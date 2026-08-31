# Breeze security master — what the vendor offers, and what it does not

**Probed:** 2026-08-31, on arb-vm, against the live Breeze SDK. Shapes only; rule 14 keeps
market data on the VM.

## The question

M6's instrument master is keyed on **ISIN**, because a symbol is a label the exchange lends
out and a token is a broker handle — neither is a durable identity. Populating it needs, per
security: ISIN, exchange token, symbol, series, lot size, tick size. Which Breeze surface
supplies those?

## What the SDK exposes

`BreezeConnect` has 49 public methods; five touch instrument identity:

| method | shape |
|---|---|
| `get_names(exchange_code, stock_code)` | one security, per-call |
| `get_stock_script_list()` | downloads and parses the whole security master |
| `get_stock_token_value(...)` | quote subscription tokens, not identity |
| `get_contract_name(...)` | derivatives contract-name builder |
| `get_data_from_stock_token_value(...)` | inverse of the above |

### `get_names` — insufficient, and this is the finding

Probed live for `NSE/RELIND`. It returns exactly seven fields:

```
company name · exchange_code · exchange_stock_code
isec_stock_code · isec_token · isec_token_level1 · isec_token_level2
```

**No ISIN. No series. No lot size. No tick size.** It answers "which token is this symbol",
which is half of M6's *token/symbol change history* — and none of the identity the master is
keyed on. It also costs one API call per security, so a 2000-name universe is 2000 calls
against the 100k/day budget for data that would still be incomplete.

### `get_stock_script_list` — the real source, and it discards most of it

Reading its implementation: it fetches
`https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip`, opens the `.txt`
member per exchange (`NSE`, `BSE`, `NFO`, `BFO`, `MCX`, `NDX`), and builds two dictionaries —
`{stock_code: token}` and `{token: [stock_code, company_name]}`.

So the SDK's *parsed output* is no better than `get_names`: it keeps the code, the token and
the company name, and throws the rest of each row away. **The zip has the columns; the SDK's
parser does not surface them.** Reading the archive directly is therefore not a workaround —
it is the only way to get ISIN, series, lot and tick from this vendor.

## The archive, measured

`HEAD https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip`

```
status         200
Content-Type   application/zip
Content-Length 2,895,936  (2.9 MB)
Last-Modified  Mon, 31 Aug 2026 01:52:24 GMT
```

Refreshed daily, which suits a daily bitemporal snapshot: each day's fetch is one
`known_from`, and a symbol or token that moves shows up as a new version rather than an
overwrite.

## Conclusion

The per-symbol API cannot populate the master. The archive can, but only if pips parses the
raw `.txt` rather than using the SDK's lossy loader. That is a **file download to the VM
(2.9 MB, ICICI direct link)** and is being put to the owner rather than assumed: it is a
different endpoint from the Breeze API covered by the GATE-0 attestation, even though it is
the same vendor and the same read-only data plane.

Nothing in this report required the download; the SDK's source and one `HEAD` were enough.
