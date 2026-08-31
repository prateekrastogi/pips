# pips research plant — the image that `make ci` runs inside, on the laptop, in Jenkins
# and on arb-vm. Dev image == prod image (§2.2): "works on my machine" is structurally
# impossible when there is only one machine.
#
# Carries a Rust toolchain because the PyO3 math-kernel binding (ADR-0002 / [C-PAR-01])
# is built in this environment, and because `make ci` runs `cargo test` in the same ladder.

FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CARGO_HOME=/usr/local/cargo \
    RUSTUP_HOME=/usr/local/rustup \
    PATH=/usr/local/cargo/bin:/app/.venv/bin:$PATH \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl git make pandoc pkg-config \
    && rm -rf /var/lib/apt/lists/*

# --- Rust toolchain (pinned by rust-toolchain.toml at build time) -------------------
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --profile minimal --default-toolchain 1.90.0 --component clippy rustfmt \
    && chmod -R a+w "$CARGO_HOME" "$RUSTUP_HOME"

# --- uv ----------------------------------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

# --- Dependency layer: cached until the manifests change ----------------------------
FROM base AS deps
COPY pyproject.toml uv.lock* .python-version ./
RUN uv sync --group dev --no-install-project

# --- Application layer --------------------------------------------------------------
FROM deps AS research
COPY . .
RUN uv sync --group dev --frozen || uv sync --group dev
CMD ["make", "ci"]
