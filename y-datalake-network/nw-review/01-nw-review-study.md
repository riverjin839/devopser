## Y지역 NW 검토 결과 이해하기 - iBGP EVPN 패브릭과 ECMP · 장애 감지 옵션

> **목표** : NW 담당자 검토 결과 항목이 각각 무엇이고, 왜 그렇게 정했는지, 우리 Cilium 설계와 어디서 맞물리는지 이해함

- 출처 : Y지역 NW 담당자 검토 결과 (2026-11), Cisco NX-OS VXLAN BGP EVPN 설정 가이드, RFC 7938, Cilium BGP Control Plane 문서
- 기준 버전 : Cilium 1.20.x, Kubernetes 1.37, Cisco Nexus 9000 (NX-OS 10.x), Intel E810 (2026-11 기준)

---

## 1. 개요

NW 검토 결과는 한 문장으로 "패브릭은 iBGP EVPN 으로 단순하게, ECMP 는 넓게, 장애 감지는 BFD 대신 다른 수단으로" 임.

<!-- diagram: nwr-01-ibgp-fabric.html -->

| 구분 | 항목 | NW 결정 |
|---|---|---|
| 구조 | 랙 분리 | 물리 서버 랙 / 스토리지 랙 분리 |
| 구조 | 패브릭 BGP | eBGP only 대신 iBGP 패브릭 유지 |
| 구조 | RD / RT | 자동 할당 |
| ECMP | maximum-paths | 64 |
| ECMP | multipath-relax · RT · spine EVPN 중계 | eBGP 를 안 쓰므로 불필요 |
| ECMP | resilient hashing | 적용 (용인 신규 OS 지원, 이천 현행 OS 미지원) |
| ECMP | 계층별 해시 seed | 미적용 |
| ECMP | export-gateway-ip | 적용 |
| 장애 | BFD | 미사용 (오탐으로 장애가 더 많았음) |
| 장애 | Port-Channel LACP | fast |
| 장애 | GR | GR 적용, helper 미적용 |
| 기타 | MTU | 9217 전 구간 |
| 기타 | VRF 수신 필터 | 미적용 (Super Spine 에 supernet null0) |
| 기타 | uRPF | 미적용 |
| 기타 | RTT | 구축 후 측정 |

**핵심은 "스위치 사이는 iBGP, 노드와 leaf 사이는 그대로 eBGP" 라는 점이다.** 이 구분을 잡으면 나머지 항목이 대부분 따라 정리됨.

---

## 2. 개념 정리

### 2-1. iBGP 패브릭 vs eBGP only 패브릭

| 항목 | iBGP 패브릭 (NW 선택) | eBGP only (RFC 7938) |
|---|---|---|
| 언더레이 | IGP(OSPF · IS-IS)로 루프백 · VTEP 도달 | eBGP 로 루프백 광고, IGP 없음 |
| 오버레이 EVPN | iBGP, spine 이 RR(route reflector) | eBGP, spine 이 경로 중계 |
| ASN | 패브릭 전체 AS 1개 | 계층 · 랙마다 ASN 계획 필요 |
| RD / RT | 자동 그대로 동작 (RT = ASN:VNI 가 모든 leaf 에서 같음) | leaf 마다 ASN 이 달라 자동 RT 가 안 맞음 → RT 재작성 · 수동 RT |
| 루프 방지 | iBGP split horizon + RR cluster-id | AS_PATH |
| ECMP 옵션 | `maximum-paths ibgp` | `maximum-paths` + `multipath-relax` |
| spine 설정 | RR 클라이언트 지정 | `retain route-target all`, next-hop 유지 |
| 장애 범위 | IGP 도메인 하나 | BGP 세션 단위로 작음 |
| 언제 쓰나 | 수백 노드급, 운영 인력이 iBGP EVPN 에 익숙할 때 | 수천 랙급 하이퍼스케일, 자동화된 ASN 관리 |

- NW 가 말한 "IP · 설정이 쉽다" = ASN 하나, RD/RT 자동, IGP 는 루프백만 → 설정 템플릿이 단순함
- "eBGP 는 영역별 ASN 할당 필요" = 맞음. Super Spine · Spine · Leaf 마다 ASN 계획 + `allowas-in` 또는 AS 재작성 고민이 생김
- "라우팅 루프는 이미 처리" = iBGP 는 RR 의 originator-id · cluster-list 로 루프를 막음
- 300 노드 · leaf 30여 대 규모에서는 iBGP 패브릭이 표준 구성임. eBGP only 의 장점(장애 범위 축소)은 이 규모에서 크지 않음

> 주의 : iBGP 패브릭이어도 Cilium 노드는 leaf 와 eBGP 로 붙는 것이 일반적임 (노드 AS 65101 · 65102 ≠ 패브릭 AS). 노드까지 iBGP 로 넣으면 leaf 가 노드 경로를 다시 반사해야 하고 next-hop 처리가 꼬임

### 2-2. RD · RT 자동 할당

- **RD(route distinguisher)** : 같은 prefix 를 VRF · 장비별로 구분하는 이름표. 자동 = `라우터ID:VRF번호` → leaf 마다 다름
- **RT(route target)** : 어느 VRF 로 가져갈지 정하는 표식. 자동 = `ASN:VNI` → AS 가 하나면 모든 leaf 에서 같음

<!-- diagram: nwr-02-type5-ecmp.html -->

- RD 가 leaf 마다 다르다 = 같은 VIP 라도 RR 이 "서로 다른 경로" 로 보고 전부 반사함 → 원격 leaf 에 경로가 여러 개 도착 → ECMP 가능
- RD 가 같으면 RR 이 경로 하나만 골라 반사함 → ECMP 가 1개로 줄어듦
- 그래서 "자동이니 검토 불필요" 는 iBGP 단일 AS 에서는 맞는 말임

### 2-3. maximum-paths 와 multipath-relax

| 설정 | 뜻 | 우리 환경에서 필요한 곳 |
|---|---|---|
| `maximum-paths 64` | eBGP 경로 ECMP 개수 | leaf VRF : 로컬 노드들에서 받은 VIP |
| `maximum-paths ibgp 64` | iBGP 경로 ECMP 개수 | leaf VRF : 원격 leaf 가 보낸 Type-5 |
| `maximum-paths mixed 64` | eBGP 와 iBGP 경로를 섞어서 ECMP | 로컬 노드와 원격 leaf 가 같은 VIP 를 광고할 때 |
| `bestpath as-path multipath-relax` | AS_PATH 내용이 달라도 길이만 같으면 ECMP | 이웃 AS 가 서로 다른 경로를 묶을 때 |

- 노드 AS 가 클러스터마다 하나(65101 · 65102)이고, 패브릭이 iBGP 면 같은 VIP 의 AS_PATH 는 모두 `65102` 로 같음 → multipath-relax 불필요가 맞음
- 단, BGP 최적 경로 선택에서 eBGP 가 iBGP 보다 우선임 → 노드가 붙은 leaf 는 자기 노드 경로만 씀. 이것이 "같은 leaf client 는 그 랙 노드로만 인입" 문제의 원인임
- `maximum-paths mixed` 를 쓰면 로컬 노드와 원격 VTEP 을 함께 ECMP 에 넣을 수 있음 (NX-OS 버전 · 라인카드 지원 확인)

> 주의 : ECMP 폭은 설정값과 하드웨어 한도 중 작은 값임. VIP 를 광고하는 노드가 64개를 넘으면 (예 : Com 252노드 전체가 광고) 일부 경로는 버려짐 → 광고 노드를 노드 그룹으로 제한

### 2-4. spine EVPN 중계

- eBGP 패브릭에서 spine 은 VNI 를 갖지 않으므로 `retain route-target all` 과 next-hop 유지 설정이 있어야 EVPN 경로를 넘겨줌
- iBGP 패브릭에서는 이 설정 대신 spine 이 RR 로 동작해야 함 (`route-reflector-client`)
- NW 의 "eBGP 아니면 필요 없음" = eBGP 용 중계 설정은 필요 없음. RR 설정은 필요함

### 2-5. export-gateway-ip 와 resilient hashing

<!-- diagram: nwr-03-gwip-resilient.html -->

| 항목 | export-gateway-ip | resilient hashing |
|---|---|---|
| 하는 일 | Type-5 경로에 원래 next-hop(노드 IP)을 gateway IP 로 실어 보냄 | ECMP 멤버가 빠질 때 남은 멤버의 흐름 배정을 유지 |
| 해결하는 문제 | VTEP 단위 분배 쏠림 (노드 3대 leaf 와 1대 leaf 가 50 : 50) | 멤버 변경 시 전체 흐름 재해시로 연결 끊김 |
| 결과 | 원격 leaf 가 노드 단위로 ECMP (1 : 1 : 1 : 1) | 빠진 멤버 흐름만 이동 |
| 동작 시점 | 경로 광고 · 설치 | 데이터 평면 해시 |
| 관계 | 분배를 고르게 | 변경을 부드럽게 → 서로 보완 |

- NW 의 "resilient 옵션과 같다" 는 정확하지 않음. 둘 다 적용하는 것이 맞음
- gateway IP 는 원격 leaf 에서 다시 해석(재귀 조회)할 수 있어야 함 → 노드 IP 가 Type-2 또는 /32 Type-5 로 패브릭에 있어야 함
- 이천 현행 OS 가 resilient 를 지원 안 함 = 이천 쪽 ECMP 는 멤버 변경 시 재해시 발생. 이때 Maglev + DSR 이 같은 백엔드를 다시 골라 연결을 살림

### 2-6. 해시 seed

- 다단 ECMP 에서 모든 계층이 같은 해시를 쓰면 위 계층에서 갈린 흐름이 아래 계층에서 한쪽으로 몰림 (polarization)
- NX-OS 는 장비마다 다른 값(universal-id)을 섞어 해시하는 것이 기본 → 따로 안 잡아도 대부분 문제없음
- 미적용 동의. 구축 후 spine 업링크 사용률이 한쪽으로 쏠리면 그때 설정

### 2-7. BFD 없이 장애 감지

<!-- diagram: nwr-04-fail-detect.html -->

| 장애 유형 | BFD 있음 | BFD 없음 (NW 결정) |
|---|---|---|
| 링크 · 광모듈 끊김 | 즉시 | 즉시 (포트 다운 → 세션 다운) |
| 노드 커널 hang · NIC 펌웨어 멈춤 | 수백 ms | BGP hold time |
| cilium-agent 재시작 | BFD 와 무관 | BFD 와 무관. 세션이 끊기므로 GR 이 없으면 경로 철회 → 재수립 후 복귀 |

- 직결 링크는 포트가 내려가면 BGP 가 바로 끊김 → BFD 의 이득은 "링크는 살아 있는데 노드가 멈춘 경우" 에 한정됨
- BFD 를 안 쓰면 BGP 타이머가 감지 시간을 결정함. NX-OS 기본 hold 180초, Cilium 기본 hold 90초 → 그대로 두면 노드 hang 시 수십 초 ~ 3분 블랙홀
- 그래서 노드 ↔ leaf 세션은 keepalive 3초 · hold 9초로 명시해야 함

### 2-8. GR 과 GR helper

| 역할 | 뜻 | 누가 |
|---|---|---|
| GR restarting speaker | 내가 재시작할 때 상대에게 "경로 잠깐 유지해줘" 를 요청 | 재시작하는 쪽 |
| GR helper | 상대가 재시작할 때 그 경로를 restart-time 동안 유지 | 기다려주는 쪽 |

- leaf 가 GR 적용 · helper 미적용 = leaf 자신의 재시작은 보호, 노드(Cilium) 재시작은 보호 안 함
- 결과 : cilium-agent 재시작 · 노드 장애 모두 경로가 즉시 철회됨 → ECMP 에서 빠지고 다른 노드가 받음
- 장점 : 노드가 진짜 죽었을 때 restart-time 동안 생기는 블랙홀이 없음
- 단점 : agent 재시작(업그레이드)마다 ECMP 멤버 변경 발생 → resilient hashing + Maglev 로 흡수

> 주의 : NX-OS 는 helper 가 기본 켜짐임. "미적용" 은 명시적으로 꺼야 함. Cilium 쪽 `gracefulRestart.enabled` 도 끄는 것으로 맞춤

### 2-9. LACP fast, MTU, uRPF

- **LACP fast** : LACPDU 1초 주기, 3초 안에 멤버 장애 감지 (slow = 30초 주기, 90초). 스위치 간 Port-Channel 이면 무조건 fast 가 맞음
- 서버 쪽 bond(vPC)까지 뜻한다면 기존 설계(포트별 L3 + BGP 2세션)와 다름 → 확인 필요
- **MTU** : Nexus 인터페이스 최대값은 9216. 9217 은 오기일 가능성 높음. 노드 9000, 패브릭 9216 이면 VXLAN 50바이트 여유 충분
- **uRPF** : 들어온 포트로 응답 경로가 있는지 검사. ECMP · DSR 처럼 비대칭 경로가 정상인 구조에서는 strict 모드가 정상 트래픽을 버림 → 미적용 동의

### 2-10. VRF 수신 필터와 null0

<!-- diagram: nwr-05-prefix-guard.html -->

- Super Spine null0 supernet = 패브릭 안에 없는 하위 대역으로 가는 트래픽을 위로 흘려보내지 않고 버림. 루프 · 외부 유출 방지용
- 이것은 "노드가 잘못 광고한 경로" 를 막지 못함. 라우팅은 최장 일치라서 노드가 광고한 /32 · /24 가 null0 supernet 을 이김
- 실수 예 : CiliumBGPAdvertisement 셀렉터 오류로 다른 팀 대역 · 0.0.0.0/0 · 서비스 CIDR 전체를 광고 → 패브릭 전체로 퍼짐
- 대책 : leaf 의 노드 피어 템플릿에 수신 prefix-list(VIP · PodCIDR · 노드 루프백 범위만, le 32) + `maximum-prefix`

---

## 3. NW 결정과 Cilium 설정 연결

| NW 결정 | Cilium 쪽 맞출 것 |
|---|---|
| iBGP 패브릭, 노드는 eBGP | `CiliumBGPClusterConfig` localASN 65101 · 65102, peerASN = 패브릭 AS |
| BFD 미사용 | `CiliumBGPPeerConfig` timers : keepAliveTimeSeconds 3, holdTimeSeconds 9 |
| GR helper 미적용 | `gracefulRestart.enabled: false` |
| resilient hashing | Maglev 유지 (이천처럼 미지원 구간 대비) |
| export-gateway-ip | 노드 IP(루프백 /32) 광고 유지 → gateway IP 해석 가능 |
| maximum-paths 64 | VIP 광고 노드를 노드 그룹으로 제한 (64 이하) |
| VRF 필터 미적용 | 광고 셀렉터를 CRD 리뷰 대상으로 고정, ArgoCD 로만 변경 |
| MTU 9216 | 노드 9000, Cilium MTU 자동 (DSR Geneve 오버헤드 반영) |

---

## 4. 사용법 예시

### 4-1. Cilium BGP 피어 설정 (BFD 없음 · GR 끔)

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPPeerConfig
metadata:
  name: leaf-peer
spec:
  timers:
    keepAliveTimeSeconds: 3     # BFD 대신 hold 9초로 감지
    holdTimeSeconds: 9
    connectRetryTimeSeconds: 5
  gracefulRestart:
    enabled: false              # leaf helper 미적용과 맞춤
  families:
    - afi: ipv4
      safi: unicast
      advertisements:
        matchLabels:
          advertise: ydl-vip
```

### 4-2. NX-OS 쪽 (개념 코드, 버전별 문법 확인)

```text
router bgp 65000
  vrf PUBLIC
    address-family ipv4 unicast
      maximum-paths 64
      maximum-paths ibgp 64
      export-gateway-ip              ! Type-5 에 노드 IP 를 gateway IP 로
  template peer CILIUM-NODE
    remote-as 65102
    timers 3 9
    address-family ipv4 unicast
      prefix-list PL-YDL-NODE in     ! VIP · PodCIDR · 루프백만 수신
      maximum-prefix 200 warning-only
```

### 4-3. 확인 명령

```bash
# leaf : VIP 하나의 ECMP 경로 수
show ip route 10.200.0.10/32 vrf PUBLIC
show bgp l2vpn evpn 10.200.0.10 | i "Gateway IP|Path"
# 노드 : 세션 타이머 · GR
cilium bgp peers
cilium-dbg bgp routes advertised ipv4 unicast
```

---

## 5. 실무에서 확인

- 이천(현행 OS) 과 용인(신규 OS) 기능 차이 : resilient hashing 외에 export-gateway-ip · maximum-paths mixed 도 버전 확인 필요
- Cilium agent 롤링 업그레이드 : GR 을 끄면 노드마다 BGP 철회가 일어남 → 한 번에 한 노드, 노드 간 30초 이상 간격
- 1,000 사용자 멀티테넌트 : 사용자는 BGP CRD 권한이 없지만 서비스 type LoadBalancer 는 만들 수 있음 → VIP 풀(IPAM) 범위와 leaf prefix-list 범위를 같게 맞춤
- E810 + MTU 9000 : XDP 가속은 3KB 초과 프레임에서 막히므로 MTU 9000 에서는 XDP 를 안 쓰는 전제 유지
- 구축 후 RTT : 같은 leaf · 같은 Pod · Super Spine 경유 3구간을 측정해 이천 기준값과 비교

---

## 6. 용어 정리

- **iBGP 패브릭** : 패브릭 전체를 AS 하나로 묶고 IGP 위에 iBGP EVPN 을 올리는 구성
- **RR(route reflector)** : iBGP 경로를 다른 iBGP 피어에게 다시 전달하는 장비, 보통 spine
- **RD(route distinguisher)** : 같은 prefix 를 장비 · VRF 별로 구분하는 값
- **RT(route target)** : 경로를 어느 VRF 로 가져갈지 정하는 표식
- **Type-5** : EVPN IP prefix 경로. VIP /32 가 이 형태로 퍼짐
- **multipath-relax** : AS_PATH 내용이 달라도 길이가 같으면 ECMP 로 묶는 옵션
- **export-gateway-ip** : Type-5 에 원래 next-hop 을 실어 원격에서 노드 단위 ECMP 를 하게 하는 옵션
- **resilient hashing** : ECMP 멤버 변경 시 기존 흐름 배정을 최대한 유지하는 해시
- **BFD** : 수백 ms 단위로 경로 생존을 확인하는 경량 프로토콜
- **GR helper** : 이웃이 재시작하는 동안 그 이웃의 경로를 유지해주는 역할
- **null0 supernet** : 큰 대역을 버림 경로로 걸어 하위 미사용 대역 트래픽을 차단하는 방식
- **uRPF** : 출발지 주소로 돌아가는 경로가 들어온 포트와 맞는지 검사하는 기능

---

## 7. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 패브릭 | 스위치 간 iBGP EVPN (AS 1개, spine RR), 노드 ↔ leaf 는 eBGP |
| RD / RT | 자동이 맞음. RD 가 leaf 마다 달라야 ECMP 가 살아남 |
| ECMP 폭 | maximum-paths 와 ibgp 둘 다 64, 광고 노드 64 이하 |
| 분배 · 변경 | export-gateway-ip = 노드 단위 분배, resilient = 변경 시 유지. 둘은 다름 |
| 장애 감지 | BFD 대신 BGP 3/9, GR helper 끔과 Cilium GR 끔을 맞춤 |
| 보호 | null0 은 하이재킹을 못 막음 → leaf 수신 prefix-list 권고 |
| 기타 | MTU 9216 확인, uRPF 끔 동의, LACP fast 범위 확인 |

**NW 결정은 대부분 타당하고, 맞춰야 할 것은 Cilium 쪽 타이머 · GR 과 몇 가지 표현 차이다.**

관련 글 : Y지역 datalake 네트워크 아키텍처, Cilium Maglev 상세 가이드
