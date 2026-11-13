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

<!-- diagram: ydl-01-overview.html -->

- 동서(Pod 간, AIStor EC 복제) 트래픽 = PRIVATE VRF
- 남북(외부 client, Egress) 트래픽 = PUBLIC VRF, Border Leaf 로만 출입
- AIStor 는 노드마다 Pod 1개(DaemonSet) → 모든 스토리지 노드가 VIP 를 광고하는 구조

**AIStor 분산은 LB 장비가 아니라 BGP ECMP 와 Cilium 소켓 LB 두 갈래로 끝낸다.**

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

> 주의 : Type-5 경로의 RD 는 leaf 별로 고유(rd auto)해야 함. RD 가 같으면 Spine 에서 경로가 하나로 합쳐져 ECMP 가 사라짐

### 2-2. Public · Private 분리

노드 한 대가 NIC 4포트(Storage 는 private 2포트 추가)를 쓰고, 포트마다 leaf 하나에 L3 로 붙음. vPC · LACP 를 쓰지 않음.

<!-- diagram: ydl-02-nw-split.html -->

| 항목 | PRIVATE | PUBLIC |
|---|---|---|
| 용도 | Pod 간, ClusterMesh, AIStor EC 복제, kubelet | 외부 client 의 VIP 접근, Egress SNAT |
| leaf 쪽 | VRF PRIVATE, leaf 별 전용 서브넷 | VRF PUBLIC, leaf 별 전용 서브넷 |
| Cilium 광고 | PodCIDR, 노드 루프백 /32 | LoadBalancer IP /32, Egress IP /32 |
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
- 피어별 수신 필터 : PRIVATE = Pod 대역과 노드 루프백만, PUBLIC = LB 풀 · Egress 풀 /32 만. maximum-prefix 로 상한을 둠
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
| B. VIP ECMP | 외부 서버, 다른 DC, 사용자망 | 패브릭 ECMP 가 VIP /32 광고 노드 중 하나를 고름 | 연결 (5-tuple 해시) |

### 3-1. 경로 A - Global Service

- AIStor 쪽 Service 에 `service.cilium.io/global: "true"`, Com 쪽에 같은 이름 · 네임스페이스의 빈 Service 를 둠
- Com 클러스터에는 AIStor Pod 가 없어서 affinity 는 의미 없음. 기본값(none) 그대로
- VIP · NAT 없이 Pod IP 로 바로 감 → 홉 1개, client IP 그대로 보임

### 3-2. 경로 B - VIP /32 와 externalTrafficPolicy Local

| 방식 | 장점 | 단점 |
|---|---|---|
| eTP Local (기본안) | 로컬 Pod 로만 전달, client IP 보존, 노드 간 2차 홉 없음 | ECMP 재해시 때 기존 연결이 다른 노드로 가면 끊김 |
| eTP Cluster + Maglev | 어느 노드로 가도 같은 백엔드를 고름 → 재해시에 강함 | 2차 홉, SNAT 로 client IP 사라짐 (DSR 은 패브릭 검증 필요) |

- eTP Local 이면 로컬 백엔드가 없는 노드는 VIP 광고를 멈춤 → 장애 노드는 자동으로 빠짐
- 점검 순서 : 노드 cordon → AIStor Pod 제거로 광고 철회 → 작업. 갑작스러운 재해시를 피함
- S3 SDK 재시도가 기본으로 있어 연결 끊김은 재시도로 흡수됨. 단, 대용량 멀티파트 업로드는 part 단위 재시도 설정 확인

> 주의 : ECMP 해시는 5-tuple(L4 포트 포함)을 유지해야 함. 2-tuple(IP 만)로 바꾸면 SNAT 된 client(Egress GW, NAT 뒤 서버)의 연결이 전부 노드 하나로 몰림

### 3-3. 보조 수단

- Sidekick : client 옆 사이드카 LB, least-connection 과 헬스체크. 대형 Spark 잡처럼 연결 수가 적고 큰 경우 쏠림 보완용
- 1.20 의 EndpointSlice 가중치(`service.cilium.io/weight`, 0 = 드레인) : eTP Cluster 서비스에서 노드 단계적 제외용

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
loadBalancer:
  algorithm: maglev
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
      matchLabels: { advertise: private }   # PodCIDR, 루프백만
---
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: public-vip
  labels: { advertise: public }
spec:
  advertisements:
  - advertisementType: Service
    service:
      addresses: [ LoadBalancerIP ]
    selector:
      matchLabels: { ydl/expose: public }   # 외부 노출 서비스만
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
    ydl/expose: public                      # 경로 B : VIP 광고 대상
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local
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
        prefix-list COM-PRIV-IN in              ! Pod 대역, 노드 루프백만
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
| AIStor 외부 | VIP /32 eTP Local, 2단 ECMP, 5-tuple 해시 유지 |
| Egress | 클러스터별 Gateway 그룹, Egress IP /32 BGP 광고, 장애 동작 PoC 필수 |
| 버전 | Cilium 1.20.x, BGP v2 리소스만 사용 |

**ECMP 가 끝까지 살아 있으려면 모든 계층의 maximum-paths, 고유 RD, 5-tuple 해시가 같이 맞아야 한다.**

관련 글 : ClusterMesh minio-global 간헐 끊김, Gateway API 전환 작업 계획, VXLAN 전환 후 Pod 통신 트러블슈팅
