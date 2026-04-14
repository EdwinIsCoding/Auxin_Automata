FROM python:3.11-slim

# pybullet needs build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY twin/ /app/twin/
COPY sdk/ /app/sdk/

RUN uv pip install --system \
    pybullet \
    numpy \
    anyio \
    websockets \
    imageio \
    "imageio-ffmpeg" \
    pillow && \
    uv pip install --system -e /app/sdk --no-deps && \
    uv pip install --system -e /app/twin --no-deps

EXPOSE 8765

CMD ["python", "-m", "twin", "--mode", "ws"]
