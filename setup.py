from __future__ import annotations

import os
import sys
from pathlib import Path

from setuptools import Extension, setup


def should_build_accelerator() -> bool:
    return "build_ext" in sys.argv or os.environ.get("MC_WORLD_MCP_BUILD_ACCEL") == "1"


def optional_extensions():
    if not should_build_accelerator():
        return []

    pyx_source = Path("src") / "mc_world_mcp" / "_preview_accel.pyx"
    c_source = pyx_source.with_suffix(".c")
    extension_name = "mc_world_mcp._preview_accel"
    try:
        from Cython.Build import cythonize
    except Exception:
        if c_source.exists():
            return [Extension(extension_name, [str(c_source)])]
        return []

    return cythonize(
        [Extension(extension_name, [str(pyx_source)])],
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "initializedcheck": False,
        },
    )


setup(ext_modules=optional_extensions())
