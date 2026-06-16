#!/usr/bin/env python3
"""Check release artifacts for local runtime data and obvious secrets.

This is intended to run after PyInstaller creates a portable/app artifact and
before uploading or publishing a release.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable


CHUNK_SIZE = 1024 * 1024
OVERLAP_SIZE = 1024

FORBIDDEN_FILE_SUFFIXES = (
    ".db",
    ".db-shm",
    ".db-wal",
    ".session",
    ".session-journal",
    ".session-wal",
    ".session-shm",
    ".log",
)

FORBIDDEN_FILE_NAMES = {
    ".env",
    "tokens.json",
}

FORBIDDEN_DIR_NAMES = {
    "template_files",
    "auto_message_files",
    "import_cache",
    "sticker_cache",
}

BINARY_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "Google AI API key",
        re.compile(rb"AIza[0-9A-Za-z_\-]{20,}"),
    ),
)

TEXT_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "Telegram bot token",
        re.compile(rb"(?<![A-Za-z0-9_])\d{6,12}:[A-Za-z0-9_\-]{30,}(?![A-Za-z0-9_])"),
    ),
    (
        "labeled API key",
        re.compile(
            rb"(?i)(?:google[_-]?ai[_-]?api[_-]?key|gemini[_-]?api[_-]?key|api[_-]?key)"
            rb"\s*[:=]\s*[\"']?(?!REDACTED|MASKED|None|null|true|false|\*{4,})"
            rb"([A-Za-z0-9_\-]{24,})"
        ),
    ),
    (
        "Telegram API hash",
        re.compile(
            rb"(?i)(?:api[_-]?hash|telegram[_-]?api[_-]?hash)"
            rb"\s*[:=]\s*[\"']?([0-9a-f]{32})"
        ),
    ),
)

TEXT_LIKE_SUFFIXES = {
    ".bat",
    ".cfg",
    ".css",
    ".env",
    ".html",
    ".ini",
    ".iss",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".plist",
    ".ps1",
    ".py",
    ".pyw",
    ".spec",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class Issue:
    kind: str
    location: str
    detail: str


def _is_forbidden_file(name: str) -> str | None:
    lowered = name.lower()
    if lowered in FORBIDDEN_FILE_NAMES:
        return f"forbidden file name '{name}'"
    for suffix in FORBIDDEN_FILE_SUFFIXES:
        if lowered.endswith(suffix):
            return f"forbidden file suffix '{suffix}'"
    return None


def _path_parts(path: str) -> list[str]:
    return [part for part in Path(path.replace("\\", "/")).parts if part not in {"", "."}]


def _forbidden_path_reason(path: str, is_dir: bool = False) -> str | None:
    parts = _path_parts(path)
    for part in parts:
        if part.lower() in FORBIDDEN_DIR_NAMES:
            return f"forbidden runtime directory '{part}'"
    if not is_dir and parts:
        return _is_forbidden_file(parts[-1])
    return None


def _redact(value: bytes) -> str:
    text = value.decode("utf-8", errors="replace")
    if len(text) <= 12:
        return "[REDACTED]"
    return f"{text[:6]}...{text[-4:]}"


def _is_text_like(label: str) -> bool:
    return Path(label.replace("\\", "/")).suffix.lower() in TEXT_LIKE_SUFFIXES


def _is_ignored_secret(pattern_name: str, value: bytes) -> bool:
    if pattern_name == "Telegram bot token":
        # Common fake tokens from library docs/examples.
        return value.startswith((b"123456:", b"456789:", b"123456789:"))
    return False


def _scan_stream(label: str, stream: BinaryIO, *, text_like: bool | None = None) -> list[Issue]:
    issues: list[Issue] = []
    tail = b""
    reported: set[str] = set()
    patterns = list(BINARY_SECRET_PATTERNS)
    should_scan_text_patterns = text_like if text_like is not None else _is_text_like(label)
    if should_scan_text_patterns:
        patterns.extend(TEXT_SECRET_PATTERNS)

    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            break

        data = tail + chunk
        tail_len = len(tail)
        for pattern_name, pattern in patterns:
            if pattern_name in reported:
                continue
            for match in pattern.finditer(data):
                if match.end() <= tail_len:
                    continue
                value = match.group(1) if match.groups() else match.group(0)
                if _is_ignored_secret(pattern_name, value):
                    continue
                reported.add(pattern_name)
                issues.append(
                    Issue(
                        "secret",
                        label,
                        f"{pattern_name} found: {_redact(value)}",
                    )
                )
                break

        tail = data[-OVERLAP_SIZE:]

    return issues


def _scan_file(path: Path, label: str | None = None) -> list[Issue]:
    display = label or str(path)
    issues: list[Issue] = []
    reason = _forbidden_path_reason(display)
    if reason:
        issues.append(Issue("file", display, reason))

    if path.suffix.lower() == ".zip" and zipfile.is_zipfile(path):
        issues.extend(_scan_zip(path))
        return issues

    try:
        with path.open("rb") as file:
            issues.extend(_scan_stream(display, file))
    except OSError as exc:
        issues.append(Issue("error", display, f"cannot read file: {exc}"))
    return issues


def _scan_zip(path: Path) -> list[Issue]:
    issues: list[Issue] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                location = f"{path}!{info.filename}"
                reason = _forbidden_path_reason(info.filename, info.is_dir())
                if reason:
                    issues.append(Issue("file", location, reason))
                if info.is_dir():
                    continue
                try:
                    with archive.open(info, "r") as stream:
                        issues.extend(_scan_stream(location, stream, text_like=_is_text_like(info.filename)))
                except (OSError, zipfile.BadZipFile) as exc:
                    issues.append(Issue("error", location, f"cannot read zip entry: {exc}"))
    except zipfile.BadZipFile as exc:
        issues.append(Issue("error", str(path), f"cannot read zip: {exc}"))
    return issues


def _scan_dir(path: Path) -> list[Issue]:
    issues: list[Issue] = []
    for root, dirs, files in os.walk(path):
        root_path = Path(root)

        for dirname in list(dirs):
            dir_path = root_path / dirname
            rel = str(dir_path.relative_to(path))
            reason = _forbidden_path_reason(rel, is_dir=True)
            if reason:
                issues.append(Issue("directory", str(dir_path), reason))

        for filename in files:
            file_path = root_path / filename
            rel = str(file_path.relative_to(path))
            issues.extend(_scan_file(file_path, label=str(path / rel)))
    return issues


def scan_targets(targets: Iterable[Path]) -> list[Issue]:
    issues: list[Issue] = []
    for target in targets:
        if not target.exists():
            issues.append(Issue("error", str(target), "target does not exist"))
            continue
        if target.is_dir():
            issues.extend(_scan_dir(target))
        elif target.is_file():
            issues.extend(_scan_file(target))
        else:
            issues.append(Issue("error", str(target), "unsupported target type"))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check release artifacts for local DB/session/log files and obvious API keys."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        default=["dist"],
        help="Files or directories to scan. Defaults to ./dist.",
    )
    args = parser.parse_args()

    targets = [Path(target).resolve() for target in args.targets]
    issues = scan_targets(targets)

    if issues:
        print("[FAIL] Release artifact check found possible personal/runtime data:\n")
        for issue in issues:
            print(f"- [{issue.kind.upper()}] {issue.location}")
            print(f"  {issue.detail}")
        print("\nFix the artifact or rebuild it from a clean runtime directory before publishing.")
        return 1

    target_list = ", ".join(str(target) for target in targets)
    print(f"[OK] Release artifact check passed: {target_list}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
