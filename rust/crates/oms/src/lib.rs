//! Order state machine: monotone fills, absorbing terminal states, idempotency.
//!
//! Contract: `[C-OMS-02]` — owned by milestone M23.
//!
//! Scaffold only (M0). Implementation lands under M23 test-first
//! (constitution rule 16): the failing test comes before the code.
#![forbid(unsafe_code)]
