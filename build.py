"""Package the add-on into an installable zip.

    python build.py

Produces dist/exploded_assembly_studio-<version>.zip with the package folder at
the root of the archive, which is what both "Install from Disk" (legacy add-on)
and the extension installer expect.
"""

import ast
import pathlib
import shutil
import zipfile

ROOT = pathlib.Path(__file__).parent
PACKAGE = ROOT / "exploded_assembly_studio"
DIST = ROOT / "dist"

EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def read_version():
    """Pull the version tuple out of bl_info without importing bpy."""
    source = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "bl_info":
                    info = ast.literal_eval(node.value)
                    return ".".join(str(part) for part in info["version"])
    raise SystemExit("Could not find bl_info version in __init__.py")


def collect_files():
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_dir():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix in EXCLUDE_SUFFIXES:
            continue
        yield path


def main():
    version = read_version()
    DIST.mkdir(exist_ok=True)

    # Remove older builds so the folder always shows the current one.
    for stale in DIST.glob("exploded_assembly_studio-*.zip"):
        stale.unlink()

    target = DIST / f"exploded_assembly_studio-{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in collect_files():
            archive.write(path, path.relative_to(ROOT).as_posix())

    size = target.stat().st_size / 1024
    print(f"Built {target.relative_to(ROOT)} ({size:.1f} KB)")
    for name in zipfile.ZipFile(target).namelist():
        print(f"  {name}")


if __name__ == "__main__":
    main()
