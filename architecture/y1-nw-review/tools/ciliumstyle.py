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
        out.append(g.box(x + 12, yy, w - 24, 18 * n + 18, t, fill="#FFFFFF", stroke=AG_S, size=12, align="center", bold=True))
        yy += 18 * n + 30
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
    g = Diagram("C-1 Storage node internals", 1400, 760)
    node(g, 20, 20, 1360, 720, "Node · Storage K8s")
    p1, e1 = pod(g, 90, 80, 260, "AIStor", "10.30.1.15", "netkit nk1")
    p2, e2 = pod(g, 450, 80, 260, "other", "10.30.1.16", "netkit nk2")
    rt = rtable(g, 70, 300, 820, [
        "10.30.1.15/32  via nk1",
        "10.30.1.16/32  via nk2",
        "10.30.0.0/16 · 10.10.0.0/16  via bond1",
        "default  via bond0",
        "VIP 203.0.113.10/32  local"])
    g.line(bot(e1), at(rt, 0.17, 0), "phys")
    g.line(bot(e2), at(rt, 0.54, 0), "phys")
    lb = g.box(110, 460, 300, 44, "eBPF LB (XDP · tc)", fill=BPF_F, stroke=BPF_S, size=12, align="center", bold=True)
    hr = g.box(500, 460, 300, 44, "eBPF host routing", fill=BPF_F, stroke=BPF_S, size=12, align="center", bold=True)
    g.line(at(rt, 0.3, 1), top(lb), "phys")
    g.line(at(rt, 0.75, 1), top(hr), "phys")
    b0, b1 = bonds(g, 160, 560, gap=150)
    g.line(bot(lb), top(b0), "pub")
    g.line(bot(hr), top(b1), "priv")
    agent(g, 960, 60, 400, 420, ["BGP#1 bond0 : VIP/32", "BGP#2 bond1 : PodCIDR", "Service LB : eTP Local", "Socket LB", "ClusterMesh (KVStoreMesh)", "eBPF programs"])
    g.text(960, 500, 400, 120, "Basics\n· External → bond0 → local pod\n· Pod-to-pod · shards → bond1\n· No DSR · no Maglev", size=12, box=True)
    return g


# ================================================================ C-2 외부 요청 처리
def c2():
    g = Diagram("C-2 External request (eTP Local)", 1400, 700)
    node(g, 20, 20, 1360, 660, "Node · Storage K8s")
    p1, e1 = pod(g, 260, 80, 300, "AIStor", "10.30.1.15", "netkit nk1")
    lb = g.box(160, 320, 500, 54, "eBPF LB (XDP · tc)\nVIP → P-IP", fill=BPF_F, stroke=BPF_S, size=12, align="center", bold=True)
    b0, b1 = bonds(g, 160, 540, gap=100)
    g.line(top(b0), at(lb, 0.25, 1), "fpub", "①")
    g.line(at(lb, 0.5, 0), bot(e1), "fpub", "②")
    shard = g.box(700, 200, 200, 44, "other AIStor nodes", fill="#FFFFFF", stroke=PRIV, size=11, align="center")
    g.line(right(p1, 0.6), left(shard), "priv", "③")
    g.line(bot(shard), top(b1), "priv")
    g.line(at(lb, 0.1, 1), at(b0, 0.1, 0), "fpub", "④")
    agent(g, 960, 60, 400, 240, ["BGP#1 bond0 : VIP/32", "eTP Local"])
    g.text(960, 330, 400, 170, "Basics\n① C-IP → VIP on bond0\n② VIP → local pod (no hop)\n③ shards via bond1\n④ reply src VIP · client IP kept", size=12, box=True)
    return g


# ================================================================ C-3 내부 client → AIStor
def c3():
    g = Diagram("C-3 Internal client → AIStor", 1640, 900)
    cm = g.box(670, 20, 300, 50, "ClusterMesh", fill=AG_F, stroke=KEY, size=12, align="center", bold=True)
    node(g, 20, 100, 640, 720, "Node · Compute K8s")
    pc, ec = pod(g, 180, 160, 300, "ETL client", "10.10.4.21", "netkit")
    sl = g.box(160, 390, 340, 44, "eBPF socket LB", fill=BPF_F, stroke=BPF_S, size=12, align="center", bold=True)
    rt = rtable(g, 80, 470, 500, ["10.10.4.21/32  via netkit", "10.30.0.0/16  via bond1", "default  via bond0"])
    b1c = g.box(230, 680, 200, 34, "bond1 · PRIVATE", fill=B1_F, stroke=PRIV, size=11, align="center", bold=True)
    g.line(bot(ec), top(sl), "fpriv", "Ⓐ")
    g.line(bot(sl), top(rt), "fpriv", "Ⓑ")
    g.line(bot(rt), top(b1c), "fpriv", "Ⓒ")
    fab = g.box(690, 650, 260, 70, "Fabric\nVRF PRIVATE", fill="#FFFFFF", stroke=MUTE, size=12, align="center", bold=True)
    node(g, 980, 100, 640, 720, "Node · Storage K8s")
    b1s = g.box(1200, 680, 200, 34, "bond1 · PRIVATE", fill=B1_F, stroke=PRIV, size=11, align="center", bold=True)
    rs = rtable(g, 1040, 470, 520, ["10.30.1.15/32  via nk1", "10.10.0.0/16  via bond1", "default  via bond0"])
    hr = g.box(1130, 390, 340, 44, "eBPF host routing", fill=BPF_F, stroke=BPF_S, size=12, align="center", bold=True)
    ps, es = pod(g, 1150, 160, 300, "AIStor", "10.30.1.15", "netkit nk1")
    g.line(right(b1c), left(fab, 0.6), "fpriv", "Ⓓ")
    g.line(right(fab, 0.6), left(b1s), "fpriv", "Ⓔ")
    g.line(top(b1s), bot(rs), "fpriv")
    g.line(top(rs), bot(hr), "fpriv")
    g.line(top(hr), bot(es), "fpriv", "Ⓕ")
    g.line(at(cm, 0.2, 1), at(sl, 0.8, 0), "ctrl")
    g.line(at(cm, 0.8, 1), at(hr, 0.3, 0), "ctrl")
    g.text(20, 836, 1600, 50, "Basics : connect(global svc) → socket LB picks an AIStor pod → Pod IP over bond1 · no NAT · reply same path", size=12, bold=True)
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
