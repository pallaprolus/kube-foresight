"""Alert dispatch for at-risk deployments via webhook and Slack."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from kube_foresight.models import DeploymentForecast

logger = logging.getLogger("kube_foresight.alerting")

# Track what we've already alerted on to avoid spamming
_alerted: dict[str, str] = {}  # deployment_name → last risk_level


def _build_alert_payload(forecasts: list[DeploymentForecast]) -> dict:
    """Build a generic alert payload."""
    critical = [f for f in forecasts if f.risk_level == "critical"]
    warning = [f for f in forecasts if f.risk_level == "warning"]

    deployments = []
    for fc in forecasts:
        cpu_breach = fc.cpu_forecast.days_until_request_breach
        mem_breach = fc.memory_forecast.days_until_request_breach
        deployments.append({
            "name": fc.deployment_name,
            "namespace": fc.namespace,
            "risk_level": fc.risk_level,
            "cpu_trend": fc.cpu_forecast.trend.value,
            "memory_trend": fc.memory_forecast.trend.value,
            "cpu_days_to_breach": round(cpu_breach, 1) if cpu_breach else None,
            "memory_days_to_breach": round(mem_breach, 1) if mem_breach else None,
            "summary": fc.summary,
        })

    return {
        "source": "kube-foresight",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": "critical" if critical else "warning",
        "total_at_risk": len(forecasts),
        "critical_count": len(critical),
        "warning_count": len(warning),
        "deployments": deployments,
    }


def _build_slack_blocks(forecasts: list[DeploymentForecast]) -> dict:
    """Build Slack Block Kit message."""
    critical = [f for f in forecasts if f.risk_level == "critical"]
    warning = [f for f in forecasts if f.risk_level == "warning"]

    emoji = ":rotating_light:" if critical else ":warning:"
    header = f"{emoji} kube-foresight: {len(forecasts)} deployment(s) at risk"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": (
            f"*{len(critical)} critical* | *{len(warning)} warning*"
        )}},
        {"type": "divider"},
    ]

    for fc in forecasts[:10]:  # Cap at 10 to avoid Slack limits
        risk_emoji = ":red_circle:" if fc.risk_level == "critical" else ":large_yellow_circle:"
        cpu_breach = fc.cpu_forecast.days_until_request_breach
        mem_breach = fc.memory_forecast.days_until_request_breach

        breach_parts = []
        if cpu_breach is not None:
            breach_parts.append(f"CPU: {cpu_breach:.0f}d")
        if mem_breach is not None:
            breach_parts.append(f"Mem: {mem_breach:.0f}d")
        breach_str = " | ".join(breach_parts) if breach_parts else "N/A"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{risk_emoji} *{fc.deployment_name}* ({fc.namespace})\n"
                    f"Trends: CPU {fc.cpu_forecast.trend.value}, "
                    f"Mem {fc.memory_forecast.trend.value}\n"
                    f"Days to breach: {breach_str}"
                ),
            },
        })

    if len(forecasts) > 10:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_...and {len(forecasts) - 10} more_"}],
        })

    return {"blocks": blocks}


def _should_alert(forecasts: list[DeploymentForecast]) -> list[DeploymentForecast]:
    """Filter to only new or escalated alerts (avoid spamming)."""
    global _alerted
    new_alerts = []
    for fc in forecasts:
        prev_risk = _alerted.get(fc.deployment_name)
        if prev_risk != fc.risk_level:
            new_alerts.append(fc)
            _alerted[fc.deployment_name] = fc.risk_level
    # Clean up resolved deployments
    current_names = {fc.deployment_name for fc in forecasts}
    for name in list(_alerted):
        if name not in current_names:
            del _alerted[name]
    return new_alerts


async def send_alerts(
    forecasts: list[DeploymentForecast],
    webhook_url: str | None = None,
    slack_webhook_url: str | None = None,
) -> None:
    """Send alerts for at-risk deployments. Only alerts on new/escalated risks."""
    if not forecasts:
        return
    if not webhook_url and not slack_webhook_url:
        return

    new_alerts = _should_alert(forecasts)
    if not new_alerts:
        logger.debug("No new alerts to send (%d at-risk, all previously alerted)", len(forecasts))
        return

    logger.info("Sending alerts for %d new/escalated at-risk deployments", len(new_alerts))

    if webhook_url:
        try:
            payload = _build_alert_payload(new_alerts)
            resp = requests.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Webhook alert sent to %s", webhook_url)
        except Exception:
            logger.exception("Failed to send webhook alert")

    if slack_webhook_url:
        try:
            payload = _build_slack_blocks(new_alerts)
            resp = requests.post(
                slack_webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Slack alert sent")
        except Exception:
            logger.exception("Failed to send Slack alert")
