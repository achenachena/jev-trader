"""Frozen second pilot: same state/rubric, Jev vs Ling vs regex rules."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import time
import urllib.error
import urllib.request

from evaluate_jev import ROOT, MODEL, CRITERIA, INSTRUCTIONS, call, load_key

BASE = ROOT / 'research/pilot-002'
GENERAL = 'inclusionai/ling-3.0-flash-fin-free'
RUBRIC = INSTRUCTIONS + '''
Evaluate at the supplied as_of observation time, never today's date. Evidence
is incomplete unless it explicitly states an exhaustive record. A future plan
is not a guarantee that an actual-release condition will fail. A later dated
announcement alone does not exclude an earlier announcement. An announcement
condition can already be met even when the announced event is in the future.
Distinguish official decisions from preferences, predictions and comments.'''


def rules(state):
    """Limited surface-text baseline; no IDs, labels or per-case lookup."""
    evidence = ' '.join(x['text'] for x in state['evidence']['segments'])
    option = state['market']['option']
    rule = state['market']['rule_paraphrase']
    # Narrow, explicit entity extraction, otherwise abstain.
    name = re.search(r'new pope ([A-Z][a-z]+)\s+[IVX]+', evidence)
    if name and 'papal name' in rule:
        return 'SUFFICIENT_YES' if name[1] == option else 'SUFFICIENT_NO'
    winner = re.search(r'winner is (\w+)', evidence)
    target = re.search(r'winner.*?is (\w+)', rule)
    if winner and target and 'final' in evidence.lower():
        return 'SUFFICIENT_YES' if winner[1] == target[1].rstrip('.') else 'SUFFICIENT_NO'
    return 'INSUFFICIENT'


def general_call(state, key):
    body = {'model': GENERAL, 'temperature': 0, 'max_tokens': 2048,
            'messages': [{'role': 'system', 'content': RUBRIC + '\nCategories: ' +
                          json.dumps(CRITERIA) + '\nReturn only the category name, with no explanation.'},
                         {'role': 'user', 'content': json.dumps(state)}]}
    encoded = json.dumps(body).encode()
    if len(encoded) > 20000:
        raise ValueError('Oversized request')
    req = urllib.request.Request('https://ai-gateway.vercel.sh/v1/chat/completions',
                                 data=encoded, headers={'Authorization': 'Bearer '+key,
                                                       'Content-Type': 'application/json'})
    tick = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Gateway HTTP {exc.code}; no retry') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('Network error; no retry') from None
    response = json.loads(raw.replace(key, '[REDACTED]'))
    choice = response['choices'][0]['message']['content'].strip()
    if choice not in CRITERIA:
        choice = 'INVALID_OUTPUT'
    return {'request': body, 'response': response, 'prediction': choice,
            'elapsed_seconds': time.perf_counter()-tick,
            'request_sha256': hashlib.sha256(encoded).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--resume', type=Path, help='Resume a partial run without repeating saved answers')
    args = parser.parse_args()
    inputs_bytes = (BASE/'inputs.json').read_bytes()
    cases = json.loads(inputs_bytes)
    assert len(cases) == 24 and len({x['id'] for x in cases}) == 24
    if not args.run:
        print('Validated 24 inputs; add --run to make 48 API calls, no retries.')
        return
    key = load_key()
    out = args.resume or ROOT/'reports'/('compare-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=bool(args.resume))
    manifest = {'inputs_sha256': hashlib.sha256(inputs_bytes).hexdigest(),
                'labels_sha256': hashlib.sha256((BASE/'labels.provisional.json').read_bytes()).hexdigest(),
                'runner_sha256': hashlib.sha256(__import__('pathlib').Path(__file__).read_bytes()).hexdigest(),
                'rubric': RUBRIC, 'models': [MODEL, GENERAL]}
    if args.resume:
        prior = json.loads((out/'manifest.json').read_text())
        for field in ('inputs_sha256','labels_sha256','rubric','models'):
            if prior[field] != manifest[field]:
                raise ValueError('Cannot resume a changed experiment')
        (out/'resume-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
        manifest = prior
    else:
        (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    records = []
    for case in cases:
        for model in ('jev','ling'):
            saved = out/(case['id']+'-'+model+'.json')
            if saved.exists():
                record = json.loads(saved.read_text())
            elif model == 'jev':
                record = call({'model': MODEL, 'state': json.dumps(case['state']),
                               'questions': {'sufficiency': {'type':'choice', 'instructions':RUBRIC,
                                                            'criteria':CRITERIA}}}, key)
                record['prediction'] = record['response']['answers']['sufficiency']['choice']
            else:
                # Free endpoint throttling: at most four new Ling calls/minute.
                time.sleep(16)
                record = general_call(case['state'], key)
            record.update(id=case['id'], split=case['split'], model=model)
            if not saved.exists():
                saved.write_text(json.dumps(record, indent=2)+'\n')
            records.append(record)
            print(case['id'], model, record['prediction'], flush=True)
        records.append({'id':case['id'], 'split':case['split'], 'model':'rules',
                        'prediction':rules(case['state']), 'elapsed_seconds':0})
    # Labels are used for scoring only after predictions have been saved.
    gold = {x['id']:x['label'] for x in json.loads((BASE/'labels.provisional.json').read_text())}
    rows = [{k:r[k] for k in ('id','split','model','prediction','elapsed_seconds')} for r in records]
    for row,record in zip(rows,records):
        row['label'] = gold[row['id']]
        if row['model']=='jev':
            row['probabilities'] = record['response']['answers']['sufficiency']['probabilities']
        if 'response' in record:
            row['usage'] = record['response'].get('usage')
            row['returned_model'] = record['response'].get('model')
            row['gateway_cost'] = record['response'].get('providerMetadata',{}).get('gateway',{}).get('cost')
    stats = {}
    for split in sorted({r['split'] for r in rows}):
        stats[split] = {}
        for model in ('jev','ling','rules'):
            subset = [r for r in rows if r['split']==split and r['model']==model]
            stats[split][model] = {'n':len(subset), 'agreement':sum(r['prediction']==r['label'] for r in subset),
                'false_definitive':sum(r['prediction'] in ('SUFFICIENT_YES','SUFFICIENT_NO') and r['prediction']!=r['label'] for r in subset),
                'median_seconds':statistics.median(r['elapsed_seconds'] for r in subset)}
    result = {'manifest':manifest,'stats':stats,'rows':rows}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':str(out),'stats':stats},indent=2))


if __name__ == '__main__':
    main()
