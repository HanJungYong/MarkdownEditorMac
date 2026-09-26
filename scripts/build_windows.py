from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tomllib
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
PACKAGING = ROOT / "packaging"


def run(command: list[str]) -> None:
    print("실행:", subprocess.list2cmdline(command))
    subprocess.run(command, cwd=ROOT, check=True)


def source_revision() -> dict[str, object]:
    """Git commit and whether the working tree had uncommitted changes when building.

    The version number alone does not tell two 0.1.0 builds apart, so the manifest records
    where the code came from.
    """
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "uncommitted_changes": None}
    return {"commit": commit, "uncommitted_changes": bool(status.strip())}


def safe_remove(path: Path) -> None:
    resolved = path.resolve()
    build_root = BUILD.resolve()
    if resolved == build_root or build_root not in resolved.parents:
        raise RuntimeError(f"build 하위가 아닌 경로는 정리할 수 없습니다: {resolved}")
    if resolved.exists():
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_cmd(path: Path, lines: list[str]) -> None:
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def create_zip(source: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(source.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(source.parent))


def create_iexpress(setup_executable: Path, portable_zip: Path, version: str) -> bool:
    iexpress = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "iexpress.exe"
    if not iexpress.exists():
        print("경고: IExpress를 찾지 못해 설치 EXE 생성을 생략합니다.")
        return False

    source = BUILD / "iexpress-source"
    safe_remove(source)
    source.mkdir(parents=True)
    shutil.copy2(portable_zip, source / "payload.zip")
    shutil.copy2(PACKAGING / "windows" / "install.ps1", source / "install.ps1")
    shutil.copy2(PACKAGING / "windows" / "setup.cmd", source / "setup.cmd")

    sed = BUILD / "MarkdownEditor-Setup.sed"
    target = str(setup_executable.resolve())
    source_path = str(source.resolve()) + os.sep
    sed_text = f"""[Version]
Class=IEXPRESS
SEDVersion=3

[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName={target}
FriendlyName=MarkdownEditor {version} 설치
AppLaunched=setup.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles

[SourceFiles]
SourceFiles0={source_path}

[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=

[Strings]
FILE0=\"setup.cmd\"
FILE1=\"install.ps1\"
FILE2=\"payload.zip\"
"""
    sed.write_text(sed_text.replace("\n", "\r\n"), encoding="utf-8")
    safe_remove(setup_executable)
    run([str(iexpress), "/N", "/Q", str(sed)])
    return setup_executable.exists() and setup_executable.stat().st_size > 0


def main() -> int:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = metadata["project"]["version"]
    machine = platform.machine().lower()
    if machine not in {"amd64", "x86_64"}:
        raise RuntimeError(f"이 빌드는 Windows x64에서 실행해야 합니다: {platform.machine()}")
    if sys.platform != "win32":
        raise RuntimeError("Windows 배포본은 Windows에서 빌드해야 합니다.")

    BUILD.mkdir(exist_ok=True)
    work = BUILD / "pyinstaller-work"
    raw_dist = BUILD / "pyinstaller-dist"
    package_name = f"MarkdownEditor-{version}-Windows-x64"
    portable = BUILD / package_name
    portable_zip = BUILD / f"{package_name}.zip"
    setup_executable = BUILD / f"MarkdownEditor-Setup-{version}-Windows-x64.exe"
    for target in (work, raw_dist, portable, portable_zip, setup_executable):
        safe_remove(target)

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--workpath",
            str(work),
            "--distpath",
            str(raw_dist),
            str(PACKAGING / "MarkdownEditor.spec"),
        ]
    )
    built_app = raw_dist / "MarkdownEditor"
    executable = built_app / "MarkdownEditor.exe"
    if not executable.exists():
        raise RuntimeError("PyInstaller 실행 파일이 생성되지 않았습니다.")
    for forbidden_icu in ("icuuc.dll", "icudt78.dll"):
        if (built_app / "_internal" / forbidden_icu).exists():
            raise RuntimeError(f"Windows 시스템 ICU를 가리는 DLL이 포함되었습니다: {forbidden_icu}")
    qt_root = built_app / "_internal" / "PySide6"
    for unused_qt in ("qml", "QtQml.pyd", "resources/*.debug.*", "translations/qtbase_de.qm"):
        if any(qt_root.glob(unused_qt)):
            raise RuntimeError(
                f"spec에서 제외한 Qt 구성 요소가 포함되었습니다: PySide6/{unused_qt}"
            )

    portable.mkdir()
    shutil.copytree(built_app, portable / "app")
    shutil.copy2(PACKAGING / "windows" / "install.ps1", portable / "install.ps1")
    shutil.copy2(PACKAGING / "windows" / "uninstall.ps1", portable / "uninstall.ps1")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", portable / "THIRD_PARTY_NOTICES.md")
    write_cmd(
        portable / "install.cmd",
        [
            "@echo off",
            "setlocal EnableExtensions",
            "chcp 65001 >nul",
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"',
            'set "EXIT_CODE=%ERRORLEVEL%"',
            'if not "%EXIT_CODE%"=="0" pause',
            "exit /b %EXIT_CODE%",
        ],
    )
    write_cmd(
        portable / "uninstall.cmd",
        [
            "@echo off",
            "setlocal EnableExtensions",
            "chcp 65001 >nul",
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"',
            'set "EXIT_CODE=%ERRORLEVEL%"',
            'if not "%EXIT_CODE%"=="0" pause',
            "exit /b %EXIT_CODE%",
        ],
    )
    write_cmd(
        portable / "MarkdownEditor_바로실행.cmd",
        [
            "@echo off",
            "setlocal EnableExtensions",
            r'start "" "%~dp0app\MarkdownEditor.exe" %*',
        ],
    )
    guide = f"""MarkdownEditor {version} Windows x64 설치 안내

권장 설치
1. install.cmd를 두 번 클릭합니다.
2. 사용자 폴더의 AppData\\Local\\Programs\\MarkdownEditor에 설치됩니다.
3. 바탕 화면 또는 시작 메뉴의 MarkdownEditor 바로가기를 실행합니다.

휴대용 실행
- 설치하지 않으려면 MarkdownEditor_바로실행.cmd를 실행합니다.
- app 폴더의 구조와 파일을 변경하지 마십시오.

제거
- Windows 설정의 설치된 앱 또는 시작 메뉴의 MarkdownEditor 제거를 실행합니다.

지원 운영체제
- 64비트 Windows 10/11
- 별도 Python, uv, Node.js 또는 인터넷 연결이 필요하지 않습니다.

주의
- 이 배포본은 코드 서명 인증서로 서명되지 않았습니다. 다른 PC에서 Windows SmartScreen
  경고가 표시될 수 있으며, 파일의 SHA-256은 함께 제공된 SHA256SUMS.txt로 확인하십시오.
- .md 기본 앱은 자동으로 변경하지 않습니다. 설치 후 연결 프로그램 목록에서
  MarkdownEditor를 선택할 수 있습니다.
"""
    (portable / "설치_안내.txt").write_text(guide, encoding="utf-8-sig", newline="\r\n")

    create_zip(portable, portable_zip)
    setup_created = create_iexpress(setup_executable, portable_zip, version)

    artifacts = [portable_zip]
    if setup_created:
        artifacts.append(setup_executable)
    checksums = "".join(f"{sha256(path)}  {path.name}\n" for path in artifacts)
    (BUILD / "SHA256SUMS.txt").write_text(checksums, encoding="ascii")

    file_count = sum(1 for path in (portable / "app").rglob("*") if path.is_file())
    manifest = {
        "product": "MarkdownEditor",
        "version": version,
        "platform": "Windows x64",
        "created_at": datetime.now().astimezone().isoformat(),
        "source": source_revision(),
        "python": platform.python_version(),
        "pyinstaller": __import__("PyInstaller").__version__,
        "app_file_count": file_count,
        "artifacts": [
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in artifacts
        ],
    }
    (BUILD / "build_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    root_guide = f"""MarkdownEditor {version} Windows x64 배포 파일

권장: MarkdownEditor-Setup-{version}-Windows-x64.exe를 대상 PC로 복사해 실행합니다.
휴대용: MarkdownEditor-{version}-Windows-x64.zip을 풀고 MarkdownEditor_바로실행.cmd를 실행합니다.
무결성: SHA256SUMS.txt의 SHA-256 값과 전달받은 파일을 비교합니다.

지원: 64비트 Windows 10/11
불필요: Python, uv, Node.js, 인터넷 연결, 관리자 권한
주의: 코드 서명되지 않은 사내 배포본이므로 Windows SmartScreen 경고가 표시될 수 있습니다.
"""
    (BUILD / "README_배포.txt").write_text(root_guide, encoding="utf-8-sig", newline="\r\n")
    for temporary in (
        work,
        raw_dist,
        BUILD / "iexpress-source",
        BUILD / "MarkdownEditor-Setup.sed",
    ):
        safe_remove(temporary)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
