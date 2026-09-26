# 개발 환경 보고서

작성일: 2026-09-19

## macOS 이식 확인 (2026-09-26)

- 현재 환경: macOS 27.0 (26A428), Apple Silicon arm64
- uv 0.10.10, 프로젝트 전용 Python 3.12.13, PySide6/QtWebEngine 6.11.2
- 기존 `uv.lock`으로 Mac용 의존성 설치 확인. 시스템 Python 3.14.3은 변경하지 않음
- 단위 테스트 72개 + GUI 테스트 36개 = 전체 108개 통과
- Ruff 검사·포맷 검사, 실행 스크립트의 Bash 구문 검사 통과
- PyInstaller 6.22.3으로 `dist/MarkdownEditor.app`과 arm64 배포 ZIP 생성
- 번들 `--version` 및 `run_markdowneditor.command --version` 실행, `codesign --verify --deep --strict` 검증 통과
- 번들 GUI에 설문지 샘플을 지정해 앱 본체와 QtWebEngine 렌더러 실행 확인. 런타임 오류 로그 없음
- 수동 화면 확인은 Computer Use의 손쉬운 사용·화면 기록 권한 대기로 수행하지 못함
- 실제 Finder/Dock 전달은 수동 미확인. Qt 파일 열기 이벤트의 시작 대기·추가 탭·중복 문서 처리는 GUI 테스트로 검증
- Intel Mac과 Windows의 이번 변경 실행 검증은 수행하지 않음. 아래 내용은 기존 Windows 개발 기록

## 확인한 사실

- 프로젝트 루트: `F:\38.AICowork\202609_MarkdownEditor`
- 운영체제: Windows(한국어 PowerShell 환경)
- uv: `0.11.2`
- Node.js: `22.17.0`
- 시스템 `python`: PATH에 없음
- 시스템 npm: 설치 파일 누락으로 실행 불가
- 기본 uv 캐시 `F:\.uv-cache`: 현재 작업 샌드박스에서 접근 거부
- 대응: 프로젝트 내부 `.uv-cache`와 `.uv-python`을 사용
- Git: 프로젝트 루트는 Git 저장소가 아니며, 사용자 지시 없이 초기화하지 않음
- 프로젝트 Python: `3.12.13`
- PySide6/QtWebEngine: `6.11.2`
- markdown-it-py: `4.2.0`
- mdit-py-plugins: `0.6.1`
- PyYAML: `6.0.3`
- platformdirs: `4.11.11`
- Mermaid: `11.17.2`(로컬 번들, 실행 중 네트워크 불필요)

## 샘플 기준선

| 파일 | 크기 | SHA-256 |
|---|---:|---|
| `Samples\설문지_기업 인공지능 활용 실태조사.md` | 53,799 bytes | `199c443b79e03fbe4c080cbd71addb0af559232607c8c03303f808bb974ea506` |
| `Samples\차세대무역플랫폼 구축 사업 1단계 제안요청서.md` | 460,277 bytes | `7af22c18bcffc0bedf3868ba39c5261c1c06f03636005fa17b9c3f289ea93895` |

두 파일 모두 정확한 지정 경로에서 확인했다.

위 표는 최초 인수 검증 기준선이다. 2026-09-19 20:19 이후 설문지 파일은 52,868바이트, SHA-256 `82f7fc093c38e0f012d82eca4df06bfba269b384546b1626882f9d42853ebaba`인 내용으로 교체되어 있다. 프로그램 검증은 이 파일을 읽기 전용 입력으로 사용했고 이전 내용으로 되돌리거나 기준 해시를 자동 갱신하지 않았다.

## 검증 결과

- `uv.lock`을 기준으로 프로젝트 전용 환경 동기화와 오프라인 빌드를 확인했다.
- 단위 테스트 34개와 실제 Windows 데스크톱 GUI 테스트 7개가 통과했다.
- 두 샘플 인수 검증은 기능 항목 19개가 통과했고, 설문지 기준선 변경 1건을 별도 경고했다. 상세 결과는 `reports/verification_20260919_224350.md`에 있다.
- 150% 화면 배율에서 위젯 전용 캡처로 편집기와 QtWebEngine 미리보기를 확인했다.
- 테스트 호스트의 GPU 가상화 컨텍스트 생성 경고 때문에 검증 시 `--disable-gpu --single-process`를 사용했다. 이는 자동 검증 프로세스용 우회이며, 소프트웨어 렌더링에서도 표·이미지·Mermaid가 정상 표시됐다.
