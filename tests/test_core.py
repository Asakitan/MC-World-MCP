from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import nbtlib

from mc_world_mcp.anvil import RegionFile, region_coords
from mc_world_mcp.config import ServerConfig
from mc_world_mcp.datapacks import read_datapack_file, search_datapack_files, validate_datapacks
from mc_world_mcp.nbt_io import get_at_path, parse_path, read_nbt_file, write_nbt_value
from mc_world_mcp.paths import resolve_under_root


class CoreTests(unittest.TestCase):
    def test_path_escape_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            with self.assertRaises(ValueError):
                resolve_under_root(config, "../outside.txt")

    def test_nbt_path_parser(self) -> None:
        self.assertEqual(parse_path("Data.WorldGenSettings.dimensions[0]"), ["Data", "WorldGenSettings", "dimensions", 0])

    def test_nbt_read_write_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ServerConfig(Path(tmp).resolve())
            world = Path(tmp) / "world"
            world.mkdir()
            path = world / "level.dat"
            data = nbtlib.File({"Data": nbtlib.Compound({"LevelName": nbtlib.String("old")})})
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


if __name__ == "__main__":
    unittest.main()

