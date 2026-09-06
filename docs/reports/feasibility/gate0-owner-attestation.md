# [G-AUTH-0] — owner attestation of ICICI's confirmation

**Recorded:** 2026-08-31 · **Attested by:** Prateek Rastogi (project owner) · **Kind:** verbal

## What is attested

The owner states that **ICICI has confirmed that Breeze may be used in the manner pips uses
it**: as a read-only market-data source for signals that the same customer then executes in
their own account at a different broker, with no redistribution of Breeze data and no
third-party access.

This is the exact question set out in `ops/runbooks/authority.md`, and it is the question
`[G-AUTH-0]` exists to answer.

## What this artifact is, and is not

It **is** the owner's signed-off record of a verbal confirmation, accepted by the owner as
sufficient to clear GATE-0.

It **is not** a written clarification from ICICI. §2.1 asks for written confirmation, and the
difference is deliberate: a written reply is an artifact that can be produced later if the
position is ever questioned, and a verbal one is not. `AuthorityRecord.caveats()` surfaces
that limitation every time the gate is checked, and `pips authority check` prints it — so no
one reaches the live path believing this rests on a letter.

## Detail to complete (owner)

These fields were not captured at the time. Filling them materially strengthens the record,
because an attestation with a name, a channel and a date can be corroborated and one without
cannot:

- **Channel used:** _(Breeze API support desk / ICICI Direct helpline / portal chat / other)_
- **Person or reference:** _(name, ticket or call reference, if any)_
- **Date of the confirmation:** _(as distinct from the date this note was recorded)_
- **Their words, as closely as recalled:** _(one or two sentences)_

## Recommended follow-up

Send the letter in `ops/runbooks/authority.md` anyway, citing the verbal confirmation and
asking for the same answer in writing. It costs one email, it is not blocking, and it upgrades
`evidence_kind` from `VERBAL_ATTESTATION` to `WRITTEN` — which is what §2.1 actually asks for
and what a compliance review would expect to see. Nothing before P6 depends on it, so there is
time to do this properly.

## Waiver, 2026-09-06

The owner waived the requirement that ICICI's written reply be filed in this repository
(message to the agent, 2026-09-06: "waiver gate 0 written reply from icici"). GATE-0 stands on
the owner's attestation above and the WRITTEN classification of 2026-09-05. No further document
is awaited. Recorded verbatim so the position is auditable rather than silent.
