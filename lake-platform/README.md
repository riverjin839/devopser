## Lake 분석 플랫폼 - B300 + K8s 에서 데이터 유형별 분석 흐름

> **목표** : 정형·텍스트·이미지·영상 분석가가 Lake 에서 실제로 어떻게 일하는지, 그걸 받치는 MLOps·LLMOps 플랫폼 구성을 한 장으로 정리

- 기준 환경 : Lake K8s (Compute 노드) + B300 GPU 노드, AIStor (오브젝트), Isilon (NAS), StarRocks, Spark, Airflow, CNPG, Keycloak, ArgoCD, Nexus (HF 프록시)
- 바탕 글 : 책 1~3장, Ray, Kubeflow, Kubeflow + MLflow, MLflow, 3개 비교
- 성격 : 운영 중인 스택 + 앞서 정리한 도구를 합친 **설계안**. 확정 구성 아님

---

## 1. 개요

출발점

- 분석가마다 다루는 데이터가 다름 : 정형(테이블), 비정형 텍스트(문서), 이미지, 동영상
- 분석 방법도 다름 : 정형 = 전통 ML, 텍스트 = LLM·RAG, 이미지 = 사전학습 모델 파인튜닝, 영상 = VLM 배치 추론
- 하지만 **저장소, GPU, 기록, 배포 경로는 공유**해야 함 → 그게 플랫폼 역할

<!-- diagram: mlpe-lake-01-overview.html -->

| 층 | 역할 | Lake 구성 |
|---|---|---|
| 저장 | 원본 보관 | StarRocks(정형), AIStor(객체), Isilon(공유 파일) |
| 처리 | 정제·피처·임베딩 | Spark(정형 ETL), Ray Data(GPU 전처리) |
| 학습 | 모델 만들기·고치기 | Ray Train, Kubeflow Trainer on B300 |
| 기록 | 실험·모델·trace | MLflow (+ mlflow-integration) |
| 서빙 | 예측·생성 | vLLM, KServe, Ray Serve |
| 오케스트레이션 | 순서·스케줄 | Airflow (기존), 필요시 KFP |
| 공통 | 인증·배포·이미지 | Keycloak, ArgoCD, Nexus |

**데이터는 달라도 길은 하나 : 저장 → 처리 → 학습 → 기록 → 서빙.**

---

## 2. 분석 트렌드 (2026 기준)

| 데이터 | 예전 | 지금 주류 | 바뀐 이유 |
|---|---|---|---|
| 정형 | SQL + 통계, 사이킷런 | **여전히 GBDT(XGBoost·LightGBM) 와 SQL**. LLM 은 text-to-SQL, 해석 보조 | 테이블은 트리 모델이 아직 최강. GPU 학습으로 속도만 빨라짐 |
| 텍스트 | 키워드 검색, TF-IDF 분류 | 임베딩 + RAG, LLM 으로 분류·요약·추출 (학습 없이) | 사전학습 LLM 이 범용 언어 이해 제공 |
| 이미지 | CNN 직접 설계·학습 | 사전학습 비전 모델(YOLO, ViT) 파인튜닝, VLM 으로 라벨링 보조 | 소량 라벨로도 성능 확보 |
| 영상 | 프레임 단위 규칙·CNN | VLM 배치 추론으로 장면 설명 → 텍스트처럼 검색 | 영상을 "검색 가능한 텍스트"로 바꾸는 게 핵심 |

공통 흐름

- **만들기 → 가져와서 맞추기** : 정형 빼고는 사전학습 모델이 출발점
- **학습보다 추론 비중 증가** : GPU 를 오래 쓰는 곳이 학습에서 배치 추론·서빙으로 이동
- **평가 중심** : 숫자 지표(Recall, AUC) + LLM judge. 평가셋 관리가 곧 경쟁력
- **멀티모달 통합** : 이미지·영상도 결국 텍스트·벡터로 바꿔 한 검색 체계에 넣음
- 단, 정형 데이터 분석은 LLM 으로 대체 안 됨. 착각 금지

---

## 3. 데이터 유형별 분석 시나리오

### 3-1. 정형 - 설비·공정 테이블로 불량 예측

<!-- diagram: mlpe-lake-02-tabular.html -->

분석가 업무

- StarRocks 에서 설비 로그·공정 파라미터 조회 → 피처 생성
- XGBoost GPU 학습 → 혼동 행렬, Recall 로 평가 (불량 놓침 = FN 이 비쌈)
- 기준 통과 모델 `@champion` → Airflow 가 매일 배치 예측 → 결과를 StarRocks 테이블로 → 대시보드

```python
import pandas as pd, sqlalchemy, xgboost as xgb, mlflow
from sklearn.model_selection import train_test_split
from sklearn.metrics import recall_score, roc_auc_score

eng = sqlalchemy.create_engine("mysql+pymysql://analyst@starrocks-fe.sr.svc:9030/mes")
df = pd.read_sql("SELECT * FROM lot_features WHERE dt >= '2026-09-01'", eng)
X, y = df.drop(columns=["is_defect"]), df["is_defect"]
X_tr, X_te, y_tr, y_te = train_test_split(X, y, stratify=y, test_size=0.2)

mlflow.set_tracking_uri("http://mlflow.mlflow.svc:5000")
mlflow.set_experiment("defect-predict")
with mlflow.start_run():
    clf = xgb.XGBClassifier(tree_method="hist", device="cuda", n_estimators=500,
                            scale_pos_weight=(y_tr == 0).sum() / (y_tr == 1).sum())
    clf.fit(X_tr, y_tr)
    prob = clf.predict_proba(X_te)[:, 1]
    mlflow.log_metrics({"auc": roc_auc_score(y_te, prob),
                        "recall@0.3": recall_score(y_te, prob > 0.3)})   # 임계값 낮춰 FN 줄임
    mlflow.xgboost.log_model(clf, name="model", registered_model_name="defect-predict")
```

- 포인트 : 불량은 드문 사건 → 정확도 대신 Recall·AUC, `scale_pos_weight` 로 불균형 보정
- GPU 는 학습 속도용. B300 1장이면 충분. 대부분 시간은 피처 만드는 데 씀

### 3-2. 비정형 텍스트 - 사내 문서 RAG

<!-- diagram: mlpe-lake-03-text.html -->

분석가 업무

- 보고서·매뉴얼·이슈 기록을 청킹 → 임베딩 → 벡터 DB 적재
- 질문 들어오면 유사 문서 검색 → 프롬프트에 붙여 사내 LLM(vLLM) 호출
- 답변 품질은 MLflow tracing + LLM judge 로 평가

```python
# 1) 적재 : Ray Data 로 문서 수천만 건 GPU 임베딩
import ray
from sentence_transformers import SentenceTransformer

class Embed:
    def __init__(self):
        self.m = SentenceTransformer("/models/bge-m3", device="cuda")   # Nexus 경유 반입 모델
    def __call__(self, batch):
        batch["vec"] = self.m.encode(list(batch["chunk"]), batch_size=256)
        return batch

ds = (ray.data.read_parquet("s3://docs/chunks/")          # AIStor, 사전 청킹 결과
         .map_batches(Embed, concurrency=8, num_gpus=1, batch_size=1024))
ds.write_parquet("s3://docs/embeddings/")                  # → pgvector 로 적재
```

```python
# 2) 질의 : 검색 + 사내 LLM (vLLM OpenAI 호환 API)
import mlflow, psycopg
from openai import OpenAI
from pgvector.psycopg import register_vector

from sentence_transformers import SentenceTransformer

mlflow.openai.autolog()                                     # trace 자동 기록
embedder = SentenceTransformer("/models/bge-m3", device="cuda")
llm = OpenAI(base_url="http://vllm.llm.svc:8000/v1", api_key="internal")

@mlflow.trace
def ask(q: str) -> str:
    qv = embedder.encode(q)
    with psycopg.connect("postgresql://rag@cnpg-rw.rag.svc/rag") as c:
        register_vector(c)
        ctx = [r[0] for r in c.execute(
            "SELECT chunk FROM docs ORDER BY vec <=> %s LIMIT 5", (qv,))]
    msg = f"아래 문서만 근거로 답해.\n{chr(10).join(ctx)}\n\n질문: {q}"
    return llm.chat.completions.create(model="qwen", messages=[
        {"role": "user", "content": msg}]).choices[0].message.content
```

- 포인트 : 학습 없음. 품질은 청킹·검색·프롬프트·평가셋에서 결정
- 벡터 DB 는 운영 중인 CNPG 에 pgvector 확장으로 시작. 수억 건 넘으면 전용 벡터 DB 검토

### 3-3. 이미지 - 검사 이미지 결함 검출

<!-- diagram: mlpe-lake-04-image.html -->

분석가 업무

- AIStor 의 검사 이미지 샘플링 → VLM 으로 사전 라벨 → 사람이 검수 (라벨링 시간 단축)
- 사전학습 YOLO 를 결함 데이터로 파인튜닝 (B300 멀티 GPU)
- 혼동 행렬·Recall 기준 통과 → MLflow 등록 → KServe 실시간 판정

```python
import mlflow
from ultralytics import YOLO

mlflow.set_experiment("wafer-defect")
with mlflow.start_run():
    model = YOLO("/models/yolo11s.pt")                     # 사전학습 가중치에서 출발
    model.train(data="/data/defect.yaml", epochs=80, imgsz=1024,
                batch=64, device=[0, 1, 2, 3])            # B300 4장
    m = model.val()
    mlflow.log_metrics({"precision": m.box.mp, "recall": m.box.mr, "map50": m.box.map50})
    mlflow.log_artifact(str(m.save_dir / "confusion_matrix.png"))
    mlflow.log_artifacts(str(model.trainer.save_dir / "weights"), "weights")
```

- 포인트 : 처음부터 설계 안 함. 라벨 품질과 평가셋(결함 유형별)이 성패 결정
- 결함 놓침(FN) 비용이 큼 → 선별 단계 임계값 낮추고, 사람 재검으로 FP 흡수

### 3-4. 동영상 - 장면 검색·안전 알람

<!-- diagram: mlpe-lake-05-video.html -->

분석가 업무

- 영상 → 청크 분할 → GPU 디코딩으로 초당 1프레임 샘플
- VLM 배치 추론으로 장면 설명·이상 태그 생성 ("보호구 미착용", "연기")
- 설명 텍스트를 임베딩 → "작업자 미착용 장면" 같은 자연어 검색, 태그는 알람으로

```python
# 개념 코드 : Ray Data + vLLM 배치 추론 (ray.data.llm 인자는 버전별로 다름)
import ray
from ray.data.llm import vLLMEngineProcessorConfig, build_llm_processor

frames = (ray.data.read_binary_files("s3://cctv/2026-10-24/")
             .flat_map(extract_frames_1fps))                # decord·PyNvVideoCodec 등으로 디코딩

cfg = vLLMEngineProcessorConfig(model_source="/models/qwen-vl",
                                engine_kwargs={"max_model_len": 8192},
                                concurrency=8, batch_size=32)
vlm = build_llm_processor(
    cfg,
    preprocess=lambda r: {"messages": [{"role": "user", "content": [
        {"type": "image", "image": r["frame"]},
        {"type": "text", "text": "장면을 한 문장으로. 보호구 미착용·연기·쓰러짐 있으면 태그."}]}],
        "sampling_params": {"max_tokens": 128}},
    postprocess=lambda r: {"cam": r["cam"], "ts": r["ts"], "desc": r["generated_text"]})

vlm(frames).write_parquet("s3://cctv-meta/2026-10-24/")      # → StarRocks 적재·임베딩
```

- 포인트 : 영상 분석의 병목은 모델이 아니라 **디코딩·I/O**. AIStor → GPU 노드 대역폭 확인 필수
- 영상을 텍스트로 바꾸는 순간 3-2 RAG 와 같은 검색 체계 재사용 가능

---

## 4. MLOps · LLMOps 를 Lake 에 매핑

### 4-1. 분석가 공통 작업 흐름

<!-- diagram: mlpe-lake-06-analyst.html -->

1. Keycloak 로그인 → 그룹 기준으로 내 네임스페이스 권한
2. Jupyter 에서 탐색·소규모 실험 → MLflow 기록
3. 규모 커지면 RayJob 제출 → Kueue 가 B300 자원 배분
4. 최적 모델 → 레지스트리 alias 승격
5. ArgoCD 로 서빙 배포 (매니페스트 Git 관리)
6. 운영 모니터링 → 임계치 넘으면 Airflow 가 재학습 트리거

### 4-2. MLOps vs LLMOps

| 항목 | MLOps (정형·이미지) | LLMOps (텍스트·영상) |
|---|---|---|
| 핵심 산출물 | 학습한 모델 가중치 | 프롬프트 + 검색 체계 + (선택) 파인튜닝 |
| 평가 | AUC, Recall, 혼동 행렬 | 정답률, 근거 일치, LLM judge, 사람 평가 |
| 버전 관리 | 모델 버전, 데이터 버전 | 프롬프트 버전, 인덱스 버전, 모델 버전 |
| 모니터링 | 데이터·모델 드리프트 | trace, 답변 품질, 토큰·지연·비용 |
| GPU 사용 | 학습 집중, 서빙 가벼움 | 서빙·배치 추론 상시 |
| 도구 | Ray Train, XGBoost, MLflow, KServe | vLLM, Ray Data LLM, pgvector, MLflow Tracing·Prompt Registry |

### 4-3. 기존 스택 vs 추가 필요

| 영역 | 이미 운영 중 | 추가 후보 | 이유 |
|---|---|---|---|
| 데이터 | StarRocks, AIStor, Isilon, Spark | Ray Data | GPU 전처리·임베딩·배치 추론 |
| 오케스트레이션 | Airflow | (선택) KFP | 리니지 필요할 때만 |
| GPU 실행 | - | KubeRay, Kueue, GPU Operator | B300 공유·갱 스케줄링 |
| 기록·레지스트리 | - | MLflow + mlflow-integration | ns = 워크스페이스, Keycloak 연동 |
| 서빙 | - | vLLM, KServe | LLM·모델 API |
| 벡터 검색 | CNPG | pgvector 확장 | 기존 PG 운영 역량 재사용 |
| 인증·배포 | Keycloak, ArgoCD, Jenkins | - | 그대로 사용 |
| 모델 반입 | Nexus (HF 프록시) | 모델 승인 절차 | 라이선스·보안 검증 |

**새로 깔 건 GPU 실행층(KubeRay·Kueue), 기록층(MLflow), 서빙층(vLLM·KServe) 3개뿐. 나머지는 이미 있음.**

---

## 5. B300 GPU 운영 전략

| 용도 | 특성 | 배치 방법 |
|---|---|---|
| 대규모 학습·파인튜닝 | 여러 장·여러 노드 동시 필요 | RayJob/TrainJob + Kueue 갱 스케줄링. 노드 간 통신은 B300 패브릭 안에서 |
| 배치 추론 (영상·임베딩) | 처리량 우선, 중단 가능 | Ray Data, 낮은 우선순위 큐. 빈 GPU 흡수 |
| 상시 서빙 (LLM) | 지연 우선, 항상 켜짐 | vLLM 전용 노드 그룹 고정 |
| 분석가 노트북 | 짧고 간헐적 | MIG·time-slicing 분할 검토. 풀 GPU 장기 점유 금지 |

- Kueue : 팀별 ClusterQueue 에 GPU 쿼터, 남는 자원은 빌려쓰기(borrowing)
- 데이터 위치 : 학습 데이터는 AIStor → GPU 노드로 Ethernet 경유 → 대용량이면 로컬 NVMe 캐시 단계 두기
- 노드 라벨·taint 로 B300 노드에는 GPU 요청 Pod 만

---

## 6. 실무에서 확인 - 도입 순서

| 단계 | 할 일 | 효과 |
|---|---|---|
| 1 | MLflow (+ Keycloak 헤더 SAR 모드) + Jupyter GPU 프로파일 | 실험 기록 통일. 바로 체감 |
| 2 | GPU Operator + KubeRay + Kueue on B300 | GPU 공유 질서. 대규모 학습·배치 추론 가능 |
| 3 | vLLM 서빙 + pgvector RAG + MLflow Tracing | 사내 LLM 활용, 텍스트·영상 분석 시작 |
| 4 | Airflow ↔ RayJob 연동, 재학습 자동화, KServe | 운영 MLOps 완성 |
| 5 | (선택) KFP·Kubeflow Hub | 리니지·감사 요구 생길 때 |

- **모델 반입** : dmz-nexus HF 프록시로 받되, 라이선스 확인 + safetensors 만 허용 + `revision` 고정. 반입 모델 목록은 레지스트리에 기록
- **데이터 권한** : Keycloak 그룹 → ns RBAC → AIStor 버킷 정책(STS) 한 줄로 이어지게 설계. 분석가가 남의 원본 못 보게
- **네트워크** : B300 노드 간은 학습 통신(IB/RoCE), Lake 와는 Ethernet. 학습 중 AIStor 대량 읽기가 Lake 트래픽과 겹치지 않게 캐싱·시간대 분리
- **관측** : GPU 사용률(DCGM) + Ray 대시보드 + MLflow trace 를 기존 Prometheus/Grafana 에 모음

> 주의 : 처음부터 전부 깔지 말 것. 1단계 MLflow 만으로도 "누가 어떤 데이터로 어떤 모델을 만들었는지"가 보이기 시작함.

> 주의 : 정형 분석가에게 LLM 을 강요하지 말 것. 데이터 유형별로 맞는 도구가 다름.

---

## 7. 용어 정리

- **GBDT(Gradient Boosted Decision Trees)** : XGBoost·LightGBM 같은 트리 앙상블. 테이블 데이터 최강
- **RAG** : 검색한 문서를 프롬프트에 붙여 LLM 답변 근거로 쓰는 방식
- **임베딩(embedding)** : 텍스트·이미지를 의미 비교 가능한 숫자 벡터로 바꾼 것
- **pgvector** : PostgreSQL 벡터 검색 확장
- **VLM(Vision Language Model)** : 이미지를 보고 텍스트로 답하는 멀티모달 LLM
- **vLLM** : 고처리량 LLM 추론 서버. OpenAI 호환 API
- **배치 추론(batch inference)** : 대량 데이터를 모아 한꺼번에 예측
- **Kueue** : K8s 잡 큐잉·쿼터·갱 스케줄링
- **MIG(Multi-Instance GPU)** : GPU 1장을 여러 독립 인스턴스로 분할
- **LLM judge** : LLM 으로 다른 LLM 답변을 채점하는 평가 방식

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 출발점 | 데이터 유형별 분석가, 공유 저장소·GPU·플랫폼 |
| 정형 | StarRocks → 피처 → XGBoost GPU → Recall 평가 → Airflow 배치 |
| 텍스트 | Ray Data 임베딩 → pgvector → vLLM RAG → Tracing 평가 |
| 이미지 | VLM 사전 라벨 → YOLO 파인튜닝 → 혼동 행렬 → KServe |
| 영상 | GPU 디코딩 → VLM 배치 추론 → 메타·임베딩 → 자연어 검색 |
| 트렌드 | 만들기 → 가져와 맞추기, 학습 → 추론, 평가 중심. 정형은 예외 |
| 플랫폼 | 기존(StarRocks·AIStor·Airflow·Keycloak·ArgoCD) + 신규(KubeRay·Kueue·MLflow·vLLM) |
| B300 | 학습·배치·서빙·노트북 용도별 큐와 노드 그룹 분리 |
| 도입 | MLflow → KubeRay·Kueue → vLLM·RAG → 재학습 자동화 |

**분석가는 데이터마다 다르게 분석하지만, 플랫폼은 저장 → 처리 → 학습 → 기록 → 서빙 한 길로 묶어줘야 함. Lake 는 저장·처리가 이미 있으니 GPU 실행·기록·서빙 3개만 채우면 됨.**

관련 글 : Ray, Kubeflow, Kubeflow + MLflow 통합, MLflow, Ray · Kubeflow · MLflow 비교
