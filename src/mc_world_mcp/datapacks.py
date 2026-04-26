from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from .config import ServerConfig
from .paths import resolve_under_root
from .safety import begin_write


def datapacks_dir(config: ServerConfig) -> Path:
    return config.world / "datapacks"


def list_datapacks(config: ServerConfig) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    root = datapacks_dir(config)
    if not root.exists():
        return results
    for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if path.name.startswith("."):
            continue
        info: dict[str, Any] = {
            "name": path.name,
            "type": "folder" if path.is_dir() else path.suffix.lower().lstrip("."),
            "path": path.relative_to(config.root).as_posix(),
        }
        mcmeta = path / "pack.mcmeta" if path.is_dir() else None
        if mcmeta and mcmeta.exists():
            try:
                pack = json.loads(mcmeta.read_text(encoding="utf-8-sig")).get("pack", {})
                info["pack_format"] = pack.get("pack_format")
                info["description"] = pack.get("description")
            except Exception as exc:
                info["mcmeta_error"] = str(exc)
        results.append(info)
    return results


def iter_datapack_files(config: ServerConfig):
    root = datapacks_dir(config)
    if not root.exists():
        return
    for dp in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if dp.is_dir():
            for file in dp.rglob("*"):
                if file.is_file():
                    yield dp.name, file.relative_to(dp).as_posix(), file
        elif dp.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(dp) as zf:
                    for name in zf.namelist():
                        if not name.endswith("/"):
                            yield dp.name, name, dp
            except zipfile.BadZipFile:
                yield dp.name, "<bad-zip>", dp


def validate_datapacks(config: ServerConfig) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    resource_keys: dict[str, list[str]] = {}
    root = datapacks_dir(config)
    if not root.exists():
        return {"json_errors": errors, "unexpected_duplicate_resources": {}}
    for dp in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if dp.is_dir():
            for file in dp.rglob("*"):
                if file.is_file():
                    rel = file.relative_to(dp).as_posix()
                    _track_resource(resource_keys, dp.name, rel)
                    if file.suffix == ".json":
                        try:
                            json.loads(file.read_text(encoding="utf-8-sig"))
                        except Exception as exc:
                            errors.append({"pack": dp.name, "file": rel, "error": str(exc)})
        elif dp.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(dp) as zf:
                    for name in zf.namelist():
                        _track_resource(resource_keys, dp.name, name)
                        if name.endswith(".json"):
                            try:
                                json.loads(zf.read(name).decode("utf-8-sig"))
                            except Exception as exc:
                                errors.append({"pack": dp.name, "file": name, "error": str(exc)})
            except Exception as exc:
                errors.append({"pack": dp.name, "file": "<zip>", "error": str(exc)})
    duplicates = {
        key: packs for key, packs in resource_keys.items()
        if len(packs) > 1 and key not in {"minecraft/tags/functions/load.json", "minecraft/tags/functions/tick.json"}
    }
    return {"json_errors": errors, "unexpected_duplicate_resources": duplicates}


def _track_resource(resource_keys: dict[str, list[str]], pack: str, rel: str) -> None:
    rel = rel.replace("\\", "/")
    if rel.startswith("data/") and rel.endswith((".json", ".mcfunction", ".nbt")):
        resource_keys.setdefault(rel[len("data/"):], []).append(pack)


def search_datapack_files(config: ServerConfig, query: str, namespace: str = "") -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    query = query.lower()
    for pack, rel, source in iter_datapack_files(config):
        rel_lower = rel.lower()
        if namespace and not rel_lower.startswith(f"data/{namespace.lower()}/"):
            continue
        if query in rel_lower:
            results.append({"pack": pack, "path": rel, "source": str(source)})
    return results[:200]


def read_datapack_file(config: ServerConfig, pack: str, inner_path: str) -> str:
    root = datapacks_dir(config)
    dp = root / pack
    if dp.is_dir():
        target = (dp / inner_path).resolve()
        target.relative_to(dp.resolve())
        return target.read_text(encoding="utf-8", errors="replace")
    if dp.suffix.lower() == ".zip":
        with zipfile.ZipFile(dp) as zf:
            return zf.read(inner_path).decode("utf-8", errors="replace")
    raise FileNotFoundError(pack)


def write_datapack_file(config: ServerConfig, pack: str, inner_path: str, content: str) -> str:
    root = datapacks_dir(config)
    dp = root / pack
    if dp.is_dir():
        target = resolve_under_root(config, dp.relative_to(config.root) / inner_path, write=True)
        backup = begin_write(config, f"write_datapack_file {pack}/{inner_path}", [target])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        backup.write_manifest()
        return json.dumps({"ok": True, "backup": str(backup.root)}, ensure_ascii=False)
    if dp.suffix.lower() == ".zip":
        backup = begin_write(config, f"write_datapack_zip_file {pack}/{inner_path}", [dp])
        tmp = dp.with_suffix(dp.suffix + ".tmp")
        with zipfile.ZipFile(dp) as src, zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            written = False
            for info in src.infolist():
                if info.filename == inner_path:
                    dst.writestr(info, content.encode("utf-8"))
                    written = True
                else:
                    dst.writestr(info, src.read(info.filename))
            if not written:
                dst.writestr(inner_path, content.encode("utf-8"))
        tmp.replace(dp)
        backup.write_manifest()
        return json.dumps({"ok": True, "backup": str(backup.root)}, ensure_ascii=False)
    raise FileNotFoundError(pack)

