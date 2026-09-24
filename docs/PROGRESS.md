# 개발 진행 상황

최종 갱신: 2026-09-20

| 단계 | 상태 | 증거 |
|---|---|---|
| M0 환경·기준선 | 완료 | `docs/environment_report.md`, 샘플 SHA-256 확인 |
| M1 uv·core | 완료 | `uv.lock`, core 모듈, 단위 테스트 49개 통과 |
| M2 기본 GUI | 완료 | 편집기·미리보기·메뉴·툴바·찾기/바꾸기 구현 |
| M3 렌더링·보안 | 완료 | GFM·HTML 표·이미지·CSP·정화기·연결 검사 구현 |
| M4 Mermaid·툴바 | 완료 | Mermaid 11.17.2 오프라인 번들, 서식 동작 구현 |
| M5 인수 검증 | 완료 | 샘플 기능 검사 22개 PASS, 기준선 변경 1건 분리 보고, GUI 테스트 8개 통과 |
| M6 문서·재현성 | 완료 | 한국어 문서, 잠금 파일, sdist/wheel 빌드 확인 |
| M7 1차 기능 보완 | 완료 | 다크 모드, Pretendard, 공통 글자 크기, `Sync Scroll` 구현 |
| M8 2차 기능 보완 | 완료 | 편집기 라이트·다크 색상과 모드 공통 밝은 스크롤바 구현 |
| M9 시각 회귀 보완 | 완료 | 3~4자리 줄 번호에서 본문 첫 글자가 가려지는 Windows 여백 문제 수정·테스트 |
| M10 Windows 배포 | 완료 | PyInstaller 독립 실행형, 휴대용 ZIP, 사용자별 설치 EXE 생성·실제 설치 검증 |
| M11 3차 기능 보완 | 완료 | 공백 2칸 Tab, 선택형 줄바꿈 들여쓰기, 인용·목록·번호 자동 계속 구현 |
| M12 Sync Scroll 개선 | 완료 | 원문 줄 번호 기반 양방향 동기화와 `Sync Scroll 위치맞춤` 강제 보정 구현 |
| M13 Mermaid 다크 대비 | 완료 | flowchart·sequenceDiagram 모드별 렌더링, 주요 선·글자 대비 4.5:1 자동 검증 구현 |

## 최종 검증

- 최종 보고서: `reports/verification_20260920_133418.md`
- 단위 테스트: 49 passed
- GUI 통합 테스트: 8 passed
- 정적 검사: Ruff check·format PASS
- 패키지: `dist/markdowneditor-0.1.0.tar.gz`, `dist/markdowneditor-0.1.0-py3-none-any.whl`
- Windows 배치 실행기: CRLF·UTF-8(무 BOM), PowerShell 호출과 한글·공백 인자 전달 확인
- 샘플 인수 검증: 기능 검사 22개 PASS, `BASELINE_CHANGED` 1개로 전체 WARN
- Mermaid 다크 모드 대비: 5개 대표 선·글자 항목 모두 4.5:1 이상, 측정 최솟값 13.76:1
- 기준선 경고: 설문지 샘플은 최초 검증의 53,799바이트 SHA-256 `199c443b…`에서 현재 52,868바이트 SHA-256 `82f7fc09…`로 바뀌었으며, 검증기는 원본을 수정하지 않음
- Windows 설치 EXE: `build/MarkdownEditor-Setup-0.1.0-Windows-x64.exe`
- 휴대용 ZIP: `build/MarkdownEditor-0.1.0-Windows-x64.zip`
- 배포 검증: 설치 EXE payload 동일성, 격리 설치·Mermaid 검증 문서 기동·정상 종료·제거, ZIP CRC, SHA-256 모두 PASS

## 권장 기능 처리

- 구현: 최근 파일 10개, 연결 문제 패널, 외부 이미지 표시 전환, CLI `check`/`render`, `--disable-gpu`, 미리보기 스크롤 위치 보존
- 이번 버전에서 생략: 문서 개요 패널, 코드 토큰 단위 강조, 파일 외부 변경 감지
- 생략 이유: 필수 편집·저장·보안·대형 샘플 렌더링의 정확성과 자동 검증을 우선했다. 생략 항목은 필수 동작에 영향을 주지 않는 권장 기능이다.
