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

`build_manifest.json`에는 버전·빌드 시각과 함께 소스의 git 커밋과 커밋하지 않은 변경 여부(`source`)를 기록합니다. 버전 번호가 같은 빌드를 구분할 때 사용합니다.

## 배포본에서의 문서 탭과 끌어다 놓기

- 설치된 `MarkdownEditor.exe`에 파일을 여러 개 넘기면(명령줄, 바탕 화면 바로 가기에 여러 파일 놓기) 한 창에서 각각 탭으로 열립니다.
- 실행 중인 창의 편집기·미리보기·탭 표시줄에 파일 탐색기의 Markdown 파일을 끌어다 놓으면 새 탭으로 열립니다.
- 파일 탐색기의 `연결 프로그램 > MarkdownEditor`로 파일을 열면 Windows가 파일마다 프로그램을 새로 실행하므로 창이 따로 열립니다. 실행 중인 창으로 파일을 넘기는 단일 실행 기능은 없습니다.
- 프로그램을 관리자 권한으로 실행하면 일반 권한의 파일 탐색기에서 끌어다 놓을 수 없습니다(Windows 보안 정책). 설치본은 사용자 권한으로 실행하십시오.

## 배포 전 검증

```powershell
uv run --locked pytest -m "not gui"
uv run --locked pytest -m gui
uv run --locked python scripts\verify_samples.py
```

GPU 가상화 문제로 미리보기가 검게 나오는 환경에서는 `$env:QTWEBENGINE_CHROMIUM_FLAGS = "--disable-gpu"`를 설정한 뒤 GUI 테스트를 실행합니다(`tests\conftest.py`는 이미 이 값을 기본으로 씁니다). 휴대용 묶음의 `app\MarkdownEditor.exe --version` 종료 코드와, 임시 설치 경로에서 설치·제거 스크립트를 추가로 확인합니다. 실제 파일 탐색기에서 끌어다 놓는 동작은 자동 검증으로 대신할 수 없으므로 설치본에서 한 번 직접 확인하고, 결과를 `scripts\verify_samples.py --confirm-explorer-drop`으로 보고서에 기록합니다.

## 제약 사항

- 대상 운영체제는 64비트 Windows 10/11입니다.
- Python, uv, Node.js, 인터넷 연결은 대상 PC에 필요하지 않습니다.
- 현재 배포본은 코드 서명되지 않았으므로 Windows SmartScreen 경고가 표시될 수 있습니다.
- 신뢰 경고를 제거하려면 조직의 Windows 코드 서명 인증서로 최종 설치 EXE와 `MarkdownEditor.exe`를 서명해야 합니다.
