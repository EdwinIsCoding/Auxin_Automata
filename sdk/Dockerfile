FROM python:3.11-slim

# pybullet (used by TwinSource) requires C++ build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy sdk source
COPY sdk/ /app/sdk/
COPY twin/ /app/twin/

# Install sdk (and twin as a path dep)
RUN cd /app/sdk && uv pip install --system -e ".[default]" 2>/dev/null || \
    uv pip install --system \
        solders \
        solana \
        pydantic \
        structlog \
        anyio \
        httpx \
        google-generativeai \
        tenacity \
        aiohttp \
        prometheus-client \
        "sentry-sdk[aiohttp]" && \
    uv pip install --system -e /app/sdk --no-deps

# Install twin
RUN uv pip install --system \
    pybullet \
    numpy \
    websockets \
    imageio \
    pillow && \
    uv pip install --system -e /app/twin --no-deps

ENV AUXIN_SOURCE=twin
ENV BRIDGE_WS_PORT=8766
ENV BRIDGE_HEALTHZ_PORT=8767

EXPOSE 8766 8767 9090

CMD ["python", "/app/sdk/scripts/run_bridge.py"]
