"""API-key authentication with role-based access control.

Configure keys with ``ATLAS_API_KEYS="key1:admin,key2:researcher,key3:auditor"``.
If no keys are configured the API runs in *development mode*: every request is
treated as ``researcher`` and ``/api/v1/health`` reports ``auth: "disabled"``.
Keys are compared in constant time. There is no payment-execution permission at
all, because the system has no execution capability.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import Header, HTTPException

ROLES = ("admin", "researcher", "treasury_operator", "risk_analyst", "auditor")
# permission -> roles allowed
PERMISSIONS = {
    "read": set(ROLES),
    "simulate": {"admin", "researcher", "treasury_operator", "risk_analyst"},
    "benchmark": {"admin", "researcher"},
    "admin": {"admin"},
}


@dataclass(frozen=True)
class Principal:
    role: str
    key_id: str


def _keys() -> dict[str, str]:
    raw = os.environ.get("ATLAS_API_KEYS", "").strip()
    out: dict[str, str] = {}
    for item in filter(None, (x.strip() for x in raw.split(","))):
        key, _, role = item.partition(":")
        if role not in ROLES or not key:
            raise RuntimeError(f"invalid ATLAS_API_KEYS entry (role must be one of {ROLES})")
        out[key] = role
    return out


def auth_enabled() -> bool:
    return bool(_keys())


def require(permission: str):
    def dep(x_api_key: str | None = Header(default=None)) -> Principal:
        keys = _keys()
        if not keys:
            return Principal("researcher", "dev-mode")
        if not x_api_key:
            raise HTTPException(status_code=401, detail="missing X-API-Key header")
        role = None
        for key, r in keys.items():
            if hmac.compare_digest(key.encode(), x_api_key.encode()):
                role = r
        if role is None:
            raise HTTPException(status_code=401, detail="invalid API key")
        if role not in PERMISSIONS[permission]:
            raise HTTPException(status_code=403, detail=f"role {role!r} lacks permission {permission!r}")
        return Principal(role, x_api_key[:4] + "…")
    return dep
