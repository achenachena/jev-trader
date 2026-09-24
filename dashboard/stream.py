"""One native filesystem observer and one consistent snapshot producer for all viewers.

SSE clients receive full bounded snapshots, not fragile deltas: reconnect always
resyncs from the ledger. OS notifications are hints, never the source of truth.
"""
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time
import uuid

from watchdog.events import FileSystemEventHandler
if sys.platform == 'darwin':
    # FSEvents can defer notifications for a continuously open WAL writer.
    from watchdog.observers.kqueue import KqueueObserver as Observer
else:
    from watchdog.observers import Observer
from .data import snapshot


class StateHub:
    def __init__(self,path,reconcile_seconds=15):
        self.path=Path(path).resolve()
        self.interval=reconcile_seconds
        self.condition=threading.Condition()
        self.wake=threading.Event()
        self.stopped=threading.Event()
        self.sequence=0
        self.epoch=uuid.uuid4().hex[:12]
        self.latest=None
        self.observer=Observer()
        hub=self
        targets={str(self.path),str(self.path)+'-wal',str(self.path)+'-journal'}
        class ChangeHandler(FileSystemEventHandler):
            def on_any_event(self,event):
                # Ignore access/open/close reads to avoid a feedback loop.
                if event.event_type in ('modified','created','deleted','moved') and not event.is_directory:
                    if event.src_path in targets or getattr(event,'dest_path',None) in targets:
                        hub.wake.set()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.observer.schedule(ChangeHandler(),str(self.path.parent),recursive=False)
        self.thread=threading.Thread(target=self.run,name='ledger-state-producer',daemon=True)

    def start(self):
        self.observer.start()
        self.wake.set()
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            self.wake.wait(self.interval)
            self.wake.clear()
            # Coalesce a transaction's burst of WAL writes; no slow-client queue.
            if self.stopped.wait(.1): break
            try:
                state=snapshot(self.path)
                state['stream']={'transport':'sse','observer':type(self.observer).__name__}
                payload=json.dumps(state,ensure_ascii=False,allow_nan=False)
                event='state'
            except (sqlite3.Error,KeyError,ValueError):
                payload=json.dumps({'error':'Ledger unavailable or initializing','server_time':time.time()})
                event='unavailable'
            with self.condition:
                self.sequence+=1
                self.latest=(f'{self.epoch}:{self.sequence}',event,payload)
                self.condition.notify_all()

    def next(self,previous=None,timeout=15):
        with self.condition:
            self.condition.wait_for(lambda:self.stopped.is_set() or (self.latest and self.latest[0]!=previous),timeout)
            return self.latest if self.latest and self.latest[0]!=previous else None

    def close(self):
        self.stopped.set(); self.wake.set()
        with self.condition: self.condition.notify_all()
        self.observer.stop(); self.observer.join(timeout=3)
        self.thread.join(timeout=5)
