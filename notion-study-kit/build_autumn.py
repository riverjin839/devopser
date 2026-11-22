"""Archify 동적 다이어그램 빌더 (Autumn leaves 테마, autumn_theme.py 용).
spec 키 : hero(핵심 1곳) strong(강조) io(입출력 흰색) size stepx stepy\n노션 임베드 프레임(약 4:3)을 채우도록 stepy 를 자동으로 늘림. stepy 를 직접 주면 자동 조정 안 함

usage: python3 build_autumn.py <specs.py> <workdir(새 폴더)> <archify.mjs> <green_theme.py> <outdir> [only-key ...]
specs.py 는 N(), E() 로 SPECS dict 를 정의함 (examples/specs_example.py 참고).
"""
import json, os, subprocess, sys

SPEC_FILE, WORK, ARCH, THEME, OUT = sys.argv[1:6]
ONLY = set(sys.argv[6:])
os.makedirs(OUT, exist_ok=True)
import glob
CHROME = os.environ.get("ARCHIFY_CHROME") or next(iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))), "")
# 노션 HTML 임베드 프레임 비율(가로/세로). 기본 4:3, ASPECT=1.6 처럼 바꿀 수 있음
ASPECT = float(os.environ.get("ASPECT", "1.333"))
STEPY_MAX = 280


def N(i, t, label, sub, col, row, tag=None):
    return dict(id=i, type=t, label=label, sublabel=sub, col=col, row=row, tag=tag)


def E(a, b, label=None, variant=None, fs=None, ts=None):
    return dict(frm=a, to=b, label=label, variant=variant, fs=fs, ts=ts)


SPECS = {}
exec(open(SPEC_FILE, encoding="utf-8").read())

def build(key, spec):
    stepx = spec.get("stepx", 300); stepy = spec.get("stepy", 170)
    nw, nh = spec.get("size", [230, 100])
    cols = max(n["col"] for n in spec["nodes"]) + 1; rows = max(n["row"] for n in spec["nodes"]) + 1
    W = (cols - 1) * stepx + nw
    # 노션 프레임 비율에 맞게 행 간격을 늘림 (상한 STEPY_MAX). 그래도 넓으면 열·행 배치를 바꿔야 함
    if rows > 1 and "stepy" not in spec:
        stepy = int(min(STEPY_MAX, max(stepy, (W / ASPECT - nh) / (rows - 1))))
    H = (rows - 1) * stepy + nh
    ratio = W / H
    fill = min(ratio / ASPECT, ASPECT / ratio)
    d = os.path.join(WORK, key)
    os.makedirs(d, exist_ok=True)
    comps = []
    for n in spec["nodes"]:
        c = {"id": n["id"], "type": n["type"], "label": n["label"],
             "pos": [40 + n["col"] * stepx, 40 + n["row"] * stepy], "size": spec.get("size", [230, 100])}
        if n["sublabel"]:
            c["sublabel"] = n["sublabel"]
        if n["tag"]:
            c["tag"] = n["tag"]
        comps.append(c)
    conns = []
    for e in spec["edges"]:
        c = {"id": f'{e["frm"]}-{e["to"]}', "from": e["frm"], "to": e["to"]}
        for k, v in (("label", e["label"]), ("variant", e["variant"]), ("fromSide", e["fs"]), ("toSide", e["ts"])):
            if v:
                c[k] = v
        conns.append(c)
    cand = {"schema_version": 1, "diagram_type": "architecture",
            "meta": {"title": spec["title"], "locale": "ko", "output": os.path.relpath(os.path.join(d, key + ".html"), "/home/claude"),
                     "quality_profile": "showcase", "legend": {"mode": "hidden"}},
            "components": comps, "connections": conns}
    if spec.get("boundaries"):
        cand["boundaries"] = [{"kind": "region", "label": l, "wraps": w} for l, w in spec["boundaries"]]
    cpath = os.path.join(d, "candidate.json")
    json.dump(cand, open(cpath, "w"), ensure_ascii=False, indent=2)
    html = os.path.join(d, key + ".html")
    r = subprocess.run(["node", ARCH, "finalize", "architecture", cpath, html, "--quality", "showcase", "--json"],
                       cwd="/home/claude", env={**os.environ, "ARCHIFY_CHROME": CHROME}, capture_output=True, text=True, timeout=300)
    ok = r.returncode == 0
    msg = ""
    if not ok:
        try:
            rec = json.load(open(os.path.join(d, key + ".finalize.json")))
            for x in rec.get("diagnostics", [])[:3]:
                ev = x.get("evidence", {})
                msg += f'\n   {x.get("code")} owner={json.dumps(ev.get("owner"), ensure_ascii=False)} text={ev.get("text")} fix={(x.get("supportedFixes") or [""])[0][:220]}'
        except Exception as ex:  # noqa
            msg = r.stdout[-600:] + r.stderr[-600:]
    else:
        out = os.path.join(OUT, os.environ.get("PREFIX", "mlpe-") + f"{key}.html")
        cfg = {"hero": spec["hero"][:1], "strong": spec.get("strong", spec["hero"][1:]), "io": spec.get("io", []), "title": spec.get("title_on", "")}
        subprocess.run(["python3", "-I", THEME, html, out, json.dumps(cfg, ensure_ascii=False)], check=True, capture_output=True)
    warn = "" if fill >= 0.8 else f"  <- 노션 프레임 채움 {fill:.0%}. 열 수를 줄이거나 행을 늘릴 것"
    print(("PASS " if ok else "FAIL ") + key + f"  (비율 {ratio:.2f}, 채움 {fill:.0%}, stepy {stepy})" + warn + msg, flush=True)


for k, v in SPECS.items():
    if not ONLY or k in ONLY:
        build(k, v)
