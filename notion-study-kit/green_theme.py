"""Archify HTML -> 아키텍처만 남긴 그린(Donezo 계열) 라이트 테마 임베드용 HTML.

usage: python3 green_theme.py <in.html> <out.html> [hero-kind]
"""
import sys

src, dst = sys.argv[1], sys.argv[2]
hero_ids = [x for x in (sys.argv[3] if len(sys.argv) > 3 else "").split(",") if x]
s = open(src, encoding="utf-8").read()

# 1) 기본 테마 = 라이트 고정
s = s.replace("window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'", "'light'")
# 2) 기본 동적(Live) — 저장값이 없으면 재생
assert "readerPaused = readStored() !== 'live';" in s
s = s.replace("readerPaused = readStored() !== 'live';", "readerPaused = readStored() === 'still';")

CSS = r"""
<style id="green-light-theme">
/* ================================================================
   GREEN LIGHT THEME (Donezo 계열)
   - 액센트  : #0F6E56 (그린) / 딥 #0B4A3A / 소프트 #E4F1EC
   - 배경    : #F3F6F4, 카드 #FFFFFF
   - 카드    : 16px 라운드 + 소프트 섀도우
   - 배지    : 필(pill) 모양, 숫자는 모노 + tabular-nums
   - 아이콘  : 원형 아웃라인 안에 배치
   - 비활성/영역 : 회색 빗금 패턴
   - 등락 색 : --up(빨강) / --down(파랑) 은 테마와 무관하게 고정. 변경 금지.
   - DeltaNumber : 상승 ▲ + --up, 하락 ▼ + --down, 보합 – + 중립. 캐럿은 숫자 앞.
   ================================================================ */
:root, html[data-theme="light"], html[data-theme="dark"] {
  --up: #E03131;    /* 등락: 상승 — 변경 금지 */
  --down: #1C64F2;  /* 등락: 하락 — 변경 금지 */
  --g-accent: #0F6E56; --g-deep: #0B4A3A; --g-mid: #2E8B6E; --g-soft: #E4F1EC;
  --g-bg: #F3F6F4; --g-card: #FFFFFF; --g-line: #E2E8E4;
  --g-text: #16201B; --g-muted: #7A847F; --g-hatch: #C9D0CC;
  --bg: var(--g-bg); --grid: transparent; --canvas-dot: transparent;
  --text: var(--g-text); --text-muted: var(--g-muted); --text-dim: #A7AFAB; --text-faint: var(--g-muted);
  --panel: var(--g-card); --panel-border: var(--g-line); --mask: var(--g-card);
  --lane-fill: transparent; --lane-stroke: var(--g-hatch);
  --arrow: #9AA6A0; --arrow-emphasis: var(--g-accent);
  --frontend-fill: #fff; --frontend-stroke: var(--g-accent);
  --backend-fill: #fff; --backend-stroke: var(--g-accent);
  --database-fill: #fff; --database-stroke: var(--g-accent);
  --cloud-fill: #fff; --cloud-stroke: var(--g-accent);
  --security-fill: #fff; --security-stroke: var(--g-accent);
  --messagebus-fill: #fff; --messagebus-stroke: var(--g-accent);
  --external-fill: #fff; --external-stroke: var(--g-accent);
}
.delta-number { font-family: 'JetBrains Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.delta-number[data-dir="up"]   { color: var(--up); }   .delta-number[data-dir="up"]::before   { content: "▲ "; }
.delta-number[data-dir="down"] { color: var(--down); } .delta-number[data-dir="down"]::before { content: "▼ "; }
.delta-number[data-dir="flat"] { color: var(--g-muted); } .delta-number[data-dir="flat"]::before { content: "– "; }

/* 아키텍처 캔버스만 남김 */
.toolbar, .header, .cards, .diagram-nav, .overview-map, .focus-chip, .route-probe,
.semantic-lens, .diagram-guide, .node-finder, .node-outline, .rail, .side-rail,
[class*="rail-"], .legend, [data-legend-hit] { display: none !important; }
html, body { background: var(--g-bg) !important; background-image: none !important; }
body { padding: 0 !important; margin: 0 !important; min-height: 0 !important; }
.container { max-width: none !important; padding: 0 !important; margin: 0 !important; }
.diagram-container { padding: 12px !important; margin: 0 !important; border: 0 !important; border-radius: 0 !important;
  box-shadow: none !important; background: var(--g-bg) !important; background-image: none !important; }
.diagram-container::before, .diagram-container::after { display: none !important; }

/* 임베드 칸 폭에 맞춤 (가로 스크롤 제거) */
html, body { overflow: hidden !important; }
.diagram-container { overflow: hidden !important; padding: 0 !important; }
.diagram-container > svg { width: 100% !important; min-width: 0 !important; max-width: 100% !important;
  height: auto !important; transform: none !important; display: block; }

/* 폰트 */
.diagram-container svg text.t-primary { font-size: 15.5px !important; }
.diagram-container svg text.t-muted { font-size: 12px !important; }
.diagram-container svg text[class^="t-edge"], .diagram-container svg text[class*=" t-edge"] { font-size: 11.5px !important; font-weight: 600; }
.diagram-container svg text { font-family: 'Pretendard', 'Inter', 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif; }
.diagram-container svg text[data-detail="fine"] { font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-variant-numeric: tabular-nums; font-weight: 700; font-size: 10.5px !important; fill: var(--g-accent) !important; }
.diagram-container svg .t-primary { fill: var(--g-text) !important; }
.diagram-container svg .t-muted { fill: var(--g-muted) !important; }

/* 16px 라운드 카드 + 소프트 섀도우 */
[data-node-id] > rect.c-mask { rx: 16px; ry: 16px; }
[data-node-id] > rect:not(.c-mask) { rx: 16px; ry: 16px; fill: var(--g-card) !important; stroke: var(--g-line) !important;
  stroke-width: 1px !important; filter: drop-shadow(0 6px 14px rgba(16, 40, 30, 0.08)) drop-shadow(0 1px 2px rgba(16, 40, 30, 0.06)); }

/* 히어로 카드 (진녹 그라데이션) */
.diagram-container svg .g-hero > rect:not(.c-mask) { fill: url(#g-hero) !important; stroke: none !important;
  filter: drop-shadow(0 10px 18px rgba(15, 110, 86, 0.28)); }
.diagram-container svg .g-hero .t-primary { fill: #FFFFFF !important; }
.diagram-container svg .g-hero .t-muted { fill: rgba(255, 255, 255, 0.78) !important; }
.diagram-container svg .g-hero text[data-detail="fine"] { fill: #FFFFFF !important; }
.diagram-container svg .g-hero .g-pill { fill: rgba(255,255,255,0.18) !important; stroke: rgba(255,255,255,0.7) !important; }
.diagram-container svg .g-hero .g-icon-ring { fill: rgba(255, 255, 255, 0.12) !important; stroke: rgba(255, 255, 255, 0.85) !important; }
.diagram-container svg .g-hero .semantic-sigil, .diagram-container svg .g-hero .semantic-sigil * { stroke: #FFFFFF !important; color: #FFFFFF !important; }

/* 줌 단계와 무관하게 배지 항상 표시 */
.diagram-container svg [data-detail="fine"] { opacity: 1 !important; }
/* 필 배지 / 원형 아이콘 */
.g-pill { fill: var(--g-soft); stroke: var(--g-accent); stroke-width: 0.8; }
.g-icon-ring { fill: #FFFFFF; stroke: var(--g-accent); stroke-width: 1; }
.semantic-sigil, .semantic-sigil * { stroke: var(--g-accent) !important; color: var(--g-accent) !important; }

/* 영역(파이프라인) = 빗금 패턴 */
rect.c-region { fill: url(#g-hatch) !important; stroke: var(--g-hatch) !important; stroke-dasharray: none !important; rx: 18px; ry: 18px; }

/* 화살표 라벨 = 필 */
.diagram-container svg rect.g-edge-pill { fill: #FFFFFF !important; stroke: var(--g-line) !important; stroke-width: 0.8px !important; }
.diagram-container svg [data-edge-label] rect, .diagram-container svg .edge-label-bg { rx: 8px; ry: 8px; }
</style>
"""

JS = r"""
<script id="green-light-theme-js">
(function () {
  function decorate() {
    var svg = document.querySelector('.diagram-container svg');
    if (!svg || svg.getAttribute('data-green-decorated')) return !!svg;
    var NS = 'http://www.w3.org/2000/svg';
    var defs = svg.querySelector('defs') || svg.insertBefore(document.createElementNS(NS, 'defs'), svg.firstChild);
    defs.insertAdjacentHTML('beforeend',
      '<linearGradient id="g-hero" x1="0" y1="0" x2="1" y2="1">' +
        '<stop offset="0" stop-color="#1F8A6B"/><stop offset="0.55" stop-color="#0F6E56"/><stop offset="1" stop-color="#0B4A3A"/>' +
      '</linearGradient>' +
      '<pattern id="g-hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
        '<rect width="10" height="10" fill="#F7F9F8"/><line x1="0" y1="0" x2="0" y2="10" stroke="#D3D9D5" stroke-width="3"/>' +
      '</pattern>');
    var HERO = __HERO_IDS__;
    svg.querySelectorAll('[data-node-id]').forEach(function (g) {
      if (HERO.indexOf(g.getAttribute('data-node-id')) >= 0) g.classList.add('g-hero');
      var tag = g.querySelector('text[data-detail="fine"]');
      if (tag) {
        tag.textContent = (tag.textContent || '').trim();
        var b = tag.getBBox(), w = Math.max(b.width + 10, 16), h = b.height + 3;
        var pill = document.createElementNS(NS, 'rect');
        pill.setAttribute('class', 'g-pill');
        pill.setAttribute('x', b.x + b.width / 2 - w / 2); pill.setAttribute('y', b.y - 1.5);
        pill.setAttribute('width', w); pill.setAttribute('height', h);
        pill.setAttribute('rx', h / 2); pill.setAttribute('ry', h / 2);
        tag.parentNode.insertBefore(pill, tag);
      }
      var sig = g.querySelector('.semantic-sigil');
      if (sig) {
        var sb = sig.getBBox(), ctm = sig.getAttribute('transform') || '';
        var m = /translate\(([-\d.]+)[ ,]+([-\d.]+)\)\s*scale\(([-\d.]+)\)/.exec(ctm);
        if (m) {
          var tx = +m[1], ty = +m[2], sc = +m[3];
          var cx = tx + 8 * sc, cy = ty + 8 * sc, r = 8 * sc + 3.5;
          var ring = document.createElementNS(NS, 'circle');
          ring.setAttribute('class', 'g-icon-ring');
          ring.setAttribute('cx', cx + 2); ring.setAttribute('cy', cy + 2); ring.setAttribute('r', r);
          sig.setAttribute('transform', 'translate(' + (tx + 2) + ' ' + (ty + 2) + ') scale(' + sc + ')');
          sig.parentNode.insertBefore(ring, sig);
        }
      }
    });
    svg.querySelectorAll('g[data-edge-id]').forEach(function (eg) {
      var t = eg.querySelector('text'), m = eg.querySelector('rect.c-mask');
      if (!t || !m) return;
      var b = t.getBBox(), padX = 6, padY = 3;
      m.setAttribute('x', b.x - padX); m.setAttribute('y', b.y - padY);
      m.setAttribute('width', b.width + padX * 2); m.setAttribute('height', b.height + padY * 2);
      m.setAttribute('rx', (b.height + padY * 2) / 2);
      m.classList.add('g-edge-pill');
    });
    svg.setAttribute('data-green-decorated', 'true');
    fit(svg);
    return true;
  }
  function fit(svg) {
    svg = svg || document.querySelector('.diagram-container svg');
    if (!svg || !svg.getScreenCTM()) return;
    var inv = svg.getScreenCTM().inverse(), P = svg.createSVGPoint();
    var x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    svg.querySelectorAll('[data-node-id], g[data-edge-id], path[data-edge-id], rect.c-region, [data-boundary-id]').forEach(function (el) {
      var r = el.getBoundingClientRect(); if (!r.width && !r.height) return;
      [[r.left, r.top], [r.right, r.bottom]].forEach(function (c) {
        P.x = c[0]; P.y = c[1]; var q = P.matrixTransform(inv);
        x0 = Math.min(x0, q.x); y0 = Math.min(y0, q.y); x1 = Math.max(x1, q.x); y1 = Math.max(y1, q.y);
      });
    });
    if (x1 <= x0) return;
    var pad = 14;
    svg.setAttribute('viewBox', (x0 - pad) + ' ' + (y0 - pad) + ' ' + (x1 - x0 + pad * 2) + ' ' + (y1 - y0 + pad * 2));
    svg.removeAttribute('width'); svg.removeAttribute('height');
    svg.setAttribute('data-green-fit', 'true');
  }
  window.addEventListener('resize', function () { /* viewBox is width-independent */ });
  function boot() { if (!decorate()) setTimeout(boot, 120); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.addEventListener('load', function () { setTimeout(function () { decorate(); fit(); }, 60); setTimeout(function () { fit(); }, 600); });
})();
</script>
"""

import json
JS = JS.replace("__HERO_IDS__", json.dumps(hero_ids))
i = s.rfind("</head>")
s = s[:i] + CSS + s[i:]
j = s.rfind("</body>")
s = s[:j] + JS + s[j:]
open(dst, "w", encoding="utf-8").write(s)
print("ok", dst)
