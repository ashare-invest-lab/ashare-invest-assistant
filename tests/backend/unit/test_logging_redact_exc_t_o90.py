# Shard T-O90: the exact-coverage ratchet compares against a single-process base run whose
# incidental cross-directory side effects (an exception log reaching RedactFilter) covered
# app/common/logging.py:53. Shards cannot reproduce that in-process ordering by construction.
# Pin the branch explicitly so the union stays >= base regardless of ordering.
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src/backend"))

from app.common.logging import RedactFilter  # noqa: E402


def test_redact_filter_formats_exception_text(tmp_path, caplog):
    record = logging.LogRecord(
        name="t_o90.shard", level=logging.ERROR, pathname=__file__,
        lineno=1, msg="boom", args=None,
        exc_info=(RuntimeError, RuntimeError("x"), None),
    )
    filt = RedactFilter()
    assert filt.filter(record) is True
    assert record.exc_text and "RuntimeError" in record.exc_text
