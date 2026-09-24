# 제3자 소프트웨어 고지

MarkdownEditor는 다음 오픈소스 소프트웨어를 사용합니다. 정확한 설치 버전은 `uv.lock`을 기준으로 합니다.

| 구성요소 | 용도 | 라이선스 |
|---|---|---|
| Python | 실행 환경 | PSF License |
| PySide6 / Qt | Windows GUI와 QtWebEngine | LGPL-3.0 등 Qt 배포 고지 참조 |
| markdown-it-py | Markdown 파싱 | MIT |
| mdit-py-plugins | front matter·각주·작업 목록 | MIT |
| linkify-it-py | 자동 링크 | MIT |
| PyYAML | YAML front matter | MIT |
| platformdirs | 사용자 설정·로그 경로 | MIT |
| pytest / pytest-qt | 개발 테스트 | MIT |
| Ruff | 린트·포맷 | MIT |
| Mermaid | 다이어그램 렌더링 | MIT |
| Pretendard | 편집기·미리보기 한글 글꼴 | SIL Open Font License 1.1 |

PySide6/Qt는 동적 링크 방식으로 사용합니다. Qt 및 Chromium의 전체 제3자 고지는 설치된 PySide6 배포물의 라이선스 파일과 Qt WebEngine 고지를 참조하십시오.

Mermaid 원본 URL, 버전, SHA-256과 MIT LICENSE는 `src/markdowneditor/assets/vendor/mermaid/`에 함께 보관합니다.

Pretendard Regular·Medium·Bold 글꼴 파일은 프로젝트 `Font/`에서 가져와 wheel의 `markdowneditor/assets/fonts/`에 포함합니다. Pretendard는 SIL Open Font License 1.1 조건으로 배포됩니다.
