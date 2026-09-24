# MarkdownEditor 아키텍처

## 계층

- `core.file_io`: 입력 검증, 인코딩·BOM·줄바꿈 문서 모델, 원자 저장
- `core.naming`: 날짜 파일명과 충돌 순번
- `core.md_actions`: 툴바가 사용하는 순수 텍스트 변환
- `core.editing`: 공백 2칸 들여쓰기와 Markdown 줄바꿈 접두사 계산
- `core.renderer`: Markdown 파싱, front matter·Mermaid 변환, HTML 정화
- `core.links`: 연결 요소 추출, 문서 폴더 기준 경로 해석
- `gui.editor`: 줄 번호·구문 강조 편집기
- `gui.fonts`: 번들 Pretendard 등록, 기본·최소·최대 글자 크기, WebEngine용 글꼴 CSS
- `gui.preview`: QtWebEngine 셸, CSP, Mermaid, 링크 브리지
- `gui.main_window`: 문서 생명주기, 메뉴·툴바·저장·상태 표시, 테마·확대·스크롤 조정

## 렌더 흐름

편집기 변경 신호는 300ms debounce 타이머를 다시 시작합니다. 최신 문서 원문을 Markdown 렌더러가 HTML로 바꾸고 위험 태그·속성을 제거합니다. 미리보기 셸은 문서 폴더를 기준 URL로 사용하며 본문 컨테이너만 교체합니다. 셸 JavaScript가 이미지 상태와 Mermaid를 처리하고 완료 정보를 Python 브리지로 보냅니다. Mermaid는 라이트 모드에서 기본 테마, 다크 모드에서 `base` 테마와 별도 색상 변수를 사용해 다시 렌더링합니다. 다크 CSS는 flowchart·sequenceDiagram의 선, 화살표, 레이블에만 제한적으로 보정 색상을 적용합니다.

브라우저 진단 함수는 실제 렌더된 SVG에서 flowchart 연결선·화살촉·레이블과 sequenceDiagram 메시지 선·텍스트의 계산된 색상을 읽습니다. 상대 휘도로 배경 대비를 계산해 GUI 테스트와 샘플 인수 검증에서 각 항목 4.5:1 이상인지 확인합니다.

## 화면 상태와 스크롤

라이트·다크 모드, 공통 글자 크기, `Sync Scroll`, 자동 들여쓰기 선택은 `QSettings`에 보관합니다. 편집기와 WebEngine 미리보기는 같은 Pretendard 자산과 배율을 사용합니다.

렌더러는 Markdown 블록과 원문 HTML 블록에 `data-line` 기준점을 넣습니다. 편집기에서 Viewer로 이동할 때는 첫 번째 보이는 원문 줄과 앞뒤 기준점 사이를 보간해 Viewer 좌표를 계산합니다. Viewer에서 편집기로 이동할 때는 같은 보간식을 역으로 적용해 원문 줄을 구하고 해당 편집기 블록을 상단으로 이동합니다. 스크롤 이벤트는 30ms 단일 실행 타이머로 합치고, 상대 창에 적용한 이동은 되먹임을 억제해 무한 왕복을 막습니다. `Sync Scroll 위치맞춤`은 같은 줄 매핑을 체크 상태와 무관하게 한 번 강제 실행합니다.

## 편집 입력 흐름

편집기는 `Tab` 키를 가로채 공백 2칸만 삽입합니다. `Enter` 키 입력 때 현재 줄의 커서 앞 텍스트를 `core.editing`에 전달해 유지할 들여쓰기와 인용·목록·번호 접두사를 계산합니다. 이 계산은 GUI와 분리된 순수 함수여서 다양한 Markdown 표식과 설정 조합을 빠르게 단위 테스트할 수 있습니다.

## 보안 경계

1. Python HTML 정화기가 active content를 제거합니다.
2. 셸 CSP가 허용된 앱 스크립트와 로컬 이미지 외 실행을 제한합니다.
3. WebEngine page가 셸 밖 navigation을 차단합니다.
4. 링크는 최소 기능의 QWebChannel 브리지로 Python에 전달합니다.
5. 외부 이미지는 사용자가 켜기 전까지 허용하지 않습니다.

## 저장 흐름

원본을 열 때 원본 바이트와 형식 메타데이터를 보관합니다. 편집하지 않은 저장은 원본 바이트를 그대로 새 날짜 파일에 씁니다. 편집 저장은 원래 인코딩·BOM·대표 줄바꿈을 적용합니다. 같은 폴더의 임시 파일을 flush·fsync한 후 `os.replace`로 교체합니다.
