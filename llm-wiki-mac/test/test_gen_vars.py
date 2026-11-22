"""gen_vars.py 를 가짜 ollama 로 검증 : 정상 저장 / arm64 비호환 CNI 거부 / 없는 페이지 거부"""
import os, subprocess, sys, tempfile, textwrap
from pathlib import Path

KIT = Path(sys.argv[1])
work = Path(tempfile.mkdtemp())
fake = work / "fakemods"; fake.mkdir()
(fake / "ollama.py").write_text(textwrap.dedent('''
    import json, os
    def chat(model, messages, format=None, options=None):
        cni = os.environ.get("FAKE_CNI", "cilium")
        assert format["properties"]["kube_network_plugin"]["enum"]
        return {"message": {"content": json.dumps({"kube_network_plugin": cni, "container_manager": "containerd",
            "kube_proxy_mode": "ipvs", "reasons": ["arm64 에서 Cilium Y [[sources/arch]]"]}, ensure_ascii=False)}}
'''), encoding="utf-8")
(work / "wiki" / "concepts").mkdir(parents=True); (work / "wiki" / "sources").mkdir()
(work / "wiki" / "concepts" / "cilium.md").write_text("# Cilium\n", encoding="utf-8")
(work / "wiki" / "sources" / "arch.md").write_text("# arch\n", encoding="utf-8")
(work / "wiki" / "log.md").write_text("", encoding="utf-8")

def run(extra_env=None, pages=("concepts/cilium", "sources/arch")):
    env = dict(os.environ, PYTHONPATH=str(fake), WIKI_ROOT=str(work), **(extra_env or {}))
    r = subprocess.run([sys.executable, str(KIT / "gen_vars.py"), "--req", "M1 VM 2대 Cilium 실습", "--arch", "arm64",
                        "--pages", *pages, "--out", str(work / "inv")], env=env, capture_output=True, text=True)
    print(f"(rc={r.returncode})\n{r.stdout}{r.stderr}")
    return r

assert run().returncode == 0
assert "kube_network_plugin: cilium" in (work / "inv/group_vars/k8s_cluster/zz-llm.yml").read_text(encoding="utf-8")
assert run({"FAKE_CNI": "flannel"}).returncode != 0          # arm64 + flannel 거부
assert run(pages=("concepts/없는것",)).returncode != 0         # 위키에 없는 근거 거부
assert "gen_vars" in (work / "wiki/log.md").read_text(encoding="utf-8")
print("ALL CHECKS PASSED")
