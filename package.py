#!/usr/bin/env python3
"""
Package the KiCad RF Tools into a ZIP with the following structure:

<zip root>/
  resources/        (copied from repo resources)
  plugins/          (contains source plugin folders)
  metadata.json     (copied from repo)

Usage:
  python package.py --output dist
"""
import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

# Known plugin source folders to include
PLUGIN_DIRS = [
    "round_tracks",
    "trace_clearance",
    "trace_solder_expander",
    "tracks_length",
    "taper_fz",
    "via_fence_generator",
    "rf_tools_wizards",
]


def copy_tree(src: Path, dst: Path):
    if not src.exists():
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def make_zip(source_root: Path, zip_path: Path):
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
        for p in source_root.rglob("*"):
            if p.is_dir():
                continue
            # Skip __pycache__ files
            if "__pycache__" in p.parts:
                continue
            rel = p.relative_to(source_root)
            zf.write(p, rel.as_posix())


def main():
    repo_root = Path(__file__).parent.resolve()

    parser = argparse.ArgumentParser(description="Package RF-tools-KiCAD into a ZIP")
    parser.add_argument("--output", default=str(repo_root / "dist"), help="Output directory for the ZIP")
    parser.add_argument("--zipname", default=None, help="Optional explicit zip filename")
    args = parser.parse_args()

    # Prepare staging directory with required structure
    with tempfile.TemporaryDirectory() as tmpdir:
        stage_root = Path(tmpdir)
        stage_resources = stage_root / "resources"
        stage_plugins = stage_root / "plugins"
        stage_resources.mkdir(parents=True, exist_ok=True)
        stage_plugins.mkdir(parents=True, exist_ok=True)

        # Copy resources
        repo_resources = repo_root / "resources"
        if repo_resources.exists():
            copy_tree(repo_resources, stage_resources)
        else:
            print("resources folder not found in repository", file=sys.stderr)

        # Copy plugins
        for d in PLUGIN_DIRS:
            src = repo_root / d
            dst = stage_plugins / d
            if src.exists():
                copy_tree(src, dst)
                # Ensure __init__.py exists in each plugin folder
                init_file = dst / "__init__.py"
                if not init_file.exists():
                    init_file.touch()
            else:
                # Warn but continue
                print(f"warning: plugin folder missing: {src}", file=sys.stderr)

        # Copy root __init__.py into plugins folder
        root_init = repo_root / "__init__.py"
        if root_init.exists():
            shutil.copy2(root_init, stage_plugins / "__init__.py")
        else:
            print("__init__.py not found at repository root", file=sys.stderr)

        # Copy metadata.json
        repo_metadata = repo_root / "metadata.json"
        if repo_metadata.exists():
            shutil.copy2(repo_metadata, stage_root / "metadata.json")
        else:
            print("metadata.json not found in repository", file=sys.stderr)

        # Build ZIP
        out_dir = Path(args.output).resolve()
        zip_filename = args.zipname or "RF-tools-KiCAD.zip"
        zip_path = out_dir / zip_filename
        make_zip(stage_root, zip_path)
        print(f"Created: {zip_path}")


if __name__ == "__main__":
    main()
