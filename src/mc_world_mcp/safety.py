from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import ServerConfig


def java_processes() -> list[dict[str, str]]:
    if os.name != "nt":
        try:
            out = subprocess.run(
                ["pgrep", "-fl", "java"],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            return [{"process": line.strip()} for line in out.stdout.splitlines() if line.strip()]
        except Exception:
            return []
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process java,javaw -ErrorAction SilentlyContinue | Select-Object ProcessName,Id,Path | ConvertTo-Json -Compress",
            ],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if not out.stdout.strip():
            return []
        data = json.loads(out.stdout)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception:
        return []


def assert_offline(config: ServerConfig) -> None:
    procs = java_processes()
    if procs:
        raise RuntimeError(f"refusing write while Java process is running: {procs}")
    lock = config.world / "session.lock"
    if lock.exists():
        try:
            lock.open("ab").close()
        except Exception as exc:
            raise RuntimeError(f"world session.lock is not writable: {exc}") from exc


@dataclass
class BackupSession:
    config: ServerConfig
    reason: str
    root: Path = field(init=False)
    entries: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.root = self.config.backup_root / stamp
        self.root.mkdir(parents=True, exist_ok=True)

    def backup_file(self, path: Path) -> None:
        path = path.resolve()
        try:
            rel = path.relative_to(self.config.root)
        except ValueError as exc:
            raise ValueError(f"cannot back up path outside root: {path}") from exc
        backup_path = self.root / rel
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, backup_path)
            status = "copied"
        else:
            status = "missing"
        self.entries.append({
            "source": rel.as_posix(),
            "backup": backup_path.relative_to(self.root).as_posix(),
            "status": status,
        })

    def write_manifest(self) -> Path:
        manifest = {
            "reason": self.reason,
            "entries": self.entries,
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def begin_write(config: ServerConfig, reason: str, files: list[Path]) -> BackupSession:
    assert_offline(config)
    session = BackupSession(config, reason)
    for file in files:
        session.backup_file(file)
    session.write_manifest()
    return session

