# Predictions

NOBA's Predictions engine forecasts future resource usage using time-series analysis. It helps you anticipate capacity problems before they become incidents.

## Capacity Prediction

Navigate to **Predictions** to see forecasts for all tracked metrics.

Supported metrics:

| Metric | Description |
|--------|-------------|
| `cpu_percent` | CPU usage % |
| `mem_percent` | RAM usage % |
| `disk_percent` | Disk usage % (per mount) |
| `net_rx_bytes` | Network receive rate |
| `net_tx_bytes` | Network transmit rate |

## Forecast Method

NOBA uses **seasonal decomposition** (STL) combined with an **exponential smoothing** model to produce forecasts:

1. **Trend** — long-term direction (e.g. disk filling over weeks).
2. **Seasonality** — repeating patterns (e.g. daily CPU spikes at backup time).
3. **Residual** — unexplained variation used to estimate confidence intervals.

The model is retrained nightly using the last 30 days of history (configurable).

## Confidence Intervals

Each forecast shows three bands:

| Band | Meaning |
|------|---------|
| **Median** | Most likely value |
| **80% CI** | 80% of outcomes expected to fall within this range |
| **95% CI** | 95% of outcomes expected to fall within this range |

Wider confidence intervals indicate more volatile or less predictable metrics.

## Predicted Breach Date

For metrics with a clear upward trend (e.g. disk usage), NOBA calculates the **predicted date to threshold breach**:

> "At current growth rate, `/mnt/data` will reach 90% in approximately **18 days** (95% CI: 12–27 days)."

A warning alert is raised when the predicted breach date is within the configured horizon (default: 14 days).

Configure the horizon and thresholds in **Settings → Predictions**.

## Per-Service Health Scoring

Navigate to **Predictions → Health Scores** to see a composite health score for each monitored service.

The health score (0–100) combines:

- Recent uptime (from Monitoring)
- Response time trend (from Monitoring)
- Resource usage trend (from Predictions)
- Security finding severity (from Security)

Health scores are updated every hour.

## Prediction Alerts

Configure prediction alerts in **Automations → Alert Rules** using prediction metrics:

```
predicted_disk_days_remaining < 14
predicted_mem_percent_7d > 90
```

These alert before a breach occurs, giving you time to act.

## History Required

Accurate predictions require at least 3 days of history. The forecast confidence improves with more data. New installations show "Insufficient data" until enough history is collected.
