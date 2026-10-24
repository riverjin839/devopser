# notion-study-kit

스터디 페이지(노션) + 동적 다이어그램(Archify, 그린 테마) 제작 도구 모음.

| 파일 | 역할 |
|---|---|
| `build.py` | specs.py(N/E 정의) → Archify finalize → green_theme 적용 HTML 생성 |
| `green_theme.py` | Archify HTML 후처리 : 라이트 그린 테마, 동적 기본값, 툴바 숨김, 폭 맞춤, 여백 자동 크롭 |
| `shot.js` | 노션 폭(630/1250px) 렌더 검사 : 높이, 가로 스크롤, 글자 넘침 |
| `to_notion.py` | 블로그 MD → 노션 MD (표 → `<table>`, 특수문자 이스케이프, 첫 `##` 제목 제거) |
| `md_to_notion.py` | 위 변환 + `<!-- diagram: X.html -->` → 임베드, 관련 글 → 페이지 멘션, 한 장 요약 표 폭 |
| `examples/specs_example.py` | 다이어그램 정의 예시 |

## 준비

```bash
git clone https://github.com/tt-a1i/archify.git          # Archify (bin/archify.mjs)
export ARCHIFY_CHROME=/opt/pw-browsers/chromium-*/chrome-linux/chrome   # 없으면 browser-check 건너뜀
```

## 사용

```bash
python3 build.py specs.py ~/.archify/<새폴더> archify/bin/archify.mjs green_theme.py out/
node shot.js out/ shots/ 630
python3 md_to_notion.py page.md page.notion.md ids.json related.json
```

- workdir 는 매번 새 폴더 (재사용하면 evidence-path-conflict 로 FAIL)
- 노션 업로드 : GitHub 에 push → raw URL(커밋 SHA 고정)을 notion create-attachment `source_url` 로
