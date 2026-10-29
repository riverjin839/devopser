## 우시 K8s 배포 서비스 전수 조사 및 담당자 매핑 가이드

> 작성일: 2026-10-29 · 작성자: Woong
> 그림: [`wuxi-k8s-service-inventory-flow.drawio`](./wuxi-k8s-service-inventory-flow.drawio)

### 1. 원칙

소스 하나만 보면 반드시 빠지는 게 생김. 그래서 클러스터에 실제로 떠 있는 리소스를 기준(정답지)으로 두고, ArgoCD·Helm·Jenkins·트래픽 같은 간접 소스를 겹쳐서 "누가, 어떻게 배포했는지"를 채우는 방식으로 감.

- **기준은 클러스터 실물**: ArgoCD에 없는 것도 클러스터엔 있음. 반대로 ArgoCD에만 있고 클러스터엔 없는 것도 찾아냄
- **합집합 후 교차 확인**: 소스별 목록을 합친 뒤, 두 소스 이상에서 확인되면 확정, 하나뿐이면 추가 확인 대상으로 분류
- **최상위 오너 단위로 셈**: Pod 단위로 세면 중복·누락이 많음. Deployment·StatefulSet·CronJob·Operator CR 같은 최상위 리소스를 "서비스 1개"의 기준으로 잡음
- **스냅샷은 최소 2번**: CronJob·Job·배치성 워크로드는 특정 시간에만 뜨므로, 1주 간격으로 두 번 이상 수집함
- **읽기 전용으로만 수집**: 조사 단계에서는 get·list·describe만 씀. 스케일 조정·삭제는 담당자 확인 이후 별도 절차로 함

### 2. 전체 흐름

> 그림: `wuxi-k8s-service-inventory-flow.drawio` — 수집 소스 7개 → 5단계 진행 흐름

1. **수집**: 읽기 전용 8단계, 1주 간격 스냅샷 2회
2. **병합**: 키 = 네임스페이스/kind/이름, 최상위 리소스 기준
3. **교차 검증**: A~F 비교로 숨은 서비스·고아 리소스 찾기 (빈칸은 다시 수집)
4. **담당자 매핑**: 근거 우선순위 적용, 확정/추정/미확인 표시
5. **본인 확인 → 확정 인벤토리**: 팀별 회람, 미확인은 지우지 않고 별도 기준으로 처리

교차 검증에서 나온 빈칸은 수집으로 돌아가 다시 채움. 이 루프를 빈칸이 없을 때까지 돌리는 게 누락 방지의 핵심임.

### 3. 수집 소스별 장단점

어느 소스도 혼자서는 완전하지 않음. "놓치는 것" 칸을 다른 소스가 메워주는 구조라 아래 7개를 다 돌려야 누락이 안 생김.

| 소스 | 잡는 것 | 놓치는 것 | 담당자 단서 |
| --- | --- | --- | --- |
| K8s API (전 리소스) | 지금 떠 있는 모든 워크로드, CRD 기반 서비스 | 지금 안 도는 Job, 클러스터 밖 의존성 | label·annotation, managedFields 매니저 |
| ArgoCD | GitOps로 배포된 앱, Git 레포·경로, 프로젝트 | kubectl·Helm·Jenkins로 직접 배포한 것 | AppProject, Git 커밋 작성자 |
| Helm 릴리즈 | helm install로 올린 것 (실패·pending 포함) | Helm 안 쓴 배포 | 릴리즈 이름, 차트 출처 |
| 노출 리소스 (Ingress, Gateway API, LB·NodePort) | 외부에서 쓰는 서비스와 도메인 | 내부 전용 서비스, 배치 | 도메인 신청 이력 |
| 이미지 (Nexus) → Jenkins | 이미지를 빌드한 Job, 소스 레포 | 외부 공개 이미지 그대로 쓴 것 | Jenkins Job 소유자, 커밋 작성자 |
| 트래픽·메트릭 (Hubble, Prometheus) | 실제 쓰이는지, 누가 누구를 부르는지, I 지역 호출 | 수집 기간 밖에서만 도는 것 | 호출하는 쪽 팀 |
| 권한·신청 이력 (RBAC, Keycloak 그룹, ITSM) | 네임스페이스 소유 팀·사용자 | 네임스페이스 안의 개별 서비스 | RoleBinding subject, 신청자 |

### 4. 단계별 수집 방법

수집은 8단계이고 전부 읽기 전용 명령임. 결과는 날짜별 디렉터리에 TSV로 남겨서 5장 교차 검증에서 바로 비교함. `<우시 ...>`는 현지 값으로 바꿔야 함.

#### 4-0. 준비

- 우시 클러스터용 읽기 전용 kubeconfig (클러스터 전체 get·list 권한), ArgoCD 읽기 계정, Jenkins 읽기 권한 확보
- `kubectl`, `jq`, `argocd`, `helm`, `hubble` CLI 준비

```bash
export KUBECONFIG=~/.kube/wuxi-readonly
OUT=inv-$(date +%F); mkdir -p $OUT
kubectl config current-context   # 우시 클러스터가 맞는지 먼저 확인
```

#### 4-1. 네임스페이스와 전 리소스 덤프

CRD 기반 서비스(StarRocks, CNPG, SparkApplication 등)까지 놓치지 않으려고, 네임스페이스 단위 리소스 타입을 전부 돌면서 개수만 먼저 뽑음. Secret은 값이 담기므로 메타데이터만 저장함.

```bash
kubectl get ns -o json | jq -r '.items[] | [.metadata.name, .metadata.creationTimestamp, (.metadata.labels|tostring), (.metadata.annotations|tostring)] | @tsv' > $OUT/ns.tsv

# 리소스 타입별 · 네임스페이스별 개수 (events, secrets 제외)
kubectl api-resources --verbs=list --namespaced -o name \
  | grep -vE '^(events|events\.events\.k8s\.io|secrets)$' \
  | while read r; do
      kubectl get "$r" -A -o json 2>/dev/null \
        | jq -r --arg r "$r" '.items[] | [$r, .metadata.namespace, .metadata.name] | @tsv'
    done > $OUT/all-resources.tsv

kubectl get secrets -A -o json | jq -r '.items[] | [.metadata.namespace, .metadata.name, .type] | @tsv' > $OUT/secrets-meta.tsv

# 어떤 타입이 몇 개인지 — 처음 보는 CRD가 있으면 그게 숨은 서비스임
cut -f1 $OUT/all-resources.tsv | sort | uniq -c | sort -rn
```

#### 4-2. 최상위 워크로드 목록 (서비스 단위)

ownerReferences가 없는 리소스가 "서비스 1개"의 기준임. 스케일 0으로 죽여둔 것도 여기서 잡힘.

```bash
kubectl get deploy,sts,ds,cronjob,job -A -o json | jq -r '
  .items[] | select(.metadata.ownerReferences == null) |
  [ .metadata.namespace, .kind, .metadata.name,
    (.spec.replicas // "-"),
    ((.spec.template.spec // .spec.jobTemplate.spec.template.spec).containers | map(.image) | join(",")),
    ([.metadata.managedFields[]?.manager] | unique | join(",")),
    (.metadata.annotations["argocd.argoproj.io/tracking-id"] // .metadata.labels["app.kubernetes.io/instance"] // "-") ]
  | @tsv' > $OUT/workloads.tsv

# Operator가 만든 워크로드: 누가 소유하는지 kind별로 집계 → 그 CR 목록을 따로 서비스로 잡음
kubectl get deploy,sts,ds -A -o json | jq -r '
  .items[].metadata.ownerReferences[]? | select(.kind != "ReplicaSet") | .kind' | sort | uniq -c

# 오너 없는 단독 Pod (Airflow KubernetesPodOperator, Spark driver, 수동 실행 Pod 등)
kubectl get pods -A -o json | jq -r '
  .items[] | select(.metadata.ownerReferences == null) |
  [.metadata.namespace, .metadata.name, (.metadata.labels|tostring)] | @tsv' > $OUT/naked-pods.tsv
```

managedFields의 manager 값으로 배포 경로를 추정할 수 있음.

| manager 값 | 배포 경로 추정 |
| --- | --- |
| argocd 계열 | ArgoCD |
| helm | helm install/upgrade |
| kubectl-client-side-apply, kubectl, kubectl-edit | 사람 또는 Jenkins가 kubectl로 직접 배포 |
| Operator 이름 | CR을 통한 간접 생성 |

#### 4-3. ArgoCD

우시 클러스터를 관리하는 ArgoCD가 I 지역 공용 인스턴스일 수 있어서, 어느 ArgoCD가 우시를 대상으로 등록했는지부터 확인함.

```bash
argocd cluster list      # 우시 API 서버가 등록된 ArgoCD 찾기 (I 지역·우시 양쪽 다 확인)

# 우시를 목적지로 하는 Application
kubectl -n argocd get applications.argoproj.io -o json | jq -r '
  .items[] | select(.spec.destination.server == "<우시 API 서버>" or .spec.destination.name == "<우시 클러스터 이름>") |
  [ .metadata.name, .spec.project, .spec.destination.namespace,
    (.spec.source.repoURL // .spec.sources[0].repoURL),
    (.spec.source.path // .spec.source.chart // "-"),
    .status.sync.status, .status.health.status ] | @tsv' > $OUT/argocd-apps.tsv

# 앱별 관리 리소스 (5장 교차 검증에 씀)
kubectl -n argocd get applications.argoproj.io -o json | jq -r '
  .items[] | .metadata.name as $a | .status.resources[]? |
  [.namespace, .kind, .name, $a] | @tsv' | sort > $OUT/argocd-resources.tsv

# ApplicationSet으로 자동 생성되는 앱의 생성 규칙
kubectl -n argocd get applicationsets.argoproj.io -o yaml > $OUT/argocd-appsets.yaml
kubectl -n argocd get appprojects.argoproj.io -o yaml > $OUT/argocd-projects.yaml
```

ArgoCD가 Helm 차트로 배포한 것은 helm template으로 렌더링되라 `helm list`에는 안 나옴. 두 목록이 겹치지 않는 게 정상임.

#### 4-4. Helm 릴리즈

```bash
helm list -A -a -o json | jq -r '.[] | [.namespace, .name, .chart, .app_version, .status, .updated] | @tsv' > $OUT/helm.tsv
```

`-a`를 빼면 failed·pending 릴리즈가 안 보임.

#### 4-5. 노출 리소스 (도메인·LB)

```bash
kubectl get ingress -A -o json | jq -r '
  .items[] | .metadata.namespace as $n | .metadata.name as $m |
  .spec.rules[]? | [$n, "Ingress", $m, .host, ([.http.paths[]?.backend.service.name] | unique | join(","))] | @tsv' > $OUT/expose.tsv

kubectl get httproute,grpcroute -A -o json | jq -r '
  .items[] | [.metadata.namespace, .kind, .metadata.name, ((.spec.hostnames // []) | join(",")),
    ([.spec.rules[]?.backendRefs[]?.name] | unique | join(","))] | @tsv' >> $OUT/expose.tsv

kubectl get svc -A -o json | jq -r '
  .items[] | select(.spec.type == "LoadBalancer" or .spec.type == "NodePort" or .spec.type == "ExternalName") |
  [.metadata.namespace, .metadata.name, .spec.type,
   (.status.loadBalancer.ingress[0].ip // "-"), (.spec.externalName // "-")] | @tsv' > $OUT/svc-external.tsv
```

ExternalName 서비스는 I 지역을 가리키는 경우가 많아 분리 영향 포인트임.

#### 4-6. 이미지 → Nexus → Jenkins

워크로드 템플릿 기준으로 이미지를 뽑아야 스케일 0인 것도 포함됨.

```bash
kubectl get deploy,sts,ds,cronjob -A -o json | jq -r '
  .items[] | .metadata.namespace as $n | .kind as $k | .metadata.name as $m |
  (.spec.template.spec // .spec.jobTemplate.spec.template.spec) |
  ((.containers // []) + (.initContainers // []))[] | [$n, $k, $m, .image] | @tsv' | sort -u > $OUT/images.tsv

# 레지스트리 호스트별 집계 — I 지역 Nexus에서 당기는 이미지가 몇 개인지
cut -f4 $OUT/images.tsv | cut -d/ -f1 | sort | uniq -c | sort -rn
```

이미지 이름으로 Jenkins Job을 역추적함. Jenkins 서버에서 읽기만 함.

```bash
# 이미지 이름이 들어간 Job 찾기 (Pipeline script, Jenkinsfile 경로 포함)
grep -rl "<이미지 이름>" $JENKINS_HOME/jobs/*/config.xml

# 우시 클러스터에 kubectl·helm으로 직접 배포하는 Job (ArgoCD 밖 배포 경로)
grep -rlE "kubectl (apply|set image|rollout)|helm (upgrade|install)" $JENKINS_HOME/jobs/*/config.xml
```

Jenkinsfile이 Git에 있는 멀티브랜치 Job은 config.xml에 내용이 없으므로, 해당 레포의 Jenkinsfile을 따로 확인함.

#### 4-7. 트래픽·사용 여부

목록에 있는 것 중 실제로 쓰이는지, 그리고 I 지역을 호출하는지 확인함. Hubble은 버퍼가 짧아서 하루 여러 번 돌려 모아야 함.

```bash
# 네임스페이스/워크로드 간 호출 관계
hubble observe --last 20000 --verdict FORWARDED -o json | jq -r '
  [ (.flow.source.namespace // "world"), (.flow.source.workloads[0].name // "-"),
    (.flow.destination.namespace // "world"), (.flow.destination.workloads[0].name // .flow.IP.destination) ] | @tsv' \
  | sort | uniq -c | sort -rn >> $OUT/flows-$(date +%H%M).tsv

# I 지역 대역으로 나가는 호출 (분리 시 끊길 의존성)
hubble observe --last 20000 --to-ip <I 지역 CIDR> -o json | jq -r '[.flow.source.namespace, .flow.source.workloads[0].name, .flow.IP.destination, (.flow.l4.TCP.destination_port // .flow.l4.UDP.destination_port)] | @tsv' | sort | uniq -c
```

Prometheus가 있으면 7일 기준으로 죽은 서비스 후보를 뽑음.

```promql
# 7일간 CPU 사용량이 거의 0인 Pod
sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{container!=""}[7d])) < 0.001

# 레플리카 0으로 죽여둔 Deployment (kube-state-metrics)
kube_deployment_spec_replicas == 0
```

#### 4-8. 설정 속 I 지역 의존성

트래픽에 안 잡힌 의존성(배치용 접속 정보 등)을 ConfigMap에서 찾음. Secret 내용은 디코딩해서 남기지 말고, 필요한 것만 담당자에게 확인 요청함.

```bash
kubectl get cm -A -o json | jq -r '
  .items[] | select(tostring | test("<I 지역 도메인>|<I 지역 IP 접두어>")) |
  [.metadata.namespace, .metadata.name] | @tsv' > $OUT/cm-i-region-ref.tsv
```

### 5. 누락 방지 교차 검증

목록끼리 빼보면 빈칸이 드러남. 아래 6개 비교에서 나온 항목이 거의 다 "숨은 서비스"임. 비교 키는 `네임스페이스/kind/이름`으로 통일함.

| # | 비교 | 결과가 뜻하는 것 | 다음 할 일 |
| --- | --- | --- | --- |
| A | 클러스터 최상위 워크로드 − ArgoCD 관리 리소스 | ArgoCD 밖에서 배포된 것 | managedFields·Helm·Jenkins로 배포 경로 추적 |
| B | ArgoCD 관리 리소스 − 클러스터 | 앱은 남았는데 실물이 없음 (Missing) | 사용 중인지 담당자 확인 |
| C | 노출 리소스 backend → Service → selector에 맞는 Pod | Pod 없는 고아 도메인·LB | 도메인 정리 대상으로 표시 |
| D | 워크로드 0개인 네임스페이스 | 빈 네임스페이스, 또는 CRD만 있는 곳 | all-resources.tsv에서 해당 NS 확인 |
| E | Hubble 목적지 − 인벤토리 | 트래픽은 있는데 목록에 없는 대상 | 대부분 외부·I 지역 의존성 → 의존성 칸에 기록 |
| F | 1차 스냅샷 ↔ 2차 스냅샷 (1주 간격) | 그사이 생기거나 사라진 Job·배치·단독 Pod | 얼마나 자주 도는지 기록 |

A·B 비교 예시.

```bash
# 클러스터 쪽 키
cut -f1-3 $OUT/workloads.tsv | sort -u > $OUT/k.cluster

# ArgoCD 쪽 키 (워크로드 kind만)
awk -F'\t' '$2 ~ /^(Deployment|StatefulSet|DaemonSet|CronJob|Job)$/ {print $1"\t"$2"\t"$3}' $OUT/argocd-resources.tsv | sort -u > $OUT/k.argocd

comm -23 $OUT/k.cluster $OUT/k.argocd > $OUT/diff-A-not-in-argocd.tsv   # A
comm -13 $OUT/k.cluster $OUT/k.argocd > $OUT/diff-B-missing.tsv         # B
```

F는 같은 스크립트를 두 번 돌린 디렉터리끼리 `diff inv-<1차>/workloads.tsv inv-<2차>/workloads.tsv`로 보면 됨. naked-pods.tsv도 같은 방식으로 비교함.

### 6. 담당자 매핑

담당자는 근거 우선순위 순서대로 찾고, 근거가 몇 개 맞는지로 신뢰도를 매김. 끝은 항상 본인 확인임.

| 우선 | 근거 | 확인 방법 | 비고 |
| --- | --- | --- | --- |
| 1 | 리소스 label·annotation | owner, team, app.kubernetes.io/part-of 같은 키 (현지 규칙 확인 필요) | 규칙이 있을 때만 유효 |
| 2 | ArgoCD AppProject · Git 레포 | 프로젝트 소유 팀, CODEOWNERS, 해당 경로 최근 커밋 작성자 | 가장 믿을 만한 간접 근거 |
| 3 | Jenkins Job | Job 생성자, 최근 빌드 실행자, 폴더·권한 | kubectl·helm 직접 배포는 여기가 핵심 |
| 4 | 네임스페이스 권한 | RoleBinding subject → Keycloak 그룹 → 팀 | 팀까지만 나오고 개인은 안 나옴 |
| 5 | 신청 이력 | 네임스페이스·도메인·LB IP 신청 티켓 (ITSM) | 오래된 건 퇴사·이동 확인 |
| 6 | 호출하는 쪽 (Hubble) | 이 서비스를 부르는 팀 | 소유자가 아니라 사용자 — 보조 근거 |
| 7 | 공지·인터뷰 | 미확인 목록 회람, 팀장 문의 | 마지막 수단 |

근거 추출 명령.

```bash
# 네임스페이스별 사람·그룹 권한 (ServiceAccount 제외)
kubectl get rolebinding -A -o json | jq -r '
  .items[] | .metadata.namespace as $n | .roleRef.name as $r |
  .subjects[]? | select(.kind != "ServiceAccount") | [$n, $r, .kind, .name] | @tsv' > $OUT/ns-rbac.tsv

# ArgoCD 앱 경로의 최근 1년 커밋 작성자 상위 5명
git -C <레포> log --since=1.year --format='%an <%ae>' -- <앱 경로> | sort | uniq -c | sort -rn | head -5
```

**신뢰도 기준**

| 신뢰도 | 기준 |
| --- | --- |
| 확정 | 본인이 확인했거나, 서로 다른 근거 2개 이상이 같은 사람·팀을 가리킴 |
| 추정 | 근거 1개만 있음 |
| 미확인 | 근거 없음, 또는 근거의 사람이 퇴사·이동 |

마무리는 팀별로 "이 목록이 당신 팀 것이 맞는지" 회람해서 확정으로 올림. 무응답은 팀장에게 올리고, 끝까지 미확인인 건 지우지 말고 분리 계획에 "미확인"으로 남겨 별도 처리 기준을 협의함.

### 7. 인벤토리 템플릿

행 1개 = 최상위 리소스 1개(서비스 1개)임. 수집 TSV를 이 컬럼에 맞춰 합치면 됨.

| 컬럼 | 내용 | 채우는 소스 |
| --- | --- | --- |
| 키 | 네임스페이스/kind/이름 | 4-1, 4-2 |
| 서비스명 | 사람이 부르는 이름 | 담당자 확인 |
| 종류 | API, 배치(CronJob), 데이터(DB·Operator), 인프라 애드온 | 4-2 |
| 배포 경로 | ArgoCD, Helm, Jenkins kubectl, 수동, Operator | 4-2 managedFields, 4-3, 4-4, 4-6 |
| ArgoCD 앱 · 프로젝트 | 앱 이름, AppProject, 관리하는 ArgoCD(I 지역/우시) | 4-3 |
| Git 레포 · 경로 | repoURL, path 또는 chart | 4-3 |
| 이미지 · 레지스트리 | 이미지, 어느 Nexus에서 받는지 | 4-6 |
| Jenkins Job | 빌드·배포 Job 경로 | 4-6 |
| 외부 노출 | 도메인, LB IP, NodePort | 4-5 |
| 사용 여부 | 트래픽·CPU 있음/없음, 레플리카 | 4-7 |
| I 지역 의존성 | 호출하는 I 지역 대상, ExternalName, ConfigMap 참조 | 4-5, 4-7, 4-8 |
| 담당자(정) · (부) · 팀 | 이름, 팀 | 6장 |
| 근거 · 신뢰도 | 어떤 근거로 정했는지, 확정/추정/미확인 | 6장 |
| 분리 처리 | 우시 이관, 공용 유지, 폐기 후보, 미정 | 담당자 협의 |
| 비고 | 특이사항 | - |

"폐기 후보"는 사용 여부가 없음이고 담당자도 동의한 경우만 붙임.

### 8. 진행 체크리스트

출장 전에 1차 수집을 끝내고, 11/2 실사에서 빈칸을 채우는 순서가 가장 효율적임.

- [ ] 우시 클러스터·ArgoCD·Jenkins 읽기 전용 접근 권한 확보
- [ ] 우시를 관리하는 ArgoCD 인스턴스 확인 (I 지역 공용 여부)
- [ ] 4-1 ~ 4-8 1차 수집
- [ ] 처음 보는 CRD·Operator 목록 따로 정리
- [ ] Hubble 흐름 수집을 하루 여러 번 (최소 업무시간·야간 배치 시간)
- [ ] 5장 A~E 교차 검증, 빈칸 목록 만들기
- [ ] 6장 근거로 담당자 1차 매핑 (확정/추정/미확인)
- [ ] 1주 뒤 2차 수집 후 5장 F 비교
- [ ] 팀별 목록 회람으로 본인 확인
- [ ] 미확인 목록 처리 기준 협의 (분리 협의 안건 7·8과 같이)
