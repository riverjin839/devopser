# notion-study-kit

스터디 페이지(노션) + 동적 다이어그램(Archify, 그린 테마) 제작 도구 모음.

| 파일 | 역할 |
|---|---|
| `build.py` | specs.py(N/E 정의) → Archify finalize → green_theme 적용 HTML 생성 |
| `green_theme.py` | Archify HTML 후처리 : 라이트 그린 테마, 동적 기본값, 툴바 숨김, 폭 맞춤, 여백 자동 크롭 |
| `build_autumn.py` | Autumn leaves 테마용 빌더. 노션 프레임(4:3)에 맞게 stepy 자동 조정, 채움 비율 출력 |
| `autumn_theme.py` | Archify HTML 후처리 : Autumn leaves 팔레트, 프레임 꽉 채움(contain·가운데 정렬) |
| `shot.js` | 렌더 검사 : 높이, 가로 스크롤, 글자 넘침. `838 625` 처럼 높이를 주면 노션 프레임 채움(fill) 측정 |
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

## 노션 임베드 빈 공간

- 노션 HTML 임베드는 내용 높이와 상관없이 프레임 높이가 고정됨 (기본 약 4:3, 예 838×625). API 로 높이 지정 불가
- 그래서 그림이 가로로 길면 아래가 하얗게 남음
- 대응 1 : `autumn_theme.py` 가 SVG 를 프레임 전체에 contain 으로 채우고 가운데 정렬함
- 대응 2 : 배치를 4:3 근처로 잡음. 노드 6개 이하 = 2열 x 3행, 7개 이상 = 3열 x 3~4행. 2행짜리 3열 배치는 금지
- `build_autumn.py` 가 stepy 를 자동으로 늘리고 `채움 %` 를 찍음. 80% 미만이면 경고
- 확인 : `node shot.js out/ frame/ 838 625` → fill 0.9 이상
- 프레임 비율이 다르면 `ASPECT=1.6 python3 build_autumn.py ...`
- workdir 은 `/home/claude` 아래에 둘 것 (`~/.archify` 는 /root 라 meta-path-syntax FAIL)
