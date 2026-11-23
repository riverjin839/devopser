## 노드 Drain 무중단 가이드 - OpenEBS · Fluent Bit · OpenSearch · StarRocks · Airflow

> **목표** : 노드 1대 또는 여러 대를 drain 하고 작업할 때(예 : bond0 LACP 전환, 커널 패치) 서비스별 동작을 알고 업무 영향 없이 진행하는 절차를 잡음

- 출처 : Kubernetes Safely Drain a Node, OpenSearch Rolling upgrade · Cluster settings, StarRocks Graceful Exit · ALTER SYSTEM, OpenEBS Replicated PV Mayastor Node Drain, Fluent Bit Buffering and Storage · Backpressure
- 기준 버전 : OpenEBS 4.6.2 (Mayastor 2.12.2, LocalPV LVM 1.10.1), Fluent Bit 5.2.0, OpenSearch 3.10.0, StarRocks 4.1.8, Airflow 3.4.0 / Helm chart 1.22.0 (2026-11 기준 GitHub 태그)

---

## 1. 개요

- drain = 노드를 cordon 하고 Pod 를 eviction API 로 내보내는 작업
- 문제는 stateless 가 아니라 **노드에 묶인 것들** 임 → 로컬 볼륨, 쿼럼, 실행 중 작업, 노드 단위 수집기
- 그래서 drain 전에 서비스별로 "이 노드가 빠지면 무슨 일이 생기나" 를 먼저 정리해야 함

<!-- diagram: drain-01-overview.html -->

**무중단의 핵심은 drain 명령이 아니라, drain 전에 각 서비스가 노드 이탈을 예상하게 만들어 두는 것임**

## 2. 개념 정리

### 2-1. drain 이 하는 일과 안 하는 일

| 구분 | 내용 |
|---|---|
| 하는 일 | cordon(스케줄 금지) → Pod eviction → PDB 위반이면 대기 |
| 안 하는 일 | DaemonSet Pod 는 안 내보냄 (`--ignore-daemonsets`), static Pod 도 그대로 둠 |
| 안 하는 일 | 앱 레벨 준비 (샤드 할당 중지, 리더 이전, job 대기) 는 안 해줌 |
| 함정 | 로컬 PV 를 쓰는 Pod 는 evict 돼도 다른 노드로 못 감 → Pending 으로 대기 |

- Kubernetes 문서도 `kubectl drain` 은 노드 1대씩 실행하라고 권장함
- 여러 대 병렬은 PDB 가 받쳐줄 때만 안전함

### 2-2. 영향 유형 네 가지

| 유형 | 예 | 노드가 빠지면 |
|---|---|---|
| 로컬 상태 (Local state) | OpenEBS LocalPV, OpenSearch data | Pod 이동 불가, 복귀까지 그 사본 없음 |
| 쿼럼 (Quorum) | StarRocks FE, OpenSearch cluster manager, Mayastor etcd | 과반이 남으면 정상, 리더면 재선출 |
| 실행 중 작업 (In-flight) | Airflow task, StarRocks 쿼리, 로드 job | 끊기고 retry, 중복 실행 위험 |
| 노드 단위 수집 (Per-node) | Fluent Bit | 그 노드 로그만 지연, buffer 설정에 따라 손실 |

### 2-3. PDB(PodDisruptionBudget) 가 지켜주는 범위

- PDB = eviction 단계에서 "동시에 몇 개까지 빠져도 되나" 를 강제함
- drain 이 PDB 위반이면 evict 를 재시도하며 기다림 → 무리한 병렬 drain 을 막아줌
- 단, PDB 는 Pod 수만 셈. OpenSearch 샤드 사본이 어디 있는지, FE 리더가 누구인지는 모름
- 그래서 PDB + 앱 레벨 준비 두 겹으로 가야 함

## 3. 서비스별 노드 중단 시 동작

<!-- diagram: drain-02-service-behavior.html -->

### 3-1. OpenEBS

| 엔진 | 노드가 빠지면 | drain 전 준비 |
|---|---|---|
| LocalPV (hostpath · LVM · ZFS) | PV 에 nodeAffinity 고정 → Pod Pending, 데이터는 노드에 남음 | 앱이 자체 복제하는지 확인 (OpenSearch replica 등) |
| Replicated PV Mayastor | 그 노드 replica 가 빠져 볼륨 degraded, 복귀 후 rebuild | `kubectl mayastor drain node` 로 nexus 를 먼저 옮김 |

- LocalPV = 스토리지 계층에 복제가 없음. 무중단 여부는 위에 올라간 앱이 결정함
- Mayastor 는 io-engine 이 DaemonSet 이라 kubectl drain 만으로는 엔진이 안 빠짐 → Mayastor 전용 drain 으로 target(nexus) 을 다른 노드로 옮긴 뒤 kubectl drain
- Mayastor 컨트롤 플레인 etcd(기본 3개) 도 쿼럼임 → etcd Pod 가 있는 노드는 한 번에 1대만

> 주의 : replica 1 짜리 Mayastor 볼륨은 그 노드가 빠지면 I/O 가 멈춤. 작업 전에 `kubectl mayastor get volumes` 로 replica 수를 확인함

### 3-2. Fluent Bit

- DaemonSet 이라 drain 대상이 아님. 그 노드 작업 중에는 네트워크가 끊겨 output 실패 → retry
- 다른 노드의 Fluent Bit 는 영향 없음. 단, OpenSearch 노드가 빠지면 bulk 응답이 느려져 retry 가 늘어남

| 설정 | 동작 |
|---|---|
| `storage.type memory` (기본) | `Mem_Buf_Limit` 넘으면 tail input pause. tail 은 offset 을 저장해서 다시 읽음 |
| `storage.type filesystem` | 메모리 한도를 넘으면 chunk 를 디스크에 쌓음. Pod 재시작에도 남음 |
| tail `DB` (hostPath) | inode=offset 저장 → 재기동 후 이어서 읽음 |

- 손실 케이스 = 다운 중 로그 로테이트로 원본 파일 삭제, `storage.total_limit_size` 초과, `Retry_Limit` 초과
- 작업 시간이 길면 kubelet 로그 로테이트 주기(`containerLogMaxSize`, `containerLogMaxFiles`) 와 비교해 봐야 함

### 3-3. OpenSearch

| 역할 | 노드가 빠지면 |
|---|---|
| data | 그 노드 primary → 다른 노드 replica 가 승격, replica 는 unassigned → **yellow** |
| data (준비 안 함) | `index.unassigned.node_left.delayed_timeout` (기본 1m) 이 지나면 다른 노드로 재복제 시작 → 대량 I/O · 네트워크 |
| cluster manager | 3대 중 1대는 무관. 현재 manager 면 재선출 |
| replica 0 인덱스 | 그 노드 샤드는 사본이 없음 → **red**, 읽기·쓰기 실패 |

<!-- diagram: drain-03-opensearch.html -->

- 준비 = `cluster.routing.allocation.enable: primaries` → `_flush` → 노드 중지
- 복귀 후 `all` 로 되돌려야 replica 가 다시 붙음. 안 되돌리면 계속 yellow 임
- LocalPV 위 OpenSearch 는 같은 노드로 돌아옴 → 로컬 데이터가 남아 있어서 차이분만 복구하므로 빠름

> 주의 : 노드마다 `primaries` → 작업 → `all` → green 대기 를 반복해야 함. 처음에 한 번만 끄고 끝에 켜면 중간 노드 복귀 때 replica 가 안 붙음

### 3-4. StarRocks (shared-data)

<!-- diagram: drain-04-starrocks.html -->

| 역할 | 노드가 빠지면 | 준비 |
|---|---|---|
| FE follower | 3대 중 1대는 메타데이터 쓰기 계속 가능 | 1대씩, observer → follower → leader 순 |
| FE leader | 재선출 (수 초), 그 FE 에 붙은 MySQL 세션 끊김 | 마지막에 작업, LB 뒤라면 재연결 |
| CN | 그 CN 에서 돌던 쿼리 fragment 실패, tablet 은 다른 CN 이 맡음 | graceful exit 로 실행 중 쿼리 대기 |
| CN 캐시 | 로컬 data cache 는 그 노드에만 있음 → 다른 CN 은 S3 에서 cold read | 피크 시간 피하기 |

- shared-data = 데이터가 S3(AIStor) 에 있음 → CN 은 stateless 라 이동 자체는 자유로움
- Graceful Exit 은 v3.3 부터, v3.4 부터 기본 활성 → SIGTERM 을 받으면 새 작업을 안 받고 실행 중 fragment 를 기다림 (`loop_count_wait_fragments_finish` x 10초)
- 그래서 CN Pod 의 `terminationGracePeriodSeconds` 를 대기 시간보다 길게 잡아야 의미가 있음
- CN 은 `ALTER SYSTEM DECOMMISSION` 대상이 아님. 잠깐 빠지는 작업은 graceful exit + drain 으로 충분함

> 주의 : 남은 CN 수가 동시 쿼리를 감당 못 하면 큐잉 · 타임아웃이 남. CN 을 여러 대 같이 빼려면 warehouse 단위 여유를 먼저 확인함

### 3-5. Airflow

| 컴포넌트 | 노드가 빠지면 | 준비 |
|---|---|---|
| metadata DB | 전체 정지 | CNPG 면 switchover 로 primary 를 먼저 옮김 |
| scheduler | 2대 이상이면 무관, 1대면 스케줄 정지 | replica 2 이상 |
| API server (3.x) | worker 가 상태 보고를 못 함 → task 실패 가능 | replica 2 이상 |
| worker · task Pod | 실행 중 task 실패 → retry | warm shutdown 대기, 중요 DAG 확인 |
| triggerer | deferrable task 대기, 복구 후 이어감 | replica 2 이상 |

- 진짜 위험은 다운이 아니라 **retry 로 인한 중복 실행** 임 (append insert, 외부 job 이중 제출)
- KubernetesExecutor task Pod 는 drain 때 그냥 evict 됨 → 작업 노드에 장시간 task 가 있으면 끝날 때까지 기다리고 drain 함

## 4. 1대씩 vs 여러 대 동시

<!-- diagram: drain-05-batch.html -->

| 방식 | 장점 | 단점 | 언제 쓰나 |
|---|---|---|---|
| 1대씩 롤링 | 판단이 단순함, 실패 범위가 작음 | 300+ 노드면 오래 걸림 | control-plane, 쿼럼 멤버, 첫 canary |
| 배치 (같은 장애 도메인 묶음) | 빠름 | 배치 설계를 잘못하면 사본 동시 손실 | 일반 worker, stateless 위주 노드 |
| 서비스 역할별 분리 | 쿼럼 · 사본 충돌을 원천 차단 | 사전 라벨링 필요 | stateful 이 섞인 노드 |

- 배치에 같이 넣으면 안 되는 조합
  - OpenSearch : 같은 샤드의 primary 와 replica 가 있는 노드들 (allocation awareness 로 zone 을 나눠 두면 zone 단위 배치 가능)
  - StarRocks FE : follower 2대 이상
  - Mayastor : 같은 볼륨 replica 를 가진 노드들, etcd 2대 이상
  - Airflow : scheduler · API server 전부, metadata DB primary
- 판단 규칙 = **한 배치에서 쿼럼 그룹당 1개 이하, 사본 그룹당 1개 이하**

## 5. 사용법 예시

### 5-1. 노드에 무엇이 있는지 먼저 봄

```bash
NODE=worker-123

# 이 노드의 Pod (DaemonSet 제외)
kubectl get pod -A -o wide --field-selector spec.nodeName=$NODE \
  | grep -v -E 'fluent-bit|cilium|io-engine|csi-node'

# 이 노드에 묶인 로컬 PV
kubectl get pv -o json | jq -r --arg n "$NODE" '.items[]
  | select(.spec.nodeAffinity.required.nodeSelectorTerms[]?.matchExpressions[]?.values[]? == $n)
  | "\(.spec.claimRef.namespace)/\(.spec.claimRef.name)  \(.spec.storageClassName)"'

# 막힐 PDB 확인 (ALLOWED DISRUPTIONS 0 이면 drain 대기)
kubectl get pdb -A
```

### 5-2. 서비스별 준비

```bash
# OpenSearch : 재복제 막고 flush
curl -XPUT "$OS/_cluster/settings" -H 'Content-Type: application/json' \
  -d '{"persistent":{"cluster.routing.allocation.enable":"primaries"}}'
curl -XPOST "$OS/_flush"

# StarRocks : FE 상태 · 리더 확인 (리더는 마지막)
mysql -h $FE -P9030 -e "SHOW FRONTENDS\G" | egrep 'Name|Role|IsMaster|Alive|ReplayedJournalId'
mysql -h $FE -P9030 -e "SHOW COMPUTE NODES\G" | egrep 'IP|Alive|TabletNum'

# OpenEBS Mayastor : 엔진 drain
kubectl mayastor drain node $NODE maint-$(date +%Y%m%d)

# Airflow : 이 노드에 실행 중 task 가 있는지
kubectl get pod -n airflow -o wide --field-selector spec.nodeName=$NODE
```

### 5-3. drain → 작업 → 복귀

```bash
kubectl drain $NODE --ignore-daemonsets --delete-emptydir-data --timeout=20m
# --force, --disable-eviction 은 쓰지 않음 (PDB 우회)

# ... 노드 작업 (bond 전환 등) ...

kubectl uncordon $NODE
kubectl mayastor uncordon node $NODE maint-$(date +%Y%m%d)
curl -XPUT "$OS/_cluster/settings" -H 'Content-Type: application/json' \
  -d '{"persistent":{"cluster.routing.allocation.enable":"all"}}'
curl "$OS/_cluster/health?wait_for_status=green&timeout=30m"
```

### 5-4. PDB 기본값 (K8s 매니페스트)

```yaml
# OpenSearch data : 한 번에 1개만
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: os-data, namespace: logging }
spec:
  maxUnavailable: 1
  selector: { matchLabels: { app: opensearch, role: data } }
---
# StarRocks FE : follower 3 중 2 유지
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: sr-fe, namespace: starrocks }
spec:
  minAvailable: 2
  selector: { matchLabels: { app.kubernetes.io/component: fe } }
---
# Airflow scheduler : 최소 1개 유지 (replica 2 이상 전제)
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: af-scheduler, namespace: airflow }
spec:
  minAvailable: 1
  selector: { matchLabels: { component: scheduler } }
```

- 라벨은 각 Helm chart · operator 기본값이 다름 → 실제 Pod 라벨로 바꿔야 함 (개념 코드)

## 6. 실무에서 확인

- 300+ 노드라 1대씩은 비현실적임 → 노드에 `maint-group` 라벨을 미리 매겨 두고 배치 단위로 돎
  - stateless worker 묶음, OpenSearch zone A/B/C, StarRocks FE 노드, control-plane 을 따로 분리
- 사용자 네임스페이스 ~1,000개 → 사용자 워크로드에 replica 1 · PDB 없음이 섞여 있음
  - 작업 공지에 "노드별 순단 가능, 단일 replica · 장시간 job 은 재시도 필요" 를 넣음
  - 반대로 `minAvailable` 을 replica 수와 같게 잡은 PDB 는 drain 을 영원히 막음 → 사전에 찾아서 협의
- Cilium BGP 로 LB IP 를 광고하는 노드면 drain 전에 광고를 빼야 외부 세션이 덜 끊김
- StarRocks 데이터는 AIStor(S3) 에 있음 → CN 이동은 가볍지만, AIStor 노드 작업과 같은 시간에 겹치면 cold read 부하가 몰림
- Airflow metadata DB 가 CNPG 면 `kubectl cnpg promote` 로 primary 를 먼저 다른 노드로 옮김
- OpenSearch 가 LocalPV 위에 있으면 노드가 **복귀 안 하는 경우** (하드웨어 고장) 가 최악임 → 그때는 `delayed_timeout` 을 짧게 돌려 재복제를 시작해야 함
- 폐쇄망이라 `kubectl-mayastor` 플러그인 바이너리를 Nexus 에 미리 올려 둬야 함
- 검증 게이트 (다음 노드로 넘어가는 조건)
  - Node Ready, 로컬 PV Pod Running
  - OpenSearch green, active recovery 0
  - StarRocks FE 전부 Alive, ReplayedJournalId 가 리더와 같음, CN 전부 Alive
  - Airflow scheduler heartbeat 정상, 작업 시간대 failed task 확인
  - Fluent Bit `fluentbit_output_retries_failed_total`, `fluentbit_output_dropped_records_total` 증가 없음

## 7. 용어 정리

- **drain** : 노드를 스케줄 금지로 만들고 Pod 를 eviction 으로 내보내는 작업
- **cordon** : 새 Pod 스케줄만 막는 것. 기존 Pod 는 그대로
- **PDB(PodDisruptionBudget)** : 자발적 중단 때 동시에 빠질 수 있는 Pod 수 제한
- **LocalPV** : 노드 로컬 디스크를 쓰는 PV. 노드에 고정되어 Pod 이동 불가
- **nexus** : Mayastor 볼륨의 I/O 진입점(target). replica 들로 I/O 를 나눠 보냄
- **shard allocation** : OpenSearch 가 샤드를 어느 노드에 둘지 정하는 과정
- **delayed_timeout** : 노드 이탈 후 재복제를 시작하기까지 기다리는 시간 (기본 1m)
- **allocation awareness** : zone · rack 속성으로 같은 샤드 사본을 다른 도메인에 나눠 두는 기능
- **FE follower / observer** : StarRocks 메타데이터 노드. follower 는 쿼럼 투표, observer 는 읽기 확장
- **Graceful Exit** : StarRocks 노드가 새 작업을 거절하고 실행 중 작업을 기다린 뒤 내려가는 방식
- **warm shutdown** : Celery worker 가 실행 중 task 를 마치고 종료하는 방식
- **tail DB** : Fluent Bit tail input 의 파일별 읽기 위치 저장소

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 원칙 | drain 전에 서비스가 노드 이탈을 예상하게 만듦 → PDB + 앱 레벨 준비 |
| OpenEBS | LocalPV = Pod 고정, 앱 복제에 의존. Mayastor = 전용 drain 으로 nexus 이동 |
| Fluent Bit | DaemonSet, 그 노드 로그만 지연. filesystem buffer + tail DB 로 손실 방지 |
| OpenSearch | 노드마다 primaries → flush → 작업 → all → green 반복 |
| StarRocks | FE 1대씩 리더 마지막, CN 은 graceful exit 와 grace period |
| Airflow | DB · scheduler · API server 이중화, 중복 실행이 진짜 위험 |
| 여러 대 | 배치당 쿼럼 그룹 1개 이하, 사본 그룹 1개 이하 |
| 다음 노드 조건 | Ready, green, FE 동기화, scheduler 정상, 로그 drop 0 |

**노드 1대가 빠져도 각 서비스가 "예정된 이탈" 로 처리하게 만들면, drain 은 그냥 반복 작업이 된다**

관련 글 :
