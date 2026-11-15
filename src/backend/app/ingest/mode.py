"""Verification mode guard; daily-bar/replay transports retain their own behavior."""

from __future__ import annotations

import os

VERIFY_OFFLINE_REASON = "replay_offline_no_request"
VERIFY_OFFLINE_MESSAGE = "当前为 replay/离线模式，未发出真实验证请求。"


def verification_is_offline() -> bool:
    """Preserve unset/default live behavior; fail closed for explicit non-live modes.

    There is no existing mode enum. Unknown nonempty values cannot authorize a
    real verification request; no additional opt-in configuration is introduced.
    """
    return os.environ.get("MAIRUI_MODE", "").strip().lower() not in {"", "live"}
