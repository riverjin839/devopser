## Machine Learning Platform Engineering 스터디 - CH4

> **목표** : MLflow 로 실험 추적·모델 레지스트리, Feast 로 피처 스토어를 붙여 "재현 가능한 ML 시스템" 기반 만들기

- 원서 : Machine Learning Platform Engineering (Manning, 2026)
- 범위 : 4장 Designing reliable ML systems
- 실습 코드 : `github.com/practical-mlops/chapter-4`
- 버전 메모 : 책은 MLflow 2.6. 현재 MLflow 3.17, Feast 0.67 (2026-10). 달라진 부분은 본문에 따로 표시

---

## 1. 개요

2부(핵심 기능 만들기) 첫 장. 1장 전체 구성도의 블록을 하나씩 실제 도구로 채우기 시작함.

4장이 채우는 블록 3개.

- **C 실험 추적** : MLflow Tracking
- **B 모델 레지스트리** : MLflow Model Registry
- **D 피처 스토어** : Feast

<!-- diagram: mlpe-ch04-01-map.html -->

실습 = 소득 구간 분류(<=50K / >50K). 데이터 약 3만 행, 전부 범주형 변수.

ML 엔지니어가 늘 받는 질문 3개.

- 지금 운영 중인 모델 버전이 뭐임?
- 제일 좋은 결과를 낸 파라미터가 뭐였음?
- 6개월 전 결과를 다시 만들 수 있음?

**4장 도구 = 이 세 질문에 답하는 장치.**

---

## 2. 4장 개념 정리 - Designing reliable ML systems

### 2-1. MLflow 실험 추적

추적이 필요한 이유 3가지.

- **재현성** : 동료가 같은 결과를 다시 만들 수 있어야 함
- **모델 선택** : 여러 모델·파라미터 중 최고를 고르려면 기록이 있어야 함
- **성능 추적** : 재학습 모델을 이전 버전과 비교

Git 커밋이나 파라미터 파일로도 가능은 함. 단, 태깅·공유·설명 부담이 큼 → 추적 서버 하나로 해결.

<!-- diagram: mlpe-ch04-02-mlflow-flow.html -->

#### 2-1-1. 데이터 탐색(EDA)

- `describe()`, `info()` 로 기본 통계 확인. 범주 수, 최빈값
- 범주형 변수별 타깃 분포 그래프 생성 → 예 : 자영업자는 50K 초과 비율 높음
- 그래프 묶음을 EDA 전용 run 의 아티팩트로 저장 → 나중에 누구나 UI 에서 확인

```python
mlflow.set_tracking_uri("http://localhost:5000")
mlflow.set_experiment("income-classifier")      # 실험 = 프로젝트 단위 묶음

with mlflow.start_run(run_name=f"eda-{uuid.uuid4()}"):   # EDA run 은 이름으로 구분
    ...                                                   # 그래프 생성·저장
    mlflow.log_artifacts("categorical_variable_plots")    # 폴더째 업로드
```

용어 구분

- **Experiment** : run 묶음. 프로젝트 단위
- **Run** : 실행 1회. run ID 로 식별. 파라미터·지표·아티팩트 기록

#### 2-1-2. 학습 기록

전처리

- 범주형 → 더미 변수 (`pd.get_dummies`, `drop_first=True`)
- 타깃 → 0/1 인코딩
- **컬럼 목록을 pickle 로 저장** → 추론 때 같은 컬럼 순서로 맞추는 용도. 5장에서 다시 씀
- train : test = 8 : 2

데이터셋도 기록

- train·test·reference 데이터셋을 MinIO 버킷에 저장
- `mlflow.data.from_pandas(df, source=경로)` → `mlflow.log_input(..., context="training")`
- MLflow 는 데이터 본체가 아니라 **위치·컬럼·행 수 메타데이터**만 기록

모델 3개 비교

| 모델 | 기록 방식 | 특징 |
|---|---|---|
| 결정 트리 | 수동 (`log_metric`, `log_params`, `log_model`) | 무엇을 남길지 직접 통제 |
| 랜덤 포레스트 | 수동 | 최종 선택 모델 (test AUC 최고) |
| XGBoost | `mlflow.xgboost.autolog()` | 파라미터·모델·피처 중요도 그래프 자동. 단, 커스텀 지표는 직접 기록 |

```python
with mlflow.start_run() as run:
    tree = DecisionTreeClassifier().fit(X_train, y_train.ravel())
    mlflow.log_input(mlflow.data.from_pandas(train_df, source=train_path), context="training")
    mlflow.log_metric("roc_auc_score_test",
                      roc_auc_score(y_test == 1, tree.predict_proba(X_test)[:, 1]))
    mlflow.log_params(tree.get_params())
    mlflow.sklearn.log_model(tree, name="income-classifier")   # 책 : 두 번째 인자 위치 지정
```

수동 기록 = 통제, autolog = 편의. 실무는 autolog 켜고 업무 지표만 추가 기록.

#### 2-1-3. 모델 레지스트리

최고 모델 고르는 방법 2가지.

- **UI** : 검색창에 `metrics.roc_auc_score_test > 0.8` → 차트 뷰로 비교
- **클라이언트** : `search_runs(filter_string=..., order_by=[... DESC], max_results=1)` → `register_model`

```python
run = client.search_runs(experiment_ids=exp.experiment_id,
                         filter_string="metrics.roc_auc_score_test > 0.8",
                         order_by=["metrics.roc_auc_score_test DESC"], max_results=1)[0]
mv = mlflow.register_model(f"runs:/{run.info.run_id}/income-classifier",
                           "random-forest-classifier")

# 현재 권장 : stage 대신 alias 로 운영 버전 지정
client.set_registered_model_alias("random-forest-classifier", "champion", mv.version)
```

| 항목 | 책 (MLflow 2.6) | 현재 (MLflow 3.x) |
|---|---|---|
| 운영 버전 지정 | stage : Staging → Production | **alias** : `@champion`, `@challenger` |
| 모델 불러오기 | `models:/이름/Production` | `models:/이름@champion` |
| 모델 객체 | run 의 아티팩트 | Logged Model (run 과 분리된 1급 객체) |
| 프롬프트 관리 | Prompts 탭, 기능 제한 → 12장 Langfuse | Prompt Registry 정식 기능 |

> 주의 : stage API 는 폐기 수순. 새로 만드는 코드는 alias 로 작성할 것.

- 책은 로컬 `mlflow ui` 로 실습 → 협업하려면 K8s 등 공용 위치에 서버 설치 필요 (부록 A)

### 2-2. Feast 피처 스토어

#### 2-2-1. 왜 필요한가

- 실제 피처는 여러 테이블·파일에서 옴 → 조인·가공 로직이 복잡해짐
- 실습은 한 파일을 일부러 3개로 쪼갬 : 인구통계(성별·인종·국적) / 관계(혼인·관계) / 직업(고용형태·학력·직종)
- 각 파일 = 타임스탬프 + user_id + 피처

핵심 문제 = **"그 시점에 맞는 피처" 꺼내기**.

<!-- diagram: mlpe-ch04-04-pit.html -->

- user_id 의 피처가 1/7, 5/21, 12/4 세 번 기록됨
- 5/22 기준 학습 데이터 → 정답은 5/21 값
- 12/4 값을 쓰면 미래 정보가 섞임 → **데이터 누수(data leakage)**
- Feast 가 이 point-in-time join 을 대신 해줌 → SQL·스크립트 직접 관리 불필요
- **TTL** : 몇 일 전까지 거슬러 볼지. TTL 2일이면 5/20 이전 값은 무시. 실습은 365일

#### 2-2-2. 구조

<!-- diagram: mlpe-ch04-03-feast.html -->

| 구성 | 역할 | 실습 구성 |
|---|---|---|
| 피처 생성 파이프라인 | 피처 계산 → 오프라인 스토어 적재 | (수동 업로드) |
| 오프라인 스토어 | 전체 이력 보관. 학습·배치 추론용 | MinIO 의 Parquet 파일 |
| 온라인 스토어 | 최신 값만. 실시간 추론용, 저지연 | Redis |
| 레지스트리 | 엔티티·피처 정의, 스토어 위치 | MinIO 의 `registry_local.db` |
| materialize | 오프라인 → 온라인 복사 | `feast materialize 시작 끝` |
| SDK·피처 서버 | 조회 인터페이스 | Python SDK, `feast serve` (REST) |

오프라인 = 학습용 과거 전체, 온라인 = 서빙용 최신 한 줄.

#### 2-2-3. 피처 등록

- **Entity** : 피처의 주인 식별자. 여기선 `user_id`. 상품이면 `product_id`
- **DataSource** : 파일 위치. `FileSource(path="s3://...", s3_endpoint_override=...)`
- **FeatureView** : 피처 묶음 = 엔티티 + 스키마 + TTL + 소스 + 태그
- **feature_store.yaml** : 프로젝트명, 레지스트리 위치, 오프라인·온라인 스토어 설정

```python
user = Entity(name="user_id", description="A user")

demo_src = FileSource(file_format=ParquetFormat(),
                      path="s3://feature_data_sets/demographic_features.parquet",
                      s3_endpoint_override="http://localhost:9000")

demographic = FeatureView(
    name="demographic", entities=[user], ttl=timedelta(days=365),
    schema=[Field(name="Native_country", dtype=String),
            Field(name="Sex", dtype=String), Field(name="Race", dtype=String)],
    source=demo_src, tags={"used_by": "Income_Calculation_Team"})
```

```yaml
project: my_feature_repo
registry: s3://feature-registry/registry_local.db
provider: local
offline_store:
  type: file
online_store:
  type: redis
  connection_string: "localhost:6379"
```

```bash
feast apply      # 레지스트리에 엔티티·FeatureView 등록 + Redis 준비
```

#### 2-2-4. 피처 조회

| 방법 | 함수 | 입력 | 용도 |
|---|---|---|---|
| 과거 피처 | `get_historical_features` | entity_df (`user_id` + `event_timestamp`) | 학습, 배치 추론 |
| 온라인 피처 | `get_online_features` | entity_rows (`user_id` 만) | 실시간 추론 |
| 피처 서버 | `POST /get-online-features` | JSON | SDK 없는 언어 (Java, Go 등) |
| UI | `feast ui` | - | 피처뷰·엔티티·태그 탐색 |

```python
store = FeatureStore(repo_path=".")
entity_df = pd.DataFrame({"user_id": [uid], "event_timestamp": [datetime(2023, 1, 30)]})
train_df = store.get_historical_features(entity_df=entity_df,
                                         features=["demographic:Sex"]).to_df()

# 온라인은 먼저 materialize 필요
# feast materialize 2022-09-16T00:00:00 2023-09-17T00:00:00
online = store.get_online_features(features=["demographic:Sex"],
                                   entity_rows=[{"user_id": uid}]).to_df()
```

- 컬럼 이름 규칙 고정 : 엔티티 이름(`user_id`) + `event_timestamp`
- 피처 지정 형식 : `피처뷰:피처` (예 : `demographic:Sex`)

**training-serving skew 방지 = 학습과 서빙이 같은 정의에서 피처를 꺼내는 구조.**

---

## 3. 실무에서 확인

- **MLflow 멀티테넌트** : 책은 로컬 서버 하나. 사용자 1,000명이면 kubeflow/mlflow-integration 으로 네임스페이스 = 워크스페이스, Keycloak 헤더 SAR 모드 권한 연동
- **MLflow 저장소** : 백엔드 = CNPG PostgreSQL, 아티팩트 = AIStor 버킷. `--serve-artifacts` 로 사용자에게 S3 키 안 나눠줌
- **stage → alias** : 사내 표준 코드·템플릿은 처음부터 alias 기준으로. 5장 추론 컴포넌트도 alias 로 바꿔 씀
- **Feast 오프라인 스토어** : 실습 = 파일. 운영은 이미 있는 Iceberg 테이블을 쓰는 게 자연스러움 → Spark·Trino 오프라인 스토어(커뮤니티 contrib) 검토. 정형 피처는 StarRocks MV 가 대안
- **Feast 온라인 스토어** : Redis 를 HA 로 운영할 여력 있는지 먼저 확인. 실시간 추론 수요 없으면 온라인 스토어 생략 가능
- **Feast 레지스트리** : 파일(`registry.db`) 은 동시 수정에 약함 → 여러 팀이 쓰면 SQL 레지스트리(PostgreSQL)
- **데이터 버전** : `log_input` 은 위치만 기록 → 그 위치 파일이 바뀌면 재현 깨짐. Iceberg 스냅샷 ID 를 파라미터로 같이 기록
- **폐쇄망** : `pip install mlflow`, `feast` 패키지와 Redis 이미지를 Nexus 프록시 경유로 반입

> 주의 : 실습은 `kubectl port-forward` 로 MinIO·Redis 에 붙음. 운영에서 사용자마다 port-forward 하는 구조는 금물. 클러스터 내부 서비스 주소와 권한으로 접근할 것.

> 주의 : MinIO 기본 계정(minio/minio123)과 접속 키를 코드에 적는 실습 방식 그대로 쓰지 말 것.

---

## 4. 용어 정리

- **실험 추적(experiment tracking)** : 파라미터·지표·아티팩트를 run 단위로 기록·비교
- **Experiment / Run** : run 묶음 / 실행 1회
- **아티팩트(artifact)** : run 이 남긴 파일. 모델, 그래프, 데이터
- **autolog** : 프레임워크별 자동 기록
- **모델 레지스트리(model registry)** : 등록 모델의 버전·alias 관리 저장소
- **alias** : 모델 버전에 붙이는 이동 가능한 이름표 (`@champion`)
- **피처 스토어(feature store)** : 피처 정의·저장·조회를 통일하는 계층
- **Entity / FeatureView** : 피처 주인 식별자 / 피처 묶음 정의
- **point-in-time join** : 기준 시각 이전의 가장 최근 피처만 붙이는 조인
- **TTL(time to live)** : 피처를 거슬러 볼 최대 기간
- **materialize** : 오프라인 피처를 온라인 스토어로 복사
- **데이터 누수(data leakage)** : 학습 데이터에 미래·정답 정보가 섞이는 문제

---

## 5. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 채운 블록 | C 실험 추적, B 모델 레지스트리, D 피처 스토어 |
| MLflow 추적 | Experiment → Run → 파라미터·지표·아티팩트·데이터셋 위치 |
| 기록 방식 | 수동 = 통제, autolog = 편의 + 커스텀 지표만 추가 |
| 레지스트리 | AUC 기준 검색 → 등록 → (현재) alias 로 운영 버전 지정 |
| Feast 구조 | 레지스트리 + 오프라인(이력) + 온라인(최신) + materialize |
| 핵심 기능 | point-in-time join 으로 시점 맞는 피처, 누수 방지 |
| 조회 | 학습·배치 = historical, 실시간 = online, 타 언어 = 피처 서버 |
| 실무 | 멀티테넌트 MLflow, alias 표준, Iceberg 오프라인 스토어, 키 관리 |

**모델은 MLflow 에, 피처는 Feast 에 등록해 두면 "언제, 어떤 데이터·피처로 만든 어떤 모델인지"를 언제든 다시 꺼낼 수 있음.**

다음 글 : 5장 Orchestrating ML pipelines - Kubeflow Pipelines 컴포넌트, 배치 추론 파이프라인
