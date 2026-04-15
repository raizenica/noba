# Dockerfile — NOBA Command Center
#
# Multi-stage build is intentionally not used here: the Vue frontend is
# pre-built and committed to static/dist/, so there is no npm/node step.
FROM python:3.14-slim

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

LABEL org.opencontainers.image.title="NOBA Command Center"
LABEL org.opencontainers.image.description="System monitoring and automation dashboard"
LABEL org.opencontainers.image.source="https://github.com/raizenica/noba-ce"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl jq lm-sensors iproute2 && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    'fastapi>=0.110.0' 'uvicorn[standard]>=0.27.1' 'psutil>=5.9.8' \
    'pyyaml>=6.0' 'httpx>=0.27' 'websocket-client>=1.7' 'cryptography>=41.0' \
    'python-multipart>=0.0.9' 'lxml>=5.0' 'defusedxml>=0.7'

WORKDIR /app

RUN useradd --create-home --shell /bin/bash noba

# Copy application files (modular structure)
COPY share/noba-web/server.py /app/server.py
COPY share/noba-web/server/ /app/server/
COPY share/noba-web/static/ /app/static/

# Copy agent zipapp (served via /api/agent/update endpoint)
COPY share/noba-agent.pyz /noba-agent.pyz

# Create data directories and symlink config/data paths into volumes.
# NOBA writes to ~/.config/noba-web/ (users, auth) and ~/.local/share/ (DB).
# With HOME=/app, these become /app/.config/noba-web/ and /app/.local/share/.
# We symlink them into /app/config and /app/data for volume persistence.
RUN mkdir -p /app/config /app/data \
             /app/.config /app/.local && \
    ln -s /app/config /app/.config/noba-web && \
    ln -s /app/config /app/.config/noba && \
    ln -s /app/data   /app/.local/share

# Declare volumes for persistence
VOLUME ["/app/config", "/app/data"]

RUN chown -R noba:noba /app
USER noba

# Environment
ENV PORT=8080
ENV HOST=0.0.0.0
ENV NOBA_CONFIG=/app/config/config.yaml
ENV HOME=/app

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -sf http://localhost:8080/api/status/public || exit 1

EXPOSE 8080

CMD ["python3", "-u", "/app/server.py"]
