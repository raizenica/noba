# Notifications

Configure notification channels in **Settings → Notifications** or directly in `config.yaml` under the `notifications` key.

A **Test** button sends a test notification through all configured channels at once.

## Email

Uses `msmtp` for sending. Configure `msmtp` separately with your SMTP credentials.

```yaml
notifications:
  email:
    to: "admin@example.com"
    from: "noba@yourhost.local"
    subject_prefix: "[NOBA]"
```

**Test msmtp independently:**
```bash
echo "Test" | msmtp --debug admin@example.com
```

Common issues: wrong SMTP credentials, port 587 blocked by ISP (try 465), missing `tls_trust_file`.

## Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Start a conversation with your bot, then get your `chat_id`:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```

```yaml
notifications:
  telegram:
    bot_token: "1234567890:ABCdef..."
    chat_id: "123456789"
```

## Discord

Create a Webhook in your Discord server: Channel Settings → Integrations → Webhooks → New Webhook.

```yaml
notifications:
  discord:
    webhook_url: "https://discord.com/api/webhooks/..."
```

Messages are sent as Discord embeds with severity colour coding.

## Slack

Create an Incoming Webhook for your Slack workspace: [api.slack.com/apps](https://api.slack.com/apps) → Create App → Incoming Webhooks.

```yaml
notifications:
  slack:
    webhook_url: "https://hooks.slack.com/services/..."
```

## Pushover

Sign up at [pushover.net](https://pushover.net), create an application, and note your User Key and API Token.

```yaml
notifications:
  pushover:
    user_key: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    api_token: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

Messages are sent with Pushover priority levels mapped from NOBA severity (`critical` → priority 1, `warning` → 0, `info` → -1).

## Gotify

Self-hosted push notifications. Create an app token in your Gotify server.

```yaml
notifications:
  gotify:
    url: "http://192.168.1.20:8070"
    token: "xxxxxxxxxxxxxxxxxxxx"
```

## Webhook (Generic)

Send a JSON payload to any HTTP endpoint:

```yaml
notifications:
  webhook_url: "http://n8n.local:5678/webhook/noba-alert"
```

Payload format:
```json
{
  "level": "warning",
  "title": "High CPU Usage",
  "message": "CPU usage is 92% on web-01",
  "timestamp": 1718000000,
  "metric": "cpu_percent",
  "value": 92.1
}
```

## ntfy

Self-hosted or [ntfy.sh](https://ntfy.sh) push notifications. Install the ntfy plugin from the Plugin Catalogue.

## Testing Notifications

Go to **Settings → Notifications** and click **Send Test Notification**. Check the server log for delivery results:

```bash
tail -f ~/.local/share/noba-web-server.log | grep notification
```

Or via API (admin only):
```bash
curl -H "Authorization: Bearer <token>" \
  http://localhost:8080/api/notifications/test
```
