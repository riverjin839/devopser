#!/usr/bin/env python3
"""Cilium 문서 스타일 노드 다이어그램 (Pod · netkit · eBPF · Routing Table · cilium agent 열).

nwdiag.Diagram 재사용. IP 는 예시값. 로고 대신 글자 표기.
"""
import os

from nwdiag import Diagram, INK, MUTE, PUB, PRIV, KEY, at, top, bot, left, right

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
NODE_F, NODE_S = "#F6F6F6", "#BDBDBD"
POD_F, POD_S = "#F6D9E8", "#C99AB4"
TAG_F, TAG_S = "#E6E1F4", "#9C93C4"
BPF_F, BPF_S = "#D9EBC9", "#7FA65A"
RT_F, RT_S = "#DCEBEA", "#7FA8A5"
AG_F, AG_S = "#F3E9D2", "#C9B48A"
B0_F, B1_F = "#F6E3D8", "#E3ECE0"


def back(g):
    """방금 그린 상자를 맨 아래 층으로 (선이 가려지지 않게)."""
    g.zones.append(g.cells.pop())


def node(g, x, y, w, h, title):
    g.box(x, y, w, h, "", fill=NODE_F, stroke=NODE_S)
    g.cells[-1] = g.cells[-1].replace("arcSize=6", "arcSize=2")
    back(g)
    g.box(x + 14, y + 12, 22, 22, "", fill="#326CE5", stroke="#326CE5")
    g.text(x + 42, y + 8, w - 60, 30, title, size=16, bold=True)


def pod(g, x, y, w, name, ip, iface):
    p = g.box(x, y, w, 96, f"pod · {name}\n{ip}", fill=POD_F, stroke=POD_S, size=12, align="center", bold=True)
    e = g.box(x + w / 2 - 34, y + 84, 68, 22, "eth0", fill="#FFFFFF", stroke=POD_S, size=10, align="center")
    t = g.box(x + w / 2 - 50, y + 132, 100, 24, iface, fill=TAG_F, stroke=TAG_S, size=10, align="center")
    b = g.box(x + w / 2 - 44, y + 176, 88, 28, "eBPF", fill=BPF_F, stroke=BPF_S, size=11, align="center", bold=True)
    g.line(bot(e), top(t), "phys")
    g.line(bot(t), top(b), "phys")
    return p, b


def rtable(g, x, y, w, lines, title="Routing Table"):
    h = 34 + 18 * len(lines)
    b = g.box(x, y, w, h, "\n".join(lines), fill=RT_F, stroke=RT_S, size=11, align="left")
    g.cells[-1] = g.cells[-1].replace("verticalAlign=middle", "verticalAlign=bottom;spacingBottom=8")
    g.text(x + 4, y + 4, 200, 22, title, size=12, bold=True)
    return b


def agent(g, x, y, w, h, items):
    g.box(x, y, w, h, "", fill=AG_F, stroke=AG_S)
    g.cells[-1] = g.cells[-1].replace("arcSize=6", "arcSize=3")
    back(g)
    g.text(x + 10, y + 10, w - 20, 28, "cilium agent", size=14, bold=True, align="center")
    yy = y + 50
    out = []
    for t in items:
        n = t.count("\n") + 1
        out.append(g.box(x + 12, yy, w - 24, 16 * n + 16, t, fill="#FFFFFF", stroke=AG_S, size=10))
        yy += 16 * n + 26
    return out


def bonds(g, x, y, gap=40):
    b0 = g.box(x, y, 200, 34, "bond0 · PUBLIC", fill=B0_F, stroke=PUB, size=11, align="center", bold=True)
    b1 = g.box(x + 200 + gap, y, 200, 34, "bond1 · PRIVATE", fill=B1_F, stroke=PRIV, size=11, align="center", bold=True)
    for b in (b0, b1):
        for i, nm in enumerate(("p1 → Leaf-A", "p2 → Leaf-B")):
            m = g.box(b["x"] + i * 104, y + 52, 96, 22, nm, fill="#FFFFFF", stroke=MUTE, size=9, align="center")
            g.line(at(b, 0.25 + 0.5 * i, 1), top(m), "phys")
    return b0, b1


# ================================================================ C-1 Storage 노드 내부
def c1():
    g = Diagram("C-1 Storage 노드 내부", 1400, 760)
    node(g, 20, 20, 1360, 720, "Node · Storage K8s (AIStor 1 Pod / 노드)")
    p1, e1 = pod(g, 90, 80, 260, "AIStor", "10.30.1.15 (P-IP)", "netkit (nk1)")
    p2, e2 = pod(g, 450, 80, 260, "기타 (예 : exporter)", "10.30.1.16", "netkit (nk2)")
    rt = rtable(g, 70, 300, 820, [
        "10.30.1.15/32  via netkit nk1          (로컬 Pod)",
        "10.30.1.16/32  via netkit nk2",
        "10.30.0.0/16 · 10.10.0.0/16  via bond1 → Leaf   (다른 노드 PodCIDR · PRIVATE)",
        "default  via bond0 → Leaf   (외부 · PUBLIC)",
        "VIP 203.0.113.10/32 (예시)  : 로컬 처리 · eTP Local"])
    g.line(bot(e1), at(rt, 0.17, 0), "phys")
    g.line(bot(e2), at(rt, 0.54, 0), "phys")
    lb = g.box(110, 470, 300, 54, "eBPF LB (XDP · tc)\nVIP → 로컬 AIStor Pod", fill=BPF_F, stroke=BPF_S, size=11, align="center", bold=True)
    hr = g.box(500, 470, 300, 54, "eBPF host routing\nPod ↔ bond1 직접 전달", fill=BPF_F, stroke=BPF_S, size=11, align="center", bold=True)
    g.line(at(rt, 0.3, 1), top(lb), "phys")
    g.line(at(rt, 0.75, 1), top(hr), "phys")
    b0, b1 = bonds(g, 160, 570, gap=150)
    g.line(bot(lb), top(b0), "pub")
    g.line(bot(hr), top(b1), "priv")
    ag = agent(g, 960, 60, 400, 600, [
        "BGP 인스턴스 ① (bond0)\nPUBLIC VIP/32 광고 — 이 노드에 AIStor Pod 있을 때만",
        "BGP 인스턴스 ② (bond1)\nPodCIDR · PRIVATE VIP 광고",
        "Service LB\neTP Local · Maglev · DSR 없음 · LB 맵 상향",
        "소켓 LB\n노드 안 Pod 의 Service 연결을 connect() 때 변환",
        "ClusterMesh (KVStoreMesh)\nglobal-svc 백엔드 · identity 동기화",
        "hold 12 · keepalive 4 · GR 15\nBFD 없음 → 감지는 hold · LACP fast",
        "eBPF 프로그램 적재\nnetkit · LB · host routing 에 설치"])
    g.text(70, 670, 860, 50, "Pod 간 기본 통신 · AIStor erasure 조각 : bond1\n외부 S3 요청 · 응답 : bond0", size=11, bold=True)
    return g


# ================================================================ C-2 외부 요청 처리 (eTP Local)
def c2():
    g = Diagram("C-2 외부 요청 처리 (eTP Local)", 1400, 700)
    node(g, 20, 20, 1360, 660, "Node · Storage K8s — 외부 S3 요청 (C-IP → VIP)")
    p1, e1 = pod(g, 260, 80, 300, "AIStor", "10.30.1.15 (P-IP)", "netkit (nk1)")
    lb = g.box(160, 320, 500, 70, "eBPF LB (XDP · tc)\n② VIP:443 → P-IP (로컬 백엔드만 : eTP Local)\n⑤ 응답 src P-IP → VIP 복원", fill=BPF_F, stroke=BPF_S, size=11, align="center", bold=True)
    b0, b1 = bonds(g, 160, 540, gap=100)
    g.line(top(b0), at(lb, 0.25, 1), "fpub", "① C-IP → VIP")
    g.line(at(lb, 0.5, 0), bot(e1), "fpub", "③ C-IP → P-IP")
    shard = g.box(700, 200, 220, 60, "④ erasure 조각 송수신\n다른 노드 AIStor Pod", fill="#FFFFFF", stroke=PRIV, size=10, align="center")
    g.line(right(p1, 0.6), left(shard), "priv")
    g.line(bot(shard), top(b1), "priv", "bond1")
    g.line(at(lb, 0.1, 1), at(b0, 0.1, 0), "fpub", "⑤ VIP → C-IP")
    agent(g, 960, 60, 400, 270, [
        "BGP 인스턴스 ① (bond0)\nVIP/32 광고 — 로컬 AIStor Pod 준비 시",
        "Pod 종료 · drain 시\nVIP 광고 철회 → 신규 연결은 다른 노드",
        "노드 간 추가 경유 없음\nclient IP (C-IP) 보존"])
    g.text(960, 350, 400, 150, "판단 근거\n· 노드당 AIStor 1 Pod · 어느 Pod 든 처리 가능\n· 외부는 Spine 방향만 진입 → 랙 균등이면 인입 균등\n· eTP Cluster 는 요청 약 99% 가 bond1 로 다른 노드 경유\n  (AIStor 조각 트래픽과 경합 · PUBLIC → PRIVATE)\n· Maglev 는 eTP Cluster 에만 적용 → 불필요", size=11, box=True)
    return g


# ================================================================ C-3 내부 client → AIStor
def c3():
    g = Diagram("C-3 내부 client → AIStor (global-svc)", 1640, 900)
    cm = g.box(620, 20, 400, 64, "ClusterMesh (KVStoreMesh)\nglobal-svc 백엔드 = 원격 AIStor Pod · identity 동기화", fill=AG_F, stroke=KEY, size=11, align="center", bold=True)
    # 왼쪽 Compute 노드
    node(g, 20, 110, 640, 760, "Node · Compute K8s")
    pc, ec = pod(g, 180, 170, 300, "ETL client (Spark · Airflow)", "10.10.4.21 (Pod-IP-c)", "netkit")
    sl = g.box(110, 400, 440, 60, "eBPF 소켓 LB\nconnect(global-svc:443) → P-IP 10.30.1.15:포트 로 변경", fill=BPF_F, stroke=BPF_S, size=11, align="center", bold=True)
    rt = rtable(g, 80, 500, 500, ["10.10.4.21/32  via netkit", "10.30.0.0/16  via bond1 → Leaf  (Storage PodCIDR, BGP)", "default  via bond0"])
    b1c = g.box(230, 680, 200, 34, "bond1 · PRIVATE", fill=B1_F, stroke=PRIV, size=11, align="center", bold=True)
    g.line(bot(ec), top(sl), "fpriv", "Ⓐ")
    g.line(bot(sl), top(rt), "fpriv", "Ⓑ Pod-IP-c → P-IP")
    g.line(bot(rt), top(b1c), "fpriv", "Ⓒ NAT 없음")
    g.text(60, 760, 580, 90, "· 분산 : 소켓 LB 가 연결마다 AIStor Pod 100 개 중 선택\n· 외부 VIP · FA Core · bond0 사용 안 함", size=11, bold=True)
    # 가운데 패브릭
    fab = g.box(690, 640, 260, 110, "패브릭 (VRF PRIVATE)\nLeaf → Spine → Super Spine\n→ 구간 간 링크 → Spine → Leaf\nVXLAN · L3VNI PRIVATE", fill="#FFFFFF", stroke=MUTE, size=10, align="center")
    # 오른쪽 Storage 노드
    node(g, 980, 110, 640, 760, "Node · Storage K8s")
    b1s = g.box(1200, 680, 200, 34, "bond1 · PRIVATE", fill=B1_F, stroke=PRIV, size=11, align="center", bold=True)
    rs = rtable(g, 1040, 500, 520, ["10.30.1.15/32  via netkit nk1", "10.10.0.0/16  via bond1 → Leaf  (Compute PodCIDR)", "default  via bond0"])
    hr = g.box(1130, 400, 340, 60, "eBPF host routing · 정책 확인\n(원격 identity : ClusterMesh)", fill=BPF_F, stroke=BPF_S, size=11, align="center", bold=True)
    ps, es = pod(g, 1150, 170, 300, "AIStor", "10.30.1.15 (P-IP)", "netkit (nk1)")
    g.line(right(b1c), left(fab, 0.6), "fpriv", "Ⓓ")
    g.line(right(fab, 0.6), left(b1s), "fpriv", "Ⓔ")
    g.line(top(b1s), bot(rs), "fpriv")
    g.line(top(rs), bot(hr), "fpriv")
    g.line(top(hr), bot(es), "fpriv", "Ⓕ")
    g.text(1020, 760, 580, 90, "· 응답 P-IP → Pod-IP-c : 같은 경로 역방향 (bond1)\n· erasure 조각도 bond1 로 다른 Storage 노드와 송수신", size=11, bold=True)
    g.line(at(cm, 0.2, 1), at(sl, 0.8, 0), "ctrl", "백엔드 목록")
    g.line(at(cm, 0.8, 1), at(hr, 0.3, 0), "ctrl", "identity")
    return g


def write():
    os.makedirs(os.path.join(OUT, "drawio"), exist_ok=True)
    pages = [("C-1", c1()), ("C-2", c2()), ("C-3", c3())]
    head = '<mxfile host="app.diagrams.net" type="device">'
    for pid, d in pages:
        with open(os.path.join(OUT, "drawio", f"{pid}.drawio"), "w", encoding="utf-8") as f:
            f.write(head + d.xml(pid) + "</mxfile>")
    with open(os.path.join(OUT, "y1-cilium-node-diagrams.drawio"), "w", encoding="utf-8") as f:
        f.write(head + "".join(d.xml(pid) for pid, d in pages) + "</mxfile>")
    print("ok", len(pages))


if __name__ == "__main__":
    write()
