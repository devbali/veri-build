# verification-builder — F* + KaRaMeL + Emscripten toolchain
#
# Build: docker build -t verification-builder:latest .
# Use:   docker run --rm -v $(pwd):/workspace verification-builder fstar.exe /workspace/spec.fsti

FROM ubuntu:24.04 AS builder

LABEL description="Formal verification builder: F*, KaRaMeL, Emscripten"
LABEL maintainer="Veri-Build <dev@veri-build>"

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    git \
    make \
    cmake \
    gcc \
    g++ \
    patch \
    libgmp-dev \
    libssl-dev \
    python3 \
    python3-pip xz-utils unzip   \
    && rm -rf /var/lib/apt/lists/*

# ── F* + KaRaMeL ────────────────────────────────────────────────────
# PINNED: v2026.05.31 — the Veri DSL backend (printer.py) targets this
# exact version's syntax: inline Pure ret pre (fun result -> post),
# FStar.Seq.seq for arrays, b2t wrapping for bool→prop conversion.
# If you upgrade F*, update backend/fstar/printer.py to match.
RUN curl -fsSL -o /tmp/fstar.tar.gz \
    "https://github.com/FStarLang/FStar/releases/download/v2026.05.31/fstar-v2026.05.31-Linux-x86_64.tar.gz" \
    && mkdir -p /opt/fstar \
    && tar -xzf /tmp/fstar.tar.gz -C /opt/fstar --strip-components=2 \
    && ln -s /opt/fstar/bin/fstar.exe /usr/local/bin/fstar.exe \
    && ln -s /opt/fstar/bin/krml /usr/local/bin/krml \
    && rm /tmp/fstar.tar.gz

# Verify F* works
RUN fstar.exe --version

# ── Dafny ──────────────────────────────────────────────────────
# PINNED: v4.11.0 — the Veri DSL backend (dafny/printer.py) targets this
# version's syntax and type system. Update both if upgrading.
RUN curl -fsSL -o /tmp/dafny.zip \
    "https://github.com/dafny-lang/dafny/releases/download/v4.11.0/dafny-4.11.0-x64-ubuntu-22.04.zip" \
    && unzip -q /tmp/dafny.zip -d /opt/dafny \
    && chmod +x /opt/dafny/dafny/dafny \
    && ln -s /opt/dafny/dafny/dafny /usr/local/bin/dafny \
    && rm /tmp/dafny.zip

# Verify Dafny works and validate backend compatibility
RUN dafny --version

# ── Emscripten ──────────────────────────────────────────────────────
RUN curl -fsSL -o /tmp/emsdk.zip \
    "https://github.com/emscripten-core/emsdk/archive/refs/heads/main.zip" \
    && unzip -q /tmp/emsdk.zip -d /opt \
    && mv /opt/emsdk-main /opt/emsdk \
    && cd /opt/emsdk \
    && ./emsdk install latest \
    && ./emsdk activate latest \
    && echo 'source /opt/emsdk/emsdk_env.sh' >> /etc/bash.bashrc \
    && rm /tmp/emsdk.zip


# Make emcc available directly
RUN ln -sf /opt/emsdk/upstream/emscripten/emcc /usr/local/bin/emcc \
    && ln -sf /opt/emsdk/upstream/emscripten/em++ /usr/local/bin/em++

# ── LLM CLIs (use emscripten's node for npm) ─────────────────
RUN PATH=/opt/emsdk/node/22.16.0_64bit/bin:$PATH npm install -g openclaw @anthropic-ai/claude-code

# ── Final image ─────────────────────────────────────────────────────
FROM ubuntu:24.04

COPY --from=builder /opt /opt
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /opt/emsdk/node/22.16.0_64bit/lib/node_modules /usr/local/lib/node_modules

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgmp-dev \
    ca-certificates \
    libicu-dev \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# ── Install veri-build code ────────────────────────────────────────────
COPY . /opt/veri-build/
ENV PYTHONPATH=/opt/veri-build/src:/opt/veri-build/src/veri_build/dsl/src
RUN ln -s /opt/veri-build/scripts/compile_parent_subagent_runner.py /usr/local/bin/veri-build-runner

# Emscripten SDK activation
ENV EMSDK=/opt/emsdk
ENV EMSCRIPTEN_ROOT=/opt/emsdk/upstream/emscripten
ENV EMSDK_NODE=/opt/emsdk/node/22.16.0_64bit/bin/node
ENV PATH=/opt/emsdk:/opt/emsdk/upstream/emscripten:/opt/emsdk/node/22.16.0_64bit/bin:$PATH

WORKDIR /workspace
ENTRYPOINT ["/bin/bash", "-lc"]
