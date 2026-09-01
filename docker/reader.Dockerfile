# pips breeze-reader — the read-only market-data plane. Holds ONLY Breeze credentials and
# has no order-plane code linked in (rule 7: two planes, two credentials, two processes).
# Emits canonical MarketEvents over a Unix-domain socket to the engine.
#
# Stub at M0.5 — the reader lands at M4/M21, test-first (§7.1).

FROM rust:1.90-slim-bookworm AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config \
    && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml Cargo.lock* ./
COPY rust ./rust
RUN cargo build --release --workspace

FROM debian:bookworm-slim AS reader
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10000 pips \\
    && useradd --system --create-home --uid 10002 --gid 10000 pips
COPY --from=builder /build/target/release/ /usr/local/lib/pips/
USER pips
ENV PIPS_DATA_ROOT=/srv/pips
CMD ["/bin/sh", "-c", "echo 'pips breeze-reader: stub until M4 — read-only data plane'; sleep infinity"]
