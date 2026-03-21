# Agent Keys

Agent keys are pre-shared secrets that authenticate remote NOBA agents with the NOBA server. Each agent uses a unique key.

## How Agent Keys Work

1. An admin generates a key in **Settings → Agent Keys**.
2. The key is written to the agent's configuration file on the remote host.
3. On every heartbeat and command request, the agent presents its key in the `X-Agent-Key` HTTP header.
4. The server validates the key, looks up the associated agent record, and processes the request.

Keys are stored hashed in the database. The plaintext key is only shown once at generation time.

## Generating a Key

1. Open **Settings → Agent Keys**.
2. Click **Generate New Key**.
3. Enter a label (e.g. the hostname the key is for).
4. Click **Create**. The key is displayed once — copy it now.

The key is a 64-character hex string (256-bit random).

## Using a Key During Agent Install

Pass the key to the install script:

```bash
curl -sf http://<noba-server>:8080/api/agents/install-script?key=<agent-key> | bash
```

Or manually write it to the agent config:

```ini
# /etc/noba-agent/agent.conf
SERVER_URL=http://192.168.1.10:8080
AGENT_KEY=<your-64-char-key>
```

Then restart the agent:
```bash
systemctl restart noba-agent
```

## Key Rotation

To rotate a key:

1. Generate a new key for the agent in **Settings → Agent Keys**.
2. Update the agent config on the remote host with the new key.
3. Restart the agent service.
4. Revoke the old key by clicking **Revoke** next to it in the key list.

The agent will be offline between the old key being revoked and the new key taking effect. Plan key rotations during a maintenance window.

## Revoking a Key

Click **Revoke** on any key in the **Settings → Agent Keys** list. Revocation is immediate — the associated agent will fail authentication on its next heartbeat and transition to `offline` status.

## Key Permissions

Keys have the same permissions as the agent they are assigned to. There is no per-key permission scoping — all agent keys grant access to the full agent API surface.

## Security Recommendations

- Generate a unique key per agent. Do not share keys between hosts.
- Rotate keys periodically (recommended: every 90 days).
- Revoke keys immediately when an agent host is decommissioned.
- Store keys in a secrets manager (e.g. Vault, Bitwarden) rather than plain text files where possible.
- Use TLS between agents and the NOBA server to protect keys in transit.
