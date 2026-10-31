## kind 실습 - Kubernetes v1.37 + kube-ops-view + metrics-server

> **목표** : 스터디 공유 실습(kind + kube-ops-view + metrics-server)을 최신 kind·Kubernetes 버전으로 그대로 따라 하고, 노드 자원 할당량 읽는 법까지 익히기

- 원본 : CloudNetastudy 공유 실습 (kind `kindest/node:v1.32.5` 기준)
- 이 페이지 기준 (2026-10) : kind **v0.33.0**, 노드 이미지 **`kindest/node:v1.37.0`**, kube-ops-view 차트 1.2.2, metrics-server 차트 3.14.0 (앱 v0.9.0), Helm v3
- 실습 파일 : `github.com/riverjin839/devopser` 의 `kind-lab/` (`verify.sh`)

---

## 1. 개요

스터디 실습 = kind 로 단일 노드 클러스터를 띄우고, 두 가지 관측 도구를 붙이는 구성.

- **kube-ops-view** : 노드·Pod 배치를 화면으로 보여주는 대시보드
- **metrics-server** : kubelet 에서 CPU·메모리 사용량을 모아 `kubectl top` 과 HPA 에 제공

<!-- diagram: mlpe-kind-01-arch.html -->

| 구성 | 실체 | 접근 |
|---|---|---|
| myk8s 노드 | `kindest/node:v1.37.0` 컨테이너 1개 (control-plane 겸 워커) | `kubectl --context kind-myk8s` |
| 포트 30000~30003 | `extraPortMappings` 로 호스트에 열어둔 NodePort 범위 | `localhost:3000x` |
| kube-ops-view | kube-system 의 Deployment + NodePort 30003 | 브라우저 |
| metrics-server | kube-system 의 Deployment, Metrics API 등록 | `kubectl top` |

- 30000~30002 는 이후 실습용으로 미리 열어둔 포트

**kind 노드 = Docker 컨테이너. 포트를 미리 열어둬야 NodePort 를 내 PC 에서 바로 접속 가능.**

---

## 2. 준비

| 항목 | 기준 | 확인 |
|---|---|---|
| Docker | Docker Desktop · OrbStack · colima. 메모리 4GB 이상 (단일 노드) | `docker info` |
| kind | v0.33.0 | `kind version` |
| kubectl | v1.36~1.38 (서버 ±1 마이너) | `kubectl version --client` |
| helm | v3 이상 | `helm version` |
| 포트 | 30000~30003 비어 있어야 함 | `lsof -i :30003` |

```bash
# macOS
brew install kind kubectl helm

# Linux (WSL2 Ubuntu 포함)
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.33.0/kind-linux-amd64 && chmod +x kind && sudo mv kind /usr/local/bin/
curl -LO https://dl.k8s.io/release/v1.37.2/bin/linux/amd64/kubectl && sudo install -m 0755 kubectl /usr/local/bin/
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

---

## 3. 실습

<!-- diagram: mlpe-kind-02-flow.html -->

### 3-1. kind k8s 배포

```bash
# kind k8s 배포 : 스터디 원본에서 이미지만 v1.32.5 → v1.37.0 으로 변경
kind create cluster --name myk8s --image kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5 --config - <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30000
    hostPort: 30000
  - containerPort: 30001
    hostPort: 30001
  - containerPort: 30002
    hostPort: 30002
  - containerPort: 30003
    hostPort: 30003
EOF

# 확인
kubectl get nodes -o wide                   # myk8s-control-plane Ready, VERSION v1.37.0
docker ps --format '{{.Names}}  {{.Ports}}' # 0.0.0.0:30000-30003->30000-30003/tcp
```

- `--image` 에 **태그 + `@sha256` digest** 를 같이 씀 → kind v0.33.0 릴리스 기본 이미지와 동일한 것 보장
- `--config -` + heredoc = 설정 파일 없이 표준 입력으로 넘기는 방식
- 노드 1대가 control-plane 이면서 워커 역할도 함 → kind 는 단일 노드에서도 Pod 스케줄됨

### 3-2. kube-ops-view

```bash
# kube-ops-view
helm repo add geek-cookbook https://geek-cookbook.github.io/charts/
helm install kube-ops-view geek-cookbook/kube-ops-view --version 1.2.2 --set service.main.type=NodePort,service.main.ports.http.nodePort=30003 --set env.TZ="Asia/Seoul" --namespace kube-system
kubectl get deploy,pod,svc,ep -n kube-system -l app.kubernetes.io/instance=kube-ops-view

# kube-ops-view 접속 URL 확인 (1.5 , 2 배율)
open "http://localhost:30003/#scale=1.5" # macOS
open "http://localhost:30003/#scale=2"   # macOS

echo "http://<Ubuntu 의 eth0 IP>:30003/#scale=1.5" # Windows WSL2(Ubuntu)
echo "http://<Ubuntu 의 eth0 IP>:30003/#scale=2"   # Windows WSL2(Ubuntu)
ip -4 addr show eth0 | grep inet                   # WSL2 eth0 IP 확인
```

- NodePort 를 30003 으로 고정 → 3-1 에서 열어둔 호스트 포트와 맞물림
- `#scale=1.5` = 화면 확대 배율. 노드·Pod 가 작게 보일 때 키움
- 차트 1.2.2 는 2022 년 이후 갱신 없음 (앱 20.4.0). 실습 시각화 용도로만 사용

> 주의 : Apple Silicon 에서 kube-ops-view 가 `ImagePullBackOff` 나 `exec format error` 로 안 뜨면 이미지가 arm64 를 지원하지 않는 경우임. 실습 진행에는 영향 없음. 3-3 부터 계속 진행 가능.

### 3-3. metrics-server

```bash
# metrics-server
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm install metrics-server metrics-server/metrics-server --version 3.14.0 --set 'args[0]=--kubelet-insecure-tls' -n kube-system
kubectl get all -n kube-system -l app.kubernetes.io/instance=metrics-server
kubectl get apiservices | grep -E '(AVAILABLE|metrics)'   # v1beta1.metrics.k8s.io ... True
```

- `--kubelet-insecure-tls` : kind 의 kubelet 인증서는 노드 IP 가 SAN 에 없어 검증 실패 → 실습에서만 검증 생략
- 스터디 원본은 차트 버전 미지정 → 여기선 `--version 3.14.0` 으로 고정 (재현성)
- `apiservices` 에서 `AVAILABLE True` 가 떠야 `kubectl top` 동작. 설치 직후 30~60초 걸림

> 주의 : 운영 클러스터에선 `--kubelet-insecure-tls` 쓰지 말 것. kubelet serving 인증서를 정식 CA 로 발급하는 게 정석.

### 3-4. 자원 사용량 확인

```bash
# 확인
kubectl top node
kubectl top pod -A --sort-by='cpu'
kubectl top pod -A --sort-by='memory'
```

- `top` = **실제 사용량** (metrics-server 가 15초 주기로 수집)
- `describe node` 의 Requests·Limits = **예약량** (스케줄러가 보는 값)
- 사용량 ≠ 예약량. 둘 차이가 크면 requests 를 과하게 잡은 것

### 3-5. 노드 자원 할당량 읽기

```bash
kubectl describe node
```

스터디 공유 출력 예시 (v1.32.5 기준. v1.37 에서도 항목 구성은 같고 Pod 이름·수치만 다름)

```
## 해당 노드에서 실행한 파드들의 자원 할당량
Non-terminated Pods:          (11 in total)
  Namespace                   Name                                           CPU Requests  CPU Limits  Memory Requests  Memory Limits  Age
  ---------                   ----                                           ------------  ----------  ---------------  -------------  ---
  kube-system                 coredns-7db6d8ff4d-bjssc                       100m (2%)     0 (0%)      70Mi (0%)        170Mi (1%)     37m
  kube-system                 coredns-7db6d8ff4d-zbncd                       100m (2%)     0 (0%)      70Mi (0%)        170Mi (1%)     37m
  kube-system                 etcd-myk8s-control-plane                       100m (2%)     0 (0%)      100Mi (0%)       0 (0%)         37m
  kube-system                 kindnet-95vz7                                  100m (2%)     100m (2%)   50Mi (0%)        50Mi (0%)      37m
  kube-system                 kube-apiserver-myk8s-control-plane             250m (6%)     0 (0%)      0 (0%)           0 (0%)         37m
  kube-system                 kube-controller-manager-myk8s-control-plane    200m (5%)     0 (0%)      0 (0%)           0 (0%)         37m
  kube-system                 kube-ops-view-7dc76bf4dc-p7dzs                 300m (7%)     300m (7%)   500Mi (3%)       500Mi (3%)     4m13s
  kube-system                 kube-proxy-g6wk6                               0 (0%)        0 (0%)      0 (0%)           0 (0%)         37m
  kube-system                 kube-scheduler-myk8s-control-plane             100m (2%)     0 (0%)      0 (0%)           0 (0%)         37m
  kube-system                 metrics-server-66855dcc7c-tgl8v                100m (2%)     0 (0%)      200Mi (1%)       0 (0%)         34s
  local-path-storage          local-path-provisioner-988d74bc-fpjpk          0 (0%)        0 (0%)      0 (0%)           0 (0%)         37m

## 해당 노드에서 실행 중인 파드들의 자원 할당량 총합
Allocated resources:
  (Total limits may be over 100 percent, i.e., overcommitted.)
  Resource           Requests     Limits
  --------           --------     ------
  cpu                1350m (33%)  400m (10%)
  memory             990Mi (6%)   890Mi (5%)
```

읽는 법

| 항목 | 의미 | 예시에서 |
|---|---|---|
| CPU Requests | 스케줄러가 예약하는 최소 CPU. 합이 노드 용량을 넘으면 새 Pod 못 올라감 | 1350m = 1.35 코어 예약 |
| CPU Limits | 넘으면 스로틀링 되는 상한 | 400m. limit 없는 Pod 가 많아서 작음 |
| Memory Requests | 예약 메모리 | 990Mi |
| Memory Limits | 넘으면 OOMKilled | 890Mi. requests 보다 작은 건 limit 없는 Pod 가 많아서 |
| 괄호 % | 노드 Allocatable 대비 비율 | 1350m = 33% → 노드 CPU 약 4코어 |
| `0 (0%)` limit | 상한 없음 = 노드 여유만큼 사용 가능 | apiserver, etcd 등 |

- **Requests 합 = 스케줄링 기준**, **Limits 합 = 과다 할당(overcommit) 여부**. limits 합은 100% 넘어도 됨
- QoS 클래스 : requests = limits 인 Pod 는 Guaranteed (예 : kube-ops-view, kindnet), 일부만 있으면 Burstable, 둘 다 없으면 BestEffort (kube-proxy)
- 메모리 부족 시 BestEffort → Burstable → Guaranteed 순으로 먼저 쫓겨남

### 3-6. 삭제

```bash
kind delete cluster --name myk8s
```

### 3-7. 자동 검증 스크립트

```bash
git clone -b mlpe-study-diagrams https://github.com/riverjin839/devopser.git
cd devopser/kind-lab && ./verify.sh          # --keep 붙이면 클러스터 남김
```

- 순서 : 도구 확인 → kind 배포(v1.37.0 확인) → helm repo → kube-ops-view(30003 응답 200) → metrics-server → `kubectl top` 대기(최대 2분) → describe node → 삭제
- 정상이면 `[PASS]` 9줄 + `kubectl top` 결과 + Allocated resources 가 출력됨

---

## 4. 폐쇄망에서 할 때

<!-- diagram: mlpe-kind-03-airgap.html -->

반입 목록

| 종류 | 대상 |
|---|---|
| 노드 이미지 | `kindest/node:v1.37.0@sha256:a1ed56cf…` |
| 앱 이미지 | kube-ops-view, metrics-server(`registry.k8s.io/metrics-server/metrics-server:v0.9.0`) |
| 차트 | `helm pull geek-cookbook/kube-ops-view --version 1.2.2`, `helm pull metrics-server/metrics-server --version 3.14.0` → tgz |

```bash
# 인터넷 PC : 이미지·차트 확보
docker pull kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
docker save kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5 | gzip > kind-node-v1.37.0.tar.gz
helm pull metrics-server/metrics-server --version 3.14.0

# 폐쇄망 PC
docker load -i kind-node-v1.37.0.tar.gz
kind load docker-image registry.k8s.io/metrics-server/metrics-server:v0.9.0 --name myk8s   # 앱 이미지는 노드에 직접 적재
helm install metrics-server ./metrics-server-3.14.0.tgz --set 'args[0]=--kubelet-insecure-tls' -n kube-system
```

- dmz-nexus 같은 Docker Hub·Helm 프록시가 있으면 반입 없이 `helm repo add` 주소만 Nexus 로 바꿔서 그대로 진행 가능

---

## 5. 검증 결과

| 검증 항목 | 방법 | 결과 |
|---|---|---|
| kind 최신 버전 | GitHub 태그 + 바이너리 실행 | v0.33.0 확인 |
| 노드 이미지 | kind v0.33.0 소스의 기본 이미지 값 | `kindest/node:v1.37.0@sha256:a1ed56cf…` 확인 |
| 클러스터 설정 | `kind create cluster --config -` 파싱 | 통과 (이미지 pull 단계까지 진행) |
| 차트 버전 | 차트 저장소 index.yaml (GitHub gh-pages) | kube-ops-view 1.2.2, metrics-server 3.14.0 존재 확인 |
| verify.sh | bash 문법 + shellcheck | 경고 0 |
| **실제 클러스터 기동** | `kind create cluster` | **미검증** : 작업 환경에서 Docker Hub 접근이 막혀 노드 이미지 pull 에서 중단 |

> 주의 : 최종 확인은 Mac 에서 `./verify.sh` 한 번이면 끝남. `[PASS]` 9줄이 나오면 이 페이지 전체가 검증된 것. 결과를 받으면 이 표를 실제 결과로 바꿀 예정.

---

## 6. 자주 막히는 곳

| 증상 | 원인 | 조치 |
|---|---|---|
| `error: Metrics API not available` | metrics-server 기동 직후 | 30~60초 대기 후 재시도 |
| metrics-server 로그에 `x509: cannot validate certificate` | kubelet 인증서 검증 | `--kubelet-insecure-tls` 확인 |
| `localhost:30003` 접속 안 됨 | 포트 매핑 누락, NodePort 번호 불일치 | `docker ps` 포트, `kubectl get svc -n kube-system` 확인 |
| WSL2 에서 localhost 안 됨 | WSL 네트워크 모드 | eth0 IP 로 접속 |
| kube-ops-view `ImagePullBackOff` | 이미지 아키텍처 (arm64) 또는 외부 접근 불가 | 3-2 주의 참고, 폐쇄망은 4장 |
| `port is already allocated` | 30000~30003 사용 중 | 기존 클러스터 `kind delete`, 점유 프로세스 종료 |

---

## 7. 용어 정리

- **kind(Kubernetes IN Docker)** : Docker 컨테이너를 노드로 쓰는 로컬 K8s 도구
- **extraPortMappings** : 호스트 포트를 kind 노드 컨테이너 포트로 연결하는 설정
- **NodePort** : 노드의 30000~32767 포트로 Service 를 여는 방식
- **kube-ops-view** : 클러스터 노드·Pod 배치를 시각화하는 대시보드
- **metrics-server** : kubelet 의 CPU·메모리 지표를 모아 Metrics API 로 제공
- **Metrics API** : `metrics.k8s.io` API 그룹. `kubectl top`, HPA 가 사용
- **Requests / Limits** : 스케줄 예약량 / 사용 상한
- **Allocatable** : 노드 전체 자원에서 시스템 예약분을 뺀, Pod 에 줄 수 있는 양
- **overcommit** : Limits 합이 노드 용량을 넘는 상태
- **QoS 클래스** : Guaranteed · Burstable · BestEffort. 자원 부족 시 축출 순서 결정

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 버전 | kind v0.33.0, 노드 v1.37.0 (digest 고정), metrics-server 차트 3.14.0 |
| 클러스터 | 단일 노드 myk8s, 30000~30003 포트를 호스트에 개방 |
| kube-ops-view | helm 설치, NodePort 30003, 브라우저로 배치 확인 |
| metrics-server | `--kubelet-insecure-tls` (실습 한정), Metrics API 등록 |
| top vs describe | top = 실제 사용량, describe = Requests·Limits 예약량 |
| 할당량 해석 | Requests 합 = 스케줄 기준, Limits 합 = overcommit, % = Allocatable 대비 |
| 검증 | 버전·설정·차트·스크립트 확인 완료, 실제 기동은 verify.sh 로 확인 필요 |

**kind 로 띄운 단일 노드에 metrics-server 를 붙이면, 실제 사용량(top)과 예약량(describe)을 나란히 비교하며 자원 설계를 연습할 수 있음.**

관련 글 : CH3. Building applications on Kubernetes
