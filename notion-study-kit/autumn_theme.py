"""Archify HTML -> Autumn leaves 팔레트 임베드용 HTML.

usage: python3 autumn_theme.py <in.html> <out.html> '<json>'
json = {"hero": [id], "strong": [id...], "io": [id...], "title": "..."}

역할별 색
  기본 도형  : 채움 #FFB343 / 테두리 #B37E2E / 글자 #614419
  강조 도형  : 채움 #DB9A39 / 테두리 #614419 / 글자 #3B2A10
  핵심 한 곳 : 채움 #614419 / 테두리 #614419 / 글자 #FFFFFF  (그림당 1개)
  입출력·보조: 채움 #FFFFFF / 테두리 #B37E2E / 글자 #614419
배경 투명, 화살표 #B37E2E 5px, 글씨 20px 이상, 제목 26px 굵게
"""
import json, sys

src, dst = sys.argv[1], sys.argv[2]
cfg = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
s = open(src, encoding="utf-8").read()

s = s.replace("window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'", "'light'")
assert "readerPaused = readStored() !== 'live';" in s
s = s.replace("readerPaused = readStored() !== 'live';", "readerPaused = readStored() === 'still';")

CSS = r"""
<style id="autumn-theme">
:root, html[data-theme="light"], html[data-theme="dark"] {
  --up: #E03131;    /* 등락: 상승 — 변경 금지 */
  --down: #1C64F2;  /* 등락: 하락 — 변경 금지 */
  --a1: #FFB343; --a2: #DB9A39; --a3: #B37E2E; --a4: #614419; --a-ink: #3B2A10;
  --bg: transparent; --grid: transparent; --canvas-dot: transparent;
  --text: var(--a4); --text-muted: var(--a4); --text-dim: var(--a3); --text-faint: var(--a3);
  --panel: #FFFFFF; --panel-border: var(--a3); --mask: #FFFFFF;
  --lane-fill: transparent; --lane-stroke: var(--a3);
  --arrow: var(--a3); --arrow-emphasis: var(--a3);
}
.toolbar, .header, .cards, .diagram-nav, .overview-map, .focus-chip, .route-probe,
.semantic-lens, .diagram-guide, .node-finder, .node-outline, .rail, .side-rail,
[class*="rail-"], .legend, [data-legend-hit] { display: none !important; }
html, body { background: transparent !important; background-image: none !important; }
body { padding: 0 !important; margin: 0 !important; min-height: 0 !important; }
.container { max-width: none !important; padding: 0 !important; margin: 0 !important; }
.diagram-container { padding: 0 !important; margin: 0 !important; border: 0 !important; border-radius: 0 !important;
  box-shadow: none !important; background: transparent !important; background-image: none !important; overflow: hidden !important; }
.diagram-container::before, .diagram-container::after { display: none !important; }
html, body { overflow: hidden !important; }
.diagram-container > svg { width: 100% !important; min-width: 0 !important; max-width: 100% !important;
  height: auto !important; transform: none !important; display: block; background: transparent !important; }
.diagram-container svg rect[fill="url(#grid)"] { display: none !important; }

/* 글씨 : 20px 이상, 굵게 */
.diagram-container svg text { font-family: 'Pretendard', 'Inter', 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif; font-weight: 700; }
.diagram-container svg text.t-primary { font-size: 24px !important; font-weight: 800 !important; }
.diagram-container svg text.t-muted { font-size: 20px !important; font-weight: 600 !important; }
.diagram-container svg text[class^="t-edge"], .diagram-container svg text[class*=" t-edge"] { font-size: 20px !important; font-weight: 700 !important; fill: var(--a4) !important; }
.diagram-container svg text[data-detail="fine"] { font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-variant-numeric: tabular-nums; font-weight: 800; font-size: 20px !important; fill: var(--a4) !important; }
.diagram-container svg text.a-title { font-size: 26px; font-weight: 800; fill: var(--a4); }

/* 도형 : 기본 = 밝은 주황 */
[data-node-id] > rect.c-mask { rx: 16px; ry: 16px; }
[data-node-id] > rect:not(.c-mask):not(.a-pill) { rx: 16px; ry: 16px; fill: var(--a1) !important; stroke: var(--a3) !important;
  stroke-width: 3px !important; filter: none !important; }
[data-node-id] .t-primary, [data-node-id] .t-muted { fill: var(--a4) !important; }
/* 강조 = 진한 주황 */
.diagram-container svg .r-strong > rect:not(.c-mask):not(.a-pill) { fill: var(--a2) !important; stroke: var(--a4) !important; }
.diagram-container svg .r-strong .t-primary, .diagram-container svg .r-strong .t-muted { fill: var(--a-ink) !important; }
/* 입출력·보조 = 흰색 */
.diagram-container svg .r-io > rect:not(.c-mask):not(.a-pill) { fill: #FFFFFF !important; stroke: var(--a3) !important; }
/* 핵심 한 곳 = 짙은 갈색 */
.diagram-container svg .r-hero > rect:not(.c-mask):not(.a-pill) { fill: var(--a4) !important; stroke: var(--a4) !important; }
.diagram-container svg .r-hero .t-primary, .diagram-container svg .r-hero .t-muted,
.diagram-container svg .r-hero text[data-detail="fine"] { fill: #FFFFFF !important; }
.diagram-container svg .r-hero .a-pill { fill: var(--a4) !important; stroke: #FFFFFF !important; }
.diagram-container svg .r-hero .a-ring { fill: var(--a4) !important; stroke: #FFFFFF !important; }
.diagram-container svg .r-hero .semantic-sigil, .diagram-container svg .r-hero .semantic-sigil * { stroke: #FFFFFF !important; color: #FFFFFF !important; }

/* 배지 · 아이콘 */
.diagram-container svg [data-detail="fine"] { opacity: 1 !important; }
.diagram-container svg .a-pill { fill: #FFFFFF !important; stroke: var(--a4) !important; stroke-width: 2.5px !important; }
.a-ring { fill: #FFFFFF; stroke: var(--a4); stroke-width: 2; }
.semantic-sigil, .semantic-sigil * { stroke: var(--a4) !important; color: var(--a4) !important; }

/* 화살표 : #B37E2E 5px */
.diagram-container svg path.a-default, .diagram-container svg path.a-emphasis, .diagram-container svg path.a-dashed,
.diagram-container svg path[class^="a-"], .diagram-container svg path[class*=" a-"] {
  stroke: var(--a3) !important; stroke-width: 5px !important; opacity: 1 !important; }
.diagram-container svg path.a-dashed { stroke-dasharray: 12 8 !important; }
.diagram-container svg marker polygon { fill: var(--a3) !important; stroke: none !important; }
.diagram-container svg rect.a-edge-pill { fill: #FFFFFF !important; stroke: var(--a3) !important; stroke-width: 2px !important; }

/* 동적 흐름 효과 : 팔레트 색 */
.diagram-container svg .ambient-edge-flow { stroke: var(--a2) !important; }
.diagram-container svg .ambient-flow-ripple { stroke: var(--a3) !important; fill: none !important; }
rect.c-region { fill: transparent !important; stroke: var(--a3) !important; stroke-dasharray: 8 6 !important; rx: 18px; ry: 18px; }
</style>
"""

JS = r"""
<script id="autumn-theme-js">
(function () {
  var CFG = __CFG__;
  var NS = 'http://www.w3.org/2000/svg';
  function role(id) {
    if ((CFG.hero || []).indexOf(id) >= 0) return 'r-hero';
    if ((CFG.strong || []).indexOf(id) >= 0) return 'r-strong';
    if ((CFG.io || []).indexOf(id) >= 0) return 'r-io';
    return 'r-basic';
  }
  function decorate() {
    var svg = document.querySelector('.diagram-container svg');
    if (!svg || svg.getAttribute('data-autumn-decorated')) return !!svg;
    // 마커 : 선 굵기에 비례해 커지지 않게 고정 크기
    svg.querySelectorAll('marker').forEach(function (m) {
      m.setAttribute('markerUnits', 'userSpaceOnUse');
      m.setAttribute('viewBox', '0 0 10 7');
      m.setAttribute('markerWidth', '22'); m.setAttribute('markerHeight', '16');
      m.setAttribute('refX', '8'); m.setAttribute('refY', '3.5');
    });
    svg.querySelectorAll('[data-node-id]').forEach(function (g) {
      g.classList.add(role(g.getAttribute('data-node-id')));
      // 큰 글씨 기준으로 세로 재배치 : 제목 → 부제 → 순번 배지, 도형 가운데 정렬
      var box0 = g.querySelector('rect:not(.c-mask)');
      if (box0) {
        var R = box0.getBBox();
        var items = [g.querySelector('text.t-primary'), g.querySelector('text.t-muted'), g.querySelector('text[data-detail="fine"]')]
          .filter(function (t) { return t && (t.textContent || '').trim(); });
        var gaps = [0, 6, 12], hs = items.map(function (t) { return t.getBBox().height; });
        var total = hs.reduce(function (a, b) { return a + b; }, 0) + gaps.slice(1, items.length).reduce(function (a, b) { return a + b; }, 0);
        var top = R.y + (R.height - total) / 2;
        items.forEach(function (t, i) {
          if (i) top += gaps[i];
          var bb = t.getBBox(), y = parseFloat(t.getAttribute('y') || '0');
          t.setAttribute('y', y + (top - bb.y));
          t.setAttribute('x', R.x + R.width / 2); t.setAttribute('text-anchor', 'middle');
          top += hs[i];
        });
      }
      var tag = g.querySelector('text[data-detail="fine"]');
      if (tag) {
        tag.textContent = (tag.textContent || '').trim();
        var b = tag.getBBox(), w = Math.max(b.width + 16, 30), h = b.height + 4;
        var pill = document.createElementNS(NS, 'rect');
        pill.setAttribute('class', 'a-pill');
        pill.setAttribute('x', b.x + b.width / 2 - w / 2); pill.setAttribute('y', b.y - 2);
        pill.setAttribute('width', w); pill.setAttribute('height', h);
        pill.setAttribute('rx', h / 2); pill.setAttribute('ry', h / 2);
        tag.parentNode.insertBefore(pill, tag);
      }
      var sig = g.querySelector('.semantic-sigil');
      if (sig) {
        var ctm = sig.getAttribute('transform') || '';
        var m = /translate\(([-\d.]+)[ ,]+([-\d.]+)\)\s*scale\(([-\d.]+)\)/.exec(ctm);
        if (m) {
          var tx = +m[1], ty = +m[2], sc = +m[3];
          var cx = tx + 8 * sc, cy = ty + 8 * sc, r = 8 * sc + 4;
          var ring = document.createElementNS(NS, 'circle');
          ring.setAttribute('class', 'a-ring');
          ring.setAttribute('cx', cx + 4); ring.setAttribute('cy', cy + 4); ring.setAttribute('r', r);
          sig.setAttribute('transform', 'translate(' + (tx + 4) + ' ' + (ty + 4) + ') scale(' + sc + ')');
          sig.parentNode.insertBefore(ring, sig);
        }
      }
    });
    svg.querySelectorAll('g[data-edge-id]').forEach(function (eg) {
      var t = eg.querySelector('text'), m = eg.querySelector('rect.c-mask');
      if (!t || !m) return;
      var b = t.getBBox(), padX = 10, padY = 4;
      m.setAttribute('x', b.x - padX); m.setAttribute('y', b.y - padY);
      m.setAttribute('width', b.width + padX * 2); m.setAttribute('height', b.height + padY * 2);
      m.setAttribute('rx', (b.height + padY * 2) / 2);
      m.classList.add('a-edge-pill');
    });
    if (CFG.title) {
      var bb = box(svg, false);
      var t = document.createElementNS(NS, 'text');
      t.setAttribute('class', 'a-title');
      t.setAttribute('x', bb[0]); t.setAttribute('y', bb[1] - 22);
      t.textContent = CFG.title;
      svg.appendChild(t);
    }
    svg.setAttribute('data-autumn-decorated', 'true');
    fit(svg);
    return true;
  }
  function box(svg, withTitle) {
    var inv = svg.getScreenCTM().inverse(), P = svg.createSVGPoint();
    var x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    var sel = '[data-node-id], g[data-edge-id], path[data-edge-id], rect.c-region, [data-boundary-id]' + (withTitle ? ', text.a-title' : '');
    svg.querySelectorAll(sel).forEach(function (el) {
      var r = el.getBoundingClientRect(); if (!r.width && !r.height) return;
      [[r.left, r.top], [r.right, r.bottom]].forEach(function (c) {
        P.x = c[0]; P.y = c[1]; var q = P.matrixTransform(inv);
        x0 = Math.min(x0, q.x); y0 = Math.min(y0, q.y); x1 = Math.max(x1, q.x); y1 = Math.max(y1, q.y);
      });
    });
    return [x0, y0, x1, y1];
  }
  function fit(svg) {
    svg = svg || document.querySelector('.diagram-container svg');
    if (!svg || !svg.getScreenCTM()) return;
    var b = box(svg, true);
    if (b[2] <= b[0]) return;
    var pad = 16;
    svg.setAttribute('viewBox', (b[0] - pad) + ' ' + (b[1] - pad) + ' ' + (b[2] - b[0] + pad * 2) + ' ' + (b[3] - b[1] + pad * 2));
    svg.removeAttribute('width'); svg.removeAttribute('height');
    svg.setAttribute('data-green-fit', 'true');
  }
  function boot() { if (!decorate()) setTimeout(boot, 120); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.addEventListener('load', function () { setTimeout(function () { decorate(); fit(); }, 60); setTimeout(function () { fit(); }, 600); });
})();
</script>
"""

JS = JS.replace("__CFG__", json.dumps(cfg, ensure_ascii=False))
i = s.rfind("</head>")
s = s[:i] + CSS + s[i:]
j = s.rfind("</body>")
s = s[:j] + JS + s[j:]
open(dst, "w", encoding="utf-8").write(s)
print("ok", dst)
