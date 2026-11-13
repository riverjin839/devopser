# Cilium Maglev 학습 - Archify specs (Autumn leaves). N(id,type,label,sub,col,row,tag) E(from,to,label,variant)
SPECS = {
    "maglev-01-overview": dict(
        title="인입 노드가 달라도 같은 백엔드", stepx=340, hero=["table"], strong=["hash"], io=["client", "backend"],
        nodes=[N("client", "external", "Client 연결", "5-tuple", 0, 0, "1"),
               N("ecmp", "backend", "ECMP 라우터", "노드 아무나", 1, 0, "2"),
               N("node", "backend", "인입 노드", "A · B · C 누구든", 2, 0, "3"),
               N("hash", "messagebus", "5-tuple 해시", "시드 클러스터 공통", 2, 1, "4"),
               N("table", "security", "Maglev 표 조회", "M = 16381 슬롯", 1, 1, "5"),
               N("backend", "database", "백엔드 Pod", "모든 노드가 같은 답", 0, 1, "6")],
        edges=[E("client", "ecmp", "VIP"), E("ecmp", "node", "재해시 가능"),
               E("node", "hash", "CT 없음", "emphasis"), E("hash", "table", "해시 % M", "emphasis"),
               E("table", "backend", "같은 Pod", "emphasis")]),

    "maglev-02-build": dict(
        title="Maglev 표 생성 순서", stepx=340, hero=["fill"], strong=["perm"], io=["list", "map"],
        nodes=[N("list", "external", "백엔드 목록", "변경 시에만 재계산", 0, 0, "1"),
               N("offsk", "backend", "offset · skip", "해시 2개로 계산", 1, 0, "2"),
               N("perm", "backend", "선호 순열", "(offset + j·skip) % M", 2, 0, "3"),
               N("fill", "security", "슬롯 채우기", "라운드로빈 · 빈칸 1개씩", 2, 1, "4"),
               N("full", "backend", "표 완성", "백엔드당 M/N 슬롯", 1, 1, "5"),
               N("map", "external", "BPF 맵 반영", "노드마다 같은 표", 0, 1, "6")],
        edges=[E("list", "offsk", "백엔드별"), E("offsk", "perm", "소수 M", "emphasis"),
               E("perm", "fill", "차례로", "emphasis"), E("fill", "full", "M 칸 다 참", "emphasis"),
               E("full", "map", "agent 기록", "dashed")]),

    "maglev-03-packet": dict(
        title="패킷 한 개의 처리 흐름", stepx=340, hero=["lookup"], strong=["ct"], io=["pkt", "fwd"],
        nodes=[N("pkt", "external", "패킷 도착", "VIP 목적지", 0, 0, "1"),
               N("ct", "backend", "CT 조회", "기존 연결인가", 1, 0, "2"),
               N("hit", "backend", "기존 백엔드", "CT 기록 그대로", 2, 0, "hit"),
               N("lookup", "security", "Maglev 조회", "표[해시 % M]", 1, 1, "3"),
               N("rec", "backend", "CT 기록", "다음 패킷은 hit", 2, 1, "4"),
               N("fwd", "external", "백엔드 전달", "DSR · SNAT", 2, 2, "5")],
        edges=[E("pkt", "ct", "조회"), E("ct", "hit", "hit", "dashed"),
               E("ct", "lookup", "miss", "emphasis"), E("lookup", "rec", "선택", "emphasis"),
               E("rec", "fwd", "전달", "emphasis")]),

    "maglev-04-disruption": dict(
        title="백엔드가 빠질 때 일어나는 일", stepx=340, hero=["recalc"], strong=["keep"], io=["drain", "result"],
        nodes=[N("drain", "external", "백엔드 1개 제거", "장애 · 가중치 0", 0, 0, "1"),
               N("recalc", "security", "표 재계산", "같은 알고리즘", 1, 0, "2"),
               N("moved", "backend", "빈 슬롯 재배치", "그 백엔드 몫 1/N", 2, 0, "3"),
               N("extra", "backend", "추가 이동", "다른 슬롯 1% 미만", 2, 1, "4"),
               N("keep", "backend", "CT 있는 연결", "노드 안에선 유지", 1, 1, "5"),
               N("result", "external", "대부분 연결 유지", "mod N 은 98% 이동", 0, 1, "6")],
        edges=[E("drain", "recalc", "EndpointSlice"), E("recalc", "moved", "필수 이동", "emphasis"),
               E("moved", "extra", "부수 이동", "dashed"), E("extra", "keep", "CT 우선"),
               E("keep", "result", "끊김 최소", "emphasis")]),
}
