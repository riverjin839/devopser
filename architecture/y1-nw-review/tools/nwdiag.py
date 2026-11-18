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
    """랙 실장도 : 프레임 + 상단 ToR + 서버 유닛."""
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
    g = Diagram("N-0 DC 구간 · 랙 배치", 1640, 840)
    # 위 : I Lake 혼재 → Y1 구간 · 랙 역할 분리
    g.zone(20, 20, 300, 375, "I Lake (현행) : 랙 혼재")
    mixed = [("AIStor", "st"), ("Compute", "cp"), ("Compute", "cp"), ("AIStor", "st"), ("Compute", "cp")]
    mixed2 = [("Compute", "cp"), ("AIStor", "st"), ("AIStor", "st"), ("AIStor", "st"), ("Compute", "cp")]
    rack(g, 40, 80, "랙 a", mixed, uh=24)
    rack(g, 180, 80, "랙 b", mixed2, uh=24)
    g.text(26, 336, 290, 54, "랙마다 AIStor 수가 다름\n→ 노드당 몫 최대 수 배 차이", size=10, color=PUB, bold=True)
    secs = [(350, "DCNY01 · Compute 전용", "Compute", "cp"), (770, "DCNY02 · GPU 전용", "GPU", "gpu"), (1190, "DCNY03 · Storage 전용", "AIStor", "st")]
    for x0, title, nm, k in secs:
        g.zone(x0, 20, 410, 375, title, color=PRIV if k == "st" else MUTE)
        for i in range(3):
            rack(g, x0 + 20 + i * 130, 80, f"랙 {i + 1}" if i < 2 else "랙 R", [(nm, k)] * 4 + [("…", "dots")], leaf=False, uh=24)
        rule = "랙당 같은 수 M 대 (필수)" if k == "st" else "랙당 같은 수 (권장)"
        g.text(x0 + 10, 290, 390, 50, f"구간 · 랙에 {nm} 만 실장\n{rule}", size=11, color=PRIV if k == "st" else INK, bold=True)
    g.line((322, 220), (346, 220), "fpriv")
    # 아래 : DCNY03 랙 실장도
    g.zone(20, 415, 1600, 410, "DCNY03 Storage 랙 실장도 (Rack elevation) : 랙 R 개 × 랙당 M 대 = Storage 노드 약 100 대")
    units = [(f"AIStor-{i:02d}", "st") for i in (1, 2, 3)] + [("…", "dots"), ("AIStor-M", "st")]
    xs = [40, 190, 340, 560]
    for i, x in enumerate(xs):
        rack(g, x, 485, f"Rack {i + 1}" if i < 3 else "Rack R", units)
    g.text(470, 605, 80, 30, "… × R", size=14, bold=True, align="center")
    g.box(720, 460, 880, 300,
          "균등 배치 규칙\n"
          "· 랙마다 Storage 서버 수 M 동일 (R × M ≈ 100)\n"
          "· 랙 상단 ToR Leaf 쌍 (Leaf-A · Leaf-B, vPC)\n"
          "· 서버마다 bond0 2포트 · bond1 2포트 → Leaf-A 1 · Leaf-B 1 로 분산\n"
          "  (같은 NIC 의 두 포트를 한 Leaf 에 몰지 않음)\n"
          "· 노드 라벨 rack=<물리 랙> = 실장 위치 (인벤토리와 일치)\n"
          "· Leaf 포트 : 랙당 M × 4 × 100G + 업링크\n\n"
          "증설 규칙\n"
          "· 기존 랙마다 같은 수 추가, 또는 새 랙 여러 개를 같은 수로\n"
          "· 새 랙 1개에 일부만 실장 금지 (그 랙 노드에 부하 집중)\n"
          "· 공간 · 전력 · Leaf 포트를 랙 단위로 미리 확보\n\n"
          "왜 중요한가\n"
          "· 패브릭(ECMP)은 랙(Leaf 쌍) 단위로 같은 몫을 줌\n"
          "· 랙당 서버 수가 같아야 노드 100 대가 같은 몫 (eTP Local 성립 조건)",
          fill="#FFFFFF", stroke=PRIV, size=12)
    g.cells[-1] = g.cells[-1].replace("verticalAlign=middle", "verticalAlign=top")
    return g


# ================================================================ N-1 전체 물리 토폴로지
def n1():
    g = Diagram("N-1 전체 토폴로지", 1640, 1010)
    cl = g.dev("cloud", 745, 14, "외부 client\n원천 소스", size=12)
    fw = g.dev("fw", 807, 140, "FA Core (방화벽)")
    g.line(bot(cl), top(fw), "pub", "S3 443")
    ss = [g.dev("l3", 690, 262, "Super Spine-1\n(Border)"), g.dev("l3", 900, 262, "Super Spine-2\n(Border)")]
    for s in ss:
        g.line(at(fw, 0.5, 1), top(s), "pub")
    g.text(1000, 250, 330, 86, "Super Spine (Border)\neBGP · ASN : <SS ASN>\nFA Core 와 VRF-lite eBGP (PUBLIC · PRIVATE)\nEVPN Type-5 중계 · next-hop unchanged", size=10, box=True)
    g.text(370, 250, 300, 86, "외부 client 진입 : Spine 방향만\nPUBLIC VIP/32 경로 V 개 ECMP\nresilient hashing · 계층별 해시 seed\nBFD 300ms × 3 · MTU 9216", size=10, box=True)
    secs = [(20, "DCNY01 · Compute K8s", "Compute 노드"), (560, "DCNY02 · GPU", "GPU 노드"), (1100, "DCNY03 · Storage K8s (AIStor)", "AIStor 노드")]
    for x0, title, nd in secs:
        g.zone(x0, 400, 520, 590, title)
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
        g.text(x0 + 222, 632, 100, 24, "… × R 랙", size=11, align="center", bold=True)
        sv = [g.dev("srv", x0 + 60, 800, nd), g.dev("srv", x0 + 150, 800, nd),
              g.dev("srv", x0 + 352, 800, nd), g.dev("srv", x0 + 442, 800, nd)]
        for i, s in enumerate(sv):
            la, lb = (lv[0], lv[1]) if i < 2 else (lv[2], lv[3])
            g.line(at(la, 0.5, 1.0), at(s, 0.35, 0), "pub")
            g.line(at(lb, 0.5, 1.0), at(s, 0.65, 0), "priv")
        g.text(x0 + 30, 520, 470, 40, "Spine : 구간 ASN (eBGP) · retain route-target all", size=10, color=MUTE)
        g.text(x0 + 30, 704, 470, 40, "Leaf 쌍 : 랙별 고유 ASN · rd auto · VTEP (vPC 공유)\nmaximum-paths ≥ V · multipath-relax · LACP fast", size=10, color=MUTE)
        g.text(x0 + 30, 900, 470, 76, f"{nd} : 랙당 같은 수\nbond0 (PUBLIC) · bond1 (PRIVATE) 각 2 × 100G\n802.3ad · layer3+4 · LACP fast\nCilium BGP : bond 별 eBGP → Leaf 쌍", size=10, box=True)
    g.text(1340, 350, 290, 44, "구간 간 링크 (DCNY01 · 02 → 03)\n대역 ≥ Compute + GPU 합 · 2 경로 이상 · RTT ≤ 0.2 ms", size=10, color=INK, box=True)
    legend(g, 20, 250, [("phys", "패브릭 링크 (100G)"), ("pc", "vPC peer-link"), ("pub", "노드 bond0 · PUBLIC"), ("priv", "노드 bond1 · PRIVATE")])
    return g


# ================================================================ N-2 랙 · 노드 연결 상세
def n2():
    g = Diagram("N-2 랙 · 노드 연결 상세", 1640, 850)
    la = g.dev("l3", 600, 60, "Leaf-A")
    lb = g.dev("l3", 990, 60, "Leaf-B")
    g.line(right(la), left(lb), "pc", "vPC peer-link · 공유 VTEP")
    g.text(30, 30, 520, 74, "Leaf-A / Leaf-B (랙별 고유 ASN · 쌍은 같은 ASN)\nVRF PUBLIC : eBGP ↔ 노드 bond0 대역 (PUBLIC VIP/32 수신)\nVRF PRIVATE : eBGP ↔ 노드 bond1 대역 (PodCIDR · PRIVATE VIP 수신)\nport-channel : LACP fast · MTU 9216 · VRF 별 수신 prefix-list · uRPF 확인", size=10, box=True)
    g.text(1100, 30, 520, 74, "노드 쪽 BGP (Cilium BGP Control Plane)\nbond 별 인스턴스 : bond0 ↔ VRF PUBLIC · bond1 ↔ VRF PRIVATE\nhold 12 · keepalive 4 · GR 15 (I Lake 유지) · BFD 미지원\n작업 : drain → BGP 라벨 해제 → 철회 확인", size=10, box=True)
    for k, x0 in enumerate((80, 860)):
        g.zone(x0, 330, 700, 470, f"Storage 노드 {k + 1} (AIStor 1 Pod / 노드)", title_at="bottom")
        g.dev("srv", x0 + 30, 380, "")
        b0 = g.box(x0 + 120, 360, 250, 70, "bond0 · PUBLIC\n802.3ad · layer3+4 · LACP fast\nMTU 9000 (선택)", fill="#F6E3D8", stroke=PUB, size=10)
        b1 = g.box(x0 + 410, 360, 250, 70, "bond1 · PRIVATE\n802.3ad · layer3+4 · LACP fast\nMTU 9000 (선택)", fill="#E3ECE0", stroke=PRIV, size=10)
        for b, kind in ((b0, "pub"), (b1, "priv")):
            g.line(at(la, 0.5, 1), at(b, 0.3, 0), kind)
            g.line(at(lb, 0.5, 1), at(b, 0.7, 0), kind)
        ag = g.box(x0 + 30, 470, 640, 92,
                   "Cilium agent : native routing · netkit · eBPF host routing\n"
                   "BGP 인스턴스 ① (bond0) : PUBLIC VIP/32 — eTP Local : AIStor Pod 있는 노드만 광고\n"
                   "BGP 인스턴스 ② (bond1) : PodCIDR · PRIVATE VIP\n"
                   "소켓 LB (내부 global-svc) · LB 맵 상향 · Bandwidth Manager · BBR", fill="#FFFFFF", size=10)
        g.line(at(b0, 0.5, 1), at(ag, 0.24, 0), "pub")
        g.line(at(b1, 0.5, 1), at(ag, 0.66, 0), "priv")
        pod = g.box(x0 + 30, 592, 300, 62, "AIStor Pod\n어느 Pod 든 모든 요청 처리", fill="#E3ECE0", stroke=PRIV, size=11, bold=True)
        g.box(x0 + 360, 592, 310, 62, "RHEL : bbr + fq · 버퍼 128M\ntuned network-throughput · IRQ NUMA 고정", fill="#F2EFE6", size=10)
        g.line(at(ag, 0.3, 1), top(pod), "phys")
        g.text(x0 + 30, 668, 640, 84, "외부 요청 : bond0 → 로컬 AIStor Pod (노드 간 추가 경유 없음)\nerasure 조각 송수신 : bond1 (Pod 간 기본 통신)\n내부 client (global-svc) : bond1 → AIStor Pod (NAT 없음)\nPDB 로 AIStor 동시 중단 수 제한 · preStop 대기", size=10)
    legend(g, 30, 160, [("pc", "vPC peer-link"), ("pub", "bond0 · VRF PUBLIC"), ("priv", "bond1 · VRF PRIVATE"), ("phys", "노드 내부")])
    return g


# ================================================================ N-3 eBGP / EVPN 제어 구조
def n3():
    g = Diagram("N-3 eBGP · EVPN 제어 구조", 1640, 900)
    ss = [g.dev("l3", 700, 40, "Super Spine-1"), g.dev("l3", 900, 40, "Super Spine-2")]
    g.text(1000, 30, 420, 46, "Super Spine : ASN <SS> (2대 같은 ASN)\nEVPN 경로 중계 · next-hop unchanged · retain RT all", size=10, box=True)
    rows = [(20, "DCNY01", "Compute"), (560, "DCNY02", "GPU"), (1100, "DCNY03", "Storage")]
    for i, (x0, dc, role) in enumerate(rows):
        g.zone(x0, 160, 520, 590, f"{dc} · {role}")
        sp = [g.dev("l3", x0 + 140, 210, "Spine-A"), g.dev("l3", x0 + 330, 210, "Spine-B")]
        g.text(x0 + 20, 280, 480, 26, f"ASN <SP-{i + 1}> (구간 Spine 같은 ASN)", size=10, align="center", color=MUTE)
        for s in ss:
            for p in sp:
                g.line(bot(s), top(p), "bgp")
        lv = [g.dev("l3", x0 + 70, 380, "Leaf 쌍 1"), g.dev("l3", x0 + 400, 380, "Leaf 쌍 R")]
        g.text(x0 + 150, 392, 220, 24, "…", size=14, align="center", bold=True)
        for p in sp:
            for l in lv:
                g.line(bot(p), top(l), "bgp")
        g.text(x0 + 10, 456, 250, 64, f"ASN <LF-{i + 1}-1>\nRD 10.{i + 1}.0.1:VNI (rd auto)", size=10, align="center")
        g.text(x0 + 290, 456, 230, 64, f"ASN <LF-{i + 1}-R>\nRD 10.{i + 1}.0.R:VNI (rd auto)", size=10, align="center")
        nd = g.box(x0 + 60, 560, 400, 70, f"{role} K8s 노드 (Cilium)\n클러스터 ASN <CL-{i + 1}> · bond 별 인스턴스", fill="#F2EFE6", size=11, bold=True)
        for l in lv:
            g.line(bot(l), top(nd), "bgp")
        adv = {"Compute": "광고 : PodCIDR (bond1)", "GPU": "광고 : PodCIDR (bond1)", "Storage": "광고 : PUBLIC VIP/32 (bond0, eTP Local)\n· PodCIDR · PRIVATE VIP (bond1)"}[role]
        g.text(x0 + 60, 640, 400, 50, adv, size=10, align="center", color=PUB if role == "Storage" else PRIV, bold=True)
        g.text(x0 + 20, 690, 480, 56, "leaf : maximum-paths ≥ V · as-path multipath-relax\nrewrite-evpn-rt-asn · VRF 별 수신 prefix-list\nallowas-in · as-override 사용 안 함", size=10, color=MUTE)
    g.box(20, 770, 760, 104,
          "Border 에서 본 PUBLIC VIP/32 (기대)\n"
          "RD 10.3.0.1:VNI  VIP/32  → VTEP Leaf 쌍 1 (DCNY03)\n"
          "RD 10.3.0.2:VNI  VIP/32  → VTEP Leaf 쌍 2\n"
          "…  RD 가 leaf 마다 달라 경로 V 개가 모두 전달 · ECMP V 설치", fill="#FFFFFF", size=11)
    g.box(800, 770, 820, 104,
          "eBGP only 로 얻는 것 · 남는 조건\n"
          "· AS-path 로 루프 방지 → iBGP · eBGP 혼합 multipath(eiBGP) 불필요, IGP metric 비교 없음\n"
          "· 그래도 필요 : 고유 RD · maximum-paths ≥ V · ECMP 하드웨어 폭 ≥ V · resilient hashing\n"
          "· 부담 : ASN 계획 · spine 설정 일관성 · 수렴 시 우회 탐색 (같은 계층 같은 ASN · BFD 로 완화)",
          fill="#FFFFFF", size=11)
    legend(g, 20, 20, [("bgp", "eBGP 세션 (underlay · EVPN)")])
    return g


# ================================================================ N-4 트래픽 경로
def n4():
    g = Diagram("N-4 트래픽 경로", 1640, 880)
    cl = g.dev("cloud", 745, 14, "외부 client", size=12)
    fw = g.dev("fw", 807, 140, "FA Core")
    ss = g.dev("l3", 796, 260, "Super Spine (Border)")
    g.zone(20, 380, 560, 480, "DCNY01 · Compute K8s")
    g.zone(1060, 380, 560, 480, "DCNY03 · Storage K8s (AIStor)")
    sp1 = g.dev("l3", 276, 420, "Spine")
    lf1 = g.dev("l3", 276, 580, "Leaf 쌍")
    cn = g.dev("srv", 285, 750, "Compute 노드\nETL client Pod")
    sp3 = g.dev("l3", 1316, 420, "Spine")
    lf3 = g.dev("l3", 1316, 580, "Leaf 쌍")
    sn = g.dev("srv", 1240, 750, "AIStor 노드 N1\n(로컬 Pod 처리)")
    sn2 = g.dev("srv", 1420, 750, "AIStor 노드 N2")
    # 외부 경로 (PUBLIC)
    g.line(bot(cl), top(fw), "fpub", "① S3 443")
    g.line(at(fw, 0.5, 1), top(ss), "fpub", "②")
    g.line(at(ss, 1, 0.3), at(sp3, 0.5, 0), "fpub", "③ VIP/32 ECMP (V 경로)")
    g.line(bot(sp3), top(lf3), "fpub", "④")
    g.line(at(lf3, 0.3, 1), at(sn, 0.5, 0), "fpub", "⑤ bond0")
    g.line(at(sn, 1, 0.5), at(sn2, 0, 0.5), "priv", "조각 bond1")
    # 내부 경로 (PRIVATE)
    g.line(at(cn, 0.5, 0), bot(lf1), "fpriv", "Ⓐ bond1")
    g.line(top(lf1), bot(sp1), "fpriv", "Ⓑ VXLAN PRIVATE")
    g.line(at(sp1, 1, 0.3), at(ss, 0, 0.7), "fpriv", "Ⓒ")
    g.line(at(ss, 0.8, 1), at(sp3, 0, 0.7), "fpriv", "Ⓓ 구간 간 링크")
    g.line(at(lf3, 0.7, 1), at(sn2, 0.5, 0), "fpriv", "Ⓔ bond1")
    # ClusterMesh 제어
    cm = g.box(660, 600, 320, 74, "ClusterMesh (제어)\nKVStoreMesh · apiserver × 2\nglobal-svc 백엔드 · identity 동기화", fill="#FBF3DE", stroke=KEY, size=10)
    g.line(at(cm, 0, 0.5), at(cn, 1, 0.3), "ctrl")
    g.line(at(cm, 1, 0.5), at(sn, 0, 0.3), "ctrl")
    g.text(40, 420, 210, 120, "내부 client (Ⓐ ~ Ⓔ)\nETL Pod → global-svc\n소켓 LB 가 연결 시 AIStor Pod 주소로 변경\nPod IP 그대로 · NAT 없음\nbond1 → VRF PRIVATE → 구간 간 링크 → Storage 노드 bond1", size=10, box=True)
    g.text(1080, 600, 200, 84, "외부 client (① ~ ⑤)\nPUBLIC VIP · eTP Local\n받은 노드의 AIStor Pod 가 처리\n응답 : 같은 경로 역방향 (bond0)", size=10, box=True)
    legend(g, 40, 120, [("fpub", "외부 요청 · PUBLIC (bond0)"), ("fpriv", "내부 요청 · PRIVATE (bond1)"), ("priv", "AIStor 조각 송수신 (bond1)"), ("ctrl", "ClusterMesh 동기화 (제어)")])
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
