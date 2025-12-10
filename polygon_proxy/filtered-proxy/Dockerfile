# Build stage
FROM rust:1.83-slim-bookworm AS builder
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN cargo build --release

# Runtime stage (~25 MB)
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/release/polygon_filtered_proxy /usr/local/bin/
ENV RUST_LOG=info
EXPOSE 8765
CMD ["polygon_filtered_proxy"]
