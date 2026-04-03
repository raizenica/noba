# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Provider-agnostic LLM client and ops context builder."""
from __future__ import annotations

import logging
import re
import socket
import time

import httpx

logger = logging.getLogger("noba")

# ── Action pattern extraction ─────────────────────────────────────────────────
_ACTION_RE = re.compile(r"\[ACTION:([^:\]]+):([^:\]]+)(?::([^\]]*))?\]")


def extract_actions(text: str) -> list[dict]:
    """Parse [ACTION:cmd:host:params] patterns from LLM response text."""
    actions: list[dict] = []
    for m in _ACTION_RE.finditer(text):
        actions.append({
            "cmd": m.group(1).strip(),
            "hostname": m.group(2).strip(),
            "params": m.group(3).strip() if m.group(3) else "",
        })
    return actions


# ── LLM Client ───────────────────────────────────────────────────────────────

class LLMClient:
    """Provider-agnostic LLM client supporting Anthropic, OpenAI, Ollama, and
    any OpenAI-compatible endpoint.

    Parameters
    ----------
    config : dict
        Keys: provider, model, apiKey, baseUrl, maxTokens, temperature, enabled.
    """

    def __init__(self, config: dict) -> None:
        self.provider = (config.get("llmProvider") or "anthropic").lower()
        self.model = config.get("llmModel") or self._default_model()
        self.api_key = config.get("llmApiKey") or ""
        self.base_url = (config.get("llmBaseUrl") or "").rstrip("/")
        self.max_tokens = int(config.get("llmMaxTokens") or 4096)
        self.temperature = float(config.get("llmTemperature") if config.get("llmTemperature") not in (None, "") else 0.3)
        self.enabled = bool(config.get("llmEnabled"))

    def _default_model(self) -> str:
        defaults = {
            "anthropic": "claude-sonnet-4-20250514",
            "openai": "gpt-4o",
            "ollama": "llama3",
            "custom": "gpt-4o",
        }
        return defaults.get(self.provider, "claude-sonnet-4-20250514")

    async def chat(self, messages: list[dict], system: str = "") -> str:
        """Send messages to the configured LLM provider and return the response text."""
        if not self.enabled:
            return "LLM is not enabled. Configure it in Settings > Integrations > AI / LLM."
        dispatch = {
            "anthropic": self._anthropic,
            "openai": self._openai_compat,
            "ollama": self._ollama,
            "custom": self._openai_compat,
        }
        handler = dispatch.get(self.provider, self._openai_compat)
        return await handler(messages, system)

    async def _anthropic(self, messages: list[dict], system: str) -> str:
        """Call the Anthropic Messages API."""
        if not self.api_key:
            return "Error: Anthropic API key not configured."
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": messages,
        }
        if system:
            body["system"] = system
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            # Anthropic returns content as a list of blocks
            content = data.get("content", [])
            parts = [b.get("text", "") for b in content if b.get("type") == "text"]
            return "\n".join(parts)

    async def _openai_compat(self, messages: list[dict], system: str) -> str:
        """Call an OpenAI-compatible chat completions API."""
        if self.provider == "openai" and not self.api_key:
            return "Error: OpenAI API key not configured."
        if self.provider == "custom" and not self.base_url:
            return "Error: Custom LLM base URL not configured."
        base = self.base_url or "https://api.openai.com"
        url = f"{base}/v1/chat/completions"
        headers: dict = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": msgs,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""

    async def _ollama(self, messages: list[dict], system: str) -> str:
        """Call a local Ollama instance."""
        base = self.base_url or "http://localhost:11434"
        url = f"{base}/api/chat"
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body = {
            "model": self.model,
            "messages": msgs,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")


# ── Context Builder ───────────────────────────────────────────────────────────

def build_ops_context(read_settings_fn, db_instance, agent_data: dict, agent_max_age: int = 120) -> str:
    """Assemble a system prompt giving the LLM infrastructure awareness.

    Parameters
    ----------
    read_settings_fn : callable
        Returns the current YAML settings dict.
    db_instance : Database
        The shared Database singleton.
    agent_data : dict
        The ``_agent_data`` dict from app.py (hostname -> metrics).
    agent_max_age : int
        Seconds before an agent is considered offline.
    """
    now = time.time()
    parts: list[str] = []

    # Server identity
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"
    parts.append(f"You are the NOBA Ops Assistant for server '{hostname}'.")
    parts.append("You help operators diagnose issues, analyze alerts, suggest fixes, and explain infrastructure status.")
    parts.append("When you suggest a concrete remediation action that can be executed on an agent, encode it as [ACTION:command_type:hostname:params].")
    parts.append("Valid command types: exec, restart_service, update_agent, set_interval, ping, get_logs, check_service, network_test, package_updates.")
    parts.append("")

    # Agent summary
    online = []
    offline = []
    cpu_vals: list[float] = []
    mem_vals: list[float] = []
    disk_vals: list[float] = []
    for host, data in agent_data.items():
        age = now - data.get("_received", 0)
        if age < agent_max_age:
            online.append(host)
            cpu_vals.append(data.get("cpu_percent", 0))
            mem_vals.append(data.get("mem_percent", 0))
            for d in data.get("disks", [])[:1]:
                disk_vals.append(d.get("percent", 0))
        else:
            offline.append(host)

    parts.append(f"## Fleet: {len(online)} agents online, {len(offline)} offline")
    if online:
        parts.append(f"Online: {', '.join(sorted(online))}")
    if offline:
        parts.append(f"Offline: {', '.join(sorted(offline))}")
    if cpu_vals:
        avg_cpu = sum(cpu_vals) / len(cpu_vals)
        avg_mem = sum(mem_vals) / len(mem_vals) if mem_vals else 0
        avg_disk = sum(disk_vals) / len(disk_vals) if disk_vals else 0
        parts.append(f"Averages across online agents: CPU {avg_cpu:.1f}%, RAM {avg_mem:.1f}%, Disk {avg_disk:.1f}%")
    parts.append("")

    # Active alerts
    try:
        alerts = db_instance.get_alert_history(limit=20)
        unresolved = [a for a in alerts if not a.get("resolved_at")]
        parts.append(f"## Active Alerts: {len(unresolved)}")
        for a in unresolved[:5]:
            parts.append(f"- [{a.get('severity', '?')}] {a.get('message', '?')} (rule: {a.get('rule_id', '?')})")
    except Exception:
        parts.append("## Active Alerts: unable to query")
    parts.append("")

    # Recent incidents
    try:
        incidents = db_instance.get_incidents(limit=5, hours=48)
        parts.append(f"## Recent Incidents ({len(incidents)} in last 48h)")
        for inc in incidents[:3]:
            status = "resolved" if inc.get("resolved_at") else "open"
            parts.append(f"- [{inc.get('severity', '?')}] {inc.get('title', '?')} ({status})")
    except Exception:
        parts.append("## Recent Incidents: unable to query")
    parts.append("")

    parts.append("Respond concisely. Use markdown formatting. If the user asks about a specific host or alert, focus on that.")
    return "\n".join(parts)
