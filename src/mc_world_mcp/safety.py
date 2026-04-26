from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import ServerConfig

CLIENT_JAVA_MARKERS = (
    "net.minecraft.client.main.main",
    "com.mojang.authlib",
    "minecraftlauncher",
    "minecraft.launcher",
    "launcher_profiles.json",
    ".minecraft",
    "--username",
    "--uuid",
    "--accessToken".lower(),
    "--assetsDir".lower(),
    "--assetIndex".lower(),
)

SERVER_JAVA_MARKERS = (
    "nogui",
    "minecraft_server",
    "server.jar",
    "arclight",
    "forge",
    "neoforge",
    "fabric-server",
    "paper",
    "spigot",
    "bukkit",
    "server.properties",
)


def java_processes(config: ServerConfig | None = None, include_clients: bool = False) -> list[dict[str, str]]:
    processes = []
    for proc in _raw_java_processes():
        classification = _classify_java_process(proc, config)
        proc["classification"] = classification
        if include_clients or classification != "minecraft_client":
            processes.append(proc)
    return processes


def _raw_java_processes() -> list[dict[str, str]]:
    if os.name != "nt":
        try:
            out = subprocess.run(
                ["pgrep", "-fl", "java"],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            results = []
            for line in out.stdout.splitlines():
                if not line.strip():
                    continue
                pid, _, command = line.strip().partition(" ")
                results.append({"ProcessId": pid, "Name": "java", "CommandLine": command or line.strip()})
            return results
        except Exception:
            return []
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name = 'java.exe' OR Name = 'javaw.exe'\" | Select-Object Name,ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress",
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


def _classify_java_process(proc: dict[str, str], config: ServerConfig | None = None) -> str:
    command = _process_text(proc)
    if config is not None:
        root = str(config.root.resolve()).lower()
        world = str(config.world.resolve()).lower()
        if root in command or world in command:
            return "minecraft_server"
    if any(marker in command for marker in CLIENT_JAVA_MARKERS):
        return "minecraft_client"
    if any(marker in command for marker in SERVER_JAVA_MARKERS):
        return "minecraft_server"
    return "unknown_java"


def _process_text(proc: dict[str, str]) -> str:
    parts = []
    for key in ("process", "Name", "ProcessName", "ExecutablePath", "Path", "CommandLine"):
        value = proc.get(key)
        if value is not None:
            parts.append(str(value))
    return " ".join(parts).replace("\\", "/").lower()


def assert_offline(config: ServerConfig) -> None:
    procs = java_processes(config)
    if procs:
        raise RuntimeError(f"refusing write while server or unknown Java process is running: {procs}")
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
    world_root = config.world.resolve()
    for file in files:
        try:
            file.resolve().relative_to(world_root)
        except ValueError:
            continue
        from .compat import assert_world_write_supported

        assert_world_write_supported(config)
        break
    session = BackupSession(config, reason)
    for file in files:
        session.backup_file(file)
    session.write_manifest()
    return session
