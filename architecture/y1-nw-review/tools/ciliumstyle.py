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


# ---------------------------------------------------------------- N-0 양식 부품
BLUE, ST_F, CP_F = "#036897", "#E3ECE0", "#ECEAE3"


def cell(g, x, y, w, h, t, kind="white", size=12, bold=True, align="center"):
    fill, stroke, fc = {"st": (ST_F, PRIV, INK), "cp": (CP_F, MUTE, INK), "blue": (BLUE, BLUE, "#FFFFFF"),
                        "white": ("#FFFFFF", INK, INK), "rule": ("#FFFFFF", PRIV, INK)}[kind]
    b = g.box(x, y, w, h, t, fill=fill, stroke=stroke, size=size, align=align, bold=bold)
    if fc != INK:
        g.cells[-1] = g.cells[-1].replace(f"fontColor={INK}", f"fontColor={fc}")
    return b


def pod2(g, x, y, w, name, ip, kind, iface):
    p = cell(g, x, y, w, 56, f"{name}\n{ip}", kind)
    n = cell(g, x + w / 2 - 60, y + 86, 120, 30, iface, "white", size=11, bold=False)
    g.line(bot(p), top(n), "phys")
    return p, n


def bond2(g, x, y):
    b0 = cell(g, x, y, 200, 36, "bond0 · PUBLIC", "blue")
    b1 = cell(g, x + 240, y, 200, 36, "bond1 · PRIVATE", "blue")
    for b in (b0, b1):
        for i, nm in enumerate(("p1 → Leaf-A", "p2 → Leaf-B")):
            m = cell(g, b["x"] + i * 104, y + 56, 96, 24, nm, "white", size=10, bold=False)
            g.line(at(b, 0.25 + 0.5 * i, 1), top(m), "phys")
    return b0, b1


def agent2(g, x, y, w, items):
    h = 50 + len(items) * 46
    g.zone(x, y, w, h, "cilium agent")
    for i, t in enumerate(items):
        cell(g, x + 14, y + 42 + i * 46, w - 28, 36, t, "white", size=12, bold=False)
    return h


def basics(g, x, y, w, h, lines):
    b = cell(g, x, y, w, h, "Basics\n" + "\n".join("· " + l for l in lines), "rule", size=12, bold=False, align="left")
    g.cells[-1] = g.cells[-1].replace("verticalAlign=middle", "verticalAlign=top")
    return b


# ================================================================ C-1 Storage 노드 내부
def c1():
    g = Diagram("C-1 Storage node internals", 1400, 720)
    g.zone(20, 20, 900, 680, "Node · Storage K8s", color=PRIV)
    p1, n1 = pod2(g, 90, 80, 260, "AIStor pod", "10.30.1.15", "st", "netkit nk1")
    p2, n2 = pod2(g, 470, 80, 260, "other pod", "10.30.1.16", "cp", "netkit nk2")
    rt = cell(g, 70, 250, 820, 120, "Routing table\n10.30.1.15/32 via nk1 · 10.30.1.16/32 via nk2\n10.30.0.0/16 · 10.10.0.0/16 via bond1\ndefault via bond0 · VIP 203.0.113.10/32 local", "white", size=12, bold=False, align="left")
    g.line(bot(n1), at(rt, 0.17, 0), "phys")
    g.line(bot(n2), at(rt, 0.55, 0), "phys")
    lb = cell(g, 110, 420, 300, 44, "eBPF LB (XDP · tc)", "white")
    hr = cell(g, 530, 420, 300, 44, "eBPF host routing", "white")
    g.line(at(rt, 0.3, 1), top(lb), "phys")
    g.line(at(rt, 0.83, 1), top(hr), "phys")
    b0, b1 = bond2(g, 210, 540)
    g.line(bot(lb), top(b0), "pub")
    g.line(bot(hr), top(b1), "priv")
    h = agent2(g, 960, 20, 420, ["BGP#1 bond0 : VIP/32", "BGP#2 bond1 : PodCIDR", "Service LB : eTP Local", "Socket LB", "ClusterMesh (KVStoreMesh)"])
    basics(g, 960, 40 + h, 420, 150, ["External → bond0 → local pod", "Pod-to-pod · shards → bond1", "No DSR · no Maglev"])
    return g


# ================================================================ C-2 외부 요청 처리
def c2():
    g = Diagram("C-2 External request (eTP Local)", 1400, 640)
    g.zone(20, 20, 900, 600, "Node · Storage K8s", color=PRIV)
    p1, n1 = pod2(g, 270, 70, 300, "AIStor pod", "10.30.1.15", "st", "netkit nk1")
    lb = cell(g, 170, 290, 500, 54, "eBPF LB (XDP · tc)\nVIP → P-IP (local only)", "white")
    b0, b1 = bond2(g, 190, 470)
    g.line(top(b0), at(lb, 0.25, 1), "fpub", "①")
    g.line(at(lb, 0.5, 0), bot(n1), "fpub", "②")
    sh = cell(g, 690, 150, 200, 44, "other AIStor nodes", "st", size=11, bold=False)
    g.line(right(p1, 0.5), left(sh), "priv", "③")
    g.line(bot(sh), top(b1), "priv")
    g.line(at(lb, 0.1, 1), at(b0, 0.1, 0), "fpub", "④")
    h = agent2(g, 960, 20, 420, ["BGP#1 bond0 : VIP/32", "eTP Local"])
    basics(g, 960, 40 + h, 420, 170, ["① C-IP → VIP on bond0", "② VIP → local pod (no extra hop)", "③ shards via bond1", "④ reply src VIP · client IP kept"])
    return g


# ================================================================ C-3 내부 client → AIStor
def c3():
    g = Diagram("C-3 Internal client → AIStor", 1640, 820)
    cm = cell(g, 670, 20, 300, 44, "ClusterMesh", "white")
    g.zone(20, 90, 640, 640, "Node · Compute K8s")
    pc, nc = pod2(g, 180, 140, 300, "ETL client pod", "10.10.4.21", "cp", "netkit")
    sl = cell(g, 160, 330, 340, 44, "eBPF socket LB", "white")
    rt = cell(g, 80, 420, 500, 84, "Routing table\n10.30.0.0/16 via bond1 · default via bond0", "white", size=12, bold=False, align="left")
    b1c = cell(g, 230, 600, 200, 36, "bond1 · PRIVATE", "blue")
    g.line(bot(nc), top(sl), "fpriv", "Ⓐ")
    g.line(bot(sl), top(rt), "fpriv", "Ⓑ")
    g.line(bot(rt), top(b1c), "fpriv", "Ⓒ")
    fab = cell(g, 690, 580, 260, 70, "Fabric\nVRF PRIVATE", "white")
    g.zone(980, 90, 640, 640, "Node · Storage K8s", color=PRIV)
    ps, ns = pod2(g, 1150, 140, 300, "AIStor pod", "10.30.1.15", "st", "netkit nk1")
    hr = cell(g, 1130, 330, 340, 44, "eBPF host routing", "white")
    rs = cell(g, 1040, 420, 520, 84, "Routing table\n10.10.0.0/16 via bond1 · default via bond0", "white", size=12, bold=False, align="left")
    b1s = cell(g, 1200, 600, 200, 36, "bond1 · PRIVATE", "blue")
    g.line(right(b1c), left(fab, 0.6), "fpriv", "Ⓓ")
    g.line(right(fab, 0.6), left(b1s), "fpriv", "Ⓔ")
    g.line(top(b1s), bot(rs), "fpriv")
    g.line(top(rs), bot(hr), "fpriv")
    g.line(top(hr), bot(ns), "fpriv", "Ⓕ")
    g.line(at(cm, 0.2, 1), at(sl, 0.8, 0), "ctrl")
    g.line(at(cm, 0.8, 1), at(hr, 0.3, 0), "ctrl")
    basics(g, 20, 744, 1600, 64, ["connect(global svc) → socket LB picks an AIStor pod → Pod IP over bond1 · no NAT · reply on the same path"])
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
