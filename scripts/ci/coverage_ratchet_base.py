#!/usr/bin/env python3
"""Freeze a trusted base measurement, never the PR's own editable baseline.

Only the first approved pre-ratchet main commit uses the reviewed 4c02 counts.
Later baselines use validated main push artifacts. All supported events may recover
an unavailable exact main measurement through a bounded first-parent history.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from coverage_ratchet import BOOTSTRAP_BASE, bootstrap_record, coverage_counts, validate_record

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = "scripts/ci/coverage-baseline.json"
LIMIT = 8 * 1024 * 1024
MAX_FALLBACK_ANCESTORS = 50
SETTLE_SECONDS = 120
# 1800 s pending budget + at most 120 s settling; below readiness's 35 min.
MAX_WAIT_SECONDS = 1920
EXPLICIT_RECOVERY_BASE = "f6c939d6ed4af94144e7dd669f206c96d6aeaf6b"
EXPLICIT_RECOVERY_PARENT = "90ef8ff16abb7204b7c4ffd54174aeeb8f712455"


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = super().redirect_request(req, fp, code, msg, headers, newurl)
        if target is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            target.remove_header("Authorization")
        return target


def base_identity(event: dict, env: dict) -> tuple[str, str]:
    repo = env["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository")
    kind = env["GITHUB_EVENT_NAME"]
    if kind == "pull_request":
        base = event["pull_request"]["base"]
        if base["repo"]["full_name"] != repo or base["ref"] != "main":
            raise ValueError("Only this repository's trusted main base is accepted")
        sha = base["sha"]
    elif kind == "merge_group":
        group = event["merge_group"]
        if group["base_ref"] != "refs/heads/main":
            raise ValueError("Only the trusted main merge group base is accepted")
        sha = group.get("base_sha", "")
    elif kind == "push" and env["GITHUB_REF"] == "refs/heads/main":
        sha = event["before"]
    elif kind == "workflow_dispatch" and env["GITHUB_REF"] == "refs/heads/main":
        sha = subprocess.check_output(["git", "rev-parse", "HEAD^"], cwd=ROOT, text=True).strip()
    else:
        raise ValueError("Unsupported coverage baseline context")
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or sha == "0" * 40:
        raise ValueError("Missing trusted base commit")
    return repo, sha


def api_reader(repo: str):
    opener = urllib.request.build_opener(SafeRedirect())
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("Missing Actions read token")

    def get(path: str, *, binary=False):
        if not path.startswith("/actions/"):
            raise ValueError("Unexpected API path")
        request = urllib.request.Request("https://api.github.com/repos/" + repo + path, headers={
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"})
        with opener.open(request, timeout=30) as response:
            data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("Baseline artifact exceeds bound")
        return data if binary else json.loads(data)
    return get


def read_artifact(data: bytes, sha: str, run_id: int, attempt: int) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        expected = "coverage-ratchet-measurement.json"
        if names.count(expected) != 1 or any(".." in path_parts(n) for n in names):
            raise ValueError("Unexpected measurement archive")
        entry = archive.getinfo(expected)
        if entry.file_size > LIMIT:
            raise ValueError("Measurement exceeds bound")
        record = validate_record(json.loads(archive.read(entry)))
        # Carry the paired raw JSON only in memory; main removes this payload
        # before writing the frozen official measurement.
        record.pop("_coverage_json", None)
        coverage_name = "coverage.json"
        if coverage_name in names:
            if names.count(coverage_name) != 1 or archive.getinfo(coverage_name).file_size > LIMIT:
                raise ValueError("Unexpected coverage archive entry")
            coverage = json.loads(archive.read(coverage_name))
            if coverage_counts(coverage) != record["counts"]:
                raise ValueError("Archived coverage.json counts disagree with measurement")
            record["_coverage_json"] = coverage
    if record.get("ratchet_passed") is not True:
        raise ValueError("Artifact ratchet_passed is not true")
    if (record.get("commit") != sha or record.get("run_id") != str(run_id)
            or record.get("attempt") != str(attempt)):
        raise ValueError("Artifact does not belong to exact trusted base run")
    record["source"] = {"kind": "trusted-main-push-artifact", "commit": sha,
                        "run_id": run_id, "attempt": attempt}
    return record


def path_parts(name: str):
    return name.replace("\\", "/").split("/")


class MeasurementPending(ValueError):
    """Only an existing exact-main push may justify waiting; never a fallback."""

    def __init__(self, sha: str, run_id: int, *, timeout: int | None = None):
        self.sha = sha
        self.run_id = run_id
        self.timeout = timeout
        message = (f"timed out after {timeout} s waiting for run {run_id}" if timeout is not None
                   else f"Exact main measurement pending: base={sha}, run={run_id}")
        super().__init__(message)


class MeasurementUnavailable(ValueError):
    """A known main head lacks a usable, validated main push measurement."""


class _MeasurementNotVisible(ValueError):
    """Completed, previously pending run whose artifact data may still settle."""

    def __init__(self, message: str, completed_at: float):
        self.completed_at = completed_at
        super().__init__(message)


def _freeze_exact(repo: str, sha: str, get, *, unavailable=ValueError,
                  known_run_id: int | None = None) -> dict:
    requested_base = sha
    if sha == EXPLICIT_RECOVERY_BASE:
        # One approved docs-only recovery, before querying any requested-base run.
        parent = subprocess.run(["git", "rev-parse", "--verify", sha + "^1"],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        if parent.returncode or parent.stdout.strip() != EXPLICIT_RECOVERY_PARENT:
            raise ValueError("Explicit recovery requires the approved first parent")
        diff = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z",
                               EXPLICIT_RECOVERY_PARENT, sha],
                              cwd=ROOT, capture_output=True, text=True, check=False)
        if diff.returncode:
            raise ValueError("Explicit recovery could not verify the docs-only diff")
        if any(not path.startswith("docs/") for path in diff.stdout.split("\0") if path):
            raise ValueError("Explicit recovery requires a docs-only diff")
        sha = EXPLICIT_RECOVERY_PARENT
    # Recovery classifies only missing/invalid measurement data, never git or API
    # failures. Source selection and trust checks remain exact for each candidate.
    exists = subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=ROOT,
                            capture_output=True, check=False)
    if exists.returncode:
        raise ValueError("Trusted base commit is not present in fetched history")
    policy = subprocess.run(["git", "show", sha + ":" + POLICY_PATH], cwd=ROOT,
                            capture_output=True, check=False)
    if policy.returncode:
        if sha != BOOTSTRAP_BASE or sha != requested_base:
            raise ValueError("Trusted base has no ratchet measurement policy")
        record = bootstrap_record()
        record["source"] = record["source"] | {"base_commit": sha}
        return record
    if known_run_id is not None:
        # The filtered runs index can lag the run's own completed status. Once
        # pending was observed, pin all retries to that run, before any fallback.
        run = get("/actions/runs/" + str(known_run_id))
        if (run.get("id") != known_run_id or run.get("head_sha") != sha
                or run.get("head_branch") != "main" or run.get("event") != "push"
                or run.get("repository", {}).get("full_name") != repo
                or run.get("path") != ".github/workflows/ci.yml"):
            raise unavailable("Known main measurement run identity mismatch")
        if run.get("status") != "completed":
            raise MeasurementPending(sha, known_run_id)
        completed_at = time.monotonic()
        runs = [run]
    else:
        runs = get("/actions/workflows/ci.yml/runs?event=push&branch=main&status=completed&head_sha="
               + sha + "&per_page=100")["workflow_runs"]
    if known_run_id is None:
        runs = [r for r in runs if r["head_sha"] == sha and r["head_branch"] == "main"
                and r["event"] == "push" and r["status"] == "completed"
                and r["repository"]["full_name"] == repo]
    if not runs:
        active = get("/actions/workflows/ci.yml/runs?event=push&branch=main&head_sha="
                     + sha + "&per_page=100")["workflow_runs"]
        active = [r for r in active if r["head_sha"] == sha and r["head_branch"] == "main"
                  and r["event"] == "push" and r["status"] in {"queued", "in_progress", "waiting", "pending", "requested"}
                  and r["repository"]["full_name"] == repo]
        if active:
            raise MeasurementPending(sha, max(int(r["id"]) for r in active))
        raise unavailable("No completed exact-base main measurement run")
    run = max(runs, key=lambda r: (r["id"], r["run_attempt"]))

    def missing(message):
        return (_MeasurementNotVisible(message, completed_at) if known_run_id is not None
                else unavailable(message))

    try:
        artifacts = get("/actions/runs/" + str(run["id"]) + "/artifacts?per_page=100")["artifacts"]
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or (known_run_id is None and unavailable is ValueError):
            raise
        raise missing("Exact-base measurement artifacts not yet visible") from exc
    name = "coverage-ratchet-" + str(run["id"]) + "-" + str(run["run_attempt"])
    selected = [a for a in artifacts if a["name"] == name and not a["expired"]]
    if len(selected) != 1:
        # Expired or ambiguous artifacts are invalid, not publication latency.
        if not any(a["name"] == name for a in artifacts):
            raise missing("Missing, expired or ambiguous exact-base measurement")
        raise unavailable("Missing, expired or ambiguous exact-base measurement")
    try:
        data = get("/actions/artifacts/" + str(selected[0]["id"]) + "/zip", binary=True)
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or (known_run_id is None and unavailable is ValueError):
            raise
        raise missing("Exact-base measurement download not yet visible") from exc
    try:
        record = read_artifact(data, sha, run["id"], run["run_attempt"])
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        if unavailable is ValueError:
            raise
        # Recovery reasons are also printed on success; keep external archive
        # exception text out of both receipts and stdout.
        raise unavailable("Invalid exact-base main push measurement: " + _failure_reason(exc)) from exc
    if sha != requested_base:
        record["source"]["requested_base"] = requested_base
    return record


def freeze(repo: str, sha: str, get, *, allow_fallback: bool = False) -> dict:
    if not allow_fallback:
        return _freeze_exact(repo, sha, get)
    requested = sha
    reason = ""
    for skipped in range(MAX_FALLBACK_ANCESTORS + 1):
        try:
            record = _freeze_exact(repo, sha, get, unavailable=MeasurementUnavailable)
        except MeasurementPending:
            if skipped == 0:
                raise  # Retain the existing wait for this head's active push.
        except MeasurementUnavailable as exc:
            if skipped == 0:
                reason = str(exc)
        else:
            if skipped == 0:
                return record  # Including the original exact bootstrap behavior.
            if record["source"]["kind"] != "trusted-main-push-artifact":
                break  # Never reset a missing chain to bootstrap counts.
            record["source"]["fallback"] = {
                "requested_base_commit": requested, "skipped_heads": skipped,
                "ancestor_limit": MAX_FALLBACK_ANCESTORS,
                "reason": reason,
            }
            return record
        if skipped == MAX_FALLBACK_ANCESTORS:
            break
        parent = subprocess.run(["git", "rev-parse", "--verify", sha + "^1"],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        if parent.returncode:
            break
        sha = parent.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid first-parent commit identity")
    raise MeasurementUnavailable(
        "No usable trusted main push measurement within "
        f"{MAX_FALLBACK_ANCESTORS} first-parent ancestors")


def wait_for_base(repo: str, sha: str, get, timeout: int, *, allow_fallback: bool = False) -> dict:
    started = time.monotonic()
    deadline = started + timeout
    hard_deadline = started + MAX_WAIT_SECONDS
    known_run_id = None
    settle_deadline = None
    unavailable = MeasurementUnavailable if allow_fallback else ValueError
    while True:
        recovering = False
        try:
            try:
                if known_run_id is not None:
                    return _freeze_exact(repo, sha, get, unavailable=unavailable,
                                         known_run_id=known_run_id)
                if allow_fallback:
                    return freeze(repo, sha, get, allow_fallback=True)
                return freeze(repo, sha, get)
            except _MeasurementNotVisible as exc:
                now = time.monotonic()
                if settle_deadline is None:
                    settle_deadline = min(exc.completed_at + SETTLE_SECONDS, hard_deadline)
                remaining = settle_deadline - now
                if remaining > 0:
                    print(f"Waiting for trusted main run {known_run_id} artifact to settle", flush=True)
                    time.sleep(min(15, remaining))
                    continue
                if not allow_fallback:
                    raise unavailable(str(exc)) from exc
            except MeasurementUnavailable:
                if known_run_id is None or not allow_fallback:
                    raise
            # Invalid data or exhausted grace can enter recovery. Its list may
            # still report pending even when the direct endpoint is completed;
            # catch that below using the same deadlines and pinned-run loop.
            recovering = True
            return freeze(repo, sha, get, allow_fallback=True)
        except MeasurementPending as pending:
            # A stale list for the already completed run must not turn the
            # publication grace crossing the pending deadline into a timeout.
            waiting_deadline = (hard_deadline if recovering and pending.run_id == known_run_id
                                else min(deadline, hard_deadline))
            known_run_id = pending.run_id
            remaining = waiting_deadline - time.monotonic()
            if remaining <= 0:
                raise MeasurementPending(sha, known_run_id,
                                         timeout=int(waiting_deadline - started)) from pending
            print(f"Waiting for existing trusted main run {pending.run_id}; base={sha}", flush=True)
            time.sleep(min(15, remaining))


def _failure_reason(exc: Exception) -> str:
    # Never echo library/API exception text: URLs, headers or attacker-controlled
    # archive content can occur there. Only these script-owned literals are safe.
    safe_messages = {
        "Invalid repository", "Only this repository's trusted main base is accepted",
        "Only the trusted main merge group base is accepted", "Missing trusted base commit",
        "Unsupported coverage baseline context", "Missing Actions read token", "Unexpected API path",
        "Baseline artifact exceeds bound", "Unexpected measurement archive", "Measurement exceeds bound",
        "Unexpected coverage archive entry", "Archived coverage.json counts disagree with measurement",
        "Artifact does not belong to exact trusted base run",
        "Artifact ratchet_passed is not true",
        "Explicit recovery requires the approved first parent",
        "Explicit recovery could not verify the docs-only diff", "Explicit recovery requires a docs-only diff",
        "Trusted base commit is not present in fetched history", "Trusted base has no ratchet measurement policy",
        "No completed exact-base main measurement run", "Known main measurement run identity mismatch",
        "Missing, expired or ambiguous exact-base measurement", "Invalid exact-base main push measurement",
        "Exact-base measurement artifacts not yet visible", "Exact-base measurement download not yet visible",
        "Invalid first-parent commit identity", "Refuse to replace a frozen baseline",
        "Trusted base artifact has no coverage.json", "Frozen measurement and coverage outputs must differ",
        f"No usable trusted main push measurement within {MAX_FALLBACK_ANCESTORS} first-parent ancestors",
    }
    if isinstance(exc, urllib.error.HTTPError):
        reason = f"HTTP status {exc.code}"
    elif isinstance(exc, MeasurementPending):
        reason = (f"timed out after {exc.timeout} s waiting for run {exc.run_id}"
                  if exc.timeout is not None else "Exact main measurement pending")
    elif isinstance(exc, ValueError) and str(exc) in safe_messages:
        reason = str(exc)
    else:
        reason = "Could not read or validate trusted base measurement data"
    return type(exc).__name__ + ": " + reason


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coverage-output", type=Path)
    parser.add_argument("--wait-for-main-seconds", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.wait_for_main_seconds <= 1800:
        parser.error("--wait-for-main-seconds must be between 0 and 1800")
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        repo, sha = base_identity(event, os.environ)
        get = api_reader(repo)
        record = wait_for_base(repo, sha, get, args.wait_for_main_seconds,
                               allow_fallback=True)
        coverage = record.pop("_coverage_json", None)
        if args.output.exists() or (args.coverage_output is not None and args.coverage_output.exists()):
            raise ValueError("Refuse to replace a frozen baseline")
        if args.coverage_output is not None:
            if coverage is None:
                raise ValueError("Trusted base artifact has no coverage.json")
            if args.coverage_output.resolve() == args.output.resolve():
                raise ValueError("Frozen measurement and coverage outputs must differ")
            args.coverage_output.write_text(json.dumps(coverage, separators=(",", ":")) + "\n", encoding="utf-8")
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        source = record["source"]
        selected = source.get("commit", sha)
        print("Frozen coverage baseline: " + selected + "; source=" + source["kind"])
        if "fallback" in source:
            print("Recovered requested base: " + sha
                  + "; reason=" + source["fallback"]["reason"]
                  + "; first-parent fallback commit=" + selected
                  + "; skipped_heads=" + str(source["fallback"]["skipped_heads"]))
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        print("::error title=coverage-ratchet::Trusted base measurement unavailable or invalid; "
              + _failure_reason(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
