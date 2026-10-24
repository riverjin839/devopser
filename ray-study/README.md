## Ray 스터디 - Kubeflow 대신 Ray 로 ML 플랫폼 보기

> **목표** : Ray 구조, KubeRay 운영 방식, Kubeflow 와 차이, 기본 사용법 이해

- 출처 : github.com/ray-project/ray, docs.ray.io, KubeRay 문서
- 기준 버전 : Ray 2.59.0, KubeRay 1.7.1 (2026-10 기준)
- 비교 대상 : Kubeflow 26.03 (KFP 2.16, Trainer 2.1, KServe 0.16)

---

## 1. 개요

Ray = 파이썬 코드를 노트북 1대에서 수천 노드까지 그대로 확장하는 분산 실행 엔진.

- 시작 : UC Berkeley RISELab. 현재 Anyscale 주도
- 2025-10 PyTorch Foundation 합류. PyTorch(모델) + vLLM(추론) + Ray(분산 실행) 묶음
- KubeRay 는 별도 레포 `kuberay-project/kuberay` 로 이동

Kubeflow 와 출발점이 다름.

- **Kubeflow** = K8s 위 ML 도구 모음. 단계마다 Pod 띄워 이어 붙임
- **Ray** = 파이썬 분산 런타임. 한 클러스터 안에서 데이터·학습·서빙을 같은 API 로 돌림

**Kubeflow 는 "워크플로를 K8s 리소스로", Ray 는 "파이썬 함수를 분산으로".**

---

## 2. Ray 개념 정리

### 2-1. 3계층 구조

<!-- diagram: mlpe-ray-01-stack.html -->

| 계층 | 구성 | 역할 |
|---|---|---|
| AI 라이브러리 | Data, Train, Tune, Serve, RLlib | ML 단계별 분산 처리 |
| Ray Core | Task, Actor, Object | 범용 분산 실행 API |
| Ray Cluster | KubeRay, Cluster Launcher, Slurm/YARN | 실제 노드 묶음 + 오토스케일 |

- 라이브러리는 골라 쓰기 가능. 전부 쓸 필요 없음
- 라이브러리 전부 Ray Core 위에서 돌아감 → 단계 간 데이터 이동이 같은 오브젝트 스토어 안에서 끝남

### 2-2. Ray Core 4가지 기본 요소

- **Task** : `@ray.remote` 붙인 함수. 다른 워커 프로세스에서 비동기 실행. 상태 없음
- **Actor** : `@ray.remote` 붙인 클래스. 상태 가진 워커 = 작은 서비스
- **Object** : Task·Actor 결과물. 노드별 공유 메모리 오브젝트 스토어에 저장. `ObjectRef` 로 참조
- **Placement Group** : 여러 노드 자원 한 번에 예약. `PACK`(모아서) / `SPREAD`(흩어서). 갱 스케줄링 용도

Task = 함수, Actor = 상태 있는 클래스.

자원 요구는 `num_cpus`, `num_gpus`, 커스텀 리소스로 선언 → 스케줄러가 그 값만 보고 배치함.

### 2-3. 클러스터 구조

<!-- diagram: mlpe-ray-02-cluster.html -->

- **Head 노드** : 클러스터당 1개. 관리 프로세스 전담
  - **GCS(Global Control Service)** : 노드·액터·잡 메타데이터 저장. 클러스터 두뇌
  - **Driver** : 잡 스크립트 실행 프로세스
  - **Autoscaler** : 자원 요청 보고 워커 증감. K8s 에선 head Pod 사이드카
  - **Dashboard** : 잡 제출 API + 모니터링 UI (기본 8265 포트)
- **Worker 노드** : 사용자 코드만 실행
  - **Raylet** : 노드별 로컬 스케줄러
  - **Object Store** : 노드별 공유 메모리. 노드 간 오브젝트 직접 전송

> 주의 : 오토스케일러는 **Task·Actor 자원 요청**에만 반응함. CPU 사용률이나 앱 지표 보고 늘리는 HPA 와 다름.

> 주의 : 대규모 클러스터는 head 노드에 Task 안 올리는 게 권장. `num-cpus: 0` 으로 head 비워둘 것.

### 2-4. AI 라이브러리

| 라이브러리 | 하는 일 | Kubeflow 쪽 대응 |
|---|---|---|
| Ray Data | 스트리밍 로드·전처리, 배치 추론 | (없음) Spark Operator, KFP 컴포넌트 |
| Ray Train | PyTorch·HF·XGBoost 분산 학습, 장애 복구 | Trainer (TrainJob) |
| Ray Tune | 하이퍼파라미터 탐색, 조기 종료 | Katib |
| Ray Serve | 모델 서빙, 모델 조합, 마이크로배칭 | KServe |
| RLlib | 분산 강화학습 | (없음) |
| Ray LLM | vLLM 기반 LLM 배치 추론·서빙 | KServe + vLLM 런타임 |

- Ray Data → Train 은 디스크 안 거치고 샤드 스트리밍으로 바로 넘김
- 단, 실험 추적·레지스트리·피처 스토어는 없음 → MLflow, W&B, Feast 같은 외부 도구 붙여야 함

---

## 3. KubeRay - K8s 위의 Ray

### 3-1. CRD 4종

Ray 노드 1개 = Pod 1개. head Pod 1개 + worker Pod 여러 개 = RayCluster 1개.

<!-- diagram: mlpe-ray-03-kuberay.html -->

| CRD | 용도 | 특징 |
|---|---|---|
| RayCluster | 개발·상시 클러스터 | 한 번 만들고 여러 잡 재사용. 버전 업은 재생성 |
| RayJob | 배치·학습 잡 | 잡마다 클러스터 생성 → 끝나면 삭제 가능 |
| RayService | 서빙 | RayCluster + Serve 앱. 무중단 업그레이드, HA |
| RayCronJob | 주기 실행 | cron 으로 RayJob 생성. alpha, 1.6.0 이상 |

CRD 고르는 기준

- 모델 서빙 → RayService
- 개발·프로토타이핑 → RayCluster
- 업그레이드 중 다운타임 안 됨 → RayJob (잡마다 버전 바꿔 띄움)
- 클러스터 기동 지연이 싫음 → RayCluster (미리 띄워두고 재사용)
- 주기 배치 → RayCronJob

### 3-2. RayJob 핵심 필드

- `entrypoint` : 실행할 명령. 내부적으로 `ray job submit -- $entrypoint`
- `rayClusterSpec` : 잡용 클러스터 스펙
- `submissionMode` : 잡 제출 방식
  - `K8sJobMode` (기본) : 제출용 K8s Job 따로 생성
  - `HTTPMode` : 오퍼레이터가 head 에 HTTP 로 제출
  - `SidecarMode` : head Pod 에 제출 컨테이너 주입
  - `InteractiveMode` : 사용자가 직접 제출할 때까지 대기 (alpha)
- `shutdownAfterJobFinishes` : 잡 끝나면 클러스터 삭제 여부. 기본 false
- `ttlSecondsAfterFinished` : 삭제 전 대기 시간
- `backoffLimit` : 재시도 횟수. 재시도마다 클러스터 새로 생성

### 3-3. 스케줄러 연동

기본 K8s 스케줄러는 Pod 단위라 갱 스케줄링 못 함. 일부 Pod 만 뜨고 나머지 대기 → 자원만 점유하는 교착 생김.

- 지원 : Kueue, Volcano, YuniKorn, KAI Scheduler, scheduler-plugins
- 멀티테넌트 큐·우선순위·쿼터는 Kueue 조합이 표준

---

## 4. Kubeflow vs Ray 비교

### 4-1. 비교 표

| 항목 | Kubeflow | Ray (+ KubeRay) |
|---|---|---|
| 정체 | K8s 네이티브 ML 도구 모음 | 파이썬 분산 실행 엔진 + 라이브러리 |
| 실행 단위 | 단계마다 컨테이너(Pod) | 클러스터 안의 Task·Actor (프로세스) |
| 단계 간 데이터 | 아티팩트 저장소(MinIO) 거쳐 전달 | 공유 메모리 오브젝트 스토어 |
| 워크플로 | KFP DAG. 캐싱·재실행·리니지 강함 | 없음. 파이썬 코드 흐름 그대로. 외부 오케스트레이터 필요 |
| 분산 학습 | Trainer(TrainJob), 프레임워크별 런타임 | Ray Train. Data 와 바로 연결 |
| HPO | Katib (트라이얼마다 Pod) | Ray Tune (트라이얼 = Actor, 가벼움) |
| 서빙 | KServe (InferenceService) | Ray Serve / RayService |
| 데이터 전처리 | 별도 (Spark Operator 등) | Ray Data |
| 노트북 | Notebook 컨트롤러 + Profile | 없음. 외부 Jupyter 에서 `ray.init` 접속 |
| 멀티테넌시 | Profile = 네임스페이스 + Istio + RBAC | 없음. 네임스페이스별 RayCluster 로 분리 |
| 실험 추적·레지스트리 | Model Registry, KFP 메타데이터 | 없음. MLflow 등 연동 |
| 오토스케일 | Pod·노드 단위 (HPA, CA) | 클러스터 안 자원 요청 단위 + Pod 증감 |
| 설치 부담 | 큼. Istio, Dex, cert-manager 등 다수 | 작음. 오퍼레이터 1개 + CRD |
| 강점 | 거버넌스, 재현성, 플랫폼 기능 | 개발 속도, 대규모 파이썬 병렬, LLM 학습·추론 |
| 약점 | 무거움. 단계마다 Pod 기동 오버헤드 | 플랫폼 기능 부재. 직접 붙여야 함 |

Kubeflow = 플랫폼, Ray = 컴퓨트 엔진.

### 4-2. 언제 뭘 쓰나

- **Kubeflow 쪽** : 여러 팀 공유 플랫폼, 감사·재현성 중요, 파이프라인 단계가 이질적(SQL, 스크립트, 컨테이너 혼합)
- **Ray 쪽** : 데이터 전처리 + 학습 + 튜닝이 한 덩어리, GPU 다수 분산 학습, LLM 배치 추론·RL 후학습
- **둘 다** : KFP 가 순서·재실행 관리, 무거운 계산 단계만 RayJob 으로 위임

<!-- diagram: mlpe-ray-05-with-kubeflow.html -->

**대체재라기보다 계층이 다름. 플랫폼은 Kubeflow, 계산 엔진은 Ray 가 현실적 조합임.**

---

## 5. 사용법 예시

### 5-1. 로컬 설치

```bash
pip install -U "ray[default]"        # Core + Dashboard
pip install -U "ray[data,train,tune,serve]"
ray start --head --dashboard-host 0.0.0.0   # 로컬 head 기동
ray status                                   # 자원 확인
```

### 5-2. Task / Actor / Object

```python
import ray
ray.init()   # 클러스터 안이면 자동 접속, 밖이면 address="ray://<head>:10001"

@ray.remote(num_cpus=1)
def square(x):
    return x * x

refs = [square.remote(i) for i in range(8)]   # 즉시 ObjectRef 반환
print(ray.get(refs))                           # 결과 모음 → [0, 1, 4, ...]

@ray.remote
class Counter:
    def __init__(self):
        self.n = 0
    def inc(self):
        self.n += 1
        return self.n

c = Counter.remote()
print(ray.get([c.inc.remote() for _ in range(3)]))   # [1, 2, 3] 상태 유지

big = ray.put(list(range(1_000_000)))   # 오브젝트 스토어에 1번만 저장
```

- `.remote()` = 비동기 실행, `ray.get()` = 결과 대기
- `ray.get` 루프 안에서 하나씩 부르면 병렬성 사라짐 → 리스트로 모아서 한 번에

### 5-3. ML 흐름 (Data → Train → Tune → Serve)

<!-- diagram: mlpe-ray-04-ml-flow.html -->

```python
import ray
from ray.train import ScalingConfig
from ray.train.torch import TorchTrainer

ds = ray.data.read_parquet("s3://bucket/train/")      # MinIO 도 S3 API 로 접근
ds = ds.map_batches(preprocess)                        # 분산 전처리

def train_loop(config):
    shard = ray.train.get_dataset_shard("train")      # 워커별 샤드
    model = ray.train.torch.prepare_model(build_model())
    for epoch in range(config["epochs"]):
        for batch in shard.iter_torch_batches(batch_size=256):
            ...                                         # 학습 스텝
        ray.train.report({"loss": loss})

trainer = TorchTrainer(
    train_loop,
    train_loop_config={"epochs": 5},
    scaling_config=ScalingConfig(num_workers=4, use_gpu=True),
    datasets={"train": ds},
)
result = trainer.fit()
```

```python
from ray import serve

@serve.deployment(num_replicas=2, ray_actor_options={"num_gpus": 1})
class Predictor:
    def __init__(self):
        self.model = load_model()       # MLflow 등에서 로드
    async def __call__(self, request):
        return self.model.predict(await request.json())

serve.run(Predictor.bind())             # 기본 :8000 HTTP 엔드포인트
```

### 5-4. KubeRay 로 띄우기

```bash
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm install kuberay-operator kuberay/kuberay-operator --version 1.7.0 -n ray-system --create-namespace
kubectl get pods -n ray-system
```

```yaml
apiVersion: ray.io/v1
kind: RayJob
metadata:
  name: train-job
  namespace: team-a
spec:
  entrypoint: python /home/ray/app/train.py
  shutdownAfterJobFinishes: true
  ttlSecondsAfterFinished: 600
  rayClusterSpec:
    rayVersion: "2.59.0"
    headGroupSpec:
      rayStartParams:
        num-cpus: "0"              # head 에 작업 안 올림
      template:
        spec:
          containers:
            - name: ray-head
              image: registry.local/ray:2.59.0-py311
              resources:
                limits: {cpu: "4", memory: 16Gi}
    workerGroupSpecs:
      - groupName: gpu
        replicas: 2
        minReplicas: 0
        maxReplicas: 8
        template:
          spec:
            containers:
              - name: ray-worker
                image: registry.local/ray:2.59.0-py311-gpu
                resources:
                  limits: {cpu: "16", memory: 128Gi, nvidia.com/gpu: "4"}
```

```bash
kubectl apply -f train-job.yaml
kubectl get rayjob -n team-a                 # JOB STATUS / DEPLOYMENT STATUS
kubectl logs -n team-a -l job-name=train-job # 제출 Job 로그
kubectl port-forward -n team-a svc/<cluster>-head-svc 8265:8265   # 대시보드
```

---

## 6. 실무에서 확인

- **폐쇄망 이미지** : `rayproject/ray` 이미지 + Helm 차트 내부 레지스트리 미러링 필요. `runtime_env` 의 `pip` 은 외부 PyPI 못 감 → 의존성은 이미지에 굽거나 내부 PyPI 미러 지정
- **멀티테넌트** : Kubeflow Profile 같은 개념 없음. 사용자 네임스페이스마다 RayCluster/RayJob 띄우고 ResourceQuota 로 제한하는 구조. 기존 네임스페이스 운영 모델에 그대로 얹을 수 있음
- **갱 스케줄링** : 300 노드 규모에서 기본 스케줄러로 RayJob 여러 개 동시 제출 → 부분 기동 교착 위험. Kueue 같은 큐잉 먼저 붙일 것
- **head 노드 SPOF** : GCS 가 head 메모리에 있음 → head 죽으면 클러스터 상태 소실. RayService 는 GCS FT(외부 Redis) 설정 필수
- **오브젝트 스토어 메모리** : 노드 메모리 상당 부분을 공유 메모리로 잡음. Pod `memory` limit 과 `/dev/shm` 크기 같이 계산. 부족하면 디스크 스필 → 로컬 디스크 성능 영향
- **MinIO** : Ray Data 는 S3 API 로 그대로 읽음. `AWS_ENDPOINT_URL` 만 내부 MinIO 로 지정
- **GPU 노드** : B300 같은 대형 GPU 노드는 worker group 을 GPU 종류별로 나누고 `nvidia.com/gpu` 요청으로 배치. 노드 간 통신(NCCL) 설정은 Ray 가 아니라 이미지·네트워크 쪽 책임
- **관측** : 대시보드 + Prometheus 메트릭 노출. 기존 Prometheus/Grafana 에 ServiceMonitor 로 연결

> 주의 : Ray 오토스케일러와 클러스터 오토스케일러는 다른 층임. Ray 가 Pod 를 늘려도 노드 자원 없으면 Pending. 베어메탈은 노드 증설 자동화가 없으니 `maxReplicas` 를 실제 여유 자원 기준으로 잡을 것.

> 주의 : Ray 버전은 head·worker·클라이언트 모두 같아야 함. 파이썬 마이너 버전까지 맞출 것.

---

## 7. 용어 정리

- **Ray Core** : Task·Actor·Object 로 구성된 범용 분산 실행 API
- **Task** : 원격 실행되는 상태 없는 함수
- **Actor** : 원격 실행되는 상태 있는 클래스 인스턴스
- **ObjectRef** : 오브젝트 스토어에 있는 결과를 가리키는 참조
- **Object Store** : 노드별 공유 메모리 저장소 (Plasma 기반)
- **GCS(Global Control Service)** : head 노드의 클러스터 메타데이터 저장소
- **Raylet** : 노드별 로컬 스케줄러 + 오브젝트 관리자
- **Placement Group** : 여러 노드 자원을 원자적으로 묶어 예약하는 단위
- **Runtime Environment** : 잡·태스크 단위로 패키지·환경변수 지정하는 기능
- **KubeRay** : Ray 클러스터를 K8s 리소스로 관리하는 오퍼레이터
- **RayJob / RayService** : 배치 잡용 / 서빙용 KubeRay CRD
- **갱 스케줄링(gang scheduling)** : 필요한 Pod 전부 동시에 확보될 때만 시작하는 스케줄링

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 정체 | 파이썬 분산 실행 엔진. 노트북 → 수천 노드 같은 코드 |
| 구조 | AI 라이브러리 → Ray Core → Ray Cluster 3계층 |
| Core | Task(함수), Actor(상태), Object(공유 메모리), Placement Group |
| 클러스터 | Head(GCS, Driver, Autoscaler) + Worker(Raylet, Object Store) |
| 라이브러리 | Data, Train, Tune, Serve, RLlib, LLM |
| K8s | KubeRay CRD 4종 : RayCluster, RayJob, RayService, RayCronJob |
| vs Kubeflow | Kubeflow = 플랫폼·워크플로, Ray = 계산 엔진 |
| 빠진 것 | 파이프라인 DAG, 멀티테넌시, 실험 추적, 레지스트리 |
| 운영 포인트 | 갱 스케줄링(Kueue), GCS FT, 공유 메모리, 버전 일치, 폐쇄망 이미지 |

**Ray 는 Kubeflow 를 통째로 대체하는 게 아니라, 무거운 분산 계산을 파이썬 그대로 돌리는 엔진이고 플랫폼 기능은 직접 붙여야 함.**

다음 글 : Ray Core 실습 - 로컬 클러스터에서 Task·Actor 병렬화, Dashboard 로 스케줄링 관찰
