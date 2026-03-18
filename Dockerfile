# Dockerfile
FROM python:3.11-alpine

# Install runtime dependencies and tools commonly used for custom actions
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    speedtest-cli \
    tzdata \
    shadow   # for useradd

# Create a non‑root user for better security
RUN groupadd -r noba && useradd -r -g noba -d /app -s /bin/bash -m noba

WORKDIR /app

# Copy application files
COPY share/noba-web/server.py /app/server.py
COPY share/noba-web/index.html /app/index.html
COPY share/noba-web/static/ /app/static/

# Set ownership and permissions
RUN chown -R noba:noba /app && \
    chmod +x /app/server.py

# Switch to non‑root user
USER noba

# Environment variables (can be overridden at runtime)
ENV PORT=8080
ENV HOST=0.0.0.0
ENV NOBA_CONFIG=/app/config/config.yaml

# Expose both HTTP and HTTPS ports for flexibility
EXPOSE 8080 8443

# Use exec form for clean signal handling
CMD ["python3", "-u", "/app/server.py"]
