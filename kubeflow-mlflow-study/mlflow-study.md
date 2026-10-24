## MLflow 스터디 - 실험 추적부터 GenAI 운영까지

> **목표** : MLflow 3 구조, 실험 추적·모델 레지스트리·GenAI 기능, 운영 배치 방법 이해

- 출처 : github.com/mlflow/mlflow, mlflow.org 문서
- 기준 버전 : MLflow 3.17.2 (2026-10 기준)
- 라이선스 : Apache 2.0. LF AI & Data 프로젝트

---

## 1. 개요

MLflow = ML 모델과 LLM 앱의 **기록·관리 플랫폼**.

- 학습 코드가 남기는 파라미터, 지표, 모델 파일을 한 곳에 모음
- 모델 버전 관리 + 배포용 별칭(alias) 관리
- MLflow 3 부터 무게중심이 GenAI 로 이동 : 트레이싱, 평가, 프롬프트 관리, AI Gateway

계산은 안 함. 학습·서빙 엔진은 따로 (Ray, Kubeflow Trainer, KServe 등).

**MLflow 는 실행 엔진이 아니라, 실행 결과를 남기고 고르는 장부임.**

---

## 2. MLflow 개념 정리

### 2-1. 서버 구조

<!-- diagram: mlpe-ml-01-arch.html -->

| 구성 | 저장 내용 | 운영 선택 |
|---|---|---|
| Tracking Server | REST API + UI | Deployment, 무상태 |
| Backend Store | 실험·run·param·metric·태그·레지스트리 메타데이터 | PostgreSQL / MySQL |
| Artifact Store | 모델 파일, 플롯, 데이터셋 사본 | MinIO / S3 / NFS |
| Model Registry | 등록 모델, 버전, alias | Backend Store 안에 같이 저장 |
| AI Gateway | LLM 공급자 키·라우팅·예산 | 서버 내장 |

- 아티팩트 프록시(`--serve-artifacts`) : 클라이언트가 S3 키 없이 서버 경유로 업로드
- 서버는 무상태 → DB + 오브젝트 스토리지만 있으면 레플리카 증설 가능

### 2-2. 실험 추적 (Tracking)

- **Experiment** : run 묶음. 보통 문제 하나 = 실험 하나
- **Run** : 학습 1회. param, metric(스텝별), tag, 아티팩트 기록
- **autolog** : `mlflow.<프레임워크>.autolog()` 한 줄로 param·metric·모델 자동 기록
- **Dataset 추적** : 어떤 데이터 버전으로 학습했는지 run 에 연결

### 2-3. 모델 수명주기

<!-- diagram: mlpe-ml-02-lifecycle.html -->

- **Logged Model** (MLflow 3 신규) : run 과 별개 1급 객체. 체크포인트마다 모델 남기고 지표 연결
- **flavor** : sklearn, pytorch, transformers 등 프레임워크별 저장 형식. 공통 인터페이스 = `pyfunc`
- **signature** : 입력·출력 스키마. 서빙 때 입력 검증
- **Registered Model** : 이름 하나에 버전 v1, v2, v3 … 누적
- **Alias** : `@champion`, `@challenger` 같은 이름표. 서빙은 alias 로 참조

> 주의 : 예전 Stage(Staging/Production) 방식은 폐기 수순. alias + 태그 방식으로 갈아탈 것.

배포 경로

- `mlflow models serve` : 로컬 REST 서버
- `mlflow models build-docker` : 서빙 이미지 생성
- KServe : MLflow 형식 모델 직접 로드 지원
- Ray Serve : 코드에서 `mlflow.pyfunc.load_model()` 로 로드

### 2-4. GenAI 기능

<!-- diagram: mlpe-ml-03-genai.html -->

| 기능 | 하는 일 |
|---|---|
| Tracing | LLM 호출·툴 호출·검색 단계를 span 으로 기록. OpenTelemetry 호환. 60개 이상 프레임워크 autolog |
| Evaluation | scorer·LLM judge 로 답변 품질 채점. 운영 trace 를 평가셋으로 재사용 |
| Prompt Registry | 프롬프트 버전 관리 + alias. 코드 배포 없이 프롬프트 교체 |
| Prompt Optimization | 평가 지표 기준 프롬프트 자동 개선 |
| AI Gateway | LLM 공급자 키 중앙 관리, 라우팅, 가드레일, 예산 제한 |
| Workspaces | 서버 하나를 팀별 격리 공간으로 분리 (3.x 신규) |

전통 ML = 숫자 지표 비교, GenAI = trace 보고 품질 채점.

---

## 3. 사용법 예시

### 3-1. 서버 띄우기

```bash
pip install "mlflow==3.17.*" psycopg2-binary boto3

export MLFLOW_S3_ENDPOINT_URL=http://minio.minio.svc:9000
export AWS_ACCESS_KEY_ID=*** AWS_SECRET_ACCESS_KEY=***

mlflow server \
  --host 0.0.0.0 --port 5000 \
  --backend-store-uri postgresql://mlflow:***@pg:5432/mlflow \
  --artifacts-destination s3://mlflow-artifacts \
  --serve-artifacts
```

### 3-2. 학습 기록 + 등록

```python
import mlflow
from mlflow import MlflowClient
from sklearn.ensemble import RandomForestClassifier

mlflow.set_tracking_uri("http://mlflow.mlflow.svc:5000")
mlflow.set_experiment("fraud-detect")
mlflow.sklearn.autolog()                      # param·metric·모델 자동 기록

with mlflow.start_run(run_name="rf-depth8") as run:
    clf = RandomForestClassifier(max_depth=8).fit(X_train, y_train)
    mlflow.log_metric("val_auc", auc(clf, X_val, y_val))
    mlflow.sklearn.log_model(clf, name="model",
                             registered_model_name="fraud-detect")

client = MlflowClient()
client.set_registered_model_alias("fraud-detect", "champion", version=3)
```

### 3-3. 서빙에서 불러오기

```python
model = mlflow.pyfunc.load_model("models:/fraud-detect@champion")
pred = model.predict(df)
```

```bash
mlflow models serve -m "models:/fraud-detect@champion" -p 8080 --env-manager local
```

### 3-4. LLM 앱 트레이싱 + 평가

```python
import mlflow
from mlflow.genai.scorers import Correctness, RelevanceToQuery

mlflow.openai.autolog()                       # LLM 호출 자동 trace

@mlflow.trace                                 # 내 함수도 span 으로
def answer(question: str) -> str:
    prompt = mlflow.genai.load_prompt("prompts:/qa@production")
    return call_llm(prompt.format(question=question))

data = [{"inputs": {"question": "RayJob 이 뭐야?"},
         "expectations": {"expected_response": "Ray 잡용 KubeRay CRD"}}]

mlflow.genai.evaluate(data=data, predict_fn=answer,
                      scorers=[Correctness(), RelevanceToQuery()])
```

### 3-5. Ray 와 같이 쓰기

- Ray Train : `ray.train.report()` 지표를 MLflow 콜백으로 전송, 체크포인트 → `log_model`
- Ray Tune : `MLflowLoggerCallback` 으로 트라이얼마다 run 자동 생성
- 정리 : Ray 가 계산, MLflow 가 기록

---

## 4. 실무에서 확인

- **멀티테넌트** : MLflow 자체 권한(basic auth)은 약함. K8s 네임스페이스 기반이면 kubeflow/mlflow-integration 플러그인 조합이 정답
- **DB** : SQLite 는 개발용. 운영은 PostgreSQL. 지표 많은 run 쌓이면 metric 테이블이 제일 큼 → 파티셔닝·정리 정책 필요
- **아티팩트** : 모델 파일이 GB 단위면 MinIO 버킷 수명주기 정책 필수. 지운 run 은 `mlflow gc` 로 실제 삭제
- **폐쇄망** : GenAI judge·AI Gateway 는 외부 LLM 전제. 사내 모델 서빙(vLLM, OpenAI 호환 엔드포인트)으로 바꿔 지정
- **trace 보관** : 운영 trace 양 많음. 차트의 trace archival CronJob 으로 오래된 trace 오브젝트 스토리지로 이관
- **버전 업그레이드** : 메이저·마이너 올릴 때 `mlflow db upgrade` 로 스키마 마이그레이션. 업그레이드 전 DB 백업

> 주의 : 클라이언트와 서버 버전 차이 크면 일부 API 실패. 특히 MLflow 2 클라이언트 → 3 서버 조합 확인 필요.

> 주의 : `--serve-artifacts` 끄면 클라이언트가 MinIO 키를 직접 가져야 함. 사용자 1,000명 환경이면 서버 프록시 방식이 키 관리상 유리.

---

## 5. 용어 정리

- **Experiment** : run 을 묶는 단위
- **Run** : 학습·실행 1회 기록
- **autolog** : 프레임워크별 자동 기록 기능
- **Logged Model** : run 과 분리된 모델 객체 (MLflow 3)
- **flavor** : 프레임워크별 모델 저장 형식
- **pyfunc** : 모든 flavor 공통 파이썬 추론 인터페이스
- **Registered Model** : 레지스트리에 이름으로 등록된 모델 + 버전 묶음
- **Alias** : 모델 버전에 붙이는 이동 가능한 이름표 (`@champion`)
- **Trace / Span** : LLM 앱 실행 1회 / 그 안의 단계 하나
- **Scorer / LLM Judge** : 답변 품질 채점 함수 / LLM 으로 채점하는 scorer
- **AI Gateway** : LLM 공급자 앞단 프록시. 키·라우팅·예산 관리

---

## 6. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 정체 | ML·LLM 실행 결과 기록·관리 플랫폼. 계산은 안 함 |
| 구조 | Tracking Server + Backend Store(PostgreSQL) + Artifact Store(MinIO) |
| 추적 | Experiment → Run → param·metric·아티팩트, autolog |
| 모델 | Logged Model → Registered Model 버전 → alias → 서빙 |
| GenAI | Tracing, Evaluation, Prompt Registry, AI Gateway |
| 연동 | Ray(계산), Kubeflow(플랫폼), KServe(서빙) |
| 운영 | PostgreSQL, 아티팩트 프록시, gc, 스키마 마이그레이션, 멀티테넌트는 플러그인 |

**MLflow 는 어떤 엔진으로 돌리든 결과를 한 장부에 남기고, 그중 배포할 버전을 alias 로 고르는 도구임.**

다음 글 : Ray · Kubeflow · MLflow 비교 - 기능, 장단점, 활용 조합
