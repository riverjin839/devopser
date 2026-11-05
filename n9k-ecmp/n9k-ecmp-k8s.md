## Cisco N9K 사용법과 ECMP - K8s(Cilium BGP) 기준

> **목표** : N9K 기본 운용 명령과 ECMP 동작을 K8s Service VIP 분산 관점으로 정리함

- 출처 : Cisco NX-API/NX-OS 문서, Cisco 커뮤니티, Cilium 공식 문서, Isovalent 블로그
- 기준 버전 : Cilium v1.20.4 (2026-11 기준, git tag 확인) / NX-OS 는 릴리즈별 차이가 있어 장비에서 직접 확인 필요
- 표기 : `개념 코드` 는 문서 문법을 바탕으로 쓴 예시임, 적용 전 장비·버전에서 검증할 것

---

## 1. 개요

N9K = NX-OS 기반 데이터센터 스위치. L3 포워딩은 전부 하드웨어에서 처리함

ECMP(Equal-Cost Multi-Path) = 같은 목적지로 가는 같은 비용 경로가 여러 개일 때 흐름(flow) 단위로 나눠 보내는 기능

K8s 에서의 의미
- 여러 노드가 같은 Service VIP /32 를 BGP 로 광고함
- Leaf(N9K) 는 VIP 하나에 next-hop 이 노드 수만큼 생김
- Leaf 가 해시로 노드를 골라 보냄 → 사실상 L3/L4 로드밸런서 역할

<!-- diagram: n9k-ecmp-overview.html -->

**Cilium 은 경로만 광고하고, 실제 포워딩은 eBPF 가 하며, 노드를 고르는 건 Leaf 의 ECMP 해시임**

> 주의 : Cilium BGP Control Plane 은 데이터패스를 프로그래밍하지 않음. 클러스터 내부 도달성 확보용이 아니라 외부 라우터에 경로를 알리는 용도임

---

## 2. 개념 정리

### 2-1. N9K 기본 사용법 (NX-OS CLI)

| 목적 | 명령 |
|---|---|
| 설정 모드 진입 | `configure terminal` |
| 설정 저장 | `copy running-config startup-config` |
| 기능 켜기 | `feature bgp` , `feature bfd` |
| 변경 전 복구 지점 | `checkpoint 이름` → `rollback running-config checkpoint 이름` |
| 경로 확인 | `show ip route 192.0.2.10/32` |
| BGP 이웃 요약 | `show bgp ipv4 unicast summary` |
| 특정 prefix 경로 목록 | `show bgp ipv4 unicast 192.0.2.10/32` |
| ECMP 해시 설정 확인 | `show ip load-sharing` |
| 특정 흐름이 타는 경로 | `show routing hash 출발IP 목적IP` |
| 포트채널 해시 확인 | `show port-channel load-balance` |

- `show ip load-sharing` , `show routing hash` 는 Cisco 커뮤니티 답변에서 확인한 명령임
- 나머지는 일반 NX-OS 문법. 릴리즈에 따라 출력 형식이 다름

### 2-2. ECMP 는 두 층으로 나뉨

| 층 | 대상 | 해시 설정 |
|---|---|---|
| L3 ECMP | 라우팅 경로 (Spine-Leaf, Leaf-노드) | `ip load-sharing ...` |
| 포트채널 | 링크 묶음 안의 멤버 | `port-channel load-balance ...` |

- 둘은 별개 설정임. 노드가 Leaf 에 포트채널로 붙어 있으면 두 층이 겹침
- 같은 흐름은 항상 같은 경로를 탐. 흐름의 정의는 설정한 해시 방식이 정함

### 2-3. L3 ECMP 해시 옵션

설정 형식 : `ip load-sharing address { destination port destination | source-destination [ port source-destination ] }`

| 옵션 | 의미 | 값 / 추가 버전 |
|---|---|---|
| source-destination | 출발·목적 IP 기준 해시 | 기본값은 장비에서 `show ip load-sharing` 으로 확인 |
| port source-destination | L4 포트까지 해시에 포함 | - |
| rotate | 해시 회전 값 | 1~63, 기본 32 |
| universal-id | 랜덤 시드 | 0~4294967295 |
| concatenation | 연결 옵션 | 기본 disabled |
| gre-outer | GRE 바깥 헤더 기준 해시 | 기본 disabled |
| ttl | TTL 을 해시에 포함 | 9.3(3) 에서 추가 |
| udf | 사용자 지정 오프셋·길이로 해시 | 9.3(3) 에서 추가 |
| exclude-l3-proto | L3 프로토콜 필드 제외 | 10.5(1) 에서 추가 |

- `no ip load-sharing ...` 로 지우면 GRE 트래픽의 내부 헤더 해싱이 꺼질 수 있음. 문서 경고임
- 시드(universal-id)는 장비마다 다르게 주는 식으로 쓰는 값임. 계층 구조에서 해시 쏠림을 줄이는 용도로 이해하면 됨

<!-- diagram: n9k-ecmp-hash-flow.html -->

### 2-4. BGP 에서 ECMP 가 켜지는 조건

- 기본은 BGP 가 best path 하나만 설치함. `maximum-paths` 로 늘려야 함
- eBGP 경로 = `maximum-paths N` , iBGP 경로 = `maximum-paths ibgp N` , 둘 섞기 = `maximum-paths mixed N` (address-family 안에서 설정)
- 경로가 ECMP 후보가 되려면 local-pref, AS path, origin, MED 같은 속성이 같아야 하는 게 BGP 일반 규칙임
- 서로 다른 AS 에서 온 경로를 같이 쓰려면 `bestpath as-path multipath-relax` 가 필요함. Spine 이 AS 가 다른 Leaf 들에게 같은 prefix 를 받는 구조에서 걸림
- ECMP 로 여러 경로를 써도 이웃에게 광고하는 건 best path 하나뿐임

### 2-5. Cilium BGP Control Plane v2 리소스

| 리소스 | 역할 |
|---|---|
| CiliumBGPClusterConfig | nodeSelector 로 고른 노드에 BGP 인스턴스와 피어 정의 |
| CiliumBGPPeerConfig | 피어들이 공유하는 세션 설정 (timers, families, ebgpMultihop 등) |
| CiliumBGPAdvertisement | 광고할 prefix 종류와 BGP 속성 |
| CiliumBGPNodeConfigOverride | 노드 단위로 routerID·localASN 등을 덮어씀 |

- PeerConfig 의 families 에 있는 advertisements 라벨 셀렉터가 Advertisement 와 연결됨. 매칭이 없으면 아무것도 광고 안 됨
- advertisementType = PodCIDR , CiliumPodIPPool , Service , Interface
- Service 는 `/32` (IPv6 는 `/128`) 로 광고됨

Service 광고 대상과 트래픽 정책

| addresses | 대상 | 참조 정책 |
|---|---|---|
| ClusterIP | spec.clusterIP | internalTrafficPolicy |
| ExternalIP | spec.externalIPs | externalTrafficPolicy |
| LoadBalancerIP | status.loadBalancer.ingress | externalTrafficPolicy |

- externalTrafficPolicy Cluster = 선택된 Service IP 를 조건 없이 광고
- externalTrafficPolicy Local = 로컬 노드에 엔드포인트가 있을 때만 광고, 없으면 광고 중단
- Cilium 문서 경고 : 같은 VIP 를 많은 노드가 광고하면 ECMP 경로 수가 늘어나는데, 라우터마다 상한이 있으니 먼저 네트워크 담당자와 한도를 확인할 것

<!-- diagram: n9k-ecmp-cilium-config.html -->

---

## 3. 구조 비교 - VIP 를 누가 광고할 것인가

| 방식 | 장점 | 단점 | 언제 쓰나 |
|---|---|---|---|
| 모든 노드가 광고 (Cluster) | 설정 단순, 경로 수 최대 | ECMP 폭이 노드 수만큼 커짐, 한도 초과 위험 | 소규모 클러스터 |
| 일부 노드만 광고 (nodeSelector) | ECMP 폭을 직접 통제 | 전용 노드군 라벨 관리 필요 | 노드가 많은 클러스터 |
| Local 정책 | 엔드포인트 있는 노드만 광고, 불필요한 노드 경유 감소 | 파드 이동 때마다 경로 변동, 경로 수 불균형 | 클라이언트 IP 보존이 중요할 때 |

---

## 4. 노드 장애 때 ECMP 는 어떻게 움직이나

1. 노드 장애 → BGP keepalive 끊김
2. hold time 만료 → 세션 단절
3. Leaf 가 해당 next-hop 제거 → 경로 수 감소
4. 해시 결과가 바뀌며 일부 흐름이 다른 노드로 이동함
5. 다른 노드에 도착한 기존 연결 패킷은 해당 노드의 eBPF 가 백엔드를 다시 고름

<!-- diagram: n9k-ecmp-node-failure.html -->

- 이동한 흐름이 원래 백엔드로 돌아가려면 노드끼리 백엔드 선택이 일관돼야 함 → Cilium 의 Maglev 방식이 이 용도의 개념임. 사용 가능 여부와 설정은 버전별 문서에서 확인 필요
- 해시 재분배 범위(일부만 이동하는지 전체가 섞이는지)는 N9K 플랫폼·릴리즈에 따라 다름. resilient hashing 지원 여부는 확인 못 함 → 장비에서 확인 필요

> 주의 : 세션 타이머가 짧을수록 장애 감지가 빠르지만, 노드 부하로 keepalive 가 늦으면 세션이 불필요하게 끊김

---

## 5. 사용법 예시

### 5-1. N9K 쪽 (개념 코드)

```text
feature bgp

ip prefix-list K8S-VIP seq 10 permit 192.0.2.0/24 le 32
route-map FROM-K8S permit 10
  match ip address prefix-list K8S-VIP

router bgp 65000
  router-id 10.0.1.1
  address-family ipv4 unicast
    maximum-paths 8          ! 예시값, 장비 상한과 노드 수 확인
  template peer K8S-NODE
    remote-as 65001
    timers 3 9               ! keepalive 3 / hold 9
    address-family ipv4 unicast
      route-map FROM-K8S in
  neighbor 10.0.1.11
    inherit peer K8S-NODE
  neighbor 10.0.1.12
    inherit peer K8S-NODE
```

- route-map 으로 VIP 대역만 받게 막아 두는 걸 권장함. 노드 설정 실수로 엉뚱한 prefix 가 들어오는 걸 방지
- 노드 수가 많으면 neighbor 를 일일이 쓰는 대신 동적 이웃 기능을 쓰는 방법이 있으나 문법은 버전 확인 필요

### 5-2. Cilium 쪽 (개념 코드)

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPClusterConfig
metadata:
  name: cilium-bgp
spec:
  nodeSelector:
    matchLabels:
      bgp-vip: "true"          # VIP 를 광고할 노드군만 선택
  bgpInstances:
    - name: "instance-65001"
      localASN: 65001
      peers:
        - name: "leaf-a"
          peerASN: 65000
          peerAddress: 10.0.1.1
          peerConfigRef:
            name: cilium-peer
---
apiVersion: cilium.io/v2
kind: CiliumBGPPeerConfig
metadata:
  name: cilium-peer
spec:
  timers:
    holdTimeSeconds: 9
    keepAliveTimeSeconds: 3
  families:
    - afi: ipv4
      safi: unicast
      advertisements:
        matchLabels:
          advertise: bgp
---
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: lb-vip
  labels:
    advertise: bgp
spec:
  advertisements:
    - advertisementType: "Service"
      service:
        addresses:
          - LoadBalancerIP
      selector:
        matchExpressions:
          - { key: never-used-value, operator: NotIn, values: ["x"] }   # 모든 Service 선택용 관용 표현
```

- LoadBalancerIP 는 IP 가 먼저 할당돼 있어야 광고됨 (LB IPAM 등)
- LB IP 풀 리소스(CiliumLoadBalancerIPPool)의 필드명은 버전마다 달라 여기서는 생략함 → 사용 버전 문서 확인

### 5-3. 확인 순서

```bash
# Cilium 쪽
cilium bgp peers                                  # 세션 established, 광고 경로 수
cilium bgp routes available ipv4 unicast          # 로컬 BGP 테이블
cilium bgp routes advertised ipv4 unicast         # 피어에게 실제 광고된 경로

# N9K 쪽
show bgp ipv4 unicast summary
show bgp ipv4 unicast 192.0.2.10/32               # 경로 여러 개 + multipath 표시
show ip route 192.0.2.10/32                       # next-hop 여러 줄이면 ECMP 설치됨
show routing hash 10.9.9.9 192.0.2.10             # 이 흐름이 어느 노드로 가는지
```

- 확인 흐름 = Cilium 세션 → Cilium 광고 → N9K 수신 → N9K 라우팅 테이블 → 해시 결과
- Cilium 상태 이상은 `kubectl describe ciliumbgpnodeconfigs 노드명` 과 ClusterConfig 의 status conditions 에서도 볼 수 있음

---

## 6. 실무에서 확인

- **노드 300대 전부가 VIP 를 광고하면 ECMP 폭 한도에 걸릴 수 있음** → LB 전용 노드군에 라벨을 달고 nodeSelector 로 광고 노드를 제한하는 구성이 안전함
- N9K 의 ECMP 최대 경로 수, 해시 기본 모드, resilient hashing 지원은 장비 모델·NX-OS 버전별로 다름 → 네트워크팀과 `show` 결과로 확인
- Local vs Cluster 정책 : Local 은 엔드포인트가 이동할 때 광고 노드가 바뀌어 경로 변동이 잦음. 롤링 업데이트가 잦은 서비스는 영향 확인 필요
- 장애 감지 시간 = hold time 이 상한임 (예시 9초). 더 빠르게 하려면 BFD 가 후보인데, N9K 는 `feature bfd` 가 있으나 Cilium OSS 쪽 BFD 지원은 확인 못 함
- 폐쇄망이라 N9K 설정 변경은 네트워크팀 작업이 필요함. 변경 전 checkpoint 를 남기고 route-map 으로 수락 prefix 를 제한해 둘 것
- Gateway API 로 만든 LB VIP 도 같은 LoadBalancerIP 광고 경로를 탐 → 이 문서의 ECMP 동작이 그대로 적용됨
- 버전 : v1 CiliumBGPPeeringPolicy 는 1.18 에서 deprecated, 1.19 에서 제거됐다는 서드파티 글이 있음. 공식 릴리즈 노트로 확인 후 v2 로 통일할 것

---

## 7. 용어 정리

- **ECMP(Equal-Cost Multi-Path)** : 같은 비용 경로 여러 개에 흐름을 나눠 보내는 기능
- **flow** : 해시 방식이 정한 기준(IP, 포트 등)으로 묶인 패킷 묶음. 같은 flow 는 같은 경로를 탐
- **next-hop** : 목적지로 가기 위한 다음 장비 주소. ECMP 면 한 prefix 에 여러 개
- **FIB(Forwarding Information Base)** : 하드웨어가 실제 포워딩에 쓰는 경로 테이블
- **maximum-paths** : BGP 가 라우팅 테이블에 설치할 동시 경로 수 상한
- **multipath-relax** : AS path 내용이 달라도 길이가 같으면 ECMP 후보로 인정하는 옵션
- **universal-id** : 해시에 섞는 랜덤 시드 값
- **VIP(/32 광고)** : Service 의 IP 를 호스트 경로로 BGP 에 올린 것
- **externalTrafficPolicy** : 외부 트래픽을 어느 노드의 엔드포인트로 보낼지 정하는 Service 설정
- **hold time** : keepalive 가 이 시간 안에 안 오면 BGP 세션을 끊는 타이머
- **BFD** : BGP 보다 빠르게 링크 장애를 감지하는 별도 프로토콜
- **Maglev** : 노드가 달라도 같은 흐름에 같은 백엔드를 고르게 하는 일관 해시 방식

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| ECMP 의 역할 | Leaf 가 VIP 의 next-hop 여러 개 중 해시로 노드를 고름 |
| 설정 위치 | N9K = maximum-paths 와 ip load-sharing, Cilium = Advertisement 로 VIP 광고 |
| 해시 확인 | show ip load-sharing 과 show routing hash |
| 경로 수 | 광고 노드 수 = ECMP 폭, 장비 상한 확인 필수 |
| 정책 | Cluster 는 전체 광고, Local 은 엔드포인트 노드만 광고 |
| 장애 | hold time 만료 후 경로 철회, 일부 흐름이 다른 노드로 이동 |
| 한계 | resilient hashing·최대 경로 수·BFD 는 장비와 버전에서 확인 필요 |

**VIP 를 광고하는 노드 수가 곧 ECMP 폭이므로, 노드 전체가 아니라 LB 전용 노드군만 광고하게 제한하는 게 핵심이다**

관련 글 : Cilium Gateway API LB VIP 헤어핀 - nginx 2대로 재현하고 구간별로 원인 좁히기

---

## Sources

- [Configuring ECMP Load Balancing - Cisco NX-API REST](https://developer.cisco.com/docs/cisco-nexus-3000-and-9000-series-nx-api-rest-sdk-user-guide-and-api-reference/latest/configuring-ecmp-load-balancing)
- [Configuring Load Sharing in the Unicast FIB - Cisco NX-API REST](https://developer.cisco.com/docs/cisco-nexus-3000-and-9000-series-nx-api-rest-sdk-user-guide-and-api-reference/latest/configuring-load-sharing-in-the-unicast-fib)
- [Configuring an IPv4 Unicast Address Family - Cisco NX-OS API](https://developer.cisco.com/docs/nx-os-n3k-n9k-api-ref-7-x/configuring-an-ipv4-unicast-address-family)
- [Configuring Mixed ECMP - Cisco NX-API REST](https://developer.cisco.com/docs/cisco-nexus-3000-and-9000-series-nx-api-rest-sdk-user-guide-and-api-reference/latest/configuring-mixed-ecmp)
- [Nexus 9000 ECMP load balancing - Cisco Community](https://community.cisco.com/t5/data-center-switches/nexus-9000-ecmp-load-balancing/m-p/4819236)
- [Cilium BGP Control Plane - Configuration](https://docs.cilium.io/en/stable/network/bgp-control-plane/bgp-control-plane-configuration/)
- [Cilium BGP Control Plane - Operation](https://docs.cilium.io/en/stable/network/bgp-control-plane/bgp-control-plane-operation/)
- [Connecting your Kubernetes island to your network with Cilium BGP - Isovalent](https://isovalent.com/blog/post/connecting-your-kubernetes-island-to-your-network-with-cilium-bgp/)
- [How to Configure BGP with Cilium on Talos Linux - OneUptime (서드파티, 버전 이력 참고용)](https://oneuptime.com/blog/post/2026-03-03-configure-bgp-with-cilium-on-talos-linux/markdown)
