# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


def collect_tree(source_dir: Path, dest_root: str) -> list[tuple[str, str]]:
    if not source_dir.exists():
        return []
    items: list[tuple[str, str]] = []
    for path in source_dir.rglob("*"):
        if path.is_file():
            relative_parent = path.parent.relative_to(source_dir)
            target_dir = Path(dest_root) / relative_parent
            items.append((str(path), str(target_dir)))
    return items


project_root = Path.cwd()
seed_argos_source = project_root / "dist_qt" / "TraductorVideos" / "_internal" / "seed_data" / "argos-translate"
seed_whisper_source = project_root / "dist_qt" / "TraductorVideos" / "_internal" / "seed_data" / "whisper"

if not seed_argos_source.exists():
    seed_argos_source = project_root / ".local" / "share" / "argos-translate"
if not seed_whisper_source.exists():
    seed_whisper_source = project_root / ".models" / "whisper"

datas = []
binaries = []
hiddenimports = []

for package_name in (
    "PySide6",
    "shiboken6",
    "imageio_ffmpeg",
    "faster_whisper",
    "ctranslate2",
    "tokenizers",
    "onnxruntime",
    "av",
    "argostranslate",
    "stanza",
    "spacy",
):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package_name)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

datas += collect_tree(seed_argos_source, "seed_data/argos-translate")
datas += collect_tree(seed_whisper_source, "seed_data/whisper")


a = Analysis(
    ["app.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TraductorVideos",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TraductorVideos",
)
