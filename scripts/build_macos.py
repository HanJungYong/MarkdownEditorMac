from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="MarkdownEditor macOS 앱 번들 빌드")
    parser.add_argument("--clean", action="store_true", help="PyInstaller 빌드 캐시 초기화")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("macOS 앱은 macOS에서 빌드해야 합니다.")

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build" / "pyinstaller-macos"),
    ]
    if args.clean:
        command.append("--clean")
    command.append(str(ROOT / "packaging" / "MarkdownEditor.spec"))
    subprocess.run(command, cwd=ROOT, check=True)

    with (ROOT / "pyproject.toml").open("rb") as metadata_file:
        version = tomllib.load(metadata_file)["project"]["version"]
    # ditto preserves the framework symlinks inside Qt's macOS app bundle.
    archive = ROOT / "build" / f"MarkdownEditor-{version}-macOS-{platform.machine()}.zip"
    subprocess.run(
        [
            "ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(ROOT / "dist" / "MarkdownEditor.app"),
            str(archive),
        ],
        check=True,
    )
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, ROOT / "dist" / name)
    print(f"앱: {ROOT / 'dist' / 'MarkdownEditor.app'}")
    print(f"배포 ZIP: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
