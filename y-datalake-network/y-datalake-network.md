## Y지역 datalake 네트워크 아키텍처 - Cilium BGP · ClusterMesh · Cisco EVPN 설계

> **목표** : Com K8s + AIStor K8s 를 Cilium ClusterMesh 로 묶는 300노드 이상 신규 datalake 의 네트워크를, Cilium BGP 와 Cisco EVPN 패브릭 관점에서 한 장으로 설계함

- 출처 : Cilium 공식 문서(BGP Control Plane, ClusterMesh Service Affinity, Egress Gateway), Cilium 1.19 · 1.20 릴리즈 노트, Cisco Nexus 9000 VXLAN BGP EVPN 설계 가이드, Cisco NX-OS Calico 설계 백서, MinIO Sidekick 문서
- 기준 버전 : Cilium 1.20.4 (2026-11 기준 최신 태그 확인), NX-OS 버전 미정 (NW팀 확인 필요)

---

## 1. 개요

요건을 설계 결정으로 바꾸면 아래와 같음.

| 요건 | 설계 반영 |
|---|---|
| Com K8s + AIStor K8s 분리 | 클러스터 2개, ClusterMesh(KVStoreMesh) 로 Pod IP 직결 |
| leaf 100G, spine · super spine 400G | 5단 Clos. 패브릭 Pod 3개 (Com 2, Storage 1) |
| Cisco EVPN, ECMP | VXLAN EVPN, VRF 별 L3VNI, Type-5 경로로 VIP ECMP |
| IGP 미사용 | underlay · overlay 모두 eBGP (RFC 7938 방식) |
| public · private 분리 | 노드 NIC 분리 와 VRF 분리. 광고 대상도 피어별로 분리 |
| iBGP · eBGP 선택 | 노드 ↔ leaf 는 eBGP, 클러스터별 ASN 1개 |
| Egress Gateway 고가용 | 클러스터별 Gateway 노드 그룹 + Egress IP BGP 광고 |
| 어느 위치 client 든 AIStor 분산 | 내부 = 소켓 LB(Global Service), 외부 = VIP /32 ECMP |
| client 인입 = Super Spine · Spine · Leaf · 동일 망 | VIP 는 eTP Cluster 와 Maglev, DSR(Geneve). 가까운 노드로 들어와도 백엔드는 전체 Pod 중에서 고름 |

<!-- diagram: ydl-01-overview.html -->

- 동서(Pod 간, AIStor EC 복제) 트래픽 = PRIVATE VRF
- 남북(외부 client, Egress) 트래픽 = PUBLIC VRF, Border Leaf 로만 출입
- AIStor 는 노드마다 Pod 1개(DaemonSet) → 모든 스토리지 노드가 VIP 를 광고하는 구조
- client 는 Super Spine 보다 같은 Spine · 같은 Leaf · 동일 망에서 더 많이 들어옴 → BGP 는 가까운 노드를 먼저 고르므로 패브릭 ECMP 만으로는 균등 분산이 안 됨

**패브릭은 가까운 노드까지만 데려오고, 어느 AIStor Pod 가 받을지는 Cilium Maglev 가 정한다.**

---

## 2. 개념 정리

### 2-1. 패브릭 구조와 규모

300노드를 기준으로 잡은 가정치임. 랙당 대수, 장비 포트 수는 NW팀과 다시 맞춰야 함.

| 구분 | 구성 | 수량 (가정) |
|---|---|---|
| Com K8s | 14랙 × 18대 | 252노드 |
| AIStor K8s | 6랙 × 8대 | 48노드 |
| 패브릭 Pod | Com-1 (랙 1~7), Com-2 (랙 8~14), Storage (스토리지 6랙 + Border Leaf) | 3 Pod |
| Leaf | 랙당 2대 | 40대 + Border 2대 |
| Spine | Pod 당 4대, 400G | 12대 |
| Super Spine | 400G | 4대 |

#### 2-1-1. 포트와 과다 구독(oversubscription)

| 계층 | 다운링크 | 업링크 | 비율 |
|---|---|---|---|
| Com Leaf | 18대 × (private 1 + public 1) = 36 × 100G | 8 × 400G | 1.1 : 1 (private 만 보면 0.6 : 1) |
| Storage Leaf | 8대 × (private 2 + public 1) = 24 × 100G | 8 × 400G | 0.75 : 1 |
| Spine | Leaf 14대 × 2 = 28 × 400G | Super Spine 4대 × 4 = 16 × 400G | 1.75 : 1 |
| Super Spine | Spine 12대 × 4 = 48 × 400G | - | - |

- S3 대량 읽기는 Com Pod → Storage Pod 로 Super Spine 을 반드시 지남. Spine 비율은 2 : 1 을 넘기지 않음
- Border Leaf 를 Storage Pod 에 둠 → 외부 S3 client 트래픽이 Super Spine 을 안 거침
- MTU = 노드 9000, 패브릭 9216 (VXLAN 50B 여유)

#### 2-1-2. IGP 없는 EVPN

- underlay = eBGP 로 루프백(router-id, VTEP)만 교환함. OSPF · IS-IS 없음
- overlay = eBGP EVPN. Spine · Super Spine 은 VTEP 없는 경로 중계(route server) 역할
- 장애 감지는 패브릭 링크에 BFD 를 붙여 IGP 수준으로 맞춤
- "IGP ignore" 를 iBGP EVPN 의 `bestpath igp-metric ignore`(VTEP 거리 무시) 로 쓴 거라면 : Super Spine · Spine 인입은 그것으로 풀리지만 같은 leaf 인입 쏠림은 안 풀림 (3-2 참고). NX-OS 지원 여부는 NW팀 확인 필요

> 주의 : Type-5 경로의 RD 는 leaf 별로 고유(rd auto)해야 함. RD 가 같으면 Spine 에서 경로가 하나로 합쳐져 ECMP 가 사라짐

### 2-2. Public · Private 분리

노드 한 대가 NIC 4포트(Storage 는 private 2포트 추가)를 쓰고, 포트마다 leaf 하나에 L3 로 붙음. vPC · LACP 를 쓰지 않음.

<!-- diagram: ydl-02-nw-split.html -->

| 항목 | PRIVATE | PUBLIC |
|---|---|---|
| 용도 | Pod 간, ClusterMesh, AIStor EC 복제, kubelet | 외부 client 의 VIP 접근, Egress SNAT |
| leaf 쪽 | VRF PRIVATE, leaf 별 전용 서브넷 | VRF PUBLIC, leaf 별 전용 서브넷 |
| Cilium 광고 | PodCIDR, 노드 루프백 /32, AIStor VIP /32 | LoadBalancer IP /32, Egress IP /32 |
| 노드 라우팅 | 내부 대역(예 : 10.0.0.0/8) → private 2경로 ECMP | 기본 경로 → public 2경로 ECMP |

- Cilium BGP 는 경로를 받아 커널에 넣지 않음(OSS 기준) → 노드 라우팅은 정적 경로로 고정
- 외부 client 응답은 기본 경로라서 PUBLIC 으로 나감. VIP 로 들어온 길과 나가는 길이 같아짐
- 노드 IP(K8s InternalIP) = 루프백 /32. private 두 세션으로 같이 광고 → 링크 하나가 죽어도 노드 IP 유지
- 루프백 광고는 1.19 의 Interface 광고, 세션 소스 IP 고정은 1.19 의 sourceInterface 로 처리함

> 주의 : 외부 대역 중 사내망 일부가 10.0.0.0/8 안에 있으면 응답이 PRIVATE 로 새서 비대칭이 됨. 내부 대역 정적 경로는 Pod · 노드 · 서비스 대역만 좁게 잡음

### 2-3. BGP 설계 (ASN, iBGP vs eBGP)

#### 2-3-1. ASN 계획

| 대상 | ASN | 비고 |
|---|---|---|
| Super Spine | 65000 | 4대 공통 |
| Spine | Pod 별 65011 · 65012 · 65013 | Pod 안 4대 공통 |
| Leaf 쌍 | 랙별 4-byte 사설 (4200001001 ~) | leaf 2대도 서로 다른 ASN 가능, 랙 단위면 충분 |
| Com 노드 | 65101 | 클러스터 전체 공통 |
| AIStor 노드 | 65102 | 클러스터 전체 공통 |
| Border 외부 피어 | 기존 사내 ASN | 외부와는 eBGP |

#### 2-3-2. 노드 ↔ leaf 는 eBGP

| 방식 | 장점 | 단점 | 언제 쓰나 |
|---|---|---|---|
| eBGP (노드 = 클러스터 ASN) | 루프 방지 자동, leaf 는 prefix 피어링 한 줄, Cisco 권장 형태 | AS-path 가 leaf 마다 달라 multipath-relax 필수 | 이번 설계 기본안 |
| iBGP (노드 = leaf ASN) | AS-path 같음 | leaf 를 RR 로 둬야 하고 next-hop-self 관리 필요, 실수 시 경로 누락 | 패브릭이 iBGP EVPN 일 때만 |
| 노드별 ASN | 노드 단위 경로 추적 쉬움 | ASN 300개 관리, 설정 생성 자동화 필요 | 거의 안 씀 |

- leaf 는 `neighbor <랙 서브넷>/26 remote-as 65101` 형태의 prefix 피어링으로 노드 설정을 개별로 안 넣음
- 피어별 수신 필터 : PRIVATE = Pod 대역, 노드 루프백, AIStor VIP 풀 /32. PUBLIC = LB 풀 · Egress 풀 /32. maximum-prefix 로 상한을 둠
- graceful restart 를 켬 → cilium-agent 재시작 때 VIP 경로가 바로 빠지지 않음

#### 2-3-3. VIP 가 ECMP 로 퍼지는 경로

<!-- diagram: ydl-03-vip-ecmp.html -->

- Storage leaf 1대 = 노드 8개 경로를 ECMP 로 가짐
- 원격 Com leaf = VIP 에 대해 Storage leaf 12대(VTEP 12개)를 ECMP 로 가짐 → 2단 분산
- 모든 계층에 `maximum-paths 64` 와 `bestpath as-path multipath-relax` 가 있어야 함. 한 곳이라도 빠지면 그 지점에서 경로가 1개로 줄어듦

> 주의 : leaf 쌍을 vPC 로 묶는 랙이 있으면 `advertise-pip` 를 켜야 함. 안 켜면 두 leaf 가 같은 가상 VTEP 로 광고돼 ECMP 폭이 반으로 줄어듦

---

## 3. AIStor 멀티 Pod 로드밸런싱

client 위치에 따라 경로를 두 갈래로 나눔.

<!-- diagram: ydl-04-aistor-lb.html -->

| 경로 | client 위치 | 분산 지점 | 분산 단위 |
|---|---|---|---|
| A. 소켓 LB | Com K8s 안 Pod (Spark, Trino, Airflow) | Cilium 소켓 LB 가 connect() 때 AIStor Pod IP 를 고름 | 연결 |
| B. VIP | K8s 밖 서버, 같은 랙 · 같은 Pod · 다른 Pod · 외부 | 패브릭이 가까운 노드로 보내고, 그 노드의 Maglev 가 전체 Pod 중 하나를 고름 | 연결 |

- 경로 A 는 원래 위치와 무관함. 토폴로지를 안 보고 전체 백엔드 중에서 고름

### 3-1. 경로 A - Global Service

- AIStor 쪽 Service 에 `service.cilium.io/global: "true"`, Com 쪽에 같은 이름 · 네임스페이스의 빈 Service 를 둠
- Com 클러스터에는 AIStor Pod 가 없어서 affinity 는 의미 없음. 기본값(none) 그대로
- VIP · NAT 없이 Pod IP 로 바로 감 → 홉 1개, client IP 그대로 보임

### 3-2. 인입 위치별로 BGP 가 고르는 경로

eBGP 패브릭에서는 AS-path 가 짧은 경로가 이김. client 가 들어오는 위치마다 VIP 경로 수가 달라짐.

<!-- diagram: ydl-06-ingress-position.html -->

| 인입 위치 | VIP 경로 선택 | 받는 노드 | 쏠림 |
|---|---|---|---|
| Super Spine (다른 Pod, Border) | Storage leaf 12대 경로의 AS-path 길이가 같음 → ECMP | 48노드 | 없음 |
| Spine (Storage Pod 안 다른 leaf) | 같은 Pod leaf 경로 길이가 같음 → ECMP | 48노드 | 없음 |
| Leaf (스토리지 랙과 같은 leaf) | 로컬 노드 경로 AS-path 1 vs 원격 3 → 로컬만 선택 | 그 랙 8노드 | 있음 |
| 동일 망 (노드와 같은 서브넷) | 게이트웨이가 같은 leaf 라 Leaf 인입과 같음 | 그 랙 8노드 | 있음 |

- iBGP EVPN 패브릭이어도 같음. 로컬 노드 경로(eBGP)가 원격 경로(iBGP)보다 우선이라 로컬만 남음
- eTP Local 이면 받은 노드의 로컬 Pod 가 그대로 처리함 → 같은 랙 client 가 많을수록 그 랙 8노드만 TLS · EC 연산을 떠안음

> 주의 : 동일 망 · 같은 leaf client 비중이 큰 환경에서 eTP Local 을 쓰면 랙 단위 핫스팟이 생김. 이전 기본안(eTP Local)을 아래 3-3 으로 바꿈

### 3-3. VIP 기본안 - eTP Cluster, Maglev, DSR(Geneve)

| 방식 | 장점 | 단점 | 이번 판단 |
|---|---|---|---|
| eTP Local | 홉 없음, client IP 보존 | 인입 위치 쏠림이 백엔드 쏠림으로 그대로 이어짐, ECMP 재해시 때 끊김 | Super Spine 인입만 있는 VIP 에만 사용 |
| eTP Cluster, Maglev, DSR(Geneve) | 어느 노드로 들어와도 같은 백엔드 계산 → 위치 쏠림과 재해시에 강함. 응답은 백엔드가 client 로 바로 보냄 | 요청 방향 1홉 추가 (PRIVATE 망), Geneve 헤더만큼 MTU 여유 필요 | 기본안 |
| eTP Cluster, Maglev, SNAT | 패브릭 요구 없음 | client IP 사라짐, 응답도 인입 노드를 거침 | DSR 검증 실패 시 대안 |

- 인입 노드는 eBPF 로 전달만 함 → 쏠려도 부담이 작음. 실제 S3 처리는 Maglev 가 고른 Pod 가 함
- 같은 대역 · 같은 leaf client 는 eBGP 로컬 경로만 보여 그 랙 노드로만 들어옴. 단, 들어온 노드에서 백엔드를 전체 Pod 중에 다시 고르므로 처리 Pod 는 랙에 묶이지 않음 (3-7 표)
- GET 응답(대용량)은 DSR 로 인입 노드를 안 거침. PUT 은 요청이 인입 노드를 한 번 더 지나감 → 같은 랙 대량 업로드 client 는 경로 A 나 Sidekick 으로 돌림
- DSR 전달은 IP 옵션 방식이 아니라 Geneve 방식을 씀. IP 옵션 패킷은 스위치에서 소프트웨어 처리로 빠져 SYN 이 버려진 사례가 있음
- native routing 에서 Geneve DSR 을 쓰려면 tunnelProtocol 을 geneve 로 명시해야 함 (자동 지정 안 함)
- VIP 는 모든 AIStor 노드가 광고함 → DSR 응답의 출발지(VIP)가 각 leaf 에서 정상 경로로 보임. 그래도 leaf uRPF 는 loose 또는 끔

### 3-4. 동일 망 client 규칙

- VIP 풀은 노드 · client 서브넷과 겹치지 않는 별도 라우팅 대역으로 둠 → ARP 불필요, Cilium L2 Announcement 미사용
- VIP 를 PUBLIC · PRIVATE 두 VRF 에 모두 광고함 → PRIVATE 서브넷에 붙은 서버도 VIP 로 바로 접근
- 응답은 client 대역 기준으로 나감 (PUBLIC client = 기본 경로, PRIVATE client = 내부 정적 경로) → 들어온 VRF 로 대칭 복귀

### 3-5. 패브릭 쪽 보조 (선택)

- iBGP EVPN 패브릭이면 leaf VRF 에 `maximum-paths mixed` 를 넣어 로컬 eBGP 경로와 원격 EVPN 경로를 같이 ECMP 로 묶을 수 있음
- 단, 로컬 노드 8개 경로와 원격 VTEP 11개 경로가 같은 비중으로 묶여 노드 단위로는 여전히 고르지 않음 → Maglev 를 대신하지 못함
- eBGP 패브릭은 AS-path 길이가 달라 이 방법이 안 먹힘. 이번 설계는 패브릭을 건드리지 않고 Maglev 로 해결함

> 주의 : ECMP 해시는 5-tuple(L4 포트 포함)을 유지해야 함. 2-tuple(IP 만)로 바꾸면 SNAT 된 client(Egress GW, NAT 뒤 서버)의 연결이 전부 노드 하나로 몰림

### 3-6. 보조 수단

- Sidekick : client 옆 사이드카 LB, least-connection 과 헬스체크. 같은 랙 대량 업로드, 연결 수가 적고 큰 Spark 잡 보완용
- 1.20 의 EndpointSlice 가중치(`service.cilium.io/weight`, 0 = 드레인) : 점검 노드의 AIStor Pod 를 단계적으로 빼는 용도
- 점검 순서 : 가중치 0 으로 드레인 → 노드 cordon → 작업. Maglev 라 남은 연결은 다른 노드로 와도 같은 백엔드로 감

### 3-7. 부하분산 검증 계획

같은 leaf · 동일 망 client 는 그 랙 노드 8대로만 들어옴. 들어온 노드가 Maglev 로 전체 48개 Pod 중 하나에 넘기는지, 그리고 그 결과가 노드별로 고른지 수치로 확인함.

| 단계 | 같은 leaf client 의 패킷이 가는 곳 | eTP Local | eTP Cluster 와 Maglev |
|---|---|---|---|
| 1. leaf 경로 선택 | eBGP 로컬 경로만 남음 → 그 랙 노드 8대 | 같음 | 같음 |
| 2. 노드 도착 후 | 백엔드 선택 범위 | 자기 노드 Pod 1개 | 전체 Pod 48개 |
| 3. 실제 S3 처리 | 처리 Pod 분포 | 랙 8개 Pod 에 몰림 | 48개에 고르게 퍼짐 |
| 4. 응답 | 응답 경로 | 같은 노드 | 처리 Pod 가 client 로 직접 (DSR) |

- 백엔드를 전체에서 고르려면 이 Service 에 `trafficDistribution`(PreferSameNode · PreferSameZone) 을 넣지 않음. 넣으면 로컬 우선으로 바뀌어 eTP Local 과 같은 쏠림이 다시 생김
- eTP Cluster 에서는 로컬 Pod 유무와 상관없이 모든 AIStor 노드가 VIP 를 광고함

#### 3-7-1. 시험 조합

| 시험 | client 위치 | 부하 | 비교 대상 |
|---|---|---|---|
| T1 | Super Spine 쪽 (Com Pod 랙) | GET 64MiB, 동시 64 | eTP Local vs Cluster+Maglev+DSR |
| T2 | 같은 Pod 다른 leaf | 같음 | 같음 |
| T3 | 스토리지와 같은 leaf | 같음 | 같음 |
| T4 | 노드와 같은 서브넷 | 같음 | 같음 |
| T5 | 같은 leaf | PUT 256MiB, 동시 64 | DSR vs SNAT 폴백 |
| T6 | 4개 위치 동시 | GET · PUT 혼합 | 기본안만 |
| T7 | T6 진행 중 | AIStor 노드 1대 강제 종료 | 끊긴 연결 비율 |

```bash
# 개념 코드 : 위치마다 client 서버에서 실행, VIP 는 AIStor LB IP
warp get --host 10.50.0.10:443 --tls \
  --access-key "$AK" --secret-key "$SK" \
  --obj.size 64MiB --concurrent 64 --duration 10m
warp put --host 10.50.0.10:443 --tls \
  --access-key "$AK" --secret-key "$SK" \
  --obj.size 256MiB --concurrent 64 --duration 10m
```

#### 3-7-2. 보는 지표

| 지표 | 수집 위치 | 확인 내용 |
|---|---|---|
| 노드별 S3 요청 수 | AIStor Prometheus 메트릭 (노드 라벨별) | 백엔드 분산 편차 |
| 노드별 NIC rx · tx | node-exporter, public · private 포트별 | 인입 노드 쏠림, DSR 우회 여부 |
| 노드별 CPU | node-exporter | TLS · EC 연산 편차 |
| leaf · spine 업링크 카운터 | NX-OS 인터페이스 카운터 | ECMP 링크 분산, 해시 쏠림 |
| VIP 경로 수 | `show ip route vrf PUBLIC <VIP>` | 위치별 next-hop 수 (3-2 표와 일치) |
| 전달 경로 | Hubble flow (인입 노드 → 백엔드) | Maglev 가 원격 Pod 로 넘기는지 |

#### 3-7-3. 판정 기준 (초안)

- 노드별 S3 요청 수 편차 : 평균 대비 ±10% 이내 (T1~T4 모두)
- 인입 노드 public tx : DSR 이면 GET 응답 바이트가 거의 안 보여야 함. 보이면 SNAT 로 동작 중
- 인입 노드 NIC 사용률 : 랙 간 2배 이내 (T6)
- 노드 1대 종료 시 끊긴 연결 : 전체의 1/48 수준 이하. 다른 노드 연결까지 끊기면 Maglev 테이블 · 재해시 설정 재점검
- 기준 미달 시 순서 : DSR 동작 확인 → 해시 seed 분리 → 같은 leaf 대량 client 경로 A · Sidekick 이전

### 3-8. Client 유형별 트래픽 플로우

토폴로지 모양으로 그린 요청 경로임. 진한 선 = 요청, 점선 = 응답 시작점.

| 유형 | 요청 경로 | 백엔드 선택 | 응답 경로 | VRF |
|---|---|---|---|---|
| ① Com Pod | Pod → Com Leaf → Com Spine → Super Spine → Storage Spine → Storage Leaf → AIStor Pod | 소켓 LB (connect 시점) | 같은 경로 역방향 | PRIVATE |
| ② 다른 Pod 서버 | 서버 → Com Leaf → Com Spine → Super Spine → Storage Spine → Storage Leaf(12개 ECMP) → 인입 노드 | 인입 노드 Maglev → Geneve 로 백엔드 노드 | 백엔드 → 자기 Leaf → Spine → Super Spine → client (DSR) | PUBLIC |
| ③ 외부 · 같은 Pod 서버 | client → Border(또는 Service) Leaf → Storage Spine → Storage Leaf(ECMP) → 인입 노드 | 인입 노드 Maglev | 백엔드 → 자기 Leaf → Storage Spine → Border Leaf → client | PUBLIC |
| ④ 같은 Leaf · 동일 망 서버 | 서버 → Storage Leaf A → 랙 A 노드 8대 중 1대 (로컬 경로만) | 인입 노드 Maglev → Geneve 로 Spine 거쳐 다른 랙 | 백엔드 → Leaf B → Storage Spine → Leaf A → client | PUBLIC 또는 PRIVATE |

<!-- diagram: ydl-07-flow-pod.html -->

<!-- diagram: ydl-08-flow-superspine.html -->

<!-- diagram: ydl-09-flow-spine.html -->

<!-- diagram: ydl-10-flow-sameleaf.html -->

- ① 은 VIP 를 안 거침. 백엔드 Pod IP 로 바로 가서 인입 노드가 없음
- ②·③ 은 패브릭 ECMP 로 인입 노드부터 고르게 퍼짐. Maglev 는 인입 노드가 바뀌어도 같은 백엔드를 고르는 역할
- ④ 만 인입 노드가 랙 A 8대로 묶임. 그래도 백엔드는 48개 중에서 고르므로, 요청은 Spine 을 한 번 더 왕복함 (같은 랙 백엔드가 걸리면 Spine 을 안 거침)
- 같은 랙 Pod 를 선호하게 하면 ④ 의 Spine 왕복은 줄지만 랙 쏠림이 다시 생김. 이번 설계는 균등 분산을 우선함

---

## 4. Egress Gateway 고가용

<!-- diagram: ydl-05-egress-gw.html -->

| 항목 | Cilium OSS (1.20) | Isovalent Enterprise |
|---|---|---|
| 다중 Gateway | `egressGateways` 목록 지원. 엔드포인트별로 Gateway 1개 고정 | Gateway 그룹 지정 |
| 장애 시 | 노드 매칭이 바뀌면 재할당. 재할당 때 기존 연결 끊김. 노드 장애 동작은 문서에 없음 | 헬스 기반 자동 페일오버 |
| ClusterMesh | Gateway 는 Pod 와 같은 클러스터에 있어야 함 | 동일 |
| 전제 | kube-proxy 대체, BPF masquerade, identity = crd | 동일 |

- 클러스터마다 Gateway 노드 그룹을 따로 둠. Com = 4대 (2랙 분산), AIStor = 2대 (복제 · KMS 용)
- Egress IP 는 Gateway 노드 루프백(또는 dummy)에 두고 BGP Interface 광고로 PUBLIC VRF 에 /32 로 올림 → 응답 복귀 경로 확보
- 외부 방화벽은 Egress IP 개별이 아니라 Egress 풀(/29 등) 단위로 허용 → Gateway 교체 시 방화벽 변경 없음
- OSS 에서 "resilient" 를 맞추려면 Gateway 노드 헬스를 보고 노드 라벨을 떼는 자동화가 필요함

> 주의 : OSS 다중 Gateway 의 노드 장애 동작은 문서에 정의돼 있지 않음. Gateway 노드 강제 종료 시 재할당 시간과 끊김 범위를 PoC 로 먼저 측정해야 함

---

## 5. 설정 예시

### 5-1. Cilium Helm values (핵심만)

```yaml
# 두 클러스터 공통, cluster.name · id · Pod 대역만 다름
cluster:
  name: ydl-com          # AIStor 쪽은 ydl-aistor
  id: 11                 # AIStor 쪽은 12
routingMode: native
ipv4NativeRoutingCIDR: 10.64.0.0/11   # 두 클러스터 Pod 대역을 모두 포함
autoDirectNodeRoutes: false           # L3 패브릭이라 노드 간 직접 경로 불필요
kubeProxyReplacement: true
bpf:
  masquerade: true                    # Egress GW 전제
tunnelProtocol: geneve                # Geneve DSR 전달용 (터널 모드 아님)
loadBalancer:
  algorithm: maglev
  mode: hybrid                        # TCP = DSR, UDP = SNAT
  dsrDispatch: geneve                 # IP 옵션 대신 Geneve 로 전달
bgpControlPlane:
  enabled: true
egressGateway:
  enabled: true
identityAllocationMode: crd
clustermesh:
  useAPIServer: true
  apiserver:
    kvstoremesh:
      enabled: true
    service:
      type: LoadBalancer              # PRIVATE 쪽 LB 풀에서 IP 할당
```

### 5-2. BGP v2 리소스 (개념 코드)

```yaml
# 랙 단위로 생성 : 피어 주소가 랙 서브넷의 leaf SVI 라서 랙마다 다름
apiVersion: cilium.io/v2
kind: CiliumBGPClusterConfig
metadata:
  name: com-rack01
spec:
  nodeSelector:
    matchLabels: { topology.ydl/rack: r01 }
  bgpInstances:
  - name: com
    localASN: 65101
    peers:
    - { name: priv-a, peerASN: 4200001001, peerAddress: 10.10.1.1,  peerConfigRef: { name: private } }
    - { name: priv-b, peerASN: 4200001001, peerAddress: 10.10.1.65, peerConfigRef: { name: private } }
    - { name: pub-a,  peerASN: 4200001001, peerAddress: 10.30.1.1,  peerConfigRef: { name: public } }
    - { name: pub-b,  peerASN: 4200001001, peerAddress: 10.30.1.65, peerConfigRef: { name: public } }
---
apiVersion: cilium.io/v2
kind: CiliumBGPPeerConfig
metadata:
  name: private
spec:
  gracefulRestart: { enabled: true, restartTimeSeconds: 120 }
  timers: { keepAliveTimeSeconds: 3, holdTimeSeconds: 9 }
  families:
  - afi: ipv4
    safi: unicast
    advertisements:
      matchExpressions:                       # PodCIDR · 루프백 + VIP
      - { key: advertise, operator: In, values: [ private, vip ] }
---
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: aistor-vip
  labels: { advertise: vip }                # private · public PeerConfig 둘 다 이 라벨을 선택
spec:
  advertisements:
  - advertisementType: Service
    service:
      addresses: [ LoadBalancerIP ]
    selector:
      matchLabels: { ydl/expose: vip }      # PUBLIC · PRIVATE 피어 둘 다에 같은 광고를 붙임
```

### 5-3. AIStor Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: minio-global
  namespace: aistor
  annotations:
    service.cilium.io/global: "true"        # 경로 A : Com 에서 Pod IP 직결
  labels:
    ydl/expose: vip                         # 경로 B : 두 VRF 에 VIP 광고
spec:
  type: LoadBalancer
  externalTrafficPolicy: Cluster            # 인입 노드와 무관하게 Maglev 로 전체 Pod 선택
  selector: { app: aistor }
  ports:
  - { name: s3, port: 443, targetPort: 9000 }
```

### 5-4. Egress Gateway 정책 (개념 코드)

```yaml
apiVersion: cilium.io/v2
kind: CiliumEgressGatewayPolicy
metadata:
  name: tenant-to-external
spec:
  selectors:
  - podSelector:
      matchLabels: { io.kubernetes.pod.namespace: team-a }
  destinationCIDRs: [ 0.0.0.0/0 ]
  excludedCIDRs: [ 10.0.0.0/8 ]             # 내부 대역은 SNAT 제외
  egressGateways:                           # Gateway 여러 개, 엔드포인트마다 1개 고정
  - nodeSelector: { matchLabels: { ydl/egw: gw1 } }
    egressIP: 10.40.0.1
  - nodeSelector: { matchLabels: { ydl/egw: gw2 } }
    egressIP: 10.40.0.2
```

### 5-5. NX-OS leaf (개념 코드)

```
router bgp 4200001001
  bestpath as-path multipath-relax
  address-family l2vpn evpn
    maximum-paths 64
  vrf PRIVATE
    address-family ipv4 unicast
      advertise l2vpn evpn
      maximum-paths 64
    neighbor 10.10.1.0/26 remote-as 65101      ! 랙 서브넷 prefix 피어링
      address-family ipv4 unicast
        prefix-list COM-PRIV-IN in              ! Pod 대역, 노드 루프백 (AIStor 랙은 VIP 풀 추가)
        maximum-prefix 2000
  vrf PUBLIC
    address-family ipv4 unicast
      advertise l2vpn evpn
      maximum-paths 64
    neighbor 10.30.1.0/26 remote-as 65101
      address-family ipv4 unicast
        prefix-list COM-PUB-IN in               ! LB 풀, Egress 풀 /32 만
```

---

## 6. 실무에서 확인

- 기존 Lake 는 Cilium 1.18.4 → Y지역은 1.20.x 로 시작함. 1.19 에서 BGP v1(PeeringPolicy) 이 제거됐으므로 기존 v1 매니페스트를 복사하지 않음
- 1.19 부터 ClusterMesh 정책 기본값이 로컬 클러스터 한정(policy-default-local-cluster) → 기존 CNP 를 옮기면 클러스터 간 트래픽이 조용히 막힐 수 있음
- 현행 Lake 의 minio-global 간헐 끊김이 원인 미확정 상태임. Y지역은 같은 구조라서 원인 확정 전에 경로 A 를 운영 기본값으로 박지 않고, 경로 B(VIP) 로 우회 가능한 상태로 둠
- 기존 Nexus 연동에서 NW팀이 언급한 2-tuple 해시 변경은 VIP 분산에 불리함. Y지역 패브릭은 5-tuple 유지로 사전 합의
- 기존 Lake 처럼 client 가 스토리지와 같은 leaf · 같은 망에 많은 구조면 eTP Local 은 랙 핫스팟이 남. PoC 에서 같은 랙 client 로 warp 를 돌려 노드별 요청 수 편차를 먼저 측정함
- DSR(Geneve) PoC 항목 : Nexus 에서 Geneve(UDP 6081) 통과, MTU, leaf uRPF 모드, 응답이 인입 노드를 안 거치는지 Hubble 로 확인
- 현행 Lake 는 NIC 다운 이슈로 VXLAN 으로 전환한 이력이 있음 → Y지역 native routing 은 NIC 펌웨어 · 드라이버 검증을 PoC 항목에 넣음
- B300 GPU 노드(Lake GPU)는 RoCE 백엔드망이 별도라 이 설계의 PRIVATE VRF 와 섞지 않음. GPU 노드의 S3 접근만 경로 A · B 를 그대로 씀
- Gateway API(Cilium) LB IP 도 PUBLIC LB 풀에서 받음. LB 풀은 용도별(public-svc, egress, clustermesh)로 나눠 IPAM 충돌을 막음
- bpf-lb-map-max 포화 이력이 있음 → 300노드 · 서비스 수 기준으로 LB 맵 크기를 처음부터 키움
- 폐쇄망 반입 : Cilium 1.20 차트 · 이미지(cilium, operator, clustermesh-apiserver, hubble)를 dmz-nexus 프록시로 받음

---

## 7. 용어 정리

- **5단 Clos(5-stage Clos)** : leaf - spine - super spine 3계층 패브릭. Pod 를 늘려 수평 확장함
- **EVPN Type-5** : IP prefix 를 VRF 단위로 패브릭에 뿌리는 경로 유형. VIP /32 가 이 형태로 퍼짐
- **L3VNI** : VRF 하나를 VXLAN 위에서 구분하는 번호. PUBLIC · PRIVATE 가 각각 하나씩 가짐
- **RD(Route Distinguisher)** : 같은 prefix 를 leaf 별로 다른 경로로 구분하는 값. 고유해야 ECMP 유지
- **multipath-relax** : AS-path 내용이 달라도 길이가 같으면 ECMP 로 묶는 BGP 옵션
- **prefix 피어링** : 서브넷 단위로 BGP 이웃을 받는 방식. 노드별 설정 불필요
- **eTP Local(externalTrafficPolicy: Local)** : 로컬 백엔드가 있는 노드만 VIP 를 받는 정책
- **Maglev** : 어느 노드에서 계산해도 같은 백엔드를 고르는 일관 해시
- **DSR(Direct Server Return)** : 백엔드가 인입 노드를 거치지 않고 client 로 바로 응답하는 방식. Geneve 전달은 원래 VIP 정보를 Geneve 헤더에 실어 보냄
- **mixed multipath** : eBGP 경로와 iBGP 경로를 함께 ECMP 로 묶는 NX-OS 옵션
- **Global Service** : ClusterMesh 에서 여러 클러스터 백엔드를 묶는 서비스
- **KVStoreMesh** : 원격 클러스터 상태를 로컬 캐시로 받아 apiserver 부하를 줄이는 ClusterMesh 구성
- **Egress Gateway** : 특정 Pod 의 외부 트래픽을 지정 노드로 보내 고정 IP 로 SNAT 하는 기능
- **graceful restart** : BGP 세션이 잠시 끊겨도 경로를 바로 지우지 않는 기능

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 패브릭 | 5단 Clos, leaf 100G · spine 400G, Pod 3개 (Com 2, Storage 1) |
| 라우팅 | IGP 없이 eBGP underlay · eBGP EVPN overlay |
| 망 분리 | NIC 와 VRF 둘 다 분리, 피어별 광고 분리, 기본 경로 = PUBLIC |
| BGP | 노드 ↔ leaf eBGP, 클러스터별 ASN, prefix 피어링, multipath-relax |
| AIStor 내부 | Global Service 소켓 LB, Pod IP 직결 |
| AIStor 외부 | VIP /32 두 VRF 광고, eTP Cluster 와 Maglev, DSR(Geneve), 5-tuple 해시 유지 |
| 인입 위치 | Super Spine · Spine = ECMP 균등, Leaf · 동일 망 = 로컬 쏠림 → Maglev 로 백엔드 균등화 |
| 검증 | 4개 위치 warp, 노드별 요청 수 편차 ±10%, DSR 우회 · 노드 장애 끊김 비율 확인 |
| Egress | 클러스터별 Gateway 그룹, Egress IP /32 BGP 광고, 장애 동작 PoC 필수 |
| 버전 | Cilium 1.20.x, BGP v2 리소스만 사용 |

**패브릭 ECMP 는 인입 노드까지만 고르게 하고, 백엔드 균등은 Maglev 가 맡아야 client 위치와 무관해진다.**

관련 글 : ClusterMesh minio-global 간헐 끊김, Gateway API 전환 작업 계획, VXLAN 전환 후 Pod 통신 트러블슈팅
