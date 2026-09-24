from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH).parent
source_root = project_root / "src"

datas = collect_data_files("markdowneditor")
for font_name in (
    "Pretendard-Regular.otf",
    "Pretendard-Medium.otf",
    "Pretendard-Bold.otf",
):
    datas.append(
        (
            str(project_root / "Font" / font_name),
            "markdowneditor/assets/fonts",
        )
    )

hidden_imports = collect_submodules("mdit_py_plugins")

analysis = Analysis(
    [str(source_root / "markdowneditor" / "__main__.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytestqt", "ruff"],
    noarchive=False,
    optimize=1,
)

# Qt 6.11 uses Windows' unversioned ICU forwarder. PyInstaller can accidentally
# pick up a version-suffixed Poppler ICU from the developer PATH and place it in
# the application root. That DLL shadows System32\icuuc.dll and makes QtCore
# fail with WinError 127 on clean PCs, so it must not be distributed.
excluded_icu_names = {"icuuc.dll", "icudt78.dll"}
analysis.binaries = [
    entry for entry in analysis.binaries if Path(entry[0]).name.lower() not in excluded_icu_names
]

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="MarkdownEditor",
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

distribution = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MarkdownEditor",
)
