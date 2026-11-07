## Machine Learning Platform Engineering 스터디 - CH9

> **목표** : PVC 로 파이프라인 단계 간 데이터를 공유하고, TensorBoard(단일 run 내부)와 MLflow(여러 run · 모델 버전)로 학습을 추적해 레지스트리 alias 로 모델을 승격하는 흐름 이해

- 원서 : Machine Learning Platform Engineering (Manning, 2026)
- 범위 : 9장 Model training and validation: Part 2
- 실습 코드 : 캡스톤 1 (신분증 탐지), 캡스톤 2 (영화 추천 `mng.bz/a98J`)
- 버전 메모 : 책은 `kfp[kubernetes]`, MLflow 2.x 문법 + alias. 현재 KFP 2.18, MLflow 3.18, scikit-learn 1.7 (2026-11)

---

## 1. 개요

8장 파이프라인의 남은 문제.

- 데이터셋을 컴포넌트마다 다시 내려받음 (다운로드 → 학습 → 검증 각각)
- 저장소 낭비, 단계 사이 공유가 불편
- 학습 과정이 블랙박스. 어떤 하이퍼파라미터가 좋았는지 기록이 없음

9장이 채우는 블록 = 학습(4) · 평가(5) + **실험 추적(C)** · **모델 레지스트리(B)**.

<!-- diagram: mlpe-ch09-01-map.html -->

| 도구 | 역할 |
|---|---|
| PVC | 데이터를 한 번 받아 모든 단계가 같은 볼륨에서 읽음 |
| TensorBoard | **run 하나의 내부**를 자세히 봄 (loss 곡선, mAP, 모델 그래프) |
| MLflow | **여러 run 을 인덱싱 · 검색 · 비교**, 모델 버전 · 승격 관리 |

**TensorBoard 는 현미경, MLflow 는 도서관 목록. 둘은 경쟁이 아니라 역할 분담이다.**

---

## 2. 9장 개념 정리 - Model training and validation Part 2

### 2-1. 왜 PVC 인가

<!-- diagram: mlpe-ch09-02-pvc.html -->

- MinIO 는 POSIX 파일시스템이 아님 → 파일 복사 · 이동이 불편, 단계마다 다운로드 반복
- PVC 하나를 만들어 모든 단계에 같은 경로(`/data`)로 마운트 → 한 번 받고 계속 씀

```python
from kfp import dsl, kubernetes      # pip install kfp[kubernetes]

@dsl.pipeline(name="YOLO Object Detection Pipeline")
def pipeline(epochs: int = 1, batch: int = 8, random_state: int = 42):
    pvc_name = "yolo-pipeline-pvc"
    pvc = kubernetes.CreatePVC(
        pvc_name=pvc_name,
        access_modes=["ReadWriteOnce"],      # 대부분 StorageClass 지원
        size="1Gi",
        storage_class_name="local-path",     # 클러스터마다 다름
    )

    download_op = download_dataset()
    kubernetes.mount_pvc(download_op, pvc_name=pvc_name, mount_path="/data")

    split_op = split_dataset(random_state=random_state).after(download_op)   # 순서 직접 지정
    kubernetes.mount_pvc(split_op, pvc_name=pvc_name, mount_path="/data")

    train_op = train_model(epochs=epochs, batch=batch).after(split_op)
    kubernetes.mount_pvc(train_op, pvc_name=pvc_name, mount_path="/data")
```

바뀐 것들.

| 항목 | 7·8장 (아티팩트) | 9장 (PVC) |
|---|---|---|
| 다운로드 | 아티팩트 경로에 쓰고 MinIO 업로드 | `/data/DATASET` 에 바로 압축 해제 |
| 분할 | 파일 목록을 아티팩트로 넘김 | 볼륨 안에서 `/data/train · val · test` 로 이동 |
| 학습 입력 | `Input[Dataset]` 6개 | 입력 없음, 경로 고정 `/data/train/images` |
| 실행 순서 | 데이터 의존성으로 자동 | **`.after()` 로 직접 지정** |
| 코드 양 | MinIO 클라이언트 코드 반복 | 대폭 감소 |

- 데이터를 아티팩트로 안 넘기니 KFP 가 순서를 추론 못 함 → `.after()` 필수
- 끝나면 `kubernetes.DeletePVC` 로 정리하거나, persistence agent 에 `TTL_SECONDS_AFTER_WORKFLOW_FINISH` 설정해 자동 정리

### 2-2. 데이터 접근 방식 비교

책이 강조한 판단 기준.

| 방식 | 저장 비용 | 시작 시간 | 학습 중 속도 | 조건 |
|---|---|---|---|---|
| 로컬 볼륨(PVC)에 복사 | 높음 | 느림 (복사) | 빠름 | 이미지처럼 작은 파일 많은 데이터 |
| 객체 스토리지 직접 읽기 | 낮음 | 빠름 | 네트워크에 좌우 | 고대역 네트워크 + 스트리밍 최적화 코드 |

캡스톤 1(이미지) = PVC, 캡스톤 2(Parquet 표) = MinIO 직접 읽기. 둘 다 정답이고 데이터 종류와 인프라가 결정함.

### 2-3. TensorBoard

- YOLOv8 는 TensorFlow 가 아니어도 project 디렉터리에 TensorBoard 로그를 씀
- project 경로를 PVC 마운트 경로로 지정 → 학습 Pod 가 쓰는 로그를 TensorBoard 가 같은 PVC 에서 읽음

Kubeflow 에서 띄우는 순서.

1. 파이프라인 run 시작, 최소한 `createpvc` 단계 완료 확인
2. 해당 컴포넌트 클릭 → `pvc_name` 확인
3. 사이드바 TensorBoards → New TensorBoard
4. 이름 입력, PVC 선택, PVC Name 지정, Mount Path 는 비움 → CREATE
5. 초록 체크 뜨면 CONNECT

보이는 것.

- mAP · loss 곡선 → 과적합 · 조기 종료 시점 판단
- 하이퍼파라미터 · 데이터 품질과의 상관 관찰
- 모델 아키텍처 그래프 → 층 · 연결 구조 이해

### 2-4. 캡스톤 2 - 추천 모델 학습

<!-- diagram: mlpe-ch09-03-recsys.html -->

- 데이터 생성 때 검증했어도 **학습 직전에 다시 검증** → 수집 파이프라인과 학습 파이프라인을 분리할 수 있음
- QA : `user_id · item_id · rating` 컬럼 존재, 타입 확인. 나중에 Evidently 같은 도구로 교체 가능
- 이번엔 PVC 없이 PyArrow 로 MinIO 에서 바로 읽음

모델 = PyTorch 행렬 분해(Matrix Factorization).

```python
class MatrixFactorization(torch.nn.Module):
    def __init__(self, n_users, n_items, n_factors, hidden_dim, dropout_rate):
        super().__init__()
        self.n_items = n_items
        self.user_factors = torch.nn.Embedding(n_users + 1, n_factors)   # 사용자 벡터
        self.item_factors = torch.nn.Embedding(n_items + 1, n_factors)   # 영화 벡터
        self.linear = torch.nn.Linear(n_factors, hidden_dim)
        self.linear2 = torch.nn.Linear(hidden_dim, 1)
        self.dropout = torch.nn.Dropout(dropout_rate)

    def forward(self, user, item):
        x = torch.mul(self.user_factors(user), self.item_factors(item))   # 두 벡터 곱
        x = self.dropout(torch.relu(self.linear(x)))
        return self.linear2(x)                                            # 예상 평점
```

- 옵티마이저 SGD + StepLR 스케줄러, 손실 L1
- 학습 전 **negative sampling** : 사용자가 안 본 영화를 일부 섞어 "안 좋아함" 예시도 학습

### 2-5. 추천 평가 지표

지표는 모델 만들기 전에 비즈니스 목표에서 정해야 함 (2장).

| 지표 | 뜻 | 좋은 방향 |
|---|---|---|
| RMSE | 예측 평점과 실제 평점의 오차 | 낮을수록 |
| Precision@50 | 추천 상위 50개 중 실제로 좋아한(평점 ≥ 3) 비율 | 높을수록 |
| Recall@50 | 실제로 좋아한 영화 중 상위 50개에 들어간 비율 | 높을수록 |

- 1장 혼동행렬의 precision · recall 을 "상위 K개 추천" 에 적용한 것
- 지표를 잘못 고르면 좋은 모델을 버리거나 나쁜 모델을 과대평가함

### 2-6. 실험 추적이 필요한 이유

| 실험 | 조건 | Precision@50 | Recall@50 | RMSE |
|---|---|---|---|---|
| 1 | 기본값, 6,400 샘플, 30 epoch | 0.7533 | 0.6316 | 0.2904 |
| 2 | lr 1e-2 로 변경 | 0.7422 | 0.8649 | 0.2836 |

책은 2번을 "조금 나빠짐" 으로 보고 되돌리려 함. 그런데 원래 lr 이 뭐였는지, 옵티마이저가 같았는지 기억이 안 남.

- 팀 여럿이 몇 달 동안 실험하면 스프레드시트로는 불가능
- 운영 중 이상 동작 원인 분석 = 학습 조건 · 데이터셋 버전을 그대로 재현해야 함

참고로 표를 보면 2번은 recall · RMSE 가 좋아지고 precision 만 약간 떨어짐. **어떤 지표를 우선할지 미리 정하지 않으면 "좋아졌다 · 나빠졌다" 판단부터 흔들린다.** 기록이 있어야 이런 논의가 가능함.

### 2-7. MLflow 연동 - 학습

```python
import mlflow
from mlflow.models import infer_signature

mlflow.set_experiment("recommender")
with mlflow.start_run():
    mlflow.log_params({k: v for k, v in input_params.items() if "mlflow_" not in k})  # 하이퍼파라미터 전부
    mlflow.log_param("optimizer", "SGD")
    mlflow.log_params({"n_user": n_users, "n_items": n_items})
    mlflow.log_artifact("model_summary.txt")                  # torchinfo 모델 요약

    for epoch in range(training_epochs):
        ...
        mlflow.log_metric("avg_training_loss", t_loss / t_count, step=epoch)
        mlflow.log_metric("avg_testing_loss", te_loss / te_count, step=epoch)

    signature = infer_signature({"user": users_np, "movie": movies_np}, preds_np)   # 입출력 스키마
    mlflow.pytorch.log_model(model, "model", signature=signature)
```

- `locals()` 로 함수 인자를 통째로 기록 → 빠뜨리는 파라미터 없음
- **signature** 기록 → 나중에 모델 클래스 코드 없이 로드 · 추론 가능
- `hot_reload_model_run_id` 로 이전 run 모델을 불러와 이어서 학습(warm start)

아티팩트 업로드 경로 2가지.

| 방식 | 동작 | 장단점 |
|---|---|---|
| 직접 접근 | 학습 Pod 가 S3 · MinIO 에 직접 업로드, 메타데이터만 서버로 | 빠름. 학습 환경마다 스토리지 자격증명 필요 |
| 프록시 모드 | 업로드를 트래킹 서버가 중계 | 설정 간단. 큰 파일이면 서버 한 곳이 병목 |

### 2-8. MLflow 연동 - 검증

```python
model = mlflow.pytorch.load_model(f"runs:/{model_run_id}/model")   # 클래스 코드 불필요
...
mlflow.log_metric("precision_50", avg_precision, run_id=model_run_id)   # 끝난 run 에 지표 추가
mlflow.log_metric("recall_50", avg_recall, run_id=model_run_id)
mlflow.log_metric("rms", rms, run_id=model_run_id)
```

- 학습과 검증을 다른 컴포넌트로 분리해도 **같은 run_id 에 지표를 이어 붙임** → 이력이 한 줄로 유지
- UI 에서 run 여러 개 선택 → Compare → 하이퍼파라미터와 지표 관계를 한 화면에. 태그 · 설명으로 검색
- 대시보드 링크 공유 = 엔지니어에게 묻지 않아도 이해관계자가 직접 확인 (비동기 소통)

### 2-9. 레지스트리 승격 - alias 게이트

<!-- diagram: mlpe-ch09-04-promote.html -->

- run 은 많고, 기준을 넘은 것만 레지스트리에 등록
- 등록 모델 = 이름 + 버전 + **alias**(`staging`, `prod`) + 메타데이터
- alias 를 다른 버전으로 옮기면 배포 · 롤백 끝

```python
from mlflow import MlflowClient
client = MlflowClient()

try:
    current = client.get_model_version_by_alias("recommender_production", "staging")
except RestException:
    current = None                                    # 첫 등록

if current is not None:
    old = client.get_run(current.run_id).data.metrics
    new = client.get_run(new_run_id).data.metrics
    if new["rms"] - old["rms"] > rms_threshold:                     return   # 오차 증가
    if new["precision_50"] - old["precision_50"] < precision_threshold: return
    if new["recall_50"] - old["recall_50"] < recall_threshold:          return

v = mlflow.register_model(f"runs:/{new_run_id}/model", "recommender_production")
client.set_registered_model_alias("recommender_production", "staging", v.version)
```

- 자동 승격은 `staging` 까지. `prod` 는 사람 검토 후 (조직 성향에 따라 자동도 가능)
- 책은 `dev.ml_components.recommender` → `prod.ml_components.recommender` 처럼 환경별 모델 이름을 나누는 방식도 소개

> 주의 : 책 코드 원문은 `current_staging` 이 `None` 인 상태에서 `current_staging.run_id` 를 먼저 읽음 → 첫 실행(staging 없음)에 `AttributeError`. 위처럼 None 체크를 먼저 할 것.

### 2-10. 전체 파이프라인과 노트북 추론

```python
@dsl.pipeline(name="Model training pipeline")
def training_pipeline(minio_bucket: str = "datasets", training_epochs: int = 30, ...):
    qa = qa_data(bucket=minio_bucket)
    meta = get_dataset_metadata(bucket=minio_bucket).after(qa)
    neg = negative_sampling(bucket=minio_bucket, split="train").after(meta)
    aux = get_test_valid_dataset(bucket=minio_bucket).after(neg)
    train = train_model(training_data=neg.outputs["negative_sampled_dataset"],
                        testing_data=aux.outputs["testing_dataset"], ...)
    val = validate_model(model_run_id=train.output,
                         validation_dataset=aux.outputs["validation_dataset"]).after(train)
    promote_model_to_staging(model_run_id=train.output).after(val)
```

- 학습 컴포넌트 출력 = run_id 문자열 → 검증 · 승격이 run_id 로 MLflow 에서 모델을 찾음
- 파라미터가 20개 넘음 → 파이프라인을 쪼개서 파이프라인이 파이프라인을 호출하는 구성도 가능

노트북에서 바로 추천 받아보기.

```python
current = MlflowClient().get_model_version_by_alias("recommender_production", "prod")
model = mlflow.pytorch.load_model(f"runs:/{current.run_id}/model")
# 안 본 영화 전체에 대해 예상 평점 → topk 10 → 영화 제목 매핑
```

- 사용자 50번 추천 = 아동 · 드라마 장르 → 실제 시청 이력과 일치
- 단순 모델도 자동 수집 · 재학습 루프 안에 있으면 계속 나아짐. 한계에 닿으면 구조 변경

### 2-11. 책 vs 현재

| 항목 | 책 | 현재 |
|---|---|---|
| RMSE 계산 | `mean_squared_error(..., squared=False)` | scikit-learn 1.6 에서 `squared` 인자 제거 → `root_mean_squared_error(y_true, y_pred)` |
| 모델 기록 | `mlflow.pytorch.log_model(model, "model")` | MLflow 3 은 `name="model"` 키워드 권장, 모델이 run 과 별개인 LoggedModel 로 관리 |
| 모델 참조 | `runs:/<run_id>/model` | 그대로 동작. `models:/<model_id>` 도 가능 |
| 승격 | alias (`staging`, `prod`) | 동일. stage API 는 폐기 |
| PVC | `kubernetes.CreatePVC`, `mount_pvc` | 동일 (`kfp-kubernetes`). `DeletePVC` 로 정리 |
| 실험 비교 | Compare 화면 | MLflow 3 UI 에서 모델 · 평가 비교 강화 |

---

## 3. 실무에서 확인

- **StorageClass 와 접근 모드** : 책은 `local-path` + RWO → 모든 단계가 같은 노드에 붙어야 함. 단계가 다른 노드로 가면 마운트 실패. 여러 노드에서 써야 하면 RWX (NFS · Isilon · CephFS) StorageClass 사용
- **PVC 청소** : run 마다 PVC 가 생기면 수백 개가 쌓임. `DeletePVC` 를 마지막 단계에, 실패 run 용으로 TTL · 주기 정리 Job
- **이미지 데이터** : 작은 파일 수만 개를 객체 스토리지에서 하나씩 읽으면 느림 → PVC 복사 또는 WebDataset · tar shard 로 묶어 스트리밍. AIStor 는 큰 객체 순차 읽기에 강함
- **TensorBoard 자원** : 사용자별 TensorBoard Pod 가 계속 떠 있으면 자원 점유. 사용 후 삭제 규칙 · 쿼터
- **MLflow 업로드 경로** : 1,000명이 큰 모델을 올리면 프록시 모드 서버가 병목. 학습 노드에 AIStor 직접 접근 권한(네임스페이스별 버킷 · 정책)을 주고 메타데이터만 서버로
- **승격 게이트 표준화** : "staging 대비 지표 차이" 게이트를 팀 공통 컴포넌트로 만들고 임계값만 파라미터로. prod 승격은 Jenkins · ArgoCD 승인 단계와 연결
- **재현성** : run 에 데이터셋 버전(Iceberg 스냅숏 ID · S3 경로), 코드 커밋 해시, 이미지 digest 를 태그로 남겨야 진짜 재현 가능
- **멀티테넌트 MLflow** : 실험 · 모델 이름 충돌 방지 → 팀 접두어 규칙 (`team-a.recommender`), Keycloak 연동 권한

> 주의 : MLflow `log_metric` 에 책처럼 f-string(`f"{loss:3f}"`)을 넘기면 문자열이 들어감. 대부분 변환되지만 텐서 · 문자열이 섞이면 오류나 정밀도 손실이 생김. `float(loss)` 로 넘길 것.

---

## 4. 용어 정리

- **PVC(PersistentVolumeClaim)** : Pod 가 요청하는 영구 저장소. StorageClass 가 실제 볼륨을 만듦
- **RWO / RWX** : 한 노드에서만 읽기쓰기 / 여러 노드에서 동시에 읽기쓰기
- **`.after()`** : 데이터 의존이 없을 때 KFP 컴포넌트 실행 순서를 직접 지정
- **TensorBoard** : 학습 곡선 · 모델 그래프 시각화 도구
- **행렬 분해(Matrix Factorization)** : 사용자 · 아이템을 벡터로 표현해 곱으로 선호도 예측
- **negative sampling** : 상호작용 없는 아이템을 부정 예시로 섞어 학습
- **Precision@K / Recall@K** : 상위 K개 추천 기준 정밀도 / 재현율
- **RMSE(Root Mean Squared Error)** : 예측 오차 제곱 평균의 제곱근
- **signature** : MLflow 모델 입출력 스키마
- **warm start** : 이전 학습 가중치에서 이어서 학습
- **alias** : 레지스트리 모델 버전에 붙이는 이름표. 옮기면 배포 · 롤백

---

## 5. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 채운 블록 | 학습(4) · 평가(5) · 실험 추적(C) · 레지스트리(B) |
| PVC | CreatePVC + mount_pvc, 한 번 받아 공유. 순서는 `.after()` |
| 데이터 접근 | 이미지 = PVC 복사, 표 = 객체 스토리지 직접 읽기 |
| TensorBoard | 같은 PVC 마운트해 run 내부 곡선 · 그래프 확인 |
| 추천 모델 | PyTorch 행렬 분해 + negative sampling |
| 지표 | Precision@50 · Recall@50 · RMSE. 우선순위를 미리 정할 것 |
| MLflow | 파라미터 · 지표 · signature · 모델 기록, 검증 지표를 같은 run 에 |
| 승격 | staging 대비 지표 게이트 → alias. prod 는 사람 검토 |
| 현재 기준 보완 | `root_mean_squared_error`, MLflow 3 LoggedModel, None 체크 순서 |
| 실무 | RWX StorageClass, PVC 청소, 직접 업로드, 재현성 태그 |

**데이터는 한 번만 옮기고, 실험은 전부 기록하고, 배포는 alias 하나 옮기는 일로 만든다. 9장까지 오면 원본 데이터에서 등록된 모델까지 자동으로 이어짐.**

다음 글 : 10장 Model inference and serving - BentoML 서비스 · 패키징, MLflow 연동 추론, KServe 비교
