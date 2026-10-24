## Kubeflow + MLflow 통합 스터디 - kubeflow/mlflow-integration

> **목표** : Kubeflow 구성 파악, MLflow 를 Kubeflow 실험 추적으로 붙이는 mlflow-integration 구조와 사용법 이해

- 출처 : github.com/kubeflow/mlflow-integration, kubeflow.org 릴리스 노트
- 기준 버전 : Kubeflow 26.03.1, mlflow-integration v2.1.0 (2026-10-16), MLflow 3.17
- 관련 제안 : KEP-897 - MLflow 를 Kubeflow 기본 실험 추적 도구로

---

## 1. 개요

Kubeflow = K8s 위에 ML 수명주기 도구를 모아둔 플랫폼.

- 노트북 → 파이프라인 → 학습 → 튜닝 → 레지스트리 → 서빙까지 단계별 컴포넌트 제공
- 멀티테넌시는 Profile(네임스페이스 + Istio + RBAC)로 해결
- 빠진 조각 = **실험 추적**. 기존 KFP 메타데이터는 run 단위 비교·시각화가 약함

그래서 나온 게 mlflow-integration.

- MLflow 서버를 Kubeflow 멀티테넌시 규칙(네임스페이스, RBAC)에 맞춰 돌리게 해주는 플러그인 묶음
- MLflow 자체를 고치는 게 아니라 **플러그인 2개 + CRD 1개 + Helm 차트**

**Kubeflow 는 판을 깔고, MLflow 는 기록을 남기고, mlflow-integration 은 둘 사이 권한을 맞춤.**

---

## 2. Kubeflow 개념 정리

### 2-1. 구성요소 (26.03.1 기준)

<!-- diagram: mlpe-kf-01-components.html -->

| 컴포넌트 | 역할 | 버전 |
|---|---|---|
| Pipelines (KFP) | ML 워크플로 DAG, 캐싱, 재실행 | v2.16 |
| Notebooks | Jupyter·VS Code 서버. v2 는 CRD 기반 재설계 (alpha) | v1.11 |
| Trainer | TrainJob 으로 PyTorch·JAX·MPI 분산 학습. 구 Training Operator 후속 | v2.2 |
| Katib | 하이퍼파라미터 튜닝, NAS | v0.19 |
| Spark Operator | K8s 위 Spark 잡 | v2.5 |
| Hub | 구 Model Registry. Model Catalog, MCP Catalog 추가 | v0.3.x |
| KServe | 모델 서빙. LLMInferenceService 로 멀티노드 LLM 추론 | v0.16~0.18 |
| Kubeflow SDK | 파이프라인·학습·Spark 를 한 파이썬 SDK 로 | v0.3 |

- K8s 1.34 이상에서 검증
- Pod Security Standards Restricted 대응, 멀티테넌트 기본값 강화
- Kale 2.0 : 노트북 셀 주석만으로 KFP v2 파이프라인 생성

### 2-2. 멀티테넌시 - Profile

- Profile 1개 = 네임스페이스 1개 + 소유자 + 기여자 RoleBinding
- Istio AuthorizationPolicy 로 네임스페이스 간 트래픽 차단
- 사용자 식별은 Dex/oauth2-proxy → `kubeflow-userid` 류 헤더로 전달

MLflow 도 이 규칙을 그대로 따라야 Kubeflow 안에서 쓸 수 있음 → mlflow-integration 의 존재 이유.

---

## 3. mlflow-integration 구조

### 3-1. 구성 3가지

| 구성 | MLflow 훅 | 하는 일 |
|---|---|---|
| Workspace Provider (`kubernetes`) | `mlflow.workspace_provider` | K8s 네임스페이스 = MLflow 워크스페이스 1:1 매핑 |
| Authorization Plugin (`kubernetes-auth`) | `mlflow.app` | 모든 MLflow 요청을 K8s RBAC 로 검사 |
| MLflowConfig CRD | - | 네임스페이스별 아티팩트 저장 위치 덮어쓰기 |

- PyPI 패키지 `mlflow-kubernetes-plugins` 설치만 하면 entry point 로 자동 로드
- MLflow 3.17 이상 필요 (MLflow 워크스페이스 기능 위에서 동작)

### 3-2. 요청 흐름

<!-- diagram: mlpe-kf-02-mlflow-auth.html -->

1. 사용자·노트북이 토큰 + 워크스페이스(`X-MLFLOW-WORKSPACE: team-a`)로 요청
2. Istio·oauth2-proxy 가 사용자 인증 → `x-remote-user`, `x-remote-groups` 헤더 추가
3. `kubernetes-auth` 가 요청을 가로채 MLflow 작업 → K8s 가상 리소스로 변환
4. K8s API 에 SubjectAccessReview 질의 → 허용이면 통과
5. 목록 응답은 볼 수 있는 것만 남기고 필터링

### 3-3. Workspace Provider

- 네임스페이스 목록을 워크스페이스로 노출. 백그라운드 watch 로 캐시 유지
- `kube-*`, `openshift-*` 같은 시스템 ns 자동 제외
- `MLFLOW_K8S_WORKSPACE_LABEL_SELECTOR` 로 대상 ns 한정 (예 : `mlflow-enabled=true`)
- ns 어노테이션 `mlflow.kubeflow.org/workspace-description` → 워크스페이스 설명
- 워크스페이스 생성·삭제는 MLflow 에서 막힘. **ns 관리는 K8s 몫**

### 3-4. Authorization Plugin

인증 모드 2가지

- **SelfSubjectAccessReview (기본)** : 호출자 토큰 그대로 K8s 에 "나 이거 돼?" 질의. 토큰 직접 받는 구조용
- **SubjectAccessReview** : 앞단 프록시가 넘긴 사용자·그룹 헤더를 믿고 서버가 대신 질의. Kubeflow(Istio + oauth2-proxy) 구조용

RBAC 리소스 = API 그룹 `mlflow.kubeflow.org` 의 가상 리소스

| 리소스 | 의미 |
|---|---|
| `experiments` | 실험, run, trace, 아티팩트 |
| `registeredmodels` | 등록 모델, 버전 |
| `datasets` | 평가 데이터셋 |
| `gatewayendpoints`, `gatewaysecrets` | AI Gateway 엔드포인트·키. 사용은 `/use` 서브리소스 |
| `mcpservers`, `skills`, `assistants` | MCP·스킬 레지스트리 |

- `resourceNames` 로 실험 이름 단위 권한 가능 (예 : `exp-a`, `exp-b` 만 수정)
- 단, 이름 기준임. ID 아님
- 인증된 사용자를 run owner 로 강제 기록 → 누가 돌렸는지 위조 불가
- 권한 매핑 없는 MLflow 엔드포인트가 있으면 **서버 기동 실패** → 신규 API 가 무방비로 열리는 일 방지

### 3-5. MLflowConfig CRD

- 네임스페이스마다 아티팩트 버킷·경로 따로 지정
- `metadata.name: mlflow`, `spec.artifactRootSecret: mlflow-artifact-connection` 고정
- `spec.artifactRootPath` 만 팀이 정함
- 팀별 MinIO 버킷 분리할 때 서버 재기동 없이 처리

---

## 4. 사용법 예시

### 4-1. Helm 설치

```bash
export VERSION=v2.1.0
helm upgrade --install mlflow oci://ghcr.io/kubeflow/charts/mlflow \
  --version "${VERSION#v}" \
  --namespace mlflow --create-namespace \
  --set-string image.tag="$VERSION" \
  -f values-kubeflow.yaml
```

Kubeflow 멀티유저용 values 핵심

```yaml
mlflow:
  backendStoreUri: "postgresql://mlflow:***@pg.mlflow.svc:5432/mlflow"
  artifactsDestination: "s3://mlflow-artifacts"
  authorizationMode: subject_access_review   # 프록시 헤더 신뢰
  staticPrefix: /mlflow                       # Kubeflow 대시보드 하위 경로
env:
  - name: MLFLOW_K8S_AUTH_REMOTE_USER_HEADER
    value: x-auth-request-email
  - name: MLFLOW_K8S_AUTH_REMOTE_GROUPS_HEADER
    value: x-auth-request-groups
  - name: MLFLOW_K8S_WORKSPACE_LABEL_SELECTOR
    value: "mlflow-enabled=true"
istio:
  enabled: true
  virtualService:
    enabled: true
    gateways: [kubeflow-gateway]
  authorizationPolicy:
    enabled: true
networkPolicy:
  enabled: true
```

> 주의 : 차트 기본값은 SQLite + 로컬 파일. 운영은 PostgreSQL + 오브젝트 스토리지로 바꿀 것. SQLite 로는 레플리카 늘리기 불가.

### 4-2. 팀 네임스페이스 열기

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: team-a
  labels:
    mlflow-enabled: "true"              # 워크스페이스로 노출
  annotations:
    mlflow.kubeflow.org/workspace-description: "Team A"
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: mlflow-editor
  namespace: team-a
rules:
  - apiGroups: ["mlflow.kubeflow.org"]
    resources: ["experiments", "registeredmodels", "datasets"]
    verbs: ["get", "list", "create", "update", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: mlflow-editor
  namespace: team-a
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: mlflow-editor}
subjects:
  - kind: Group
    name: team-a-members
    apiGroup: rbac.authorization.k8s.io
```

### 4-3. 클라이언트에서 기록

```python
import mlflow

mlflow.set_tracking_uri("http://mlflow.mlflow.svc:5000")
mlflow.set_workspace("team-a")          # 또는 MLFLOW_WORKSPACE=team-a
mlflow.set_experiment("fraud-detect")

with mlflow.start_run():
    mlflow.log_params({"lr": 1e-3, "epochs": 10})
    mlflow.log_metric("auc", 0.91)
    mlflow.sklearn.log_model(model, name="model",
                             registered_model_name="fraud-detect")
```

```bash
# 서비스어카운트 토큰으로 직접 호출 (SSAR 모드)
TOKEN=$(kubectl -n team-a create token mlflow-writer)
curl -H "Authorization: Bearer ${TOKEN}" \
     -H "X-MLFLOW-WORKSPACE: team-a" \
     http://mlflow.example/api/2.0/mlflow/experiments/search
```

### 4-4. 파이프라인에 붙이기

<!-- diagram: mlpe-kf-03-pipeline-mlflow.html -->

- KFP 컴포넌트 안에서 `mlflow` 로그 → 파이프라인 run 과 MLflow run 을 태그로 연결 (`kfp_run_id`)
- 학습은 TrainJob 이든 RayJob 이든 상관없음. 기록 대상만 MLflow
- 서빙은 KServe 가 `models:/fraud-detect@champion` 위치의 모델을 받아감

---

## 5. 실무에서 확인

- **네임스페이스 모델 그대로 재사용** : 사용자별 네임스페이스 운영 구조 = MLflow 워크스페이스 구조. 신규 권한 체계 안 만들어도 됨
- **SAR 부하** : 요청마다 SubjectAccessReview 호출. 기본 300초 캐시(`MLFLOW_K8S_AUTH_CACHE_TTL_SECONDS`). 1,000명 규모면 API 서버 부하 모니터링 필요
- **watch 범위** : provider 가 전체 ns 를 list·watch 함. 라벨 셀렉터로 대상 좁힐 것
- **인증 경로** : Kubeflow 없이 쓰면 SSAR 모드 + SA 토큰. Keycloak·oauth2-proxy 앞단이면 SAR 모드 + 헤더. 헤더 위조 막으려면 MLflow 직접 접근 차단(NetworkPolicy) 필수
- **아티팩트** : MinIO 버킷을 팀별로 나누면 MLflowConfig CRD + 팀 ns 의 `mlflow-artifact-connection` 시크릿 사용
- **폐쇄망** : 차트는 `ghcr.io` OCI, 이미지 `ghcr.io/kubeflow/mlflow-integration`. 내부 레지스트리로 미러링

> 주의 : MLflow 버전 고정 범위가 좁음 (v2.1.0 = MLflow 3.17.x). MLflow 만 따로 올리면 플러그인 로드 실패. 둘을 같이 올릴 것.

> 주의 : Kubeflow SDK 쪽 MLflow 연동은 아직 계획 단계. 지금은 사용자가 코드에서 직접 `mlflow` 호출하는 방식.

---

## 6. 용어 정리

- **Profile** : Kubeflow 멀티테넌시 단위. 네임스페이스 + 소유자 + 권한
- **KFP(Kubeflow Pipelines)** : 컨테이너 단계를 DAG 로 묶는 워크플로 엔진
- **TrainJob** : Kubeflow Trainer v2 의 분산 학습 CRD
- **Hub** : Kubeflow 모델·MCP 카탈로그. 구 Model Registry
- **KEP(Kubeflow Enhancement Proposal)** : Kubeflow 기능 제안 문서
- **MLflow 워크스페이스(workspace)** : MLflow 서버 안의 격리 단위. 실험·모델을 나눔
- **Workspace Provider** : 워크스페이스 목록을 외부(여기선 K8s ns)에서 가져오는 플러그인
- **SAR(SubjectAccessReview)** : "이 사용자가 이 작업 가능?"을 K8s 에 묻는 API
- **SSAR(SelfSubjectAccessReview)** : 호출자 자기 토큰으로 묻는 SAR
- **MLflowConfig** : 네임스페이스별 아티팩트 위치 지정 CRD

---

## 7. 한 장 요약

| 항목 | 핵심 |
|---|---|
| Kubeflow | K8s 위 ML 플랫폼. KFP, Notebooks, Trainer, Katib, Hub, KServe |
| 빈 자리 | 실험 추적 → KEP-897 로 MLflow 채택 |
| mlflow-integration | Workspace Provider + kubernetes-auth + MLflowConfig CRD + Helm 차트 |
| 매핑 | 네임스페이스 = 워크스페이스, K8s RBAC = MLflow 권한 |
| 인증 | SSAR(토큰 직접) / SAR(프록시 헤더) |
| 세밀 권한 | `resourceNames` 로 실험·모델 이름 단위 |
| 운영 | PostgreSQL + MinIO, SAR 캐시, 라벨 셀렉터, 버전 동시 업그레이드 |

**mlflow-integration 은 MLflow 를 Kubeflow 네임스페이스·RBAC 체계에 그대로 끼워 넣는 어댑터임.**

다음 글 : MLflow 스터디 - 실험 추적, 모델 레지스트리, GenAI 기능
