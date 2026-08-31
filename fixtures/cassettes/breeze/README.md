# Breeze cassettes

`session_open_slice.json` and `widened_window_edges.json` are **recorded verbatim** from
`get_historical_data_v2` on 2026-08-28 (RELIND, NSE cash), captured from arb-vm. The widened
case is trimmed in row count but keeps the boundary rows on both ends — the 09:07 pre-open and
15:31 post-close prints — because those are exactly what the session clip must drop.

`SYNTHESIZED_rate_limited.json` is **not recorded**, and its filename says so. Obtaining a real
one means deliberately breaching a rate limit on a live account, which is not worth doing for a
fixture whose shape SAL-0003 already documents: the rejection arrives in the JSON body as
`{"Status": 5, "Error": "Limit exceed..."}`, never as HTTP 429. If that shape ever changes this
fixture is wrong and the tests built on it are testing a fiction — so it is labelled loudly
rather than mixed in with the real ones.

CI never makes live calls (§6 M4). These files are how the fetch path is tested.
