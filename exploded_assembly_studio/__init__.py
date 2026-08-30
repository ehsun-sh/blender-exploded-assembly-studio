"""Exploded Assembly Studio - assembly explode/assemble animation for Blender.

Turns an assembled model into an exploded view and back, as real keyframed
animation, with an optional orbiting camera. See README.md for the workflow.
"""

bl_info = {
    "name": "Exploded Assembly Studio",
    "author": "Exploded Assembly Studio",
    "version": (1, 14, 0),
    "blender": (3, 0, 0),
    "location": "3D Viewport > Sidebar (N) > Exploded",
    "description": "Explode and assemble animations for mechanical and electronic assemblies",
    "category": "Animation",
}

if "bpy" in locals():  # add-on reload support
    import importlib

    for _module in ("properties", "core", "camera", "snapshots", "operators", "ui"):
        if _module in locals():
            importlib.reload(locals()[_module])

import bpy  # noqa: E402

from . import camera, core, operators, properties, snapshots, ui  # noqa: E402,F401

MODULES = (properties, operators, ui)


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()


if __name__ == "__main__":
    register()
