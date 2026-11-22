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

**작은 로컬 모델에게 위키 전체를 맡기지 않고, LLM 은 내용만 JSON 으로 내고 파일·링크·index·log 는 코드가 관리하는 게 Mac 버전의 핵심임**

---

## 2. 개념 정리

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

### 2-3. 왜 Mac 에선 "LLM 은 내용, 코드는 관리" 인가

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

### 5-3. 핵심 코드 - 구조화 출력으로 내용만 받기

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
| Mac 버전 원칙 | LLM 은 JSON 내용만, 파일·링크·index·log 는 코드 |
| 모델 | gemma3:4b 기본, 8B Q4 상한, Modelfile 로 num_ctx·temperature 고정 |
| 검색 확장 | `index.md`, qmd, ChromaDB 순 |
| 입력 확장 | 음성 메모 → Whisper 텍스트를 raw/voice 로 |
| 사내 확장 | AIStor 원본, 클러스터 Ollama, Git 위키, lint CronJob, 권한 단위 분리 |

**작은 로컬 모델로도 LLM Wiki 는 돌아가고, 조건은 모델에게 위키 관리를 맡기지 않고 내용만 받는 구조로 짜는 것이다**

관련 글 : Local AI Models on a Mac - Ollama·Whisper·Streamlit 음성 챗봇 · Local AI Models on a Mac Ch15~18 - 문제 해결, RAG, Open WebUI, LangChain, 에이전트, 미세조정 · LLM Wiki · MacBook Pro M1 Pro 사양
