# Dockerfile — NOBA Command Center
FROM python:3.13-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl jq lm-sensors iproute2 && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi 'uvicorn[standard]' psutil pyyaml httpx

# Create non-root user
RUN groupadd -r noba && useradd -r -g noba -d /app -s /bin/bash -m noba

WORKDIR /app

# Copy application files (modular structure)
COPY share/noba-web/server.py /app/server.py
COPY share/noba-web/server/ /app/server/
COPY share/noba-web/static/ /app/static/

# Copy agent script (served via /api/agent/update endpoint)
COPY share/noba-agent/agent.py /app/noba-agent/agent.py

# Create data directories
RUN mkdir -p /app/config /app/data && \
    chown -R noba:noba /app

USER noba

# Environment
ENV PORT=8080
ENV HOST=0.0.0.0
ENV NOBA_CONFIG=/app/config/config.yaml

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -sf http://localhost:8080/api/status/public || exit 1

EXPOSE 8080

CMD ["python3", "-u", "/app/server.py"]
