## Kubeflow 스터디 - K8s 네이티브 AI 플랫폼 전체 구조

> **목표** : Kubeflow 서브프로젝트 구성, 플랫폼 공통 서비스, 설치 방식, 컴포넌트별 사용법 이해

- 출처 : github.com/kubeflow/kubeflow, github.com/kubeflow/community-distribution (구 manifests), kubeflow.org
- 기준 버전 : Kubeflow 26.03 (태그 v1.11.0, 2026-03), 다음 릴리스 26.10 준비 중 (master)

---

## 1. 개요

Kubeflow = K8s 위에서 데이터·AI 워크로드를 돌리는 **모듈형 오픈소스 프로젝트 묶음**.

- `kubeflow/kubeflow` 레포에는 코드 없음. README, 로드맵, 로고만 있는 입구 역할
- 실제 개발은 서브프로젝트 레포별로 진행 (pipelines, trainer, katib, hub, notebooks, dashboard …)
- 전부 묶어 설치하는 건 `kubeflow/community-distribution` (구 `kubeflow/manifests`)
- 릴리스는 연 2회 (KubeCon EU·NA 직전). 커뮤니티 지원은 6개월 best-effort
- CNCF 졸업(Graduation) 신청 상태

미션 4가지 : Simple(K8s 몰라도 됨), Portable(로컬·온프레미스·클라우드 같은 코드), Scalable(대규모 학습·에이전트), Composable(골라 쓰기).

**Kubeflow 는 제품 하나가 아니라, AI 수명주기 단계마다 하나씩 있는 K8s 컨트롤러들의 모음임.**

---

## 2. 서브프로젝트 정리

### 2-1. AI 수명주기별 구성

<!-- diagram: mlpe-kfp-01-lifecycle.html -->

| 단계 | 서브프로젝트 | 핵심 리소스 | 26.03 | master (26.10 예정) |
|---|---|---|---|---|
| 데이터 준비 | Spark Operator | `SparkApplication` | 2.5.0 | 2.5.2 |
| 탐색·개발 | Notebooks | `Notebook` | 1.10 | 1.11 (v2 alpha 별도) |
| 워크플로 | Pipelines (KFP) | Pipeline, Run, Recurring Run | 2.16.0 | 2.17.3 |
| 학습 | Trainer | `TrainJob`, `TrainingRuntime` | 2.1.0 | 2.3.0 |
| 튜닝 | Katib | `Experiment`, `Trial` | 0.19.0 | 0.19.0 |
| 등록 | Hub (구 Model Registry) | 모델·MCP 카탈로그 | 0.3.x | 0.3.18 |
| 서빙 | KServe | `InferenceService`, `LLMInferenceService` | 0.16 | 0.21.0 |
| 진입점 | Central Dashboard | Profile, KFAM, PodDefault | 1.10 | 2.0.0 |

- 각 컴포넌트 단독 설치 가능. KFP 만, KServe 만 쓰는 곳도 많음
- Kubeflow SDK : Trainer·Katib·Spark·Pipelines 를 파이썬 한 SDK 로 묶는 중
- Kale 2.0 : 노트북 셀에 주석만 달면 KFP v2 파이프라인으로 변환

### 2-2. 컴포넌트별 한 줄 요약

- **Pipelines** : 컨테이너 단계를 DAG 로 연결. 실행 엔진은 Argo Workflows. 캐싱·재실행·리니지
- **Trainer** : 구 Training Operator(PyTorchJob, TFJob …) 후속. `TrainJob` 하나 + 프레임워크별 `TrainingRuntime` 템플릿 구조. MPI, JAX, LLM 파인튜닝 지원. 내부적으로 JobSet 사용
- **Katib** : 트라이얼마다 Pod 띄워 하이퍼파라미터 탐색. random, grid, bayesian, TPE, early stopping
- **Hub** : 모델 메타데이터·버전 저장. 26 년부터 Model Catalog, MCP Catalog 추가. OCI 로 모델 저장
- **KServe** : 모델 서빙 표준. 스케일 투 제로(Knative), 카나리, LLM 멀티노드 추론
- **Notebooks** : 사용자 ns 에 Jupyter·VS Code 서버. v2 는 CRD 기반 재설계

---

## 3. 플랫폼 공통 서비스

### 3-1. 인증·멀티테넌시 구조

<!-- diagram: mlpe-kfp-02-platform.html -->

| 공통 서비스 | 역할 | 검증 버전 (master) |
|---|---|---|
| Istio (CNI 모드) | 라우팅, mTLS, AuthorizationPolicy | 1.31 |
| oauth2-proxy | Istio 게이트웨이 앞 OIDC 클라이언트, 세션·토큰 | 7.15 |
| Dex | 기본 IdP. 운영에선 Keycloak 등 외부 OIDC 로 교체 | 2.46 |
| cert-manager | 웹훅 인증서 | 1.21 |
| Knative | KServe 서버리스 모드 | 1.23 |

흐름

1. 사용자 → Istio Ingress Gateway
2. oauth2-proxy 가 OIDC 로그인 처리 → 사용자 정보 헤더 추가
3. Central Dashboard → Profile 조회 → 내가 속한 네임스페이스 목록 표시
4. 작업(노트북, 파이프라인 run, InferenceService)은 전부 내 Profile 네임스페이스 안에 생성

**Profile**

- Profile 1개 = 네임스페이스 1개 + 소유자 + RoleBinding + Istio AuthorizationPolicy + ResourceQuota
- KFAM(Kubeflow Access Management) : 기여자 추가·삭제 API
- 인증 = oauth2-proxy, 인가 = K8s RBAC + Istio AuthorizationPolicy. 둘 분리

### 3-2. 리소스 규모

master 기준 전체 설치 합계 : CPU 약 4.4 core, 메모리 약 12 GiB, PVC 65 GB.

- 제일 무거운 것 : Knative(1.45 core), KFP(0.97 core·3.5 GiB·35 GB), Istio(0.75 core·2.3 GiB)
- 단일 노드 실습 권장 사양 : RAM 16 GB, 8 core

---

## 4. Kubeflow Pipelines 자세히

### 4-1. 실행 구조

<!-- diagram: mlpe-kfp-03-kfp-run.html -->

- SDK 로 파이썬 함수를 컴포넌트로 정의 → 컴파일하면 IR YAML (플랫폼 중립 형식)
- API Server 가 IR 을 Argo Workflow 로 변환해 제출
- 단계마다 Pod 1개. 단계 간 데이터는 아티팩트 저장소 경유
- 실행 기록·입출력 리니지는 MySQL + MLMD(ML Metadata)
- **26.03 부터 기본 아티팩트 저장소가 MinIO → SeaweedFS 로 교체** (S3 API 호환)

### 4-2. KFP 특징

- **캐싱** : 입력 같은 단계는 재실행 안 하고 이전 결과 재사용
- **Recurring Run** : cron 스케줄 재학습
- **리니지** : 어떤 데이터·파라미터로 어떤 모델이 나왔는지 그래프로 추적
- 단, 단계마다 Pod 기동 → 짧은 단계 수십 개면 오버헤드 큼

---

## 5. 사용법 예시

### 5-1. 설치 (kustomize)

```bash
git clone https://github.com/kubeflow/community-distribution.git
cd community-distribution && git checkout v1.11.0     # 26.03

# 전체 한 번에 (CRD 준비 전 실패 → 재시도 루프)
while ! kustomize build example | kubectl apply --server-side --force-conflicts -f -; do
  echo "retry"; sleep 20
done

# 일부만 : example/kustomization.yaml 에서 Knative, Katib, KServe 등 주석 처리
kubectl port-forward svc/istio-ingressgateway -n istio-system 8080:80
```

> 주의 : 기본 계정 `user@example.com / 12341234`. 운영 전 Dex 비밀번호 교체 또는 외부 OIDC 연동 필수.

### 5-2. 팀 Profile 만들기

```yaml
apiVersion: kubeflow.org/v1
kind: Profile
metadata:
  name: team-a                      # = 네임스페이스 이름
spec:
  owner:
    kind: User
    name: alice@example.com
  resourceQuotaSpec:
    hard:
      cpu: "64"
      memory: 256Gi
      requests.nvidia.com/gpu: "8"
```

### 5-3. 파이프라인 (KFP v2 SDK)

```python
from kfp import dsl, compiler, Client

@dsl.component(base_image="python:3.11", packages_to_install=["pandas"])
def preprocess(rows: int, out: dsl.Output[dsl.Dataset]):
    import pandas as pd
    pd.DataFrame({"x": range(rows)}).to_csv(out.path, index=False)

@dsl.component(base_image="python:3.11", packages_to_install=["pandas", "scikit-learn"])
def train(data: dsl.Input[dsl.Dataset]) -> float:
    import pandas as pd
    df = pd.read_csv(data.path)
    return float(len(df))                              # 학습 대신 예시 값

@dsl.pipeline(name="demo-train")
def pipeline(rows: int = 1000):
    p = preprocess(rows=rows)
    t = train(data=p.outputs["out"])
    t.set_cpu_limit("4").set_memory_limit("16G")
    t.set_accelerator_type("nvidia.com/gpu").set_accelerator_limit(1)

compiler.Compiler().compile(pipeline, "pipeline.yaml")
Client(host="http://localhost:8080/pipeline").create_run_from_pipeline_package(
    "pipeline.yaml", arguments={"rows": 5000}, namespace="team-a")
```

### 5-4. 분산 학습 (Trainer TrainJob)

```yaml
apiVersion: trainer.kubeflow.org/v1alpha1
kind: TrainJob
metadata:
  name: resnet-ddp
  namespace: team-a
spec:
  runtimeRef:
    name: torch-distributed           # 클러스터에 등록된 ClusterTrainingRuntime
  trainer:
    image: registry.local/train:1.0
    command: ["torchrun", "train.py"]
    numNodes: 2
    resourcesPerNode:
      limits:
        nvidia.com/gpu: 4
```

### 5-5. 하이퍼파라미터 튜닝 (Katib)

```yaml
apiVersion: kubeflow.org/v1beta1
kind: Experiment
metadata:
  name: lr-search
  namespace: team-a
spec:
  objective:
    type: maximize
    goal: 0.95
    objectiveMetricName: accuracy
  algorithm:
    algorithmName: bayesianoptimization
  parallelTrialCount: 3
  maxTrialCount: 12
  maxFailedTrialCount: 3
  parameters:
    - name: lr
      parameterType: double
      feasibleSpace: {min: "0.0001", max: "0.1"}
  trialTemplate:
    primaryContainerName: training
    trialParameters:
      - name: learningRate
        reference: lr
    trialSpec:
      apiVersion: batch/v1
      kind: Job
      spec:
        template:
          spec:
            restartPolicy: Never
            containers:
              - name: training
                image: registry.local/train:1.0
                command: ["python", "train.py", "--lr=${trialParameters.learningRate}"]
```

### 5-6. 서빙 (KServe)

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: fraud-detect
  namespace: team-a
spec:
  predictor:
    model:
      modelFormat:
        name: sklearn
      storageUri: s3://models/fraud-detect/v3
```

```bash
kubectl get isvc -n team-a          # READY True + URL 확인
```

---

## 6. Kubeflow 와 대안 비교

| 항목 | Kubeflow 전체 | KFP 단독 | Ray (KubeRay) | MLflow | 관리형 (SageMaker·Vertex) |
|---|---|---|---|---|---|
| 범위 | 개발~서빙 전체 | 파이프라인만 | 분산 계산 | 기록·레지스트리 | 전체 |
| 멀티테넌시 | Profile 완비 | 약함 | 없음 | 플러그인 필요 | IAM 기반 |
| 설치·운영 부담 | 큼 | 중간 | 작음 | 작음 | 없음 (비용 대신) |
| 폐쇄망 | 가능 (이미지 미러링) | 가능 | 가능 | 가능 | 불가 |
| 강점 | 거버넌스, 재현성, K8s 표준 | 가벼운 DAG + 리니지 | 파이썬 확장성, LLM | 실험 추적 표준 | 즉시 사용 |
| 약점 | 컴포넌트 많음, 업그레이드 어려움 | 인증·권한 직접 | 플랫폼 기능 없음 | 계산 없음 | 종속, 비용 |

Kubeflow 전체 = 공용 플랫폼, KFP 단독 = 워크플로만, Ray = 계산 엔진, MLflow = 장부.

---

## 7. 실무에서 확인

- **폐쇄망** : 공식 FAQ 기준 가능. trivy 스캔 스크립트로 이미지 목록 추출 → 미러링 → kustomize overlay 로 이미지 교체. Kyverno 런타임 치환도 방법
- **Cilium 환경** : Istio CNI 와 같이 쓰려면 Cilium 쪽 설정 필요. 안 하면 Central Dashboard 에서 RBAC access denied 발생
- **멀티테넌트 구조** : Profile = 네임스페이스. 이미 사용자별 네임스페이스 운영 중이면 Profile CR 로 기존 ns 를 감싸는 방식 검토. ResourceQuota 는 Profile 이 관리하게 되므로 기존 쿼터 관리 체계와 충돌 여부 확인
- **인증** : Dex 대신 Keycloak 을 oauth2-proxy OIDC 로 연결. MLflow(SAR 모드), Ray 대시보드도 같은 헤더 체계로 맞추면 SSO 통일
- **스토리지** : 26.03 에서 MinIO → SeaweedFS 기본값 변경. 기존 MinIO/AIStor 를 KFP 아티팩트 저장소로 쓰려면 외부 S3 로 설정하고 SeaweedFS 빼는 구성
- **업그레이드** : 26.03 → 26.10 은 Dashboard 2.0 이전, JobSet 셀렉터 변경 등 수동 삭제 단계 있음. Profile CRD·Namespace 는 절대 지우지 말 것
- **규모** : KFP·Knative·Istio 컨트롤 플레인이 대부분 자원 차지. 300 노드 규모에선 KFP DB(MySQL)·Argo 컨트롤러 튜닝이 병목 지점

> 주의 : `kubeflow/kubeflow` 레포 클론해도 설치할 게 없음. 설치는 `community-distribution`, 개별 컴포넌트는 각 서브프로젝트 레포.

> 주의 : 전체 설치를 처음부터 하지 말 것. KFP 단독 또는 KServe 단독으로 시작해 필요할 때 Profile·Dashboard 를 붙이는 게 운영 부담이 적음.

---

## 8. 용어 정리

- **Community Distribution** : 공식 컴포넌트 + 공통 서비스를 kustomize 로 묶은 설치본 (구 manifests)
- **Profile** : 사용자·팀 단위 네임스페이스 + 권한 묶음 CR
- **KFAM(Kubeflow Access Management)** : Profile 기여자 관리 API
- **IR YAML** : KFP v2 SDK 가 컴파일한 플랫폼 중립 파이프라인 정의
- **MLMD(ML Metadata)** : 실행·아티팩트 리니지 저장 라이브러리
- **TrainJob / TrainingRuntime** : Trainer v2 의 학습 잡 / 프레임워크별 실행 템플릿
- **JobSet** : 여러 Job 을 한 단위로 묶는 K8s 프로젝트. Trainer 내부에서 사용
- **Experiment / Trial** : Katib 탐색 전체 / 파라미터 조합 1회
- **InferenceService (ISVC)** : KServe 서빙 단위 CR
- **Istio CNI** : 특권 init 컨테이너 없이 사이드카 트래픽 가로채는 방식. PSS 호환

---

## 9. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 정체 | K8s 네이티브 AI 플랫폼 = 서브프로젝트 모음 |
| 레포 | kubeflow/kubeflow = 입구, community-distribution = 설치본, 개발은 서브프로젝트별 |
| 컴포넌트 | Spark Op, Notebooks, KFP, Trainer, Katib, Hub, KServe, Dashboard |
| 공통 서비스 | Istio(CNI), oauth2-proxy, Dex, cert-manager, Knative |
| 멀티테넌시 | Profile = ns + RBAC + Istio 정책 + 쿼터 |
| KFP | SDK → IR YAML → Argo Workflow → 단계 Pod, SeaweedFS + MLMD |
| 릴리스 | 연 2회 (26.03, 26.10), 6개월 지원 |
| 운영 포인트 | 폐쇄망 미러링, Cilium 설정, 외부 OIDC, 스토리지 교체, 업그레이드 수동 단계 |

**Kubeflow 는 "K8s 를 몰라도 되는 AI 플랫폼"을 목표로 하지만, 운영자는 K8s 를 제일 깊게 알아야 하는 플랫폼임.**

관련 글 : Ray 스터디, Kubeflow + MLflow 통합 스터디, Ray · Kubeflow · MLflow 비교
