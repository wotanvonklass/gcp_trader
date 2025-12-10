# Python image for NautilusTrader news trading system
# NOTE: NautilusTrader is installed from private fork at /opt/nautilus_trader_private
#       For Docker, either:
#       1. Build NautilusTrader wheel and COPY it
#       2. Mount the source at runtime
#       3. Use pre-built nautilus_trader from PyPI (public version)

FROM python:3.11-slim-bookworm

# Install build dependencies for NautilusTrader
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Rust (required for NautilusTrader build)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Install Python dependencies first
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install NautilusTrader from PyPI (public version)
# For private fork: build wheel separately and COPY it here
RUN pip install --no-cache-dir nautilus_trader

# Copy application code
COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "run_news_trader.py"]
