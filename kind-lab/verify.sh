#!/usr/bin/env bash
# kind 실습 검증 : 클러스터 생성 → 이미지 적재 → 배포 → 접속 → 삭제
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
