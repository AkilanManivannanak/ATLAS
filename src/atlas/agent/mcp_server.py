"""Model Context Protocol server for the twin, over stdio. Standard library only.

    python -m atlas.agent.mcp_server [--seed 11] [--payments my_day.csv]

Any MCP-capable client (an IDE assistant, a desktop chat app, a bank's own agent runtime) can then call the tools
in :mod:`atlas.agent.tools`. The server speaks JSON-RPC 2.0, one message per line, and implements ``initialize``,
``ping``, ``tools/list`` and ``tools/call``. It exposes tools only: no resources, prompts or sampling.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import IO, Any

from .tools import AGENT_VERSION, ToolError, ToolSession

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = ("ATLAS is a simulator of interbank payment settlement and intraday liquidity. Call list_options first. "
                "simulate_day creates a run; the other tools read from a run. All figures are simulated; no tool can execute anything.")


def handle(session: ToolSession, msg: dict) -> dict | None:
    """Return the JSON-RPC response for one request, or None for a notification."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None
    ok = lambda result: {"jsonrpc": "2.0", "id": mid, "result": result}
    err = lambda code, text: {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "atlas-sigma", "version": AGENT_VERSION}, "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"],
                              "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}
                             for t in session.list_tools()]})
    if method == "tools/call":
        try:
            result = session.call(params.get("name", ""), params.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": json.dumps(result)}], "structuredContent": result, "isError": False})
        except ToolError as exc:
            return ok({"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except Exception as exc:  # noqa: BLE001 - never crash the server on a tool bug; report it to the client
            return ok({"content": [{"type": "text", "text": f"internal tool error: {type(exc).__name__}"}], "isError": True})
    return err(-32601, f"method not found: {method}")


def serve(session: ToolSession, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg: Any = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            stdout.flush()
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            resp = handle(session, m) if isinstance(m, dict) else None
            if resp is not None:
                stdout.write(json.dumps(resp) + "\n")
                stdout.flush()


def main() -> None:
    ap = argparse.ArgumentParser(description="ATLAS MCP server (stdio)")
    ap.add_argument("--seed", type=int, default=11, help="seed of the synthetic day when no file is given")
    ap.add_argument("--payments", help="CSV of your own payments (see `atlas template`)")
    ap.add_argument("--balances", help="optional CSV of opening balances")
    a = ap.parse_args()
    scenario = None
    if a.payments:
        from pathlib import Path

        from atlas.ingest import load_payments_csv
        scenario, report = load_payments_csv(Path(a.payments).read_text(), balances_csv=Path(a.balances).read_text() if a.balances else None)
        print(f"loaded {report.accepted} payments, rejected {len(report.rejected)}", file=sys.stderr)
    serve(ToolSession(scenario, seed=a.seed))


if __name__ == "__main__":
    main()
