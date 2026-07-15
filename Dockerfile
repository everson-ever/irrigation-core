FROM node:20-bookworm-slim

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENV NODE_RED_HOME=/node-red-data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && npm install -g --omit=dev node-red@3 \
    && mkdir -p /node-red-data \
    && cd /node-red-data \
    && npm init -y \
    && npm install --omit=dev node-red-dashboard@3 \
    && chmod -R a+rwX /node-red-data

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e '.[dev]'

COPY data ./data
COPY node-red ./node-red

EXPOSE 1880

CMD ["irrigation", "--help"]
