# DATA_DICTIONARY.md

Field-level semantics per data zone. Grows slowly; shard per zone if it passes ~300 lines.

## Conventions that apply everywhere

- **Prices are integer paise** (`*_paise`), quantities integer shares. No float crosses a
  schema boundary `[C-NUM-01]`.
- **Timestamps are `TimestampNs`** — nanoseconds since the Unix epoch, UTC. A naive
  wall-clock string in a config or fixture is interpreted as **IST**, never machine-local.
- **Bars are labelled by close time** `[C-BAR-01]`; a bar is measurable at or after its
  label. A trade exactly on an interior boundary belongs to the bar *ending* there.
- **Bitemporal PIT tables** carry `valid_from / valid_to / known_from / known_to`.
  Corrections create a new knowledge-time version; nothing is ever overwritten.

## fixtures/bars/*.json (seeded smoke fixtures, M0)

| Field | Type | Meaning |
|---|---|---|
| `symbol` | str | Synthetic instrument id (`SMOKEA`, `SMOKEB`) |
| `close_ts_ns` | int | Bar **close** label, nanoseconds since epoch |
| `open_paise` | int | First trade price in the bar |
| `high_paise` | int | Maximum trade price in the bar |
| `low_paise` | int | Minimum trade price in the bar |
| `close_paise` | int | Last trade price in the bar |
| `volume` | int | Shares traded in the bar |

`fixtures/bars/MANIFEST.json` carries the generator `spec`, its `spec_hash`, a per-file
content hash and a `manifest_hash` root — this is what `make determinism` compares.

## bronze / silver / gold / quarantine

Populated from M4 onward; documented as each zone lands.
