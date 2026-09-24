# Jev Trader

A small Polymarket bot project: automatic paper entries and exits today, a separately validated real execution adapter in a future phase.

**Status: the paper bot is implemented. Offline ledger/execution tests, synthetic round trips, live public-data checks, a Jev API smoke call and a short forward-data run passed. No live-money trading exists. No profitable strategy or 24-hour reliability claim has been established.**

Start with [current paper V1, strategy, technical design and limits (中文)](docs/PAPER_V1.zh-CN.md).

A read-only **live dashboard** is available: equity, cash, positions, decisions and evidence,
orders/fills, source health and a 24-hour equity chart. Native ledger change notifications
feed SSE; the browser does not poll. [Dashboard and Railway deployment guide (中文)](docs/DASHBOARD_DEPLOY.zh-CN.md).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dashboard.txt
.venv/bin/python -m dashboard  # view existing worker at http://127.0.0.1:8080
```

Dashboard-only startup does not start another bot or make model calls. For a new hosted
instance the Docker entrypoint supervises both services; it requires a dashboard password,
HTTPS proxy and persistent volume. No cloud service has been provisioned yet.

The earlier reading experiments remain useful background, not a gate preventing paper research:
[second-round conclusions](research/pilot-002/RESULTS.zh-CN.md),
[frozen comparison protocol](research/pilot-002/PROTOCOL.zh-CN.md), and
[first-run results](research/pilot-001/RESULTS.zh-CN.md).

## Current V1

1. Poll Apple and Take-Two official feeds against eight reviewed contracts in four risk groups.
2. Compare separate $1,000 virtual accounts: Jev directional classification and simple text rules.
3. Automatically simulate taker entries and exits from fresh public order books, with dynamic fees, delay, partial fills and persistent holdings.
4. Record candidates, rejections, fees, PnL lower bounds and coverage errors. Real execution is a future phase.

Python 3.10+ on macOS/Linux; standard library only. Configure `AI_GATEWAY_API_KEY` in local `.env` or the environment, then:

```sh
python3 -m jev_trader doctor
python3 -m jev_trader run
```

The worker runs until interrupted. Read `reports/paper/latest.md` / `latest.json`, or run
`python3 -m jev_trader report`. Data is in `data/paper.sqlite`; all are ignored by Git.
The first feed read creates a baseline and never trades historical entries. No wallet
or Polymarket credential is needed. Configuration changes require a new database.

```sh
.venv/bin/python -m unittest discover -s tests -v
python3 -m jev_trader demo --output reports/my-demo
```

The demo uses synthetic prices and mocked Jev answers; its PnL is not strategy evidence.
Current limitations include RSS summaries rather than full articles, polling rather
than low-latency streaming, a static reviewed watchlist, and no automatic settlement
or redemption. Closed/unpriceable positions remain visible rather than receiving
invented payouts. Dockerfile is provided for a future always-on host; deployment
has not been tested. A sleeping laptop does not provide continuous coverage.

The original reading pilot has **10 cases across 4 event groups**, not ten independent trading signals. Labels are provisional and assistant-authored. Historical memory, researcher paraphrasing and hindsight can bias results. This is not a forecasting benchmark or evidence of profitability.

## Start here

- [首批 10 个案例、来源和判断依据](research/pilot-001/README.zh-CN.md)
- [当前 V1 范围（中文）](docs/V1_FIT_CHECK.zh-CN.md)
- [Machine-readable corpus](research/pilot-001/corpus.json)
- [Provisional labels — keep out of model inputs](research/pilot-001/labels.provisional.json)

Run with Python 3.10+ (standard library only; no credentials or network):

```sh
python3 scripts/pilot_dataset.py
python3 scripts/pilot_dataset.py --export reports/pilot-inputs.json
```

The export uses an allowlist and excludes answers, rationales, market URLs and observed outcomes. It contains English researcher paraphrases; original URLs and short quotations are retained separately for auditing. It does not call a model or place orders.

## Run Jev through Vercel AI Gateway

Put `AI_GATEWAY_API_KEY=your-key` in the local `.env` (ignored by Git), or set
the environment variable. The runner reads only this setting; it does not execute
the file. Environment variables take precedence. Never publish credentials.

```sh
chmod 600 .env
python3 scripts/evaluate_jev.py --smoke
python3 scripts/evaluate_jev.py --run
```

Run the ten cases only after the synthetic smoke test succeeds. Gateway may
require a valid credit card on the account even to unlock free credits. Account
setup and billing are managed in the Vercel dashboard.

The Python standard-library runner uses the official
[evaluation HTTP API](https://vercel.com/docs/ai-gateway/modalities/evaluation)
with `typesafe-ai/jev`. Jev selects one of four evidence-sufficiency labels;
it does not generate a written rationale. A run makes at most ten sequential
requests, with a 30-second timeout per request, no automatic retries and no
fallback model. Failed runs stop immediately and preserve completed records.
Rerunning starts a new run and may incur new charges.

Timestamped `reports/jev-*/` folders (ignored by Git) retain the exact label-free
requests, request hashes, responses, elapsed wall time, token/cost metadata and
an agreement summary. Missing billing metadata stays unknown. Latency includes
network connection overhead, not just model inference. Option probabilities
are not calibrated market-outcome probabilities. Labels remain provisional;
the always-INSUFFICIENT baseline gets 6/10, so raw agreement alone is inadequate.

## Deferred design

The earlier, larger design contains unimplemented features. The current implemented scope is [PAPER_V1](docs/PAPER_V1.zh-CN.md):

- [Deferred shadow-trading specification](docs/V1_SPEC.zh-CN.md)
- [Deferred delivery milestones](docs/DELIVERY.md)
- [Official integration sources](docs/SOURCES.md)

## Publication

Public repository: [achenachena/jev-trader](https://github.com/achenachena/jev-trader).

Do not commit credentials, full captured articles, private databases or logs. Published research includes links, brief excerpts and attributed summaries rather than third-party full text. No software license has been selected; public visibility alone does not grant an open-source license.

This independent project is not endorsed by TypeSafe AI or Polymarket.
