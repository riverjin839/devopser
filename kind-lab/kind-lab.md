## kind 실습 - 최신 Kubernetes v1.37 로컬 클러스터

> **목표** : kind 최신 버전으로 멀티노드 K8s v1.37 클러스터를 띄우고, 레지스트리 없이 앱 이미지를 넣어 배포·접속·검증까지 한 번에 해보기

- 출처 : github.com/kubernetes-sigs/kind (v0.33.0 소스·문서), kind.sigs.k8s.io
- 기준 버전 (2026-10) : kind **v0.33.0**, 노드 이미지 `kindest/node:v1.37.0` (v0.33.0 기본값), kubectl v1.37.x
- 실습 파일 : `github.com/riverjin839/devopser` 의 `kind-lab/` (설정, 앱, 검증 스크립트)

---

## 1. 개요

kind(Kubernetes IN Docker) = **Docker 컨테이너 하나를 K8s 노드 하나로 쓰는** 로컬 클러스터 도구.

- 원래 K8s 자체 테스트용으로 만든 도구 → 업스트림 최신 버전이 제일 빨리 올라옴
- VM 없이 노드 여러 대, 멀티 control-plane(HA) 까지 가능
- 노드 이미지 `kindest/node` 안에 kubelet, kubeadm, containerd, 기본 이미지가 다 들어 있음

<!-- diagram: mlpe-kind-01-arch.html -->

| 구성 | 실체 | 역할 |
|---|---|---|
| kind CLI | 단일 바이너리 | 노드 컨테이너 생성·삭제, 이미지 적재 |
| 노드 | `kindest/node` 컨테이너 | 안에서 systemd + containerd + kubelet 실행 |
| control-plane | 노드 컨테이너 1개 | kubeadm 으로 API 서버·etcd·스케줄러 기동 |
| CNI | kindnet | 기본 Pod 네트워크 |
| 스토리지 | local-path-provisioner | 기본 StorageClass |
| 포트 | `extraPortMappings` | 호스트 포트 → 노드 컨테이너 포트 |

**kind 노드 = 컨테이너. 그래서 클러스터 생성·삭제가 1~2분이면 끝남.**

---

## 2. 준비

| 항목 | 기준 | 확인 |
|---|---|---|
| Docker | 메모리 8GB 이상 할당 (노드 3대 기준) | `docker info` |
| cgroup | v2 권장. v1 은 kind 가 경고하고 다음 버전에서 지원 종료 예정 | `stat -fc %T /sys/fs/cgroup` → `cgroup2fs` |
| inotify (Linux) | 노드 여러 대면 한도 부족 → too many open files | 아래 sysctl |
| 포트 | 8080 비어 있어야 함 | `ss -ltn \| grep 8080` |

```bash
# Linux : 멀티노드에서 자주 터지는 inotify 한도 올리기
sudo sysctl fs.inotify.max_user_watches=524288
sudo sysctl fs.inotify.max_user_instances=512
```

### 2-1. 설치

```bash
# kind v0.33.0 (Linux amd64)
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.33.0/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind

# kubectl v1.37 (서버 버전 ±1 마이너 안에서 사용)
curl -LO https://dl.k8s.io/release/v1.37.2/bin/linux/amd64/kubectl
sudo install -m 0755 kubectl /usr/local/bin/kubectl

# macOS 는 brew
brew install kind kubectl

kind version          # kind v0.33.0 ...
```

---

## 3. 실습

<!-- diagram: mlpe-kind-02-flow.html -->

### 3-1. 클러스터 설정

```yaml
# kind-lab.yaml : control-plane 1 + worker 2, Kubernetes v1.37.0
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: lab
nodes:
- role: control-plane
  image: kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
  extraPortMappings:
  - containerPort: 30080      # NodePort
    hostPort: 8080            # 내 PC localhost:8080
- role: worker
  image: kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
- role: worker
  image: kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
containerdConfigPatches:      # 사내 미러 쓰려면 certs.d 방식 활성화 (5장)
- |-
  [plugins."io.containerd.grpc.v1.cri".registry]
    config_path = "/etc/containerd/certs.d"
```

- 노드 이미지는 **태그 + `@sha256` digest** 로 고정 → kind 릴리스 노트에 적힌 값 그대로
- 다른 K8s 버전이 필요하면 같은 kind 릴리스 노트의 다른 `kindest/node` 이미지로 교체

### 3-2. 생성·확인

```bash
kind create cluster --config kind-lab.yaml --wait 3m
kubectl cluster-info --context kind-lab
kubectl get nodes -o wide          # 3대 Ready, VERSION v1.37.0
kind get clusters                  # lab
```

### 3-3. 앱 이미지 만들고 넣기

```python
# server.py : 어느 Pod·노드가 응답했는지 출력하는 최소 웹 서버
import http.server, os, socket

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"hello from {socket.gethostname()} ({os.environ.get('NODE_NAME', '-')})\n".encode()
        self.send_response(200); self.send_header("Content-Type", "text/plain")
        self.end_headers(); self.wfile.write(body)

http.server.HTTPServer(("", 8080), H).serve_forever()
```

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY server.py .
CMD ["python", "server.py"]
```

```bash
docker build -t hello-lab:0.1 .
kind load docker-image hello-lab:0.1 --name lab      # 레지스트리 없이 모든 노드에 적재
```

- `kind load` = 내 PC 이미지를 노드 컨테이너 안 containerd 로 복사
- 그래서 매니페스트에 `imagePullPolicy: IfNotPresent` 필수. `latest` 태그면 기본값이 Always 라 외부로 pull 하러 감 → 실패

### 3-4. 배포·접속

```yaml
# app.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hello
  labels: {app: hello}
spec:
  replicas: 3
  selector:
    matchLabels: {app: hello}
  template:
    metadata:
      labels: {app: hello}
    spec:
      containers:
      - name: hello
        image: hello-lab:0.1
        imagePullPolicy: IfNotPresent
        env:
        - name: NODE_NAME             # 어느 노드에서 응답했는지 표시
          valueFrom:
            fieldRef: {fieldPath: spec.nodeName}
        ports:
        - containerPort: 8080
        readinessProbe:
          httpGet: {path: /, port: 8080}
        resources:
          requests: {cpu: 50m, memory: 32Mi}
          limits: {memory: 64Mi}
---
apiVersion: v1
kind: Service
metadata:
  name: hello
spec:
  type: NodePort
  selector: {app: hello}
  ports:
  - port: 80
    targetPort: 8080
    nodePort: 30080
```

```bash
kubectl apply -f app.yaml
kubectl rollout status deploy/hello
kubectl get pods -o wide                      # worker 두 대에 분산
for i in $(seq 6); do curl -s localhost:8080; done
# hello from hello-xxxx (lab-worker) / hello from hello-yyyy (lab-worker2) ... 섞여서 나와야 정상
```

흐름 : localhost:8080 → control-plane 컨테이너 30080 (extraPortMappings) → NodePort Service → Pod 3개 중 하나.

### 3-5. 자동 검증 스크립트

```bash
#!/usr/bin/env bash
# verify.sh : 클러스터 생성 → 이미지 적재 → 배포 → 접속 → 삭제
# usage: ./verify.sh [--keep]   (--keep 이면 클러스터 남김)
set -euo pipefail
NAME=lab
CTX="kind-${NAME}"
pass() { echo "[PASS] $*"; }
fail() { echo "[FAIL] $*"; exit 1; }

if kind version | grep -q "v0.33"; then pass "kind $(kind version | awk '{print $2}')"; else fail "kind v0.33.x 아님"; fi

if ! kind get clusters | grep -qx "${NAME}"; then
  kind create cluster --config kind-lab.yaml --wait 3m
fi

nodes=$(kubectl --context "${CTX}" get nodes --no-headers | wc -l)
if [ "${nodes}" -eq 3 ]; then pass "노드 3대"; else fail "노드 ${nodes}대"; fi

ver=$(kubectl --context "${CTX}" get nodes -o jsonpath='{.items[*].status.nodeInfo.kubeletVersion}')
if echo "${ver}" | grep -q "v1.37.0"; then pass "kubelet ${ver%% *}"; else fail "버전 ${ver}"; fi

kubectl --context "${CTX}" wait --for=condition=Ready nodes --all --timeout=180s >/dev/null
pass "전 노드 Ready"

docker build -q -t hello-lab:0.1 . >/dev/null
pass "이미지 빌드 hello-lab:0.1"
kind load docker-image hello-lab:0.1 --name "${NAME}" >/dev/null
pass "kind load : 레지스트리 없이 노드에 적재"

kubectl --context "${CTX}" apply -f app.yaml >/dev/null
kubectl --context "${CTX}" rollout status deploy/hello --timeout=120s >/dev/null
pass "Deployment hello 3/3"

for _ in 1 2 3 4 5 6; do curl -s localhost:8080; done | sort | uniq -c
pods=$(for _ in $(seq 1 20); do curl -s localhost:8080; done | sort -u | wc -l)
if [ "${pods}" -ge 2 ]; then pass "localhost:8080 → NodePort 30080 → Pod ${pods}개로 분산"; else fail "접속 실패"; fi

if [ "${1:-}" != "--keep" ]; then
  kind delete cluster --name "${NAME}" >/dev/null
  pass "클러스터 삭제"
fi
```

- 정상이면 `[PASS]` 9줄 + Pod 별 응답 횟수가 나옴. 하나라도 `[FAIL]` 이면 그 단계에서 멈춤

### 3-6. 정리·로그

```bash
kind export logs ./kind-logs --name lab   # 문제 생기면 노드 로그 통째로 수집
kind delete cluster --name lab
```

---

## 4. 폐쇄망에서 kind 쓰기

<!-- diagram: mlpe-kind-03-airgap.html -->

노드 이미지 반입

```bash
# 인터넷 되는 PC
docker pull kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
docker save kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5 | gzip > kind-node-v1.37.0.tar.gz

# 폐쇄망 PC
docker load -i kind-node-v1.37.0.tar.gz
docker image tag <로드된 이미지 ID> kindest/node:v1.37.0
kind create cluster --config kind-airgap.yaml
```

앱 이미지는 사내 Nexus 미러로

```yaml
# kind-airgap.yaml : 노드에 certs.d 마운트
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: lab
nodes:
- role: control-plane
  image: kindest/node:v1.37.0
  extraMounts:
  - hostPath: ./certs.d
    containerPath: /etc/containerd/certs.d
- role: worker
  image: kindest/node:v1.37.0
  extraMounts:
  - hostPath: ./certs.d
    containerPath: /etc/containerd/certs.d
containerdConfigPatches:
- |-
  [plugins."io.containerd.grpc.v1.cri".registry]
    config_path = "/etc/containerd/certs.d"
```

```toml
# certs.d/docker.io/hosts.toml : docker.io 요청을 Nexus 프록시로
server = "https://registry-1.docker.io"

[host."https://nexus.internal:8443"]
  capabilities = ["pull", "resolve"]
  skip_verify = true          # 사내 CA 를 노드에 넣었으면 false + ca 지정
```

- dmz-nexus 처럼 Docker Hub 프록시가 이미 있으면 노드 이미지도 `nexus.internal:8443/kindest/node:...` 로 바로 pull 가능 → 반입 단계 생략
- 사내 CA 는 노드 컨테이너 안에도 있어야 함 → `extraMounts` 로 CA 파일 마운트하거나 `skip_verify` 로 실습만

---

## 5. 검증 결과

이 페이지 내용을 클라우드 작업 환경에서 실제로 돌려본 결과임.

| 검증 항목 | 방법 | 결과 |
|---|---|---|
| kind 최신 버전 | GitHub 태그 조회 + 바이너리 실행 | v0.33.0 (go1.26.7) 동작 확인 |
| 기본 노드 이미지 | kind v0.33.0 소스 `pkg/apis/config/defaults/image.go` | `kindest/node:v1.37.0@sha256:a1ed56cf…` 확인 |
| 클러스터 설정 문법 | `kind create cluster --config` 파싱 | kind-lab.yaml, kind-airgap.yaml 통과. 잘못된 role 은 즉시 거부되는 것까지 확인 |
| 매니페스트 | K8s 1.37.0 strict 스키마 검증 | Deployment·Service 통과. 타입 틀린 nodePort 는 거부 확인 |
| hosts.toml | TOML 파서 | 정상 |
| 앱 서버 | 로컬 실행 후 curl | `hello from ...` 200 응답 |
| verify.sh | bash 문법 + shellcheck + 도구 모의 실행 | 경고 0, 9단계 흐름 정상 |
| **실제 클러스터 기동** | `kind create cluster` | **미검증** : 작업 환경에서 Docker Hub(`registry-1.docker.io`) 접근이 막혀 노드 이미지 pull 단계에서 중단 |

> 주의 : 실제 기동 확인은 Docker Hub 또는 Nexus 프록시에 접근되는 PC 에서 `./verify.sh` 한 번 돌리면 끝남. `[PASS]` 9줄이 나오면 이 페이지 전체가 검증된 것.

- 작업 환경에서 cgroup v1 경고(`cgroup v1 is deprecated ...`)도 확인됨 → 실습 PC 는 cgroup v2 권장

---

## 6. 자주 막히는 곳

| 증상 | 원인 | 조치 |
|---|---|---|
| `too many open files`, kube-proxy 재시작 반복 | inotify 한도 | 2장 sysctl |
| `ImagePullBackOff` (hello-lab) | `kind load` 안 함 또는 `latest` 태그 + Always | `kind load` 후 `imagePullPolicy: IfNotPresent` |
| `curl localhost:8080` 응답 없음 | 포트 충돌, extraPortMappings 누락 | `docker ps` 로 `0.0.0.0:8080->30080` 확인 |
| 노드 NotReady 오래 감 | Docker 메모리 부족 | Docker 메모리 8GB 이상 |
| `failed to pull image kindest/node` | 외부 접근 불가 | 4장 반입 또는 Nexus 프록시 |
| kubectl 경고·오동작 | 클라이언트·서버 버전 차 큼 | kubectl v1.36~1.38 사용 |

---

## 7. 용어 정리

- **kind(Kubernetes IN Docker)** : Docker 컨테이너를 노드로 쓰는 로컬 K8s 도구
- **노드 이미지(node image)** : kubelet·containerd·기본 이미지가 든 `kindest/node` 이미지
- **digest** : 이미지 내용의 sha256 지문. 태그가 바뀌어도 같은 이미지 보장
- **extraPortMappings** : 호스트 포트를 노드 컨테이너 포트로 연결하는 kind 설정
- **extraMounts** : 호스트 디렉터리를 노드 컨테이너 안에 마운트
- **kind load** : 로컬 이미지를 노드 containerd 로 직접 적재
- **NodePort** : 모든 노드의 같은 포트(30000~32767)로 Service 를 여는 방식
- **kindnet** : kind 기본 CNI
- **certs.d / hosts.toml** : containerd 레지스트리 미러·인증서 설정 방식
- **cgroup v2** : 리눅스 자원 제어 통합 계층. 최신 K8s 기본 전제

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 버전 | kind v0.33.0, 노드 v1.37.0 (digest 고정), kubectl v1.37 |
| 구조 | 노드 = Docker 컨테이너, control-plane 1 + worker 2 |
| 핵심 설정 | `image@sha256`, `extraPortMappings`, `containerdConfigPatches` |
| 이미지 | `docker build` → `kind load docker-image` → `IfNotPresent` |
| 접속 | localhost:8080 → 30080 → NodePort → Pod 분산 |
| 검증 | `verify.sh` 9단계 PASS |
| 폐쇄망 | 노드 이미지 save/load, 앱 이미지는 certs.d 로 Nexus 미러 |
| 이번 검증 | 버전·설정·매니페스트·스크립트 확인 완료, 실제 기동은 외부 접근 막혀 미검증 |

**kind 는 노드를 컨테이너로 띄워서 최신 K8s 를 1~2분 만에 만들고 지우는 실습용 클러스터. 이미지는 kind load 로 넣으면 레지스트리 없이도 됨.**

관련 글 : CH3. Building applications on Kubernetes
