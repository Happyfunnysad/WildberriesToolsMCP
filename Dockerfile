FROM python:3.12-slim

ARG XRAY_VERSION=26.3.27

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XRAY_BIN=/usr/local/bin/xray \
    XRAY_READY_FILE=/tmp/xray-ready

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
         amd64) xray_arch="64" ;; \
         arm64) xray_arch="arm64-v8a" ;; \
         *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
       esac \
    && curl -fsSL \
         "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/Xray-linux-${xray_arch}.zip" \
         -o /tmp/xray.zip \
    && mkdir -p /tmp/xray-unpack \
    && unzip -q /tmp/xray.zip -d /tmp/xray-unpack \
    && install -m 0755 /tmp/xray-unpack/xray /usr/local/bin/xray \
    && xray version \
    && rm -rf /var/lib/apt/lists/* /tmp/xray.zip /tmp/xray-unpack

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

ENTRYPOINT ["python", "scripts/supervisor.py"]
