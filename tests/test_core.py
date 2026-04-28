from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

import nbtlib
from PIL import Image

from mc_world_mcp.anvil import RegionFile, fill_blocks, get_block, load_chunk_with_cache, read_block_box, region_coords, replace_blocks, set_block
from mc_world_mcp.assistant_guidance import SERVER_INSTRUCTIONS, assistant_instruction_markdown, assistant_instruction_payload
from mc_world_mcp.compat import detect_world_info
from mc_world_mcp.config import ServerConfig, discover_server_roots, load_config, make_config
from mc_world_mcp.datapacks import read_datapack_file, search_datapack_files, validate_datapacks
from mc_world_mcp.item_preview import render_item_nbt_preview
from mc_world_mcp.nbt_io import get_at_path, parse_path, read_nbt_file, write_nbt_value
from mc_world_mcp.paths import resolve_under_root
from mc_world_mcp.preview import render_closeup_map_preview, render_map_preview, render_slice_preview, render_template_preview
from mc_world_mcp.safety import assert_offline, java_processes
from mc_world_mcp.source_worlds import compare_world_chunks, import_chunks_from_world, list_local_worlds, simulate_worldgen_generation, worldgen_source_plan
from mc_world_mcp.templates import export_region_to_template, list_structure_templates
from mc_world_mcp.world_ops import _biome_local_index, _decode_biome_indices, add_block_entity, add_entity, set_biome_box, write_chunk_nbt_value
from mc_world_mcp.worldgen import list_generation_interfaces, validate_worldgen_references


class CoreTests(unittest.TestCase):
    def test_assistant_guidance_is_mcp_visible_content(self) -> None:
        payload = assistant_instruction_payload()
        self.assertIn("assistant_instructions", SERVER_INSTRUCTIONS)
        self.assertEqual(payload["tool_order"][0]["tools"][0], "server_summary")
        self.assertIn("Source World Workflow", assistant_instruction_markdown())

    def test_java_process_filter_ignores_minecraft_client(self) -> None:
        raw = [
            {
                "Name": "javaw.exe",
                "ProcessId": 11,
                "CommandLine": r"C:\Java\bin\javaw.exe -Dminecraft.launcher.brand=minecraft-launcher net.minecraft.client.main.Main --username Player",
            },
            {
                "Name": "java.exe",
                "ProcessId": 12,
                "CommandLine": r"C:\Java\bin\java.exe -jar arclight-forge-1.20.1.jar nogui",
            },
            {
                "Name": "java.exe",
                "ProcessId": 13,
                "CommandLine": r"C:\Java\bin\java.exe -jar custom-tool.jar",
            },
        ]
        with mock.patch("mc_world_mcp.safety._raw_java_processes", return_value=raw):
            blocking = java_processes()
            all_processes = java_processes(include_clients=True)
        self.assertEqual([item["ProcessId"] for item in blocking], [12, 13])
        self.assertEqual(all_processes[0]["classification"], "minecraft_client")
        self.assertEqual(blocking[0]["classification"], "minecraft_server")
        self.assertEqual(blocking[1]["classification"], "unknown_java")

    def test_assert_offline_allows_minecraft_client_java(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            config.world.mkdir()
            raw = [{
                "Name": "javaw.exe",
                "ProcessId": 11,
                "CommandLine": r"C:\Java\bin\javaw.exe net.minecraft.client.main.Main --username Player --assetsDir C:\Users\me\AppData\Roaming\.minecraft\assets",
            }]
            with mock.patch("mc_world_mcp.safety._raw_java_processes", return_value=raw):
                assert_offline(config)

    def _basic_world(self, tmp: str) -> tuple[ServerConfig, Path, RegionFile]:
        config = ServerConfig(Path(tmp).resolve())
        world = Path(tmp) / "world"
        (world / "region").mkdir(parents=True)
        nbtlib.File({"Data": nbtlib.Compound({"DataVersion": nbtlib.Int(3465)})}).save(world / "level.dat")
        region = RegionFile(world / "region" / "r.0.0.mca")
        raw = io.BytesIO()
        nbtlib.File({
            "xPos": nbtlib.Int(0),
            "zPos": nbtlib.Int(0),
            "sections": nbtlib.List[nbtlib.Compound]([
                nbtlib.Compound({
                    "Y": nbtlib.Byte(0),
                    "block_states": nbtlib.Compound({
                        "palette": nbtlib.List[nbtlib.Compound]([
                            nbtlib.Compound({"Name": nbtlib.String("minecraft:air")})
                        ])
                    }),
                })
            ]),
            "block_entities": nbtlib.List[nbtlib.Compound](),
            "Status": nbtlib.String("minecraft:full"),
        }).write(raw)
        region.set_raw(0, raw.getvalue())
        region.write()
        return config, world, region

    def _write_single_palette_chunk(self, world: Path, block: str, cx: int = 0, cz: int = 0) -> None:
        (world / "region").mkdir(parents=True, exist_ok=True)
        nbtlib.File({"Data": nbtlib.Compound({"DataVersion": nbtlib.Int(3465)})}).save(world / "level.dat")
        rx, rz, index = region_coords(cx, cz)
        region = RegionFile(world / "region" / f"r.{rx}.{rz}.mca")
        raw = io.BytesIO()
        nbtlib.File({
            "xPos": nbtlib.Int(cx),
            "zPos": nbtlib.Int(cz),
            "sections": nbtlib.List[nbtlib.Compound]([
                nbtlib.Compound({
                    "Y": nbtlib.Byte(0),
                    "block_states": nbtlib.Compound({
                        "palette": nbtlib.List[nbtlib.Compound]([
                            nbtlib.Compound({"Name": nbtlib.String(block)})
                        ])
                    }),
                })
            ]),
            "block_entities": nbtlib.List[nbtlib.Compound](),
            "Status": nbtlib.String("minecraft:full"),
        }).write(raw)
        region.set_raw(index, raw.getvalue())
        region.write()

    def _write_1_21_1_chunk(self, world: Path, block: str, cx: int = 0, cz: int = 0) -> None:
        (world / "region").mkdir(parents=True, exist_ok=True)
        nbtlib.File({
            "Data": nbtlib.Compound({
                "DataVersion": nbtlib.Int(3955),
                "Version": nbtlib.Compound({
                    "Id": nbtlib.Int(3955),
                    "Name": nbtlib.String("1.21.1"),
                    "Series": nbtlib.String("main"),
                    "Snapshot": nbtlib.Byte(0),
                }),
            })
        }).save(world / "level.dat")
        rx, rz, index = region_coords(cx, cz)
        region = RegionFile(world / "region" / f"r.{rx}.{rz}.mca")
        biome_indices = [0] * 64
        biome_indices[_biome_local_index(1, 0, 0)] = 1
        raw_biome_data = 0
        for i, value in enumerate(biome_indices):
            raw_biome_data |= value << i
        raw = io.BytesIO()
        nbtlib.File({
            "DataVersion": nbtlib.Int(3955),
            "xPos": nbtlib.Int(cx),
            "zPos": nbtlib.Int(cz),
            "yPos": nbtlib.Int(-4),
            "sections": nbtlib.List[nbtlib.Compound]([
                nbtlib.Compound({
                    "Y": nbtlib.Byte(0),
                    "block_states": nbtlib.Compound({
                        "palette": nbtlib.List[nbtlib.Compound]([
                            nbtlib.Compound({"Name": nbtlib.String(block)})
                        ])
                    }),
                    "biomes": nbtlib.Compound({
                        "palette": nbtlib.List[nbtlib.String]([
                            nbtlib.String("minecraft:plains"),
                            nbtlib.String("minecraft:lush_caves"),
                        ]),
                        "data": nbtlib.LongArray([raw_biome_data]),
                    }),
                })
            ]),
            "block_entities": nbtlib.List[nbtlib.Compound](),
            "Status": nbtlib.String("minecraft:full"),
        }).write(raw)
        region.set_raw(index, raw.getvalue())
        region.write()

    def test_path_escape_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            with self.assertRaises(ValueError):
                resolve_under_root(config, "../outside.txt")
            self.assertEqual(
                resolve_under_root(config, Path(tmp) / "global_packs" / "pack" / "data" / "demo.nbt", write=True),
                Path(tmp).resolve() / "global_packs" / "pack" / "data" / "demo.nbt",
            )
            with self.assertRaises(ValueError):
                resolve_under_root(config, Path(tmp).parent / "outside.nbt", write=True)

    def test_nbt_path_parser(self) -> None:
        self.assertEqual(parse_path("Data.WorldGenSettings.dimensions[0]"), ["Data", "WorldGenSettings", "dimensions", 0])

    def test_nbt_read_write_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            world = Path(tmp) / "world"
            world.mkdir()
            path = world / "level.dat"
            data = nbtlib.File({"Data": nbtlib.Compound({"DataVersion": nbtlib.Int(3465), "LevelName": nbtlib.String("old")})})
            data.save(path)
            with mock.patch("mc_world_mcp.safety.java_processes", return_value=[]):
                result = json.loads(write_nbt_value(config, "world/level.dat", "Data.LevelName", '"new"'))
            self.assertTrue(result["ok"])
            self.assertEqual(str(get_at_path(nbtlib.load(path), "Data.LevelName")), "new")
            self.assertIn("new", read_nbt_file(config, "world/level.dat", "Data.LevelName"))

    def test_region_coords(self) -> None:
        self.assertEqual(region_coords(0, 0), (0, 0, 0))
        self.assertEqual(region_coords(31, 31), (0, 0, 1023))
        self.assertEqual(region_coords(32, -1), (1, -1, 992))

    def test_region_file_empty_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.0.0.mca"
            region = RegionFile(path)
            raw = io.BytesIO()
            nbtlib.File({
                "xPos": nbtlib.Int(0),
                "zPos": nbtlib.Int(0),
                "sections": nbtlib.List[nbtlib.Compound](),
                "block_entities": nbtlib.List[nbtlib.Compound](),
                "Status": nbtlib.String("full"),
            }).write(raw)
            region.set_raw(0, raw.getvalue())
            region.write()
            reread = RegionFile(path)
            self.assertIsNotNone(reread.get_raw(0))

    def test_load_chunk_with_cache_reuses_region_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = ServerConfig(root)
            self._write_single_palette_chunk(root / "world", "minecraft:stone", cx=0)
            self._write_single_palette_chunk(root / "world", "minecraft:sand", cx=1)
            reads = 0
            original_read = RegionFile._read

            def counted_read(region: RegionFile) -> None:
                nonlocal reads
                reads += 1
                original_read(region)

            regions: dict[Path, RegionFile] = {}
            with mock.patch.object(RegionFile, "_read", counted_read):
                load_chunk_with_cache(config, 0, 0, "overworld", regions)
                load_chunk_with_cache(config, 1, 0, "overworld", regions)
            self.assertEqual(reads, 1)

    def test_world_name_follows_server_properties(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "server.properties").write_text("level-name=world_regen_source\n", encoding="utf-8")
            (root / "world_regen_source").mkdir()
            config = ServerConfig(root)
            self.assertEqual(config.world_name, "world_regen_source")
            self.assertEqual(config.world, root / "world_regen_source")

    def test_source_world_plan_and_chunk_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "server.properties").write_text("level-name=world\n", encoding="utf-8")
            config = ServerConfig(root)
            self._write_single_palette_chunk(root / "world", "minecraft:air")
            self._write_single_palette_chunk(root / "world_regen_source", "minecraft:stone")

            worlds = list_local_worlds(config)
            self.assertEqual([item["name"] for item in worlds], ["world", "world_regen_source"])
            plan = worldgen_source_plan(config, "world_regen_source")
            self.assertFalse(plan["can_execute_worldgen"])
            comparison = compare_world_chunks(config, "world_regen_source", 0, 0, 0, 0)
            self.assertEqual(comparison["source_present"], 1)
            self.assertEqual(comparison["target_present"], 1)

            with mock.patch("mc_world_mcp.safety.java_processes", return_value=[]):
                result = import_chunks_from_world(
                    config,
                    "world_regen_source",
                    [{"cx": 0, "cz": 0}],
                    include_entities=False,
                    include_poi=False,
                    confirm=True,
                )
            self.assertTrue(result["ok"])
            self.assertEqual(get_block(config, 0, 0, 0), "minecraft:stone")

    def test_worldgen_simulation_reports_source_world_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "server.properties").write_text("level-name=world\n", encoding="utf-8")
            config = ServerConfig(root)
            self._write_single_palette_chunk(root / "world", "minecraft:air")
            self._write_single_palette_chunk(root / "world_regen_source", "minecraft:tube_coral_block")

            result = simulate_worldgen_generation(config, "world_regen_source", 0, 0, 0, 0, sample=8)

            self.assertTrue(result["ok"])
            self.assertTrue(result["success"])
            self.assertTrue(result["complete_requested_area"])
            self.assertEqual(result["generated_chunks"], 1)
            self.assertEqual(result["generation_signal"]["strength"], "medium")
            self.assertEqual(result["appearance"]["notable_blocks"][0]["block"], "minecraft:tube_coral_block")
            self.assertEqual(result["appearance"]["ocean_floor_y"]["max"], 15)
            self.assertTrue(Path(result["previews"]["ocean_floor"]["path"]).exists())
            self.assertIn("datapacks", result["generation_interfaces"])

    def test_generation_interfaces_include_datapacks_mods_and_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = ServerConfig(root)
            dp = root / "world" / "datapacks" / "Demo"
            (dp / "data" / "demo" / "worldgen" / "structure").mkdir(parents=True)
            (dp / "pack.mcmeta").write_text('{"pack":{"pack_format":15,"description":"demo"}}', encoding="utf-8")
            (dp / "data" / "demo" / "worldgen" / "structure" / "reef.json").write_text('{"type":"minecraft:jigsaw"}', encoding="utf-8")
            (root / "mods").mkdir()
            with zipfile.ZipFile(root / "mods" / "demo-mod.jar", "w") as zf:
                zf.writestr("META-INF/mods.toml", "modLoader=\"javafml\"\n")
                zf.writestr("data/demomod/forge/biome_modifier/add_reef.json", "{}")
            (root / "plugins").mkdir()
            with zipfile.ZipFile(root / "plugins" / "demo-plugin.jar", "w") as zf:
                zf.writestr("plugin.yml", "name: Demo\n")
                zf.writestr("data/demoplugin/worldgen/placed_feature/kelp.json", "{}")

            result = list_generation_interfaces(config)

            self.assertEqual(result["datapacks"]["worldgen_resource_count"], 1)
            self.assertEqual(result["mods"]["worldgen_resource_count"], 1)
            self.assertEqual(result["plugins"]["worldgen_resource_count"], 1)
            self.assertEqual(result["mods"]["archives"][0]["metadata"], ["META-INF/mods.toml"])
            self.assertEqual(result["plugins"]["archives"][0]["metadata"], ["plugin.yml"])

    def test_env_world_name_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"MC_SERVER_ROOT": tmp, "MC_WORLD_NAME": "custom"}, clear=False):
            root = Path(tmp)
            (root / "server.properties").write_text("level-name=world\n", encoding="utf-8")
            self.assertEqual(load_config().world_name, "custom")

    def test_workspace_root_auto_resolves_server_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"MC_SERVER_ROOT": tmp}, clear=False):
            workspace = Path(tmp)
            server = workspace / "server"
            world = server / "world"
            world.mkdir(parents=True)
            (server / "server.properties").write_text("level-name=world\n", encoding="utf-8")

            config = load_config()

            self.assertEqual(config.root, server.resolve())
            self.assertEqual(config.world, world.resolve())

    def test_discover_and_make_config_for_server_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            server = workspace / "server"
            world = server / "world"
            world.mkdir(parents=True)
            (server / "server.properties").write_text("level-name=world\n", encoding="utf-8")

            roots = discover_server_roots(workspace)
            config = make_config(workspace)

            self.assertEqual([Path(item["server_root"]) for item in roots], [server.resolve()])
            self.assertTrue(roots[0]["world_exists"])
            self.assertEqual(config.root, server.resolve())

    def test_detect_world_support_levels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            world = Path(tmp) / "world"
            world.mkdir()
            nbtlib.File({"Data": nbtlib.Compound({"DataVersion": nbtlib.Int(3465)})}).save(world / "level.dat")
            self.assertEqual(detect_world_info(config).support_level, "full_1_20_1")
            nbtlib.File({"Data": nbtlib.Compound({"DataVersion": nbtlib.Int(3955)})}).save(world / "level.dat")
            self.assertEqual(detect_world_info(config).support_level, "full_1_21_1")
            nbtlib.File({"Data": nbtlib.Compound({"DataVersion": nbtlib.Int(3700)})}).save(world / "level.dat")
            self.assertEqual(detect_world_info(config).support_level, "readonly_best_effort")

    def test_world_write_rejects_non_1_20_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            world = Path(tmp) / "world"
            world.mkdir()
            path = world / "level.dat"
            nbtlib.File({"Data": nbtlib.Compound({"DataVersion": nbtlib.Int(3700), "LevelName": nbtlib.String("old")})}).save(path)
            with mock.patch("mc_world_mcp.safety.java_processes", return_value=[]), self.assertRaises(RuntimeError):
                write_nbt_value(config, "world/level.dat", "Data.LevelName", '"new"')

    def test_world_write_allows_1_21_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            world = Path(tmp) / "world"
            world.mkdir()
            path = world / "level.dat"
            nbtlib.File({"Data": nbtlib.Compound({"DataVersion": nbtlib.Int(3955), "LevelName": nbtlib.String("old")})}).save(path)
            with mock.patch("mc_world_mcp.safety.java_processes", return_value=[]):
                result = json.loads(write_nbt_value(config, "world/level.dat", "Data.LevelName", '"new"'))
            self.assertTrue(result["ok"])
            self.assertEqual(str(get_at_path(nbtlib.load(path), "Data.LevelName")), "new")

    def test_1_21_1_chunk_block_and_biome_write_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            self._write_1_21_1_chunk(Path(tmp) / "world", "minecraft:stone")

            with mock.patch("mc_world_mcp.safety.java_processes", return_value=[]):
                set_block(config, 0, 0, 0, "minecraft:deepslate")
                set_biome_box(config, 0, 0, 0, 0, 0, 0, "minecraft:desert")

            self.assertEqual(get_block(config, 0, 0, 0), "minecraft:deepslate")
            _, _, _, chunk = load_chunk_with_cache(config, 0, 0, "overworld", {})
            biomes = chunk["sections"][0]["biomes"]
            palette = [str(item) for item in biomes["palette"]]
            indices = _decode_biome_indices(biomes)
            self.assertEqual(palette[indices[_biome_local_index(0, 0, 0)]], "minecraft:desert")
            self.assertEqual(palette[indices[_biome_local_index(1, 0, 0)]], "minecraft:lush_caves")

    def test_block_state_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            world = Path(tmp) / "world"
            (world / "region").mkdir(parents=True)
            nbtlib.File({"Data": nbtlib.Compound({"DataVersion": nbtlib.Int(3465)})}).save(world / "level.dat")
            region = RegionFile(world / "region" / "r.0.0.mca")
            for cx in (0, 1):
                raw = io.BytesIO()
                nbtlib.File({
                    "xPos": nbtlib.Int(cx),
                    "zPos": nbtlib.Int(0),
                    "sections": nbtlib.List[nbtlib.Compound]([
                        nbtlib.Compound({
                            "Y": nbtlib.Byte(0),
                            "block_states": nbtlib.Compound({
                                "palette": nbtlib.List[nbtlib.Compound]([
                                    nbtlib.Compound({"Name": nbtlib.String("minecraft:air")})
                                ])
                            }),
                        })
                    ]),
                    "block_entities": nbtlib.List[nbtlib.Compound](),
                    "Status": nbtlib.String("minecraft:full"),
                }).write(raw)
                region.set_raw(cx, raw.getvalue())
            region.write()
            with mock.patch("mc_world_mcp.safety.java_processes", return_value=[]):
                set_block(config, 0, 0, 0, "minecraft:oak_stairs[facing=north,waterlogged=false]")
                fill_blocks(config, 15, 0, 0, 16, 0, 0, "minecraft:stone")
            self.assertEqual(get_block(config, 0, 0, 0), "minecraft:oak_stairs[facing=north,waterlogged=false]")
            self.assertEqual(get_block(config, 15, 0, 0), "minecraft:stone")
            self.assertEqual(get_block(config, 16, 0, 0), "minecraft:stone")

    def test_fill_blocks_decodes_each_section_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _, _ = self._basic_world(tmp)
            calls = {"decode": 0, "encode": 0}

            import mc_world_mcp.anvil as anvil_module

            original_decode = anvil_module.decode_indices
            original_encode = anvil_module.encode_indices

            def counted_decode(block_states):
                calls["decode"] += 1
                return original_decode(block_states)

            def counted_encode(block_states, indices):
                calls["encode"] += 1
                return original_encode(block_states, indices)

            with (
                mock.patch("mc_world_mcp.safety.java_processes", return_value=[]),
                mock.patch("mc_world_mcp.anvil.decode_indices", counted_decode),
                mock.patch("mc_world_mcp.anvil.encode_indices", counted_encode),
            ):
                result = fill_blocks(config, 0, 0, 0, 15, 15, 15, "minecraft:stone", confirm=True)

            self.assertEqual(result["changed"], 4096)
            self.assertEqual(calls, {"decode": 1, "encode": 1})
            self.assertEqual(get_block(config, 15, 15, 15), "minecraft:stone")

    def test_read_block_box_decodes_each_section_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _, _ = self._basic_world(tmp)
            calls = {"decode": 0}

            import mc_world_mcp.anvil as anvil_module

            original_decode = anvil_module.decode_indices

            def counted_decode(block_states):
                calls["decode"] += 1
                return original_decode(block_states)

            with mock.patch("mc_world_mcp.anvil.decode_indices", counted_decode):
                result = read_block_box(config, 0, 0, 0, 15, 15, 15, include_air=True, confirm=True)

            self.assertEqual(result["returned"], 4096)
            self.assertEqual(calls, {"decode": 1})

    def test_export_region_decodes_each_section_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = ServerConfig(root)
            self._write_single_palette_chunk(root / "world", "minecraft:stone")
            target = "world/generated/demo/structures/full_section.nbt"
            calls = {"decode": 0}

            import mc_world_mcp.anvil as anvil_module

            original_decode = anvil_module.decode_indices

            def counted_decode(block_states):
                calls["decode"] += 1
                return original_decode(block_states)

            with (
                mock.patch("mc_world_mcp.safety.java_processes", return_value=[]),
                mock.patch("mc_world_mcp.anvil.decode_indices", counted_decode),
            ):
                result = json.loads(export_region_to_template(config, 0, 0, 0, 15, 15, 15, target, confirm=True))

            self.assertEqual(result["blocks"], 4096)
            self.assertEqual(calls, {"decode": 1})
            self.assertTrue((root / target).exists())

    def test_export_region_scans_only_intersecting_entity_regions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = ServerConfig(root)
            self._write_single_palette_chunk(root / "world", "minecraft:stone")
            entity_root = root / "world" / "entities"
            entity_root.mkdir(parents=True)

            def write_entity_chunk(cx: int, cz: int, x: float, y: float, z: float) -> None:
                rx, rz, index = region_coords(cx, cz)
                region = RegionFile(entity_root / f"r.{rx}.{rz}.mca")
                raw = io.BytesIO()
                nbtlib.File({
                    "Entities": nbtlib.List[nbtlib.Compound]([
                        nbtlib.Compound({
                            "id": nbtlib.String("minecraft:marker"),
                            "Pos": nbtlib.List[nbtlib.Double]([
                                nbtlib.Double(x),
                                nbtlib.Double(y),
                                nbtlib.Double(z),
                            ]),
                        })
                    ]),
                    "Position": nbtlib.IntArray([cx, cz]),
                }).write(raw)
                region.set_raw(index, raw.getvalue())
                region.write()

            write_entity_chunk(0, 0, 1.0, 1.0, 1.0)
            write_entity_chunk(64, 0, 1024.0, 1.0, 1.0)
            seen_entity_regions: list[str] = []
            original_read = RegionFile._read

            def counted_read(region: RegionFile) -> None:
                if region.path.parent.name == "entities":
                    seen_entity_regions.append(region.path.name)
                original_read(region)

            with (
                mock.patch("mc_world_mcp.safety.java_processes", return_value=[]),
                mock.patch.object(RegionFile, "_read", counted_read),
            ):
                result = json.loads(export_region_to_template(config, 0, 0, 0, 15, 15, 15, "world/generated/demo/structures/with_entity.nbt", confirm=True))

            self.assertEqual(result["entities"], 1)
            self.assertEqual(seen_entity_regions, ["r.0.0.mca"])

    def test_cython_encode_indices_matches_python_when_available(self) -> None:
        import mc_world_mcp.anvil as anvil_module

        accel = anvil_module._PREVIEW_ACCEL
        if accel is None or not hasattr(accel, "encode_indices"):
            self.skipTest("Cython encode_indices accelerator is not built")

        palette = nbtlib.List[nbtlib.Compound]([
            nbtlib.Compound({"Name": nbtlib.String("minecraft:air")}),
            nbtlib.Compound({"Name": nbtlib.String("minecraft:stone")}),
            nbtlib.Compound({"Name": nbtlib.String("minecraft:deepslate")}),
        ])
        indices = [(i * 7) % 3 for i in range(4096)]
        accelerated = nbtlib.Compound({"palette": copy.deepcopy(palette)})
        fallback = nbtlib.Compound({"palette": copy.deepcopy(palette)})

        anvil_module.encode_indices(accelerated, indices)
        with mock.patch.object(anvil_module, "_PREVIEW_ACCEL", None):
            anvil_module.encode_indices(fallback, indices)

        self.assertEqual([int(item) for item in accelerated["data"]], [int(item) for item in fallback["data"]])

    def test_replace_blocks_skips_missing_chunks_inside_box(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = ServerConfig(root)
            self._write_single_palette_chunk(root / "world", "minecraft:stone", cx=0)
            self._write_single_palette_chunk(root / "world", "minecraft:stone", cx=2)

            with mock.patch("mc_world_mcp.safety.java_processes", return_value=[]):
                result = replace_blocks(config, 0, 0, 0, 47, 0, 0, "minecraft:stone", "minecraft:sand", confirm=True)

            self.assertTrue(result["ok"])
            self.assertEqual(result["changed"], 32)
            self.assertEqual(result["skipped_chunks"], [{"cx": 1, "cz": 0}])
            self.assertEqual(result["affected_chunks"], [{"cx": 0, "cz": 0}, {"cx": 2, "cz": 0}])
            self.assertEqual(get_block(config, 0, 0, 0), "minecraft:sand")
            self.assertEqual(get_block(config, 32, 0, 0), "minecraft:sand")
            with self.assertRaises(FileNotFoundError):
                get_block(config, 16, 0, 0)

    def test_zip_datapack_search_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            dp_root = Path(tmp) / "world" / "datapacks"
            dp_root.mkdir(parents=True)
            zip_path = dp_root / "sample.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("pack.mcmeta", '{"pack":{"pack_format":22,"description":"x"}}')
                zf.writestr("data/demo/functions/test.mcfunction", "say hi\n")
                zf.writestr("data/demo/tags/functions/load.json", '{"replace":false,"values":[]}')
            self.assertEqual(validate_datapacks(config)["json_errors"], [])
            self.assertEqual(search_datapack_files(config, "test", "demo")[0]["pack"], "sample.zip")
            self.assertEqual(read_datapack_file(config, "sample.zip", "data/demo/functions/test.mcfunction"), "say hi\n")

    def test_chunk_block_entity_and_entity_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, world, _ = self._basic_world(tmp)
            (world / "entities").mkdir()
            entity_region = RegionFile(world / "entities" / "r.0.0.mca")
            raw = io.BytesIO()
            nbtlib.File({"Entities": nbtlib.List[nbtlib.Compound](), "Position": nbtlib.IntArray([0, 0])}).write(raw)
            entity_region.set_raw(0, raw.getvalue())
            entity_region.write()
            with mock.patch("mc_world_mcp.safety.java_processes", return_value=[]):
                chunk_result = write_chunk_nbt_value(config, 0, 0, "Status", '"minecraft:full"')
                block_entity_result = add_block_entity(
                    config,
                    1,
                    0,
                    1,
                    "minecraft:chest[facing=north,type=single,waterlogged=false]",
                    '{id:"minecraft:chest",Items:[]}',
                )
                entity_result = add_entity(config, '{id:"minecraft:pig",Pos:[0.5d,0.0d,0.5d]}')
            self.assertTrue(chunk_result["ok"])
            self.assertEqual(block_entity_result["after"], "minecraft:chest[facing=north,type=single,waterlogged=false]")
            self.assertEqual(entity_result["entity_count"], 1)

    def test_worldgen_reference_validation_finds_missing_same_namespace_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            dp = Path(tmp) / "world" / "datapacks" / "Demo"
            (dp / "data" / "demo" / "worldgen" / "structure_set").mkdir(parents=True)
            (dp / "pack.mcmeta").write_text('{"pack":{"pack_format":15,"description":"demo"}}', encoding="utf-8")
            (dp / "data" / "demo" / "worldgen" / "structure_set" / "bad.json").write_text(
                '{"structures":[{"structure":"demo:missing","weight":1}],"placement":{"type":"minecraft:random_spread","salt":1,"spacing":32,"separation":8}}',
                encoding="utf-8",
            )
            result = validate_worldgen_references(config)
            self.assertEqual(result["json_errors"], [])
            self.assertEqual(result["missing_references"][0]["reference"], "demo:missing")

    def test_preview_renderers_create_nonblank_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, world, _ = self._basic_world(tmp)
            with mock.patch("mc_world_mcp.safety.java_processes", return_value=[]):
                set_block(config, 0, 0, 0, "minecraft:stone")
                set_block(config, 0, 1, 0, "minecraft:water")
            map_result = render_map_preview(config, 0, 0, 1, 1, "0")
            sampled_result = render_map_preview(config, 0, 0, 3, 3, "0", sample=2)
            top_result = render_map_preview(config, 0, 0, 0, 0, "top")
            floor_result = render_map_preview(config, 0, 0, 0, 0, "ocean_floor")
            closeup_result = render_closeup_map_preview(config, 0, 0, 1, 1, "surface", view="oblique", scale=6)
            slice_result = render_slice_preview(config, "x", 0, 0, 1, 0, 1)
            template_path = world / "generated" / "demo" / "structures" / "tiny.nbt"
            template_path.parent.mkdir(parents=True)
            nbtlib.File({
                "DataVersion": nbtlib.Int(3465),
                "size": nbtlib.List[nbtlib.Int]([nbtlib.Int(1), nbtlib.Int(1), nbtlib.Int(1)]),
                "palette": nbtlib.List[nbtlib.Compound]([nbtlib.Compound({"Name": nbtlib.String("minecraft:stone")})]),
                "blocks": nbtlib.List[nbtlib.Compound]([
                    nbtlib.Compound({
                        "pos": nbtlib.List[nbtlib.Int]([nbtlib.Int(0), nbtlib.Int(0), nbtlib.Int(0)]),
                        "state": nbtlib.Int(0),
                    })
                ]),
                "entities": nbtlib.List[nbtlib.Compound](),
            }).save(template_path, gzipped=True)
            template_result = render_template_preview(config, "world/generated/demo/structures/tiny.nbt")
            self.assertEqual(sampled_result["size"]["width"], 2)
            self.assertEqual(sampled_result["size"]["height"], 2)
            self.assertEqual(sampled_result["size"]["sample"], 2)
            self.assertEqual(top_result["top_blocks"][0]["block"], "minecraft:water")
            self.assertEqual(floor_result["top_blocks"][0]["block"], "minecraft:stone")
            self.assertEqual(closeup_result["view"], "oblique")
            self.assertGreater(closeup_result["size"]["width"], 0)
            self.assertGreater(closeup_result["blocks_projected"], 0)
            self.assertIn("accelerated_recomputation", closeup_result["rendering"])
            for result in (map_result, sampled_result, top_result, floor_result, closeup_result, slice_result, template_result):
                path = Path(result["path"])
                self.assertTrue(path.exists())
                image = Image.open(path)
                self.assertIsNotNone(image.getbbox())

    def test_template_preview_uses_nearest_projected_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, world, _ = self._basic_world(tmp)
            template_path = world / "generated" / "demo" / "structures" / "stack.nbt"
            template_path.parent.mkdir(parents=True)
            nbtlib.File({
                "DataVersion": nbtlib.Int(3465),
                "size": nbtlib.List[nbtlib.Int]([nbtlib.Int(1), nbtlib.Int(2), nbtlib.Int(1)]),
                "palette": nbtlib.List[nbtlib.Compound]([
                    nbtlib.Compound({"Name": nbtlib.String("minecraft:sand")}),
                    nbtlib.Compound({"Name": nbtlib.String("minecraft:stone")}),
                ]),
                "blocks": nbtlib.List[nbtlib.Compound]([
                    nbtlib.Compound({
                        "pos": nbtlib.List[nbtlib.Int]([nbtlib.Int(0), nbtlib.Int(0), nbtlib.Int(0)]),
                        "state": nbtlib.Int(0),
                    }),
                    nbtlib.Compound({
                        "pos": nbtlib.List[nbtlib.Int]([nbtlib.Int(0), nbtlib.Int(1), nbtlib.Int(0)]),
                        "state": nbtlib.Int(1),
                    }),
                ]),
                "entities": nbtlib.List[nbtlib.Compound](),
            }).save(template_path, gzipped=True)
            result = render_template_preview(config, "world/generated/demo/structures/stack.nbt")
            self.assertEqual(result["blocks_projected"], 1)
            self.assertEqual(result["top_blocks"][0]["block"], "minecraft:stone")

    def test_export_template_allows_absolute_global_pack_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, world, _ = self._basic_world(tmp)
            with mock.patch("mc_world_mcp.safety.java_processes", return_value=[]):
                set_block(config, 0, 0, 0, "minecraft:stone")
                target = Path(tmp) / "global_packs" / "required_data" / "demo" / "data" / "demo" / "structure" / "probe.nbt"
                result = json.loads(export_region_to_template(config, 0, 0, 0, 0, 0, 0, str(target)))

            self.assertTrue(result["ok"])
            self.assertTrue(target.exists())
            templates = list_structure_templates(config)
            self.assertIn(target.relative_to(Path(tmp)).as_posix(), [item["path"] for item in templates])

    def test_item_nbt_preview_resolves_custom_model_and_oblique_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = ServerConfig(root)
            pack = root / "resourcepacks" / "DemoPack"
            models = pack / "assets" / "demo" / "models" / "item"
            textures = pack / "assets" / "demo" / "textures" / "item"
            models.mkdir(parents=True)
            textures.mkdir(parents=True)
            (models / "gem.json").write_text(
                json.dumps({
                    "parent": "minecraft:item/generated",
                    "textures": {"layer0": "demo:item/gem"},
                    "overrides": [
                        {"predicate": {"custom_model_data": 7}, "model": "demo:item/gem_alt"}
                    ],
                }),
                encoding="utf-8",
            )
            (models / "gem_alt.json").write_text(
                json.dumps({
                    "parent": "minecraft:item/generated",
                    "textures": {"layer0": "demo:item/gem_alt"},
                }),
                encoding="utf-8",
            )
            Image.new("RGBA", (16, 16), (40, 80, 220, 255)).save(textures / "gem.png")
            Image.new("RGBA", (16, 16), (220, 70, 40, 255)).save(textures / "gem_alt.png")

            result = render_item_nbt_preview(
                config,
                '{id:"demo:gem",Count:2b,tag:{CustomModelData:7,Enchantments:[{id:"minecraft:sharpness",lvl:1s}]}}',
                views=["front", "oblique"],
                size=32,
                resource_path="resourcepacks/DemoPack",
            )

            self.assertEqual(result["item"]["id"], "demo:gem")
            self.assertEqual(result["item"]["count"], 2)
            self.assertTrue(result["item"]["enchanted"])
            self.assertEqual(result["model"]["selected"], "demo:item/gem_alt")
            self.assertFalse(result["textures"]["fallback"])
            self.assertEqual(result["views"], ["front", "oblique"])
            image = Image.open(result["path"])
            self.assertEqual(image.size, (64, 32))
            self.assertIsNotNone(image.getbbox())

    def test_map_preview_lazily_decompresses_only_needed_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            world = Path(tmp) / "world"
            self._write_single_palette_chunk(world, "minecraft:stone", cx=0)
            self._write_single_palette_chunk(world, "minecraft:sand", cx=1)
            calls = 0
            original_decompress = zlib.decompress

            def counted_decompress(*args, **kwargs):
                nonlocal calls
                calls += 1
                return original_decompress(*args, **kwargs)

            with mock.patch("mc_world_mcp.preview.zlib.decompress", counted_decompress):
                result = render_map_preview(config, 0, 0, 0, 0, "0")
            self.assertEqual(calls, 1)
            self.assertEqual(result["top_blocks"][0]["block"], "minecraft:stone")


if __name__ == "__main__":
    unittest.main()
