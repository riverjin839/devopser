## I 지역 Target K8s 클러스터 Cilium Bandwidth Manager 적용 작업 계획서

> 작성일: 2026-11-19 · 대상: I 지역 Target K8s 클러스터 (Cilium 1.18.4)
> 상세 절차: [`cilium-bandwidth-manager-etl-guide.md`](./cilium-bandwidth-manager-etl-guide.md)
> 그림: [`cilium-bandwidth-manager.drawio`](./cilium-bandwidth-manager.drawio) (구조 흐름 · 적용 절차), [`i-region-etl-bandwidth.drawio`](./i-region-etl-bandwidth.drawio) (I 지역 데이터 흐름 · 대역폭 제어 적용 지점)

### 1. 개요

I 지역 Target 클러스터의 ETL Job(Airflow · Spark · StarRocks)이 W 지역 SRC 데이터를 가져와 AIStor에 저장할 때, W ↔ I 구간 회선(10G)에서 ETL 사용량을 1G 이내로 제한하는 게 목표임. Cilium 1.18.4의 Bandwidth Manager를 켜고 Spark 파드에 대역폭 어노테이션을 적용하는 방식으로 진행함.

**작업 목표**

1. Target 클러스터 전 노드에서 Bandwidth Manager 활성화 (`BandwidthManager: EDT with BPF`)
2. ETL이 W ↔ I 구간에서 쓰는 합계를 1G 이내로 유지 (구간 10G의 10%)
3. Cilium 재시작과 ETL 제한 적용 중 서비스 장애 0건, ETL Job SLA 유지

**진행 원칙**

- 기능 활성화(Cilium)와 제한 적용(ETL 어노테이션)을 다른 날로 나눔. 문제가 생겼을 때 원인을 바로 구분하기 위함
- 제한은 ETL 파드(Spark driver · executor, Airflow 태스크 파드)에만 검. StarRocks · AIStor는 여러 사용자가 함께 쓰는 서비스라 제외함
- 운영 작업은 작업창(야간 · 저트래픽 시간)에만 하고, 판정 기준을 못 넘으면 즉시 롤백함

### 2. 현황 및 사전 확인 항목

아래 표의 "현재" 칸은 작업 전 Target 클러스터에서 확인해 채워둬야 함. 확인 안 된 항목이 있으면 작업일을 확정하지 않음.

| 항목 | 현재 | 판정 기준 · 확인 방법 |
| --- | --- | --- |
| Cilium 버전 | 1.18.4 | `cilium version` |
| 노드 커널 | 확인 필요 | 전 노드 v5.10 이상 (`uname -r`). BBR은 이번 범위 아님 |
| 라우팅 모드 · Host Routing | 확인 필요 | `cilium-dbg status`의 Routing · Host Routing 줄 |
| 노드 NIC 구성 | 확인 필요 (예: bond0 외부 · bond1 내부) | W 지역 경로와 AIStor 경로가 지나는 NIC를 모두 `devices`에 넣어야 함 |
| L7 정책 (toFQDNs · HTTP) | 확인 필요 | ETL 네임스페이스 파드를 선택하는 L7 정책이 있으면 제한이 빠짐 |
| CNI chaining bandwidth 플러그인 | 확인 필요 | 사용 중이면 제거 후 진행 |
| Cilium BGP · Graceful Restart | 확인 필요 | BGP 사용 시 재시작 중 경로 철회 여부 확인 |
| Cilium DaemonSet `maxUnavailable` | 확인 필요 | 작업 시 1로 운영 |
| Envoy 분리 여부 | 확인 필요 | 별도 DaemonSet이면 L7 트래픽은 재시작 영향 없음 |
| Spark executor 수 · dynamic allocation | 확인 필요 | 고정 또는 `maxExecutors` 상한 필요 |
| Airflow pool | 확인 필요 | 이 ETL의 동시 Spark Job 수 고정 |
| 구간 회선 모니터링 | 확인 필요 | W ↔ I 구간 라우터 인터페이스 사용량 조회 경로 |

### 3. 작업 범위 및 변경 내역

| 구분 | 대상 | 변경 내용 | 담당 |
| --- | --- | --- | --- |
| Cilium | Helm values | `bandwidthManager.enabled: true`, `bbr: false`, `devices`(NIC가 나뉘면 명시) | 플랫폼팀 |
| Cilium | DaemonSet | `rollout restart ds/cilium` (`maxUnavailable: 1`) | 플랫폼팀 |
| ETL | Spark 제출 설정 | executor `ingress/egress-bandwidth: 250M`, driver `egress-bandwidth: 50M`, executor 4개 고정 | 데이터엔지니어링 |
| ETL | Airflow | ETL 전용 pool slot 1 (동시 Spark Job 1개) | 데이터엔지니어링 |
| ETL | (선택) Kyverno | `workload-type: etl` 파드에 기본 egress 제한 주입 | 플랫폼팀 |
| 제외 | StarRocks · AIStor | 파드 제한 없음. StarRocks는 적재 동시성 · 리소스 그룹으로 조절 | StarRocks 담당 |

**파드당 상한 산정**

```
파드당 상한 = 1G ÷ (동시 Spark Job 수 × Job당 executor 수) = 1G ÷ (1 × 4) = 250M
```

동시 Job 수나 executor 수를 바꾸면 이 값도 다시 계산해 함께 바꿔야 함.

### 4. 단계별 일정

작업일(D-day)은 2장 확인이 끝난 뒤 확정함. 아래는 D-day 기준 상대 일정임.

| 단계 | 시점 | 내용 | 산출물 · 완료 기준 |
| --- | --- | --- | --- |
| 0. 사전 점검 | D-7 ~ D-5 | 2장 항목 확인, 구간 회선 · NIC 사용량 기준선 수집 (ETL 시간대 1주) | 현황 표 완성, 기준선 그래프 |
| 1. 스테이징 검증 | D-5 ~ D-3 | 스테이징에서 활성화 → iperf3 실측(±10%) → 재시작 영향 확인 | 검증 결과서 |
| 2. 작업 승인 | D-2 | 작업 계획 · 롤백 기준 공유, 변경 승인 | 변경 승인 |
| 3. 운영 Cilium 활성화 | D-day 작업창 | Helm upgrade → rolling restart → 전 노드 활성화 확인. 어노테이션은 넣지 않음 | 전 노드 `EDT with BPF`, 서비스 지표 이상 없음 |
| 4. 파일럿 ETL 1개 | D+1 ~ D+2 | 대표 Spark Job 1개에 250M × 4 적용, 1~2회 실행 비교 | 구간 사용량 1G 이내, Job SLA 유지 |
| 5. 전체 ETL 확대 | D+3 ~ D+5 | 나머지 ETL Job · Airflow pool 적용, (선택) Kyverno 정책 | ETL 전체 적용 목록 |
| 6. 안정화 관찰 | D+5 ~ D+19 | 2주간 7장 지표 관찰 후 값 조정 | 결과 보고 · 최종 값 확정 |

### 5. D-day 작업 절차 (운영 Cilium 활성화)

작업창은 2시간으로 잡고, 실제 작업은 1시간 이내, 나머지는 관찰 · 롤백 여유로 둠. 노드 수에 따라 rolling restart 시간이 달라지므로 스테이징 실측으로 다시 계산함.

| 시간 | 작업 | 확인 · Go/No-Go |
| --- | --- | --- |
| T-30분 | 작업 공지, 배포 동결(앱 배포 · ETL 스케줄 일시 중지) | 진행 중인 ETL Job 없음 |
| T+0 | 사전 상태 확인: `cilium status --wait`, 노드 · 파드 상태 | 전 Agent 정상이면 Go |
| T+5분 | 백업: `helm get values`, `cilium-config` ConfigMap | 백업 파일 2개 확인 |
| T+10분 | `maxUnavailable: 1` 확인 · 설정 | |
| T+15분 | `helm upgrade --version 1.18.4 --reuse-values -f bandwidth-values.yaml` | ConfigMap `enable-bandwidth-manager: "true"` |
| T+20분 | `kubectl -n kube-system rollout restart ds/cilium`, `rollout status` 관찰 | 노드별 재시작 시 앱 에러율 · Hubble drop 증가 없음 |
| 재시작 완료 후 | 전 노드 `cilium-dbg status \| grep BandwidthManager` | 전 노드 `EDT with BPF [<NIC>]`, NIC가 계획과 일치 |
| 완료 후 30분 | 서비스 지표 관찰, 배포 동결 해제 | 이상 없으면 작업 종료 |

이상이 보이면 `kubectl -n kube-system rollout pause ds/cilium`으로 멈추고 8장 롤백 기준에 따라 판단함.

### 6. 운영 영향도

Cilium Agent 재시작 중에도 기존 연결은 대부분 유지됨(eBPF 프로그램 · 맵이 커널에 남아 있음). 영향은 재시작 중 새로 일어나는 일에 집중됨.

| 항목 | 영향 | 대응 |
| --- | --- | --- |
| 새 파드 생성 | 재시작 중인 노드에서 `ContainerCreating` 대기 | 배포 동결, ETL 스케줄 일시 중지 |
| 정책 · Service 변경 | 재시작 동안 반영 지연 | 작업창 중 변경 금지 |
| DNS (toFQDNs 정책 사용 시) | DNS 질의 실패 · 지연 가능 | 사용 여부 사전 확인, 해당 서비스 담당자 공지 |
| Cilium BGP | Graceful Restart 미설정 시 경로 철회 | 사전 확인, 미설정이면 별도 검토 후 진행 |
| NIC qdisc 교체 | FQ로 바뀌는 순간 짧은 지연 · 재정렬 가능 | 저트래픽 시간 작업 |
| ETL 제한 적용 후 | Job 실행 시간 증가 (상한 1G) | 파일럿으로 SLA 확인 후 확대 |

### 7. 검증 기준

| 구분 | 기준 | 확인 방법 |
| --- | --- | --- |
| 활성화 | 전 노드 `BandwidthManager: EDT with BPF` | `cilium-dbg status` |
| 제한 등록 | ETL 파드가 Ingress · Egress 250M으로 등록 | `cilium-dbg bpf bandwidth list` |
| 실측 | iperf3 receiver 평균이 제한값 ±10% | 가이드 5.2 |
| 구간 사용량 | ETL 시간대 W ↔ I 구간 사용량 중 ETL 몫 1G 이내 | 구간 라우터 인터페이스 카운터 |
| 서비스 영향 | 작업 전후 앱 에러율 · 지연 변화 없음 | 기존 서비스 대시보드 |
| ETL SLA | Job 완료 시각이 마감 이내 | kube-state-metrics, Airflow 실행 이력 |
| 재전송 · 드롭 | ETL 노드 TCP 재전송 · Hubble drop 급증 없음 | node_exporter, Hubble |

### 8. 롤백 계획

| 상황 | 판단 기준 | 조치 | 소요 |
| --- | --- | --- | --- |
| Cilium 재시작 중 장애 | 앱 에러율 급증, 노드 Agent 기동 실패 | `rollout pause` → 원인 확인 → `bandwidthManager.enabled=false`로 Helm upgrade 후 재시작 | 노드 수 × 재시작 시간 |
| 활성화 실패 | `BandwidthManager: Disabled` 노드 존재 | 해당 노드 커널 · NIC 확인. 해결 안 되면 기능 해제 | 30분 |
| 파일럿 ETL SLA 초과 | 마감 시각 초과 또는 실행 시간 2배 이상 | 해당 Job 어노테이션 제거, executor · 상한 값 재산정 | 다음 실행부터 |
| 재전송 급증 | ETL 노드 재전송이 기준선 대비 크게 증가 | ingress 제한 제거, executor · 파티션 수로만 제어 | 다음 실행부터 |

### 9. 역할 및 연락 체계

| 역할 | 담당 | 범위 |
| --- | --- | --- |
| 작업 총괄 · 승인 | 확인 필요 | 작업 승인, Go/No-Go 판단 |
| Cilium 작업 | 플랫폼팀 (확인 필요) | Helm upgrade, 재시작, 활성화 확인, 롤백 |
| ETL 적용 | 데이터엔지니어링 (확인 필요) | Spark · Airflow 설정, 파일럿 · 확대 |
| StarRocks | StarRocks 담당 (확인 필요) | 적재 동시성 · 리소스 그룹 점검 |
| 네트워크 | 네트워크팀 (확인 필요) | W ↔ I 구간 사용량 모니터링 |
| 서비스 모니터링 | 각 서비스 담당 | 작업창 중 에러율 · 지연 확인 |

### 10. 리스크 및 대응

| 리스크 | 영향 | 대응 |
| --- | --- | --- |
| ETL 트래픽이 `devices`에 없는 NIC로 나감 | 제한이 걸리지 않음 | 사전에 NIC 구성 확인, 필요 시 `devices` 명시 |
| L7 정책이 ETL 파드를 선택 | 제한이 조용히 빠짐 | 사전 확인, ETL 파드 제외 또는 L3/L4 정책으로 대체 |
| executor 수 변동 (dynamic allocation) | 합계가 1G 초과 | executor 수 고정 또는 `maxExecutors` 상한 |
| Airflow 동시 Job 증가 | 합계가 1G 초과 | ETL 전용 pool slot 고정 |
| ingress 제한으로 WAN 재전송 증가 | 실제 처리량이 상한보다 크게 낮아짐 | executor · 파티션 수로 1차 제어, ingress는 상한 보호용 |
| 같은 노드 AIStor로 저장 | egress 제한 미적용 | 구간 사용량(추출)에는 영향 없음. 필요 시 배치 분리 |
| Job 실행 시간 증가 | 후속 작업 지연 | 파일럿에서 SLA 확인, 스케줄 조정 |

### 11. 사전 준비 및 산출물

**사전 준비**

- [ ] 2장 현황 표 완성 (전 항목 "현재" 칸 채움)
- [ ] ETL 시간대 구간 회선 · NIC 사용량 기준선 1주 수집
- [ ] 스테이징 검증 완료 (활성화, iperf3, 재시작 영향)
- [ ] `bandwidth-values.yaml` · Spark 제출 설정 · Airflow pool 변경안 리뷰
- [ ] 작업 공지 · 변경 승인 · 담당자 연락처 확정

**산출물**

- 현황 표 · 기준선 그래프
- 스테이징 검증 결과서
- D-day 작업 기록 (명령 · 시간 · 확인 결과)
- 안정화 관찰 결과 보고 · 최종 상한 값
