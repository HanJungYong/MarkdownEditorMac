# 개발 진행 상황

최종 갱신: 2026-09-26 (4차 기능보완)

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
| 4차 M0 실사 | 완료 | 기준 테스트 단위 49·GUI 8 통과, PySide6/Qt 6.11.2, 단일 문서 상태·액션 연결·드롭 경로 실사 |
| 4차 M1 글간격 | 완료 | `보기 > 글간격 크게/작게`, 5%p·80~150%, `view/letter_spacing`, 줄 번호 100% 유지 |
| 4차 M2 세션 분리 | 완료 | `DocumentSession`, 활성 탭 액션 라우팅, 외부 요청 차단기 단일화, 늦은 콜백 차단 |
| 4차 M3 문서 탭 | 완료 | 탭 UI, 공통 열기 경로·중복 탭 방지, 탭별 저장·닫기·종료 확인, 시작 화면, 지연 셸 로드 |
| 4차 M4 끌어다 놓기 | 부분 | 편집기·미리보기·탭 표시줄·시작 화면 Qt 이벤트 경로 구현·검증. 실제 파일 탐색기 조작(S29)은 미확인 |
| 4차 M5 인수 검증 | 완료 | S24~S28 PASS, 화면(S14) 확인 기록, S29 `NOT_CHECKED` |
| 4차 M6 문서·배포 | 완료 | README·사용설명서·아키텍처·결정·배포 가이드 갱신, Windows 배포본 재빌드 |
| 4차 M7 탭 편의 기능 | 완료 | 탭 오른쪽 클릭 메뉴, 다른 탭·모든 탭 닫기, 가운데 단추 닫기, 글간격 기본값, 자동 줄바꿈·보기 모드 저장 |

## 4차 기능보완 검증 (2026-09-26)

- 시작 전 기준: 단위 49 passed, GUI 8 passed(5.0초)
- 최종 단위 테스트: `uv run --locked pytest -m "not gui"` → 70 passed, 34 deselected
- 최종 GUI 테스트: `uv run --locked pytest -m gui` → 34 passed, 70 deselected(기존 8개 + 4차 26개), 연속 2회 실행 모두 통과
- 정적 검사: `ruff check .`, `ruff format --check .` PASS
- 샘플 인수 검증 보고서: `reports/verification_20260926_174614.md`(M7 반영 뒤 다시 실행)
  - 전체 WARN: PASS 27, `BASELINE_CHANGED` 1(S01, 설문지 샘플 기준선), `NOT_CHECKED` 1(S29 실제 파일 탐색기 끌어다 놓기)
  - S14 화면: 캡처 11장을 직접 열어 확인한 뒤 `--confirm-visual`로 기록(파일별 SHA-256 포함)
  - S29: 컴퓨터 조작 권한 요청이 거부되어 실제 탐색기 조작을 하지 못함. 사용자 수동 확인 후 `--confirm-explorer-drop`으로 기록해야 함
- 성능(같은 검증 실행): 제안요청서 Python 렌더 92.1ms, 열기→미리보기 설문지 445ms·제안요청서 1037ms, 편집 반영 676ms
- 탭 수별 열기→렌더 시간: 1개 391ms, 2개째 1019ms, 3개째 818ms, 4개째 736ms
- 탭 수별 메모리(검증 프로세스, 앞선 검증 창의 사용량 포함): QtWebEngineProcess 합계 1개 118MB, 2개 283MB, 3개 434MB, 4개 684MB(탭마다 렌더 프로세스 1개), 앱 프로세스 470→521MB
- 캡처 확인 중 발견해 고친 문제: 기본 스타일에서 활성 탭이 글자 밝기로만 구분됨 → 파란 상단 막대와 굵은 글씨, 테마 변경 뒤 상태 표시줄 메시지와 경로가 겹침 → 메시지 동안 경로 라벨 명시적 숨김
- 원본 샘플 SHA-256: 검증 전후 동일(설문지 `82f7fc09…`, 제안요청서 `7af22c18…`)
- Windows 배포본 재빌드(M7 반영, 17:48, `build/BUILD_REPORT.md`): 설치 EXE 137,924,608바이트 `c878f3e3…`, 휴대용 ZIP 138,408,254바이트 `7929150b…`. manifest에 소스 커밋 `4dd4371`과 커밋하지 않은 변경 포함 여부 기록
  - SHA-256·ZIP CRC(105개 항목)·설치 EXE payload 동일성 PASS
  - 배포 실행 파일(UI Automation): 두 샘플 탭 2개, `보기`의 `글간격 크게/작게/기본값`, `파일`의 `탭 닫기/다른 탭 닫기/모든 탭 닫기`, 종료 코드 0, 샘플 사본 불변 PASS
  - 레지스트리 설정: 검증 전 내보내고 검증 뒤 되돌림, 전후 `reg query` 결과 동일
  - 17:31 첫 재빌드(`bab863df…`/`50af361a…`)는 M7 추가 전 산출물로 대체됨
- 설치 스크립트 격리 설치·제거: 사용자의 기존 MarkdownEditor가 계속 실행 중이어서 `install.ps1`의 실행 중 검사가 설치를 막음(테스트 모드로도 건너뛰지 않음) → NOT_CHECKED. 설치·제거 스크립트는 이번 라운드에 변경 없음. 수동 확인 절차는 `build/BUILD_REPORT.md`에 기록

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
