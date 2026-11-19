# Cilium 1.18.4 Bandwidth Manager 적용 및 ETL Job 파드 대역폭 제어 가이드

작성일: 2026-11-19 · 대상: Cilium 1.18.4 · 구조 흐름도: [cilium-bandwidth-manager.drawio](./cilium-bandwidth-manager.drawio)

## 1. 개요

**결론:** Cilium 1.18.4에서 `bandwidthManager.enabled=true`로 Bandwidth Manager를 켜고, ETL Job 파드 템플릿에 `kubernetes.io/egress-bandwidth`(필요 시 `kubernetes.io/ingress-bandwidth`) 어노테이션을 붙이면 파드 단위로 대역폭 상한이 적용됩니다. 이렇게 하면 ETL 대량 전송이 같은 노드의 서비스 트래픽을 밀어내는 문제(noisy neighbor)를 막을 수 있습니다.

**배경:** ETL Job(Spark, Airflow 워커, 덤프·적재 배치 등)은 짧은 시간에 수 Gbps를 쓰며 노드 NIC를 포화시킵니다. 그 결과 같은 노드의 API·DB 클라이언트 파드에서 지연과 타임아웃이 생깁니다. 파드 단위로 대역폭 상한을 두면 ETL은 일정한 속도로 오래 전송하고, 다른 워크로드는 남은 대역폭을 확보합니다.

**동작 원리**

| 구분 | 어노테이션 | 적용 지점 | 방식 |
| --- | --- | --- | --- |
| Egress(파드 → 외부) | `kubernetes.io/egress-bandwidth` | 노드의 물리 디바이스(예: eth0) | eBPF가 패킷에 EDT(Earliest Departure Time) 타임스탬프를 찍고, FQ qdisc가 그 시각에 맞춰 내보냄 |
| Ingress(외부 → 파드), 1.18 신규 | `kubernetes.io/ingress-bandwidth` | 파드로 들어가는 eBPF 경로 | eBPF 토큰 버킷으로 초과분을 drop |
| BBR(선택) | Helm `bandwidthManager.bbr` | 파드 TCP 혼잡제어 | 새로 뜨는 파드의 기본 혼잡제어를 BBR로 설정 |

- Bandwidth Manager는 Cilium에 내장된 기능이며 bandwidth CNI 플러그인(TBF)을 쓰지 않습니다. TBF 방식은 멀티 큐 NIC에서 확장성 문제가 있어 권장되지 않습니다.
- direct routing 모드와 터널링(VXLAN/Geneve) 모드를 모두 지원합니다.
- Egress 제한은 송신 측에서 속도를 조절(pacing)하므로 재전송이 적습니다. Ingress 제한은 이미 노드에 도착한 패킷을 버리는 방식이라 TCP 재전송이 늘어납니다. **ETL은 egress 제한을 기본으로 하고, ingress는 보조로만 씁니다.**

구조 흐름은 [cilium-bandwidth-manager.drawio](./cilium-bandwidth-manager.drawio)의 「구조 흐름」 페이지를 참고합니다. Cilium Agent가 파드 어노테이션을 읽어 BPF 맵에 기록하고, 송신 경로는 물리 NIC에서, 수신 경로는 파드 진입 전에 제한이 걸립니다.

## 2. 사전 요구사항 및 제약사항

아래 항목을 모두 충족해야 대역폭 제한이 실제로 걸립니다. 특히 L7 정책과의 충돌은 오류 없이 제한만 조용히 빠지므로 먼저 확인합니다.

| 항목 | 요구 조건 | 확인 방법 |
| --- | --- | --- |
| Linux 커널 | Cilium 1.18 최소 v5.10(RHEL 8.6 이상). Bandwidth Manager 자체는 v5.1 이상 | `uname -r` |
| BBR 사용 시 커널 | v5.18 이상(파드→호스트 네임스페이스 이동 시 패킷 타임스탬프 유지 필요) | `uname -r` |
| BBR 사용 시 라우팅 | eBPF Host-Routing(`bpf.masquerade=true`, kube-proxy replacement 환경 권장) | `cilium-dbg status`의 `Host Routing: BPF` |
| 노드 디바이스 | 자동 감지(기본 라우트 또는 InternalIP 디바이스). 수동 지정 시 모든 노드에서 이름이 같아야 함 | `cilium-dbg status`의 BandwidthManager 줄 |
| 실행 환경 | Kind 등 중첩 네임스페이스 환경은 `/proc/sys/net/core` 접근이 없어 동작하지 않음 | 베어메탈/VM 노드에서 테스트 |

**제약사항**

- **L7 CiliumNetworkPolicy와 비호환:** 파드의 egress를 L7(HTTP, Kafka, DNS 프록시 등) 정책이 선택하면 그 파드의 대역폭 제한은 비활성화됩니다. ETL 네임스페이스에 `toFQDNs`(DNS 프록시)나 `rules.http` 정책이 있는지 먼저 확인합니다.
- **bandwidth CNI 플러그인 병행 금지:** CNI chaining으로 `bandwidth` 플러그인을 쓰고 있다면 제거합니다. 두 방식이 같은 어노테이션을 읽어 중복 제한이 걸립니다.
- **파드 단위 제한:** 제한은 파드(Endpoint)마다 걸립니다. Job의 총 사용량은 `parallelism × 파드당 제한`이므로 나중에 값을 정할 때 함께 계산합니다.
- **hostNetwork 파드는 제외:** `hostNetwork: true` 파드는 Cilium Endpoint가 아니므로 어노테이션이 적용되지 않습니다.
- **동일 노드 트래픽:** Ingress 제한은 같은 노드에서 오는 트래픽에는 적용되지 않는다는 사용자 보고가 있습니다. 노드 간 트래픽으로 검증합니다.

## 3. Bandwidth Manager 활성화 절차

Bandwidth Manager는 새로 설치할 때 기본값이 꺼져 있습니다. 기존 1.18.4 클러스터는 Helm 값을 바꾼 뒤 cilium DaemonSet을 재시작하면 적용됩니다. 전체 절차는 drawio의 「적용 절차」 페이지에 흐름으로 정리돼 있습니다.

1. 현재 설정을 백업합니다.

```bash
helm -n kube-system get values cilium -o yaml > cilium-values-backup-$(date +%Y%m%d).yaml
kubectl -n kube-system get cm cilium-config -o yaml > cilium-config-backup.yaml
cilium version   # cilium-cli 기준 서버/클라이언트 버전 확인
```

2. Helm values 파일에 아래 내용을 추가합니다(`bandwidth-values.yaml`).

```yaml
bandwidthManager:
  enabled: true
  # BBR는 커널 5.18+ 와 eBPF Host-Routing이 모두 충족될 때만 켭니다.
  # ETL 대역폭 제한만 목적이면 false로 둡니다.
  bbr: false

# (선택) 디바이스 자동 감지가 틀릴 때만 수동 지정. 모든 노드에서 같은 이름이어야 함
# devices: "eth0"
```

3. Helm upgrade 후 Cilium Agent를 재시작합니다. `--version`은 반드시 현재 버전(1.18.4)으로 고정해 의도하지 않은 업그레이드를 막습니다.

```bash
helm upgrade cilium cilium/cilium --version 1.18.4 \
  --namespace kube-system \
  --reuse-values \
  -f bandwidth-values.yaml

kubectl -n kube-system rollout restart ds/cilium
kubectl -n kube-system rollout status ds/cilium --timeout=15m
```

4. 활성화 여부를 확인합니다.

```bash
kubectl -n kube-system exec ds/cilium -- cilium-dbg status | grep BandwidthManager
# 예상 출력
# BandwidthManager:       EDT with BPF [CUBIC] [eth0]
# (bbr: true 인 경우 [BBR])

kubectl -n kube-system get cm cilium-config -o yaml | grep -i bandwidth
# enable-bandwidth-manager: "true"
```

- `BandwidthManager: Disabled`가 나오면 에이전트가 재시작되지 않았거나 커널·디바이스 감지에 실패한 것입니다. 에이전트 로그에서 `bandwidth`를 검색합니다.
- `[eth0]` 자리에 표시된 디바이스가 ETL 트래픽이 실제로 나가는 NIC인지 확인합니다. 본딩(bond0)이나 스토리지 전용 NIC가 따로 있다면 `devices`에 포함해야 합니다.
- 재시작 중에도 기존 파드 통신은 유지되지만, 운영 클러스터는 트래픽이 적은 시간에 진행합니다(6장 단계적 롤아웃 참고).

## 4. ETL Job 파드 적용

어노테이션은 **파드 템플릿의 metadata**에 붙여야 합니다. Job이나 CronJob 자체의 `metadata.annotations`에 붙이면 파드로 전달되지 않아 제한이 걸리지 않습니다.

### 4.1 제한값 산정 기준

파드당 제한은 노드 NIC 용량 중 ETL에 허용할 비율을 정하고, 한 노드에 동시에 뜨는 ETL 파드 수로 나눕니다.

```
파드당 제한 = (NIC 용량 × ETL 허용 비율) / 노드당 최대 ETL 파드 수
```

예를 들어 10 Gbps NIC에서 ETL에 40%를 허용하고 노드당 ETL 파드가 최대 4개라면 파드당 1 Gbps(`"1G"`)입니다. 노드당 파드 수는 `podAntiAffinity`나 `topologySpreadConstraints`로 제한해야 계산이 유지됩니다.

| 티어 | 용도 | egress | ingress |
| --- | --- | --- | --- |
| etl-heavy | 대용량 적재·덤프, S3/HDFS 업로드 | `1G` | `2G` 또는 미지정 |
| etl-standard | 일반 변환 배치 | `500M` | 미지정 |
| etl-light | 소량 동기화, 검증 Job | `100M` | 미지정 |

- 단위는 bit/s입니다. `K`, `M`, `G` 접미사를 씁니다(`"500M"` = 500 Mbit/s ≈ 62.5 MB/s).
- 위 티어 값은 예시입니다(10 Gbps NIC, ETL 40% 가정). 실제 NIC 용량과 ETL 목표 처리 시간으로 다시 계산합니다. 제한이 낮을수록 Job 실행 시간이 길어지므로 `activeDeadlineSeconds`도 함께 조정합니다.

### 4.2 Kubernetes Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: etl-daily-load
  namespace: etl
spec:
  parallelism: 4
  completions: 4
  backoffLimit: 3
  activeDeadlineSeconds: 14400
  template:
    metadata:
      labels:
        app: etl-daily-load
        workload-type: etl
      annotations:
        kubernetes.io/egress-bandwidth: "1G"   # 파드 → 외부(적재·업로드)
        kubernetes.io/ingress-bandwidth: "2G"  # 외부 → 파드(소스 추출), 필요 시만
    spec:
      restartPolicy: Never
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              workload-type: etl
      containers:
        - name: etl
          image: registry.example.com/etl/loader:1.4.2
          resources:
            requests: { cpu: "2", memory: 4Gi }
            limits:   { cpu: "4", memory: 8Gi }
```

### 4.3 CronJob

어노테이션 위치는 `spec.jobTemplate.spec.template.metadata.annotations`입니다.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etl-hourly-sync
  namespace: etl
spec:
  schedule: "0 * * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        metadata:
          labels:
            workload-type: etl
          annotations:
            kubernetes.io/egress-bandwidth: "500M"
        spec:
          restartPolicy: OnFailure
          containers:
            - name: sync
              image: registry.example.com/etl/sync:2.0.1
```

### 4.4 Spark on Kubernetes

Spark는 driver와 executor 파드에 각각 어노테이션을 줍니다. 대역폭은 주로 executor가 쓰므로 executor에 제한을 겁니다.

```bash
spark-submit \
  --master k8s://https://<api-server>:6443 \
  --deploy-mode cluster \
  --conf spark.kubernetes.namespace=etl \
  --conf spark.kubernetes.executor.annotation.kubernetes.io/egress-bandwidth=1G \
  --conf spark.kubernetes.executor.annotation.kubernetes.io/ingress-bandwidth=2G \
  --conf spark.kubernetes.driver.annotation.kubernetes.io/egress-bandwidth=200M \
  ...
```

Spark Operator(`SparkApplication`)를 쓴다면 `spec.executor.annotations`와 `spec.driver.annotations`에 같은 키를 넣습니다. Executor 간 shuffle 트래픽도 제한 대상이므로, shuffle이 많은 Job은 제한값을 더 넓게 잡습니다.

### 4.5 Airflow KubernetesPodOperator

```python
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

load = KubernetesPodOperator(
    task_id="etl_load",
    namespace="etl",
    image="registry.example.com/etl/loader:1.4.2",
    labels={"workload-type": "etl"},
    annotations={
        "kubernetes.io/egress-bandwidth": "1G",
    },
)
```

### 4.6 누락 방지: Kyverno로 기본값 자동 주입(선택)

팀마다 매니페스트에 어노테이션을 넣는 방식은 누락이 생깁니다. Kyverno 같은 정책 엔진이 있다면 `workload-type: etl` 레이블이 붙은 파드에 기본 제한을 자동으로 넣습니다. `+()` 문법은 값이 없을 때만 추가하므로, Job에 직접 지정한 값이 우선합니다.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: etl-default-bandwidth
spec:
  rules:
    - name: add-egress-bandwidth
      match:
        any:
          - resources:
              kinds: ["Pod"]
              namespaces: ["etl"]
              selector:
                matchLabels:
                  workload-type: etl
      mutate:
        patchStrategicMerge:
          metadata:
            annotations:
              +(kubernetes.io/egress-bandwidth): "500M"
```

### 4.7 우선순위 어노테이션(참고)

Cilium 소스에는 `bandwidth.cilium.io/priority` 어노테이션이 있고, 값이 없으면 파드 QoS 클래스(Guaranteed/Burstable/BestEffort)에 따라 기본 우선순위가 정해집니다. 다만 공식 문서에는 값의 범위와 동작이 설명되어 있지 않습니다. 이 가이드에서는 사용하지 않고, 5장의 `cilium-dbg bpf bandwidth list` 출력에서 `PRIO` 값만 확인합니다.

## 5. 검증 및 모니터링

어노테이션이 실제로 적용됐는지는 파드가 떠 있는 노드의 Cilium Agent에서 BPF 맵을 조회해 확인합니다. 그다음 iperf3로 실측 속도가 제한값 근처에서 멈추는지 봅니다.

### 5.1 BPF 맵 확인

```bash
# 1) ETL 파드가 있는 노드와 그 노드의 cilium 파드 찾기
NODE=$(kubectl -n etl get pod <etl-pod> -o jsonpath='{.spec.nodeName}')
CILIUM=$(kubectl -n kube-system get pod -l k8s-app=cilium \
  --field-selector spec.nodeName=$NODE -o name)

# 2) 대역폭 제한 목록
kubectl -n kube-system exec $CILIUM -- cilium-dbg bpf bandwidth list
# IDENTITY   DIRECTION   PRIO   BANDWIDTH (BitsPerSec)
# 724        Egress      0      1G
# 724        Ingress     0      2G

# 3) IDENTITY를 Endpoint/파드와 대조
kubectl -n kube-system exec $CILIUM -- cilium-dbg endpoint list | grep etl
```

목록에 파드가 없으면 어노테이션 위치(파드 템플릿 여부), L7 정책 적용 여부, Bandwidth Manager 활성화 여부를 차례로 확인합니다(6.3 참고).

### 5.2 iperf3 실측 테스트

서버와 클라이언트를 **서로 다른 노드**에 띄웁니다. 서버 파드에 ETL과 같은 어노테이션을 붙입니다.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: bw-server
  namespace: etl
  labels: { app: bw-server }
  annotations:
    kubernetes.io/egress-bandwidth: "100M"
    kubernetes.io/ingress-bandwidth: "200M"
spec:
  containers:
    - name: iperf
      image: cilium/netperf
      args: ["iperf3", "-s"]
      ports: [{ containerPort: 5201 }]
---
apiVersion: v1
kind: Pod
metadata:
  name: bw-client
  namespace: etl
spec:
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchLabels: { app: bw-server }
          topologyKey: kubernetes.io/hostname
  containers:
    - name: iperf
      image: cilium/netperf
      args: ["sleep", "infinity"]
```

```bash
SERVER_IP=$(kubectl -n etl get pod bw-server -o jsonpath='{.status.podIP}')

# 서버 egress(서버 → 클라이언트) 측정: -R
kubectl -n etl exec bw-client -- iperf3 -R -c $SERVER_IP -t 30
# 기대값: receiver 약 95~100 Mbit/s

# 서버 ingress(클라이언트 → 서버) 측정
kubectl -n etl exec bw-client -- iperf3 -c $SERVER_IP -t 30
# 기대값: receiver 약 200 Mbit/s 근처
```

판정 기준은 receiver 평균이 제한값의 ±10% 안에 들어오는 것입니다. Ingress는 토큰 버킷 버스트 때문에 제한값보다 조금 높게 나올 수 있습니다. 테스트 후에는 `kubectl -n etl delete pod bw-server bw-client`로 정리합니다.

### 5.3 운영 모니터링

| 지표 | 수집 경로 | 볼 것 |
| --- | --- | --- |
| 노드 NIC 송수신량 | node_exporter `node_network_transmit_bytes_total`, `node_network_receive_bytes_total` | ETL 시간대에 NIC 포화가 없어졌는지 |
| 파드별 네트워크 사용량 | cAdvisor `container_network_transmit_bytes_total` | ETL 파드가 제한값 근처에서 평탄해지는지 |
| 드롭 | Hubble `hubble observe --verdict DROPPED`, Cilium `cilium_drop_count_total` | ingress 제한으로 인한 드롭 증가 |
| TCP 재전송 | node_exporter `node_netstat_Tcp_RetransSegs` | ingress 제한·BBR 적용 후 재전송 급증 |
| Job 실행 시간 | kube-state-metrics `kube_job_status_completion_time` - `start_time` | 제한 후 SLA(마감 시각) 초과 여부 |

## 6. 운영 가이드 및 트러블슈팅

기능 활성화와 어노테이션 적용을 분리해서 진행합니다. Bandwidth Manager를 켜도 어노테이션이 없는 파드는 제한받지 않으므로, 활성화 자체의 위험은 Agent 재시작에 한정됩니다.

### 6.1 단계적 롤아웃

1. **개발/스테이징 클러스터:** Bandwidth Manager를 활성화하고 5.2 iperf3 테스트로 제한 동작을 확인합니다.
2. **운영 클러스터 활성화:** 트래픽이 적은 시간에 Helm upgrade와 `rollout restart ds/cilium`을 진행합니다. 이 단계에서는 어노테이션을 넣지 않으므로 트래픽 변화가 없어야 합니다.
3. **대표 ETL Job 1개 적용:** 여유 있는 제한값(예: 관측 피크의 80%)으로 시작해 Job 실행 시간과 노드 NIC 사용량을 1~2회 비교합니다.
4. **전체 ETL 확대:** 티어별 값을 확정하고, 필요하면 4.6의 Kyverno 정책으로 기본값을 강제합니다.
5. **튜닝:** 5.3 지표로 2주간 관찰하고, SLA를 넘기는 Job은 제한을 올리거나 실행 시간대를 분산합니다.

### 6.2 롤백

- **특정 Job만 해제:** 파드 템플릿에서 어노테이션을 지우고 다음 실행부터 적용됩니다. 실행 중인 파드는 `kubectl annotate pod <pod> kubernetes.io/egress-bandwidth-`로 지울 수 있지만, 반영 여부는 5.1 명령으로 확인합니다.
- **기능 전체 해제:** 백업한 values로 되돌립니다.

```bash
helm upgrade cilium cilium/cilium --version 1.18.4 \
  --namespace kube-system \
  --reuse-values \
  --set bandwidthManager.enabled=false
kubectl -n kube-system rollout restart ds/cilium
```

### 6.3 흔한 문제와 해결

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| `bpf bandwidth list`에 파드가 없음 | 어노테이션이 Job/CronJob 레벨에 붙음 | `spec.template.metadata.annotations`로 옮김. `kubectl get pod -o yaml`로 파드에 있는지 확인 |
| 목록에는 있는데 속도가 제한되지 않음 | L7 CiliumNetworkPolicy가 파드 egress를 선택(toFQDNs, HTTP 규칙) | ETL 파드를 L7 정책에서 제외하거나 L3/L4 정책으로 대체 |
| 제한이 특정 NIC에서만 걸림 | ETL 트래픽이 `devices`에 없는 보조 NIC로 나감 | `cilium-dbg status`의 디바이스 목록 확인 후 `devices`에 추가 |
| `BandwidthManager: Disabled` | Agent 미재시작, 커널 미지원, 중첩 네임스페이스 환경 | `rollout restart`, `uname -r`, Agent 로그 확인 |
| Ingress 제한이 동작하지 않음 | 같은 노드에서 오는 트래픽 | 노드 간 트래픽으로 검증. 소스 DB가 같은 노드면 제한 대상 아님 |
| 제한 후 TCP 재전송 급증 | Ingress 토큰 버킷이 초과분을 drop | Ingress 제한을 넓히거나 제거하고 송신 측 egress 제한으로 대체 |
| BBR 활성화 후 혼잡제어 미변경 | 기존 파드는 바뀌지 않음. BBR은 새로 뜨는 파드부터 적용 | 파드 재생성. 커널 5.18+ 및 Host Routing BPF 확인 |
| Job 실행 시간이 크게 늘어남 | 제한값이 너무 낮음 | 4.1 수식으로 재산정, `activeDeadlineSeconds` 조정 |

## 7. I 지역 Target 클러스터 적용 예시 (구간 10G, ETL 1G)

**결론:** W 지역 SRC와 I 지역 Target 클러스터 사이 구간 회선은 10G입니다. ETL이 이 구간에서 쓰는 합계를 1G로 묶고, 그 1G를 동시에 뜨는 Spark executor 수로 나눠 파드별 상한을 겁니다. 흐름도는 [i-region-etl-bandwidth.drawio](./i-region-etl-bandwidth.drawio)(데이터 흐름, 대역폭 제어 적용 지점 2페이지)를 참고합니다.

**데이터 흐름**

1. Airflow가 Spark ETL Job을 실행합니다.
2. Spark executor가 W 지역 SRC 데이터를 가져옵니다. 구간 10G 회선을 지나며, executor 파드 기준으로는 **ingress**입니다.
3. Spark가 결과를 I 지역 AIStor(S3)에 저장합니다. executor 파드 기준으로는 **egress**입니다.
4. Airflow가 StarRocks에 적재 SQL(Broker Load, INSERT FROM FILES)을 보냅니다.
5. StarRocks(shared-data)가 AIStor에서 읽고 테이블 데이터를 AIStor에 씁니다.

**파드별 상한 계산**

```
파드당 상한 = 1G ÷ (Airflow 동시 Spark Job 수 × Job당 executor 수)
```

| 동시 Spark Job | Job당 executor | 파드당 ingress / egress | 구간 합계 |
| --- | --- | --- | --- |
| 1 | 4 | `250M` | 1G |
| 1 | 8 | `125M` | 1G |
| 2 | 4 | `125M` | 1G |

- executor 수가 바뀌면 합계가 1G를 넘습니다. Spark dynamic allocation을 쓰면 `spark.dynamicAllocation.maxExecutors`로 상한을 고정합니다.
- Airflow pool로 이 ETL의 동시 Spark Job 수를 고정합니다(예: pool slot 1).
- driver는 SRC 데이터를 직접 받지 않으므로 작은 값(예: `50M`)만 겁니다.

**Spark 설정 예시 (동시 Job 1개, executor 4개)**

```bash
spark-submit \
  --conf spark.executor.instances=4 \
  --conf spark.dynamicAllocation.enabled=false \
  --conf spark.kubernetes.executor.annotation.kubernetes.io/ingress-bandwidth=250M \
  --conf spark.kubernetes.executor.annotation.kubernetes.io/egress-bandwidth=250M \
  --conf spark.kubernetes.driver.annotation.kubernetes.io/egress-bandwidth=50M \
  ...
```

**주의사항**

- **추출(②)은 ingress 제한:** ingress는 토큰 버킷이 초과분을 버립니다. RTT가 큰 지역 간 회선에서는 재전송이 늘어 실제 처리량이 상한보다 크게 떨어질 수 있습니다. executor 수와 파티션 수(JDBC `numPartitions`, 파일 분할)로 먼저 속도를 맞추고, ingress 제한은 1G를 넘지 않게 막는 보호선으로 둡니다. 5.2 iperf3 테스트를 W ↔ I 구간에서 한 번 실측해 둡니다.
- **NIC 구성:** 외부 경로(W 지역)와 내부 경로(AIStor)가 다른 NIC로 나뉘어 있다면(예: bond0 / bond1) `devices`에 둘 다 넣습니다. 자동 감지는 기본 라우트 NIC만 잡을 수 있습니다.
- **같은 노드의 AIStor:** 같은 노드에 있는 AIStor 파드로 가는 트래픽은 NIC를 거치지 않아 egress 제한이 걸리지 않습니다.
- **StarRocks · AIStor는 제외:** 공용 스토리지와 쿼리 엔진이라 파드 제한을 걸면 다른 사용자까지 느려집니다. StarRocks 적재(④ · ⑤)는 적재 동시성과 리소스 그룹으로 조절합니다.
- **구간 실사용량 확인:** 구간 회선의 실제 사용량은 Cilium이 아니라 네트워크 장비(구간 라우터 인터페이스 카운터)에서 확인해 1G 이내인지 봅니다.

## 8. 체크리스트 및 참고자료

**적용 전**

- [ ] 모든 노드 커널 v5.10 이상(BBR을 쓸 경우 v5.18 이상) 확인
- [ ] ETL 네임스페이스에 L7 CiliumNetworkPolicy(toFQDNs, HTTP 규칙) 없음 확인
- [ ] CNI chaining `bandwidth` 플러그인 미사용 확인
- [ ] Helm values·cilium-config 백업
- [ ] 노드 NIC 용량과 ETL 허용 비율 합의

**적용 중**

- [ ] `bandwidthManager.enabled=true`로 Helm upgrade(`--version 1.18.4` 고정)
- [ ] `rollout restart ds/cilium` 완료 및 `BandwidthManager: EDT with BPF` 확인
- [ ] ETL 파드 템플릿에 어노테이션 추가

**적용 후**

- [ ] `cilium-dbg bpf bandwidth list`에 ETL 파드 등록 확인
- [ ] iperf3 실측이 제한값 ±10% 이내
- [ ] ETL 시간대 노드 NIC 포화 해소, Job SLA 유지 확인

**참고자료**

- [Cilium Bandwidth Manager 공식 문서](https://docs.cilium.io/en/stable/network/kubernetes/bandwidth-manager/): Helm 값, 어노테이션, BBR 요구사항, 제약사항, 검증 절차
- [Isovalent: Cilium 1.18 릴리스 소개](https://isovalent.com/blog/post/cilium-1-18/): 1.18 ingress 대역폭 제한 신규 기능
- [Cilium bandwidth 패키지 소스(pkg.go.dev)](https://beta.pkg.go.dev/github.com/cilium/cilium/pkg/datapath/linux/bandwidth): `bandwidth.cilium.io/priority`와 QoS별 기본 우선순위 상수
- [Cilium 1.18.4 Helm 차트 릴리스](https://newreleases.io/project/artifacthub/helm/cilium/cilium/release/1.18.4): 1.18.4 이미지 및 보안 수정 내역
- [Cilium 1.18.0 릴리스 노트 요약](https://gitea.alexlebens.dev/alexlebens/infrastructure/pulls/1062): 1.18 최소 커널 v5.10
- [ingress 제한의 동일 노드 트래픽 예외 사례](https://pando85.github.io/homelab/troubleshooting/bandwidth-limiting/): 사용자 보고(비공식)
