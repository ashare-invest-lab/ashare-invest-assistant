#!/usr/bin/env python3
"""Fail closed unless the full frontend audit reports no high/critical advisories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SEVERITIES = ("info", "low", "moderate", "high", "critical")
BLOCKING_SEVERITIES = ("high", "critical")


def load_report(path: str) -> dict:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"审计报告不可读或不是 JSON：{exc}") from exc
    if not isinstance(report, dict) or not isinstance(report.get("advisories"), dict):
        raise ValueError("审计报告缺少 advisories 对象，拒绝放行")
    metadata = report.get("metadata")
    counts = metadata.get("vulnerabilities") if isinstance(metadata, dict) else None
    if not isinstance(counts, dict) or any(
        type(counts.get(key)) is not int or counts[key] < 0 for key in SEVERITIES
    ):
        raise ValueError("审计报告缺少有效漏洞计数，拒绝放行")
    if report.get("muted"):
        raise ValueError("审计报告包含静音公告，拒绝放行")
    return report


def count_blocking_advisories(report: dict) -> int:
    """Validate report details without dropping any advisory or dependency path."""
    counts = dict.fromkeys(SEVERITIES, 0)
    for advisory_id, advisory in report["advisories"].items():
        if not isinstance(advisory, dict) or advisory.get("severity") not in SEVERITIES:
            raise ValueError(f"advisory {advisory_id} 结构或严重性无效，拒绝放行")
        findings = advisory.get("findings")
        if not isinstance(findings, list) or not findings:
            raise ValueError(f"advisory {advisory_id} 缺少有效 findings，拒绝放行")
        for finding in findings:
            if not isinstance(finding, dict):
                raise ValueError(f"advisory {advisory_id} finding 不是对象")
            paths = finding.get("paths")
            if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
                raise ValueError(f"advisory {advisory_id} findings.paths 无效")
        counts[advisory["severity"]] += 1
    # pnpm --audit-level high may retain lower severity counts without their advisory details.
    for severity in BLOCKING_SEVERITIES:
        if counts[severity] != report["metadata"]["vulnerabilities"][severity]:
            raise ValueError(f"审计报告 {severity} 计数与公告明细不符，拒绝放行")
    return sum(counts[severity] for severity in BLOCKING_SEVERITIES)


def gate_result(report: dict, audit_exit: int) -> int:
    blocking = count_blocking_advisories(report)
    if blocking:
        print(f"::error::存在 {blocking} 个 high/critical 审计项，拒绝放行")
        return 1
    if audit_exit != 0:
        print(f"::error::pnpm audit 退出 {audit_exit}，拒绝放行")
        return 1
    print("frontend audit 通过；high/critical=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--audit-exit", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        return gate_result(load_report(args.report), args.audit_exit)
    except ValueError as exc:
        print(f"::error::{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
