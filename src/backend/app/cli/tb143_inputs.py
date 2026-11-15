"""T-B143w 输入完整性校验与安全搬运；仅处理调用方指定的离线文件。"""

from __future__ import annotations

import dbm
import hashlib
import re
import shutil
import tarfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.ingest.tdx_local import file_sha256


class InputKeys:
    """本次审计目录内的磁盘去重索引，避免全历史主键常驻内存。"""

    def __init__(self, path: Path) -> None:
        self.db = dbm.open(str(path), "n")  # noqa: SIM115 - run 的 finally 统一关闭

    @staticmethod
    def encode(key: tuple[str, date, str]) -> bytes:
        return f"{key[0]}|{key[1]}|{key[2]}".encode("ascii")

    def __contains__(self, key: tuple[str, date, str]) -> bool:
        return self.encode(key) in self.db

    def add(self, key: tuple[str, date, str]) -> None:
        self.db[self.encode(key)] = b"1"

    def difference_update(self, keys: Iterable[tuple[str, date, str]]) -> None:
        for key in keys:
            encoded = self.encode(key)
            if encoded in self.db:
                del self.db[encoded]

    def close(self) -> None:
        self.db.close()


@dataclass
class Inputs:
    """完整性错误独立于行级异常；任一错误禁止整次 apply。"""

    files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    hashes: dict[str, str] = field(default_factory=dict)


def manifest(root: Path, name: str, result: Inputs) -> dict[str, str]:
    """接受 sha256sum 的 HEX<空白>[*]相对路径；拒绝路径逃逸及重复项。"""
    entries: dict[str, str] = {}
    path = root / name
    if not path.is_file():
        return entries
    if not path.resolve().is_relative_to(root.resolve()):
        result.errors.append(f"{name}:unsafe_manifest_path")
        return entries
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line)
        if match is None:
            result.errors.append(f"{name}:invalid_manifest")
            continue
        digest, rel = match.groups()
        target = root / rel
        if (
            not rel
            or "\\" in rel
            or ":" in rel
            or Path(rel).is_absolute()
            or ".." in Path(rel).parts
            or not target.resolve().is_relative_to(root.resolve())
            or rel in entries
        ):
            result.errors.append(f"{name}:unsafe_or_duplicate_path")
            continue
        entries[rel] = digest.lower()
    if not entries:
        result.errors.append(f"{name}:empty_manifest")
    return entries


def verify(root: Path, entries: dict[str, str], result: Inputs) -> None:
    for rel, expected in entries.items():
        target = root / rel
        if not target.is_file():
            result.errors.append(f"missing:{rel}")
        else:
            actual = file_sha256(target)
            result.hashes[str(target)] = actual
            if actual != expected:
                result.errors.append(f"sha256_mismatch:{rel}")


def _unpack(root: Path, destination: Path, bundles: dict[str, str], result: Inputs) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in sorted(bundles):
        with tarfile.open(root / name, mode="r:gz") as archive:
            for member in archive:
                # 旧 SQL 仅作为 SUMS 哈希对象保留，绝不执行；拒绝链接/任意目录。
                rel = member.name.removeprefix("./")
                if rel not in ("SUMS", "tb143_load_day.sql") and not re.fullmatch(
                    r"day_[0-9]{4}\.csv", rel
                ):
                    continue
                if not member.isfile():
                    result.errors.append(f"bundle:not_regular:{rel}")
                    continue
                target = destination / rel
                stream = archive.extractfile(member)
                if stream is None:
                    result.errors.append(f"bundle:unreadable:{rel}")
                    continue
                if target.exists():
                    with stream:
                        digest = hashlib.sha256()
                        while block := stream.read(1024 * 1024):
                            digest.update(block)
                        if digest.hexdigest() != file_sha256(target):
                            result.errors.append(f"bundle:conflicting_member:{rel}")
                    continue
                with stream, target.open("xb") as output:
                    shutil.copyfileobj(stream, output)


def prepare(root: Path, destination: Path, bundle_sizes: str | None = None) -> Inputs:
    """年度 CSV 可直接使用；旧传输格式固定 p00–p56、b1–b5，拒绝部分清单。

    仅有 p?? 时，调用方必须提供五段字节数以恢复 b*.tgz。所有原件保留。
    SUMS 覆盖所有加载 CSV；没有传输清单的普通 CSV 目录记录输入哈希即可。
    """
    result = Inputs()
    try:
        if not root.is_dir():
            result.errors.append("not_directory")
            return result
        parts = manifest(root, "PARTS", result)
        bundles = manifest(root, "BUNDLES", result)
        if (root / "PARTS").exists():
            if set(parts) != {f"p{i:02d}" for i in range(57)}:
                result.errors.append("PARTS:expected_p00-p56")
            verify(root, parts, result)
        elif any(root.glob("p[0-9][0-9]")):
            result.errors.append("PARTS:missing_manifest")
        if (root / "BUNDLES").exists() and set(bundles) != {f"b{i}.tgz" for i in range(1, 6)}:
            result.errors.append("BUNDLES:expected_b1-b5")
        result.files = sorted(root.rglob("*.csv"))
        # 非日线辅助 CSV 不参与加载，避免把 SHA256SUMS.csv 当行情。
        result.files = [p for p in result.files if p.name.startswith(("day_", "daily_bars"))]
        if not result.files and bundles and not result.errors:
            bundle_root = root
            if not all((root / name).is_file() for name in bundles):
                if not parts or bundle_sizes is None:
                    result.errors.append("bundles_missing:need_complete_PARTS_and_bundle_sizes")
                    return result
                sizes = [int(value) for value in bundle_sizes.split(",")]
                if len(sizes) != 5 or min(sizes) <= 0:
                    raise ValueError("bundle_sizes")
                destination.mkdir(parents=True, exist_ok=True)
                combined = destination / "all.bin"
                with combined.open("xb") as output:
                    for name in sorted(parts):
                        with (root / name).open("rb") as source:
                            shutil.copyfileobj(source, output)
                if combined.stat().st_size != sum(sizes):
                    raise ValueError("bundle_sizes_total")
                with combined.open("rb") as source:
                    for name, size in zip(sorted(bundles), sizes, strict=True):
                        with (destination / name).open("xb") as output:
                            remaining = size
                            while remaining:
                                block = source.read(min(remaining, 1024 * 1024))
                                if not block:
                                    raise ValueError("truncated_bundle")
                                output.write(block)
                                remaining -= len(block)
                bundle_root = destination
            verify(bundle_root, bundles, result)
            if result.errors:
                return result
            extracted = destination / "csv"
            _unpack(bundle_root, extracted, bundles, result)
            root = extracted
            result.files = sorted(root.glob("day_*.csv"))
            if not (root / "SUMS").is_file():
                result.errors.append("SUMS:missing_after_unpack")
        elif bundles:
            verify(root, bundles, result)
        sums = manifest(root, "SUMS", result)
        verify(root, sums, result)
        if sums:
            covered = {(root / rel).resolve() for rel in sums}
            if any(path.resolve() not in covered for path in result.files):
                result.errors.append("SUMS:uncovered_csv")
        if (parts or bundles) and not sums:
            result.errors.append("SUMS:required_for_shards")
        if not result.files:
            result.errors.append("no_daily_csv")
        safe_files = []
        for path in result.files:
            if not path.resolve().is_relative_to(root.resolve()):
                result.errors.append("csv:unsafe_path")
                continue
            result.hashes[str(path)] = file_sha256(path)
            safe_files.append(path)
        result.files = safe_files
    except (OSError, ValueError, tarfile.TarError) as exc:
        result.errors.append(f"input_failure:{type(exc).__name__}")
        result.files = [path for path in result.files if str(path) in result.hashes]
    return result
