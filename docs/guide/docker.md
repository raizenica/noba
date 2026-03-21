# Docker Setup

## docker-compose.yml

```yaml
services:
  noba:
    build: .
    container_name: noba
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - TZ=Europe/Brussels
    volumes:
      - ./data/config:/app/config
      - ./data/db:/app/data
      - ./data/certs:/app/certs:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

## Volumes

| Mount | Purpose |
|-------|---------|
| `./data/config:/app/config` | Settings, users, agent keys |
| `./data/db:/app/data` | SQLite database (metrics, history) |
| `./data/certs:/app/certs:ro` | TLS certificates (optional) |
| `/var/run/docker.sock` | Container monitoring (optional) |

## Custom Port

```yaml
ports:
  - "9090:8080"
```

## Podman

Mount the Podman socket instead:
```yaml
volumes:
  - /run/user/1000/podman/podman.sock:/var/run/docker.sock:ro
```

## TLS

Place your certificate files in `./data/certs/` and set environment variables:
```yaml
environment:
  - SSL_CERT=/app/certs/cert.pem
  - SSL_KEY=/app/certs/key.pem
```

## Health Check

The container includes a built-in health check hitting `/api/status/public`.
