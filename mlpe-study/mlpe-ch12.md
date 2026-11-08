## Machine Learning Platform Engineering 스터디 - CH12

> **목표** : 기존 MLOps 플랫폼 위에 LLM 앱이 추가로 요구하는 것(벡터 DB, 프롬프트, 관측)을 이해하고, 사내 문서 RAG 챗봇 DakkaBot 을 검색 · 증강 · 생성 · UI · 관측 순서로 만드는 흐름 정리

- 원서 : Machine Learning Platform Engineering (Manning, 2026)
- 범위 : 12장 Designing LLM-powered systems (4부 Extending MLOps for LLMs 시작)
- 실습 : DataKrypt 사내 문서 챗봇 DakkaBot (LangChain + FAISS + Gemini + Chainlit + Langfuse)
- 버전 메모 : 책은 `text-embedding-004`, `gemini-2.5-flash`, LangChain 0.x import. 현재 `text-embedding-004` 는 2026-01-14 종료, LangChain 1.4 · langchain-google-genai 4.4 · Chainlit 2.12 · Langfuse SDK 5.2 (2026-11)

---

## 1. 개요

11장까지 = 전통 ML (표 · 이미지 · 추천). 12장부터 = **LLM 앱**.

핵심 메시지는 하나. **새로 짓는 게 아니라 확장하는 것**. K8s, CI/CD, MLflow, Prometheus 는 그대로 쓰고 LLM 전용 부품만 얹음.

<!-- diagram: mlpe-ch12-01-map.html -->

| 구분 | 그대로 쓰는 것 | 새로 붙는 것 |
|---|---|---|
| 인프라 | 컨테이너, LB, HPA, Ingress · 서비스 메시 | LLM 게이트웨이 (공급자 간 라우팅) |
| 배포 | CI/CD | 벡터 인덱스 · 프롬프트도 배포 대상 |
| 추적 | MLflow 실험 · 리니지 | Langfuse 트레이스 · 토큰 · 비용 |
| 모니터링 | Prometheus · Grafana | 응답 품질, 안전 위반 알림 |
| 보안 | 인증 · 인가 · 네트워크 정책 | 프롬프트 인젝션, 탈옥, 학습 데이터 노출 |
| 저장 | DB · 객체 스토리지 | 벡터 DB (백업 · 인덱스 버전 · 롤백) |

**같은 HPA 가 XGBoost 추천 Pod 와 LangChain RAG Pod 를 같이 늘린다. 플랫폼은 그대로고 워크로드 종류만 늘어난 것임.**

---

## 2. 12장 개념 정리 - Designing LLM-powered systems

### 2-1. LLM 앱이 다른 점

| 항목 | 전통 ML | LLM 앱 |
|---|---|---|
| 출력 | 같은 입력 = 같은 출력 | 같은 입력도 매번 다를 수 있음 (비결정성) |
| 테스트 | `assert predict(x) == y` | 의미 · 사실성 · 지침 준수 평가 |
| 흐름 | 입력 → 예측 1회 | 검색 · 조합 · 생성 · 검증 다단계 체인 |
| 성능 좌우 | 피처 엔지니어링 | 프롬프트 엔지니어링 |
| 비용 | 서버 시간 (예측 가능) | 토큰 수 (질문마다 100배 차이 가능) |

샘플링 파라미터.

| 파라미터 | 의미 | 예 |
|---|---|---|
| `temperature` | 무작위성. 0 = 가장 확률 높은 토큰만 | 0 사실 검색, 0.7 대화, 1.5 창작 · 횡설수설 위험 |
| `top_k` | 상위 K개 후보 안에서만 선택 | 1 = 결정적, 40 = 일반적 |
| `top_p` | 누적 확률 P 까지의 후보만 (nucleus) | 0.9 = 균형 |

- temperature 0 이어도 **완전한 결정성은 아님** (구현 세부 때문). 테스트엔 충분히 일관적, 재현은 보장 못 함

토큰 예산 = 설계 제약.

- 입력(컨텍스트 창) + 출력(`max_tokens`) 한도
- 예 : 청크 50개 × 500 토큰 = 25K + 시스템 프롬프트 2K + 질문 100 → 32K 창이면 답변에 5K 남음
- 입력 초과 = 요청 실패, 출력 한도 도달 = 문장 중간에 잘림

### 2-2. LLM 배포 메타데이터

모델 가중치 하나가 아니라 이 묶음 전체를 버전 관리해야 함.

| 분류 | 내용 |
|---|---|
| 프롬프트 | 시스템 프롬프트, 사용자 템플릿, few-shot 예시, CoT 템플릿 |
| 설정 | 토큰 한도, 샘플링 값, 모델 · 공급자 버전, 재시도 · 타임아웃 |
| 검색 | 벡터 인덱스 · 임베딩, 청크 전략, top-k · 유사도 임계값, 전처리 |
| 평가 | 테스트 프롬프트셋, 지표(관련성 · 충실성 · 유해성), 사람 피드백, A/B 결과 |

**시스템 프롬프트 한 줄 변경이 모델 교체만큼 동작을 바꿈.** `prompt_v2.3 + 모델 + temperature 0.7 + max_tokens 500` 조합 단위로 추적해야 하는 이유다.

### 2-3. 필수 도구

| 도구 | 역할 |
|---|---|
| 임베딩 모델 | 텍스트 → 의미 벡터. "API 인증" 과 "사용자 로그인 보안" 을 가깝게 |
| FAISS | 벡터 유사도 검색 라이브러리. 개발 · 중간 규모용. 운영 확장 시 Pinecone · Weaviate · Chroma 등 |
| LangChain | 로더 · 분할기 · 임베딩 · 벡터스토어 · LLM 을 같은 인터페이스로. 부품 교체가 쉬움 |
| LangGraph | 조건 분기 · 병렬 · 반복 루프가 필요한 에이전트형 흐름 |
| Langfuse | LLM 트레이스, 토큰 · 비용, 프롬프트 관리 (오픈소스) |
| Promptfoo | 프롬프트 인젝션 · 탈옥 자동 공격 테스트 (13장) |

<!-- diagram: mlpe-ch12-03-graph.html -->

- 직접 구현 RAG = 연결 관리 · 재시도 · 에러 처리 · 포맷 변환을 다 손으로
- LangChain = `retriever`, `llm` 만 꽂으면 체인 완성. 임베딩을 OpenAI → Gemini 로 바꿔도 나머지 코드 그대로
- 권장 순서 : **LangChain 으로 빠르게 실험 → 흐름이 복잡해지면 LangGraph → 안정되면 추상화를 유지할지 직접 구현할지 재평가**

### 2-4. 왜 RAG 인가

단일 LLM 호출의 한계.

- 컨텍스트 창 한계 : 사내 문서 수백만 토큰을 한 번에 못 넣음
- 긴 프롬프트일수록 추론 품질 저하
- 큰 프롬프트 하나가 틀리면 전체가 틀림 (오류 전파)
- 같은 큰 컨텍스트를 매번 처리 = 비용 낭비

RAG 가 주는 것.

| 이점 | 내용 |
|---|---|
| 학습 시점 이후 정보 | 재학습 없이 최신 문서 반영 |
| 선택적 검색 | 500쪽 핸드북 대신 관련 3구간만 |
| 실시간 데이터 | 재고 · 시세 등 바뀌는 데이터 |
| 사내 비공개 데이터 | 공개 LLM 이 모르는 문서 활용 |
| 비용 | 필요한 부분만 입력 |
| 근거 제시 | 출처 표시로 환각 감소 · 검증 가능 |

### 2-5. DakkaBot - 검색(Retrieval)

<!-- diagram: mlpe-ch12-02-rag.html -->

상황 : DataKrypt 가 50명 → 200명 이상 엔지니어 조직으로 커짐. 문서는 많은데 신규 입사자가 못 찾음 → 온보딩용 사내 문서 챗봇.

```python
class GeminiEmbeddings(Embeddings):                     # LangChain 인터페이스로 감싼 래퍼
    def __init__(self):
        self.client = genai.Client()

    def embed_documents(self, texts):
        return [self.client.models.embed_content(
                    model="text-embedding-004", contents=t,
                    config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),   # 저장용
                ).embeddings[0].values for t in texts]

    def embed_query(self, text):
        return self.client.models.embed_content(
            model="text-embedding-004", contents=text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),             # 검색용
        ).embeddings[0].values
```

- **문서용 · 질의용 task_type 을 다르게** → 책 기준 검색 정확도 10~20% 향상
- 래퍼로 감싸 두면 임베딩 공급자 교체가 쉬움

```python
docs = DirectoryLoader("./DATA", glob="**/*.md", loader_cls=TextLoader,
                       loader_kwargs={"encoding": "utf-8"}).load()
chunks = RecursiveCharacterTextSplitter(
    chunk_size=1000, chunk_overlap=200,                       # 경계 문맥 유지
    separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""],   # 제목 → 문단 → 문장 순
).split_documents(docs)
vs = FAISS.from_documents(chunks, GeminiEmbeddings())
vs.save_local("./DATA/faiss_index")                           # 매번 재임베딩 방지
vs = FAISS.load_local("./DATA/faiss_index", GeminiEmbeddings(),
                      allow_dangerous_deserialization=True)   # pickle 로드 → 보안 주의
```

검색 품질 요인.

| 요인 | 포인트 |
|---|---|
| 청크 크기 | 작으면 정확하지만 맥락 부족, 크면 맥락 많지만 잡음 |
| 임베딩 모델 | 학습 도메인이 내 문서와 가까울수록 유리 |
| 거리 척도 | L2 · 코사인 · 내적. 텍스트는 코사인이 무난 |
| k · 임계값 | 적으면 누락, 많으면 잡음 |

운영 팁 : 파일 해시 · 수정 시각으로 **바뀐 문서만 재색인**, 인덱스 버전 관리로 롤백, 대규모면 블루그린 인덱스 교체.

### 2-6. 증강 · 생성

```python
retriever = vector_store.as_retriever(search_kwargs={"k": 5})
docs = retriever.invoke(query)
context = "\n\n".join(f"**Document {i+1}:**\n{d.page_content}" for i, d in enumerate(docs))

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
prompt = f"""You are DakkaBot, DataKrypt's expert developer assistant.
**Documentation Context:** {context}
**User Question:** {query}
**Instructions:**
- Provide accurate, detailed answers based on the documentation
- If you're not sure about something, say so rather than guessing
- Stay focused on DataKrypt-specific information
**Answer:**"""
response = llm.invoke(prompt)
```

- 증강 = 검색 청크 + 질문을 하나의 프롬프트로. 번호 · 구획을 붙이면 모델이 구조를 잘 이해
- 시스템 프롬프트가 하는 일 : 출력 표준화, 할 수 있는 것 · 없는 것 명시, 시스템 지시 · 내부 맥락 유출 금지, 페르소나, 범위 밖 질문 처리

### 2-7. UI - Chainlit 과 스트리밍

- `DakkaBotCore` 클래스로 분리 → 같은 로직을 Chainlit · FastAPI · 배치 · 테스트에서 재사용 (관심사 분리)
- 지연 초기화(`initialize()` async) + `initialized` 플래그
- `process_query` 는 텍스트가 아니라 `{response, sources, doc_count, error}` 구조로 반환 → UI 가 출처 · 오류 표시

```python
async def process_query_stream(self, query):
    docs = self.retriever.invoke(query)
    yield {"type": "sources", "sources": sources, "doc_count": len(docs)}   # 출처 먼저
    async for chunk in self.llm.astream(prompt, config={"callbacks": [self.langfuse_handler]}):
        if chunk.content:
            yield {"type": "token", "content": chunk.content}                # 토큰 단위
    yield {"type": "done"}

@cl.on_message
async def main(message: cl.Message):
    query, ok = validate_user_inputs(message.content)       # LLM 호출 전 입력 검증
    if not ok: ...
    msg = cl.Message(content="", author="DakkaBot")
    async for c in dakka_bot.process_query_stream(query):
        if c["type"] == "token":
            await msg.stream_token(c["content"])
        elif c["type"] == "done":
            await msg.send()
```

- 출처 → "검색 중…" 상태 → 토큰 스트리밍 → 완료 신호 순서 = 체감 속도 향상
- 테스트 프레임워크용 동기 래퍼(`asyncio.run`) + 싱글턴으로 재초기화 방지
- `chainlit run` → `localhost:8000`

### 2-8. LLM 관측 - Langfuse

<!-- diagram: mlpe-ch12-04-trace.html -->

- 전통 관측 = "고장 났다" 를 알려줌. LLM 관측 = "**왜 답이 나쁜지**" 를 보여줌 (어떤 문서를 가져왔고, 어떤 프롬프트가 갔고, 무엇을 생성했나)
- 설치 : `git clone langfuse` → `docker compose up` → `localhost:3000` → 조직 · 프로젝트 · API 키

```python
from langfuse.langchain import CallbackHandler          # 현재 SDK 경로

self.langfuse_handler = CallbackHandler()               # LANGFUSE_PUBLIC_KEY · SECRET_KEY · HOST 환경변수
response = self.llm.invoke(prompt, config={
    "callbacks": [self.langfuse_handler],
    "metadata": {"doc_count": len(docs), "context_length": len(context)},   # 비즈니스 맥락
})
```

대시보드에서 보는 것.

| 영역 | 내용 |
|---|---|
| 시간별 트레이스 | 업무 시간 피크 → 실제 사용 패턴 |
| 모델 사용량 | 모델별 비용 (책 : 수백 건에 약 $0.62) |
| 지연 퍼센타일 | 전체 트레이스 · 생성 · 스팬별 |
| 트레이스 상세 | 1건 = 지연 11.48초, 입력 1,408 → 출력 2,359 토큰, $0.00632 |

정확도 · 지연만으로 부족한 이유.

- 정답이 이분법이 아님. 사실은 맞지만 의도를 놓친 답, 비슷한 질문에 품질이 들쭉날쭉한 답
- 스트리밍에선 **첫 토큰까지 시간(TTFT)** 이 체감 속도. 출처를 먼저 보여준 3초 응답이 아무 피드백 없는 2초 응답보다 빠르게 느껴짐
- 토큰 지표 : 입출력 비율, 컨텍스트 활용도, 질문 유형별 비용(트러블슈팅이 단순 질문의 10배), 장황한 생성 탐지

### 2-9. 책 vs 현재

| 항목 | 책 | 현재 |
|---|---|---|
| 임베딩 모델 | `text-embedding-004` | **2026-01-14 종료**. `gemini-embedding-001`(2028-05 종료 예정) 또는 `gemini-embedding-2`. 차원이 달라 인덱스 전체 재생성 필요 |
| 생성 모델 | `gemini-2.5-flash` | 계속 제공. 최신은 `gemini-3.8-flash` 등 3.x 계열 |
| LangChain import | `langchain.text_splitter`, `langchain.schema`, `langchain.chains.RetrievalQA` | 1.x 는 `langchain_text_splitters`, `langchain_core.documents`, `RetrievalQA` 는 `langchain-classic` 로 이동. LCEL · LangGraph 권장 |
| Gemini 옵션 | `convert_system_message_to_human=True` | 최신 langchain-google-genai 는 시스템 메시지 직접 지원, 옵션 불필요 |
| Langfuse 콜백 | `from langchain.callbacks import LangfuseCallbackHandler` | `from langfuse.langchain import CallbackHandler` |
| Langfuse 자체 호스팅 | `docker compose up` | v3 이후 구성 = 웹 · 워커 + Postgres + **ClickHouse + Redis + S3** |

---

## 3. 실무에서 확인

- **폐쇄망 LLM** : 책은 Gemini API(외부) 전제. 폐쇄망에선 외부 API 불가 → B300 위 vLLM · SGLang 으로 오픈 웨이트 모델 서빙, 임베딩도 사내 모델(bge-m3 · e5 계열) 로. LangChain 은 OpenAI 호환 엔드포인트로 그대로 연결
- **벡터 DB 선택** : FAISS 는 파일 기반 라이브러리 → 다중 Pod 공유 · 실시간 갱신이 어려움. 운영은 pgvector · Milvus · Qdrant 같은 서버형, 또는 이미 있는 검색 엔진(OpenSearch 벡터) 재사용 검토
- **pickle 인덱스** : `allow_dangerous_deserialization=True` = 인덱스 파일이 바뀌면 임의 코드 실행 가능. 인덱스 파일은 서명 · 해시 검증, 쓰기 권한 최소화
- **문서 권한** : 1,000명 사내 RAG 에서 가장 큰 사고는 "볼 권한 없는 문서가 답에 섞이는 것". 청크 메타데이터에 ACL · 부서 태그를 넣고 검색 시 사용자 권한으로 필터 (Keycloak 그룹 연동)
- **재색인 파이프라인** : 문서 수집 → 분할 → 임베딩을 Airflow · KFP 배치로. 변경분만 처리, 인덱스 버전 태그를 배포 메타데이터로 관리
- **Langfuse 운영** : ClickHouse · Redis · S3 까지 필요 → S3 는 AIStor 버킷, ClickHouse 는 디스크 · 보관 기간 설계. 트레이스에 질문 원문 · 문서 본문이 남으므로 개인정보 · 기밀 마스킹 정책 필요
- **Prometheus 연계** : Langfuse 는 LLM 내부, Prometheus 는 Pod 지연 · 오류율. 둘 다 필요함. 토큰 · 비용 수치는 Prometheus 메트릭으로도 내보내 기존 알림 체계에 태우기
- **스트리밍 경로** : Ingress · 프록시 버퍼링이 켜져 있으면 토큰 스트리밍이 한꺼번에 도착함. NGINX `proxy_buffering off`, WebSocket · SSE 타임아웃 확인

> 주의 : 책 코드를 그대로 돌리면 임베딩 호출에서 모델 없음 오류가 남(`text-embedding-004` 종료). 모델명만 바꾸고 기존 FAISS 인덱스를 그대로 로드하면 차원 불일치로 검색이 깨지므로 인덱스부터 다시 만들 것.

---

## 4. 용어 정리

- **LLMOps** : LLM 앱 운영 관행. MLOps 의 확장
- **RAG(Retrieval-Augmented Generation)** : 검색한 문서를 프롬프트에 넣어 생성하는 방식
- **임베딩(embedding)** : 텍스트를 의미가 반영된 숫자 벡터로 바꾼 것
- **벡터 DB · FAISS** : 벡터 유사도 검색 저장소 · Meta 의 유사도 검색 라이브러리
- **청크(chunk) · 겹침(overlap)** : 문서를 나눈 조각 · 조각 경계에서 겹치는 부분
- **컨텍스트 창(context window)** : 모델이 한 번에 처리하는 최대 토큰 수
- **temperature · top-k · top-p** : 생성 무작위성 조절 파라미터
- **환각(hallucination)** : 그럴듯하지만 사실이 아닌 생성
- **LangChain · LangGraph** : LLM 앱 부품 연결 프레임워크 · 그래프형 흐름 확장
- **Chainlit** : 파이썬만으로 채팅 UI 를 만드는 프레임워크
- **Langfuse** : 오픈소스 LLM 관측 · 프롬프트 관리 플랫폼
- **TTFT(Time To First Token)** : 요청 후 첫 토큰이 나오기까지 시간
- **프롬프트 인젝션** : 입력에 지시문을 숨겨 시스템 지시를 무력화하는 공격

---

## 5. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 관점 | LLMOps = MLOps 의 확장. 플랫폼은 그대로, 부품만 추가 |
| 다른 점 | 비결정성, 다단계 체인, 프롬프트 = 코드, 토큰 과금 |
| 버전 대상 | 프롬프트 · 설정 · 인덱스 · 평가셋 전체 |
| 검색 | 문서 로드 → 1000자 청크 → 문서 · 질의 임베딩 분리 → FAISS 저장 |
| 증강 · 생성 | top-k 5 컨텍스트 + 시스템 프롬프트, temperature 0 |
| UI | DakkaBotCore 분리, 출처 먼저 · 토큰 스트리밍 |
| 관측 | Langfuse 콜백 하나로 트레이스 · 토큰 · 비용 · 지연 |
| 현재 기준 보완 | 임베딩 모델 종료, LangChain 1.x import, Langfuse v3 구성 |
| 실무 | 폐쇄망 자체 서빙, 문서 ACL 필터, 서버형 벡터 DB, 트레이스 마스킹 |

**RAG 의 힘은 분리에 있음. 문서가 바뀌어도 모델은 그대로 두고 인덱스만 갈아 끼우면 된다. 대신 그 사이 단계가 늘어난 만큼 추적 도구가 필수가 됨.**

다음 글 : 13장 Production LLM system design - 프롬프트 관리, LLM 평가 · 레드팀, 가드레일, 비용 최적화
