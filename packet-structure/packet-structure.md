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

## 6. 패킷 여행 - JSON hello 가 A 에서 B 로

> 가정 : A 와 B 는 같은 스위치에 붙은 같은 서브넷(/24 가정, 마스크는 확인 못 함). 포트 8080, MAC, 임시 포트는 예시 값

### 6-1. 시나리오

- A 노드(10.40.24.1)의 클라이언트가 B 노드(10.40.24.2)의 서버로 HTTP 요청을 보냄
- 요청 = `POST /hello`, 본문 = JSON `{"message":"hello"}` (19B)
- 응답 = `200 OK`, 본문 = `{"status":"ok"}` (15B)

<!-- diagram: mlpe-packet-06-journey.html -->

### 6-2. 단계별 여행

| 단계 | 위치 | 일어나는 일 |
|---|---|---|
| 1 | A 앱 | HTTP 요청 문자열을 만들고 소켓 send() 로 커널에 넘김 |
| 2 | A 커널 | 목적지 10.40.24.2 가 같은 서브넷인지 확인 → 같음 → 게이트웨이 없이 직접 전달 |
| 3 | A 커널 | ARP 캐시에 B 의 MAC 이 없으면 ARP(Address Resolution Protocol) 요청을 브로드캐스트 → B 가 자기 MAC 으로 응답 |
| 4 | A 커널 | TCP 3-way handshake 로 연결 수립 (6-3 참고) |
| 5 | A 커널 | HTTP 를 TCP 세그먼트에 싣고 IP, Ethernet 순으로 감쌈 (6-4 참고) |
| 6 | A NIC | 프레임을 비트로 바꿔 케이블로 송신 |
| 7 | 스위치 | 목적지 MAC 으로 MAC 테이블을 조회해 해당 포트로만 전달. 테이블에 없으면 모든 포트로 뿌림(flooding) |
| 8 | B NIC, 커널 | 목적지 MAC 확인 → IP 목적지 확인 → Protocol 6 → TCP 포트 8080 → 소켓 |
| 9 | B 앱 | JSON 을 파싱해 응답을 만들고 같은 경로를 거꾸로 되돌려 보냄 |

> 주의 : 서브넷이 다르면 A 는 B 의 MAC 이 아니라 게이트웨이의 MAC 으로 프레임을 보냄. IP 주소는 끝까지 그대로고, MAC 만 홉마다 바뀜

### 6-3. TCP 연결과 요청, 응답

<!-- diagram: mlpe-packet-09-tcp-flow.html -->

| 번호 | 방향 | 플래그 | 내용 |
|---|---|---|---|
| 1 | A → B | SYN | 연결 요청. 시퀀스 번호 시작값과 MSS 같은 옵션을 알림 |
| 2 | B → A | SYN, ACK | 요청 수락. B 의 시퀀스 번호를 알림 |
| 3 | A → B | ACK | 연결 수립 완료 |
| 4 | A → B | PSH, ACK | HTTP 요청 113B (헤더 94B 와 본문 19B) |
| 5 | B → A | ACK | 수신 확인. 응답과 합쳐져 생략되기도 함 |
| 6 | B → A | PSH, ACK | HTTP 응답 86B (헤더 71B 와 본문 15B) |
| 7 | A → B | ACK | 응답 수신 확인 |
| 8 | 양쪽 | FIN, ACK | 연결 종료. 누가 먼저 끊는지는 서버와 클라이언트 구현에 따라 다름 |

- 임시 포트(Ephemeral port) = A 가 연결마다 커널에서 받는 출발지 포트. 응답이 돌아올 문패 역할
- 1~3 번이 3-way handshake 이고 이후부터 데이터가 오감
- 플래그 조합은 일반적인 흐름이며 실제 캡처에서 합쳐지거나 나뉠 수 있음
- 같은 PC 의 loopback 에서 curl 과 Python http.server 로 측정한 결과는 이 표와 달랐음
  - 응답 헤더와 본문이 별도 세그먼트로 나뉨
  - HTTP/1.0 서버라 서버가 먼저 FIN 을 보냄
  - 이 표는 흐름을 보여주는 기준이고 실제 패킷 수는 클라이언트와 서버 조합에 따라 달라짐

### 6-4. 세그먼트, 패킷, 프레임 그리고 요청 프레임 한 장

같은 데이터가 어느 계층에서 보느냐에 따라 이름이 달라짐

| 계층 | 부르는 이름 | 헤더 | 누적 크기 |
|---|---|---|---|
| L7 | 데이터(HTTP 요청) | 없음 | 113B |
| L4 | 세그먼트(Segment) | TCP 20B | 133B |
| L3 | 패킷(Packet) | IP 20B | 153B |
| L2 | 프레임(Frame) | Ethernet 14B | 167B |
| L1 | 비트 | FCS 4B 는 NIC 이 추가 | 171B |

<!-- diagram: mlpe-packet-07-pdu.html -->

A 는 헤더를 바깥쪽으로 쌓고, B 는 바깥쪽부터 하나씩 벗김

<!-- diagram: mlpe-packet-08-encap-decap.html -->

- 캡슐화(A) = 앱 데이터 → TCP 헤더 → IP 헤더 → Ethernet 헤더
- 역캡슐화(B) = Ethernet 확인(내 MAC) → IP 확인(내 IP, Protocol 6) → TCP 확인(포트 8080) → 소켓

요청 프레임 한 장의 내용

| 계층 | 내용 | 크기 |
|---|---|---|
| Ethernet | 목적지 MAC = B, 출발지 MAC = A, EtherType 0x0800 | 14B |
| IPv4 | 10.40.24.1 → 10.40.24.2, Protocol 6, TTL | 20B |
| TCP | 출발지 = 임시 포트, 목적지 = 8080 (옵션 제외) | 20B |
| HTTP 헤더 | POST /hello, Host, Content-Type, Content-Length | 94B |
| JSON 본문 | {"message":"hello"} | 19B |
| 합계 | FCS 4B 제외 | 167B |

- 의미 있는 데이터는 19B 뿐이고 나머지 148B 는 헤더임
- IP 패킷 크기 153B 는 MTU 1500B 보다 훨씬 작아서 단편화 없이 한 프레임으로 감
- 위 크기는 최소 헤더로 직접 계산한 예시값임
- 실제 캡처는 TCP 옵션(SYN 은 40B, 그 외 타임스탬프로 32B)과 curl 의 헤더 때문에 더 큼
  - loopback 측정 = curl 요청 본문 154B, 프레임 220B
- 그래서 캡처 값이 예시와 달라도 정상임. 구조(층 순서)를 확인하는 용도임

### 6-5. 폐쇄망에서 Linux 2대로 직접 확인

> 주의 : 아래 명령은 loopback 에서 일부 확인했고 2대 실장비에서는 실행 검증 전인 개념 코드임. 인터페이스 이름과 IP 는 환경에 맞게 변경

**준비**

- A, B 가 같은 서브넷이고 root(또는 sudo) 권한이 있어야 함
- 인터페이스 이름 확인 : `ip -br addr` (아래 eth0 는 예시)
- B 의 방화벽에서 8080 허용 (firewalld 면 `firewall-cmd --add-port=8080/tcp`)
- 외부 도구 없이도 가능함 : B 는 python3 만 있으면 서버가 되고 A 는 curl 이나 python3 로 요청 가능
- tcpdump 가 없으면 인터넷 되는 PC 에서 같은 OS 버전의 패키지(rpm 또는 deb)와 의존 라이브러리(libpcap)를 받아 반입 후 설치
  - RHEL 계열 = `rpm -ivh libpcap*.rpm tcpdump*.rpm`
  - Debian 계열 = `dpkg -i libpcap*.deb tcpdump*.deb`
- Wireshark 는 GUI PC 에 설치하고 pcap 파일만 옮겨서 봄. 서버에는 tshark(CLI)만 있어도 됨

**1단계 : B 에서 서버 실행**

```bash
# B : JSON POST 를 받아 {"status":"ok"} 를 돌려주는 최소 서버
cat > server.py <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        print('받은 본문 :', self.rfile.read(n))
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
HTTPServer(('0.0.0.0', 8080), H).serve_forever()
PY
python3 server.py
```

**2단계 : B 에서 캡처 시작 (다른 터미널)**

```bash
# ARP 까지 보려면 A 에서 먼저 ip neigh flush 해 둠
# -nn = 이름 변환 끔, -e = MAC 표시, -w = 파일 저장
tcpdump -nn -e -i eth0 -w hello.pcap \
  'arp or (host 10.40.24.1 and tcp port 8080)'
```

**3단계 : A 에서 요청**

```bash
# A : ARP 캐시 비우고 경로 확인
sudo ip neigh flush to 10.40.24.2
ip route get 10.40.24.2          # via 없이 dev 만 나오면 같은 서브넷

# A : JSON hello 전송
curl -s -X POST http://10.40.24.2:8080/hello \
  -H 'Content-Type: application/json' -d '{"message":"hello"}'

# A : B 의 MAC 이 캐시에 들어왔는지 확인
ip neigh show 10.40.24.2
```

**4단계 : 결과 읽기**

```bash
# 화면으로 바로 확인 (MAC 과 플래그)
tcpdump -nn -e -r hello.pcap

# 본문까지 보기 : -A (ASCII), -X (hex + ASCII)
tcpdump -nn -A -r hello.pcap 'tcp port 8080'

# tshark 로 흐름 정리 (서버에 tshark 가 있을 때)
tshark -r hello.pcap -Y 'tcp.port==8080' \
  -T fields -e frame.number -e ip.src -e ip.dst -e tcp.flags.str -e frame.len
```

**Wireshark 로 볼 때**

- hello.pcap 을 GUI PC 로 옮겨 열기
- 디스플레이 필터 : `arp || (ip.addr==10.40.24.1 && tcp.port==8080)`
- 패킷 선택 후 가운데 창에서 Frame → Ethernet → IP → TCP → HTTP 순으로 펼치면 캡슐화 층이 그대로 보임
- 우클릭 → Follow → TCP Stream : 요청과 응답 본문을 한 번에 봄
- Statistics → Flow Graph : 6-3 의 SYN → SYN,ACK → ACK 흐름을 그림으로 확인
- 프레임 길이는 Frame 항목의 Frame Length 로 확인

**확인할 것**

| 확인 | 볼 곳 | 기대 결과 |
|---|---|---|
| 같은 서브넷 | `ip route get` | via 없음 |
| ARP | 캡처 첫 두 줄 | A 가 who-has 브로드캐스트, B 가 is-at 응답 |
| MAC | `-e` 출력 | 출발지 = A 의 MAC, 목적지 = B 의 MAC |
| 3-way handshake | 플래그 | [S] → [S.] → [.] |
| 데이터 | `[P.]` 와 length | 요청 본문 19B 가 들어간 세그먼트 |
| 종료 | `[F.]` | 마지막에 FIN 교환 |

**자주 걸리는 함정**

> 주의 : `-i any` 로 캡처하면 Ethernet 헤더 대신 cooked 헤더가 붙어서 MAC 이 안 보임. MAC 을 보려면 인터페이스를 지정함

- 송신 측(A) 에서 캡처하면 체크섬이 incorrect 로 보일 수 있음 = NIC 체크섬 오프로드 때문이며 정상임 (`ethtool -k eth0` 로 확인)
- 오프로드(TSO, GRO) 가 켜져 있으면 MTU 보다 큰 프레임이 캡처에 보일 수 있음
- 응답 헤더와 본문이 별도 패킷으로 보이거나, FIN 을 서버가 먼저 보내는 건 정상 (6-3 참고)
- 같은 스위치 안의 통신만 보이므로 제3의 노드에서는 캡처가 안 됨 (스위치가 해당 포트로만 전달). A 나 B 에서 캡처함
- 이 경로는 노드 IP 끼리의 직접 통신이라 VXLAN 캡슐화가 없음. 터널은 Pod IP 끼리 통신할 때만 붙음 (2-3 참고)

**IP 는 끝까지 그대로고 MAC 은 홉마다 바뀐다.**

---

## 7. 실무에서 확인

- 노드 IP 끼리 통신 : 10.40.24.x 같은 노드 간 직접 통신은 터널 없이 6장 경로 그대로임
- 터널 여부부터 확인 : 폐쇄망 bare-metal 클러스터가 VXLAN 터널인지 네이티브 라우팅인지에 따라 tcpdump 로 보이는 모습이 달라짐
- 방화벽·ACL : 터널 모드면 노드 간 UDP 8472(또는 설정한 포트) 허용 여부를 확인함
- 점보 프레임 : 노드 NIC, 스위치, Pod MTU 설정이 서로 맞아야 함. 한 곳이라도 작으면 큰 패킷만 실패함
- 대용량 S3 트래픽 : AIStor 같은 객체 스토리지 트래픽은 MSS 와 MTU 영향을 크게 받음. 대량 전송 성능이 이상하면 MTU 부터 확인함
- GPU 노드(Lake GPU) : B300 노드 간 통신이 RoCEv2 면 UDP 4791 과 무손실 설정(PFC, ECN)을 스위치 팀과 함께 확인함
- 이미지 미러링 구간 : 폐쇄망 프록시 구간은 L7 에서 끊기는 경우와 L3, L4 에서 끊기는 경우를 구분해서 봄
- 사용자 네임스페이스 : 1,000명 규모에서 증상이 특정 Pod 에만 있으면 노드 단위(MTU, NIC)인지 Pod 단위(NetworkPolicy)인지 먼저 나눔

---

## 8. 용어 정리

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

## 9. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 기본 원리 | 데이터에 L4, L3, L2 헤더를 순서대로 덧붙임. 수신은 역순으로 벗김 |
| 헤더 체인 | EtherType → Protocol → 포트 순으로 다음 헤더를 가리킴 |
| 크기 | Ethernet 14B, IPv4 20B 이상, TCP 20B 이상, UDP 8B |
| VXLAN | 바깥에 50B 추가. Cilium 기본 UDP 8472, Geneve 는 6081 |
| RoCEv2 | UDP 4791 위에 IB 전송 계층. IP 라우팅 가능 |
| 패킷 여행 | 서브넷 판단 → ARP → 3-way handshake → 캡슐화 → 스위치 → 역캡슐화. 요청 프레임 167B 중 JSON 은 19B |
| 추적 순서 | Hubble → tcpdump(구간 분리) → MTU 점검 |
| 함정 | 방화벽 포트 불일치, MTU 불일치, 터널 모드 착각 |

**헤더를 층별로 나눠 읽으면 터널이든 RoCE 든 같은 방법으로 추적할 수 있다.**

관련 글 : Cisco N9K ECMP - K8s(Cilium BGP) 기준 정리 · Cilium Gateway API LB VIP 헤어핀
