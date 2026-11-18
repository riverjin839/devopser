#!/usr/bin/env python3
"""Y1 완결 보고서 그림 : 0 · 3 ~ 9장 (1 · 2장은 gen_v2 재사용). USE_KEY=1 로 실행."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from figlib2 import Page, drawio, svg
import gen_v2 as g2

OUT = os.path.dirname(os.path.abspath(__file__)) + "/.."


# ================================================================ 0 : 요약용
def fig0_1():
    # 그림 = 구조만 (제목 · 설명은 .md 캡션). ClusterMesh · 내부 client → global-svc 경로 포함
    p = Page("그림 0-1 전체 구조", 1400, 760)
    d = -84
    cl = p.box(250, 104 + d, 260, 54, "외부 ETL client\n원천 소스", "plain", size=12, cube=True)
    fa = p.box(570, 104 + d, 260, 54, "FA Core\nDC 코어 · 방화벽", "device", size=12, cube=True)
    p.edge(cl, fa, "S3 443", "norm")
    ss = p.box(400, 184 + d, 600, 58, "Super Spine (세 구간에 걸친 같은 패브릭)\nBorder · VRF PUBLIC / PRIVATE", "device", size=12, cube=True)
    p.edge(fa, ss, "", "norm")
    zones = [(30, "DCNY01 (Compute K8s)", "Compute 노드\nSpark · Airflow · ETL\nbond0 · bond1",
              ("Compute K8s (Cilium)\nETL client Pod\nSpark · Airflow · Arrow Flight", "key", 120)),
             (490, "DCNY02 (GPU)", "GPU 노드\nAI 학습 · 추론\nbond0 · bond1",
              ("GPU K8s (Cilium)\n학습 Pod\nS3 읽기 · 체크포인트", "note", 92)),
             (950, "DCNY03 (Storage K8s)", "AIStor 노드\nVIP /32 BGP 광고\nbond0 · bond1",
              ("Storage K8s (AIStor)\nglobal-svc (Global Service)\n→ AIStor Pod", "good", 120))]
    cbox = []
    for x0, zn, nd, (ct, ck, ch) in zones:
        p.box(x0, 270 + d, 420, 462, zn, "zone", bold=True, size=13, valign="top", align="right" if x0 == 950 else "left")
        sp = p.box(x0 + 100, 304 + d, 220, 50, "Spine", "device", size=12, cube=True)
        lf = p.box(x0 + 80, 384 + d, 260, 56, "ToR leaf 쌍 (VTEP)\n랙당 서버 수 동일", "device", size=12, cube=True)
        n = p.box(x0 + 60, 470 + d, 300, 92, nd, "good" if "AIStor" in nd else "node", size=12, cube=True)
        c = p.box(x0 + 30, 590 + d, 360, ch, ct, ck, size=12)
        cbox.append(c)
        sx, tx = {30: (0.05, 0.85), 490: (0.5, 0.85), 950: (1.0, 0.1)}[x0]   # 구역 제목과 교차 방지 (DCNY03 제목은 오른쪽)
        p.edge(ss, sp, "", "norm", both=True, anc=(sx, 1, tx, 0))
        p.edge(sp, lf, "", "norm", both=True)
        p.edge(lf, n, "802.3ad", "norm", both=True)
        p.edge(n, c, "", "norm", both=True)
    # 내부 client → global-svc : 외부 VIP 미경유, Pod IP 직결 (bond1 PRIVATE, 패브릭 경유)
    p.edge(cbox[0], cbox[2], "S3 적재 → global-svc\nbond1 PRIVATE", "hot", anc=(1, 0.95, 0, 0.95))
    # ClusterMesh : Service · Endpoint 동기화 (제어)
    cm = p.box(30, 750 + d, 1340, 60, "ClusterMesh : KVStoreMesh · clustermesh-apiserver × 2\nglobal-svc Service · Endpoint 를 세 클러스터에 동기화", "device", size=13, cube=True)
    p.edge(cbox[0], cm, "동기화", "idle", both=True, anc=(0.5, 1, 0.163, 0))
    p.edge(cbox[1], cm, "", "idle", both=True, anc=(0.1, 1, 0.399, 0))
    p.edge(cbox[2], cm, "동기화", "idle", both=True, anc=(0.5, 1, 0.849, 0))
    return p


def fig0_2():
    p = Page("그림 0-2 분산 3단계 전후", 1400, 740)
    p.title("그림 0-2. 분산 3단계 : I Lake → Y1",
            "인입 노드(패브릭) · 백엔드(L4) · 송신 멤버(bond) 세 단계가 모두 고르게 나뉘어야 AIStor 전체가 고르게 일함")
    heads = ["① 패브릭 ECMP : 어느 노드로 들어오나", "② L4 LB : 어느 AIStor Pod 가 처리하나", "③ 노드 · bond : 어느 링크로 나가나"]
    for i, h in enumerate(heads):
        p.box(30 + i * 460, 104, 420, 40, h, "device", bold=True, size=13)
    rows = [
        ("I Lake (현행)", [
            ("· 랙 혼재 → 랙마다 AIStor 수 다름\n· igp-metric ignore 적용\n· RD · maximum-paths : NW 확인 대기", "hot", "랙별 몫 불균등"),
            ("· random (Maglev 미사용)\n· SNAT (응답이 인입 노드 경유)\n· eTP Local Service 4개 · 소켓 LB off", "hot", "인입 쏠림 → 처리 쏠림"),
            ("· 802.3ad · layer3+4 (정상)\n· LACP slow · MTU 1500\n· cubic · 버퍼 25M · tuned 없음", "plain", "분산 정상, 감지 · 대역 개선")]),
        ("Y1 (개선)", [
            ("· 역할별 랙 분리 · 랙당 동일\n· RD 고유 · maximum-paths 64\n· export-gateway-ip · resilient", "good", "노드당 몫 동일"),
            ("· Maglev (AIStor VIP annotation)\n· DSR Geneve (응답 직접)\n· eTP Cluster · 소켓 LB on", "good", "인입 무관 전체 Pod 균등"),
            ("· 802.3ad · layer3+4 (유지)\n· LACP fast · MTU 9000\n· BBR + fq · 128M · IRQ NUMA", "good", "감지 3초 · 100G 대역")]),
    ]
    y = 160
    for label, cells in rows:
        p.zone(20, y, 1360, 270, label)
        prev = None
        for i, (txt, k, verdict) in enumerate(cells):
            x = 30 + i * 460
            b = p.box(x, y + 36, 420, 150, txt, k if k != "hot" else "plain", size=13, align="left")
            v = p.box(x, y + 200, 420, 50, verdict, k if k != "plain" else "note", bold=True, size=14)
            if prev:
                p.edge(prev, b, "", "hot" if label.startswith("I") else "good")
            prev = b
        y += 290
    return p


# ================================================================ 0-3 · 0-4 : 패킷 흐름 (client IP → 대상 S3)
def _flow(p, top, req, resp, req_title, resp_title, req_labels, resp_labels):
    """req : 8 단계, resp : 4 단계. 단계 = (글자, 종류, 패킷 헤더). 위 줄 → 오른쪽, 둘째 줄 ← 왼쪽, 응답 줄 → 오른쪽."""
    X = [50, 390, 730, 1070]
    W, SH, PH = 300, 96, 76
    p.box(20, top, 1360, 462, req_title, "zone", bold=True, size=13, valign="top", align="left")
    p.box(20, top + 482, 1360, 236, resp_title, "zone", bold=True, size=13, valign="top", align="right")   # ⑧→⑨ 연결선과 겹침 방지
    rows = [(top + 32, X, req[:4]), (top + 262, X[::-1], req[4:]), (top + 514, X, resp)]
    S, P = [], []
    for y, xs, steps in rows:
        for x, (txt, k, pk) in zip(xs, steps):
            S.append(p.box(x, y, W, SH, txt, k, size=13, cube=True))
            P.append(p.box(x, y + SH + 12, W, PH, pk, "note", size=12))
    labels = req_labels + [None] + resp_labels
    for i in range(len(S) - 1):
        a, b = (P[i], S[i + 1]) if i in (3, 7) else (S[i], S[i + 1])
        kind = "good" if i >= 8 else ("back" if i == 7 else "norm")
        lab = (labels[i] or "") if i == 3 and labels[i] else ""      # 가로 연결선은 라벨 없음 (패킷 상자에 같은 정보)
        p.edge(a, b, lab, kind)
    return S, P


def fig0_3():
    p = Page("그림 0-3 외부 client 패킷 흐름", 1400, 760)
    req = [("① 외부 ETL client\nC-IP\nS3 요청 (TCP 443)", "plain", "C-IP : sport → VIP : 443"),
           ("② FA Core\n방화벽 허용\nVIP 대역 → Border", "device", "C-IP → VIP\n(변경 없음)"),
           ("③ Border (Super Spine)\nVIP/32 Type-5 · ECMP V 경로\n5-tuple 해시 → leaf 선택", "device", "바깥 : Border VTEP → leaf VTEP\nUDP 4789 · L3VNI PUBLIC\n안 : C-IP → VIP"),
           ("④ Spine\nunderlay 라우팅\n바깥 IP(VTEP) 만 봄", "device", "바깥 : Border VTEP → leaf VTEP\n안 : C-IP → VIP"),
           ("⑤ Storage leaf (VTEP)\nVXLAN 풂 · VRF PUBLIC\nVIP/32 → 노드 BGP multipath", "device", "C-IP → VIP\n→ 인입 노드 N1 bond0 (802.3ad)"),
           ("⑥ 인입 노드 N1 (bond0)\nCilium XDP · tc\nMaglev → AIStor Pod (N2)", "key", "바깥 : N1 → N2 (Geneve UDP 6081)\n안 : C-IP → VIP (보존)"),
           ("⑦ 백엔드 노드 N2\nGeneve 풂 · VIP → P-IP\nnetkit 로 Pod 전달", "node", "C-IP → P-IP : 포트\n(client IP 보존)"),
           ("⑧ AIStor Pod\nS3 처리\nclient IP = C-IP", "good", "응답 생성\nP-IP → C-IP")]
    resp = [("⑨ N2 역 NAT\nsrc P-IP → VIP\nbond0 로 직접 송신", "good", "VIP : 443 → C-IP : sport\n인입 노드 N1 미경유 (DSR)"),
            ("⑩ Storage leaf\nVRF PUBLIC\nVXLAN 감쌈 → Border", "device", "바깥 : leaf VTEP → Border VTEP\n안 : VIP → C-IP"),
            ("⑪ Border · FA Core\nVXLAN 풂\n방화벽 세션 일치", "device", "VIP → C-IP"),
            ("⑫ 외부 ETL client\n응답 수신\nsrc = VIP", "plain", "VIP : 443 → C-IP : sport")]
    _flow(p, 14, req, resp, "요청 : C-IP → VIP (PUBLIC · bond0)", "응답 : VIP → C-IP (DSR, 인입 노드 미경유)",
          ["S3 443", "VRF PUBLIC", "VXLAN", "VXLAN", "802.3ad", "Geneve", "netkit"], ["", "", ""])
    return p


def fig0_4():
    p = Page("그림 0-4 내부 client 패킷 흐름", 1400, 860)
    cm = p.box(390, 14, 640, 58, "ClusterMesh (제어) : KVStoreMesh\nglobal-svc 백엔드 · identity 를 Compute 클러스터에 동기화", "device", size=13, cube=True)
    req = [("① ETL client Pod\nPod-IP-c (Compute K8s)\nglobal-svc 로 요청", "key", "Pod-IP-c → global-svc : 443\n(ClusterIP · DNS)"),
           ("② Compute 노드 소켓 LB\nGlobal Service 백엔드\n= AIStor Pod (원격)", "node", "connect() 시 목적지 변경\nPod-IP-c → P-IP : 포트"),
           ("③ Compute 노드 라우팅\neBPF host routing\nStorage PodCIDR → bond1", "node", "Pod-IP-c → P-IP\n(NAT 없음) · bond1 (802.3ad)"),
           ("④ Compute leaf (VTEP)\nVRF PRIVATE\nPodCIDR Type-5 → VXLAN", "device", "바깥 : leaf VTEP(01) → leaf VTEP(03)\nUDP 4789 · L3VNI PRIVATE\n안 : Pod-IP-c → P-IP"),
           ("⑤ Spine · Super Spine\nDCNY01 → DCNY03\n구간 간 링크 · ECMP", "device", "바깥 : leaf VTEP(01) → leaf VTEP(03)\n안 : Pod-IP-c → P-IP"),
           ("⑥ Storage leaf (VTEP)\nVXLAN 풂 · VRF PRIVATE\nPodCIDR → 소유 노드 N2", "device", "Pod-IP-c → P-IP\n→ N2 bond1 (802.3ad)"),
           ("⑦ Storage 노드 N2 (bond1)\neBPF host routing\n정책 확인 → netkit", "node", "Pod-IP-c → P-IP\nidentity : ClusterMesh 동기화"),
           ("⑧ AIStor Pod\nS3 PUT 처리\nclient IP = Pod-IP-c", "good", "응답 생성\nP-IP → Pod-IP-c")]
    resp = [("⑨ N2 (bond1)\n역방향 그대로\nNAT 없음", "good", "P-IP → Pod-IP-c\nbond1 PRIVATE"),
            ("⑩ Storage leaf · Spine\nVRF PRIVATE\nVXLAN → Compute leaf", "device", "바깥 : leaf VTEP(03) → leaf VTEP(01)\n안 : P-IP → Pod-IP-c"),
            ("⑪ Compute leaf\nVXLAN 풂\n→ Compute 노드 bond1", "device", "P-IP → Pod-IP-c"),
            ("⑫ ETL client Pod\n소켓은 global-svc 로\n연결된 것으로 인식", "key", "P-IP → Pod-IP-c\n(소켓 LB 가 주소 복원)")]
    S, P = _flow(p, 112, req, resp, "요청 : Pod-IP-c → global-svc → P-IP (PRIVATE · bond1)", "응답 : P-IP → Pod-IP-c (같은 경로 역방향)",
                 ["", "", "802.3ad", "VXLAN", "VXLAN", "802.3ad", "netkit"], ["", "", ""])
    p.edge(cm, S[1], "백엔드 동기화", "idle", anc=(0.234, 1, 0.5, 0))
    return p


# ================================================================ 3 : ECMP · 수렴
def fig3_1():
    p = Page("그림 3-1 resilient hashing", 1400, 760)
    p.title("그림 3-1. ECMP 멤버 제거 시 재해시 : 일반 해시 → resilient hashing",
            "노드 3 이 빠질 때 일반 해시는 살아 있는 노드로 가던 흐름까지 섞음. resilient 는 빠진 노드 몫만 옮김 (NW 적용 예정)")
    before = [1, 2, 3, 4, 1, 2, 3, 4]
    plain_after = [[1, 2, 4][b % 3] for b in range(8)]
    res_after = [1, 2, 1, 4, 1, 2, 2, 4]
    for half, (x0, title, after, verdict) in enumerate([
            (30, "I Lake : 일반 해시 (확인 후 결정)", plain_after, "8개 중 6개 이동 → 살아 있는 노드의 연결까지 다른 노드로\nMaglev 가 없으면 이동한 연결은 다른 백엔드로 가서 끊김"),
            (710, "Y1 : resilient hashing (NW 적용 예정)", res_after, "노드 3 몫 2개만 이동, 나머지 6개 그대로\n+ Maglev 로 이동한 연결도 같은 백엔드 → 유지")]):
        p.zone(x0, 104, 660, 630, title)
        p.box(x0 + 20, 140, 620, 30, "해시 버킷 8개 → 담당 노드 (멤버 4개 : 노드 1 ~ 4)", "plain", bold=True, size=12)
        for j, n in enumerate(before):
            p.box(x0 + 20 + j * 78, 182, 70, 70, f"b{j}\n노드 {n}", "node", size=12, cube=True)
        p.box(x0 + 20, 270, 620, 30, "노드 3 제거 후 (멤버 3개)", "plain", bold=True, size=12)
        moved = 0
        for j, n in enumerate(after):
            ch = n != before[j]
            moved += ch
            p.box(x0 + 20 + j * 78, 312, 70, 70, f"b{j}\n노드 {n}", "hot" if ch else "good", size=12, cube=True)
        p.box(x0 + 20, 404, 620, 90, verdict, "hot" if half == 0 else "good", size=13, bold=True)
        p.box(x0 + 20, 512, 620, 200,
              ("동작\n· 버킷 = hash(5-tuple) mod 멤버 수\n· 멤버 수가 바뀌면 mod 결과가 대부분 바뀜\n· 노드 · leaf 작업 때마다 대량 재배치" if half == 0 else
               "동작\n· 버킷 표를 고정해 두고 빠진 멤버 칸만 다시 채움\n· 설정 : hardware profile ecmp resilient (모델 · 버전 확인)\n· export-gateway-ip 와 함께 쓰면 노드 단위 ECMP 에도 적용"),
              "note" if half == 0 else "key", align="left", size=13, valign="top")
    return p


def fig3_2():
    p = Page("그림 3-2 계층별 해시 seed", 1400, 760)
    p.title("그림 3-2. 다단 ECMP 해시 : 같은 seed → 계층별 seed",
            "상위와 하위가 같은 해시를 쓰면 하위 계층에서 한쪽만 사용 (polarization). 계층마다 seed 를 다르게")

    def half(x0, after):
        p.zone(x0, 104, 660, 630, "Y1 : 계층별 seed (I Lake 는 NW 확인)" if after else "같은 seed 일 때 (확인 대상)")
        ss = p.box(x0 + 210, 140, 240, 56, "Super Spine\nseed " + ("101" if after else "기본"), "device", size=12, cube=True)
        s1 = p.box(x0 + 60, 250, 220, 56, "Spine 1\nseed " + ("201" if after else "기본"), "device", size=12, cube=True)
        s2 = p.box(x0 + 380, 250, 220, 56, "Spine 2\nseed " + ("201" if after else "기본"), "device", size=12, cube=True)
        k = "good" if after else "hot"
        p.edge(ss, s1, "50%", k); p.edge(ss, s2, "50%", k)
        ls = [p.box(x0 + 20 + i * 160, 380, 140, 56, f"leaf {i+1}", "good" if after else ("hot" if i in (0, 2) else "mute"), size=12, cube=True) for i in range(4)]
        if after:
            for s, pr in ((s1, (0, 1)), (s2, (2, 3))):
                for i in pr:
                    p.edge(s, ls[i], "25%", "good")
        else:
            p.edge(s1, ls[0], "50%", "hot"); p.edge(s1, ls[1], "0%", "idle")
            p.edge(s2, ls[2], "50%", "hot"); p.edge(s2, ls[3], "0%", "idle")
        p.box(x0 + 20, 470, 620, 240,
              ("적용\n· ip load-sharing address source-destination port source-destination universal-id <계층별 값>\n"
               "· 같은 계층 안에서는 같은 값, 계층끼리만 다르게\n· 5-tuple 유지 (SNAT 된 client 도 포트로 분산)\n"
               "확인 : show ip load-sharing, 같은 계층 업링크 사용률 편차 ±10%") if after else
              ("증상\n· 상위에서 이미 걸러진 흐름 집합에 같은 함수를 다시 적용\n· 하위 계층에서 같은 쪽만 선택 → 링크 절반 유휴\n"
               "· 장비를 늘려도 대역이 늘지 않음\nI Lake : show ip load-sharing 결과로 판단 (NW 확인 대기)"),
              "key" if after else "note", align="left", size=13, valign="top")

    half(30, False)
    half(710, True)
    return p


def fig3_3():
    p = Page("그림 3-3 장애 감지 시간", 1400, 820)
    p.title("그림 3-3. 장애 감지 · 전환 시간 : I Lake → Y1",
            "막대 길이 = 트래픽이 사라지거나 쏠린 채 머무는 최대 시간. 짧을수록 좋음 (축은 대략적 비례)")
    rows = [
        ("스위치 간 링크\n(leaf · spine · super spine)", ("BFD 확인 대기 → 없으면 BGP hold 최대 180초", 470, "hot", "확인 후 결정"),
         ("BFD 300ms × 3 → 1초 이내", 40, "good", "개선 (NW)")),
        ("bond 멤버\n(링크는 살아 있는 장애)", ("LACP slow → 최대 90초 (30초 × 3)", 330, "hot", "개선"),
         ("LACP fast → 3초 (1초 × 3)", 70, "good", "")),
        ("노드 ↔ leaf BGP", ("hold 12초 · keepalive 4초", 150, "good", "동일 유지"),
         ("hold 12초 (I Lake 값 유지)", 150, "good", "")),
        ("노드 실제 장애\n(graceful restart 유지 시간)", ("GR 15초", 180, "good", "동일 유지"),
         ("GR 15초 (I Lake 값 유지)", 180, "good", "")),
        ("AIStor Pod 장애\n(백엔드 제외)", ("readiness 기본값 (확인 대기)", 260, "plain", "확인 후 결정"),
         ("readiness 5초 × 2 → 약 10초", 120, "good", "")),
    ]
    p.box(30, 104, 240, 36, "장애 종류", "device", bold=True, size=13)
    p.box(280, 104, 860, 36, "감지 · 전환까지 (I Lake 위 · Y1 아래)", "device", bold=True, size=13)
    p.box(1150, 104, 220, 36, "I Lake 대비", "device", bold=True, size=13)
    y = 152
    for name, il, y1 in rows:
        p.box(30, y, 240, 112, name, "plain", bold=True, size=12)
        for j, (txt, w, k, v) in enumerate((il, y1)):
            yy = y + 6 + j * 54
            p.box(280, yy, max(w, 40), 44, "", k)
            p.box(280 + max(w, 40) + 10, yy, 860 - max(w, 40) - 10, 44, txt, "label", size=12, align="left")
        p.box(1150, y, 220, 112, il[3], "hot" if il[3] == "개선" else ("good" if il[3] == "동일 유지" else "plain"), bold=True, size=13)
        y += 124
    return p


# ================================================================ 4 : L4 LB
def fig4_1():
    p = Page("그림 4-1 L4 경로 전후", 1400, 790)
    p.title("그림 4-1. AIStor VIP 처리 경로 : I Lake → Y1",
            "I Lake = random · SNAT · eTP Local(일부). Y1 = Maglev · DSR(Geneve) · eTP Cluster. XDP best-effort 는 동일 유지")

    def half(x0, after):
        p.zone(x0, 104, 660, 660, "Y1 : Maglev + DSR(Geneve) + eTP Cluster" if after else "I Lake : random + SNAT (+ eTP Local Service 4개)")
        cl = p.box(x0 + 470, 150, 170, 70, "client\n(ETL)", "plain", size=12, cube=True)
        lf = p.box(x0 + 220, 150, 200, 70, "Storage leaf\nVIP ECMP", "device", size=12, cube=True)
        ing = p.box(x0 + 220, 290, 200, 90, "인입 노드\n" + ("XDP · Maglev\n→ Geneve" if after else "XDP best-effort\nrandom · SNAT"),
                    "good" if after else "hot", size=12, cube=True)
        be_l = p.box(x0 + 20, 290, 150, 90, "로컬 Pod\n(같은 노드)", "node", size=12, cube=True)
        be_r = p.box(x0 + 470, 290, 170, 90, "다른 랙 Pod\n(전체 중 1)", "good" if after else "mute", size=12, cube=True)
        p.edge(cl, lf, "요청", "norm")
        p.edge(lf, ing, "", "norm")
        if after:
            p.edge(ing, be_r, "Geneve", "good")
            p.edge(be_r, cl, "응답 직접 (DSR)", "back")
            p.edge(ing, be_l, "로컬일 때", "norm")
        else:
            p.edge(ing, be_l, "Local", "hot", anc=(0, 0.3, 1, 0.3))
            p.edge(be_l, ing, "응답", "hot", anc=(1, 0.8, 0, 0.8))
            p.edge(ing, be_r, "Cluster 일 때", "idle")
            p.edge(ing, cl, "응답 경유", "hot", anc=(1, 0.1, 0.3, 1))
        rows = [("백엔드 선택", "노드마다 random → 재해시 시 끊김", "Maglev → 어느 노드든 같은 Pod"),
                ("응답 경로", "인입 노드 경유 (SNAT)", "처리 Pod → client 직접 (DSR)"),
                ("eTP", "Local 4개 → 인입 랙 Pod 에 묶임", "Cluster → 전체 Pod"),
                ("client IP", "SNAT 로 소실", "보존"),
                ("XDP", "best-effort", "best-effort (유지, bond PoC 후 native)")]
        y = 420
        for name, a, b in rows:
            p.box(x0 + 20, y, 140, 58, name, "device", bold=True, size=12)
            txt = b if after else a
            k = "good" if after else ("plain" if name == "XDP" else "hot")
            if after and name == "XDP":
                k = "plain"
            p.box(x0 + 170, y, 470, 58, txt, k, size=12)
            y += 66

    half(30, False)
    half(710, True)
    return p


def fig4_2():
    p = Page("그림 4-2 Maglev 효과", 1400, 760)
    p.title("그림 4-2. 인입 노드가 바뀔 때 : random → Maglev",
            "노드 B 장애 · 작업으로 패브릭이 흐름을 노드 C 로 옮김. 새 노드가 같은 백엔드를 고르는지가 연결 유지를 결정")

    def half(x0, after):
        p.zone(x0, 104, 660, 630, "Y1 : Maglev (AIStor VIP)" if after else "I Lake : random (Maglev 미사용)")
        cl = p.box(x0 + 240, 140, 180, 60, "client 연결 F", "plain", size=12, cube=True)
        b = p.box(x0 + 60, 250, 180, 70, "노드 B\n(장애 · 작업)", "mute", size=12, cube=True)
        c = p.box(x0 + 420, 250, 180, 70, "노드 C\n(새 인입)", "device", size=12, cube=True)
        p.edge(cl, b, "전", "idle")
        p.edge(cl, c, "후 (재해시)", "norm")
        px = p.box(x0 + 60, 400, 180, 70, "Pod X\n(F 를 처리 중)", "good", size=12, cube=True)
        py = p.box(x0 + 420, 400, 180, 70, "Pod Y", "hot" if not after else "mute", size=12, cube=True)
        p.edge(b, px, "", "idle")
        if after:
            p.edge(c, px, "같은 표 → Pod X", "good")
        else:
            p.edge(c, py, "새로 고름 → Pod Y", "hot")
        p.box(x0 + 20, 500, 620, 210,
              ("결과\n· 노드 C 도 같은 Maglev 표 (같은 시드 · 백엔드 목록) → 같은 Pod X\n· conntrack 이 없어도 연결 유지\n"
               "· 백엔드 1개 증감 시에만 일부 이동 (제거 시 그 Pod 몫 + 약 1%)\n설정 : bpf-lb-algorithm-annotation=true + svc annotation maglev") if after else
              ("결과\n· 노드 C 에는 F 의 conntrack 이 없음 → 새 연결로 보고 random 선택\n· Pod Y 는 F 를 모름 → RST → S3 요청 실패 · 재시도\n"
               "· 노드 작업 · leaf 장애 · ECMP 재해시 때마다 반복\nI Lake 확인값 : bpf-lb-algorithm random, annotation 기능 off, maglev 0"),
              "key" if after else "hot", align="left", size=13, valign="top")

    half(30, False)
    half(710, True)
    return p


def fig4_3():
    p = Page("그림 4-3 eTP Local vs Cluster", 1400, 760)
    p.title("그림 4-3. externalTrafficPolicy : Local → Cluster",
            "같은 leaf 에 붙은 client 는 BGP 상 로컬 랙 노드로만 들어옴 (정상). Local 이면 처리도 그 랙에 묶이고, Cluster + Maglev 면 전체로 나뉨")

    def half(x0, after):
        p.zone(x0, 104, 660, 630, "Y1 : Cluster + Maglev" if after else "I Lake : Local (LoadBalancer 4개)")
        cl = p.box(x0 + 220, 140, 220, 60, "같은 leaf client", "plain", size=12, cube=True)
        r1 = p.box(x0 + 220, 250, 220, 80, "랙 1 인입 노드\n(로컬 랙만 수신)", "device", size=12, cube=True)
        p.edge(cl, r1, "AS-path 짧은 로컬", "norm")
        pods = []
        for i in range(3):
            x = x0 + 30 + i * 210
            busy = (i == 0) if not after else True
            pods.append(p.box(x, 400, 180, 80, f"랙 {i+1} AIStor Pod", ("hot" if busy else "mute") if not after else "good", size=12, cube=True))
        if after:
            for i, pd in enumerate(pods):
                p.edge(r1, pd, "1/R", "good")
        else:
            p.edge(r1, pods[0], "100%", "hot")
            p.edge(r1, pods[1], "0%", "idle"); p.edge(r1, pods[2], "0%", "idle")
        p.box(x0 + 20, 510, 620, 200,
              ("결과\n· 인입이 로컬이어도 처리는 전체 Pod 로 분산\n· DSR 로 client IP 보존 (Local 의 장점 유지)\n"
               "· Maglev 로 인입 노드가 바뀌어도 같은 Pod\n확인 : AIStor VIP 의 ETP = Cluster") if after else
              ("결과\n· 로컬 Pod 만 처리 → 인입 쏠림이 처리 쏠림으로 그대로\n· VIP 를 광고하는 노드도 로컬 Pod 있는 노드로 줄어듦\n"
               "· 현행 불균형의 직접 원인 후보\n확인 필요 : Local 4개가 AIStor VIP 인지"),
              "key" if after else "hot", align="left", size=13, valign="top")

    half(30, False)
    half(710, True)
    return p


def fig4_4():
    p = Page("그림 4-4 내부 경로 소켓 LB", 1400, 800)
    p.title("그림 4-4. 내부 client (Compute · GPU Pod) → AIStor : 소켓 LB off → on",
            "소켓 LB 는 connect() 한 번에 백엔드 Pod IP 를 정함. off 면 패킷마다 NAT · conntrack. Global Service 로 다른 클러스터 AIStor 까지 직결")

    def half(x0, after):
        p.zone(x0, 104, 660, 670, "Y1 : 소켓 LB on + Global Service" if after else "I Lake : 소켓 LB off (bpf-lb-sock=false)")
        pod = p.box(x0 + 30, 150, 200, 76, "ETL · 학습 Pod\n(Compute · GPU)", "plain", size=12, cube=True)
        hook = p.box(x0 + 300, 150, 330, 76, ("connect() 훅 (cgroup BPF)\n목적지 = AIStor Pod IP 로 1회 변경" if after else
                                               "패킷마다 tc BPF\nClusterIP → Pod DNAT · 응답 역변환"),
                     "good" if after else "hot", size=12, cube=True)
        p.edge(pod, hook, "", "good" if after else "hot")
        fab = p.box(x0 + 300, 280, 330, 70, "PRIVATE VRF (bond1)\n구간 간 링크 → DCNY03", "device", size=12, cube=True)
        p.edge(hook, fab, "Pod IP 직결" if after else "NAT 된 패킷", "good" if after else "norm")
        st = p.box(x0 + 300, 400, 330, 76, "AIStor Pod (전체 중 1)\nStorage 클러스터", "good" if after else "node", size=12, cube=True)
        p.edge(fab, st, "", "good" if after else "norm")
        p.box(x0 + 20, 510, 620, 240,
              ("효과\n· 패킷 단위 NAT · conntrack 없음 → CPU 절감, 대용량 I/O 유리\n· 분산 단위 = 연결 (connect 시점). 연결 수가 많을수록 고르게\n"
               "· Global Service (service.cilium.io/global=true) 로 Compute · GPU → Storage 백엔드 직접\n· affinity 미설정 (none) 유지\n"
               "주의 : 의도적으로 끈 이유 (호환 · 정책) 가 있는지 먼저 확인") if after else
              ("현상\n· I Lake Storage 클러스터 bpf-lb-sock = false (명시)\n· 패킷마다 서비스 변환 → 노드 CPU · conntrack 사용 증가\n"
               "· 분산은 되지만 효율 낮음\n확인 : Compute · GPU 클러스터 값, 끈 이유, Global Service affinity 값 (1개 존재)"),
              "key" if after else "note", align="left", size=13, valign="top")

    half(30, False)
    half(710, True)
    return p


# ================================================================ 5 : VRF · bond
def fig5_1():
    p = Page("그림 5-1 VRF · bond 매핑", 1400, 800)
    p.title("그림 5-1. bond0 = PUBLIC · bond1 = PRIVATE : 광고 · 응답 경로",
            "BGP 인스턴스 2개가 bond 별로 다른 것을 광고. 내부 client 는 PRIVATE VIP, 외부 client 는 PUBLIC VIP → 응답 경로 대칭")
    ex = p.box(30, 130, 200, 70, "외부 client\n(FA Core 경유)", "plain", size=12, cube=True)
    inn = p.box(30, 470, 200, 70, "내부 서버\n(사내 대역)", "plain", size=12, cube=True)
    pub = p.box(330, 130, 300, 70, "VRF PUBLIC\nleaf 쌍 (bond0 쪽)", "device", size=12, cube=True)
    prv = p.box(330, 470, 300, 70, "VRF PRIVATE\nleaf 쌍 (bond1 쪽)", "device", size=12, cube=True)
    b0 = p.box(760, 130, 220, 70, "bond0\n802.3ad · layer3+4", "good", size=12, cube=True)
    b1 = p.box(760, 470, 220, 70, "bond1\n802.3ad · layer3+4", "good", size=12, cube=True)
    node = p.box(1060, 230, 310, 210, "AIStor 노드 (Cilium)\nBGP 인스턴스 A → bond0\n  PUBLIC VIP /32\nBGP 인스턴스 B → bond1\n  PodCIDR · PRIVATE VIP\n(I Lake : ASN-A · ASN-B 2개)", "node", size=12, cube=True)
    p.edge(ex, pub, "PUBLIC VIP", "good"); p.edge(pub, b0, "", "good", both=True)
    p.edge(inn, prv, "PRIVATE VIP", "good"); p.edge(prv, b1, "", "good", both=True)
    p.edge(b0, node, "", "norm", both=True); p.edge(b1, node, "", "norm", both=True)
    p.edge(inn, pub, "PUBLIC VIP 접속", "idle", anc=(0.5, 0, 0.2, 1))
    p.box(430, 250, 300, 150, "비대칭 (피할 것)\n내부 서버 → PUBLIC VIP\n요청 : bond0 로 들어옴\n응답 : 목적지가 사내 대역 → bond1\n→ 방화벽 · uRPF drop", "hot", size=12)
    p.box(30, 580, 1340, 190,
          "원칙 · 판단\n"
          "· 노드는 VRF 가 없어 목적지 주소로 출구 bond 를 고름 → 내부 대역은 bond1, 기본 경로는 bond0\n"
          "· 내부 client 는 PRIVATE VIP, 외부 client 는 PUBLIC VIP 만 사용 → DNS 를 내부 · 외부로 나눠 강제\n"
          "· LB IPAM 풀 PRIVATE · PUBLIC 분리 : I Lake 2개 이상 확인 → 동일 유지\n"
          "· BGP 인스턴스 2개 (ASN-A : 2개 광고, ASN-B : 10개 광고) → 어느 쪽이 bond0 인지 확인 후 광고 대상 대조\n"
          "· PodCIDR 가 PUBLIC 으로 새지 않게 leaf 수신 필터 (NW) · Cilium 광고 라벨 분리",
          "key", align="left", size=13, valign="top")
    return p


# ================================================================ 6 : 노드 · bond
def fig6_1():
    p = Page("그림 6-1 노드 데이터패스 전후", 1400, 860)
    p.title("그림 6-1. 노드 : I Lake → Y1 (bond 802.3ad 유지)",
            "netkit · bond 해시는 이미 좋음 → 유지. LACP · MTU · TCP · tuned · IRQ 를 100G 기준으로 개선")

    def half(x0, after):
        p.zone(x0, 104, 660, 730, "Y1" if after else "I Lake (Storage K8s 실측)")
        pod = p.box(x0 + 220, 140, 220, 56, "Pod (S3 · 학습 I/O)", "node", size=12, cube=True)
        nk = p.box(x0 + 170, 230, 320, 64, "netkit (Pod 장치)\n" + ("유지" if after else "적용됨 ✓"), "good", size=12, cube=True)
        hr = p.box(x0 + 170, 324, 320, 64, "host routing\n" + ("BPF 확인 · 유지" if after else "값 확인 필요 (?)"), "good" if after else "plain", size=12, cube=True)
        b0 = p.box(x0 + 40, 424, 270, 86, "bond0 (PUBLIC)\n802.3ad · layer3+4 " + ("유지" if after else "✓") + "\n" + ("LACP fast · MTU 9000" if after else "LACP slow · MTU 1500"), "good" if after else "hot", size=12, cube=True)
        b1 = p.box(x0 + 350, 424, 270, 86, "bond1 (PRIVATE)\n802.3ad · layer3+4 " + ("유지" if after else "✓") + "\n" + ("LACP fast · MTU 9000" if after else "LACP slow · MTU 1500"), "good" if after else "hot", size=12, cube=True)
        lf = p.box(x0 + 170, 548, 320, 56, "leaf 쌍 (EVPN · 이중화 방식 확인)", "device", size=12, cube=True)
        p.edge(pod, nk, "", "good"); p.edge(nk, hr, "", "good")
        p.edge(hr, b0, "외부 · 응답", "good" if after else "norm"); p.edge(hr, b1, "내부 · AIStor", "good" if after else "norm")
        p.edge(b0, lf, "", "norm", both=True); p.edge(b1, lf, "", "norm", both=True)
        txt = ("Y1 설정\n· sysctl : bbr + fq, rmem · wmem 128M, backlog 250000\n· tuned network-throughput, NIC IRQ NUMA 로컬 고정\n"
               "· 큐 수 = NIC NUMA 로컬 코어 수 (ice)\n· Cilium devices = bond0, bond1 명시 · BBR(bandwidth-manager)") if after else \
              ("I Lake 실측\n· cubic · fq_codel, rmem · wmem 25M, backlog 16384\n· tuned 없음, irqbalance active\n"
               "· 큐 96 · NIC NUMA n0 · n1 (멤버가 서로 다른 NUMA)\n· devices auto · bandwidth-manager · BBR off")
        p.box(x0 + 20, 626, 620, 190, txt, "key" if after else "note", align="left", size=13, valign="top")

    half(30, False)
    half(710, True)
    return p


def fig6_2():
    p = Page("그림 6-2 NUMA · IRQ", 1400, 760)
    p.title("그림 6-2. NIC 큐 · IRQ 배치 : 전체 코어 96 → NUMA 로컬",
            "NIC 이 붙은 NUMA 의 코어가 그 NIC 의 인터럽트 · 패킷 처리를 맡아야 원격 메모리 접근이 없음")

    def half(x0, after):
        p.zone(x0, 104, 660, 630, "Y1 : NUMA 로컬 고정" if after else "I Lake : 큐 96 · irqbalance")
        n0 = p.zone(x0 + 20, 140, 300, 300, "NUMA 0 (CPU 0 ~ 47)")
        n1 = p.zone(x0 + 340, 140, 300, 300, "NUMA 1 (CPU 48 ~ 95)")
        a = p.box(x0 + 50, 180, 240, 70, "NIC A (bond 멤버 1)\nice · NUMA 0", "device", size=12, cube=True)
        b = p.box(x0 + 370, 180, 240, 70, "NIC B (bond 멤버 2)\nice · NUMA 1", "device", size=12, cube=True)
        c0 = p.box(x0 + 50, 330, 240, 80, "코어 0 ~ 47", "good" if after else "node", size=12, cube=True)
        c1 = p.box(x0 + 370, 330, 240, 80, "코어 48 ~ 95", "good" if after else "node", size=12, cube=True)
        if after:
            p.edge(a, c0, "큐 · IRQ 로컬", "good"); p.edge(b, c1, "큐 · IRQ 로컬", "good")
        else:
            p.edge(a, c0, "", "norm"); p.edge(b, c1, "", "norm")
            p.edge(a, c1, "원격", "hot"); p.edge(b, c0, "원격", "hot")
        p.box(x0 + 20, 470, 620, 240,
              ("설정\n· ethtool -L <nic> combined <로컬 코어 수>\n· IRQ → /sys/class/net/<nic>/device/local_cpulist 로 고정\n"
               "· irqbalance 에서 NIC IRQ 제외 (또는 중지) · tuned 와 한 방식만\n· 효과 : 캐시 지역성, 100G 에서 rx drop · 지연 감소") if after else
              ("현상\n· 큐 96 = 전체 코어 → 절반은 원격 NUMA 에서 처리\n· irqbalance 가 IRQ 를 수시로 옮김\n"
               "· bond 멤버 2개가 서로 다른 NUMA 에 붙음 (n0 · n1)\n· 고부하에서 rx drop · 지연 편차 원인"),
              "key" if after else "note", align="left", size=13, valign="top")

    half(30, False)
    half(710, True)
    return p


# ================================================================ 7 : 클러스터
def fig7_1():
    p = Page("그림 7-1 ClusterMesh", 1400, 820)
    p.title("그림 7-1. ClusterMesh 3 클러스터 : apiserver 1개 직접 연결 → KVStoreMesh + HA",
            "Compute · GPU · Storage 가 서로의 서비스 · 엔드포인트를 공유. 원격 상태를 클러스터마다 캐시하면 연결 수 · 장애 영향이 줄어듦")

    def half(x0, after):
        p.zone(x0, 104, 660, 690, "Y1 : 클러스터마다 apiserver + KVStoreMesh (replica 2)" if after else "I Lake : 원격 에이전트가 apiserver 에 직접 (replica 1 · KVStoreMesh 없음)")
        names = ["Compute K8s\nDCNY01", "GPU K8s\nDCNY02", "Storage K8s\nDCNY03"]
        cls, apis = [], []
        for i, nm in enumerate(names):
            x = x0 + 30 + i * 210
            cls.append(p.box(x, 150, 180, 70, nm + "\n에이전트 전부", "node", size=12, cube=True))
            apis.append(p.box(x, 300, 180, 80, "clustermesh-apiserver\n" + ("+ KVStoreMesh · 2개" if after else "replica 1"),
                              "good" if after else ("hot" if i == 2 else "plain"), size=12, cube=True))
        if after:
            for c, a in zip(cls, apis):
                p.edge(c, a, "로컬 조회", "good")
            p.edge(apis[0], apis[1], "캐시 동기화", "back", both=True)
            p.edge(apis[1], apis[2], "캐시 동기화", "back", both=True)
        else:
            p.edge(cls[0], apis[2], "원격 직접", "hot")
            p.edge(cls[1], apis[2], "원격 직접", "hot")
            p.edge(cls[2], apis[2], "", "norm")
        p.box(x0 + 20, 420, 620, 350,
              ("Y1\n· KVStoreMesh : 원격 상태를 클러스터 안 apiserver 에 캐시 → 에이전트는 로컬만 조회\n· apiserver replica 2 이상 + 랙 분산 → 하나 죽어도 동기화 유지\n"
               "· 연결이 끊겨도 마지막 상태로 데이터패스 계속 동작\n· cluster id · PodCIDR(multi-pool) 3 클러스터 비중복\n"
               "· Cilium patch 정렬 (GPU 1.20.2 기준), K8s 지원 범위 확인\n· Global Service affinity 미설정 유지") if after else
              ("I Lake 실측 (Storage)\n· remote 2/2 ready (Compute · GPU 로 추정, 확인 필요)\n· clustermesh-apiserver replica 1, KVStoreMesh 없음\n"
               "· 원격 클러스터의 모든 에이전트가 apiserver 1개에 직접 연결\n· apiserver 1개 장애 = 원격 서비스 변화 반영 중단\n"
               "· 기존 문서 : global-svc 간헐 끊김 원인 미확정 → 연관 확인"),
              "key" if after else "note", align="left", size=13, valign="top")

    half(30, False)
    half(710, True)
    return p


# ================================================================ 8 : 클라이언트
def fig8_1():
    p = Page("그림 8-1 연결 단위 분산", 1400, 720)
    p.title("그림 8-1. 연결 단위 분산의 한계 : 장기 연결 · Arrow Flight(gRPC)",
            "L4 LB 는 연결이 처음 맺어질 때만 백엔드를 고름 → 연결이 적고 오래 살면 고르게 나뉘지 않음")

    def half(x0, after):
        p.zone(x0, 104, 660, 590, "Y1 : 연결 수명 제한 + 다중 채널" if after else "장기 연결 1~2개 (keep-alive · gRPC)")
        c = p.box(x0 + 30, 160, 200, 80, "client\n(Airflow · Spark ·\nArrow Flight)", "plain", size=12, cube=True)
        bes = [p.box(x0 + 420, 140 + i * 100, 200, 76, f"백엔드 {i+1}", ("hot" if i == 0 else "mute") if not after else "good", size=12, cube=True) for i in range(3)]
        if after:
            for i, b in enumerate(bes):
                p.edge(c, b, f"채널 {i+1}", "good")
        else:
            p.edge(c, bes[0], "연결 1개에 요청 전부", "hot")
            p.edge(c, bes[1], "", "idle"); p.edge(c, bes[2], "", "idle")
        p.box(x0 + 20, 460, 620, 214,
              ("적용\n· gRPC(Arrow Flight) 서버 : max connection age (예 : 수 분) → 주기적 재연결로 재분산\n"
               "· client : 채널 · 연결 여러 개 (풀 크기 ≥ 백엔드 수 고려)\n· S3 SDK : 커넥션 풀 수명 · 최대 유휴 시간 제한\n"
               "· 대용량 업로드 : 멀티파트 병렬 → 연결 수 확보\n· I Lake 동일 유지 : 적재는 Airflow · Spark Job (K8s 내부, 소켓 LB 경로)") if after else
              ("현상\n· HTTP/2 · gRPC 는 연결 하나에 요청을 계속 실음 (멀티플렉싱)\n· 그 연결을 받은 백엔드만 바쁨\n"
               "· Maglev · 소켓 LB 도 연결 단위라 해결 못 함\n· I Lake : Arrow Flight 추가됨 → 신규 확인 대상"),
              "key" if after else "hot", align="left", size=13, valign="top")

    half(30, False)
    half(710, True)
    return p


# ================================================================ 9 : 운영 · 검증
def fig9_1():
    p = Page("그림 9-1 적용 로드맵", 1400, 720)
    p.title("그림 9-1. 적용 로드맵 : 확인 → 위험 낮은 것 → LB → 패브릭 협업 → 검증",
            "Y1 은 구축 시 한 번에 적용, 단계는 PoC 와 I Lake 역적용 순서. 단계마다 게이트 통과 후 다음 단계")
    steps = [
        ("P0 확인", "확인 대기 해소\nLocal Svc 4개\nNW 핵심 3개\nCompute 결과", "plain"),
        ("P1 노드", "LACP fast\nsysctl · tuned\nIRQ · NUMA\nCilium 맵 · BBR", "good"),
        ("P2 L4 LB", "Maglev annotation\neTP Cluster\n소켓 LB on\nKVStoreMesh · HA", "good"),
        ("P3 DSR", "MTU 9000 / 9216\nGeneve DSR\nuRPF · UDP 6081\nXDP bond PoC", "key"),
        ("P4 패브릭", "RD · max-paths\nexport-gateway-ip\nresilient · seed\nBFD · 구간 링크", "key"),
        ("P5 검증", "T1 ~ T14\n랙 · 노드 편차 ±10%\n장애 · drain\n구간 링크 사용률", "plain"),
    ]
    prev = None
    for i, (h, b, k) in enumerate(steps):
        x = 30 + i * 226
        hd = p.box(x, 120, 206, 50, h, "title", bold=True, size=15)
        p.box(x, 182, 206, 150, b, k, size=13)
        if prev:
            p.edge(prev, hd, "", "norm")
        prev = hd
    p.box(30, 356, 1340, 150,
          "게이트 (다음 단계 진입 조건)\n"
          "P0 → P1 : 확인 대기 목록 중 P1 대상 값 확정\n"
          "P1 → P2 : bond 멤버 장애 시 3초 내 전환, rx drop 증가 없음\n"
          "P2 → P3 : AIStor Pod 별 요청 수 편차 ±10%, 노드 작업 시 연결 유지 (Maglev)\n"
          "P3 → P4 : DSR 응답이 인입 노드 tx 에 거의 없음, MTU 분할 없음\n"
          "P4 → P5 : Border VIP 경로 수 = 기대값 (VTEP 수 또는 노드 수), 계층별 업링크 편차 ±10%",
          "plain", align="left", size=13, valign="top")
    p.box(30, 524, 1340, 160,
          "PoC 선행\n"
          "· bond 위 XDP (ice) native 부착 · XDP_TX 경로 (PUBLIC 에서 노드 간 Geneve 도달)\n"
          "· MTU 9000 전환 영향 (노드 · 패브릭 · 구간 간 링크 9216, Pod MTU 자동 조정)\n"
          "· DSR 응답과 VRF 응답 경로 (bond0 / bond1) 정합성\n"
          "· export-gateway-ip 적용 시 ECMP 폭 ≥ Storage 노드 수\n"
          "· 노드 drain 시 BGP 광고 철회 절차 (그림 9-2)",
          "key", align="left", size=13, valign="top")
    return p


def fig9_2():
    p = Page("그림 9-2 노드 작업 절차", 1400, 540)
    p.title("그림 9-2. 노드 작업 절차 : 광고 철회 → drain → 작업 → 복구",
            "바로 재부팅하면 BGP hold(12초) 또는 GR(15초) 동안 그 노드로 가는 트래픽이 사라짐 → 광고부터 먼저 거둠")
    steps = [("① cordon", "새 Pod 배치 중지"),
             ("② 광고 철회", "BGP 대상 라벨 제거\n→ 세션 정상 종료\n→ leaf 경로 즉시 삭제"),
             ("③ 경로 확인", "leaf 에서 그 노드\nnext-hop 사라짐"),
             ("④ 연결 drain", "기존 연결 종료 대기\n(모니터링으로 확인)"),
             ("⑤ drain · 작업", "Pod 이동 후\n커널 · 펌웨어 작업"),
             ("⑥ 복구", "라벨 복구 → 세션 · 광고\n→ uncordon")]
    prev = None
    for i, (h, b) in enumerate(steps):
        x = 30 + i * 226
        hd = p.box(x, 120, 206, 50, h, "title", bold=True, size=14)
        p.box(x, 182, 206, 120, b, "good" if i in (1, 2) else "plain", size=13)
        if prev:
            p.edge(prev, hd, "", "norm")
        prev = hd
    p.box(30, 326, 660, 180,
          "전제 · 주의\n"
          "· CiliumBGPClusterConfig nodeSelector 에 작업용 라벨 조건 (예 : bgp.example/enabled=true)\n"
          "· 라벨 제거 시 PodCIDR 광고도 빠짐 → 반드시 cordon 뒤, drain 과 묶어서\n"
          "· 세션을 정상 종료하면 GR 이 적용되지 않음 → 즉시 철회\n"
          "· Maglev 가 있으면 다른 노드가 같은 백엔드를 골라 연결 유지\n"
          "· 검증 : T13 (부하 중 절차 수행, 끊김 · 오류 0)",
          "key", align="left", size=13, valign="top")
    p.box(710, 326, 660, 180,
          "바로 재부팅할 때 (현행 위험)\n"
          "· 세션이 비정상 종료 → leaf 는 hold 12초 동안 경로 유지\n"
          "· GR 이 걸리면 15초 동안 유지 (I Lake 값)\n"
          "· 그 사이 그 노드로 ECMP 된 흐름은 블랙홀\n"
          "· random LB 면 재해시된 연결은 다른 백엔드 → 끊김\n"
          "· I Lake 판단 : 절차 유무 확인 후 결정",
          "note", align="left", size=13, valign="top")
    return p


FIGS = [("fig0-1", fig0_1), ("fig0-2", fig0_2), ("fig0-3", fig0_3), ("fig0-4", fig0_4),
        ("fig1-1", g2.fig1_1), ("fig1-2", g2.fig1_2), ("fig1-3", g2.fig1_3), ("fig1-4", g2.fig1_4),
        ("fig2-1", g2.fig2_1), ("fig2-2", g2.fig2_2), ("fig2-3", g2.fig2_3),
        ("fig3-1", fig3_1), ("fig3-2", fig3_2), ("fig3-3", fig3_3),
        ("fig4-1", fig4_1), ("fig4-2", fig4_2), ("fig4-3", fig4_3), ("fig4-4", fig4_4),
        ("fig5-1", fig5_1), ("fig6-1", fig6_1), ("fig6-2", fig6_2), ("fig7-1", fig7_1),
        ("fig8-1", fig8_1), ("fig9-1", fig9_1), ("fig9-2", fig9_2)]

if __name__ == "__main__":
    only = sys.argv[1:]
    base = OUT
    for d in ("drawio", "drawio-gliffy", "figures"):
        os.makedirs(os.path.join(base, d), exist_ok=True)
    pages = []
    for name, fn in FIGS:
        if only and name not in only:
            continue
        pg = fn()
        pages.append(pg)
        with open(os.path.join(base, "drawio", f"{name}.drawio"), "w", encoding="utf-8") as f:
            f.write(drawio([pg]))
        with open(os.path.join(base, "drawio-gliffy", f"{name}.drawio"), "w", encoding="utf-8") as f:
            f.write(drawio([pg], gliffy=True))
        with open(os.path.join(base, "figures", f"{name}.svg"), "w", encoding="utf-8") as f:
            f.write(svg(pg))
    if not only:
        with open(os.path.join(base, "y1-ai-dataplatform-all-figures.drawio"), "w", encoding="utf-8") as f:
            f.write(drawio(pages))
        with open(os.path.join(base, "y1-ai-dataplatform-all-figures-gliffy.drawio"), "w", encoding="utf-8") as f:
            f.write(drawio(pages, gliffy=True))
    print("ok", len(pages))
