"""2색 테마 그림 모듈 : draw.io XML + SVG 를 같은 모델에서 생성.
색은 THEME 의 primary · neutral 2개만 사용. 강조 · 구분은 명도(tint)와 선 굵기 · 점선으로만."""
import html

# ▼ 테마 : 첨부 이미지(ref/theme.jpg) 추출값
#   색 2개 = accent(레드 오렌지) · positive(그린). ink(먹) · paper(종이)는 무채색 바탕으로 색 수에서 제외
#   페이지 · 구역 배경 = 투명. paper 는 옅은 채움 계산의 기준색으로만 사용
THEME = {
    "accent":   "#CC501A",   # 문제 · 쏠림 · 금지
    "positive": "#5F8B5A",   # 개선 · 균등 · 권장
    "ink":      "#201E1F",   # 글씨 · 선 · 제목 바탕 (명도 단계로 구분)
    "paper":    "#F7F3EC",   # 배경
    "key":      "#D4A941",   # (시험) 핵심 · 결론 : 머스터드. USE_KEY=1 일 때만 사용
}
import os as _os
USE_KEY = _os.environ.get("USE_KEY") == "1"
FONT = "Noto Sans CJK KR, Malgun Gothic, sans-serif"
DFONT = "Noto Sans KR,Noto Sans CJK KR,Malgun Gothic,Apple SD Gothic Neo,sans-serif"   # draw.io 용 대체 글꼴 목록


def mix(hex_, t, base=None):
    """t = 1 이면 원색, 0 이면 base(기본 paper)."""
    base = base or THEME["paper"]
    a = [int(hex_.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(base.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#{:02X}{:02X}{:02X}".format(*[round(y + (x - y) * t) for x, y in zip(a, b)])


def A(t): return mix(THEME["accent"], t)
def G(t): return mix(THEME["positive"], t)
def K(t): return mix(THEME["ink"], t)
def Y(t): return mix(THEME["key"], t)


# ▼ 가독성 : 상자 크기에 맞춰 글자를 최대한 키움 (draw.io · SVG 공통)
FONT_SAFETY = 1.2   # 맑은 고딕 · Apple SD 고딕 등 PC 글꼴이 Noto 보다 넓은 경우 대비


def text_w(line, sz):
    w = 0.0
    for ch in line:
        o = ord(ch)
        if o >= 0x1100 and not (0x2000 <= o <= 0x206F):
            w += 1.0           # 한글 · CJK · 기호
        elif ch == " ":
            w += 0.32
        elif ch.isupper() or ch.isdigit():
            w += 0.64
        else:
            w += 0.56
    return w * sz * FONT_SAFETY


def fit_size(b):
    """원래 크기 이상, 상한 이하에서 상자 안에 들어가는 가장 큰 글자 크기."""
    base = b["size"]
    kind = b["kind"]
    if kind == "title":
        cap = 24
    elif kind == "zone":
        cap = 17
    else:
        cap = 20
    lines = b["text"].split("\n")
    if b.get("cube"):
        aw, ah = b["w"] - CUBE_D - 10, b["h"] - CUBE_D - 6
    elif kind == "zone":
        aw, ah = b["w"] - 20, 10 ** 6          # 구역 제목 : 폭만 제한
        lines = lines[:1]
    else:
        aw, ah = b["w"] - 14, b["h"] - 8
    best = base
    s = base
    while s <= cap:
        tw = max(text_w(l, s) for l in lines)
        th = len(lines) * (s + 5) + (4 if b.get("cube") else 0)
        if tw <= aw and th <= ah:
            best = s
        else:
            break
        s += 0.5
    return round(best * 2) / 2


EDGE_FONT = 13

BG = THEME["paper"]
CUBE_D = 10   # 큐브 깊이 (px)
CARD = mix("#FFFFFF", 0.6)   # 종이보다 밝은 카드 바탕


# 박스 종류 : (fill, stroke, strokeWidth, fontColor, dashed)
def kinds():
    return {
        "title":  (K(1.0), K(1.0), 1, BG, False),
        "sub":    (Y(0.30), Y(1.0), 2, K(1.0), False) if USE_KEY else (K(0.06), K(0.45), 1, K(1.0), False),
        "key":    (Y(0.22), Y(1.0), 2.5, K(1.0), False) if USE_KEY else (K(0.04), K(0.30), 1, K(1.0), False),
        "hot":    (A(1.0), A(1.0), 3, "#FFFFFF", False),     # 문제 · 금지 : 원색 + 굵은 테두리
        "good":   (G(0.20), G(1.0), 2.5, K(1.0), False),      # 개선 · 권장 : 옅은 채움 + 굵은 테두리
        "device": (CARD, K(0.70), 1.5, K(1.0), False),        # 스위치 · 랙
        "node":   (K(0.07), K(0.40), 1, K(1.0), False),       # 일반 서버 · Pod
        "note":   (K(0.04), K(0.30), 1, K(1.0), False),
        "zone":   ("none", K(0.45), 1.2, K(1.0), True),
        "plain":  (CARD, K(0.40), 1, K(1.0), False),
        "mute":   ("none", K(0.25), 1, K(0.6), True),
        "label":  ("none", "none", 0, K(1.0), False),     # 글자만
    }


# 선 종류 : (color, width, dashed)
def ekinds():
    return {
        "hot":  (A(1.0), 5, False),
        "good": (G(1.0), 2.5, False),
        "norm": (K(0.55), 1.5, False),
        "idle": (K(0.35), 1.2, True),
        "back": (G(1.0), 2.5, True),
    }


class Page:
    def __init__(self, name, w=1400, h=820):
        self.name, self.w, self.h = name, w, h
        self.boxes, self.edges, self.n = {}, [], 0

    def box(self, x, y, w, h, text, kind="plain", bold=False, size=12, align="center", valign="middle", cube=False):
        self.n += 1
        bid = f"b{self.n}"
        self.boxes[bid] = dict(x=x, y=y, w=w, h=h, text=text, kind=kind, bold=bold, size=size,
                               align=align, valign=valign, cube=cube)
        return bid

    def zone(self, x, y, w, h, text):
        return self.box(x, y, w, h, text, "zone", bold=True, size=13, valign="top")

    def title(self, text, sub=""):
        self.box(20, 14, self.w - 40, 44, text, "title", bold=True, size=18)
        if sub:
            self.box(20, 62, self.w - 40, 30, sub, "sub", bold=True, size=13)

    def edge(self, a, b, label="", kind="norm", anc=None, both=False):
        self.edges.append(dict(a=a, b=b, label=label, kind=kind, anc=anc, both=both))

    def anchors(self, e):
        if e.get("anc"):
            return e["anc"]
        A, B = self.boxes[e["a"]], self.boxes[e["b"]]
        if B["y"] >= A["y"] + A["h"]:
            return 0.5, 1, 0.5, 0
        if A["y"] >= B["y"] + B["h"]:
            return 0.5, 0, 0.5, 1
        if B["x"] >= A["x"] + A["w"]:
            return 1, 0.5, 0, 0.5
        return 0, 0.5, 1, 0.5


def drawio(pages, gliffy=False):
    """gliffy=True : Confluence Gliffy 가져오기용. cube 의 direction(회전) 속성을 쓰지 않음."""
    K, E = kinds(), ekinds()
    out = ['<mxfile host="app.diagrams.net" type="device">']
    for pi, p in enumerate(pages):
        out.append(f'<diagram id="p{pi+1}" name="{html.escape(p.name)}">')
        out.append(f'<mxGraphModel dx="{p.w}" dy="{p.h}" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
                   f'arrows="1" fold="1" page="1" pageScale="1" pageWidth="{p.w}" pageHeight="{p.h}" math="0" '
                   f'shadow="0" background="none"><root><mxCell id="0"/><mxCell id="1" parent="0"/>')
        for bid, b0 in p.boxes.items():
            b = dict(b0, size=fit_size(b0))
            fill, stroke, sw, fc, dash = K[b["kind"]]
            st = (f"rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
                  f"strokeWidth={sw};fontColor={fc};fontSize={b['size']};fontStyle={1 if b['bold'] else 0};"
                  f"align={b['align']};verticalAlign={b['valign']};spacing=6;fontFamily={DFONT};")
            if dash:
                st += "dashed=1;"
            lh = b["size"] + 5
            val = html.escape(f'<div style="line-height:{lh}px">' + html.escape(b["text"]).replace("\n", "<br>") + "</div>")
            if b.get("cube"):
                head, *body = b["text"].split("\n")
                cdir = "" if gliffy else "direction=south;anchorPointDirection=0;"
                st = (f"shape=cube;size={CUBE_D};{cdir}boundedLbl=1;backgroundOutline=1;"
                      f"darkOpacity=0.05;darkOpacity2=0.12;whiteSpace=wrap;html=1;fillColor={fill};"
                      f"strokeColor={stroke};strokeWidth={sw};fontColor={fc};fontSize={b['size']};"
                      f"align=center;verticalAlign=top;spacing=0;spacingTop=2;fontFamily={DFONT};")
                sep = fc if fc.upper() == "#FFFFFF" else stroke
                sz = b["size"]; lh = sz + 5
                rest = b["h"] - CUBE_D - (sz + 9)           # 머리 아래 남은 높이 (SVG 와 같은 계산)
                pad = max(0, (rest - len(body) * lh) / 2)
                inner = (f'<div style="line-height:{sz + 5}px;font-weight:bold">{html.escape(head)}</div>'
                         f'<div style="border-top:1px solid {sep};margin:0 auto;height:0;width:{b["w"] - CUBE_D}px"></div>'
                         f'<div style="line-height:{lh}px;padding-top:{pad:.0f}px">' + "<br>".join(html.escape(x) for x in body) + "</div>")
                val = html.escape(inner)
            out.append(f'<mxCell id="p{pi}{bid}" value="{val}" style="{st}" vertex="1" parent="1">'
                       f'<mxGeometry x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" height="{b["h"]}" as="geometry"/></mxCell>')
        for ei, e in enumerate(p.edges):
            col, w, dash = E[e["kind"]]
            ax, ay, bx, by = p.anchors(e)
            A_, B_ = p.boxes[e["a"]], p.boxes[e["b"]]
            x1, y1 = A_["x"] + A_["w"] * ax, A_["y"] + A_["h"] * ay
            x2, y2 = B_["x"] + B_["w"] * bx, B_["y"] + B_["h"] * by
            # 상자에 붙이지 않고 좌표 고정 직선 : draw.io 자동 경로(꺾임) 방지, 목업과 동일
            st = (f"edgeStyle=none;orthogonal=0;rounded=0;html=1;strokeColor={col};strokeWidth={w};fontSize={EDGE_FONT};fontColor={col};"
                  f"fontStyle=1;fontFamily={DFONT};labelBackgroundColor={CARD};endArrow=block;endFill=1;")
            if dash:
                st += "dashed=1;"
            if e["both"]:
                st += "startArrow=block;startFill=1;"
            val = html.escape(html.escape(e["label"]).replace("\n", "<br>"))
            out.append(f'<mxCell id="p{pi}e{ei}" value="{val}" style="{st}" edge="1" parent="1">'
                       f'<mxGeometry relative="1" as="geometry"><mxPoint x="{x1:.1f}" y="{y1:.1f}" as="sourcePoint"/>'
                       f'<mxPoint x="{x2:.1f}" y="{y2:.1f}" as="targetPoint"/></mxGeometry></mxCell>')
        out.append("</root></mxGraphModel></diagram>")
    out.append("</mxfile>")
    return "\n".join(out)


def svg(p):
    K, E = kinds(), ekinds()
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {p.w} {p.h}" width="{p.w}" height="{p.h}" font-family="{FONT}">',
         "<defs>"]
    for k, (col, w, d) in E.items():
        o.append(f'<marker id="m{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="{4 if w >= 4 else 6}" '
                 f'markerHeight="{4 if w >= 4 else 6}" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    o.append("</defs>")
    boxes = [dict(b, size=fit_size(b)) for b in p.boxes.values()]
    for b in boxes:
        fill, stroke, sw, fc, dash = K[b["kind"]]
        da = ' stroke-dasharray="6 4"' if dash else ""
        if b.get("cube"):
            x, y, w, h, d = b["x"], b["y"], b["w"], b["h"], CUBE_D
            top = mix(THEME["ink"], 0.05, fill if fill != "none" else BG)
            side = mix(THEME["ink"], 0.12, fill if fill != "none" else BG)
            o.append(f'<polygon points="{x},{y+d} {x+d},{y} {x+w},{y} {x+w-d},{y+d}" fill="{top}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"/>')
            o.append(f'<polygon points="{x+w-d},{y+d} {x+w},{y} {x+w},{y+h-d} {x+w-d},{y+h}" fill="{side}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"/>')
            o.append(f'<rect x="{x}" y="{y+d}" width="{w-d}" height="{h-d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
            o.append(f'<line x1="{x}" y1="{y+d+b["size"]+9}" x2="{x+w-d}" y2="{y+d+b["size"]+9}" stroke="{fc if fc.upper() == '#FFFFFF' else stroke}" stroke-width="1"/>')
            continue
        o.append(f'<rect x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" height="{b["h"]}" rx="5" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="{sw}"{da}/>')
    for e in p.edges:
        col, w, dash = E[e["kind"]]
        A, B = p.boxes[e["a"]], p.boxes[e["b"]]
        ax, ay, bx, by = p.anchors(e)
        x1, y1 = A["x"] + A["w"] * ax, A["y"] + A["h"] * ay
        x2, y2 = B["x"] + B["w"] * bx, B["y"] + B["h"] * by
        da = ' stroke-dasharray="7 5"' if dash else ""
        ms = f' marker-start="url(#m{e["kind"]})"' if e["both"] else ""
        o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="{w}"{da} '
                 f'marker-end="url(#m{e["kind"]})"{ms}/>')
        if e["label"]:
            lines = e["label"].split("\n")
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            wd, ht = max(text_w(l, EDGE_FONT) for l in lines) + 10, len(lines) * (EDGE_FONT + 3) + 4
            o.append(f'<rect x="{mx-wd/2}" y="{my-ht/2}" width="{wd}" height="{ht}" fill="{CARD}"/>')
            for i, l in enumerate(lines):
                o.append(f'<text x="{mx}" y="{my-ht/2+EDGE_FONT+2+i*(EDGE_FONT+3)}" font-size="{EDGE_FONT}" font-weight="bold" fill="{col}" '
                         f'text-anchor="middle">{html.escape(l)}</text>')
    for b in boxes:
        fc = K[b["kind"]][3]
        if b.get("cube"):
            head, *body = b["text"].split("\n")
            x, y, w, h, d, sz = b["x"], b["y"], b["w"], b["h"], CUBE_D, b["size"]
            cx = x + (w - d) / 2
            o.append(f'<text x="{cx}" y="{y+d+sz+3}" font-size="{sz}" fill="{fc}" text-anchor="middle" font-weight="bold">{html.escape(head)}</text>')
            lh = sz + 5
            top = y + d + sz + 9
            y0 = top + (y + h - top) / 2 - len(body) * lh / 2 + sz - 1
            for i, l in enumerate(body):
                o.append(f'<text x="{cx}" y="{y0+i*lh}" font-size="{sz}" fill="{fc}" text-anchor="middle">{html.escape(l)}</text>')
            continue
        lines = b["text"].split("\n")
        lh = b["size"] + 5
        y0 = b["y"] + 8 + b["size"] if b["valign"] == "top" else b["y"] + b["h"] / 2 - len(lines) * lh / 2 + b["size"]
        if b["align"] == "left":
            x0, anc = b["x"] + 10, "start"
        elif b["align"] == "right":
            x0, anc = b["x"] + b["w"] - 10, "end"
        else:
            x0, anc = b["x"] + b["w"] / 2, "middle"
        fw = ' font-weight="bold"' if b["bold"] else ""
        for i, l in enumerate(lines):
            o.append(f'<text x="{x0}" y="{y0+i*lh}" font-size="{b["size"]}" fill="{fc}" text-anchor="{anc}"{fw}>'
                     f'{html.escape(l)}</text>')
    o.append("</svg>")
    return "\n".join(o)
