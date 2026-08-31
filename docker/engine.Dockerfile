# pips execution plant — the Rust engine. Loads signed bundles read-only and trades them
# under an independent risk layer. DRY_RUN by default: the `live` feature flag plus
# PIPS_LIVE=1 plus `i_understand_live_trading: true` are all required (rule 8), and none
# of them is set here or reachable by the autonomous loop.
#
# Stub at M0.5 — the engine itself lands at M21–M23, test-first (§7.1).

FROM rust:1.90-slim-bookworm AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config \
    && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml Cargo.lock* ./
COPY rust ./rust
RUN cargo build --release --workspace

FROM debian:bookworm-slim AS engine
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --uid 10001 pips
COPY --from=builder /build/target/release/ /usr/local/lib/pips/
USER pips
ENV PIPS_DATA_ROOT=/srv/pips
CMD ["/bin/sh", "-c", "echo 'pips engine: stub until M23 — DRY_RUN only'; sleep infinity"]
