# macOS 실행 및 배포 가이드

이 프로그램은 Mac의 **macOS 데스크톱**에서 실행합니다. iPhone·iPad의 iOS 앱은 아닙니다. 기존 Windows 실행 방식도 유지합니다.

## 소스에서 실행

- macOS 13 이상, Apple Silicon 또는 Intel Mac
- uv 0.10 이상(현재 Mac에서 0.10.10으로 확인)
- 최초 실행 시 Python과 패키지를 다운로드할 인터넷 연결

프로젝트는 Python 3.12를 사용합니다. 시스템 Python 3.14를 바꾸지 않고 uv가 프로젝트 전용 Python과 `.venv`를 준비합니다. Windows에서 만든 `.venv`는 복사하지 않습니다.

Homebrew를 사용하는 경우 uv를 설치합니다.

```bash
brew install uv
```

프로젝트 폴더에서 실행합니다.

```bash
chmod +x run_markdowneditor.command
./run_markdowneditor.command
```

Finder에서 `run_markdowneditor.command`를 두 번 눌러도 실행됩니다. 처음에는 다운로드 때문에 시간이 걸립니다. 이 실행 파일은 Apple Silicon과 Intel의 Homebrew 경로, 사용자 uv 설치 경로를 찾습니다.

터미널에서 문서 여러 개를 지정하거나 GPU를 끌 수 있습니다.

```bash
./run_markdowneditor.command "samples/설문지_기업 인공지능 활용 실태조사.md"
./run_markdowneditor.command "첫 문서.md" "다른 문서.md"
./run_markdowneditor.command --disable-gpu
```

`uv`를 직접 사용하려면 다음을 실행합니다.

```bash
export UV_CACHE_DIR="$PWD/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.uv-python"
uv sync --locked
uv run --locked markdowneditor
```

## Mac에서 사용

- 열기 `⌘O`, 날짜 저장 `⌘S`, 다른 이름 저장 `⇧⌘S`, 탭 닫기 `⌘W`
- 찾기 `⌘F`, 다음 찾기 `⌘G`, 바꾸기 `⇧⌘H`, 줄로 이동 `⌘L`
- 실행 취소 `⌘Z`, 다시 실행 `⇧⌘Z`, 굵게 `⌘B`, 기울임 `⌘I`, 링크 `⌘K`
- 다음·이전 탭 `Control+Tab` / `Control+Shift+Tab`, 글자 크기 `⌘+` / `⌘-` 또는 Command+마우스 휠
- 메뉴는 macOS 화면 상단 메뉴 막대에 나타납니다. 프로그램 종료는 `⌘Q`입니다.
- Finder의 Markdown 파일을 편집기·미리보기·탭 표시줄·시작 화면에 놓으면 문서 탭으로 엽니다.
- `파일 위치 열기`는 Finder에서 문서 폴더를 엽니다.
- 설정은 Qt의 macOS 사용자 설정 저장소에 보관하며, Windows 레지스트리를 사용하지 않습니다.

Mac에서는 파일 시스템이 대소문자를 구별하는지에 따라 같은 파일인지 판정합니다. 대소문자를 구별하는 볼륨의 `a.md`와 `A.md`는 서로 다른 문서입니다. Windows에서 작성한 상대 경로의 `\`와 Markdown의 `/`를 모두 처리합니다.

## Python 없이 실행하는 앱 만들기

macOS에서 빌드합니다. Apple Silicon에서 빌드하면 arm64 앱, Intel에서 빌드하면 x86_64 앱입니다. Windows에서는 Mac 앱을 빌드할 수 없습니다.

```bash
export UV_CACHE_DIR="$PWD/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.uv-python"
uv sync --locked
uv run --locked python scripts/build_macos.py
open dist/MarkdownEditor.app
```

결과물:

- `dist/MarkdownEditor.app`: Python·QtWebEngine·Mermaid·Pretendard·사용설명서가 포함된 앱
- `build/MarkdownEditor-0.1.0-macOS-arm64.zip` 또는 `...-x86_64.zip`: 배포용 ZIP

앱을 원하는 폴더에 복사해 두 번 눌러 실행합니다. 대상 Mac에는 Python이나 uv가 필요하지 않습니다. 앱 번들의 Markdown 문서 연결 정보와 Qt `FileOpen` 이벤트 처리를 통해, Finder의 `연결 프로그램`으로 파일을 열거나 Dock 앱 아이콘에 문서를 놓으면 실행 중인 앱의 탭으로 전달됩니다. 이미 열린 문서는 해당 탭으로 이동합니다.

빌드는 로컬 ad-hoc 서명을 사용하며 Apple Developer ID 서명·공증은 포함하지 않습니다. 인터넷을 통해 다른 Mac에 배포하려면 별도의 Developer ID 서명과 공증이 필요할 수 있습니다.

## 검증

```bash
uv run --locked pytest -m "not gui"
uv run --locked pytest -m gui
uv run --locked ruff check .
uv run --locked ruff format --check .
```

GUI 검사는 실제 macOS 로그인 세션에서 실행합니다. Finder 파일 열기, Command 단축키, 편집·저장·탭·미리보기·Mermaid를 확인합니다.

참고: [Qt의 Mac 단축키 규칙](https://doc.qt.io/qt-6/qkeysequence.html), [Qt 파일 열기 이벤트](https://doc.qt.io/qt-6/qfileopenevent.html), [PyInstaller macOS 이벤트와 앱 번들](https://pyinstaller.org/en/stable/feature-notes.html).
