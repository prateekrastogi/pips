# Breeze credential probe — 2026-08-31

**Result: the credentials are well-formed but do NOT authenticate.** Recorded here rather than
retried silently, because a probe that fails and leaves no artifact is indistinguishable from
a probe that was never run.

## What was run

A read-only session check from **arb-vm**, not the laptop. That placement is not incidental:
SAL-0001 (the `intraday` Breeze donor at `be8186d`) records that *"only API calls must egress
from the whitelisted IP; the browser login can be from anywhere"*. Running the probe from a
laptop could fail for the wrong reason, or succeed from an address that will not be the one
production uses.

```
egress IP     80.225.251.163            (arb-vm — the SEBI static-IP binding, §2.2)
flow          BreezeConnect(api_key) -> generate_session(api_secret, session_token)
call          get_customer_details    (read-only; no order plane involved)
result        Exception: "Could not authenticate credentials. Please check session key."
```

## What the values look like (shape only — no value was read or logged)

| field | length | character class | notes |
|---|---|---|---|
| `BREEZE_API_KEY` | 32 | alphanumeric | plausible |
| `BREEZE_API_SECRET` | 32 | mixed | plausible |
| `BREEZE_SESSION_TOKEN` | 7 | digits | plausible; the donor notes these are *typically* 8 digits |

No stray whitespace, no quotes, nothing URL-encoded. So this is not a copy-paste mangling — the
values are shaped correctly and the server is rejecting them.

## The two likely causes, in order

1. **The session token has expired.** SAL-0001's own docstring: *"Breeze's session token is
   interactive and DAILY (expires 24h/midnight)."* A token generated before today's midnight
   is dead regardless of how correctly it was copied. This is the most probable cause and the
   cheapest to eliminate.
2. **arb-vm's egress IP is not whitelisted on the Breeze app.** The Breeze app registration
   carries an IP allow-list, and `80.225.251.163` must be on it. The error message points at
   the session key rather than the IP, which makes this the second suspect — but the two are
   easy to confuse from the client side, so it is worth confirming while regenerating.

## What the owner needs to do

1. Open the login URL for the registered app — `https://api.icicidirect.com/apiuser/login?api_key=<the key already in .env>` —
   log in, and copy the `API_Session` value from the redirect (DevTools → Network → Form Data).
2. Put it in `.env` as `BREEZE_SESSION_TOKEN` and commit (`ops/runbooks/breeze-token.md`).
3. While there, confirm `80.225.251.163` appears in the app's IP allow-list.

Then re-run this probe. It is a read-only call and costs one API request.

## What this does not block

Nothing before M4. GATE-0 authority `[G-AUTH-0]` is a separate matter and is already cleared
(on verbal evidence — see `gate0-authority.yaml`). M0-M3.5, M9-M13 have all proceeded without
live data, and the fixtures make the whole funnel runnable with zero API access by design (§4).

## Why the failure is recorded rather than fixed by retrying

A daily token will fail again tomorrow, and the useful artifact is not "it worked once" but the
procedure and the two failure modes. §6 M3 asks for probe artifacts committed under
`docs/reports/feasibility/`; this is one, and a negative result is a result.
