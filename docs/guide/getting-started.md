# Getting Started

## Requirements

- Python 3.10+ (3.11+ recommended)
- Linux (Fedora, Ubuntu, Debian, Raspberry Pi OS, TrueNAS SCALE)
- 512 MB RAM minimum, 1 GB recommended

## Bare Metal Install

```bash
git clone https://github.com/raizenica/noba-ce.git
cd noba
bash install.sh
```

The installer handles dependencies, systemd units, and initial configuration.

Grab your generated admin password:
```bash
journalctl --user -u noba-web.service | grep password
```

Open `http://localhost:8080` and log in.

## Docker Install

```bash
git clone https://github.com/raizenica/noba-ce.git
cd noba
docker compose up -d
```

```bash
docker logs noba 2>&1 | grep password
```

See [Docker Guide](./docker) for volumes, TLS, and Podman setup.

## What's Next

1. [First Login](./first-login) — change your password, explore the UI
2. [Dashboard](./dashboard) — understand the card system
3. [Remote Agents](./agents) — deploy monitoring agents to your hosts
4. [Configuration](/config/) — connect your integrations
