## 패킷 구조 - 헤더가 캡슐처럼 쌓이는 방식

> **목표** : Ethernet, IP, TCP/UDP 헤더 구조를 잡고, 오버레이(VXLAN)와 RoCEv2 로 이어서 Cilium 환경의 패킷 문제를 직접 추적할 수 있게 함

- 출처 : Cilium 공식 문서(Routing 개념), NVIDIA DOCA 문서(RoCE), RFC 7348(VXLAN), RFC 9638(NVO3 캡슐화 비교)
- 기준 버전 : Cilium 1.20.4 (2026-11 기준 최신 태그 확인)

---

## 1. 개요

패킷은 데이터 앞에 헤더를 한 겹씩 덧붙여 만든 캡슐임. 송신은 안쪽에서 바깥쪽으로 감싸고, 수신은 바깥쪽부터 벗겨냄.

<!-- diagram: mlpe-packet-01-encap-flow.html -->

- 앱 데이터 → L4 헤더(포트) → L3 헤더(IP) → L2 헤더(MAC) 순서로 감쌈
- 각 계층은 자기 헤더만 보고 판단함. 위 계층 내용은 열어보지 않음
- 터널(VXLAN)과 RoCEv2 도 같은 원리임. 헤더를 한 겹 더 얹거나 다른 헤더로 바꿀 뿐

**패킷 문제의 절반은 어느 층의 헤더를 보고 있는지 구분하는 것에서 풀린다.**

---

## 2. 개념 정리

### 2-1. 헤더 체인

각 헤더에는 다음 헤더가 무엇인지 알려주는 필드가 있음. 이 필드를 따라가면 패킷 전체를 읽을 수 있음.

<!-- diagram: mlpe-packet-02-header-chain.html -->

| 계층 | 헤더 | 크기 | 다음을 가리키는 필드 |
|---|---|---|---|
| L2 | Ethernet II | 14B (FCS 4B 별도) | EtherType (IPv4 = 0x0800, IPv6 = 0x86DD) |
| L3 | IPv4 | 20B 이상 (옵션 시 최대 60B) | Protocol (TCP = 6, UDP = 17) |
| L3 | IPv6 | 40B 고정 | Next Header |
| L4 | TCP | 20B 이상 (옵션 시 최대 60B) | 목적지 포트 |
| L4 | UDP | 8B 고정 | 목적지 포트 |

### 2-1-1. 헤더별 핵심 필드

| 헤더 | 핵심 필드 | 읽는 이유 |
|---|---|---|
| Ethernet | 목적지 MAC, 출발지 MAC, EtherType | 같은 L2 구간 안에서 다음 홉 결정 |
| IPv4 | 출발지 IP, 목적지 IP, TTL, Protocol, 단편화 필드 | 라우팅, 루프 방지, 단편화 여부 |
| TCP | 포트 2개, Seq, Ack, 플래그(SYN, ACK, FIN, RST), 윈도우 | 연결 상태, 재전송, 흐름 제어 |
| UDP | 포트 2개, 길이, 체크섬 | 연결 없이 포트로만 구분 |

- TCP 플래그를 보면 연결 단계가 보임. SYN 만 반복되면 응답이 없는 것이고, RST 가 오면 상대가 거부한 것임
- TTL 은 라우터를 지날 때마다 1씩 줄어듦. 0 이 되면 폐기됨

### 2-2. MTU 와 MSS

- MTU = 한 프레임에 실을 수 있는 L3 패킷 크기. 이더넷 기본 1500B
- MSS = TCP 가 한 번에 실을 수 있는 데이터 크기. IPv4 + TCP 기본 헤더 40B 를 빼서 1460B
- 헤더를 한 겹 더 얹으면 그만큼 데이터 자리가 줄어듦

> 주의 : MTU 를 넘는 패킷은 단편화되거나 버려짐. DF 비트가 켜져 있으면 버려지고, 경로 중간에서 ICMP 가 막히면 원인 모를 타임아웃으로 보임

### 2-3. 오버레이 캡슐화 (VXLAN)

Pod 간 패킷 전체(Ethernet 부터)를 UDP 안에 통째로 넣어서 노드 IP 끼리의 통신처럼 보이게 하는 방식임.

<!-- diagram: mlpe-packet-03-overlay-vxlan.html -->

- 바깥쪽에 Ethernet 14B, IP 20B, UDP 8B, VXLAN 8B 가 붙음 → 합계 50B 오버헤드
- VXLAN 헤더의 VNI(24비트)로 가상 네트워크를 구분함
- Cilium 문서 기준 VXLAN 은 8472/UDP, Geneve 는 6081/UDP 를 기본으로 씀
- 언더레이 장비에서는 안쪽 Pod IP 가 보이지 않고 노드 IP 와 UDP 포트만 보임

> 주의 : 표준 VXLAN 포트는 4789 지만 Cilium 기본값은 8472 임. 방화벽 정책을 4789 로만 열어두면 막힘

### 2-4. RoCEv2

RDMA 를 이더넷 위에서 쓰기 위한 방식임. GPU 노드 간 통신(Lake GPU 쪽)에서 만나게 됨.

<!-- diagram: mlpe-packet-04-rocev2.html -->

- RoCEv1 = Ethernet 바로 위에 IB 전송 계층. EtherType 0x8915, 같은 L2 구간에서만 통신
- RoCEv2 = Ethernet → IP → UDP(목적지 4791) → IB 전송 계층. IP 가 있어서 라우터를 넘을 수 있음
- UDP 출발지 포트를 흐름 구분용으로 써서 ECMP 분산이 가능함 (NVIDIA 문서 기준)
- BTH(Base Transport Header)에는 Opcode, 목적지 QP, PSN 이 들어가고 끝에 ICRC 4B 가 붙음. BTH 필드는 IB 스펙 일반 지식이며 위 NVIDIA 페이지에서는 직접 확인하지 못함

> 주의 : RoCEv2 는 패킷 손실에 약해서 보통 PFC 와 ECN 을 켠 무손실에 가까운 구성이 필요함. 스위치 설정은 별도로 확인해야 함

---

## 3. 구조 비교

### 3-1. 전달 방식 비교

| 방식 | 장점 | 단점 | 언제 쓰나 |
|---|---|---|---|
| VXLAN 터널 | 언더레이 요구사항 적음, 설정 단순 | 50B 오버헤드, 캡슐화 비용 | 네트워크를 건드리기 어려울 때 |
| Geneve 터널 | 옵션 필드로 메타데이터 확장 가능 | VXLAN 과 같은 오버헤드, 포트 6081 별도 허용 | 메타데이터가 필요한 기능을 쓸 때 |
| 네이티브 라우팅 | 캡슐화 없음, 헤더 단순 | 언더레이가 Pod IP 를 라우팅해야 함 | 네트워크 팀과 라우팅 협의가 가능할 때 |

- Cilium 문서 기준 터널 모드가 설정을 안 했을 때의 기본 동작임. 언더레이에 요구하는 것이 가장 적기 때문
- 오버헤드는 점보 프레임(9000B)에서 상대적으로 작아짐

### 3-2. RoCE 버전 비교

| 항목 | RoCEv1 | RoCEv2 |
|---|---|---|
| 캡슐 | Ethernet + IB | Ethernet + IP + UDP + IB |
| 식별자 | EtherType 0x8915 | UDP 목적지 포트 4791 |
| 범위 | 같은 L2 구간 | IP 라우팅 가능 |

---

## 4. 헤더 읽는 순서

문제가 생기면 아래 순서로 한 겹씩 확인함.

1. Ethernet : MAC 이 맞는지, VLAN 태그가 있는지
2. IP : 출발지와 목적지가 기대한 주소인지, TTL 이 남아 있는지
3. L4 : 포트와 플래그가 정상 흐름인지
4. 터널 구간이면 바깥 헤더(노드 IP, UDP 8472)와 안쪽 헤더(Pod IP)를 따로 읽음

---

## 5. 사용법 예시

### 5-1. 캡처

```bash
# 노드 NIC 에서 앞 5개만 링크 계층 포함 출력
tcpdump -nn -e -i eth0 -c 5

# 특정 Pod IP 의 TCP 443 만 확인
tcpdump -nn -i any host 10.0.1.23 and tcp port 443
```

### 5-2. 터널 구간 확인

```bash
# VXLAN 터널 포트만 캡처 (바깥 헤더 확인)
tcpdump -nn -i eth0 udp port 8472

# 터널 장치 상태 (터널 모드일 때 존재)
ip -d link show cilium_vxlan
```

### 5-3. 라우팅 모드 확인

```bash
# 우리 클러스터가 터널인지 네이티브 라우팅인지 확인
kubectl -n kube-system get cm cilium-config -o yaml | grep -E 'routing-mode|tunnel'
```

### 5-4. MTU 점검

```bash
# DF 비트를 켜고 크기를 올려가며 확인 (페이로드 + 28B = 패킷 크기)
ping -M do -s 1422 <상대 Pod IP>
```

- 통과하면 Pod 경로 MTU 가 1450 이상임
- 실패하는 크기가 곧 경로 MTU 의 힌트가 됨

### 5-5. 추적 순서

<!-- diagram: mlpe-packet-05-debug-flow.html -->

- 먼저 Hubble 로 drop 사유가 보이는지 확인함 (`hubble observe --verdict DROPPED`)
- 사유가 안 보이면 구간을 나눠서 tcpdump 로 확인함
- 터널 구간에서 큰 패킷만 실패하면 MTU 를 의심함

---

## 6. 실무에서 확인

- 터널 여부부터 확인 : 폐쇄망 bare-metal 클러스터가 VXLAN 터널인지 네이티브 라우팅인지에 따라 tcpdump 로 보이는 모습이 달라짐
- 방화벽·ACL : 터널 모드면 노드 간 UDP 8472(또는 설정한 포트) 허용 여부를 확인함
- 점보 프레임 : 노드 NIC, 스위치, Pod MTU 설정이 서로 맞아야 함. 한 곳이라도 작으면 큰 패킷만 실패함
- 대용량 S3 트래픽 : AIStor 같은 객체 스토리지 트래픽은 MSS 와 MTU 영향을 크게 받음. 대량 전송 성능이 이상하면 MTU 부터 확인함
- GPU 노드(Lake GPU) : B300 노드 간 통신이 RoCEv2 면 UDP 4791 과 무손실 설정(PFC, ECN)을 스위치 팀과 함께 확인함
- 이미지 미러링 구간 : 폐쇄망 프록시 구간은 L7 에서 끊기는 경우와 L3, L4 에서 끊기는 경우를 구분해서 봄
- 사용자 네임스페이스 : 1,000명 규모에서 증상이 특정 Pod 에만 있으면 노드 단위(MTU, NIC)인지 Pod 단위(NetworkPolicy)인지 먼저 나눔

---

## 7. 용어 정리

- **캡슐화(Encapsulation)** : 상위 데이터에 헤더를 덧붙이는 동작
- **EtherType** : Ethernet 헤더에서 다음 헤더 종류를 알리는 2B 필드
- **TTL(Time To Live)** : 라우터를 지날 때마다 줄어드는 IP 헤더 값. 루프 방지용
- **MTU(Maximum Transmission Unit)** : 한 프레임에 실을 수 있는 L3 패킷 최대 크기
- **MSS(Maximum Segment Size)** : TCP 한 세그먼트에 실을 수 있는 데이터 최대 크기
- **DF 비트(Don't Fragment)** : 켜져 있으면 단편화하지 않고 버리게 하는 IP 플래그
- **VXLAN(Virtual eXtensible LAN)** : L2 프레임을 UDP 에 넣어 L3 위로 확장하는 터널 방식
- **VNI(VXLAN Network Identifier)** : VXLAN 의 24비트 가상 네트워크 식별자
- **Geneve** : 옵션 필드를 확장할 수 있는 터널 방식. Cilium 기본 포트 6081
- **RoCEv2** : 이더넷 위에서 RDMA 를 IP 와 UDP 로 감싸 쓰는 방식. 포트 4791
- **BTH(Base Transport Header)** : IB 전송 계층의 기본 헤더. Opcode, QP, PSN 포함
- **ICRC(Invariant CRC)** : IB 패킷 끝에 붙는 무결성 검사 값

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 기본 원리 | 데이터에 L4, L3, L2 헤더를 순서대로 덧붙임. 수신은 역순으로 벗김 |
| 헤더 체인 | EtherType → Protocol → 포트 순으로 다음 헤더를 가리킴 |
| 크기 | Ethernet 14B, IPv4 20B 이상, TCP 20B 이상, UDP 8B |
| VXLAN | 바깥에 50B 추가. Cilium 기본 UDP 8472, Geneve 는 6081 |
| RoCEv2 | UDP 4791 위에 IB 전송 계층. IP 라우팅 가능 |
| 추적 순서 | Hubble → tcpdump(구간 분리) → MTU 점검 |
| 함정 | 방화벽 포트 불일치, MTU 불일치, 터널 모드 착각 |

**헤더를 층별로 나눠 읽으면 터널이든 RoCE 든 같은 방법으로 추적할 수 있다.**

관련 글 : Cisco N9K ECMP - K8s(Cilium BGP) 기준 정리 · Cilium Gateway API LB VIP 헤어핀
