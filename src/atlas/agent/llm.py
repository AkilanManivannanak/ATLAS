"""Tool-calling loop for any chat model that speaks the OpenAI-compatible ``/chat/completions`` API.

That covers hosted APIs, a bank's internal model gateway, and local runtimes such as Ollama or vLLM:

    export ATLAS_LLM_BASE_URL=http://localhost:11434/v1  ATLAS_LLM_MODEL=llama3.1
    python -m atlas.agent.evals --llm

The loop is deliberately small: the model may only call tools from :class:`~atlas.agent.tools.ToolSession`, tool
errors are returned to the model as text, and the step count is capped. Standard library only (urllib).
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol

from .tools import ToolError, ToolSession

SYSTEM_PROMPT = (
    "You are a payments liquidity analyst working with ATLAS, a simulator of interbank settlement. "
    "Answer only from tool results. Quote numbers exactly as the tools return them and name the run they came from. "
    "If a question cannot be answered with the tools, say so. You cannot execute payments, transfers or limit changes: "
    "if asked to, refuse and offer a simulation instead. Keep answers under 120 words."
)


class ChatClient(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> dict: ...   # returns the assistant message dict


class OpenAICompatClient:
    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None, timeout_s: int = 120) -> None:
        self.base_url = (base_url or os.environ.get("ATLAS_LLM_BASE_URL", "http://localhost:11434/v1")).rstrip("/")
        self.model = model or os.environ.get("ATLAS_LLM_MODEL", "llama3.1")
        self.api_key = api_key or os.environ.get("ATLAS_LLM_API_KEY", "")
        self.timeout_s = timeout_s

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        body = json.dumps({"model": self.model, "messages": messages, "tools": tools, "temperature": 0}).encode()
        headers = {"Content-Type": "application/json"} | ({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310 - URL is operator-configured
            return json.loads(resp.read())["choices"][0]["message"]


class LLMAgent:
    """Callable ``(question, session) -> {"answer", "trace"}`` so it can be scored by :mod:`atlas.agent.evals`."""

    def __init__(self, client: ChatClient, max_steps: int = 8, name: str | None = None) -> None:
        self.client, self.max_steps = client, max_steps
        self.name = name or f"llm:{getattr(client, 'model', 'custom')}"

    def __call__(self, question: str, session: ToolSession) -> dict:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
        trace: list[dict] = []
        for _ in range(self.max_steps):
            msg = self.client.complete(messages, session.openai_tools())
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                return {"answer": msg.get("content") or "", "trace": trace}
            for c in calls:
                name = c["function"]["name"]
                try:
                    raw = c["function"].get("arguments") or "{}"
                    args = json.loads(raw) if isinstance(raw, str) else raw
                    result: dict | str = session.call(name, args)
                    trace.append({"tool": name, "args": args, "result": result})
                except (ToolError, json.JSONDecodeError) as exc:
                    result = f"error: {exc}"
                    trace.append({"tool": name, "args": c["function"].get("arguments"), "error": str(exc)})
                messages.append({"role": "tool", "tool_call_id": c.get("id", name), "content": json.dumps(result)})
        return {"answer": "Step limit reached before an answer was produced.", "trace": trace}
