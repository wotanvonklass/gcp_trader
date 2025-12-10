# Multi-stage build for all Rust proxy services
# Produces tiny images (~10-20 MB each)

FROM rust:1.83-slim-bookworm AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Build firehose-proxy
COPY polygon_proxy/firehose-proxy ./firehose-proxy
WORKDIR /build/firehose-proxy
RUN cargo build --release

# Build ms-aggregator
WORKDIR /build
COPY polygon_proxy/ms-aggregator ./ms-aggregator
WORKDIR /build/ms-aggregator
RUN cargo build --release

# Build filtered-proxy
WORKDIR /build
COPY polygon_proxy/filtered-proxy ./filtered-proxy
WORKDIR /build/filtered-proxy
RUN cargo build --release

# Build alpaca-trade-updates-proxy
WORKDIR /build
COPY alpaca_trade_updates_proxy ./alpaca-trade-proxy
WORKDIR /build/alpaca-trade-proxy
RUN cargo build --release

# ---------------------------------------------------
# Minimal runtime images
# ---------------------------------------------------

FROM debian:bookworm-slim AS firehose-proxy
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/firehose-proxy/target/release/firehose_proxy /usr/local/bin/
ENV RUST_LOG=info
EXPOSE 8767
CMD ["firehose_proxy"]

FROM debian:bookworm-slim AS ms-aggregator
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/ms-aggregator/target/release/ms_aggregator /usr/local/bin/
ENV RUST_LOG=info
EXPOSE 8768
CMD ["ms_aggregator"]

FROM debian:bookworm-slim AS filtered-proxy
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/filtered-proxy/target/release/filtered_proxy /usr/local/bin/
ENV RUST_LOG=info
EXPOSE 8765
CMD ["filtered_proxy"]

FROM debian:bookworm-slim AS alpaca-trade-proxy
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/alpaca-trade-proxy/target/release/trade-updates-proxy /usr/local/bin/
ENV RUST_LOG=info
EXPOSE 8099
CMD ["trade-updates-proxy"]
