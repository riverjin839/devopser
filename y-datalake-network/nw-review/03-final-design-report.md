## Y지역 K8s lake 최종 설계 보고서 v2 - NW 검토 반영 (iBGP EVPN 패브릭)

> **목표** : NW 담당자 검토 결과를 반영해 Y지역 신규 lake 의 패브릭 · 노드 BGP · LB · 장애 대응 설계를 확정안으로 정리함

- 기준 : Cilium 1.20.x, Kubernetes 1.37, Cisco Nexus 9000 VXLAN BGP EVPN (용인 신규 OS), Intel E810, 최소 300노드
- 이전 문서 : Y지역 K8s lake 아키텍처 v1 (eBGP only 전제), NW 검토 판정 (`02-nw-review-verdict.md`)
- 설계도 : `y-k8s-lake-architecture-v2.drawio` (6페이지, Super Spine · Spine RR, L3 계층 표기 갱신)
- 상태 : 설계 확정, 표시한 NW 확인 항목 회신 후 상세 설정 작성

---

## 1. v1 대비 변경점

| 영역 | v1 (eBGP only) | v2 확정 (NW 검토 반영) | 이유 |
|---|---|---|---|
| 패브릭 라우팅 | IGP 없이 underlay · overlay eBGP | 언더레이 IGP + iBGP EVPN, spine RR | ASN 1개, RD/RT 자동, 운영 익숙도 |
| 스위치 ASN | Super Spine · Spine · 랙별 고유 ASN | 패브릭 AS 1개 | 같음 |
| 노드 ↔ leaf | eBGP (클러스터당 AS) | 변경 없음 (65101 · 65102) | 노드 경로를 패브릭이 재광고 |
| ECMP 옵션 | maximum-paths 64 + multipath-relax | maximum-paths 64 + ibgp 64, relax 없음 | 단일 노드 AS 라 AS_PATH 동일 |
| Type-5 분배 | VTEP 단위 | export-gateway-ip 로 노드 단위 | VTEP 별 노드 수 차이 보정 |
| 재해시 | resilient 지원 여부 미정 | resilient hashing 적용 (용인) | 노드 철회 시 흐름 유지 |
| 해시 seed | 계층별 분리 | 미적용 (NX-OS 기본) | 구축 후 측정으로 판단 |
| 장애 감지 | 패브릭 BFD + 노드 BGP 3/9 | BFD 미사용, 노드 BGP 3/9 | BFD 오탐 장애 이력 |
| GR | Cilium GR 짧게 | leaf helper 끔, Cilium GR 끔 | 노드 장애 시 블랙홀 제거 |
| MTU | 노드 9000, 패브릭 9216 | 변경 없음 (NW 9217 은 9216 으로 정정 요청) | Nexus 최대 9216 |
| 수신 보호 | 미정 | null0 supernet + leaf 수신 prefix-list 요청 | 잘못된 광고 차단 |
| uRPF | loose 검토 | 미적용 | ECMP · DSR 비대칭 |

**LB 구조(eTP Cluster · Maglev · DSR Geneve · 소켓 LB)는 그대로이고, 바뀐 것은 스위치 사이 라우팅과 장애 감지 방식이다.**

---

## 2. 전체 구조

| 계층 | 구성 | 역할 |
|---|---|---|
| FA Core | 2대 | DC 코어 · 방화벽 경계. Super Spine 과 VRF-lite eBGP |
| Super Spine | 4대, 400G | Pod 간 연결, Pod 간 EVPN RR (NW 확인) |
| Spine | Pod 별 4대, 400G | Com-1, Com-2, Storage. Pod 안 EVPN RR |
| Leaf | 랙마다 2대, 100G 다운링크 | VTEP, 노드와 eBGP |
| 랙 | 물리 서버 랙(Row A · B) / 스토리지 랙(Row C) 분리 | Com 252노드, AIStor 48노드 |

- 패브릭 = AS 1개. 언더레이 IGP 는 루프백 · VTEP 도달만 담당
- VRF 2개 : PRIVATE(동서 : Pod 간, ClusterMesh, EC 복제), PUBLIC(남북 : VIP, Egress)
- 클러스터 : Com K8s(ydl-com, AS 65101), AIStor K8s(ydl-aistor, AS 65102), ClusterMesh 로 연결

> 주의 : Super Spine 이 FA Core 와 VRF 단위로 붙으려면 border gateway 역할이 필요함. 안 되면 Border leaf 쌍을 추가함 (NW 확인)

---

## 3. 라우팅 설계

### 3-1. 패브릭

| 항목 | 설정 |
|---|---|
| 언더레이 | OSPF 또는 IS-IS, 루프백 · VTEP 만 |
| 오버레이 | iBGP l2vpn evpn, spine RR · Super Spine RR (계층 RR) |
| RD / RT | 자동 (RD = 라우터ID:VRF, RT = ASN:VNI) |
| 링크 장애 | 포트 다운 즉시 감지, BFD 없음 |
| 스위치 간 Port-Channel | LACP fast |
| MTU | 9216 전 구간 |
| uRPF | 미적용 |

### 3-2. leaf VRF (PUBLIC · PRIVATE 공통)

| 항목 | 설정 | 비고 |
|---|---|---|
| eBGP ECMP | `maximum-paths 64` | 로컬 노드가 보낸 VIP |
| iBGP ECMP | `maximum-paths ibgp 64` | 원격 leaf 가 보낸 Type-5 |
| 혼합 ECMP | `maximum-paths mixed` (지원 시) | 같은 leaf client 인입 분산. 없어도 Maglev 가 백엔드 균등화 |
| Type-5 | `export-gateway-ip` | 노드 단위 ECMP |
| 해시 | 5-tuple, resilient hashing | seed 는 기본값 |
| 노드 피어 템플릿 | remote-as 65101 · 65102, `timers 3 9` | BFD 대신 |
| GR | GR 적용, helper 끔 | 노드 경로 즉시 철회 |
| 수신 보호 | prefix-list(VIP 풀 · PodCIDR · 노드 루프백, le 32) + maximum-prefix | NW 요청 중 |

### 3-3. 노드 · Cilium

| 항목 | PRIVATE | PUBLIC |
|---|---|---|
| NIC | 2포트 (Storage 4포트), leaf A · B 에 하나씩 L3 | 2포트, leaf A · B 에 하나씩 L3 |
| 광고 | PodCIDR, 노드 루프백 /32, AIStor 내부 VIP | LoadBalancer VIP /32, Egress IP /32 |
| BGP | keepalive 3 · hold 9, GR 끔 | 같음 |

- Cilium : native routing, kube-proxy 대체(KPR), BGP Control Plane v2, Maglev(annotation), DSR Geneve, Egress Gateway, KVStoreMesh
- 노드 루프백 /32 광고는 export-gateway-ip 의 gateway IP 해석에도 쓰임
- VIP 광고 노드는 노드 그룹 라벨로 제한 (AIStor 48대 전체, Com 은 인입 그룹 32~48대) → ECMP 64 한도 안

> 주의 : NW 의 "Port-Channel LACP fast" 가 서버 bond 까지 뜻하면 이 표가 바뀜. 서버 vPC 로 가면 Cilium 피어링(SVI 또는 양쪽 leaf), advertise-pip, XDP 부착 위치를 재설계함

---

## 4. Client 위치별 LB

| client 위치 | 패브릭 (L3) | Cilium (L4) | 결과 |
|---|---|---|---|
| 외부 (FA Core) | Super Spine → 원격 leaf, gateway IP 로 노드 단위 ECMP | Maglev 로 백엔드 선택, DSR 응답 | 인입 · 처리 모두 균등 |
| 다른 Pod 서버 | spine 경유, 노드 단위 ECMP | 같음 | 균등 |
| 같은 leaf · 동일 망 | eBGP 우선으로 로컬 노드만 인입 (mixed 지원 시 분산) | Maglev 가 48개 전체에서 선택 → Geneve 로 전달 | 인입만 로컬, 처리는 균등 |
| K8s Pod | 해당 없음 (Pod IP 직결) | 소켓 LB, ClusterMesh Global Service | 균등 |

- Maglev 설정 : tableSize 16381, hashSeed 고정, `service.cilium.io/lb-algorithm: maglev` (AIStor · StarRocks VIP 만)
- 인입 노드가 바뀌어도 같은 백엔드를 고름 → resilient 미지원 구간(이천)에서도 연결 유지
- S3 데이터 경로는 L4 만, UI · API 는 Gateway API (L7)

---

## 5. 장애 대응

| 장애 | 감지 | 동작 | 영향 |
|---|---|---|---|
| 노드 링크 1개 | 포트 다운 즉시 | 남은 포트 세션 유지, 루프백 노드 IP 유지 | 거의 없음 |
| 노드 hang | BGP hold 9초 | 경로 철회 (helper 끔) → resilient 로 나머지 유지 | 그 노드 경유 연결, 최대 9초 |
| 노드 전원 장애 | 포트 다운 즉시 | 경로 철회 → Maglev 가 같은 백엔드 재선택 (DSR) | 그 노드 경유 연결만 |
| cilium-agent 재시작 | 세션 끊김 | 경로 철회 · 재광고, 데이터패스는 BPF 맵으로 계속 동작 | ECMP 멤버 변경 1회, 업그레이드는 한 노드씩 |
| leaf 1대 | 포트 다운 · IGP | 노드는 다른 leaf 포트로, 패브릭은 남은 VTEP | 그 leaf 경유 재전송 |
| spine · Super Spine 1대 | 포트 다운 · IGP | 남은 3대로 ECMP | 대역 25% 감소 |
| 잘못된 VIP 광고 | leaf 수신 필터 | 거부 · maximum-prefix 경고 | 없음 (필터 적용 시) |

**BFD 를 빼는 대신 "BGP 3/9 + GR helper 끔 + resilient + Maglev" 네 가지가 합쳐서 같은 역할을 한다.**

---

## 6. 검증 계획 (구축 후)

| 시험 | 내용 | 판정 |
|---|---|---|
| T1 | client 위치 4곳 warp GET | 노드별 요청 수 편차 ±10% |
| T2 | 원격 leaf ECMP 경로 수 | 광고 노드 수와 같음 (export-gateway-ip 확인) |
| T3 | 인입 노드 커널 hang | 9초 이내 철회, 다른 연결 끊김 0 |
| T4 | cilium-agent 롤링 재시작 | 끊긴 연결 0 |
| T5 | leaf 1대 전원 차단 | 재전송만, 세션 유지 |
| T6 | 범위 밖 /32 광고 | leaf 에서 거부 |
| T7 | RTT 3구간 (같은 leaf · 같은 Pod · Super Spine 경유) | 이천 기준 대비 p99 비교 |
| T8 | spine 업링크 사용률 | 편차 20% 이내 (넘으면 해시 seed 재검토) |
| T9 | 9000 바이트 DF ping, Geneve DSR | 단편화 없음 |

---

## 7. 남은 결정 · 리스크

| 항목 | 내용 | 담당 |
|---|---|---|
| RR 계층 | Super Spine · Spine RR 구성, cluster-id | NW |
| maximum-paths ibgp · mixed | VRF AF 반영, mixed 지원 OS | NW |
| export-gateway-ip | gateway IP 해석 (노드 루프백 수신) | NW · PoC |
| LACP fast 범위 | 스위치 간만인지 서버 bond 포함인지 | NW |
| GR helper | NX-OS 기본 켜짐 → 명시적으로 끄기 | NW |
| 수신 prefix-list | VIP 풀 · PodCIDR 범위 전달 후 적용 | NW · 플랫폼 |
| MTU 표기 | 9217 → 9216 | NW |
| 이천 연동 | resilient 미지원, EVPN 직접 연동 시 RT 수동 | NW · 플랫폼 |
| Egress Gateway | 노드 장애 시 재할당 시간 | PoC |
| ClusterMesh | 현행 minio-global 간헐 끊김 원인 확인 후 적용 | 운영 |

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 패브릭 | IGP + iBGP EVPN, AS 1개, spine · Super Spine RR, RD/RT 자동 |
| 노드 BGP | eBGP (65101 · 65102), 3/9 타이머, GR 끔 |
| ECMP | maximum-paths 64 + ibgp 64, export-gateway-ip, resilient |
| LB | eTP Cluster + Maglev + DSR Geneve, Pod 는 소켓 LB |
| 장애 | BFD 없음 → 타이머 · 즉시 철회 · resilient · Maglev |
| 보호 | null0 supernet + leaf 수신 prefix-list |
| 기타 | MTU 9216 / 노드 9000, uRPF 끔, RTT 는 구축 후 |

**v2 는 NW 표준(iBGP 패브릭)을 받아들이고, 위치와 무관한 부하분산은 Cilium Maglev 가 계속 책임지는 구조다.**
