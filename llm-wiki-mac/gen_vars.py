#!/usr/bin/env python3
"""
gen_vars.py - LLM Wiki 를 근거로 kubespray group_vars 초안을 만드는 실습 코드

  LLM  : 요구사항과 위키 페이지를 읽고, 변수 선택과 근거를 JSON 으로 써서 돌려준다
  코드 : 허용값·CPU 아키텍처 호환을 검사하고, 통과하면 YAML 로 저장하고 log 에 남긴다

사용
  python gen_vars.py --req "M1 Mac VM 2대, Cilium 실습" --arch arm64 \
      --pages concepts/cilium sources/arch --out ~/kubespray/inventory/lima
기준 : kubespray v2.32.0 (inventory/sample, docs/advanced/arch.md)
"""
import argparse, datetime as dt, json, os, sys
from pathlib import Path

import ollama

WIKI  = Path(os.environ.get("WIKI_ROOT", ".")) / "wiki"
MODEL = os.environ.get("WIKI_MODEL", "gemma3:4b")
OPTS  = {"temperature": 0.1, "num_ctx": 8192}

# kubespray v2.32.0 inventory/sample 주석 기준 허용값
ALLOWED = {
    "kube_network_plugin": ["calico", "cilium", "flannel", "kube-ovn", "kube-router", "cni"],
    "container_manager":   ["containerd", "crio", "docker"],
    "kube_proxy_mode":     ["ipvs", "iptables", "nftables"],
}
# docs/advanced/arch.md 호환표 : arm64 단독 클러스터에서 Y 인 CNI
ARCH_CNI = {"amd64": set(ALLOWED["kube_network_plugin"]), "arm64": {"calico", "cilium"}}

SCHEMA = {   # enum 으로 1차 제한 → 모델이 없는 값을 지어내지 못함
    "type": "object",
    "properties": {
        **{k: {"type": "string", "enum": v} for k, v in ALLOWED.items()},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": [*ALLOWED, "reasons"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--req", required=True, help="요구사항 한 문장")
    ap.add_argument("--arch", choices=list(ARCH_CNI), default="arm64")
    ap.add_argument("--pages", nargs="+", required=True, help="근거로 쓸 위키 페이지 (예: concepts/cilium)")
    ap.add_argument("--out", required=True, help="kubespray inventory 폴더 (예: inventory/lima)")
    a = ap.parse_args()

    ctx = []
    for ref in a.pages:
        p = WIKI / f"{ref}.md"
        if not p.exists():
            sys.exit(f"위키에 없는 페이지 : {ref} → 먼저 ingest 할 것")
        ctx.append(f"### [[{ref}]]\n{p.read_text(encoding='utf-8')}")

    r = ollama.chat(model=MODEL, format=SCHEMA, options=OPTS, messages=[
        {"role": "system", "content": "주어진 위키 페이지만 근거로 kubespray 변수를 고름. 근거는 [[경로]] 를 붙여 한국어로."},
        {"role": "user", "content": f"요구사항: {a.req}\nCPU 아키텍처: {a.arch}\n\n" + "\n\n".join(ctx)}])
    j = json.loads(r["message"]["content"])

    # ── 코드 검증 : 스키마가 막지 못한 조합 규칙은 여기서 막음 ──
    errs = [f"{k}={j.get(k)} 는 허용값 아님" for k, v in ALLOWED.items() if j.get(k) not in v]
    if j.get("kube_network_plugin") not in ARCH_CNI[a.arch]:
        errs.append(f"{a.arch} 에서 {j.get('kube_network_plugin')} 미지원 (docs/advanced/arch.md)")
    if errs:
        sys.exit("거부 : " + " / ".join(errs))

    out = Path(a.out).expanduser() / "group_vars" / "k8s_cluster" / "zz-llm.yml"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = [f"# gen_vars.py {dt.date.today()} | model={MODEL} | arch={a.arch}", f"# 요구사항 : {a.req}"]
    body += [f"# 근거 : {x}" for x in j["reasons"]]
    body += [f"{k}: {j[k]}" for k in ALLOWED]
    out.write_text("\n".join(body) + "\n", encoding="utf-8")       # zz- 접두어 → 같은 폴더 다른 파일보다 나중에 읽힘

    log = WIKI / "log.md"
    if log.exists():
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"## [{dt.date.today()}] gen_vars | {a.req}\n")
    print(out.read_text(encoding="utf-8"))
    print(f"저장 : {out}\n다음 : ansible-inventory -i {Path(a.out) / 'inventory.ini'} --graph 로 확인 후 사람이 cluster.yml 실행")


if __name__ == "__main__":
    main()
