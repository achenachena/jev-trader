# Jev Trader

A small, reproducible **paper-trading research system** for Jev × Polymarket.

**Status: design only. No runnable trading implementation, live performance claims, wallet integration, or deployed service yet.**

The first experiment asks whether Jev can interpret newly received primary-source evidence and identify opportunities that remain executable after processing latency, fees, and order-book depth are accounted for. Profitability is unproven.

## V1 scope

- Manually reviewed watchlist of 10–20 event groups, starting with product release / public availability announcements where suitable markets and primary sources exist.
- Public market metadata and order-book recording; allowlisted RSS, JSON and static HTML sources.
- Simple-rule baseline, structured Jev evidence judgments, and an exploratory Jev probability arm.
- Taker-only hypothetical orders, bounded capital, partial fills, realistic exits and immutable experiment versions.
- Deterministic replay using recorded model responses; daily Markdown/HTML/CSV reports.
- No real orders, private keys, autonomous web browsing, maker fills, leverage or guaranteed returns.

## Documentation

- [最终 V1 方案（中文）](docs/V1_SPEC.zh-CN.md)
- [Delivery milestones and acceptance criteria](docs/DELIVERY.md)
- [Official sources and unresolved integration checks](docs/SOURCES.md)

## Proposed stack

Python 3.12, uv, asyncio, Pydantic, HTTPX, official public Polymarket and TypeSafe adapters, SQLite WAL, compressed JSONL archives, Jinja2 reports, pytest and Ruff. Dependencies and exact versions will be verified and locked during implementation.

There are no installation or execution commands yet: the modules and CLI described in the specification are planned, not implemented.

## GitHub publication

Public repository: [achenachena/jev-trader](https://github.com/achenachena/jev-trader). The initial release contains a specification package only. Publish only source, documentation and synthetic test fixtures; keep credentials, captured articles, database files, logs and real experiment archives out of Git. Do not present simulated returns as live results. A license has not yet been selected; public visibility alone does not grant an open-source license.

The project is independent and is not endorsed by TypeSafe AI or Polymarket.
