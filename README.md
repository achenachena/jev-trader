# Jev Trader

A small research project testing whether Jev can interpret evidence for Polymarket contracts.

**Status: a 10-case pilot dataset, offline exporter and Vercel Gateway Jev runner are available. Connectivity was attempted but blocked by Gateway account verification (credit card required). No Jev pilot results, live observation, paper PnL or real trading are available.**

## Current V1

1. Source-check a small set of market rules and official evidence.
2. Compare deterministic rules, Jev and a general model on evidence sufficiency (pending).
3. Only if useful, observe 3–5 active events for executable opportunities (pending).

The pilot has **10 cases across 4 event groups**, not ten independent trading signals. Labels are provisional and assistant-authored. Historical memory, researcher paraphrasing and hindsight can bias results. This is not a forecasting benchmark or evidence of profitability.

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

The earlier, larger paper-trading plan is **not the current implementation scope**:

- [Deferred shadow-trading specification](docs/V1_SPEC.zh-CN.md)
- [Deferred delivery milestones](docs/DELIVERY.md)
- [Official integration sources](docs/SOURCES.md)

## Publication

Public repository: [achenachena/jev-trader](https://github.com/achenachena/jev-trader).

Do not commit credentials, full captured articles, private databases or logs. Published research includes links, brief excerpts and attributed summaries rather than third-party full text. No software license has been selected; public visibility alone does not grant an open-source license.

This independent project is not endorsed by TypeSafe AI or Polymarket.
