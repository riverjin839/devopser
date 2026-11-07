## Machine Learning Platform Engineering 스터디 - CH7

> **목표** : Kubeflow 노트북으로 분석 환경을 표준화하고, KFP 컴포넌트 사이 데이터 전달 규칙을 익혀 캡스톤 2개의 데이터 준비 파이프라인을 만드는 흐름 이해

- 원서 : Machine Learning Platform Engineering (Manning, 2026)
- 범위 : 7장 Data analysis and preparation (3부 Applying MLOps in practice 시작)
- 실습 코드 : 책 프로젝트 레포 (객체 탐지 `mng.bz/yNwJ`, 영화 추천 `mng.bz/a98J`)
- 버전 메모 : 책은 KFP SDK 2.11, Kubeflow Notebooks 1.x. 현재 KFP 2.18, Kubeflow 26.03 (Notebooks 1.10, v2 는 alpha) (2026-11)

---

## 1. 개요

1~6장 = 플랫폼 블록을 하나씩 채움. 7장부터 3부 = **실제 프로젝트에 적용**.

캡스톤 프로젝트 2개.

| 프로젝트 | 데이터 | 모델 | 데이터 형태 |
|---|---|---|---|
| 1. 신분증 탐지 | MIDV-500 (신분증 영상 500개 중 ID 카드만) | YOLOv8 | 이미지 + 라벨 (~10GB) |
| 2. 영화 추천 | MovieLens 25M (평점 2,500만 건) | 추천 모델 | 표 (CSV → Parquet) |

7장은 1장 구성도의 **데이터 수집·준비(3)** 단계.

<!-- diagram: mlpe-ch07-01-map.html -->

- 7-1 : 분석 환경 = Kubeflow 노트북
- 7-2 : 컴포넌트 사이 데이터 전달 규칙 (값 vs 경로 vs 아티팩트 타입)
- 7-3 : 두 캡스톤의 데이터 준비 파이프라인

**"Garbage in, garbage out". 모델 구조보다 데이터 준비가 결과를 더 크게 좌우한다는 게 3부의 출발점임.**

---

## 2. 7장 개념 정리 - Data analysis and preparation

### 2-1. 분석 환경의 조건

- 데이터 가까이에서 돌아야 함 → 대용량도 옮기지 않고 처리
- GPU·대용량 메모리 같은 비싼 자원을 필요할 때만 켰다 끔
- 배포 환경과 비슷한 환경에서 실험 + 버전 관리·CI/CD

→ 답 = **Kubeflow 노트북**. Jupyter·VS Code(code-server)·RStudio 를 브라우저로, 파이프라인과 같은 클러스터·같은 베이스 이미지로 띄움.

### 2-2. 노트북 서버 띄우기

<!-- diagram: mlpe-ch07-02-notebook.html -->

| 설정 | 의미 | 주의 |
|---|---|---|
| Namespace | 내 Profile 네임스페이스 | 쿼터·볼륨·시크릿 범위가 여기서 정해짐 |
| Image | 노트북 이미지 | 관리자가 목록 제한 가능 |
| CPU · Memory | K8s requests · limits 그대로 | 메모리 limit 너무 낮으면 OOMKilled |
| GPU | GPU 개수 | 켜 둔 동안 다른 Pod 가 못 씀 → 유휴 중지 규칙 필요 |
| Workspace volume | `/home/jovyan` 에 자동 마운트, 기본 StorageClass 로 생성 | 환경·설정 보존 |
| Data volume | 기존 PVC 마운트 | 공용 데이터셋 |
| Configurations | 네임스페이스의 PodDefault 선택 | 환경변수·시크릿·볼륨 주입 |
| Affinity / Toleration | 노드 선택 | GPU 노드 접근 통제 |
| Shared memory | `/dev/shm` 확대 | 분산 학습·DataLoader 캐시에 필요 |

- 실제 Pod = 메인 컨테이너 + init 컨테이너 + Istio 사이드카. 네트워크는 Kubeflow 가 숨김
- 노트북은 `notebooks.kubeflow.org` CRD 리소스 → 생성 후 변경은 CR 수정. 단, 수정하면 재배포 → 비영구 데이터 삭제

### 2-3. PodDefault - 설정 주입

```yaml
apiVersion: kubeflow.org/v1alpha1
kind: PodDefault
metadata:
  name: add-proxy-vars
  namespace: kubeflow
spec:
  desc: add proxy variables              # UI 에 보이는 설명
  selector:
    matchLabels:
      add-proxy-vars: "true"             # 이 라벨 달린 Pod 에만 적용
  env:
  - name: https_proxy
    value: http://192.168.1.1:3128
  - name: no_proxy
    value: .svc,.local,127.0.0.0/8
  - name: MLFLOW_TRACKING_URI            # 이후 장에서 계속 쓰임
    value: http://mlflow.kubeflow.svc.cluster.local:5000
```

- 노트북 생성 화면에서 체크하면 Pod 에 자동 주입
- 환경변수뿐 아니라 인증 정보·볼륨 마운트도 가능 → 경로·PVC 이름을 클러스터 수준에서 통제

### 2-4. 관리자 메뉴 커스터마이즈

- 노트북 생성 화면의 선택지 = `kubeflow` 네임스페이스의 `jupyter-web-app-config-*` ConfigMap
- 항목마다 `value`(기본값) + `options`(선택지) + `readOnly`(사용자 변경 금지)

```yaml
spawnerFormDefaults:
  image:                                   # Jupyter 이미지 목록
    value: kubeflownotebookswg/jupyter-scipy:v1.6.1
    options:
    - .../jupyter-pytorch:1.9.0
  imageGroupOne: [...]                     # code-server
  imageGroupTwo: [...]                     # RStudio
  affinityConfig:
    value: ""
    options:
    - configKey: small-cpu-selector
      displayName: small-cpu-node
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
            - matchExpressions:
              - {key: compute, operator: In, values: [small]}
```

- 이미지 목록을 CD 파이프라인에서 갱신 → 새 이미지 배포 = 메뉴 자동 반영
- affinity 만으로는 "선호" 수준. 고성능 노드를 막으려면 **taint + toleration** 조합

### 2-5. 커스텀 노트북 이미지

| 층 | 내용 |
|---|---|
| 베이스 의존성 | kubectl, s6-overlay(프로세스 관리), 사용자 `jovyan` 생성 |
| 런타임 | Jupyter 또는 code-server 설치 |
| 런타임 설정 | s6 init 스크립트, 홈 디렉터리, 설정 파일 |
| 커스텀 | 팀 패키지 (파이프라인 이미지와 같은 베이스) |

- 책 레포에 베이스 이미지를 인자로 받는 멀티스테이지 Dockerfile 제공
- 핵심 = **노트북 이미지와 파이프라인 컴포넌트 이미지가 같은 베이스** → 노트북에서 된 코드가 파이프라인에서도 됨

### 2-6. 데이터 전달 1 - 작은 값

<!-- diagram: mlpe-ch07-03-passing.html -->

컴포넌트 = 각자 다른 Pod. 메모리 공유 없음 → 전달 방법을 알아야 함.

```python
from kfp import dsl

@dsl.component(base_image="python:3.11", packages_to_install=["pyjokes"])
def generate_joke() -> str:
    import pyjokes                       # import 는 함수 안에
    return pyjokes.get_joke()

@dsl.component
def count_words(input: str) -> int:
    return len(input.split())

@dsl.pipeline(name="joke-pipeline")
def pipeline():
    joke = generate_joke()
    count_words(input=joke.output)       # 반환값 = .output
```

컴파일된 YAML 을 열어 보면 마법이 아님.

- `deploymentSpec.executors` : 컴포넌트마다 컨테이너 정의. ① pip 로 `kfp` 설치 ② 함수 코드를 임시 파일로 써서 `kfp.dsl.executor_main` 으로 실행
- `comp-*` : 입력·출력 타입 (`STRING`, `NUMBER_INTEGER`)
- `root.dag.tasks` : `dependentTasks`, `taskOutputParameter` 로 연결 + 캐시 설정
- 반환값 직렬화는 KFP 가 주입한 코드가 처리

의존성 넣는 3가지 방법.

| 방법 | 내용 | 권장 |
|---|---|---|
| `base_image` | 패키지가 깔린 이미지 지정 | ○ |
| `packages_to_install` | 실행 시 pip 설치 | ○ (외부망 필요) |
| 함수 안에서 `subprocess pip install` | 직접 설치 | ✕ |

### 2-7. 데이터 전달 2 - 큰 데이터는 경로로

- 값을 그대로 넘기면 Pod 메모리에 다 올림 → 수백 GB 면 **OOMKilled**
- 파일·디렉터리에 쓰고 **경로**를 넘김

```python
from kfp.dsl import Input, Output, Artifact

@dsl.component(packages_to_install=["pyjokes"])
def generate_joke(num_of_jokes: int, output_jokes: Output[Artifact]):
    import os, pyjokes
    os.makedirs(output_jokes.path, exist_ok=True)       # KFP 는 경로만 줌
    with open(os.path.join(output_jokes.path, "jokes.txt"), "w") as f:
        for _ in range(num_of_jokes):
            f.write(pyjokes.get_joke() + "\n")

@dsl.component
def count_words(jokes_file: Input[Artifact]) -> int:
    import os
    return len(open(os.path.join(jokes_file.path, "jokes.txt")).read().split())

@dsl.pipeline(name="joke-pipeline")
def joke_pipeline(num_jokes: int = 42):
    jokes = generate_joke(num_of_jokes=num_jokes)
    count_words(jokes_file=jokes.outputs["output_jokes"])   # 아티팩트는 outputs["이름"]
```

- 내부 동작 : 출력 경로(로컬 임시 경로)를 실행 후 **아티팩트 저장소(MinIO)에 업로드** → 다음 Pod 가 다운로드해서 `.path` 로 제공
- 출력 파라미터는 호출할 때 안 넘김. KFP 가 알아서 만듦

KFP v1 → v2 변화.

| v1 | v2 |
|---|---|
| `InputPath(str)` / `OutputPath(str)` | `Input[T]` / `Output[T]` |
| `_path`, `_file` 접미사 자동 제거 규칙 | 이름 규칙 없음, 타입으로 구분 |
| 경로 문자열 | `.path` + `.metadata` 가진 객체 |

### 2-8. KFP v2 아티팩트 타입

| 타입 | 용도 | UI 표시 |
|---|---|---|
| `Dataset` | 학습·검증·테스트 데이터, 피처, 분할 결과 | 파일 |
| `Model` | 학습된 모델, 체크포인트, 가중치 | 파일 |
| `Metrics` | 정확도·F1 같은 숫자 지표 `log_metric` | 지표 표 |
| `ClassificationMetrics` | ROC 곡선, 혼동행렬 `log_confusion_matrix` | 그래프 |
| `SlicedClassificationMetrics` | 데이터 조각별 분류 지표 | 그래프 |
| `HTML` | 리포트, 대화형 시각화 | 렌더링 |
| `Markdown` | 모델 카드, 요약 문서 | 렌더링 |
| `Artifact` | 위에 안 맞는 일반 파일, 설정 JSON | 파일 |

- 모든 타입에 `.metadata` dict → 샘플 수·컬럼·날짜 기록 → 리니지 추적
- 1장 혼동행렬 지표를 파이프라인 UI 에서 바로 보려면 `ClassificationMetrics` 를 쓰면 됨

### 2-9. 캡스톤 1 - 신분증 탐지 데이터 준비

YOLOv8 이 기대하는 구조부터 확인.

```yaml
path: /home/jovyan/data/
train: "train/images"          # 라벨은 train/labels 에 있다고 가정
val: "val/images"
test: "test/images"
names:
  0: id_card                   # 클래스 1개
```

- 파일 규칙 : `images/id0042.png` ↔ `labels/id0042.txt`
- 모델마다 데이터 포맷이 다름 → 분할 컴포넌트 만들기 전에 문서부터 확인

컴포넌트 3종.

| 컴포넌트 | 하는 일 | 입출력 |
|---|---|---|
| download_dataset | Box URL 에서 10GB tar.gz 스트리밍 다운로드(tqdm) → 압축 해제 | → `Output[Dataset]` |
| split_dataset | `train_test_split` 2회 → 75 / 15 / 10 | `Input[Dataset]` → `Output[Dataset]` × 3 |
| output_file_contents | 디렉터리 트리 출력 (확인용) | `Input[Dataset]` |

```python
# 3분할 = 2번 쪼개기
x_train, x_rest, y_train, y_rest = train_test_split(
    images, labels, test_size=1 - 0.75, random_state=random_state)
x_val, x_test, y_val, y_test = train_test_split(
    x_rest, y_rest, test_size=0.10 / (0.10 + 0.15), random_state=random_state)
```

- 10GB 를 컴포넌트 5개가 각자 받으면 50GB → **경로(아티팩트)로 전달**
- `random_state` 를 파이프라인 파라미터로 → 분할 재현
- 실행 : 컴파일 YAML 업로드 → Experiment 선택 → Run (반복 실행 Recurring run 도 가능). 책 환경 약 30분

> 주의 : 진행 바·상세 로그는 recurring run 에서 MinIO 에 로그가 계속 쌓임 → MinIO 가 노드 로컬 디스크면 DiskPressure → 노드 drain. 로그 보관 주기·정리 자동화 필수.

### 2-10. 캡스톤 2 - MovieLens 데이터 준비

<!-- diagram: mlpe-ch07-04-movielens.html -->

| 순서 | 컴포넌트 | 포인트 |
|---|---|---|
| 1 | download_ml25m_data | zip 을 `Output[Artifact]` 경로에 바로 씀 |
| 2 | unzip_data | ratings.csv, movies.csv 만 추출 → 출력 2개 |
| 3 | csv_to_parquet × 2 | 같은 컴포넌트 재사용, 병렬 실행 |
| 4 | split_dataset | 출력 = 폴더 1개 안에 train · val · test Parquet |
| 5 | put_to_minio × 2 | 파일·폴더 둘 다 업로드. 파일명 지정 파라미터 |
| 6 | qa_data | PyArrow 로 MinIO 직접 읽기 → 컬럼 수 · 행 수(75%) assert |

새로 나온 것들.

- **Parquet** : 컬럼 지향 포맷. CSV 보다 작고 빠름, 샤딩 가능
- **컨테이너화 파이썬 컴포넌트** : `target_image` 지정 → 의존성을 빌드 시점에 이미지로 구움 → 실행 시 pip 설치 없음, 기동 빠름, 다른 모듈 import 가능. 단, 빌드에 Docker 데몬 필요
- **명시적 순서** : 데이터 의존이 없는 QA 는 `.after(u1).after(u2)` 로 순서 강제
- **캐시 끄기** : `set_caching_options(False)`. 다운로드처럼 외부 상태에 의존하는 단계는 캐시하면 안 됨
- **노트북에서 실행** : 클러스터 안 노트북은 `kfp.Client()` 만으로 인증·엔드포인트 자동 (PodDefault 주입). 멀티유저면 ServiceAccount 토큰 필요

```python
@dsl.pipeline(name="Data prep pipeline")
def dataprep_pipeline(minio_bucket: str = "datasets", random_init: int = 42):
    dl = download_ml25m_data()
    uz = unzip_data(input_path=dl.outputs["output_path_one"])
    ratings = csv_to_parquet(inputFile=uz.outputs["ratings_output_path"])
    movies = csv_to_parquet(inputFile=uz.outputs["movies_output_path"])
    split = split_dataset(input_parquet=ratings.output, random_state=random_init)
    u1 = put_to_minio(inputFile=movies.output, upload_file_name="movies.parquet.gzip", bucket=minio_bucket)
    u2 = put_to_minio(inputFile=split.output, bucket=minio_bucket)
    qa_data(bucket=minio_bucket).after(u1).after(u2)

client = kfp.Client()                                    # 노트북 안이면 인자 없이
client.upload_pipeline("dataPrep_pipeline.yaml", pipeline_name="ml-25m-processing")
```

컴포넌트 3종류 비교.

| 종류 | 정의 | 의존성 | 언제 |
|---|---|---|---|
| 경량 파이썬 | `@dsl.component` | 실행 시 pip | 프로토타입 |
| 컨테이너화 파이썬 | `@dsl.component(target_image=...)` + `kfp component build` | 빌드 시 이미지에 | 무거운 의존성, 여러 모듈 |
| 컨테이너 | `component.yaml` 또는 `@dsl.container_component` | 직접 만든 이미지 | 비파이썬 도구 (5장 방식) |

### 2-11. 책 vs 현재

| 항목 | 책 | 현재 |
|---|---|---|
| KFP SDK | 2.11 | 2.18. 문법 동일 |
| 책 요약의 `kfp.create_component_from_func` | v1 API 표기 | v2 에선 `@dsl.component` (본문 코드는 v2) |
| 아티팩트 저장소 | MinIO | Kubeflow 26.03 부터 기본 SeaweedFS. 외부 S3 설정 가능 |
| 노트북 | Notebooks 1.x, `jupyter-web-app` | 26.03 = Notebooks 1.10. v2(Workspaces, CRD 재설계)는 alpha |
| 노트북 → 파이프라인 | 직접 컴포넌트 작성 | Kale 2.0 으로 셀 주석 → KFP v2 변환도 가능 |
| 업로드 API | `client.pipeline_uploads.upload_pipeline` | `client.upload_pipeline(...)` 권장 |

---

## 3. 실무에서 확인

- **폐쇄망 이미지** : 책은 `python:3.11` + `packages_to_install` 위주 → 폐쇄망에선 실행할 때마다 외부 PyPI 접근 실패. 컨테이너화 컴포넌트로 빌드해 사내 레지스트리에 두거나, Nexus PyPI 미러를 `pip_index_urls` 로 지정
- **노트북 이미지 관리** : 1,000명 멀티테넌트면 사용자 임의 이미지는 보안·지원 부담. ConfigMap `readOnly` 로 사내 승인 이미지만 허용, 이미지 목록은 CD 에서 갱신
- **GPU 노트북 점유** : 노트북이 GPU 를 잡고 놀면 B300 같은 고가 자원 낭비. culling(유휴 자동 중지) 설정, GPU 노트북은 별도 taint 노드 + 쿼터, 대화형은 MIG·time-slicing 고려
- **PodDefault 활용** : MLflow URI, 사내 프록시, AIStor 접속 정보, CA 인증서 마운트를 PodDefault 로 표준화 → 사용자는 체크만
- **데이터 위치** : 책은 외부 URL 다운로드. 실무는 Lake 의 Iceberg·S3 테이블에서 읽기 → 다운로드 컴포넌트 대신 Trino·Spark·PyArrow 로 필요한 파티션만 조회
- **아티팩트 저장 비용** : 10GB 데이터셋을 단계마다 아티팩트로 복사하면 run 마다 수십 GB 누적. 큰 데이터는 S3 경로 문자열만 넘기고 실제 데이터는 공용 버킷에 한 번만 두는 방식이 저장소에 덜 부담됨
- **Airflow 와 분담** : MovieLens 수집·Parquet 변환 같은 ETL 은 Airflow·Spark 가 이미 하는 일. KFP 데이터 준비 단계는 학습 직전 분할·검증 위주로 두는 게 역할 중복이 적음
- **QA 강화** : 책 QA 는 파일 존재·행 수만 봄. 스키마·null 비율·값 범위·중복까지 검사 (Great Expectations, Evidently `DataSummaryPreset`)
- **비밀값** : `minio` / `minio123` 하드코딩 → Secret 주입 (`kfp.kubernetes.use_secret_as_env`)

> 주의 : 컨테이너화 컴포넌트 빌드는 Docker 데몬이 필요함. 노트북 Pod 안에서는 보통 Docker 를 못 씀 → 빌드는 CI 에서 하고 노트북은 빌드된 이미지를 쓰는 컴포넌트 정의만 가져다 씀.

---

## 4. 용어 정리

- **캡스톤 프로젝트(capstone)** : 앞에서 배운 걸 종합하는 실전 프로젝트
- **Kubeflow 노트북** : 클러스터 안에서 띄우는 Jupyter · code-server · RStudio 서버
- **PodDefault** : 라벨 선택으로 Pod 에 환경변수·볼륨·시크릿을 주입하는 Kubeflow 리소스
- **jupyter-web-app-config** : 노트북 생성 화면 선택지를 정하는 ConfigMap
- **affinity / taint · toleration** : Pod 를 특정 노드로 끌어당김 / 노드가 Pod 를 밀어내고 허용된 Pod 만 받음
- **OOMKilled** : 메모리 limit 초과로 컨테이너가 강제 종료된 상태
- **아티팩트(artifact)** : 컴포넌트 사이 파일로 전달되는 산출물. 저장소에 보관
- **경량 / 컨테이너화 / 컨테이너 컴포넌트** : 실행 시 pip / 빌드 시 이미지 / 직접 만든 이미지
- **Parquet** : 컬럼 지향 압축 파일 포맷
- **YOLO** : 한 번 보고 객체 위치·종류를 예측하는 객체 탐지 모델 계열
- **MovieLens 25M** : GroupLens 의 영화 평점 공개 데이터셋

---

## 5. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 채운 블록 | 데이터 수집 · 준비(3), 3부 캡스톤 시작 |
| 분석 환경 | Kubeflow 노트북. 파이프라인과 같은 클러스터 · 같은 베이스 이미지 |
| 관리자 통제 | ConfigMap 으로 이미지 · 어피니티 메뉴, PodDefault 로 설정 주입 |
| 작은 값 전달 | 반환값 `.output`, KFP 가 직렬화 |
| 큰 데이터 전달 | `Output[Dataset]` 경로에 쓰고 `outputs["이름"]` 으로 넘김 |
| 아티팩트 타입 | Dataset · Model · Metrics · ClassificationMetrics · HTML · Markdown · Artifact |
| 캡스톤 1 | 다운로드 → 75/15/10 분할 → 확인 (YOLO 구조) |
| 캡스톤 2 | 다운로드 → unzip → Parquet → 분할 → MinIO → QA |
| 실무 | 사내 이미지 · PyPI, GPU 노트북 culling, Lake 테이블 직접 조회 |

**컴포넌트는 서로 메모리를 공유하지 않음. 무엇을 값으로, 무엇을 경로로 넘길지 정하는 게 KFP 설계의 기본기다.**

다음 글 : 8장 Model training and validation Part 1 - 학습 컴포넌트 설계, 지표·아티팩트 추적, 학습·검증 파이프라인
