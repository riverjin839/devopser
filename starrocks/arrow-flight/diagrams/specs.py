# StarRocks Arrow Flight 내부·외부 성능 차이 - Archify specs (Autumn leaves). N(id,type,label,sub,col,row,tag) E(from,to,label,variant)
SPECS = {
    "af-01-overview": dict(
        title="Arrow Flight SQL 조회 흐름", stepx=340, hero=["be"], strong=["info", "batch"], io=["client", "df"],
        nodes=[N("client", "external", "Client", "ADBC · pyarrow", 0, 0, "1"),
               N("fe", "backend", "StarRocks FE", "GetFlightInfo · 9408", 1, 0, "2"),
               N("info", "messagebus", "FlightInfo", "Endpoint · Ticket", 2, 0, "3"),
               N("be", "database", "StarRocks BE", "DoGet · 9419", 2, 1, "4"),
               N("batch", "backend", "Arrow 배치", "RecordBatch 스트림", 1, 1, "5"),
               N("df", "frontend", "DataFrame", "pandas · polars", 0, 1, "6")],
        edges=[E("client", "fe", "SQL"), E("fe", "info", "계획"),
               E("info", "be", "Ticket"), E("be", "batch", "컬럼 그대로", "emphasis"),
               E("batch", "df", "변환 없음", "emphasis")]),

    "af-02-row-vs-col": dict(
        title="MySQL 프로토콜 vs Arrow Flight", stepx=340, hero=["arrow"], strong=["ser"], io=["mbe", "fbe"],
        nodes=[N("mbe", "database", "BE 컬럼 결과", "MySQL 프로토콜", 0, 0, "A"),
               N("ser", "backend", "행 직렬화", "행 단위 바이트", 1, 0, "A"),
               N("deser", "frontend", "행 파싱", "다시 컬럼 변환", 2, 0, "A"),
               N("fbe", "database", "BE 컬럼 결과", "Arrow Flight", 0, 1, "B"),
               N("arrow", "messagebus", "Arrow 배치", "포맷 그대로 전송", 1, 1, "B"),
               N("recv", "frontend", "Arrow 수신", "바로 DataFrame", 2, 1, "B")],
        edges=[E("mbe", "ser", "변환"), E("ser", "deser", "네트워크", "dashed"),
               E("fbe", "arrow", "직렬화 생략", "emphasis"), E("arrow", "recv", "gRPC", "emphasis")]),

    "af-03-in-vs-ex": dict(
        title="내부 1초 vs 외부 10초 경로", stepx=340, hero=["nginx"], strong=["fe", "lb"], io=["inpod", "ext"],
        nodes=[N("inpod", "frontend", "내부 Client", "Pod · 1초", 0, 1, "IN"),
               N("be", "database", "StarRocks BE", "9419 · 컬럼 실행", 2, 0),
               N("fe", "backend", "FE 프록시", "9408 · 기본 ON", 2, 1),
               N("ext", "external", "외부 Client", "사용자망 · 10초", 0, 2, "EX"),
               N("lb", "security", "Cilium LB", "LB-IPAM · L4", 1, 2),
               N("nginx", "backend", "ingress-nginx", "L7 · gRPC 재처리", 2, 2)],
        edges=[E("inpod", "fe", "ClusterIP 직결", "emphasis"),
               E("ext", "lb", "RTT · 대역폭"), E("lb", "nginx", "TCP"),
               E("nginx", "fe", "HTTP/2 재전송"), E("fe", "be", "fetch", "dashed")]),

    "af-04-diagnose": dict(
        title="원인 판별 순서", stepx=340, hero=["cnginx"], strong=["cnet"], io=["testc"],
        nodes=[N("testc", "external", "C 테스트", "외부 → L4 → FE", 0, 0, "1"),
               N("fast", "backend", "빨라짐", "1~2초 수준", 1, 0, "2"),
               N("cnginx", "security", "nginx 원인", "L7 재처리 병목", 2, 0, "3"),
               N("slow", "backend", "그대로 10초", "nginx 무관", 0, 1, "2"),
               N("iperf", "messagebus", "iperf3 비교", "MB/s ≈ 회선 속도", 1, 1, "3"),
               N("cnet", "cloud", "외부망 한계", "대역폭 · RTT", 2, 1, "4")],
        edges=[E("testc", "fast", "결과"), E("fast", "cnginx", "판정", "emphasis"),
               E("testc", "slow", "결과"), E("slow", "iperf", "측정"),
               E("iperf", "cnet", "판정", "emphasis")]),

    "af-05-target": dict(
        title="Gateway API 전환 후 권장 구조", stepx=340, hero=["l4"], strong=["gw", "fe"], io=["ext", "bevip"],
        nodes=[N("ext", "external", "외부 Client", "사용자망", 0, 0),
               N("gw", "security", "Cilium Gateway", "Envoy · HTTPRoute", 1, 0),
               N("ui", "frontend", "FE HTTP", "8030 · 웹 UI", 2, 0),
               N("l4", "messagebus", "Flight 전용 LB IP", "L4 · TCPRoute", 1, 1),
               N("fe", "backend", "FE Flight", "9408 · 세션 고정", 2, 1),
               N("bevip", "cloud", "BE별 LB IP", "선택 · 직접 DoGet", 1, 2),
               N("be", "database", "StarRocks BE", "9419", 2, 2)],
        edges=[E("ext", "gw", "HTTPS"), E("gw", "ui", "L7"),
               E("ext", "l4", "gRPC 직통", "emphasis"), E("l4", "fe", "L4 통과", "emphasis"),
               E("fe", "be", "프록시 fetch", "dashed"), E("bevip", "be", "병렬", "dashed")]),
}
