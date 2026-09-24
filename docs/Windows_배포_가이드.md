# MarkdownEditor Windows 배포 가이드

## 배포본 만들기

Windows x64 개발 PC의 프로젝트 루트에서 실행합니다.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "$PWD\.uv-python"
uv sync --locked
uv run --locked python scripts\build_windows.py
```

모든 중간 파일과 결과물은 프로젝트의 `build` 아래에 생성됩니다.

## 사용자에게 전달할 파일

- `MarkdownEditor-Setup-0.1.0-Windows-x64.exe`: 관리자 권한 없는 사용자별 설치 파일
- `MarkdownEditor-0.1.0-Windows-x64.zip`: 설치하지 않고 실행하거나 수동 설치할 수 있는 휴대용 묶음
- `SHA256SUMS.txt`: 전달 과정에서 파일이 손상되지 않았는지 확인하는 체크섬

설치 EXE는 Windows 내장 IExpress로 만든 자체 압축 해제 패키지입니다. 사용자 계정의 `%LOCALAPPDATA%\Programs\MarkdownEditor`에 설치하고 바탕 화면·시작 메뉴 바로가기를 생성합니다. `.md` 기본 앱을 강제로 바꾸지 않고 Windows의 연결 프로그램 목록에만 등록합니다.

## 배포 전 검증

```powershell
uv run --locked pytest -m "not gui"
$env:QTWEBENGINE_CHROMIUM_FLAGS = "--disable-gpu --single-process"
uv run --locked pytest -m gui
```

휴대용 묶음의 `app\MarkdownEditor.exe --version` 종료 코드와, 임시 설치 경로에서 설치·제거 스크립트를 추가로 확인합니다.

## 제약 사항

- 대상 운영체제는 64비트 Windows 10/11입니다.
- Python, uv, Node.js, 인터넷 연결은 대상 PC에 필요하지 않습니다.
- 현재 배포본은 코드 서명되지 않았으므로 Windows SmartScreen 경고가 표시될 수 있습니다.
- 신뢰 경고를 제거하려면 조직의 Windows 코드 서명 인증서로 최종 설치 EXE와 `MarkdownEditor.exe`를 서명해야 합니다.
