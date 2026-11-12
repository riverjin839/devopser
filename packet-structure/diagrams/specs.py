# packet 구조 학습 - Archify specs (Autumn leaves). N(id,type,label,sub,col,row,tag) E(from,to,label,variant)
SPECS = {
    "packet-01-encap-flow": dict(
        title="패킷 한 장이 만들어지는 순서", hero=["ip"], strong=["l4", "l2"], io=["app", "wire", "rx"],
        nodes=[N("app", "external", "앱 데이터", "HTTP · gRPC 요청", 0, 0, "1"),
               N("l4", "backend", "L4 헤더 추가", "TCP · UDP 포트", 1, 0, "2"),
               N("ip", "security", "L3 헤더 추가", "IP 주소 · TTL", 2, 0, "3"),
               N("l2", "backend", "L2 헤더 추가", "MAC · EtherType", 2, 1, "4"),
               N("wire", "external", "NIC 전송", "비트열로 변환", 1, 1, "5"),
               N("rx", "external", "수신 · 역캡슐화", "헤더를 순서대로 제거", 0, 1, "6")],
        edges=[E("app", "l4", "세그먼트화"), E("l4", "ip", "패킷화", "emphasis"),
               E("ip", "l2", "프레임화", "emphasis"), E("l2", "wire", "전송", "emphasis"),
               E("wire", "rx", "수신", "dashed")]),

    "packet-02-header-chain": dict(
        title="헤더는 다음 헤더를 가리킴", hero=["ip"], strong=["eth", "l4"], io=["data", "app"],
        nodes=[N("eth", "backend", "Ethernet", "14B · FCS 4B", 0, 0, "L2"),
               N("ip", "security", "IPv4", "20B 이상", 1, 0, "L3"),
               N("l4", "backend", "TCP · UDP", "20B 이상 · 8B", 2, 0, "L4"),
               N("data", "external", "페이로드", "애플리케이션 데이터", 2, 1, "L7"),
               N("app", "external", "앱 프로세스", "소켓으로 전달", 1, 1, "수신")],
        edges=[E("eth", "ip", "0x0800", "emphasis"),
               E("ip", "l4", "Proto 6 · 17", "emphasis"),
               E("l4", "data", "Port", "emphasis"),
               E("data", "app", "역캡슐화", "dashed")]),

    "packet-03-overlay-vxlan": dict(
        title="Cilium VXLAN 캡슐화 경로", hero=["encap"], strong=["podA", "podB"], io=["inner", "under"],
        nodes=[N("podA", "backend", "Pod A", "노드 1 · 원본 송신", 0, 0, "1"),
               N("inner", "external", "원본 패킷", "Pod IP 간 통신", 1, 0, "2"),
               N("encap", "security", "VXLAN 캡슐화", "UDP 8472 · VNI", 2, 0, "3"),
               N("under", "external", "Underlay 전송", "노드 IP 간 통신", 2, 1, "4"),
               N("decap", "backend", "VXLAN 해제", "노드 2 · 원본 복원", 1, 1, "5"),
               N("podB", "backend", "Pod B", "원본 수신", 0, 1, "6")],
        edges=[E("podA", "inner", "veth 송신"), E("inner", "encap", "터널 장치", "emphasis"),
               E("encap", "under", "+50B 헤더", "emphasis"), E("under", "decap", "물리망 통과", "emphasis"),
               E("decap", "podB", "veth 전달", "dashed")]),

    "packet-04-rocev2": dict(
        title="RoCEv2 패킷 층 구조", hero=["bth"], strong=["udp", "icrc"], io=["eth", "ip", "pay"],
        nodes=[N("eth", "external", "Ethernet", "L2 헤더", 0, 0, "1"),
               N("ip", "external", "IP", "라우팅 가능", 1, 0, "2"),
               N("udp", "backend", "UDP", "목적지 포트 4791", 2, 0, "3"),
               N("bth", "security", "BTH", "QP · PSN", 2, 1, "4"),
               N("pay", "external", "페이로드", "GPU 메모리 데이터", 1, 1, "5"),
               N("icrc", "backend", "ICRC", "끝에 붙는 4B CRC", 0, 1, "6")],
        edges=[E("eth", "ip", "L3 로 확장"), E("ip", "udp", "UDP 캡슐", "emphasis"),
               E("udp", "bth", "IB 전송 계층", "emphasis"), E("bth", "pay", "데이터 이어짐", "emphasis"),
               E("pay", "icrc", "무결성 검사", "dashed")]),

    "packet-05-debug-flow": dict(
        title="패킷 문제 추적 순서", hero=["tcpdump"], strong=["hubble", "mtu"], io=["symptom", "cause"],
        nodes=[N("symptom", "external", "증상 발생", "타임아웃 · 지연", 0, 0, "1"),
               N("hubble", "backend", "Hubble 확인", "drop 사유 조회", 1, 0, "2"),
               N("tcpdump", "security", "tcpdump 캡처", "veth · 노드 NIC", 2, 0, "3"),
               N("filter", "backend", "터널 포트 필터", "UDP 8472 구간", 2, 1, "4"),
               N("mtu", "backend", "MTU 점검", "50B 오버헤드 확인", 1, 1, "5"),
               N("cause", "external", "원인 확정", "조치 · 재발 방지", 0, 1, "6")],
        edges=[E("symptom", "hubble", "먼저 확인"), E("hubble", "tcpdump", "원인 불분명", "emphasis"),
               E("tcpdump", "filter", "구간 분리", "emphasis"), E("filter", "mtu", "단편화 의심", "emphasis"),
               E("mtu", "cause", "결론", "dashed")]),
}
