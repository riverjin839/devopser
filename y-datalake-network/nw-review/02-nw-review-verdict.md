## Y지역 NW 검토 결과 판정 - 항목별 동의 · 조건부 · 이견

> **목표** : NW 담당자 검토 결과가 항목별로 맞는지 판정하고, 조건 · 이견 항목은 근거와 요청 사항을 정리함

- 대상 : Y지역 신규 datalake (Com K8s + AIStor K8s, Cilium 1.20 BGP, Nexus 9000 VXLAN EVPN, 300노드)
- 판정 기준 : 기능이 맞는가, 우리 LB 설계(eTP Cluster · Maglev · DSR)와 충돌이 없는가, 운영 리스크가 남는가
- 참고 : 개념 설명은 `01-nw-review-study.md`

---

## 1. 판정 요약

| 판정 | 개수 | 항목 |
|---|---|---|
| 동의 | 9 | 랙 분리, iBGP 패브릭, RD/RT 자동, ECMP 대역, multipath-relax · RT 불필요, resilient hashing, 해시 seed 미적용, uRPF 미적용 |
| 조건부 동의 | 6 | maximum-paths 64, BFD 미사용, LACP fast, GR 적용 · helper 미적용, MTU 9217, RTT 구축 후 측정 |
| 이견 · 정정 | 3 | spine EVPN 중계 불필요, VRF 수신 필터 미적용, export-gateway-ip = resilient |

**큰 방향(iBGP 패브릭, BFD 미사용, GR helper 미적용)은 모두 받아들일 수 있다.** 대신 Cilium 쪽 설정을 거기에 맞추고, 3개 항목은 표현 정정 또는 추가 보호가 필요함.

---

## 2. 항목별 판정

### 2-1. 구조

| # | NW 결정 | 판정 | 근거 | 요청 · 후속 |
|---|---|---|---|---|
| 1 | 물리 서버 / 스토리지 랙 분리 | 동의 | 기존 설계(Row A · B Com, Row C Storage)와 같음. EC 복제 · S3 트래픽이 Storage Spine 안에 머묾 | Storage leaf 업링크 비율 1 : 1 이하 유지 |
| 2 | iBGP 패브릭 유지 | 동의 | 300노드 · leaf 30여 대 규모에서 표준 구성. ASN 1개로 RD/RT 자동, 템플릿 단순. eBGP only 의 장애 범위 이점은 이 규모에서 작음 | 노드 ↔ leaf 는 eBGP 유지 확인 (노드 AS 65101 · 65102). Super Spine · Spine RR 계층 구조 문서화 |
| 3 | RD / RT 자동 | 동의 | 단일 AS 에서 RT = ASN:VNI 로 모든 leaf 동일, RD = 라우터ID:VRF 로 leaf 별 고유 → RR 이 경로를 전부 반사해 ECMP 유지 | 없음. 단, 이천 ↔ 용인 간 EVPN 을 직접 잇는다면 양쪽 ASN 이 달라 RT 수동 필요 |

### 2-2. ECMP

| # | NW 결정 | 판정 | 근거 | 요청 · 후속 |
|---|---|---|---|---|
| 4 | maximum-paths 64 | 조건부 | 값은 충분함. 단 iBGP 패브릭은 원격 Type-5 가 iBGP 경로라 `maximum-paths ibgp` 가 따로 있어야 함 | VRF AF 에 `maximum-paths 64` 와 `maximum-paths ibgp 64` 둘 다. 로컬 · 원격 혼합 ECMP 를 원하면 `maximum-paths mixed` 지원 여부 확인 |
| 4-1 | ECMP 대역 : 노드 100G, 업링크 400G | 동의 | 노드 1대가 받는 인입이 100G 를 넘지 않게 VIP 광고 노드 수가 충분함 | VIP 광고 노드 수가 64를 넘지 않게 노드 그룹 지정 (Com 252노드 전체 광고 금지) |
| 5 | multipath-relax 불필요 | 동의 | 클러스터별 노드 AS 가 하나라 같은 VIP 의 AS_PATH 가 모두 같음 | 노드마다 다른 AS 를 쓰는 설계로 바꾸면 다시 필요 |
| 6 | RT 별도 설정 불필요 | 동의 | 3번과 같은 이유 | 없음 |
| 7 | spine EVPN 중계 불필요 | 정정 | eBGP 용 중계 설정(`retain route-target all`, next-hop 유지)은 불필요가 맞음. 하지만 iBGP 에서는 spine 이 RR 로 EVPN 을 반사해야 함 → "중계" 역할 자체는 필요 | spine RR 설정, Super Spine 이 Pod 간 RR 인지 확인 |
| 8 | resilient hashing 적용 | 동의 | 노드 철회(GR 미적용 · agent 재시작) 때 나머지 흐름이 유지됨 | 이천 미지원 구간은 Maglev + DSR 로 흡수. 용인 OS 버전 · 지원 라인카드 명시 |
| 9 | 해시 seed 미적용 | 동의 | NX-OS 는 장비별 값을 섞어 해시하는 것이 기본이라 계층 간 쏠림이 크지 않음 | 구축 후 spine 업링크 사용률 편차 측정, 20% 넘으면 재검토 |
| 10 | export-gateway-ip 적용 (= resilient 와 같다) | 정정 | 적용은 동의. 다만 두 기능은 다름. gateway IP = 노드 단위로 고르게 분배, resilient = 멤버 변경 시 흐름 유지. 서로 보완 | 둘 다 적용. 원격 leaf 가 gateway IP(노드 루프백)를 해석할 수 있는지 확인 (Type-2 또는 /32 Type-5) |

### 2-3. 장애 감지

| # | NW 결정 | 판정 | 근거 | 요청 · 후속 |
|---|---|---|---|---|
| 11 | BFD 미사용 | 조건부 | 오탐 경험 존중. 직결 링크 장애는 포트 다운으로 즉시 감지됨. 남는 위험은 노드 hang | 노드 피어 템플릿에 `timers 3 9`. Cilium 도 keepalive 3 · hold 9. 기본값(NX-OS 60/180, Cilium 30/90)이면 hang 시 최대 3분 블랙홀 |
| 12 | Port-Channel LACP fast | 조건부 | 스위치 간 Port-Channel 이면 동의 | 서버 bond(vPC)까지 뜻하는지 확인. 기존 설계는 서버 bond 없이 포트별 L3 + BGP 2세션. 서버 vPC 로 바꾸면 Cilium 피어링 방식 · advertise-pip · XDP 부착 위치를 다시 설계해야 함 |
| 13 | GR 적용, helper 미적용 | 조건부 | 노드 장애 시 restart-time 블랙홀이 없어 오히려 깔끔함. 대신 agent 재시작마다 경로 철회 | Cilium `gracefulRestart.enabled: false` 로 맞춤. NX-OS 는 helper 기본 켜짐이라 명시적으로 끄는지 확인. Cilium 업그레이드는 한 노드씩 |

### 2-4. 기타

| # | NW 결정 | 판정 | 근거 | 요청 · 후속 |
|---|---|---|---|---|
| 14 | MTU 9217 | 조건부 | Nexus 9000 인터페이스 최대 MTU 는 9216. 9217 은 오기로 보임 | 패브릭 9216, 노드 9000 으로 문서 정정. 노드 측 E810 은 XDP 미사용 전제 |
| 15 | VRF 수신 필터 미적용 (null0 supernet) | 이견 | null0 은 패브릭에 없는 하위 대역을 버리는 용도. 노드가 잘못 광고한 /32 · /24 · 0/0 은 최장 일치로 null0 을 이겨 패브릭 전체에 퍼짐 | leaf 노드 피어 템플릿에 수신 prefix-list(VIP 풀 · PodCIDR · 노드 루프백, le 32) + `maximum-prefix`. 템플릿 1개라 운영 부담 작음 |
| 16 | uRPF 미적용 | 동의 | ECMP 비대칭과 DSR 응답(인입 노드를 안 거침)이 정상 경로라 strict 모드는 정상 트래픽을 버림 | 없음 |
| 17 | RTT 구축 후 측정 | 조건부 | 측정 자체는 구축 후가 맞음 | 측정 구간 · 도구 · 판정 기준을 미리 합의 (3절) |

---

## 3. 구축 후 측정 항목 (합의 요청)

| 측정 | 구간 | 도구 | 기대 |
|---|---|---|---|
| RTT | 같은 leaf / 같은 Pod 다른 leaf / Super Spine 경유 | `netperf -t TCP_RR`, `ping -c 1000` | 구간별 p50 · p99 를 이천 기준과 비교 |
| ECMP 분배 | VIP 1개 → 광고 노드 전체 | 노드별 `cilium-dbg metrics` 인입 패킷 | 노드 간 편차 ±15% 이내 |
| 노드 hang 감지 | 인입 노드 커널 정지 | `echo c > /proc/sysrq-trigger` | 경로 철회 9초 이내 |
| agent 재시작 | cilium-agent 재시작 | warp GET 부하 | 끊긴 연결 0 (resilient + Maglev) |
| 잘못된 광고 | 테스트 노드에서 범위 밖 /32 광고 | leaf 수신 확인 | prefix-list 로 거부 |
| MTU | 노드 간 9000 바이트 DF | `ping -M do -s 8972` | 단편화 없이 통과 |

---

## 4. NW 팀에 보낼 확인 · 요청 (정리본)

1. 노드 ↔ leaf 는 eBGP(노드 AS 65101 · 65102) 유지가 맞는지, Super Spine · Spine RR 계층은 어떻게 되는지
2. VRF AF 에 `maximum-paths ibgp 64` 도 들어가는지, `maximum-paths mixed` 지원 여부
3. export-gateway-ip 와 resilient hashing 은 별개 기능이므로 둘 다 적용 부탁. gateway IP 해석을 위해 노드 루프백 /32 수신 필요
4. BFD 미사용 대신 노드 피어 템플릿 `timers 3 9` 적용 요청
5. GR helper 를 명시적으로 끄는지 (NX-OS 기본 켜짐). Cilium 도 GR 을 끔
6. LACP fast 적용 범위가 스위치 간 Port-Channel 인지, 서버 bond 인지
7. MTU 9217 → 9216 정정 여부
8. leaf 노드 피어 템플릿 수신 prefix-list + maximum-prefix 적용 요청 (VIP 풀 · PodCIDR 범위 전달 예정)
9. 이천 · 용인 OS 별 지원 기능표 (resilient, export-gateway-ip, maximum-paths mixed)

---

## 5. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 동의 | 랙 분리, iBGP 패브릭, RD/RT 자동, relax 불필요, resilient, seed 미적용, uRPF 미적용 |
| 조건부 | maximum-paths 는 ibgp 도, BFD 대신 3/9, LACP 범위, GR helper 와 Cilium GR 일치, MTU 9216, RTT 기준 합의 |
| 이견 | spine 은 RR 로 반사 필요, gateway IP ≠ resilient, null0 은 하이재킹을 못 막음 |
| 우리 쪽 할 일 | Cilium 타이머 3/9, GR 끔, VIP 광고 노드 64 이하, VIP 풀 범위 전달 |

**판정 결과, 설계 방향은 그대로 가고 수신 필터 1건만 추가 요청하면 된다.**
