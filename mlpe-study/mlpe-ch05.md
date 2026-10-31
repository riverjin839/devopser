## Machine Learning Platform Engineering 스터디 - CH5

> **목표** : Kubeflow Pipelines 로 4장의 MLflow·Feast 를 엮어 배치 추론을 자동화하는 구조와 컴포넌트 설계 원칙 이해

- 원서 : Machine Learning Platform Engineering (Manning, 2026)
- 범위 : 5장 Orchestrating ML pipelines
- 실습 코드 : `github.com/practical-mlops/chapter-5`
- 버전 메모 : 책은 KFP v2 SDK + YAML 컴포넌트. 현재 KFP 2.18 (2026-10)

---

## 1. 개요

4장까지 = 도구는 있지만 사람이 손으로 돌림. 재학습, 피처 갱신, 추론 모두 수동.

5장 = 그 수동 단계를 **파이프라인으로 자동화**. 1장 구성도의 파이프라인 오케스트레이션 블록 (책 그림 5.1 캡션은 A 로 표기).

<!-- diagram: mlpe-ch05-01-map.html -->

대부분의 추론 파이프라인 모양은 같음.

- 데이터 읽기 → 전처리 → 피처·모델 가져오기 → 추론 → 결과 쓰기
- 주기적으로 실행, 날짜·테이블명 같은 실행 파라미터 필요

엔지니어가 받는 질문.

- ML 워크플로를 어떻게 반복 가능하게 만듦?
- 모델마다 다른 단계를 어떻게 표준화함?
- 단계 사이 데이터 전달을 어떻게 믿을 수 있게 만듦?

**답 = 단계를 컴포넌트로 포장하고, 컴포넌트를 DAG 로 연결.**

---

## 2. 5장 개념 정리 - Orchestrating ML pipelines

### 2-1. KFP 기본

- KFP = Kubeflow 의 파이프라인 도구. 파이썬 SDK(`kfp`)로 정의
- **컴포넌트** : 재사용 가능한 작업 단위. 전처리, 학습, 평가, 배포 등
- **컴포넌트 1개 = Pod 1개** → 단계마다 깨끗하게 격리된 환경
- **파이프라인** : 컴포넌트를 DAG(방향 있음, 순환 없음)로 연결. 앞 단계 끝나야 다음 단계 실행

### 2-2. 컴포넌트 만들기

<!-- diagram: mlpe-ch05-02-component.html -->

책 방식 = **컨테이너 컴포넌트** 3단계.

1. 파이썬 코드 작성 : 함수 + `argparse` 메인 블록
2. 컨테이너화 : Dockerfile → `docker build` → `docker push`
3. 컴포넌트 명세 : `component.yaml` 에 입력·출력·이미지·실행 명령 정의

```yaml
name: Read Data From MinIO
inputs:
- {name: minio_host, type: String}
- {name: bucket_name, type: String}
- {name: file_name, type: String}
outputs:
- {name: data_output, type: Dataset}          # Dataset 타입 = 다음 단계로 넘길 산출물
implementation:
  container:
    image: <registry>/read-minio-data:latest
    command:
    - python3
    - /app/src/read_data/read_data.py
    - --bucket_name
    - {inputValue: bucket_name}               # 값 그대로 전달
    - --data_output_path
    - {outputPath: data_output}               # KFP 가 정해준 출력 경로
```

| 표기 | 의미 | 예 |
|---|---|---|
| `inputValue` | 문자열·숫자 값을 그대로 인자로 | 버킷명, 모델명 |
| `inputPath` | 앞 단계 산출물이 놓인 경로 | 엔티티 DataFrame |
| `outputPath` | 이 단계 산출물을 쓸 경로 | 피처 DataFrame |

- 단계 사이 데이터는 메모리로 안 넘어감 → 파일로 쓰고, KFP 가 아티팩트 저장소(MinIO)에 보관 → 다음 Pod 가 받아 읽음

디렉터리 구조

```
├── Dockerfile
├── requirements.txt
├── components/<이름>/component.yaml   # 명세
└── src/<이름>/<이름>.py               # 코드
```

### 2-3. 소득 분류 배치 추론 파이프라인

<!-- diagram: mlpe-ch05-03-pipeline.html -->

| 순서 | 컴포넌트 | 입력 | 하는 일 | 출력 |
|---|---|---|---|---|
| 1 | Read Data | MinIO 버킷·파일 | user_id 목록 Parquet 읽기 | entity DataFrame |
| 2 | Retrieve Features | entity_df, 피처 목록, feature_store.yaml | Feast `get_historical_features` | 피처 DataFrame |
| 3 | Run Inference | 피처 DataFrame, 모델명·stage | MLflow 에서 모델·컬럼 목록 로드 → 더미 변환 → `predict_proba` | 예측 DataFrame |
| 4 | Write Data | 예측 DataFrame | MinIO `inference-datasets` 버킷에 Parquet 저장 | - |

준비 작업

- 4장 `feast apply` 는 로컬에서 port-forward 주소로 등록함 → 파이프라인 Pod 는 그 주소를 못 씀
- 클러스터 내부 주소(`minio-service.kubeflow.svc.cluster.local:9000`)로 바꿔 **K8s Job 으로 클러스터 안에서 다시 `feast apply`**

추론 컴포넌트 포인트

- 4장에서 pickle 로 저장한 **컬럼 목록**을 MLflow 아티팩트에서 받아옴
- 추론 데이터도 같은 더미 변환 후 `reindex(columns=col_list, fill_value=0)` → 학습 때와 컬럼 순서·개수 일치
- 모델 프레임워크(sklearn, xgboost, tensorflow)별로 load 함수 분기

```python
fetch_data_op = kfp.components.load_component_from_file("components/read_data/component.yaml")
...
@dsl.pipeline(name="income-classifier-pipeline")
def income_classifier_pipeline(minio_host: str, entity_df_bucket: str, ...):
    fetch_task = fetch_data_op(minio_host=minio_host, bucket_name=entity_df_bucket, ...)
    feat_task = retrieve_features_op(entity_df=fetch_task.outputs["data_output"], ...)
    infer_task = run_inference_op(input_data=feat_task.outputs["data_output"], ...)
    write_data_op(input_data=infer_task.outputs["data_output"], ...)

compiler.Compiler().compile(income_classifier_pipeline, "income_classifier_pipeline.yaml")
```

- `task.outputs[...]` 를 다음 입력에 넣는 순간 의존성 자동 생성 → 순서 지정 코드 불필요
- 실행 : 컴파일 YAML → KFP UI 업로드 → **Experiment**(run 묶음) 생성 → **Run**(실행 1회) 시작 → UI 에서 단계별 진행 확인

KFP Experiment·Run = MLflow Experiment·Run 과 이름만 같고 대상이 다름. KFP = 파이프라인 실행, MLflow = 학습 기록.

### 2-4. 컴포넌트 설계 원칙

| 원칙 | 내용 | 실습 예 |
|---|---|---|
| 모듈화 | 컴포넌트 하나 = 기능 하나 (단일 책임) | 추론과 쓰기를 분리 |
| 입출력 명확 | 입력·출력·타입을 명세에 정의 | component.yaml |
| 파라미터화 | 값 하드코딩 금지 → 다른 환경 재사용 | mlflow_host, bucket_name |
| 문서화 | 기능·입출력·사용법 설명 | description 필드 |

얻는 것

- **재사용** : 한 번 만든 컴포넌트를 여러 파이프라인에서 씀 → 팀 표준 부품 목록
- **협업** : 사람마다 다른 컴포넌트 동시 개발
- **테스트** : 컴포넌트 단위로 따로 테스트 → 디버깅 범위 축소

### 2-5. 컨테이너 컴포넌트 vs 경량 컴포넌트

| 구분 | 컨테이너 컴포넌트 (책) | 경량 파이썬 컴포넌트 |
|---|---|---|
| 정의 | 코드 + Dockerfile + component.yaml | `@dsl.component` 데코레이터 하나 |
| 이미지 | 직접 빌드·푸시 | base_image + `packages_to_install` |
| 장점 | 무거운 의존성, 비파이썬 도구, 이미지 고정 | 빠른 개발, 파일 하나 |
| 단점 | 파일 3종 관리, 빌드 필요 | 실행 때마다 pip 설치 (폐쇄망에서 문제) |
| 언제 | 운영 표준 컴포넌트 | 프로토타입, 가벼운 단계 |

```python
from kfp import dsl, kubernetes
from kfp.dsl import Input, Output, Dataset

@dsl.component(base_image="registry.local/ml-base:py311")   # 의존성 미리 구운 사내 이미지
def run_inference(input_data: Input[Dataset], model_name: str, data_output: Output[Dataset]):
    import mlflow, pandas as pd
    model = mlflow.pyfunc.load_model(f"models:/{model_name}@champion")   # stage 대신 alias
    df = pd.read_parquet(input_data.path)
    df["pred"] = model.predict(df)
    df.to_parquet(data_output.path)

@dsl.pipeline(name="income-batch")
def pipe(model_name: str = "random-forest-classifier"):
    t = run_inference(input_data=..., model_name=model_name)
    kubernetes.use_secret_as_env(t, secret_name="minio-cred",         # 키는 Secret 으로
        secret_key_to_env={"accesskey": "AWS_ACCESS_KEY_ID", "secretkey": "AWS_SECRET_ACCESS_KEY"})
```

**운영 표준 = 의존성을 미리 구운 이미지 + 경량 컴포넌트 문법 조합이 관리하기 제일 편함.**

---

## 3. 실무에서 확인

- **비밀값 전달** : 책은 MinIO access_key·secret_key 를 파이프라인 파라미터로 넘김 → UI·실행 기록에 평문 노출. `kfp-kubernetes` 의 Secret 주입으로 바꿀 것
- **stage → alias** : 추론 컴포넌트의 `current_stage == model_stage` 비교는 MLflow 3 에서 폐기 수순. `models:/이름@champion` 으로 대체
- **이미지 반입** : 컴포넌트 이미지는 Docker Hub(`varunmallya/...`) 대신 사내 레지스트리. 경량 컴포넌트의 `packages_to_install` 은 폐쇄망에서 외부 PyPI 접근 실패 → 사내 PyPI 미러 또는 의존성 구운 base 이미지
- **KFP vs Airflow** : Lake 는 Airflow 가 이미 있음. 데이터 ETL 순서 = Airflow, ML 단계 리니지·아티팩트 추적이 필요한 학습·추론 = KFP. Airflow 에서 KFP run 을 트리거하는 조합 가능
- **아티팩트 저장소** : KFP 기본 저장소가 26.03 부터 SeaweedFS. 기존 AIStor 를 쓰려면 외부 S3 로 설정
- **Feast 등록 위치** : 실습의 "K8s Job 으로 feast apply" 를 CI(ArgoCD·Jenkins) 단계로 고정 → 피처 정의도 GitOps 로 관리
- **멀티테넌트** : 파이프라인 run 은 사용자 Profile 네임스페이스에서 돌아감 → MLflow·Feast·MinIO 접근 권한을 네임스페이스 ServiceAccount 기준으로 설계
- **배치 vs 실시간** : KFP 는 배치 추론용. 실시간 API 는 6장 BentoML (Lake 기준으로는 KServe·Ray Serve 후보)

> 주의 : `:latest` 태그 이미지를 컴포넌트에 쓰면 같은 파이프라인이 날마다 다른 코드로 돌 수 있음. 재현성을 위해 버전 태그나 digest 로 고정할 것.

---

## 4. 용어 정리

- **오케스트레이션(orchestration)** : 여러 단계를 순서·데이터·자원에 맞춰 실행·관리
- **KFP(Kubeflow Pipelines)** : K8s 위 ML 파이프라인 정의·실행 도구
- **컴포넌트(component)** : 파이프라인의 재사용 작업 단위. 실행 시 Pod 1개
- **DAG(Directed Acyclic Graph)** : 방향 있고 순환 없는 그래프. 단계 의존성 표현
- **component.yaml** : 컨테이너 컴포넌트 명세. 입출력·이미지·명령
- **inputValue / inputPath / outputPath** : 값 전달 / 입력 파일 경로 / 출력 파일 경로
- **Dataset(아티팩트 타입)** : 단계 사이 넘기는 데이터 산출물
- **KFP Experiment / Run** : 파이프라인 실행 묶음 / 실행 1회
- **경량 컴포넌트(lightweight component)** : `@dsl.component` 파이썬 함수 기반 컴포넌트
- **배치 추론(batch inference)** : 대량 데이터를 모아 주기적으로 예측

---

## 5. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 채운 블록 | 파이프라인 오케스트레이션 (KFP) |
| 컴포넌트 | 작업 단위 = Pod 1개. 코드 → 이미지 → component.yaml |
| 데이터 전달 | inputPath·outputPath 파일 + 아티팩트 저장소 |
| 실습 파이프라인 | MinIO 읽기 → Feast 피처 → MLflow 모델 추론 → MinIO 쓰기 |
| 의존성 | `task.outputs` 연결만으로 DAG 자동 구성 |
| 설계 원칙 | 단일 책임, 입출력 명확, 파라미터화, 문서화 |
| 현재 기준 보완 | 경량 컴포넌트, alias, Secret 주입, 이미지 태그 고정 |
| 실무 | Airflow 와 역할 분담, 사내 이미지·PyPI, 네임스페이스 권한 |

**4장의 도구들을 사람이 아니라 파이프라인이 돌리게 만드는 게 5장. 잘 쪼갠 컴포넌트가 곧 팀의 재사용 자산임.**

다음 글 : 6장 Productionizing ML models - BentoML 로 실시간 서빙, Evidently 로 데이터 드리프트 감시
