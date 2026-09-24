# Delivery plan

Status: all implementation milestones are pending. This repository currently contains a design package only.

## M0 — Integration and market feasibility (1–2 days)

- Verify installed versions and public-client APIs against current official docs; lock dependencies.
- Verify TypeSafe pricing, quota, actual model ID and input/output accounting with an authorized test key.
- Identify suitable event groups and primary sources. If too few qualify, report the shortage before expanding scope.
- Capture one full book plus incremental updates and reconstruct against a later snapshot.
- Validate fee parameters, share precision, market status and settlement payout fields. Unknown fields must block simulation.

## M1 — Durable recording (1–2 days)

- Implement watchlist, allowlisted source adapters, immutable versions and first-seen timestamps.
- SQLite WAL single writer plus compressed raw-event archives; persistent checkpoints.
- Recovery, heartbeat, gap detection, bounded queues and cost/request limits.
- Run 24-hour smoke capture; inspect coverage and disk growth before selecting retention limits.

## M2 — Decisions and execution simulation (2–3 days)

- Implement versioned A/B/C strategies, fixed candidate and exit rules.
- Decimal ladder fills, fee rounding, price protection, capital reservations, partial fills and expiry.
- Separate account per experimental arm and stress scenario; no double counting across accounts.
- Replay stored model answers without calling an API. New-model evaluation is a new experiment.

## M3 — Reports and release (1 day, may overlap)

- Daily Markdown/HTML/CSV; candidate funnel, latency, execution, PnL, unknown valuations and cost.
- Synthetic demo without credentials; document implemented commands only after they work.
- CI: Ruff and pytest, no network or secrets required. Add dependency lock and reproducible runtime.
- Verify tracked files, select license and publication settings, publish repository when destination is established.

## Required meaningful tests

1. Changing a future message cannot alter any earlier decision or fill.
2. Multi-level partial fills respect limits and total reserved capital including fees.
3. Nonlinear per-level fees and rounding match verified official examples.
4. Restart after transaction boundaries produces no duplicated orders, fills or balances.
5. Stale/disconnected books cannot fill; recovery requires a valid snapshot.
6. Duplicated evidence cannot trigger duplicate positions; revisions remain visible.
7. Exits without depth retain inventory; no fictitious cash release.
8. 1/0 and fractional payout scenarios preserve accounting invariants.
9. Malformed model responses, prompt-injection-like source text and unknown references fail closed.
10. A golden synthetic replay has identical output hashes and ledger totals across two runs.

No tests need to be created for this documentation-only delivery. These are implementation acceptance criteria.

## Research checkpoint

Start 7–14-day observation only after instrumentation is healthy. Freeze prompts and configuration. Report insufficient sample size honestly; no automatic live-trading gate. A later live-execution stage requires a separate scope and explicit activation.
