#!/usr/bin/env python3
"""Y1 N/W 검토 요청용 전통 네트워크 다이어그램 (Cisco 아이콘 · 포트 · 링크 · ASN · VRF 표기).

draw.io 파일을 직접 생성. 목업 PNG 는 같은 파일을 mxGraph 로 렌더링해서 만듦 (render 단계).
연결선은 좌표 고정 직선 (draw.io 자동 경로 · Gliffy 직각 변환 방지).
"""
import html
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FONT = "Noto Sans KR,Malgun Gothic,Apple SD Gothic Neo,sans-serif"
INK, MUTE, PAPER = "#2B2A27", "#8A877E", "#FFFFFF"
PUB, PRIV, KEY = "#CC501A", "#5F8B5A", "#D4A941"     # PUBLIC(bond0) · PRIVATE(bond1) · 제어/강조

CISCO = ("sketch=0;html=1;pointerEvents=1;dashed=0;fillColor=#036897;strokeColor=#ffffff;strokeWidth=2;"
         "verticalLabelPosition=bottom;verticalAlign=top;align=center;outlineConnect=0;")
ICON = {  # 종류 : (shape, w, h)
    "l3": ("mxgraph.cisco.switches.layer_3_switch", 48, 48),
    "fw": ("mxgraph.cisco.security.firewall", 26, 58),
    "srv": ("mxgraph.cisco.servers.fileserver", 30, 44),
    "cloud": ("mxgraph.cisco.storage.cloud", 150, 86),
}
LINK = {  # 종류 : (색, 굵기, 점선, 화살표)
    "phys": (INK, 1.5, False, False),
    "pc": (INK, 3.5, False, False),
    "pub": (PUB, 2.5, False, False),
    "priv": (PRIV, 2.5, False, False),
    "bgp": (MUTE, 1.5, True, False),
    "fpub": (PUB, 4.5, False, True),
    "fpriv": (PRIV, 4.5, False, True),
    "ctrl": (KEY, 2.5, True, True),
}


def esc(t):
    return html.escape(html.escape(t).replace("\n", "<br>"))


class Diagram:
    def __init__(self, name, w, h):
        self.name, self.w, self.h = name, w, h
        self.cells = []      # 장비 · 글자 (맨 위)
        self.edges = []      # 연결선 (중간)
        self.zones = []      # 구역 (맨 아래)
        self.n = 0

    def _id(self):
        self.n += 1
        return f"c{self.n}"

    def dev(self, kind, x, y, label, size=12, bold=True):
        shape, w, h = ICON[kind]
        st = CISCO + f"shape={shape};fontFamily={FONT};fontSize={size};fontColor={INK};labelBackgroundColor={PAPER};" + ("fontStyle=1;" if bold else "")
        if kind == "cloud":
            st = st.replace("verticalLabelPosition=bottom;verticalAlign=top;", "verticalLabelPosition=middle;verticalAlign=middle;").replace(f"fontColor={INK}", "fontColor=#FFFFFF").replace(f"labelBackgroundColor={PAPER};", "")
        self.cells.append(f'<mxCell id="{self._id()}" value="{esc(label)}" style="{st}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return dict(x=x, y=y, w=w, h=h)

    def text(self, x, y, w, h, t, size=11, color=INK, align="left", bold=False, box=False, valign="top"):
        st = (f"text;html=1;whiteSpace=wrap;align={align};verticalAlign={valign};spacing=4;fontFamily={FONT};"
              f"fontSize={size};fontColor={color};" + ("fontStyle=1;" if bold else ""))
        if box:
            st += f"fillColor={PAPER};strokeColor={MUTE};rounded=1;arcSize=4;"
        else:
            st += f"labelBackgroundColor={PAPER};"
        self.cells.append(f'<mxCell id="{self._id()}" value="{esc(t)}" style="{st}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')

    def zone(self, x, y, w, h, title, color=MUTE, size=13, title_at="top"):
        st = (f"rounded=1;arcSize=2;html=1;fillColor=none;strokeColor={color};dashed=1;dashPattern=6 4;strokeWidth=1.5;"
              f"align=left;verticalAlign=top;spacingLeft=8;spacingTop=2;fontFamily={FONT};fontSize={size};fontStyle=1;fontColor={INK};")
        self.zones.append(f'<mxCell id="{self._id()}" value="" style="{st}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        ty = y + 2 if title_at == "top" else y + h - size - 16
        self.text(x + 6, ty, len(title) * size * 0.95 + 20, size + 12, title, size=size, bold=True)

    def box(self, x, y, w, h, t, fill="#F2EFE6", stroke=MUTE, size=11, align="left", bold=False):
        st = (f"rounded=1;arcSize=6;html=1;whiteSpace=wrap;fillColor={fill};strokeColor={stroke};align={align};verticalAlign=middle;"
              f"spacing=5;fontFamily={FONT};fontSize={size};fontColor={INK};" + ("fontStyle=1;" if bold else ""))
        self.cells.append(f'<mxCell id="{self._id()}" value="{esc(t)}" style="{st}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return dict(x=x, y=y, w=w, h=h)

    def line(self, p1, p2, kind="phys", label="", size=10):
        col, wd, dash, arrow = LINK[kind]
        st = (f"edgeStyle=none;orthogonal=0;rounded=0;html=1;strokeColor={col};strokeWidth={wd};"
              f"endArrow={'block' if arrow else 'none'};endFill=1;startArrow=none;fontFamily={FONT};fontSize={size};"
              f"fontColor={col if col != MUTE else INK};fontStyle=1;labelBackgroundColor={PAPER};")
        if dash:
            st += "dashed=1;dashPattern=5 4;"
        self.edges.append(f'<mxCell id="{self._id()}" value="{esc(label)}" style="{st}" edge="1" parent="1">'
                          f'<mxGeometry relative="1" as="geometry"><mxPoint x="{p1[0]:.1f}" y="{p1[1]:.1f}" as="sourcePoint"/>'
                          f'<mxPoint x="{p2[0]:.1f}" y="{p2[1]:.1f}" as="targetPoint"/></mxGeometry></mxCell>')

    def xml(self, pid):
        body = "".join(self.zones + self.edges + self.cells)
        return (f'<diagram id="{pid}" name="{html.escape(self.name)}"><mxGraphModel dx="1400" dy="900" grid="0" gridSize="10" '
                f'guides="1" tooltips="1" connect="0" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{self.w}" '
                f'pageHeight="{self.h}" background="none" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
                f'{body}</root></mxGraphModel></diagram>')


def top(d):
    return (d["x"] + d["w"] / 2, d["y"])


def bot(d):
    return (d["x"] + d["w"] / 2, d["y"] + d["h"])


def left(d, dy=0.5):
    return (d["x"], d["y"] + d["h"] * dy)


def right(d, dy=0.5):
    return (d["x"] + d["w"], d["y"] + d["h"] * dy)


def at(d, fx, fy):
    return (d["x"] + d["w"] * fx, d["y"] + d["h"] * fy)


def legend(g, x, y, items):
    g.text(x, y, 230, 22, "범례", size=11, bold=True)
    for i, (k, t) in enumerate(items):
        yy = y + 30 + i * 22
        g.line((x + 6, yy), (x + 52, yy), k)
        g.text(x + 58, yy - 10, 190, 20, t, size=10)


# ================================================================ N-0 DC 구간 · 랙 배치
def rack(g, x, y, title, units, leaf=True, uh=26, w=118):
    n = len(units)
    h = 34 + (64 if leaf else 0) + n * (uh + 4) + 12
    g.box(x, y, w, h, "", fill="#FFFFFF", stroke=INK)
    g.text(x - 10, y - 26, w + 20, 22, title, size=11, bold=True, align="center")
    yy = y + 10
    if leaf:
        for nm in ("Leaf-A", "Leaf-B"):
            g.box(x + 8, yy, w - 16, 24, nm, fill="#036897", stroke="#036897", size=10, align="center", bold=True)
            g.cells[-1] = g.cells[-1].replace(f"fontColor={INK}", "fontColor=#FFFFFF")
            yy += 30
        yy += 6
    for t, k in units:
        fill, stroke = {"st": ("#E3ECE0", PRIV), "cp": ("#ECEAE3", MUTE), "gpu": ("#E6E3DA", INK), "dots": ("#FFFFFF", "#FFFFFF")}[k]
        g.box(x + 8, yy, w - 16, uh, t, fill=fill, stroke=stroke, size=10, align="center")
        yy += uh + 4
    return h


def n0():
    g = Diagram("N-0 DC 구간 · 랙 배치", 1640, 780)
    g.zone(20, 20, 300, 330, "I Lake : 랙 혼재", color=PUB)
    mixed = [("AIStor", "st"), ("Compute", "cp"), ("Compute", "cp"), ("AIStor", "st"), ("Compute", "cp")]
    mixed2 = [("Compute", "cp"), ("AIStor", "st"), ("AIStor", "st"), ("AIStor", "st"), ("Compute", "cp")]
    rack(g, 40, 80, "랙 a", mixed, uh=24)
    rack(g, 180, 80, "랙 b", mixed2, uh=24)
    secs = [(350, "DCNY01 · Compute", "Compute", "cp"), (770, "DCNY02 · GPU", "GPU", "gpu"), (1190, "DCNY03 · Storage", "AIStor", "st")]
    for x0, title, nm, k in secs:
        g.zone(x0, 20, 410, 330, title, color=PRIV if k == "st" else MUTE)
        for i in range(3):
            rack(g, x0 + 20 + i * 130, 80, f"랙 {i + 1}" if i < 2 else "랙 R", [(nm, k)] * 4 + [("…", "dots")], leaf=False, uh=24)
    g.line((322, 200), (346, 200), "fpriv")
    g.zone(20, 380, 900, 390, "DCNY03 랙 실장 : R 랙 × M 대", color=PRIV)
    units = [(f"AIStor-{i:02d}", "st") for i in (1, 2, 3)] + [("…", "dots"), ("AIStor-M", "st")]
    for i, x in enumerate([40, 190, 340, 580]):
        rack(g, x, 450, f"Rack {i + 1}" if i < 3 else "Rack R", units)
    g.text(470, 570, 100, 30, "… × R", size=14, bold=True, align="center")
    return g


# ================================================================ N-1 전체 토폴로지
def n1():
    g = Diagram("N-1 전체 토폴로지", 1640, 920)
    cl = g.dev("cloud", 745, 14, "외부 client", size=12)
    fw = g.dev("fw", 807, 140, "FA Core")
    g.line(bot(cl), top(fw), "pub", "S3 443")
    ss = [g.dev("l3", 690, 262, "Super Spine-1\n(Border)"), g.dev("l3", 900, 262, "Super Spine-2\n(Border)")]
    for s in ss:
        g.line(at(fw, 0.5, 1), top(s), "pub")
    secs = [(20, "DCNY01 · Compute K8s", "Compute"), (560, "DCNY02 · GPU", "GPU"), (1100, "DCNY03 · Storage K8s", "AIStor")]
    for x0, title, nd in secs:
        g.zone(x0, 400, 520, 500, title)
        sp = [g.dev("l3", x0 + 130, 450, "Spine-A"), g.dev("l3", x0 + 342, 450, "Spine-B")]
        for s in ss:
            for p in sp:
                g.line(at(s, 0.5, 1.0), top(p), "phys")
        lv = [g.dev("l3", x0 + 40, 620, "Leaf-1A"), g.dev("l3", x0 + 140, 620, "Leaf-1B"),
              g.dev("l3", x0 + 332, 620, "Leaf-RA"), g.dev("l3", x0 + 432, 620, "Leaf-RB")]
        for p in sp:
            for l in lv:
                g.line(bot(p), top(l), "phys")
        g.line(right(lv[0]), left(lv[1]), "pc", "vPC")
        g.line(right(lv[2]), left(lv[3]), "pc", "vPC")
        g.text(x0 + 222, 632, 100, 24, "… × R", size=11, align="center", bold=True)
        sv = [g.dev("srv", x0 + 60, 800, nd), g.dev("srv", x0 + 150, 800, nd),
              g.dev("srv", x0 + 352, 800, nd), g.dev("srv", x0 + 442, 800, nd)]
        for i, s in enumerate(sv):
            la, lb = (lv[0], lv[1]) if i < 2 else (lv[2], lv[3])
            g.line(at(la, 0.5, 1.0), at(s, 0.35, 0), "pub")
            g.line(at(lb, 0.5, 1.0), at(s, 0.65, 0), "priv")
    return g


# ================================================================ N-2 랙 · 노드 연결
def n2():
    g = Diagram("N-2 랙 · 노드 연결", 1640, 640)
    la = g.dev("l3", 600, 40, "Leaf-A")
    lb = g.dev("l3", 990, 40, "Leaf-B")
    g.line(right(la), left(lb), "pc", "vPC")
    for k, x0 in enumerate((80, 860)):
        g.zone(x0, 290, 700, 330, f"Storage 노드 {k + 1}", title_at="bottom")
        g.dev("srv", x0 + 30, 340, "")
        b0 = g.box(x0 + 120, 320, 250, 44, "bond0 · PUBLIC", fill="#F6E3D8", stroke=PUB, size=12, align="center", bold=True)
        b1 = g.box(x0 + 410, 320, 250, 44, "bond1 · PRIVATE", fill="#E3ECE0", stroke=PRIV, size=12, align="center", bold=True)
        for b, kind in ((b0, "pub"), (b1, "priv")):
            g.line(at(la, 0.5, 1), at(b, 0.3, 0), kind)
            g.line(at(lb, 0.5, 1), at(b, 0.7, 0), kind)
        ag = g.box(x0 + 120, 410, 540, 60, "Cilium agent\nBGP ① bond0 · BGP ② bond1", fill="#FFFFFF", size=12, align="center", bold=True)
        g.line(at(b0, 0.5, 1), at(ag, 0.24, 0), "pub")
        g.line(at(b1, 0.5, 1), at(ag, 0.78, 0), "priv")
        pod = g.box(x0 + 270, 500, 240, 50, "AIStor Pod", fill="#E3ECE0", stroke=PRIV, size=12, align="center", bold=True)
        g.line(at(ag, 0.5, 1), top(pod), "phys")
    return g


# ================================================================ N-3 eBGP · EVPN 제어
def n3():
    g = Diagram("N-3 eBGP · EVPN 제어", 1640, 760)
    ss = [g.dev("l3", 700, 30, "Super Spine-1"), g.dev("l3", 900, 30, "Super Spine-2")]
    g.text(1000, 40, 200, 26, "ASN <SS>", size=12, bold=True)
    rows = [(20, "DCNY01", "Compute"), (560, "DCNY02", "GPU"), (1100, "DCNY03", "Storage")]
    for i, (x0, dc, role) in enumerate(rows):
        g.zone(x0, 150, 520, 590, f"{dc} · {role}")
        sp = [g.dev("l3", x0 + 140, 200, "Spine-A"), g.dev("l3", x0 + 330, 200, "Spine-B")]
        g.text(x0 + 20, 272, 480, 26, f"ASN <SP-{i + 1}>", size=11, align="center", bold=True)
        for s in ss:
            for p in sp:
                g.line(bot(s), top(p), "bgp")
        lv = [g.dev("l3", x0 + 70, 380, "Leaf 쌍 1"), g.dev("l3", x0 + 400, 380, "Leaf 쌍 R")]
        g.text(x0 + 150, 392, 220, 24, "…", size=14, align="center", bold=True)
        for p in sp:
            for l in lv:
                g.line(bot(p), top(l), "bgp")
        g.text(x0 + 10, 456, 250, 44, f"ASN <LF-{i + 1}-1>\nRD 10.{i + 1}.0.1:VNI", size=11, align="center")
        g.text(x0 + 290, 456, 230, 44, f"ASN <LF-{i + 1}-R>\nRD 10.{i + 1}.0.R:VNI", size=11, align="center")
        nd = g.box(x0 + 60, 560, 400, 56, f"{role} K8s · ASN <CL-{i + 1}>", fill="#F2EFE6", size=12, align="center", bold=True)
        for l in lv:
            g.line(bot(l), top(nd), "bgp")
        adv = "VIP/32 (bond0) · PodCIDR (bond1)" if role == "Storage" else "PodCIDR (bond1)"
        g.text(x0 + 60, 630, 400, 30, adv, size=11, align="center", color=PUB if role == "Storage" else PRIV, bold=True)
    return g


# ================================================================ N-4 트래픽 경로
def n4():
    g = Diagram("N-4 트래픽 경로", 1640, 880)
    cl = g.dev("cloud", 745, 14, "외부 client", size=12)
    fw = g.dev("fw", 807, 140, "FA Core")
    ss = g.dev("l3", 796, 260, "Super Spine (Border)")
    g.zone(20, 380, 560, 480, "DCNY01 · Compute K8s")
    g.zone(1060, 380, 560, 480, "DCNY03 · Storage K8s")
    sp1 = g.dev("l3", 276, 420, "Spine")
    lf1 = g.dev("l3", 276, 580, "Leaf 쌍")
    cn = g.dev("srv", 285, 750, "Compute 노드\nETL client Pod")
    sp3 = g.dev("l3", 1316, 420, "Spine")
    lf3 = g.dev("l3", 1316, 580, "Leaf 쌍")
    sn = g.dev("srv", 1240, 750, "AIStor 노드 N1")
    sn2 = g.dev("srv", 1420, 750, "AIStor 노드 N2")
    g.line(bot(cl), top(fw), "fpub", "①")
    g.line(at(fw, 0.5, 1), top(ss), "fpub", "②")
    g.line(at(ss, 1, 0.3), at(sp3, 0.5, 0), "fpub", "③")
    g.line(bot(sp3), top(lf3), "fpub", "④")
    g.line(at(lf3, 0.3, 1), at(sn, 0.5, 0), "fpub", "⑤")
    g.line(at(sn, 1, 0.5), at(sn2, 0, 0.5), "priv")
    g.line(at(cn, 0.5, 0), bot(lf1), "fpriv", "Ⓐ")
    g.line(top(lf1), bot(sp1), "fpriv", "Ⓑ")
    g.line(at(sp1, 1, 0.3), at(ss, 0, 0.7), "fpriv", "Ⓒ")
    g.line(at(ss, 0.8, 1), at(sp3, 0, 0.7), "fpriv", "Ⓓ")
    g.line(at(lf3, 0.7, 1), at(sn2, 0.5, 0), "fpriv", "Ⓔ")
    cm = g.box(700, 610, 240, 50, "ClusterMesh", fill="#FBF3DE", stroke=KEY, size=12, align="center", bold=True)
    g.line(at(cm, 0, 0.5), at(cn, 1, 0.3), "ctrl")
    g.line(at(cm, 1, 0.5), at(sn, 0, 0.3), "ctrl")
    return g


def write():
    os.makedirs(os.path.join(OUT, "drawio"), exist_ok=True)
    pages = [("N-0", n0()), ("N-1", n1()), ("N-2", n2()), ("N-3", n3()), ("N-4", n4())]
    head = '<mxfile host="app.diagrams.net" type="device">'
    for pid, d in pages:
        with open(os.path.join(OUT, "drawio", f"{pid}.drawio"), "w", encoding="utf-8") as f:
            f.write(head + d.xml(pid) + "</mxfile>")
    with open(os.path.join(OUT, "y1-nw-review-diagrams.drawio"), "w", encoding="utf-8") as f:
        f.write(head + "".join(d.xml(pid) for pid, d in pages) + "</mxfile>")
    print("ok", len(pages))


if __name__ == "__main__":
    write()
