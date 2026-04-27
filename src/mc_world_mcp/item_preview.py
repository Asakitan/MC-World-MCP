from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import nbtlib
from PIL import Image, ImageChops, ImageDraw, ImageFont, UnidentifiedImageError

from .config import ServerConfig
from .paths import resolve_under_root
from .preview import _check_preview_size, _preview_path, _save_preview, color_for_block

try:
    from . import _preview_accel as _PREVIEW_ACCEL
except Exception:
    _PREVIEW_ACCEL = None


_ARCHIVE_SUFFIXES = {".jar", ".zip"}
_DEFAULT_VIEWS = ["front", "right", "back", "left", "top", "oblique"]
_VIEW_CODES = {
    "front": 0,
    "back": 1,
    "left": 2,
    "right": 3,
    "top": 4,
    "bottom": 5,
    "isometric": 6,
    "oblique": 7,
}
_VIEW_ALIASES = {
    "front": "front",
    "gui": "front",
    "inventory": "front",
    "back": "back",
    "left": "left",
    "right": "right",
    "top": "top",
    "bottom": "bottom",
    "iso": "isometric",
    "isometric": "isometric",
    "diagonal": "oblique",
    "angled": "oblique",
    "oblique": "oblique",
}

_MAX_DAMAGE = {
    "wooden": 59,
    "stone": 131,
    "iron": 250,
    "diamond": 1561,
    "golden": 32,
    "netherite": 2031,
    "trident": 250,
    "bow": 384,
    "crossbow": 465,
    "fishing_rod": 64,
    "shears": 238,
    "shield": 336,
    "flint_and_steel": 64,
    "carrot_on_a_stick": 25,
    "warped_fungus_on_a_stick": 100,
    "elytra": 432,
    "leather_helmet": 55,
    "leather_chestplate": 80,
    "leather_leggings": 75,
    "leather_boots": 65,
    "chainmail_helmet": 165,
    "chainmail_chestplate": 240,
    "chainmail_leggings": 225,
    "chainmail_boots": 195,
    "iron_helmet": 165,
    "iron_chestplate": 240,
    "iron_leggings": 225,
    "iron_boots": 195,
    "diamond_helmet": 363,
    "diamond_chestplate": 528,
    "diamond_leggings": 495,
    "diamond_boots": 429,
    "golden_helmet": 77,
    "golden_chestplate": 112,
    "golden_leggings": 105,
    "golden_boots": 91,
    "netherite_helmet": 407,
    "netherite_chestplate": 592,
    "netherite_leggings": 555,
    "netherite_boots": 481,
    "turtle_helmet": 275,
}


@dataclass(frozen=True)
class _ItemStack:
    item_id: str
    count: int
    tag: Any
    components: Any
    custom_model_data: int | None
    damage: int
    max_damage: int | None
    dyed_color: tuple[int, int, int] | None
    potion_color: tuple[int, int, int] | None
    enchanted: bool


@dataclass(frozen=True)
class _ResourceSource:
    path: Path
    label: str
    archive: bool

    def read_bytes(self, inner_path: str) -> bytes | None:
        if self.archive:
            try:
                with zipfile.ZipFile(self.path) as zf:
                    try:
                        return zf.read(inner_path)
                    except KeyError:
                        return None
            except zipfile.BadZipFile:
                return None
        target = self.path / inner_path
        if target.is_file():
            return target.read_bytes()
        return None


@dataclass
class _LoadedModel:
    model_id: str
    data: dict[str, Any]
    found: bool
    source: str | None


class _ResourceIndex:
    def __init__(self, sources: list[_ResourceSource]) -> None:
        self.sources = sources

    def read_bytes(self, inner_path: str) -> tuple[bytes, str] | tuple[None, None]:
        normalized = inner_path.replace("\\", "/")
        for source in self.sources:
            data = source.read_bytes(normalized)
            if data is not None:
                return data, source.label
        return None, None

    def read_json(self, inner_path: str) -> tuple[dict[str, Any], str] | tuple[None, None]:
        data, source = self.read_bytes(inner_path)
        if data is None:
            return None, None
        try:
            return json.loads(data.decode("utf-8")), source
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, None


def render_item_nbt_preview(
    config: ServerConfig,
    item_snbt: str,
    views: Iterable[str] | str | None = None,
    size: int = 128,
    resource_path: str = "",
    background: str = "transparent",
) -> dict[str, Any]:
    """Render an item stack SNBT preview using local asset models when present."""
    stack = _parse_item_stack(item_snbt)
    normalized_views = _normalize_views(views)
    size = _normalize_size(size)
    _check_preview_size(size * size * len(normalized_views))

    resources = _ResourceIndex(_resource_sources(config, resource_path))
    base_model_id = _item_model_id(stack.item_id)
    model_cache: dict[str, _LoadedModel] = {}
    base_model = _load_model(resources, base_model_id, model_cache)
    selected_model, matched_overrides = _select_model_for_stack(stack, resources, base_model, model_cache)
    icon, texture_info = _icon_from_model(resources, selected_model, stack)

    if texture_info["fallback"]:
        icon = _fallback_icon(stack, icon.size if icon is not None else (32, 32))
    if stack.dyed_color is not None and _is_dyeable(stack.item_id):
        icon = _tint_image(icon, stack.dyed_color)
    if stack.enchanted:
        icon = _apply_enchantment_glint(icon)
    if stack.max_damage and stack.damage > 0:
        _draw_damage_bar(icon, stack.damage, stack.max_damage)
    if stack.count > 1:
        _draw_count(icon, stack.count)

    bg = _parse_background(background)
    rendered = [_render_view(icon, view, size, bg) for view in normalized_views]
    sheet = Image.new("RGBA", (size * len(rendered), size), bg)
    for index, image in enumerate(rendered):
        sheet.alpha_composite(image, (index * size, 0))
    path = _preview_path(config, "item")
    _save_preview(sheet, path)

    return {
        "ok": True,
        "path": str(path),
        "item": {
            "id": stack.item_id,
            "count": stack.count,
            "custom_model_data": stack.custom_model_data,
            "damage": stack.damage,
            "max_damage": stack.max_damage,
            "enchanted": stack.enchanted,
            "dyed_color": list(stack.dyed_color) if stack.dyed_color else None,
            "potion_color": list(stack.potion_color) if stack.potion_color else None,
        },
        "views": normalized_views,
        "size": {"view": size, "width": sheet.width, "height": sheet.height},
        "model": {
            "base": base_model_id,
            "selected": selected_model.model_id,
            "model_found": selected_model.found,
            "model_source": selected_model.source,
            "matched_overrides": matched_overrides,
        },
        "textures": texture_info,
        "rendering": {
            "accelerated_recomputation": _item_view_acceleration_available(),
        },
        "resource_sources": [source.label for source in resources.sources],
    }


def _parse_item_stack(item_snbt: str) -> _ItemStack:
    text = str(item_snbt).strip()
    if not text:
        raise ValueError("item_snbt must be an SNBT compound or item id")
    if text.startswith("{"):
        value = nbtlib.parse_nbt(text)
        if not isinstance(value, nbtlib.Compound):
            raise ValueError("item_snbt must parse to an SNBT compound")
        item_id = _string_value(value.get("id") or value.get("item") or value.get("Name"))
        count = _int_value(value.get("Count"), 1)
        tag = value.get("tag", nbtlib.Compound())
        components = value.get("components", nbtlib.Compound())
    else:
        item_id = text
        count = 1
        tag = nbtlib.Compound()
        components = nbtlib.Compound()
    if not item_id:
        raise ValueError("item_snbt must include an item id")
    item_id = _normalize_item_id(item_id)
    custom_model_data = _custom_model_data(tag, components)
    damage = _int_value(_lookup_component(tag, components, "Damage", "minecraft:damage"), 0)
    max_damage = _known_max_damage(item_id)
    dyed_color = _color_value(_lookup_component(tag, components, "display.color", "minecraft:dyed_color"))
    potion_color = _color_value(_lookup_component(tag, components, "CustomPotionColor", "minecraft:potion_contents.custom_color"))
    enchanted = _has_enchantments(tag, components)
    return _ItemStack(
        item_id=item_id,
        count=max(1, count),
        tag=tag,
        components=components,
        custom_model_data=custom_model_data,
        damage=max(0, damage),
        max_damage=max_damage,
        dyed_color=dyed_color,
        potion_color=potion_color,
        enchanted=enchanted,
    )


def _normalize_item_id(item_id: str) -> str:
    value = item_id.strip()
    if ":" not in value:
        value = f"minecraft:{value}"
    return value


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _int_value(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _custom_model_data(tag: Any, components: Any) -> int | None:
    value = _lookup_component(tag, components, "CustomModelData", "minecraft:custom_model_data")
    if value is None:
        return None
    if isinstance(value, nbtlib.Compound):
        for key in ("value", "floats"):
            nested = value.get(key)
            if isinstance(nested, list) and nested:
                return _int_value(nested[0])
            if nested is not None:
                return _int_value(nested)
    return _int_value(value)


def _lookup_component(tag: Any, components: Any, legacy_path: str, component_path: str) -> Any:
    value = _get_path(tag, legacy_path)
    if value is not None:
        return value
    return _get_path(components, component_path)


def _get_path(root: Any, path: str) -> Any:
    current = root
    for part in path.split("."):
        if isinstance(current, (nbtlib.Compound, dict)) and part in current:
            current = current[part]
        else:
            return None
    return current


def _color_value(value: Any) -> tuple[int, int, int] | None:
    if value is None:
        return None
    if isinstance(value, nbtlib.Compound):
        for key in ("rgb", "color", "value"):
            if key in value:
                return _color_value(value[key])
    raw = _int_value(value, -1)
    if raw < 0:
        return None
    return ((raw >> 16) & 255, (raw >> 8) & 255, raw & 255)


def _has_enchantments(tag: Any, components: Any) -> bool:
    for key in ("Enchantments", "StoredEnchantments"):
        value = tag.get(key) if isinstance(tag, (nbtlib.Compound, dict)) else None
        if value:
            return True
    value = components.get("minecraft:enchantments") if isinstance(components, (nbtlib.Compound, dict)) else None
    if isinstance(value, (nbtlib.Compound, dict)):
        levels = value.get("levels")
        return bool(levels)
    return bool(value)


def _known_max_damage(item_id: str) -> int | None:
    name = item_id.split(":", 1)[1]
    if name in _MAX_DAMAGE:
        return _MAX_DAMAGE[name]
    for material in ("wooden", "stone", "iron", "diamond", "golden", "netherite"):
        if name.startswith(f"{material}_") and name.rsplit("_", 1)[-1] in {"sword", "pickaxe", "axe", "shovel", "hoe"}:
            return _MAX_DAMAGE[material]
    return None


def _resource_sources(config: ServerConfig, resource_path: str) -> list[_ResourceSource]:
    if resource_path:
        target = resolve_under_root(config, resource_path)
        if not _is_resource_source(target):
            raise ValueError("resource_path must point to a resource-pack folder, .zip, or .jar")
        return [_source_from_path(target)]

    sources: list[_ResourceSource] = []
    for base in (config.root / "resourcepacks", config.root / "mods", config.root / "plugins", config.world / "datapacks"):
        if not base.exists():
            continue
        children = sorted(base.iterdir(), key=lambda item: item.name.lower(), reverse=True)
        for child in children:
            if _is_resource_source(child):
                sources.append(_source_from_path(child))
    return sources


def _is_resource_source(path: Path) -> bool:
    return path.is_dir() or (path.is_file() and path.suffix.lower() in _ARCHIVE_SUFFIXES)


def _source_from_path(path: Path) -> _ResourceSource:
    archive = path.is_file() and path.suffix.lower() in _ARCHIVE_SUFFIXES
    return _ResourceSource(path=path, label=str(path), archive=archive)


def _item_model_id(item_id: str) -> str:
    namespace, name = item_id.split(":", 1)
    return f"{namespace}:item/{name}"


def _load_model(index: _ResourceIndex, model_id: str, cache: dict[str, _LoadedModel], seen: frozenset[str] = frozenset()) -> _LoadedModel:
    normalized = _normalize_model_id(model_id)
    if normalized in cache:
        return cache[normalized]
    if normalized in seen:
        return _LoadedModel(normalized, {}, False, None)

    data, source = index.read_json(_model_resource_path(normalized))
    if data is None:
        loaded = _LoadedModel(normalized, {}, False, None)
        cache[normalized] = loaded
        return loaded

    merged = dict(data)
    parent_id = data.get("parent")
    if isinstance(parent_id, str) and not parent_id.startswith("builtin/"):
        parent = _load_model(index, _normalize_model_id(parent_id, _namespace(normalized)), cache, seen | {normalized})
        if parent.data:
            merged = _merge_model_data(parent.data, data)
    loaded = _LoadedModel(normalized, merged, True, source)
    cache[normalized] = loaded
    return loaded


def _merge_model_data(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    merged = dict(parent)
    for key, value in child.items():
        if key == "textures" and isinstance(value, dict):
            textures = dict(parent.get("textures", {}))
            textures.update(value)
            merged[key] = textures
        elif key == "display" and isinstance(value, dict):
            display = dict(parent.get("display", {}))
            display.update(value)
            merged[key] = display
        else:
            merged[key] = value
    return merged


def _select_model_for_stack(
    stack: _ItemStack,
    resources: _ResourceIndex,
    base_model: _LoadedModel,
    model_cache: dict[str, _LoadedModel],
) -> tuple[_LoadedModel, list[dict[str, Any]]]:
    selected = base_model
    matched: list[dict[str, Any]] = []
    seen = {selected.model_id}
    for _ in range(8):
        override_model = None
        override_predicate = None
        for override in selected.data.get("overrides", []):
            predicate = override.get("predicate", {})
            if isinstance(predicate, dict) and _predicate_matches(stack, predicate):
                override_model = override.get("model")
                override_predicate = predicate
        if not isinstance(override_model, str):
            break
        candidate_id = _normalize_model_id(override_model, _namespace(selected.model_id))
        if candidate_id in seen:
            break
        seen.add(candidate_id)
        candidate = _load_model(resources, candidate_id, model_cache)
        matched.append({"model": candidate_id, "predicate": override_predicate or {}, "found": candidate.found})
        selected = candidate
    return selected, matched


def _predicate_matches(stack: _ItemStack, predicate: dict[str, Any]) -> bool:
    for key, threshold in predicate.items():
        required = _float_value(threshold)
        if key == "custom_model_data":
            if stack.custom_model_data is None or stack.custom_model_data < required:
                return False
        elif key == "damage":
            if not stack.max_damage or (stack.damage / stack.max_damage) < required:
                return False
        elif key == "damaged":
            if (1.0 if stack.damage > 0 else 0.0) < required:
                return False
        elif key == "charged":
            charged = bool(_get_path(stack.tag, "ChargedProjectiles"))
            if (1.0 if charged else 0.0) < required:
                return False
        elif key in {"lefthanded", "pulling", "blocking", "cast", "firework"}:
            if required > 0:
                return False
        else:
            value = _get_path(stack.tag, key)
            if value is None or _float_value(value) < required:
                return False
    return True


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _model_resource_path(model_id: str) -> str:
    namespace, model_path = model_id.split(":", 1)
    return f"assets/{namespace}/models/{model_path}.json"


def _texture_resource_path(texture_id: str) -> str:
    namespace, texture_path = texture_id.split(":", 1)
    return f"assets/{namespace}/textures/{texture_path}.png"


def _normalize_model_id(model_id: str, default_namespace: str = "minecraft") -> str:
    if ":" not in model_id:
        return f"{default_namespace}:{model_id}"
    return model_id


def _namespace(resource_id: str) -> str:
    return resource_id.split(":", 1)[0]


def _icon_from_model(resources: _ResourceIndex, model: _LoadedModel, stack: _ItemStack) -> tuple[Image.Image | None, dict[str, Any]]:
    textures = model.data.get("textures", {})
    if not isinstance(textures, dict):
        textures = {}
    layer_keys = _texture_layer_keys(textures)
    loaded_layers: list[Image.Image] = []
    texture_layers: list[dict[str, Any]] = []
    base_size: tuple[int, int] | None = None
    for order, key in enumerate(layer_keys):
        texture_id = _resolve_texture_reference(key, textures, _namespace(model.model_id))
        if not texture_id:
            continue
        raw, source = resources.read_bytes(_texture_resource_path(texture_id))
        if raw is None:
            texture_layers.append({"key": key, "texture": texture_id, "found": False, "source": None})
            continue
        try:
            layer = Image.open(io.BytesIO(raw)).convert("RGBA")
        except UnidentifiedImageError:
            texture_layers.append({"key": key, "texture": texture_id, "found": False, "source": source})
            continue
        if base_size is None:
            base_size = layer.size
        elif layer.size != base_size:
            layer = layer.resize(base_size, Image.Resampling.NEAREST)
        if _should_tint_layer(stack, key, texture_id, order):
            tint = stack.dyed_color if stack.dyed_color is not None else stack.potion_color
            if tint is not None:
                layer = _tint_image(layer, tint)
        loaded_layers.append(layer)
        texture_layers.append({"key": key, "texture": texture_id, "found": True, "source": source})

    if not loaded_layers:
        return None, {"fallback": True, "layers": texture_layers, "reason": "no readable texture layers"}

    icon = Image.new("RGBA", base_size or loaded_layers[0].size, (0, 0, 0, 0))
    for layer in loaded_layers:
        icon.alpha_composite(layer)
    return icon, {"fallback": False, "layers": texture_layers, "reason": ""}


def _texture_layer_keys(textures: dict[str, Any]) -> list[str]:
    numbered = []
    for key in textures:
        if key.startswith("layer") and key[5:].isdigit():
            numbered.append((int(key[5:]), key))
    if numbered:
        return [key for _, key in sorted(numbered)]
    for key in ("all", "front", "side", "top", "particle"):
        if key in textures:
            return [key]
    return []


def _resolve_texture_reference(key: str, textures: dict[str, Any], default_namespace: str) -> str:
    value = textures.get(key)
    seen = set()
    while isinstance(value, str) and value.startswith("#"):
        ref = value[1:]
        if ref in seen:
            return ""
        seen.add(ref)
        value = textures.get(ref)
    if not isinstance(value, str) or not value:
        return ""
    if ":" not in value:
        return f"{default_namespace}:{value}"
    return value


def _should_tint_layer(stack: _ItemStack, key: str, texture_id: str, order: int) -> bool:
    if stack.dyed_color is not None and _is_dyeable(stack.item_id):
        return key == "layer0" or "leather" in texture_id
    if stack.potion_color is not None and ("potion" in stack.item_id or "tipped_arrow" in stack.item_id):
        return order > 0 or "overlay" in texture_id
    return False


def _is_dyeable(item_id: str) -> bool:
    name = item_id.split(":", 1)[1]
    return name.startswith("leather_") or name in {"shield"}


def _fallback_icon(stack: _ItemStack, size: tuple[int, int]) -> Image.Image:
    width, height = max(16, size[0]), max(16, size[1])
    icon = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    base = color_for_block(stack.item_id)
    accent = _hashed_color(stack.item_id)
    margin = max(2, min(width, height) // 8)
    draw.rounded_rectangle(
        (margin, margin, width - margin - 1, height - margin - 1),
        radius=max(2, min(width, height) // 8),
        fill=(*base, 230),
        outline=(*accent, 255),
        width=max(1, min(width, height) // 16),
    )
    draw.polygon(
        [
            (width // 2, margin * 2),
            (width - margin * 2, height // 2),
            (width // 2, height - margin * 2),
            (margin * 2, height // 2),
        ],
        fill=(*accent, 190),
    )
    return icon


def _hashed_color(value: str) -> tuple[int, int, int]:
    digest = hashlib.sha1(value.encode("utf-8")).digest()
    return (80 + digest[0] % 140, 80 + digest[1] % 140, 80 + digest[2] % 140)


def _tint_image(image: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    tint = Image.new("RGBA", image.size, (*color, 255))
    tinted = ImageChops.multiply(image.convert("RGBA"), tint)
    tinted.putalpha(image.getchannel("A"))
    return tinted


def _apply_enchantment_glint(image: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    step = max(4, image.width // 4)
    for x in range(-image.height, image.width + image.height, step):
        draw.line((x, image.height, x + image.height, 0), fill=(178, 96, 255, 70), width=max(1, image.width // 16))
    alpha = ImageChops.multiply(overlay.getchannel("A"), image.getchannel("A"))
    overlay.putalpha(alpha)
    result = image.copy()
    result.alpha_composite(overlay)
    return result


def _draw_damage_bar(image: Image.Image, damage: int, max_damage: int) -> None:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    bar_width = max(1, width - 4)
    remaining = max(0.0, min(1.0, 1.0 - damage / max_damage))
    filled = max(1, int(bar_width * remaining))
    y = height - max(3, height // 10)
    hue = int(255 * remaining)
    color = (255 - hue, hue, 40, 255)
    draw.rectangle((2, y, width - 3, y + 1), fill=(0, 0, 0, 210))
    draw.rectangle((2, y, 1 + filled, y + 1), fill=color)


def _draw_count(image: Image.Image, count: int) -> None:
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    text = str(count)
    box = draw.textbbox((0, 0), text, font=font)
    x = max(0, image.width - (box[2] - box[0]) - 2)
    y = max(0, image.height - (box[3] - box[1]) - 2)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        draw.text((x + dx, y + dy), text, fill=(25, 25, 25, 230), font=font)
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)


def _render_view(icon: Image.Image, view: str, size: int, background: tuple[int, int, int, int]) -> Image.Image:
    accelerated = _render_view_accelerated(icon, view, size, background)
    if accelerated is not None:
        return accelerated
    if view == "front":
        return _centered_icon(icon, size, background)
    if view == "back":
        return _centered_icon(icon.transpose(Image.Transpose.FLIP_LEFT_RIGHT), size, background)
    if view in {"left", "right"}:
        return _edge_view(icon, size, background, vertical=True, flip=view == "left")
    if view in {"top", "bottom"}:
        return _edge_view(icon, size, background, vertical=False, flip=view == "bottom")
    if view == "isometric":
        return _angled_view(icon, size, background, rotation=45, y_scale=0.58, depth=max(2, size // 18))
    if view == "oblique":
        return _angled_view(icon, size, background, rotation=-28, y_scale=0.78, depth=max(3, size // 12))
    raise ValueError(f"unsupported view: {view}")


def _item_view_acceleration_available() -> bool:
    return _PREVIEW_ACCEL is not None and hasattr(_PREVIEW_ACCEL, "render_item_view_rgba")


def _render_view_accelerated(
    icon: Image.Image,
    view: str,
    size: int,
    background: tuple[int, int, int, int],
) -> Image.Image | None:
    if not _item_view_acceleration_available():
        return None
    code = _VIEW_CODES.get(view)
    if code is None:
        return None
    rgba = icon.convert("RGBA")
    try:
        data = _PREVIEW_ACCEL.render_item_view_rgba(rgba.tobytes(), rgba.width, rgba.height, code, size, background)
    except Exception:
        return None
    return Image.frombytes("RGBA", (size, size), data)


def _centered_icon(icon: Image.Image, size: int, background: tuple[int, int, int, int]) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), background)
    fitted = _fit(icon, int(size * 0.78), int(size * 0.78))
    canvas.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    return canvas


def _edge_view(icon: Image.Image, size: int, background: tuple[int, int, int, int], *, vertical: bool, flip: bool) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), background)
    if vertical:
        fitted = _fit(icon, max(2, size // 8), int(size * 0.72))
    else:
        fitted = _fit(icon, int(size * 0.72), max(2, size // 8))
    if flip:
        fitted = fitted.transpose(Image.Transpose.FLIP_TOP_BOTTOM if vertical else Image.Transpose.FLIP_LEFT_RIGHT)
    canvas.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    return canvas


def _angled_view(
    icon: Image.Image,
    size: int,
    background: tuple[int, int, int, int],
    *,
    rotation: float,
    y_scale: float,
    depth: int,
) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), background)
    base = _fit(icon, int(size * 0.62), int(size * 0.62))
    shadow = _tint_alpha(base, (28, 26, 36), 95)
    for offset in range(depth, 0, -1):
        shifted = shadow.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
        shifted = shifted.resize((shifted.width, max(1, int(shifted.height * y_scale))), Image.Resampling.BICUBIC)
        canvas.alpha_composite(shifted, ((size - shifted.width) // 2 + offset, (size - shifted.height) // 2 + offset))
    angled = base.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
    angled = angled.resize((angled.width, max(1, int(angled.height * y_scale))), Image.Resampling.BICUBIC)
    canvas.alpha_composite(angled, ((size - angled.width) // 2, (size - angled.height) // 2))
    return canvas


def _fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    ratio = min(max_width / image.width, max_height / image.height)
    width = max(1, int(image.width * ratio))
    height = max(1, int(image.height * ratio))
    return image.resize((width, height), Image.Resampling.NEAREST)


def _tint_alpha(image: Image.Image, color: tuple[int, int, int], alpha: int) -> Image.Image:
    tinted = Image.new("RGBA", image.size, (*color, alpha))
    tinted.putalpha(ImageChops.multiply(image.getchannel("A"), Image.new("L", image.size, alpha)))
    return tinted


def _normalize_views(views: Iterable[str] | str | None) -> list[str]:
    if views is None:
        raw_views = list(_DEFAULT_VIEWS)
    elif isinstance(views, str):
        raw_views = [item for part in views.split(",") for item in part.split()]
    else:
        raw_views = [str(view) for view in views]
    normalized: list[str] = []
    for view in raw_views:
        key = view.strip().lower().replace("-", "_")
        if not key:
            continue
        if key not in _VIEW_ALIASES:
            raise ValueError(f"unsupported view '{view}'; use front, back, left, right, top, bottom, isometric, or oblique")
        normalized.append(_VIEW_ALIASES[key])
    if not normalized:
        raise ValueError("at least one view is required")
    return normalized


def _normalize_size(size: int) -> int:
    try:
        value = int(size)
    except (TypeError, ValueError):
        raise ValueError("size must be a positive integer") from None
    if value < 16 or value > 1024:
        raise ValueError("size must be between 16 and 1024")
    return value


def _parse_background(background: str) -> tuple[int, int, int, int]:
    value = str(background).strip().lower()
    if value in {"", "transparent", "none"}:
        return (0, 0, 0, 0)
    named = {
        "white": (255, 255, 255, 255),
        "black": (0, 0, 0, 255),
        "gray": (128, 128, 128, 255),
        "grey": (128, 128, 128, 255),
    }
    if value in named:
        return named[value]
    if value.startswith("#") and len(value) in {7, 9}:
        try:
            red = int(value[1:3], 16)
            green = int(value[3:5], 16)
            blue = int(value[5:7], 16)
            alpha = int(value[7:9], 16) if len(value) == 9 else 255
            return (red, green, blue, alpha)
        except ValueError:
            pass
    raise ValueError("background must be transparent, a named color, or #RRGGBB/#RRGGBBAA")
