# Sources and verification boundaries

Checked on 2026-09-24. These are primary documentation sources, not proof of profitability. SDK behavior, pricing and market rules may change.

| Source | Relevance |
| --- | --- |
| [Polymarket Python SDK](https://docs.polymarket.com/getting-started/python) | Current official documentation identifies `polymarket-client`, `AsyncPublicClient`, public streams and Decimal-based values. |
| [Discover markets](https://docs.polymarket.com/market-data/discover-markets) | Market discovery; concrete watchlist still needs selection. |
| [Real-time data](https://docs.polymarket.com/market-data/realtime-data) | Book, price-change, tick-size and lifecycle events. |
| [Place orders](https://docs.polymarket.com/trading/place-orders) | Limits, minimum sizes, accepted versus matched states and partial execution. Read for simulation semantics; V1 does not place orders. |
| [Fees](https://docs.polymarket.com/trading/fees) | Current documented fee curve; dynamic per-market parameters remain implementation inputs. |
| [Resolution](https://docs.polymarket.com/concepts/resolution) | Disputes, payout and redemption distinction. |
| [TypeSafe Python SDK](https://docs.typesafe.ai/sdk/python) | Official async integration. |
| [Noul](https://docs.typesafe.ai/primitives/noul) | Probability output semantics; not evidence of domain calibration. |
| [Confidence](https://docs.typesafe.ai/confidence) | Confidence versus predicted outcome probability. |
| [Jev limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13) | Numeric/date reasoning limitations support deterministic arithmetic. |
| [Models](https://docs.typesafe.ai/models) | Verify pinned model availability at implementation. |

## Not yet verified in a running integration

- Exact dependency versions and runtime compatibility.
- Jev account pricing, quotas, latency distribution and actual usage charges.
- Suitable active watchlist and allowed fetch cadence for each primary source.
- Complete fee metadata, payout and order-status schema mapping in the installed SDK.
- Snapshot/incremental reconstruction and connection recovery behavior.
- Any profitable signal, calibrated forecast, executable opportunity frequency or live execution result.

Do not replace these missing measurements with search-result quotations, website percentage displays or hypothetical examples.
