## LLM Wiki on Mac - 로컬 LLM 으로 쌓이는 개인 지식 위키 만들기

> **목표** : Karpathy 의 LLM Wiki 패턴을 *Local AI Models on a Mac* 책 스택(Ollama, MLX Whisper, Streamlit, ChromaDB)으로 Mac 안에서만 돌게 옮기고, 아이디어 → 아키텍처 → 실습 코드 → 사내 확장까지 정리함

- 출처 : Andrej Karpathy, *LLM Wiki* gist (442a6bf555914893e9891c11519de94f) / Keiji Kamigusa, *Build Applications with Local AI Models on a Mac* 8~16장 / tobi/qmd README
- 기준 버전 : Ollama 0.40.17, ollama-python 0.6.3, qmd 2.9.0, pypdf 7.1.1, chromadb 1.5.9 (2026-11 기준)
- 실습 코드 : `llm-wiki-mac/wiki.py` (init · ingest · query · lint 240줄), 가짜 Ollama 로 전 과정 테스트 완료

---

## 1. 개요

- LLM Wiki = 원본을 매번 검색(RAG)하는 대신, LLM 이 원본을 읽고 **마크다운 위키를 계속 고쳐 쓰는** 방식
- gist 는 Claude Code·Codex 같은 클라우드 에이전트를 전제로 함 → 이 글은 같은 패턴을 Mac 로컬 모델로 돌리는 구성
- 책이 이미 부품을 다 줌. Ollama(4장), Modelfile(13장), 오프라인 검증(14장), MLX Whisper(9장), Streamlit(8장), RAG·에이전트(16장)

<!-- diagram: llmwiki-overview.html -->

**작은 로컬 모델에게 위키 전체를 맡기지 않고 역할을 나누는 게 Mac 버전의 핵심임**

- LLM : 요약 문장, 개념 이름, 근거 메모를 JSON 으로 써서 돌려준다
- 코드 : 그걸 받아서 파일로 저장하고, 링크를 걸고, index·log 를 갱신한다

---

## 2. 개념 정리

### 2-0. 먼저 짚는 용어 - 위키, gist, 스키마, 음성 메모 텍스트 변환

#### 2-0-1. 위키(wiki) 는 특정 양식이 아님

- 위키 = 한 주제를 한 페이지로 쓰고, 페이지끼리 링크로 잇는 문서 묶음
- MediaWiki·Confluence 같은 특정 제품이나 정해진 서식을 뜻하지 않음
- LLM Wiki 에서의 실체 = 폴더 안의 평범한 `.md` 파일들 + `[[링크]]`

| 구분 | 위키백과 | 사내 위키 (Confluence 등) | LLM Wiki |
|---|---|---|---|
| 저장 형태 | MediaWiki DB | 제품 DB | 마크다운 파일 폴더 |
| 쓰는 주체 | 다수 사람 | 팀원 | LLM (사람은 방향·검토) |
| 페이지 단위 | 한 표제어 | 자유 | 원본 1개, 개념 1개, 질의 1개 |
| 연결 | 내부 링크 | 링크·라벨 | `[[sources/x]]` 같은 위키 링크 |
| 보는 도구 | 웹 | 웹 | Obsidian, 에디터, 정적 사이트 |

- 정해진 건 두 파일뿐임 → `index.md`(전체 목록 + 한 줄 요약), `log.md`(시간순 기록)
- 나머지 페이지 종류·양식은 스키마(2-0-3)에서 정함
- 이 글의 페이지 종류 = `sources/`(원본 요약), `concepts/`(개념), `analyses/`(저장한 질의 답)

```markdown
# RAG

> 검색 증강 생성

## 근거

- [[sources/local-ai-mac]] : 문서를 잘라 벡터 DB 에 넣고 질문과 가까운 조각을 context 로 넣음
- [[sources/essential-graphrag]] : 그래프 구조로 검색 범위를 넓힘
```

- 위 예시 = `concepts/rag.md`. 원본이 늘수록 근거 줄이 쌓이는 구조
- 파일이라서 Obsidian 으로 열면 그래프로 보이고, git 으로 이력 관리가 되고, 다른 도구로 옮기기도 쉽다

#### 2-0-2. gist

- gist = GitHub 의 짧은 코드·글 공유 서비스 (gist.github.com)
- 실체는 작은 git 저장소 → 수정 이력, fork, 댓글이 있음. 공개·비밀(secret, 링크 아는 사람만) 선택 가능
- 레포를 만들 만큼은 아닌 스크립트, 설정 파일, 메모를 올릴 때 씀

| 구분 | gist | GitHub 레포 |
|---|---|---|
| 용도 | 파일 몇 개짜리 코드·글 | 프로젝트 전체 |
| 구조 | 폴더 없음, 파일 나열 | 폴더·브랜치·이슈·PR |
| 이력 | git 이력 (revision) | git 이력 |
| 공유 | URL 하나 | URL, 권한, 팀 |

- Karpathy 의 LLM Wiki 는 코드가 아니라 "아이디어 문서" 하나를 gist 로 공개한 것
- 문서 자체가 일부러 추상적임 → 내 LLM 에이전트에 붙여 넣고 내 환경에 맞게 구체화하라는 의도
- 이 글도 같은 방식임 → gist 의 패턴을 Mac 로컬 환경에 맞게 구체화한 것

#### 2-0-3. 스키마(schema) = 위키를 만드는 규칙 문서

- 스키마 = "이 위키는 이렇게 만든다" 를 적은 문서. LLM 이 작업 전에 읽는 설명서
- 파일 이름은 보통 `AGENTS.md` 또는 `CLAUDE.md`
- Claude Code 는 `CLAUDE.md`, Codex 는 `AGENTS.md` 를 자동으로 읽음 → 그래서 이 이름을 씀

| 구분 | DB 스키마 | 위키 스키마 |
|---|---|---|
| 정하는 것 | 테이블, 컬럼, 타입 | 페이지 종류, 양식, 이름·링크 규칙 |
| 형식 | DDL (`CREATE TABLE`) | 자연어 마크다운 |
| 강제력 | 어긋나면 DB 가 거부 | 없음. LLM 이 읽고 따를 뿐 |
| 바꾸는 법 | 마이그레이션 | 문서 수정 → 다음 작업부터 적용 |
| 공통점 | 데이터 모양을 미리 정함 | 데이터 모양을 미리 정함 |

스키마에 적는 항목

| 항목 | 예 |
|---|---|
| 폴더 구조 | `sources/` = 원본 요약, `concepts/` = 개념, `analyses/` = 질의 결과 |
| 페이지 양식 | `# 제목` → `> 한 줄 정의` → `## 근거` |
| 이름 규칙 | 같은 개념은 같은 이름. "검색 증강 생성" 대신 "RAG" |
| 동작 규칙 | ingest 때 index·log 갱신, 원본에 없는 내용 금지 |
| 언어·톤 | 한국어, 기술 용어는 영문 병기 |

```markdown
# AGENTS.md - 위키 규칙
- 언어 : 한국어, 기술 용어는 영문 병기
- 원본(raw/)은 읽기만 함
- 요약은 원문에 있는 내용만. 추측 금지
- 개념 이름은 짧은 명사구, 같은 개념은 같은 이름 (예: "RAG", "양자화")
- 개념 페이지 = 한 줄 정의 + 근거 줄([[sources/x]] : 메모)
```

- gist 원형 = 사람이 초안을 쓰고, 위키를 쓰면서 LLM 과 같이 고쳐 감
- 이 글의 Mac 버전 = 스키마를 둘로 나눔

| 규칙 종류 | 어디에 둠 | 이유 |
|---|---|---|
| 내용 규칙 (언어, 이름, 추측 금지) | `AGENTS.md` → 프롬프트에 그대로 넣음 | 언어 판단은 LLM 이 해야 함 |
| 형식 규칙 (폴더, 양식, 링크 문법) | `wiki.py` 코드 | 작은 모델은 읽어도 형식을 자주 틀림 |

> 주의 : 스키마는 강제력이 없음. 4B~8B 모델에게 "양식을 지켜라" 만 적어 두면 페이지마다 모양이 달라짐 → 반드시 지켜야 하는 형식은 코드로 옮겨야 한다

#### 2-0-4. 음성 메모 → Whisper 텍스트 변환

- LLM 은 소리를 직접 못 읽음 → 녹음은 먼저 글자로 바꿔야 위키 원본이 됨
- 이 작업을 언어학·녹취 분야에선 전사(transcription), AI 쪽에선 STT(Speech-to-Text) 라고 부름
- 이 글에선 헷갈리지 않게 "음성 메모 → Whisper 텍스트 변환" 으로 씀

| 단계 | 도구 | 결과 |
|---|---|---|
| 1. 녹음 | 아이폰·Mac 음성 메모 | `.m4a` 파일 |
| 2. 텍스트 변환 | MLX Whisper (책 9장, Apple Silicon 최적화) | 문장 텍스트 |
| 3. 원본 저장 | `voice_to_raw.py` | `raw/voice/<이름>.md` |
| 4. 위키 반영 | `wiki.py ingest` | sources·concepts 페이지 갱신 |

- 모델 크기 = 책 기준 8GB Mac 은 small, 16GB 이상은 medium 부터. 정확도 우선이면 large-v3
- 회의 녹음, 출퇴근길 아이디어 메모, 강의 녹음이 원본 후보
- 단, 변환 결과는 말버릇·반복이 그대로 남음 → ingest 단계에서 LLM 이 요약하므로 따로 다듬지 않아도 됨
- 단, 고유명사·약어(Cilium, CNPG 등)는 자주 틀림 → `initial_prompt` 에 용어를 넣거나, 스키마 이름 규칙으로 통일

### 2-1. RAG vs LLM Wiki

| 구분 | RAG (책 16.1) | LLM Wiki (gist) |
|---|---|---|
| 지식 위치 | 원본 조각 + 벡터 DB | LLM 이 정리한 마크다운 페이지 |
| 질문할 때 | 매번 원본에서 조각 검색 → 처음부터 다시 종합 | 이미 종합된 위키 페이지를 읽음 |
| 축적 | 없음. 같은 종합을 반복 | 원본 추가·좋은 답이 위키에 쌓임 |
| 모순 처리 | 검색된 조각끼리 충돌해도 모름 | lint 로 모순·오래된 주장 표시 |
| 사람 역할 | 문서 넣고 질문 | 원본 고르기·질문·방향 잡기 |
| 비용 | 질문마다 검색 + 긴 context | 수집 때 한 번 많이, 질문은 가벼움 |

- gist 비유 = Obsidian 이 IDE, LLM 이 프로그래머, 위키가 코드베이스
- 위키 = 지식을 한 번 "컴파일" 해 두고 계속 갱신하는 산출물. RAG = 매번 인터프리트
- 단, 원본이 수천 개 넘거나 원문 인용이 꼭 필요하면 RAG 가 여전히 유리함 → 둘은 배타적이지 않음 (2-4)

### 2-2. 세 계층과 세 동작

| 계층 | 내용 | 누가 씀 |
|---|---|---|
| raw/ | 책 PDF, 기사, 음성 메모(Whisper 텍스트), 이미지 | 사람이 넣음. 읽기 전용 |
| wiki/ | sources/(원본 요약), concepts/(개념), analyses/(질의 결과), `index.md`, `log.md` | LLM(+코드) |
| `AGENTS.md` | 위키 규칙. 언어, 개념 이름 규칙, 근거 표기 방식 | 사람과 LLM 이 같이 다듬음 |

| 동작 | gist 정의 | Mac 버전 구현 |
|---|---|---|
| Ingest | 원본 하나가 위키 10~15페이지를 건드림 | 청크별 JSON 추출 → source 페이지 생성 → concept 페이지에 근거 줄 추가 |
| Query | index 먼저 읽고 관련 페이지 → 인용 포함 답 | index → 페이지 고르기(JSON) → 존재 확인 → 답 → `--save` 로 analyses 저장 |
| Lint | 모순, 오래된 주장, 고아, 빠진 링크 | 고아·깨진 링크·미수집 원본은 코드로, 모순은 LLM 으로 |

- `index.md` = 내용 목록(카탈로그). 페이지마다 링크 + 한 줄 요약
- `log.md` = 시간순 기록. `## [2026-11-22] ingest | 제목` 접두어 → `grep "^## \[" log.md | tail -5` 로 바로 조회
- gist 기준 `index.md` 만으로 원본 ~100개, 페이지 수백 개까지는 임베딩 검색 없이 동작

### 2-3. 왜 Mac 에선 LLM 과 코드의 역할을 나누나

- LLM : 요약 문장, 개념 이름, 근거 메모를 JSON 으로 써서 돌려준다
- 코드 : 그걸 받아서 파일로 저장하고, 링크를 걸고, index·log 를 갱신한다

- gist 의 LLM 은 Claude Code 급 에이전트 → 파일을 직접 열고 고치고 index 갱신까지 스스로 함
- 책 16.5 기준 에이전트(도구 호출)는 7B 이상부터 쓸 만함, gemma3:4b 는 제한적
- M1 Pro 16GB 상한 = 8B Q4 → 파일 10~15개를 도구 호출로 고치게 두면 링크가 깨지고 index 가 어긋남
- 해결 = Ollama structured outputs. `ollama.chat(..., format=<JSON schema>)` 로 응답 모양을 강제함

<!-- diagram: llmwiki-split.html -->

| 일 | 담당 | 이유 |
|---|---|---|
| 요약 문장, 개념 이름, 근거 메모 | LLM (JSON) | 언어 이해가 필요한 부분 |
| 파일 경로, slug, `[[링크]]` 문법 | 코드 | 작은 모델이 자주 틀리는 형식 |
| `index.md` 재생성 | 코드 | 매번 전체 재생성 → 어긋날 일 없음 |
| `log.md` 추가 | 코드 | 날짜 형식 고정 |
| 개념 페이지 갱신 | 코드 (덧붙이기만) | 기존 내용 재작성 금지 → 정보 유실 방지 |
| 모순 판단 | LLM | 근거 2개 이상 개념만 검사 |

> 주의 : 개념 페이지를 LLM 에게 "다시 써 줘" 로 갱신시키면 4B 모델은 기존 근거를 빼먹는 경우가 많음. 덧붙이기 + 주기적 사람 검토가 안전함

### 2-4. 검색 계층 - `index.md` 다음 단계

| 단계 | 방식 | 언제 |
|---|---|---|
| 1 | `index.md` 를 통째로 context 에 넣음 | 페이지 수백 개까지. num_ctx 8192 기준 index 한 줄 ~30토큰이면 ~200줄 |
| 2 | qmd (BM25 + 벡터 + LLM rerank, 전부 로컬 GGUF) | index 가 context 를 넘을 때. CLI·MCP 서버 제공 |
| 3 | ChromaDB + Ollama 임베딩 (책 16.1) | 이미 RAG 코드가 있거나 Python 안에서 끝내고 싶을 때 |

- qmd = tobi 가 만든 로컬 마크다운 검색 엔진. node-llama-cpp 로 GGUF 3개(임베딩 ~300MB, reranker ~640MB, 쿼리 확장 1.7B ~1.1GB)를 `~/.cache/qmd/models` 에 받아 씀
- 한국어 위키면 임베딩을 Qwen3-Embedding 으로 바꿈 → `QMD_EMBED_MODEL` 지정 후 `qmd embed -f`
- ChromaDB 기본 임베딩(all-MiniLM-L6-v2)은 영어 위주 → 한국어는 `OllamaEmbeddingFunction` + bge-m3

---

## 3. 아키텍처 - Mac 한 대 안에서

<!-- diagram: llmwiki-mac-stack.html -->

| 계층 | 구성 | 책 근거 |
|---|---|---|
| 입력 | PDF·MD 는 raw/ 에 복사, 음성 메모 → MLX Whisper 로 텍스트 변환 → raw/voice/ | 9장 |
| 모델 | Ollama `localhost:11434`, gemma3:4b 기본 / 8B Q4 상한 | 4장, 12장 RAM 표 |
| 모델 설정 | Modelfile 로 wiki 전용 모델. SYSTEM 에 `AGENTS.md` 요약, `num_ctx 8192`, 낮은 temperature | 13장 |
| 위키 엔진 | `wiki.py` (ingest · query · lint) | 이 글 5장 |
| 검색 | `index.md` → qmd → ChromaDB 순으로 확장 | 16.1 |
| 보기 | Obsidian (그래프 뷰, 백링크), 질의 UI 는 Streamlit 채팅 | 8장 |
| 이력 | wiki/ 를 git 으로 관리. ingest 마다 커밋 | gist |
| 네트워크 | 모델 받은 뒤 Wi-Fi 끄고 전 과정 동작 확인 | 14장 |

### 3-1. 메모리 예산 (M1 Pro 16GB)

| 조합 | 대략 사용량 | 판단 |
|---|---|---|
| gemma3:4b + num_ctx 8192 | ~5GB | 기본. Obsidian·브라우저 같이 써도 여유 |
| llama3.1:8b Q4 + num_ctx 8192 | ~7GB | 요약 품질 우선일 때 |
| 8B + whisper medium + qmd 모델 | ~10GB 이상 | GPU 사용 가능 ~10.7GB 에 근접 → 동시에 돌리지 말 것 |

- 텍스트 변환(Whisper) → 수집(Ollama) → 색인(qmd) 을 순서대로 돌리면 한 번에 한 모델만 메모리에 올라감
- `ollama ps` 로 실제 컨텍스트 할당 확인, `OLLAMA_KEEP_ALIVE` 를 짧게 두면 다음 단계 전에 내려감

### 3-2. 대안 구성 비교

| 구성 | 장점 | 단점 | 언제 |
|---|---|---|---|
| Claude Code·Codex + 클라우드 모델 (gist 원형) | 에이전트가 위키 전체를 알아서 관리, 품질 최고 | 원본이 외부로 나감, 사용량 비용 | 공개 자료, 개인 학습 |
| 완전 로컬 Ollama + `wiki.py` (이 글) | 데이터가 Mac 밖으로 안 나감, 비용 0, 오프라인 | 요약 품질이 모델 크기에 묶임, 수집 느림 | 사내 문서, 민감 메모 |
| 하이브리드 | 수집은 로컬, 가끔 lint·재구성만 클라우드 | 어떤 페이지를 보낼지 관리 필요 | 품질과 보안 둘 다 필요할 때 |
| 로컬 에이전트 (Ollama 도구 호출) | gist 와 같은 자율성 | 16GB 에선 도구 호출 신뢰도 낮음 | 32GB 이상 Mac, 14B 이상 모델 |

---

## 4. 동작 흐름

### 4-1. Ingest

<!-- diagram: llmwiki-ingest.html -->

1. 원본 위치 확인 → raw/ 밖이면 거부 (원본 불변 원칙)
2. pypdf 로 텍스트 추출 → `WIKI_CHUNK`(기본 6000자) 단위로 자름
3. 청크마다 `format=INGEST_SCHEMA` 로 `{title, summary[], concepts[{name, note}]}` 받음
4. `sources/<slug>.md` 생성. frontmatter 에 원본 경로·수집일·청크 수
5. 개념마다 `concepts/<slug>.md` → 없으면 생성, 있으면 `- [[sources/x]] : 근거` 한 줄 덧붙임, 같은 원본이면 건너뜀
6. `index.md` 전체 재생성 → `log.md` 에 `ingest` 한 줄

- 책 300쪽 PDF ≈ 60만 자 → 청크 100개 내외 → gemma3:4b 로 수십 분 단위. 밤에 돌리는 배치로 생각하는 게 맞음
- 단, 장 단위로 PDF 를 쪼개 넣으면 source 페이지가 장별로 생겨 위키 구조가 좋아짐

### 4-2. Query

<!-- diagram: llmwiki-query.html -->

1. `index.md` 를 읽고 `format=PICK_SCHEMA` 로 필요한 페이지 경로 최대 5개 받음
2. 실제 파일이 있는 경로만 남김 → 모델이 지어낸 경로 제거
3. 해당 페이지만 근거로 답, 문장마다 `[[경로]]` 인용
4. `--save` 면 `analyses/` 에 저장 → index·log 갱신 → 다음 질문부터 이 답도 위키의 일부

- gist 핵심 = 좋은 답을 채팅에 흘려보내지 않고 위키로 되돌려 넣는 것 → 질문할수록 위키가 두꺼워짐

### 4-3. Lint

| 검사 | 방법 | 조치 |
|---|---|---|
| 깨진 링크 | `[[x]]` 대상 파일 없음 | 링크 수정 또는 페이지 생성 |
| 고아 개념 | 아무 페이지도 링크 안 하는 concept | 관련 source 에 링크 추가 또는 삭제 |
| 미수집 원본 | raw/ 에 있는데 sources/ 에 없음 | ingest 실행 |
| 모순 (`--llm`) | 근거 2개 이상인 개념만 LLM 검사 | 사람이 원본 확인 후 정리 |

- 코드 검사는 매번, LLM 검사는 주 1회 정도 → 시간 대부분이 모순 검사에서 나옴

---

## 5. 실습

### 5-1. 준비

```bash
# 모델 (책 4장)
brew install ollama && ollama serve &
ollama pull gemma3:4b

# 위키 폴더
mkdir -p ~/llm-wiki && cd ~/llm-wiki
python3 -m venv .venv && source .venv/bin/activate
pip install ollama pypdf
curl -O https://raw.githubusercontent.com/riverjin839/devopser/mlpe-study-diagrams/llm-wiki-mac/wiki.py

python wiki.py init          # raw/ wiki/ AGENTS.md 생성
git init && git add -A && git commit -m "wiki init"
```

### 5-2. wiki 전용 모델 (책 13장 Modelfile)

```dockerfile
FROM gemma3:4b
PARAMETER temperature 0.2
PARAMETER num_ctx 8192
SYSTEM """원문에 있는 내용만 한국어로 정리함. 추측하지 않음. 같은 개념은 같은 이름으로 씀."""
```

```bash
ollama create wiki-gemma -f Modelfile
export WIKI_MODEL=wiki-gemma
```

### 5-3. 핵심 코드 - LLM 이 JSON 으로 써서 돌려주기

```python
INGEST_SCHEMA = {                      # 응답 모양 강제
    "type": "object",
    "properties": {
        "title":    {"type": "string"},
        "summary":  {"type": "array", "items": {"type": "string"}},
        "concepts": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "note": {"type": "string"}},
            "required": ["name", "note"]}},
    },
    "required": ["title", "summary", "concepts"],
}

def chat_json(system, user, schema):
    r = ollama.chat(model=MODEL, format=schema, options={"temperature": 0.2, "num_ctx": 8192},
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}])
    return json.loads(r["message"]["content"])
```

### 5-4. 핵심 코드 - 개념 페이지는 덧붙이기만

```python
def upsert_concept(name, note, src):
    p = WIKI / "concepts" / f"{slug(name)}.md"
    line = f"- [[sources/{src}]] : {note.strip()}"
    if not p.exists():
        p.write_text(f"# {name}\n\n> {note.strip()}\n\n## 근거\n\n{line}\n", encoding="utf-8")
        return "new"
    body = p.read_text(encoding="utf-8")
    if f"[[sources/{src}]]" in body:      # 같은 원본 재수집 → 중복 안 넣음
        return "same"
    p.write_text(body.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")
    return "append"
```

### 5-5. 돌려 보기

```bash
cp ~/book/local-ai-mac.pdf raw/
python wiki.py ingest raw/local-ai-mac.pdf
python wiki.py query "RAG 와 Modelfile SYSTEM 중 무엇부터 바꾸나" --save
python wiki.py lint --llm
git add -A && git commit -m "ingest local-ai-mac"
grep "^## \[" wiki/log.md | tail -5
```

가짜 Ollama 로 돌린 테스트 결과 (원본 3개 중 2개 수집, 재수집 1회, 질의 저장, lint)

```text
ingest 완료 : sources/notes.md, 개념 신규 1 · 추가 1 · 중복 0
ingest 완료 : sources/notes.md, 개념 신규 0 · 추가 0 · 중복 2     ← 재수집해도 중복 없음
원본은 raw/ 아래에 두고 넣을 것                                    ← raw/ 밖 거부
페이지 7 · 깨진 링크 1 · 고아 개념 1 · 미수집 원본 1
  깨진 링크 : concepts/외톨이 → [[concepts/없는링크]]
  미수집    : later.md
  검토 필요 : concepts/rag - 모순: 근거 두 줄의 설명 범위가 다름
```

### 5-6. 음성 메모를 원본으로 (책 9장)

```python
# voice_to_raw.py - 개념 코드. 음성 메모 → Whisper 텍스트 → raw/voice/
import mlx_whisper, pathlib, sys
src = pathlib.Path(sys.argv[1])
r = mlx_whisper.transcribe(str(src), path_or_hf_repo="mlx-community/whisper-medium-mlx", language="ko")
out = pathlib.Path("raw/voice") / f"{src.stem}.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(f"# 음성 메모 {src.stem}\n\n{r['text']}\n", encoding="utf-8")
print(out)   # → python wiki.py ingest raw/voice/<이름>.md
```

### 5-7. 검색 확장 - qmd

```bash
npm install -g @tobilu/qmd                         # node 22 이상
export QMD_EMBED_MODEL="hf:Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf"
qmd collection add ~/llm-wiki/wiki --name wiki
qmd embed
qmd query "양자화 와 메모리" --json                 # BM25 + 벡터 + rerank
qmd mcp --http                                     # localhost:8181, 에이전트 도구로 연결
```

- `wiki.py` query 에서 `index.md` 대신 `qmd query --json` 결과 상위 경로를 쓰면 1단계 → 2단계 전환 끝
- 첫 실행 때 HF 에서 GGUF 를 받음 → 오프라인 전에 한 번 돌려서 캐시해 둘 것

### 5-8. 보기 - Obsidian

- `~/llm-wiki/wiki` 를 Vault 로 열면 `[[sources/x]]` 링크가 그대로 동작 → 그래프 뷰로 허브 개념과 고아 페이지가 보임
- gist 팁 = 한쪽에 LLM 터미널, 한쪽에 Obsidian. 수집 직후 그래프를 보고 다음 질문을 정함
- 질의를 채팅으로 하고 싶으면 책 8장 Streamlit 채팅에 `cmd_query` 를 연결 (`st.session_state` 에 이전 질문 보관)

---

## 6. 실무에서 확인

### 6-1. 내 Mac (M1 Pro 16GB)

- 이번에 뽑은 Manning 책 PDF 12권이 바로 raw/ 후보 → 장 단위로 잘라 넣으면 책 간 공통 개념(양자화, RAG, K8s 스케줄링)이 concept 페이지에서 합쳐짐
- 책 원문은 위키 안에서만 쓰고 외부 공유 금지. sources 페이지는 요약만 둠
- 수집은 gemma3:4b, 주간 lint 모순 검사만 llama3.1:8b → 품질과 속도 절충
- 한글 slug 는 Obsidian·git 모두 문제없음. 단, macOS 파일명 NFD 정규화로 git 에서 다른 파일처럼 보일 수 있음 → `git config core.precomposeunicode true`

### 6-2. 팀 운영 위키로 확장 (폐쇄망 K8s)

<!-- diagram: llmwiki-team.html -->

- raw/ = 장애 보고서, 런북, 회의록, 릴리즈 노트 → AIStor 버킷에 원본 불변 저장 (버킷 버전 관리 + 삭제 금지 정책)
- 모델 = 클러스터 Ollama 또는 vLLM. `wiki.py` 는 `OLLAMA_HOST` 만 바꾸면 그대로 붙음
- qmd·임베딩 GGUF = HF 프록시(dmz-nexus) 경유 반입 → `~/.cache/qmd/models` 를 PVC 로 미리 채움
- wiki/ = Git 저장소(사내 Git) → ArgoCD 와 무관하게 사람이 PR 로 검토, 위키 변경도 리뷰 대상
- 보기 = Obsidian 대신 MkDocs·Wiki.js 로 정적 사이트, 인증은 Keycloak OIDC

```yaml
# 개념 코드 - 매일 새벽 lint, 결과는 log.md 에 남고 git push
apiVersion: batch/v1
kind: CronJob
metadata: { name: llm-wiki-lint, namespace: ops-wiki }
spec:
  schedule: "30 3 * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: lint
              image: nexus.internal/ops/llm-wiki:0.1      # wiki.py + git 이 든 이미지
              env:
                - { name: OLLAMA_HOST, value: "http://ollama.llm.svc:11434" }
                - { name: WIKI_MODEL,  value: "llama3.1:8b" }
                - { name: WIKI_ROOT,   value: "/wiki" }
              command: ["sh", "-c", "git pull && python /app/wiki.py lint --llm && git commit -am lint && git push"]
              volumeMounts: [{ name: wiki, mountPath: /wiki }]
          volumes:
            - name: wiki
              persistentVolumeClaim: { claimName: llm-wiki }
```

> 주의 : 팀 위키는 원본마다 열람 권한이 다름. 권한이 다른 원본을 한 concept 페이지에 합치면 요약을 통해 정보가 샘 → 네임스페이스·권한 단위로 위키를 나누는 게 먼저임 (LLM 인가 글과 같은 문제)

### 6-3. 함정

| 함정 | 증상 | 대응 |
|---|---|---|
| num_ctx 기본값 | 긴 청크 뒷부분 무시, 요약이 앞부분만 | 옵션이나 Modelfile 로 명시, `ollama ps` 확인 |
| 개념 이름 흔들림 | "RAG", "검색 증강 생성", "Retrieval" 이 각각 페이지 | `AGENTS.md` 에 표준 이름 목록, lint 에서 유사 이름 묶기 |
| 요약 환각 | 원문에 없는 수치 | 근거 줄에 원본 링크 필수, 수치는 사람이 확인 |
| PDF 추출 품질 | 코드블록·표가 깨진 텍스트 | 장 단위 MD 변환 후 넣기, 스캔본은 OCR 먼저 |
| index 비대화 | 질의 첫 단계가 context 초과 | 2-4 단계표대로 qmd 전환 |
| 오프라인 첫 실행 | qmd·Whisper 가 모델을 받으려다 실패 | 온라인에서 한 번 실행해 캐시 → Wi-Fi 끄고 재확인 (14장) |

---

## 7. 용어 정리

- **LLM Wiki** : LLM 이 원본을 읽고 마크다운 위키를 계속 갱신하며 쌓아 가는 지식 저장 패턴
- **위키(wiki)** : 특정 제품·양식이 아니라, 한 주제를 한 페이지로 쓰고 `[[링크]]` 로 서로 잇는 마크다운 파일 묶음. 페이지 종류와 형식은 스키마에서 정함
- **gist** : GitHub 의 짧은 코드·글 공유 서비스(gist.github.com). 레포를 만들지 않고 파일 몇 개를 올리는 작은 git 저장소. Karpathy 가 LLM Wiki 아이디어를 이 형태로 공개함
- **원본(raw sources)** : 위키의 근거 자료. LLM 이 읽기만 하는 불변 계층
- **스키마(schema)** : `AGENTS.md`·`CLAUDE.md` 처럼 위키 규칙을 적은 설정 문서
- **수집(ingest)** : 원본 하나를 읽고 요약·개념·링크를 위키 여러 페이지에 반영하는 동작
- **린트(lint)** : 모순, 고아 페이지, 깨진 링크, 빠진 원본을 찾는 위키 건강 검사
- **`index.md`** : 위키 전체 페이지 목록과 한 줄 요약. 질의의 첫 단계
- **`log.md`** : 수집·질의·린트를 시간순으로 남긴 추가 전용 기록
- **구조화 출력(structured outputs)** : Ollama `format` 에 JSON 스키마를 넣어 응답 모양을 강제하는 기능
- **슬러그(slug)** : 제목을 파일 이름용으로 바꾼 문자열
- **고아 페이지(orphan page)** : 다른 페이지에서 들어오는 링크가 없는 페이지
- **qmd** : BM25·벡터·rerank 를 로컬 GGUF 로 돌리는 마크다운 검색 엔진
- **Memex** : 1945 년 Vannevar Bush 가 구상한 개인 연상 지식 기계. gist 가 계보로 언급

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 아이디어 | 매번 검색하는 RAG 대신 LLM 이 위키를 고쳐 쓰며 지식을 쌓음 |
| 세 계층 | raw/ 불변 원본, wiki/ LLM 산출물, `AGENTS.md` 규칙 |
| 세 동작 | ingest 로 반영, query 로 답하고 저장, lint 로 점검 |
| Mac 버전 원칙 | LLM 은 요약 문장, 개념 이름, 근거 메모를 JSON 으로 써서 돌려주고, 코드는 그걸 받아서 파일로 저장하고, 링크를 걸고, index·log 를 갱신한다 |
| 모델 | gemma3:4b 기본, 8B Q4 상한, Modelfile 로 num_ctx·temperature 고정 |
| 검색 확장 | `index.md`, qmd, ChromaDB 순 |
| 입력 확장 | 음성 메모 → Whisper 텍스트를 raw/voice 로 |
| 사내 확장 | AIStor 원본, 클러스터 Ollama, Git 위키, lint CronJob, 권한 단위 분리 |

**작은 로컬 모델로도 LLM Wiki 는 돌아가고, 조건은 LLM 이 JSON 으로 써서 돌려주고 저장·링크·index·log 갱신은 코드가 맡는 구조로 짜는 것이다**

---

## 9. 응용 - LLM Wiki 로 kubespray K8s 설치 보조

> **목표** : kubespray 문서를 로컬 LLM Wiki 에 넣고, 그 위키를 근거로 설치 변수를 고르고 실행 로그를 다시 위키에 쌓는 구조가 가능한지 분석하고, M1 Pro Mac 의 VM 2대로 직접 실습함

- 기준 버전 : kubespray v2.32.0 (Kubernetes 1.36.4, etcd 3.6.14, containerd 2.3.5, Calico 3.31.7, Cilium 1.20.2), ansible 12.3.0 = ansible-core 2.19, Lima v2.3.0 (2026-11 기준)
- 실습 코드 : `llm-wiki-mac/gen_vars.py` (가짜 Ollama 테스트 통과), kubespray v2.32.0 `cluster.yml --syntax-check` 통과

### 9-1. 가능한가 - 이론 분석

| 질문 | 판단 | 근거 |
|---|---|---|
| M1 Mac 에서 kubespray 로 K8s 설치 | 가능 | Mac 은 Ansible 실행 머신만 맡고, 노드는 Lima 로 띄운 arm64 Ubuntu 24.04 VM. kubespray 지원 OS 에 Ubuntu 22.04·24.04·26.04 포함 |
| arm64 노드에서 쓸 CNI | Calico, Cilium 만 | kubespray `docs/advanced/arch.md` 호환표 기준 arm64 단독 = Calico Y, Cilium Y, Flannel·kube-router N |
| 메모리 | VM 2대가 현실적 | kubespray 최소값 = control plane 2GB, worker 1GB. Ollama 4B ~5GB 와 같이 쓰면 16GB 에서 VM 3대는 빠듯함 |
| LLM Wiki 가 할 수 있는 일 | 문서 요약, 변수 선택 근거 제시, 에러 로그 정리 | 위키 = kubespray 문서 75개(약 2.2MB)를 개념 단위로 압축한 지식 |
| LLM 이 설치를 직접 실행 | 하지 않음 | 4B~8B 는 도구 호출 신뢰도가 낮음(책 16.5). `cluster.yml` 은 되돌리기 어려운 작업이라 사람이 실행 |

- 결론 = 설치 자체는 kubespray 가 함. LLM Wiki 는 "읽고 고르고 기록하는" 보조 역할로 붙이는 게 맞다
- 단, 위키 내용은 kubespray 버전에 묶임 → 태그가 바뀌면 문서를 다시 ingest 하고 lint 로 오래된 주장을 찾아야 함

### 9-2. 역할 나누기 - 이 글의 원칙을 kubespray 에 그대로

- LLM : 요구사항과 위키 페이지를 읽고, 변수 선택과 근거를 JSON 으로 써서 돌려준다
- 코드 : 허용값·CPU 아키텍처 호환을 검사하고, 통과하면 `group_vars` YAML 로 저장하고 log 에 남긴다
- 사람 : 만들어진 파일을 보고 `ansible-playbook` 을 실행한다

| 일 | 담당 | 이유 |
|---|---|---|
| kubespray 문서 요약·개념 정리 | LLM (ingest) | 75개 문서를 다 읽을 시간 절약 |
| CNI·런타임·kube-proxy 모드 선택과 근거 | LLM (JSON, enum 제한) | 근거 문장과 위키 링크를 같이 받음 |
| 허용값·arm64 호환 검사 | 코드 (`gen_vars.py`) | 호환표 같은 사실은 모델 판단에 맡기지 않음 |
| inventory.ini (노드 IP·그룹) | 사람 | IP·그룹 오류는 바로 장애로 이어짐 |
| `cluster.yml` 실행 | 사람 | 되돌리기 어려움, 실행 전 검토 필요 |
| 실패 로그 정리·재발 방지 메모 | LLM (ingest) + 코드 (fatal 줄 추출) | 다음 설치 때 query 로 바로 찾음 |

### 9-3. 아키텍처

<!-- diagram: llmwiki-kubespray.html -->

| 구성 | 내용 |
|---|---|
| 원본 | `raw/kubespray/` = kubespray v2.32.0 `README.md`, `docs/` 중 필요한 문서, `inventory/sample` 주석 |
| 위키 | `wiki.py ingest` → sources·concepts (예: `concepts/cilium`, `concepts/kube_proxy_mode`) |
| 변수 생성 | `gen_vars.py` → `inventory/lima/group_vars/k8s_cluster/zz-llm.yml` |
| 실행 | Mac 의 kubespray venv 에서 `ansible-playbook -b cluster.yml` |
| 노드 | Lima VM 2대 (cp1 = control plane + etcd, w1 = worker), arm64 Ubuntu 24.04 |
| 되먹임 | 실행 로그 → `fatal:` 줄만 추출 → `raw/runs/` → ingest → 다음 질의 근거 |

메모리 예산 (M1 Pro 16GB)

| 구성 | 할당 | 비고 |
|---|---|---|
| cp1 | 2CPU, 2.5GB | kubespray 최소 2GB 보다 약간 여유 |
| w1 | 2CPU, 2GB | 최소 1GB, 파드 몇 개 올릴 여유 |
| Ollama gemma3:4b | ~5GB | 설치 중엔 내려 둠 (`ollama stop gemma3:4b`) |
| macOS + 브라우저 | ~4~5GB | |

- 순서 = 위키 작업(Ollama 사용) → Ollama 내림 → VM 띄우고 설치 → 로그 ingest(Ollama 다시)
- 동시에 다 띄우지 않는 게 16GB 에서 핵심임

### 9-4. 실습 가이드

#### 9-4-1. 위키에 kubespray 문서 넣기

```bash
cd ~/llm-wiki
git clone -b v2.32.0 --depth 1 https://github.com/kubernetes-sigs/kubespray.git ~/kubespray

mkdir -p raw/kubespray
# 75개 전부 대신 설치에 필요한 문서만 (gemma3:4b 기준 문서당 수 분)
for f in README.md docs/advanced/arch.md docs/ansible/ansible.md docs/ansible/inventory.md \
         docs/CNI/cilium.md docs/CNI/calico.md docs/operations/port-requirements.md \
         docs/operations/offline-environment.md docs/operations/upgrades.md; do
  cp ~/kubespray/$f raw/kubespray/$(echo $f | tr '/' '_')
done
for f in raw/kubespray/*.md; do python wiki.py ingest "$f"; done
python wiki.py lint
```

```bash
# 설치 전에 위키에 물어볼 것
python wiki.py query "arm64 노드에서 쓸 수 있는 CNI 는?" --save
python wiki.py query "control plane 최소 메모리와 필요한 포트" --save
python wiki.py query "kube_proxy_mode 선택지와 차이" --save
```

#### 9-4-2. Lima VM 2대

```bash
brew install lima

# socket_vmnet = VM 끼리, Mac 과 VM 이 같은 대역(192.168.105.0/24)으로 통신하게 해 줌
# Lima 문서 기준 Homebrew 설치는 비권장 → root 소유 경로(/opt/socket_vmnet)에 소스로 설치
git clone https://github.com/lima-vm/socket_vmnet && cd socket_vmnet
git checkout v1.2.2
make && sudo make PREFIX=/opt/socket_vmnet install.bin
cd .. && limactl sudoers > etc_sudoers.d_lima && sudo install -o root etc_sudoers.d_lima /etc/sudoers.d/lima && rm etc_sudoers.d_lima

for n in cp1 w1; do
  mem=$([ $n = cp1 ] && echo 2.5 || echo 2)
  limactl create --name=$n --cpus=2 --memory=$mem --network=lima:shared \
    --set '.containerd.user=false' --tty=false template:ubuntu-24.04   # Lima 기본 rootless containerd 끔
  limactl start $n
done
limactl shell cp1 ip -4 -br addr show lima0     # 192.168.105.x 확인
limactl shell w1  ip -4 -br addr show lima0
```

> 주의 : Lima 기본 네트워크(user-mode)는 모든 VM 이 같은 192.168.5.15 를 받아서 VM 끼리 통신이 안 됨. vzNAT 은 Mac 에서는 닿지만 VM 끼리는 안 됨. etcd·kubelet·CNI 는 노드 간 통신이 필수라 shared(socket_vmnet) 가 필요함

#### 9-4-3. kubespray 준비와 inventory

```bash
cd ~/kubespray
python3.13 -m venv ~/ks-venv && source ~/ks-venv/bin/activate     # ansible-core 2.19 = Python 3.11~3.13
pip install -r requirements.txt                                    # ansible 12.3.0
cp -r inventory/sample inventory/lima
```

```ini
# inventory/lima/inventory.ini  (IP 는 lima0 주소로)
[kube_control_plane]
cp1 ansible_host=192.168.105.2 ip=192.168.105.2 etcd_member_name=etcd1

[etcd:children]
kube_control_plane

[kube_node]
w1 ansible_host=192.168.105.3 ip=192.168.105.3

[all:vars]
ansible_user=<Mac 사용자 이름>                  # Lima VM 기본 사용자 = Mac 사용자
ansible_ssh_private_key_file=~/.lima/_config/user
```

- `k8s_cluster` 그룹은 inventory 에 안 적어도 됨 → kubespray 가 `kube_control_plane` + `kube_node` 로 실행 중에 만듦 (`docs/ansible/inventory.md`)
- 그래서 `ansible-inventory --host w1` 에는 `group_vars/k8s_cluster` 값이 안 보임. 정상임

#### 9-4-4. LLM 으로 변수 초안 만들기

```bash
cd ~/llm-wiki
python gen_vars.py --req "M1 Mac VM 2대, 회사와 같은 Cilium 으로 실습" --arch arm64 \
  --pages concepts/cilium sources/docs_advanced_arch --out ~/kubespray/inventory/lima
```

```yaml
# 결과 예 : inventory/lima/group_vars/k8s_cluster/zz-llm.yml
# gen_vars.py 2026-11-23 | model=gemma3:4b | arch=arm64
# 요구사항 : M1 Mac VM 2대, 회사와 같은 Cilium 으로 실습
# 근거 : arm64 단독 클러스터에서 Cilium 지원 [[sources/docs_advanced_arch]]
kube_network_plugin: cilium
container_manager: containerd
kube_proxy_mode: ipvs
```

- 핵심 코드 = JSON 스키마 enum 으로 1차 제한, 코드로 2차 검사

```py
ALLOWED = {
    "kube_network_plugin": ["calico", "cilium", "flannel", "kube-ovn", "kube-router", "cni"],
    "container_manager":   ["containerd", "crio", "docker"],
    "kube_proxy_mode":     ["ipvs", "iptables", "nftables"],
}
ARCH_CNI = {"amd64": set(ALLOWED["kube_network_plugin"]), "arm64": {"calico", "cilium"}}  # docs/advanced/arch.md

errs = [f"{k}={j.get(k)} 는 허용값 아님" for k, v in ALLOWED.items() if j.get(k) not in v]
if j.get("kube_network_plugin") not in ARCH_CNI[a.arch]:
    errs.append(f"{a.arch} 에서 {j.get('kube_network_plugin')} 미지원 (docs/advanced/arch.md)")
if errs:
    sys.exit("거부 : " + " / ".join(errs))           # 통과 못 하면 파일을 아예 안 씀
```

가짜 Ollama 테스트 결과

```txt
kube_network_plugin: cilium ... 저장 : inv/group_vars/k8s_cluster/zz-llm.yml
거부 : arm64 에서 flannel 미지원 (docs/advanced/arch.md)
위키에 없는 페이지 : concepts/없는것 → 먼저 ingest 할 것
```

#### 9-4-5. 설치 실행과 확인 (사람이 실행)

```bash
ollama stop gemma3:4b                                   # 메모리 비우기
cd ~/kubespray && source ~/ks-venv/bin/activate
ansible -i inventory/lima/inventory.ini all -m ping     # SSH 확인
ansible-playbook -i inventory/lima/inventory.ini cluster.yml --syntax-check
mkdir -p ~/llm-wiki/raw/runs
ansible-playbook -i inventory/lima/inventory.ini -b cluster.yml 2>&1 | tee ~/llm-wiki/raw/runs/cluster-$(date +%F).log

limactl shell cp1 sudo kubectl --kubeconfig /etc/kubernetes/admin.conf get nodes -o wide
limactl shell cp1 sudo kubectl --kubeconfig /etc/kubernetes/admin.conf -n kube-system get pods
```

- 이미지·바이너리 다운로드가 대부분의 시간을 차지함 → 집 회선 기준 수십 분 예상
- 확인 기준 = 노드 2개 Ready, cilium·coredns 파드 Running

#### 9-4-6. 실패 로그를 위키로 되먹임

```bash
cd ~/llm-wiki
# 로그 전체는 수만 줄 → fatal 줄과 바로 앞 TASK 이름만 남겨서 원본으로
log=raw/runs/cluster-$(date +%F).log
grep -B3 -E '^fatal:|FAILED!' $log | grep -E '^TASK|^fatal:|FAILED!' > raw/runs/fail-$(date +%F).md
python wiki.py ingest raw/runs/fail-$(date +%F).md
python wiki.py query "지난 설치에서 실패한 task 와 원인" --save
```

- 다음 설치 전에 같은 질문을 하면 `analyses/` 에 쌓인 답이 먼저 나옴 → 같은 실수 반복 방지
- 정리 = `ansible-playbook -i inventory/lima/inventory.ini -b reset.yml` 또는 `limactl delete -f cp1 w1`

### 9-5. 실무에서 확인 - 폐쇄망 운영 클러스터로 넓힐 때

| 항목 | Mac 실습 | 사내 300+ 노드 |
|---|---|---|
| 원본 | kubespray 공식 문서 | 공식 문서 + 우리 group_vars + 업그레이드 런북 + 장애 기록 |
| 다운로드 | 인터넷 직접 | `offline-environment.md` 대로 files_repo·이미지 레지스트리·OS 저장소 → Nexus(dmz-nexus) |
| 변수 생성 | `gen_vars.py` 가 바로 저장 | 초안만 만들고 Git PR → 사람 리뷰 → ArgoCD 와 무관한 별도 저장소 |
| 실행 | 사람이 한 번에 | `--limit` 로 노드 묶음 단위, `upgrade_cluster.yml` 은 마이너 한 단계씩 |
| 모델 | Mac Ollama | 클러스터 내부 LLM (외부로 inventory·IP 가 나가지 않음) |

- inventory 와 group_vars 에는 노드 IP, 인증서 경로, 레지스트리 주소가 들어 있음 → 외부 LLM 에 넣지 않는 게 로컬 LLM Wiki 를 쓰는 가장 큰 이유임
- 업그레이드 전 질의 예 = "v2.31 → v2.32 에서 바뀐 기본값", "우리 group_vars 중 deprecated 된 변수" → 위키가 릴리즈 노트와 우리 설정을 같이 들고 있어야 답이 나옴

> 주의 : 위키 답을 그대로 운영 클러스터에 적용하지 말 것. LLM Wiki 는 "어디를 봐야 하는지" 를 빨리 알려 주는 도구이고, 최종 판단은 원문 문서와 스테이징 실행 결과로 해야 한다

### 9-6. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 가능 여부 | 가능. Mac 은 Ansible 실행, 노드는 Lima arm64 Ubuntu 24.04 VM 2대 |
| CNI | arm64 단독이면 Calico 또는 Cilium 만 |
| LLM 역할 | kubespray 문서 요약, 변수 선택과 근거를 JSON 으로 돌려줌 |
| 코드 역할 | 허용값·arm64 호환 검사, `zz-llm.yml` 저장, log 기록 |
| 사람 역할 | inventory 작성, `cluster.yml` 실행, 결과 확인 |
| 되먹임 | 실패 로그 fatal 줄 → raw/runs → ingest → 다음 설치 때 query |
| 사내 확장 | Nexus 오프라인 저장소, PR 리뷰, 노드 묶음 단위 실행, 내부 LLM |

**kubespray 설치는 kubespray 가 하고, LLM Wiki 는 문서를 읽고 변수를 고르고 실패를 기록하는 보조로 붙일 때 작은 로컬 모델로도 쓸모가 있다**


관련 글 : Local AI Models on a Mac - Ollama·Whisper·Streamlit 음성 챗봇 · Local AI Models on a Mac Ch15~18 - 문제 해결, RAG, Open WebUI, LangChain, 에이전트, 미세조정 · LLM Wiki · MacBook Pro M1 Pro 사양
