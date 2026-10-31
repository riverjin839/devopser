#!/usr/bin/env bash
# 스터디 실습 검증 : kind(v1.37) → kube-ops-view → metrics-server → kubectl top → 삭제
# usage: ./verify.sh [--keep]   (--keep 이면 클러스터 남김)
set -euo pipefail
NAME=myk8s
CTX="kind-${NAME}"
IMAGE="kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5"
pass() { echo "[PASS] $*"; }
fail() { echo "[FAIL] $*"; exit 1; }

for t in docker kind kubectl helm curl; do command -v "$t" >/dev/null || fail "$t 없음"; done
pass "도구 : $(kind version | awk '{print $1, $2}'), helm $(helm version --short)"

if ! kind get clusters | grep -qx "${NAME}"; then
kind create cluster --name "${NAME}" --image "${IMAGE}" --wait 3m --config - <<CFG
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
CFG
fi
ver=$(kubectl --context "${CTX}" get nodes -o jsonpath='{.items[0].status.nodeInfo.kubeletVersion}')
if [ "${ver}" = "v1.37.0" ]; then pass "kind 클러스터 ${NAME} : 노드 v1.37.0 Ready"; else fail "노드 버전 ${ver}"; fi

helm repo add geek-cookbook https://geek-cookbook.github.io/charts/ >/dev/null
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ >/dev/null
helm repo update >/dev/null
pass "helm repo 2개 추가"

helm upgrade --install kube-ops-view geek-cookbook/kube-ops-view --version 1.2.2 \
  --set service.main.type=NodePort,service.main.ports.http.nodePort=30003 \
  --set env.TZ="Asia/Seoul" --namespace kube-system --kube-context "${CTX}" --wait --timeout 5m >/dev/null
pass "kube-ops-view 설치 (NodePort 30003)"

code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:30003/)
if [ "${code}" = "200" ]; then pass "http://localhost:30003 응답 200"; else fail "kube-ops-view 접속 ${code}"; fi

helm upgrade --install metrics-server metrics-server/metrics-server --version 3.14.0 \
  --set 'args[0]=--kubelet-insecure-tls' -n kube-system --kube-context "${CTX}" --wait --timeout 5m >/dev/null
pass "metrics-server 설치"

ok=""
for _ in $(seq 1 24); do
  if kubectl --context "${CTX}" top node >/dev/null 2>&1; then ok=1; break; fi
  sleep 5
done
if [ -n "${ok}" ]; then pass "kubectl top node 동작 (Metrics API 준비)"; else fail "2분 안에 지표 안 올라옴"; fi
kubectl --context "${CTX}" top node
kubectl --context "${CTX}" top pod -A --sort-by=cpu | head -6

kubectl --context "${CTX}" describe node | sed -n '/Allocated resources/,/memory/p'
pass "describe node : 자원 할당량 확인"

if [ "${1:-}" != "--keep" ]; then
  kind delete cluster --name "${NAME}" >/dev/null
  pass "클러스터 삭제"
fi
