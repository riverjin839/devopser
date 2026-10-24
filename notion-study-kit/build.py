"""Archify 동적 다이어그램 빌더 (그린 테마).

usage: python3 build.py <specs.py> <workdir(새 폴더)> <archify.mjs> <green_theme.py> <outdir> [only-key ...]
specs.py 는 N(), E() 로 SPECS dict 를 정의함 (examples/specs_example.py 참고).
"""
import json, os, subprocess, sys

SPEC_FILE, WORK, ARCH, THEME, OUT = sys.argv[1:6]
ONLY = set(sys.argv[6:])
os.makedirs(OUT, exist_ok=True)
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def N(i, t, label, sub, col, row, tag=None):
    return dict(id=i, type=t, label=label, sublabel=sub, col=col, row=row, tag=tag)


def E(a, b, label=None, variant=None, fs=None, ts=None):
    return dict(frm=a, to=b, label=label, variant=variant, fs=fs, ts=ts)


SPECS = {}
exec(open(SPEC_FILE, encoding="utf-8").read())

def build(key, spec):
    stepx = spec.get("stepx", 250); stepy = spec.get("stepy", 150)
    d = os.path.join(WORK, key)
    os.makedirs(d, exist_ok=True)
    comps = []
    for n in spec["nodes"]:
        c = {"id": n["id"], "type": n["type"], "label": n["label"],
             "pos": [40 + n["col"] * stepx, 40 + n["row"] * stepy], "size": [172, 76]}
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
        out = os.path.join(OUT, f"mlpe-{key}.html")
        subprocess.run(["python3", "-I", THEME, html, out, ",".join(spec["hero"])], check=True, capture_output=True)
    print(("PASS " if ok else "FAIL ") + key + msg, flush=True)


for k, v in SPECS.items():
    if not ONLY or k in ONLY:
        build(k, v)
