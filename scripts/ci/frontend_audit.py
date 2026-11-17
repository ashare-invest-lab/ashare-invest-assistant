#!/usr/bin/env python3
"""Fail-closed frontend audit with one exact, expiring exception (Grok 6957881424)."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ADVISORY_ID = "GHSA-fc5q-39xc-vjpf"
PACKAGE = "picomatch"
VERSION = "4.0.7"
DEPENDENCY_PATH = ".>typescript-eslint>@typescript-eslint/typescript-estree>tinyglobby>picomatch"
EXPIRES_ON = date(2026, 12, 1)  # 2026-12-01 00:00 UTC 起拒绝；仅 2026-11-30 前有效。
SOURCE = "https://github.com/ashare-invest-lab/ashare-invest-assistant/pull/283#issuecomment-6957881424"
EXPECTED_VULNERABLE_RANGE = "<=4.0.7"
NO_PATCH = "<0.0.0"


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
        type(counts.get(key)) is not int or counts[key] < 0
        for key in ("info", "low", "moderate", "high", "critical")
    ):
        raise ValueError("审计报告缺少有效漏洞计数，拒绝放行")
    if report.get("muted"):
        raise ValueError("审计报告包含静音公告，拒绝放行")
    return report


def is_exception(advisory: dict, finding: dict, path: str) -> bool:
    return (
        advisory.get("github_advisory_id") == ADVISORY_ID
        and advisory.get("module_name") == PACKAGE
        and advisory.get("severity") == "high"
        and finding.get("version") == VERSION
        and path == DEPENDENCY_PATH
    )


def filter_exception(report: dict) -> tuple[dict, int]:
    """Remove only the approved version/path; preserve every other finding."""
    filtered = copy.deepcopy(report)
    matched = 0
    kept_advisories = {}
    for advisory_id, advisory in filtered["advisories"].items():
        if not isinstance(advisory, dict) or advisory.get("severity") not in (
            "info", "low", "moderate", "high", "critical"
        ):
            raise ValueError(f"advisory {advisory_id} 结构或严重性无效，拒绝放行")
        findings = advisory.get("findings")
        if not isinstance(findings, list) or not findings:
            raise ValueError(f"advisory {advisory_id} 缺少有效 findings，拒绝放行")
        kept_findings = []
        for finding in findings:
            if not isinstance(finding, dict):
                raise ValueError(f"advisory {advisory_id} finding 不是对象")
            paths = finding.get("paths")
            if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
                raise ValueError(f"advisory {advisory_id} findings.paths 无效")
            remaining = []
            for path in paths:
                if is_exception(advisory, finding, path):
                    matched += 1
                else:
                    remaining.append(path)
            if remaining:
                kept_findings.append({**finding, "paths": remaining})
        if kept_findings:
            kept_advisories[advisory_id] = {**advisory, "findings": kept_findings}
    filtered["advisories"] = kept_advisories
    counts = {key: 0 for key in ("info", "low", "moderate", "high", "critical")}
    for advisory in report["advisories"].values():
        counts[advisory["severity"]] += 1
    # pnpm --audit-level high 保留 moderate 元计数，但 advisories 只列 high/critical。
    for severity in ("high", "critical"):
        if counts[severity] != report["metadata"]["vulnerabilities"][severity]:
            raise ValueError(f"审计报告 {severity} 计数与公告明细不符，拒绝放行")
    remaining_counts = {key: 0 for key in counts}
    for advisory in kept_advisories.values():
        remaining_counts[advisory["severity"]] += 1
    filtered["metadata"]["vulnerabilities"] = remaining_counts
    return filtered, matched


def check_expiry(today: date) -> str | None:
    if today >= EXPIRES_ON:
        return f"临时审计例外已于 {EXPIRES_ON.isoformat()} 到期；出处 {SOURCE}"
    return None


def gate_result(report: dict, audit_exit: int, today: date) -> tuple[int, int]:
    expired = check_expiry(today)
    if expired:
        print(f"::error::{expired}")
        return 2, 0
    filtered, matched = filter_exception(report)
    remaining = filtered["metadata"]["vulnerabilities"]
    high = remaining["high"] + remaining["critical"]
    if high:
        print(f"::error::仍有 {high} 个 high/critical 审计项；精确例外不覆盖")
        return 1, matched
    if audit_exit == 0:
        print(f"frontend audit 通过；精确例外匹配 {matched} 项，其余 high/critical=0")
        return 0, matched
    if audit_exit == 1 and matched:
        print(f"仅临时例外 {ADVISORY_ID}@{VERSION} 被豁免；到期 {EXPIRES_ON}；出处 {SOURCE}")
        return 0, matched
    print(f"::error::pnpm audit 退出 {audit_exit} 且未由精确例外完整解释，拒绝放行")
    return 1, matched


def find_advisory(report: dict) -> dict | None:
    for advisory in report["advisories"].values():
        if advisory.get("github_advisory_id") == ADVISORY_ID:
            return advisory
    return None


def watch_result(report: dict, audit_exit: int, today: date, latest_version: str) -> int:
    result, matched = gate_result(report, audit_exit, today)
    if result:
        return result
    advisory = find_advisory(report)
    if advisory is None or matched == 0:
        print("::error::公告或精确依赖路径已消失；请移除临时例外并核对锁文件")
        return 1
    if advisory.get("patched_versions") != NO_PATCH:
        print(f"::error::检测到修复版本信息 {advisory.get('patched_versions')}；请升级并移除临时例外")
        return 1
    if advisory.get("vulnerable_versions") != EXPECTED_VULNERABLE_RANGE:
        print(f"::error::影响范围已变为 {advisory.get('vulnerable_versions')}；请复核临时例外")
        return 1
    if latest_version != VERSION:
        print(f"::error::npm 最新 picomatch 为 {latest_version}；请验证修复并移除临时例外")
        return 1
    print(f"每日检查：仍无修复版，最新版 {latest_version}；例外 {EXPIRES_ON} 到期")
    return 0


def main(argv: list[str] | None = None, *, today: date | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("gate", "watch"))
    parser.add_argument("--report", required=True)
    parser.add_argument("--audit-exit", required=True, type=int)
    parser.add_argument("--latest-version")
    args = parser.parse_args(argv)
    current = today or datetime.now(timezone.utc).date()
    try:
        report = load_report(args.report)
        if args.mode == "gate":
            return gate_result(report, args.audit_exit, current)[0]
        if not args.latest_version:
            raise ValueError("watch 模式必须提供 --latest-version")
        return watch_result(report, args.audit_exit, current, args.latest_version)
    except ValueError as exc:
        print(f"::error::{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
