from fnmatch import fnmatch
from pathlib import Path
import sys
import tomllib

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH).parent
source_root = project_root / "src"
with (project_root / "pyproject.toml").open("rb") as metadata_file:
    version = tomllib.load(metadata_file)["project"]["version"]

datas = collect_data_files("markdowneditor")
datas.append((str(project_root / "docs" / "사용설명서.md"), "markdowneditor/assets/docs"))
datas.append((str(project_root / "docs" / "macOS_실행_가이드.md"), "markdowneditor/assets/docs"))
for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    datas.append((str(project_root / notice), "markdowneditor/assets/legal"))
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

# PySide6 bindings that the QtWebEngine hooks pull in although the app never
# imports them. With PySide6.QtQml in the graph PyInstaller collects every QML
# plugin plus the Qt 3D/Charts/Multimedia/... DLLs they link against. The Qt
# DLLs that QtWebEngine itself needs are still found by binary analysis.
unused_qt_bindings = [
    "PySide6.QtOpenGL",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
] if sys.platform == "win32" else []

analysis = Analysis(
    [str(source_root / "markdowneditor" / "__main__.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytestqt", "ruff", *unused_qt_bindings],
    noarchive=False,
    optimize=1,
)

# Qt 6.11 uses Windows' unversioned ICU forwarder. PyInstaller can accidentally
# pick up a version-suffixed Poppler ICU from the developer PATH and place it in
# the application root. That DLL shadows System32\icuuc.dll and makes QtCore
# fail with WinError 127 on clean PCs, so it must not be distributed.
excluded_icu_names = {"icuuc.dll", "icudt78.dll"}

# Files under PySide6/ that the app never loads: QML imports, debug-build and
# DevTools WebEngine resources (DevTools is not exposed), and Qt plugins for
# platforms, input methods, QML debugging and image formats the app does not use.
# opengl32sw.dll stays: it may be the rendering fallback on PCs without a GPU.
unused_qt_patterns = [
    "qml/*",
    "resources/*.debug.*",
    "resources/qtwebengine_devtools_resources.pak",
    "plugins/generic/*",
    "plugins/platforminputcontexts/*",
    "plugins/position/*",
    "plugins/qmltooling/*",
    "plugins/platforms/qdirect2d.dll",
    "plugins/platforms/qminimal.dll",
    "plugins/platforms/qoffscreen.dll",
    "plugins/imageformats/qicns.dll",
    "plugins/imageformats/qpdf.dll",
    "plugins/imageformats/qtga.dll",
    "plugins/imageformats/qtiff.dll",
    "plugins/imageformats/qwbmp.dll",
    # Linked only by the pdf image-format and virtual keyboard plugins above.
    "qt6pdf.dll",
    "qt6virtualkeyboard.dll",
]
# The UI is Korean only. Chromium falls back to en-US.pak for other locales.
kept_translations = {"ko.pak", "en-us.pak"}


def is_unused_qt_file(dest_name):
    path = dest_name.replace("\\", "/").lower()
    if not path.startswith("pyside6/"):
        return False
    path = path.removeprefix("pyside6/")
    if path.startswith("translations/"):
        name = path.rsplit("/", 1)[-1]
        return not (name.endswith("_ko.qm") or name in kept_translations)
    return any(fnmatch(path, pattern) for pattern in unused_qt_patterns)


if sys.platform == "win32":
    analysis.binaries = [
        entry
        for entry in analysis.binaries
        if Path(entry[0]).name.lower() not in excluded_icu_names and not is_unused_qt_file(entry[0])
    ]
    analysis.datas = [entry for entry in analysis.datas if not is_unused_qt_file(entry[0])]

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

if sys.platform == "darwin":
    app = BUNDLE(
        distribution,
        name="MarkdownEditor.app",
        bundle_identifier="org.openaicowork.markdowneditor",
        version=version,
        info_plist={
            "CFBundleDisplayName": "MarkdownEditor",
            "CFBundleShortVersionString": version,
            "CFBundleDevelopmentRegion": "ko",
            "CFBundleLocalizations": ["ko"],
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Markdown 문서",
                    "CFBundleTypeExtensions": ["md", "markdown", "mdown", "mkd", "mkdn"],
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Alternate",
                }
            ],
        },
    )
