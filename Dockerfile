FROM python:3.11-alpine

# Speedtest CLI Version
ARG SPEEDTEST_VERSION=2.1.3

# Create user first for better layer caching
RUN adduser -D speedtest

# Install system dependencies in a single layer
RUN apk add --no-cache \
    ca-certificates \
    curl \
    wget \
    && rm -rf /var/cache/apk/*

WORKDIR /app

# Copy and install requirements first for better layer caching
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Speedtest CLI
RUN ARCHITECTURE=$(uname -m) && \
    if [ "$ARCHITECTURE" = 'armv7l' ]; then ARCHITECTURE="armhf"; fi && \
    wget -nv -O /tmp/speedtest.tgz "https://install.speedtest.net/app/cli/ookla-speedtest-${SPEEDTEST_VERSION}-linux-${ARCHITECTURE}.tgz" && \
    tar zxvf /tmp/speedtest.tgz -C /tmp && \
    cp /tmp/speedtest /usr/local/bin && \
    chmod +x /usr/local/bin/speedtest && \
    rm -rf /tmp/*

# Copy application code
COPY src/. .
RUN chown -R speedtest:speedtest /app

USER speedtest

# Add metadata
LABEL org.opencontainers.image.source="https://github.com/YourUsername/speedtest-exporter"
LABEL org.opencontainers.image.description="Prometheus Exporter for Speedtest"
LABEL org.opencontainers.image.licenses="MIT"

# Expose port
EXPOSE 9798

# More efficient healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget -q -O - http://localhost:${SPEEDTEST_PORT:=9798}/ || exit 1

# Use exec form of CMD
CMD ["python", "-u", "exporter.py"]
