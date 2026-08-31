//! Broker-agnostic order plane traits: intents in, execution events out.
//!
//! Contract: `[C-OMS-01]` — owned by milestone M23.
//!
//! Scaffold only (M0). Implementation lands under M23 test-first
//! (constitution rule 16): the failing test comes before the code.
#![forbid(unsafe_code)]
