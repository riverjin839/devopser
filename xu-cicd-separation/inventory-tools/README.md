## xu K8s 서비스 인벤토리 수집기

xu 클러스터 서비스 전수 조사용 파이썬 도구 2개. 둘 다 표준 라이브러리만 쓰고(Python 3.6+), kubectl 로 **읽기만** 함. 폐쇄망에서 파일 복사만으로 실행됨.

| 파일 | 실행 위치 | 보는 것 |
| --- | --- | --- |
| `xu_k8s_inventory.py` | xu 클러스터 master #1 | 클러스터에 실제로 떠 있는 전부 (기준 목록) |
| `xu_argocd_inventory.py` | ArgoCD 가 설치된 클러스터 노드 | ArgoCD 가 xu 로 배포하는 앱 (GitOps 기준 목록) |

두 결과를 비교하면 "ArgoCD 밖에서 배포된 것"과 "ArgoCD 에만 있고 실물이 없는 것"이 나옴.

### 1. xu_k8s_inventory.py (master #1)

```bash
python3 xu_k8s_inventory.py                                   # 기본 실행
python3 xu_k8s_inventory.py --ref-pattern 'i-region\.corp|10\.10\.'   # ConfigMap 의 I 지역 참조도 검색
python3 xu_k8s_inventory.py --skip-resource-scan              # 리소스 타입 스캔 생략 (빠름)
python3 xu_k8s_inventory.py --exclude-ns '^(kube-|cattle-)'   # 네임스페이스 제외
```

하는 일

- Deployment·StatefulSet·DaemonSet·CronJob·Job·ReplicaSet·Pod 를 전부 읽고 ownerReferences 를 끝까지 따라가 **최상위 리소스 = 서비스 1개**로 묶음. Operator CR(StarRocksCluster 등)도 루트로 잡음
- 배포 경로 추정: tracking-id·managedFields·Helm annotation 으로 `ArgoCD / Helm / kubectl / Operator:<kind> / Airflow-Pod / Spark-Pod / 단독Pod / 미상` 표시
- Service selector → Pod → 루트로 따라가서 Ingress·HTTPRoute host, LB IP, NodePort 를 서비스에 붙임
- Helm 시크릿에서 차트 이름·버전만 해석 (값·manifest 는 안 봄)
- owner·team 계열 label·annotation, 네임스페이스 RoleBinding(User/Group)을 담당자 단서로 붙임

출력 (`inv-YYYYmmdd-HHMM/`)

| 파일 | 내용 |
| --- | --- |
| services.csv | **서비스 목록** (네임스페이스+서비스명 단위). 끝에 담당자·신뢰도·분리 처리 빈칸 있음 |
| workloads.csv | 최상위 리소스 단위 상세 (배포 경로, 이미지, 상태, 플래그) |
| exposure.csv | Ingress·HTTPRoute·LB·NodePort → 대상 워크로드. `(대상 Pod 없음)` = 고아 도메인 |
| external_names.csv | ExternalName 서비스 (I 지역 의존성 후보) |
| argocd_apps.csv / argocd_missing.csv | 클러스터 안에 ArgoCD 가 있을 때만 채워짐 |
| helm_releases.csv | 최신 리비전 기준. `has_workload=N` 은 확인 대상 |
| ns_rbac.csv, empty_namespaces.csv | 네임스페이스 권한, 워크로드 없는 NS |
| configmap_refs.csv | `--ref-pattern` 매칭 결과 |
| resource_counts.csv | 리소스 타입(CRD 포함)별·NS별 개수 |
| summary.md, services.txt | 요약, 콘솔에 찍힌 서비스 목록 |

### 2. xu_argocd_inventory.py (ArgoCD 노드)

```bash
python3 xu_argocd_inventory.py                       # 대화형
python3 xu_argocd_inventory.py --argocd-ns argocd    # ArgoCD 네임스페이스가 다를 때
python3 xu_argocd_inventory.py --cluster xu-k8s -y   # 비대화형 (cron 등)
```

대화 흐름

1. `[1/2] 클러스터 이름을 입력` — 엔터만 치면 ArgoCD 에 등록된 클러스터 목록(이름·서버·앱 수)이 나옴. 일부만 쳐도 후보를 보여주고 번호로 고름
2. 서버 URL 과 IP(호스트명이면 이 노드에서 DNS 해석)를 보여주고 `[2/2] 이 서버가 맞습니까? [y/N]` — n 이면 1로 돌아감
3. 그 클러스터를 목적지(server 또는 name)로 하는 Application 을 추출

클러스터 등록 시크릿에서는 `name`, `server` 만 디코딩함. 자격증명(`config`)은 읽지도 저장하지도 않음.

출력 (`argo-inv-<클러스터>-YYYYmmdd-HHMM/`)

| 파일 | 내용 |
| --- | --- |
| services.csv | **앱 = 서비스 목록**. 워크로드, repo/path, 외부 URL, 이미지, 담당자 단서 + 빈칸 |
| apps.csv | 앱 상세 (sync/health, 자동 sync 여부, 마지막 sync 시각·실행자) |
| app_resources.csv | 앱별 관리 리소스. role = 워크로드/노출/설정 |
| missing.csv | ArgoCD 에는 있는데 클러스터에 없는 리소스 |
| applicationsets.csv | 이 클러스터에 앱을 찍어내는 ApplicationSet (clusters 제너레이터 포함) |
| summary.md, services.txt | 요약, 콘솔 목록 |

담당자 단서(owner_hint)는 앱·AppProject 의 owner/team annotation, 알림 구독(`notifications.argoproj.io/subscribe.*`), AppProject 설명·role 그룹, Git repo 그룹 경로, 마지막 수동 sync 실행자에서 모음.

### 3. 두 결과 비교

```bash
# 클러스터 쪽 워크로드 키 (master #1 결과)
python3 - <<'EOF'
import csv
k = sorted({(r["namespace"], r["kind"], r["name"]) for r in csv.DictReader(open("inv-XXXX/workloads.csv", encoding="utf-8-sig"))})
a = sorted({(r["namespace"], r["kind"], r["name"]) for r in csv.DictReader(open("argo-inv-XXXX/app_resources.csv", encoding="utf-8-sig")) if r["role"] == "워크로드"})
print("ArgoCD 밖 배포:", [x for x in k if x not in a])
print("ArgoCD 에만 있음:", [x for x in a if x not in k])
EOF
```

두 파일을 같은 PC 로 가져와서 돌리면 됨. CronJob·단독 Pod 는 수집 시점에 따라 달라지므로 1주 간격으로 두 번 돌려 workloads.csv 를 비교함.

### 4. 참고

- 권한: 전 네임스페이스 get/list (워크로드, services, ingresses, rolebindings, helm 시크릿). 권한이 없는 항목은 건너뛰고 summary.md 의 "수집 경고"에 남김
- 대규모 클러스터용으로 `--chunk-size`(기본 500), `--timeout`(기본 300초) 조정 가능
- 둘 다 `--kubectl`, `--kubeconfig`, `--context` 지원
