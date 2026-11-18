#!/usr/bin/env python3
"""Lake 현행 상태 일괄 점검 → 레포트 (Markdown · CSV · JSON)

Y1 제안서 항목 기준으로 K8s 노드 · 클러스터 상태를 수집하고 값마다 판정 · 해석을 붙인다.
N9K(NW) 항목은 명령과 해석만 제공 (수동).

  sudo python3 lake_check.py                         # 이 노드 + 클러스터
  sudo python3 lake_check.py --out /tmp/lake-report  # 결과 위치
  sudo python3 lake_check.py --storage-selector node-role=storage --bonds bond0,bond1

Python 3.6+ 표준 라이브러리만 사용. kubectl(admin.conf) 또는 crictl 중 하나가 있으면 Cilium 값을 읽음.
판정 : 충족(Y1 권장 충족) · 유지(I Lake 그대로 유지, 정상) · 개선(Y1 개선 대상) · 확인(값 확인 필요) · NA(수집 불가) · 수동(NW)
"""
import argparse
import csv
import datetime
import glob
import json
import os
import re
import shutil
import socket
import subprocess

VERDICTS = ["개선", "확인", "충족", "유지", "NA", "수동"]


# ------------------------------------------------------------------ 실행 도구
def run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                           universal_newlines=True)
        return p.returncode, p.stdout.strip()
    except Exception as e:  # noqa
        return 1, str(e)


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def num(v, default=None):
    try:
        return float(str(v).strip().rstrip("*"))
    except Exception:
        return default


class Ctx:
    """수집 결과 캐시 (명령은 한 번만 실행)."""

    def __init__(self, args):
        self.a = args
        self.ns = args.ns
        self.bonds = [b for b in args.bonds.split(",") if b]
        self.host = socket.gethostname()
        self._c = {}
        kc = args.kubeconfig or os.environ.get("KUBECONFIG") or ("/etc/kubernetes/admin.conf" if os.path.exists("/etc/kubernetes/admin.conf") else "")
        self.kubectl = None
        if shutil.which("kubectl"):
            self.kubectl = "kubectl" + (f" --kubeconfig {kc}" if kc else "")
            if run(f"{self.kubectl} version --request-timeout=5s -o json", 10)[0] != 0:
                self.kubectl = None

    def cache(self, key, fn):
        if key not in self._c:
            try:
                self._c[key] = fn()
            except Exception:
                self._c[key] = None
        return self._c[key]

    # -------- kubectl
    def kjson(self, args):
        if not self.kubectl:
            return None
        return self.cache("k:" + args, lambda: json.loads(run(f"{self.kubectl} {args} -o json", 30)[1]))

    def node_name(self):
        def f():
            nodes = self.kjson("get nodes") or {}
            names = [n["metadata"]["name"] for n in nodes.get("items", [])]
            for cand in (self.host, self.host.split(".")[0]):
                if cand in names:
                    return cand
            return self.host
        return self.cache("node", f)

    def cilium_pod(self):
        def f():
            pods = self.kjson(f"-n {self.ns} get pods -l k8s-app=cilium --field-selector spec.nodeName={self.node_name()}") or {}
            items = pods.get("items", [])
            return items[0]["metadata"]["name"] if items else None
        return self.cache("cpod", f)

    def cilium(self, sub):
        """cilium-dbg 실행 : kubectl exec → crictl exec 순."""
        def f():
            if self.kubectl and self.cilium_pod():
                rc, out = run(f"{self.kubectl} -n {self.ns} exec {self.cilium_pod()} -c cilium-agent -- cilium-dbg {sub}", 40)
                if rc == 0:
                    return out
            if shutil.which("crictl"):
                rc, cid = run("crictl ps --name cilium-agent -q | head -1")
                if rc == 0 and cid:
                    rc, out = run(f"crictl exec {cid} cilium-dbg {sub}", 40)
                    if rc == 0:
                        return out
            return None
        return self.cache("c:" + sub, f)

    def cfg(self, key, default=None):
        """cilium-config 값. 없으면 기본값 + '*'."""
        def f():
            cm = self.kjson(f"-n {self.ns} get configmap cilium-config")
            if cm:
                return cm.get("data", {})
            out = self.cilium("config -a") or ""
            d = {}
            for line in out.splitlines():
                m = re.match(r"^\s*([\w-]+)\s*[:=]\s*(.*)$", line)
                if m:
                    d[m.group(1)] = m.group(2).strip()
            return d or None
        data = self.cache("cfg", f)
        if data is None:
            return None
        if key in data:
            return data[key]
        return None if default is None else f"{default}*"

    def status(self, pattern):
        out = self.cilium("status --verbose")
        if not out:
            return None
        m = re.search(pattern, out, re.I | re.M)
        return m.group(1).strip() if m else None

    def svcs(self):
        d = self.kjson("get svc -A") or {}
        return d.get("items", []) if d else None

    def bond(self, b):
        return read(f"/proc/net/bonding/{b}")

    def bond_field(self, field):
        vals = []
        for b in self.bonds:
            t = self.bond(b)
            if t is None:          # 없는 bond 는 건너뜀 (모두 없으면 NA)
                continue
            m = re.search(rf"^{field}:\s*(.+)$", t, re.M)
            vals.append(f"{b}={m.group(1).strip() if m else '?'}")
        return ",".join(vals) or None

    def sysctl(self, k):
        return read("/proc/sys/" + k.replace(".", "/"))


# ------------------------------------------------------------------ 판정 도우미
def every(v, pred):
    """'a=x,b=y' 형식 값이 모두 pred 를 만족하는지."""
    parts = [p.split("=", 1)[-1] for p in str(v).split(",") if p]
    return bool(parts) and all(pred(p) for p in parts)


def is_true(v):
    return str(v).rstrip("*").lower() in ("true", "enabled", "1", "yes")


# ------------------------------------------------------------------ 점검 항목 (시트와 공유하는 단일 원본)
# rules : [(값 조건, 판정, 해석)] — judge(value) 가 rules 의 번호를 돌려줌
def I(id, area, ch, item, target, cmd, y1, rules, get=None, judge=None):
    return dict(id=id, area=area, ch=ch, item=item, target=target, cmd=cmd, y1=y1, rules=rules, get=get, judge=judge)


def by_bool(true_idx=0, false_idx=1):
    return lambda v: true_idx if is_true(v) else false_idx


def by_min(th, ok=0, bad=1):
    return lambda v: ok if (num(v) is not None and num(v) >= th) else bad


def by_in(*groups):
    """groups : 값 목록들. 해당 그룹 번호, 없으면 마지막 규칙."""
    def j(v):
        s = str(v).rstrip("*").lower()
        for i, g in enumerate(groups):
            if s in g:
                return i
        return len(groups)
    return j


def count_svc(ctx, pred):
    items = ctx.svcs()
    if items is None:
        return None
    hit = [f"{s['metadata']['namespace']}/{s['metadata']['name']}" for s in items if pred(s)]
    return f"{len(hit)}" + (f" ({', '.join(hit[:8])}{' …' if len(hit) > 8 else ''})" if hit else "")


def first_int(v):
    m = re.match(r"\s*(\d+)", str(v))
    return int(m.group(1)) if m else None


def bond_mtu(ctx):
    return ",".join(f"{b}={read(f'/sys/class/net/{b}/mtu')}" for b in ctx.bonds if read(f"/sys/class/net/{b}/mtu")) or None


def bond_slaves(ctx):
    out = []
    for b in ctx.bonds:
        s = read(f"/sys/class/net/{b}/bonding/slaves")
        out += s.split() if s else []
    return out


def nic_queues(ctx):
    res = []
    for n in bond_slaves(ctx):
        rc, o = run(f"ethtool -l {n} 2>/dev/null")
        cur = re.findall(r"Combined:\s*(\d+)", o)
        q = cur[-1] if cur else "?"
        node = read(f"/sys/class/net/{n}/device/numa_node") or "?"
        cpus = read(f"/sys/class/net/{n}/device/local_cpulist") or ""
        ncpu = 0
        for part in cpus.split(","):
            if "-" in part:
                a, b = part.split("-")
                ncpu += int(b) - int(a) + 1
            elif part.strip():
                ncpu += 1
        res.append(f"{n}={q}@n{node}({ncpu})")
    return ",".join(res) if res else None


def nic_drivers(ctx):
    out = []
    for n in bond_slaves(ctx):
        m = re.search(r"driver:\s*(\S+)", run("ethtool -i " + n)[1])
        out.append(n + "=" + (m.group(1) if m else "?"))
    return ",".join(out) or None


def bond_members_up(ctx):
    out = []
    for b in ctx.bonds:
        t = ctx.bond(b)
        if t:
            up = len(re.findall(r"Slave Interface:.*\n\s*MII Status:\s*up", t))
            out.append(b + "=" + str(up))
    return ",".join(out) or None


def judge_queues(v):
    ok = True
    for p in str(v).split(","):
        m = re.search(r"=(\d+)@n[^()]*\((\d+)\)", p)
        if not m:
            return 2
        q, c = int(m.group(1)), int(m.group(2))
        if c and q > c:
            ok = False
    return 0 if ok else 1


def rack_counts(ctx):
    nodes = ctx.kjson("get nodes" + (f" -l {ctx.a.storage_selector}" if ctx.a.storage_selector else ""))
    if not nodes:
        return None
    cnt = {}
    for n in nodes.get("items", []):
        r = n["metadata"].get("labels", {}).get(ctx.a.rack_label, "(없음)")
        cnt[r] = cnt.get(r, 0) + 1
    return ",".join(f"{k}={v}" for k, v in sorted(cnt.items()))


def judge_rack(v):
    vals = [int(p.split("=")[1]) for p in str(v).split(",") if "=" in p]
    if any(p.startswith("(없음)") for p in str(v).split(",")):
        return 2
    return 0 if vals and max(vals) == min(vals) else 1


def bgp_peers(ctx):
    out = ctx.cilium("bgp peers")
    if not out:
        return None
    lines = [l for l in out.splitlines()[1:] if l.strip()]
    est = sum(1 for l in lines if re.search(r"established", l, re.I))
    asns = sorted(set(l.split()[0] for l in lines if l.split() and l.split()[0].isdigit()))
    return f"{est}/{len(lines)} established, local AS {' '.join(asns)}"


def bgp_timers(ctx):
    d = ctx.kjson("get ciliumbgppeerconfigs -A")
    if not d:
        return None
    vals = set()
    for it in d.get("items", []):
        sp = it.get("spec", {})
        t = sp.get("timers", {})
        gr = sp.get("gracefulRestart", {})
        vals.add(f"{t.get('holdTimeSeconds', 90)}/{t.get('keepAliveTimeSeconds', 30)}/GR{gr.get('restartTimeSeconds', 120) if gr.get('enabled') else '-'}")
    return " ".join(sorted(vals)) if vals else "0개"


def cm_replicas(ctx):
    d = ctx.kjson(f"-n {ctx.ns} get deploy clustermesh-apiserver")
    if not d:
        return None
    cs = [c["name"] for c in d["spec"]["template"]["spec"].get("containers", [])]
    return f"replicas={d['spec'].get('replicas', 1)},kvstoremesh={'yes' if any('kvstoremesh' in c for c in cs) else 'no'}"


NA = ("수집 불가", "NA", "kubectl · crictl · 권한 확인 후 재실행")

CATALOG = [
    # ---------------- 4장 L4 LB
    I("L01", "L4 LB", "4", "kube-proxy 대체 (KPR)", "cluster", "cilium-config : kube-proxy-replacement", "true",
      [("true", "유지", "kube-proxy 없이 eBPF LB (I Lake 유지)"), ("false · partial", "확인", "kube-proxy 병행 · eBPF LB 기능 일부 미사용")],
      lambda c: c.cfg("kube-proxy-replacement", "false"), by_bool()),
    I("L02", "L4 LB", "4", "라우팅 모드", "cluster", "cilium-config : routing-mode", "native",
      [("native", "유지", "BGP native routing (I Lake 유지)"), ("tunnel", "확인", "오버레이 사용 · 설계(native) 와 다름")],
      lambda c: c.cfg("routing-mode", "tunnel"), by_in(("native",))),
    I("L03", "L4 LB", "4", "전역 LB 알고리즘", "cluster", "cilium-config : bpf-lb-algorithm", "random (AIStor VIP 만 Maglev)",
      [("random", "유지", "전역 random 유지, AIStor VIP 는 annotation 으로 Maglev"), ("maglev", "확인", "전역 Maglev : 모든 Service 가 Maglev 표 유지 (메모리 · 갱신 비용)")],
      lambda c: c.cfg("bpf-lb-algorithm", "random"), by_in(("random",))),
    I("L04", "L4 LB", "4", "Service 별 알고리즘 지정", "cluster", "cilium-config : bpf-lb-algorithm-annotation", "true",
      [("true", "충족", "Service annotation 으로 Maglev 지정 가능"), ("false · 없음", "개선", "Service 별 Maglev 지정 불가 → P2 에서 true")],
      lambda c: c.cfg("bpf-lb-algorithm-annotation", "false"), by_bool()),
    I("L05", "L4 LB", "4", "Maglev 지정 Service 수", "cluster", "kubectl get svc -A -o json | annotation service.cilium.io/lb-algorithm=maglev", "AIStor VIP ≥ 1",
      [("1 이상", "충족", "목록에 AIStor VIP 가 있으면 Maglev 적용"), ("0", "개선", "AIStor VIP random → 경로 · 노드 변경 시 연결 끊김")],
      lambda c: count_svc(c, lambda s: s["metadata"].get("annotations", {}).get("service.cilium.io/lb-algorithm") == "maglev"),
      lambda v: 0 if (first_int(v) or 0) >= 1 else 1),
    I("L06", "L4 LB", "4", "LB 응답 방식", "cluster", "cilium-config : bpf-lb-mode", "dsr",
      [("dsr", "충족", "응답이 Pod 노드에서 직접, client IP 보존"), ("snat", "개선", "응답이 인입 노드 경유 · client IP 미보존 → P3 DSR (PoC)"), ("hybrid", "확인", "TCP DSR · UDP SNAT")],
      lambda c: c.cfg("bpf-lb-mode", "snat"), by_in(("dsr",), ("snat",))),
    I("L07", "L4 LB", "4", "DSR 전달 방식", "cluster", "cilium-config : bpf-lb-dsr-dispatch", "geneve",
      [("geneve", "충족", "DSR 정보를 Geneve 로 전달"), ("opt · ipip · 기본", "개선", "DSR 도입 시 Geneve 로 (IP 옵션은 중간 장비 영향)")],
      lambda c: c.cfg("bpf-lb-dsr-dispatch", "opt"), by_in(("geneve",))),
    I("L08", "L4 LB", "4", "터널 프로토콜 (DSR 전달용)", "cluster", "cilium-config : tunnel-protocol", "geneve",
      [("geneve", "충족", "DSR Geneve 전달 가능"), ("vxlan · 기본", "개선", "DSR Geneve 도입 시 geneve 필요 (routing-mode 는 native 유지)")],
      lambda c: c.cfg("tunnel-protocol", "vxlan"), by_in(("geneve",))),
    I("L09", "L4 LB", "4", "XDP 가속", "cluster", "cilium-config : bpf-lb-acceleration", "best-effort",
      [("best-effort · native", "유지", "XDP 가속 (I Lake 유지)"), ("disabled", "확인", "XDP 미사용 → tc 단계 처리")],
      lambda c: c.cfg("bpf-lb-acceleration", "disabled"), by_in(("best-effort", "native"))),
    I("L10", "L4 LB", "4", "소켓 LB (내부 경로)", "node", "cilium-dbg status --verbose : Socket LB", "Enabled",
      [("Enabled", "충족", "connect() 시 백엔드로 직결, 패킷 NAT 없음"), ("Disabled", "개선", "내부 경로 패킷마다 NAT · conntrack → 끈 이유 확인 후 on")],
      lambda c: c.status(r"^\s*Socket LB:\s*(\w+)") or c.cfg("bpf-lb-sock", "false"), by_bool()),
    I("L11", "L4 LB", "4", "LB 맵 크기", "cluster", "cilium-config : bpf-lb-map-max", "131072 이상",
      [("131072 이상", "충족", "대량 연결 여유"), ("65536 (기본)", "개선", "맵 포화 시 신규 연결 drop 가능 → 상향")],
      lambda c: c.cfg("bpf-lb-map-max", "65536"), by_min(131072)),
    I("L12", "L4 LB", "4", "동적 맵 비율", "cluster", "cilium-config : bpf-map-dynamic-size-ratio", "0.005 이상",
      [("0.005 이상", "충족", "CT · NAT 맵 여유"), ("0.0025 (기본)", "개선", "CT 맵 여유 부족 가능 → 상향")],
      lambda c: c.cfg("bpf-map-dynamic-size-ratio", "0.0025"), by_min(0.005)),
    I("L13", "L4 LB", "4", "eTP Local LoadBalancer Service", "cluster", "kubectl get svc -A -o json | type=LoadBalancer · externalTrafficPolicy=Local", "AIStor VIP 는 0",
      [("0", "충족", "인입 쏠림이 처리 쏠림으로 이어지지 않음"), ("1 이상", "확인", "목록 중 AIStor VIP 가 있으면 Cluster 전환 대상 (불균형 직접 원인 후보)")],
      lambda c: count_svc(c, lambda s: s["spec"].get("type") == "LoadBalancer" and s["spec"].get("externalTrafficPolicy") == "Local"),
      lambda v: 0 if first_int(v) == 0 else 1),
    I("L14", "L4 LB", "4", "sessionAffinity ClientIP", "cluster", "kubectl get svc -A -o json | sessionAffinity=ClientIP", "0",
      [("0", "유지", "분산 방해 설정 없음"), ("1 이상", "확인", "같은 client 가 한 Pod 에 고정 → 대상 확인")],
      lambda c: count_svc(c, lambda s: s["spec"].get("sessionAffinity") == "ClientIP"),
      lambda v: 0 if first_int(v) == 0 else 1),
    I("L15", "L4 LB", "4 · 7", "Global Service · affinity", "cluster", "kubectl get svc -A -o json | service.cilium.io/global · affinity", "global 사용 · affinity 의도 확인",
      [("affinity 없음", "유지", "Global Service 백엔드 전체 사용"), ("affinity 있음", "확인", "local · remote 우선 → 의도 확인 (괄호 안 Service)")],
      lambda c: count_svc(c, lambda s: bool(s["metadata"].get("annotations", {}).get("service.cilium.io/affinity"))),
      lambda v: 0 if first_int(v) == 0 else 1),
    I("L16", "L4 LB", "5", "LB IP 풀 수", "cluster", "kubectl get ciliumloadbalancerippools", "2 이상 (PUBLIC · PRIVATE)",
      [("2 이상", "유지", "PUBLIC · PRIVATE 분리 (I Lake 유지)"), ("0 · 1", "확인", "VIP 대역 분리 여부 확인")],
      lambda c: str(len((c.kjson("get ciliumloadbalancerippools") or {}).get("items", []))) if c.kubectl else None, by_min(2)),
    I("L17", "L4 LB", "5", "L2 announcement 정책", "cluster", "kubectl get ciliuml2announcementpolicies", "0 (BGP 광고)",
      [("0", "유지", "VIP 는 BGP 로 광고 (I Lake 유지)"), ("1 이상", "확인", "L2 광고 병행 → 대상 확인")],
      lambda c: str(len((c.kjson("get ciliuml2announcementpolicies") or {}).get("items", []))) if c.kubectl else None,
      lambda v: 0 if first_int(v) == 0 else 1),
    # ---------------- 3 · 6장 노드
    I("N01", "노드", "6", "Pod 장치", "cluster", "cilium-config : datapath-mode", "netkit",
      [("netkit · netkit-l2", "유지", "netkit (I Lake 유지)"), ("veth", "확인", "veth 사용 → netkit 대비 지연 · CPU")],
      lambda c: c.cfg("datapath-mode", "veth"), by_in(("netkit", "netkit-l2"))),
    I("N02", "노드", "6", "host routing", "node", "cilium-dbg status --verbose : Host Routing", "BPF",
      [("BPF", "유지", "eBPF host routing"), ("Legacy", "개선", "호스트 스택 · iptables 경유 → 커널 · 설정 확인")],
      lambda c: c.status(r"Host Routing:\s*(\w+)"), by_in(("bpf",))),
    I("N03", "노드", "6", "bond 모드", "node", "/proc/net/bonding/<bond> : Bonding Mode", "IEEE 802.3ad",
      [("모두 802.3ad", "유지", "LACP (I Lake 유지)"), ("그 외", "확인", "bond 모드 확인")],
      lambda c: c.bond_field("Bonding Mode"), lambda v: 0 if every(v, lambda p: "802.3ad" in p) else 1),
    I("N04", "노드", "6", "bond 송신 해시", "node", "/proc/net/bonding/<bond> : Transmit Hash Policy", "layer3+4",
      [("모두 layer3+4", "유지", "흐름별 분산 (I Lake 유지)"), ("layer2 등", "개선", "흐름 분산 부족 → layer3+4")],
      lambda c: c.bond_field("Transmit Hash Policy"), lambda v: 0 if every(v, lambda p: p.startswith("layer3+4")) else 1),
    I("N05", "노드", "3 · 6", "LACP rate", "node", "/proc/net/bonding/<bond> : LACP rate", "fast",
      [("모두 fast", "충족", "멤버 장애 3초 내 감지"), ("slow", "개선", "링크 유지 장애 감지 최대 90초 → fast (스위치 쪽도)")],
      lambda c: c.bond_field("LACP rate"), lambda v: 0 if every(v, lambda p: p == "fast") else 1),
    I("N06", "노드", "3", "miimon", "node", "/proc/net/bonding/<bond> : MII Polling Interval (ms)", "100",
      [("100 이하 · 0 아님", "유지", "링크 down 즉시 감지"), ("0", "개선", "링크 감시 꺼짐")],
      lambda c: c.bond_field("MII Polling Interval \\(ms\\)"), lambda v: 0 if every(v, lambda p: 0 < (num(p, 0) or 0) <= 100) else 1),
    I("N07", "노드", "6", "bond MTU", "node", "cat /sys/class/net/<bond>/mtu", "9000",
      [("모두 9000", "충족", "점보 프레임 · DSR Geneve 여유"), ("1500 등", "개선", "패킷 수 증가 · DSR 전제 미충족 → 패브릭 9216 후 9000")],
      bond_mtu, lambda v: 0 if every(v, lambda p: num(p, 0) >= 9000) else 1),
    I("N08", "노드", "6", "Cilium devices 지정", "cluster", "cilium-config : devices", "bond0 bond1",
      [("bond 명시", "충족", "장치 고정 · 노드 간 일관"), ("미지정 (자동)", "개선", "자동 감지 → 노드별 차이 가능")],
      lambda c: c.cfg("devices", "auto"), lambda v: 0 if "bond" in str(v) else 1),
    I("N09", "노드", "6", "TCP 혼잡 제어", "node", "sysctl net.ipv4.tcp_congestion_control", "bbr",
      [("bbr", "충족", "100G · 짧은 RTT 대역 활용"), ("cubic 등", "개선", "손실 기반 → 재전송 · 큐 적체")],
      lambda c: c.sysctl("net.ipv4.tcp_congestion_control"), by_in(("bbr",))),
    I("N10", "노드", "6", "기본 qdisc", "node", "sysctl net.core.default_qdisc", "fq",
      [("fq", "충족", "BBR pacing"), ("fq_codel 등", "개선", "BBR 사용 시 fq 필요")],
      lambda c: c.sysctl("net.core.default_qdisc"), by_in(("fq",))),
    I("N11", "노드", "6", "소켓 버퍼 최대", "node", "sysctl net.core.rmem_max · wmem_max", "134217728 이상",
      [("둘 다 128M 이상", "충족", "100G 다중 흐름 여유"), ("그 미만", "개선", "버스트 시 처리량 제한")],
      lambda c: f"rmem={c.sysctl('net.core.rmem_max')},wmem={c.sysctl('net.core.wmem_max')}",
      lambda v: 0 if every(v, lambda p: (num(p, 0) or 0) >= 134217728) else 1),
    I("N12", "노드", "6", "netdev backlog", "node", "sysctl net.core.netdev_max_backlog", "250000 이상",
      [("250000 이상", "충족", "버스트 수신 여유"), ("그 미만", "개선", "softnet drop 가능")],
      lambda c: c.sysctl("net.core.netdev_max_backlog"), by_min(250000)),
    I("N13", "노드", "6", "tuned 프로파일", "node", "tuned-adm active", "network-throughput",
      [("network-throughput · latency-performance", "충족", "CPU 절전 · 지연 편차 감소"), ("없음 · 기타", "개선", "기본 절전 상태")],
      lambda c: (run("tuned-adm active 2>/dev/null")[1].split(":")[-1].strip() or "none") if shutil.which("tuned-adm") else "none",
      by_in(("network-throughput", "latency-performance"))),
    I("N14", "노드", "6", "irqbalance", "node", "systemctl is-active irqbalance", "inactive (NIC IRQ 고정)",
      [("inactive", "충족", "IRQ 고정 유지"), ("active", "개선", "NIC IRQ 가 계속 이동 → NIC 제외 또는 중지 후 NUMA 고정")],
      lambda c: run("systemctl is-active irqbalance 2>/dev/null")[1] or "unknown", by_in(("inactive", "unknown", "failed"))),
    I("N15", "노드", "6", "NIC 큐 · NUMA", "node", "ethtool -l <nic> · /sys/class/net/<nic>/device/{numa_node,local_cpulist}", "큐 수 ≤ 로컬 NUMA 코어 수",
      [("큐 ≤ 로컬 코어", "충족", "원격 NUMA 처리 없음"), ("큐 > 로컬 코어", "개선", "일부 큐가 원격 NUMA 에서 처리 → 큐 수 조정 · IRQ 고정"), ("수집 불가", "확인", "ethtool · sysfs 확인")],
      nic_queues, judge_queues),
    I("N16", "노드", "6", "Bandwidth Manager", "cluster", "cilium-config : enable-bandwidth-manager", "true",
      [("true", "충족", "Pod 송신 pacing (EDT)"), ("false", "개선", "Pod 단위 pacing 없음")],
      lambda c: c.cfg("enable-bandwidth-manager", "false"), by_bool()),
    I("N17", "노드", "6", "Cilium BBR", "cluster", "cilium-config : enable-bbr", "true",
      [("true", "충족", "Pod 에 BBR 적용"), ("false", "개선", "Pod 은 노드 기본 혼잡 제어")],
      lambda c: c.cfg("enable-bbr", "false"), by_bool()),
    I("N18", "노드", "6", "BIG TCP", "cluster", "cilium-config : enable-ipv4-big-tcp", "PoC 후 결정",
      [("true", "충족", "GSO · GRO 확대"), ("false", "확인", "ice NIC 지원 → PoC 대상")],
      lambda c: c.cfg("enable-ipv4-big-tcp", "false"), by_bool()),
    I("N19", "노드", "6", "NIC 드라이버", "node", "ethtool -i <nic>", "ice (참고)",
      [("수집됨", "유지", "드라이버 · 펌웨어 기록 (I Lake 유지)")],
      nic_drivers,
      lambda v: 0),
    I("N20", "노드", "6", "rp_filter", "node", "sysctl net.ipv4.conf.{all,default}.rp_filter", "0 또는 2",
      [("0 · 2", "유지", "비대칭 응답 허용"), ("1", "확인", "strict → 비대칭 경로 drop 가능")],
      lambda c: f"all={c.sysctl('net.ipv4.conf.all.rp_filter')},default={c.sysctl('net.ipv4.conf.default.rp_filter')}",
      lambda v: 0 if every(v, lambda p: p in ("0", "2")) else 1),
    I("N21", "노드", "6", "bond 멤버 상태", "node", "/proc/net/bonding/<bond> : Slave · MII Status", "bond 마다 멤버 2개 up",
      [("모두 2개 이상 up", "유지", "이중화 정상"), ("1개 이하", "확인", "멤버 장애 · 구성 확인")],
      bond_members_up,
      lambda v: 0 if every(v, lambda p: (num(p, 0) or 0) >= 2) else 1),
    # ---------------- 1 · 2 · 7장 클러스터
    I("K01", "클러스터", "7", "IPAM 모드", "cluster", "cilium-config : ipam", "multi-pool",
      [("multi-pool", "유지", "I Lake 유지"), ("그 외", "확인", "클러스터 간 풀 비중복 확인")],
      lambda c: c.cfg("ipam", "cluster-pool"), by_in(("multi-pool",))),
    I("K02", "클러스터", "7", "cluster-name · id", "cluster", "cilium-config : cluster-name · cluster-id", "클러스터별 고유",
      [("기록", "유지", "다른 클러스터와 중복 없는지 대조")],
      lambda c: f"name={c.cfg('cluster-name', 'default')},id={c.cfg('cluster-id', '0')}" if c.cfg("cluster-name", "default") is not None else None,
      lambda v: 0),
    I("K03", "클러스터", "7", "Cilium 버전", "node", "cilium-dbg version", "클러스터 간 patch 정렬",
      [("기록", "확인", "Compute · GPU · Storage 버전 대조")],
      lambda c: (re.search(r"(\d+\.\d+\.\d+\S*)", c.cilium("version") or "") or [None, None])[1], lambda v: 0),
    I("K04", "클러스터", "7", "ClusterMesh 원격", "node", "cilium-dbg status : ClusterMesh", "원격 전부 ready",
      [("전부 ready", "유지", "원격 클러스터 연동 정상"), ("일부 · 0", "확인", "원격 연결 · 인증서 확인")],
      lambda c: c.status(r"ClusterMesh:\s*(.+)$"),
      lambda v: 0 if (lambda m: m and m.group(1) == m.group(2) and m.group(1) != "0")(re.search(r"(\d+)/(\d+)", str(v))) else 1),
    I("K05", "클러스터", "7", "clustermesh-apiserver · KVStoreMesh", "cluster", f"kubectl -n <ns> get deploy clustermesh-apiserver", "replicas ≥ 2 · kvstoremesh=yes",
      [("둘 다 충족", "충족", "이중화 · 캐시"), ("replica 1 또는 kvstoremesh 없음", "개선", "apiserver 단일 장애점 · 노드별 원격 직접 연결"), ("없음", "확인", "ClusterMesh 미사용 또는 이름 다름")],
      cm_replicas,
      lambda v: 2 if v is None else (0 if (num(re.search(r"replicas=(\d+)", v).group(1), 1) >= 2 and "kvstoremesh=yes" in v) else 1)),
    I("K06", "클러스터", "7", "Hubble", "cluster", "cilium-config : enable-hubble", "true",
      [("true", "유지", "관측 (I Lake 유지)"), ("false", "확인", "흐름 관측 불가")],
      lambda c: c.cfg("enable-hubble", "false"), by_bool()),
    I("K07", "클러스터", "7", "WireGuard", "cluster", "cilium-config : enable-wireguard", "false",
      [("false", "유지", "암호화 오버헤드 없음 (I Lake 유지)"), ("true", "확인", "100G 처리량 영향 확인")],
      lambda c: c.cfg("enable-wireguard", "false"), by_bool(1, 0)),
    I("K08", "클러스터", "1", "랙별 노드 수", "cluster", "kubectl get nodes -L <rack 라벨> [-l <storage 셀렉터>]", "랙마다 같은 수",
      [("모두 같음", "충족", "랙(VTEP) 단위 분산 = 노드 단위 분산"), ("다름", "개선", "서버 적은 랙의 노드가 더 많이 받음 → 랙 균등 · export-gateway-ip"), ("rack 라벨 없음", "확인", "라벨 · 셀렉터 확인")],
      rack_counts, judge_rack),
    I("K09", "클러스터", "2 · 5", "BGP 세션", "node", "cilium-dbg bgp peers", "전부 established, bond0 · bond1 세션",
      [("전부 established", "유지", "세션 정상 · local AS 로 bond 매핑 대조"), ("일부", "확인", "down 세션 확인")],
      bgp_peers, lambda v: 0 if (lambda m: m and m.group(1) == m.group(2))(re.match(r"(\d+)/(\d+)", str(v))) else 1),
    I("K10", "클러스터", "3", "BGP 타이머 · GR", "cluster", "kubectl get ciliumbgppeerconfigs -A -o json : timers · gracefulRestart", "12/4/GR15",
      [("12/4/GR15", "유지", "I Lake 튜닝값 유지"), ("그 외", "확인", "hold · keepalive · GR 값 대조")],
      bgp_timers, lambda v: 0 if str(v).strip() == "12/4/GR15" else 1),
    I("K11", "클러스터", "5", "BGP 광고 prefix", "node", "cilium-dbg bgp routes advertised ipv4 unicast", "PUBLIC VIP → bond0, PodCIDR · PRIVATE VIP → bond1",
      [("기록", "확인", "인스턴스(AS) 별 광고 대상이 bond 매핑과 맞는지 대조")],
      lambda c: (lambda o: f"{len([l for l in o.splitlines()[1:] if l.strip()])}개" if o else None)(c.cilium("bgp routes advertised ipv4 unicast")),
      lambda v: 0),
]

NW = [
    ("W01", "고유 RD", "2", "show bgp l2vpn evpn <VIP>", "leaf 수만큼 RD 별 경로", [("leaf 수만큼", "충족", "RR 이 경로를 모두 반사"), ("1개", "개선", "RD 중복 → RR 이 1개만 반사")]),
    ("W02", "maximum-paths", "2 · 3", "show run bgp | include maximum-paths", "≥ V (ibgp 포함)", [("≥ V", "충족", "VTEP 전부 설치"), ("< V · 없음", "개선", "설치 경로 수 제한")]),
    ("W03", "multipath-relax", "3", "show run bgp | include bestpath", "as-path multipath-relax", [("있음", "충족", "AS-path 다른 경로 multipath"), ("없음", "개선", "랙별 ASN 차이로 경로 탈락")]),
    ("W04", "igp-metric ignore", "3", "show run bgp | include bestpath", "igp-metric ignore", [("있음", "유지", "I Lake 적용 완료"), ("없음", "개선", "가까운 VTEP 만 선택")]),
    ("W05", "Border VIP 경로 수", "2", "show ip route <VIP>/32 vrf PUBLIC", "next-hop V", [("V 와 같음", "충족", "Storage 랙 전부 사용"), ("V 보다 적음", "개선", "W01 ~ W03 원인 확인")]),
    ("W06", "resilient hashing", "3", "show run | include ecmp resilient", "적용", [("있음", "충족", "경로 이탈 시 약 1/n 만 이동"), ("없음", "개선", "경로 이탈 시 대부분 재해시")]),
    ("W07", "계층별 해시 seed", "3", "show ip load-sharing", "계층별 universal-id 상이", [("상이", "충족", "polarization 방지"), ("동일 · 기본", "확인", "업링크 편차 측정")]),
    ("W08", "BFD", "3", "show bfd neighbors", "300ms × 3", [("Up", "충족", "1초 내 감지"), ("없음", "확인", "BGP hold 시간까지 감지 지연")]),
    ("W09", "port-channel LACP rate", "3", "show lacp interface <멤버> | include rate", "fast", [("fast", "충족", "노드 쪽과 일치"), ("normal", "개선", "스위치 쪽 감지 90초")]),
    ("W10", "MTU", "6", "show interface <링크> | include MTU", "9216", [("9216", "충족", "노드 9000 + 헤더 여유"), ("1500 등", "개선", "노드 9000 적용 전 선행")]),
    ("W11", "uRPF", "4", "show run interface <노드 포트> | include urpf", "loose 또는 없음", [("loose · 없음", "충족", "DSR 응답 허용"), ("strict", "개선", "DSR 응답(src VIP) drop")]),
    ("W12", "export-gateway-ip", "1", "show bgp l2vpn evpn <VIP> | include Gateway", "GW IP = 노드 IP", [("있음", "충족", "노드 수 비례 분산"), ("없음", "확인", "랙 서버 수 균일이면 불필요")]),
]
for wid, item, ch, cmd, y1, rules in NW:
    CATALOG.append(I(wid, "NW (N9K)", ch, item, "nw", cmd, y1, rules))


# ------------------------------------------------------------------ 실행 · 레포트
def evaluate(ctx):
    res = []
    for it in CATALOG:
        r = dict(id=it["id"], area=it["area"], ch=it["ch"], item=it["item"], target=it["target"], cmd=it["cmd"], y1=it["y1"])
        if it["target"] == "nw":
            r.update(value="-", verdict="수동", meaning="N9K 에서 명령 실행 후 해석표 대조")
        elif (it["target"] == "cluster" and ctx.a.skip_cluster) or (it["target"] == "node" and ctx.a.skip_node):
            r.update(value="-", verdict="NA", meaning="건너뜀 (옵션)")
        else:
            try:
                v = it["get"](ctx)
            except Exception as e:  # noqa
                v = None
            if v is None or str(v).strip() in ("", "None"):
                r.update(value="-", verdict=NA[1], meaning=NA[2])
            else:
                try:
                    idx = it["judge"](v)
                    cond, verdict, meaning = it["rules"][min(idx, len(it["rules"]) - 1)]
                except Exception:
                    cond, verdict, meaning = ("", "확인", "판정 실패 · 값 직접 확인")
                r.update(value=str(v), verdict=verdict, meaning=meaning)
        res.append(r)
    return res


def write_reports(ctx, res, out):
    os.makedirs(out, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.join(out, f"lake-check-{ctx.host}-{ts}")
    cols = ["id", "area", "ch", "item", "target", "value", "verdict", "y1", "meaning", "cmd"]
    with open(base + ".csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in res:
            w.writerow({k: r.get(k, "") for k in cols})
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(dict(host=ctx.host, time=ts, kubectl=bool(ctx.kubectl), results=res), f, ensure_ascii=False, indent=2)

    cnt = {v: sum(1 for r in res if r["verdict"] == v) for v in VERDICTS}
    esc = lambda s: str(s).replace("|", "\\|")
    L = [f"# Lake 현행 상태 점검 레포트", "",
         f"| 항목 | 값 |", "|---|---|",
         f"| 노드 | {ctx.host} |", f"| 시각 | {ts} |",
         f"| kubectl | {'사용' if ctx.kubectl else '없음 (노드 항목만)'} |",
         f"| bond | {', '.join(ctx.bonds)} |", "",
         "## 요약", "", "| 판정 | 수 | 뜻 |", "|---|---|---|",
         f"| 개선 | {cnt['개선']} | Y1 에서 바꿀 대상 |",
         f"| 확인 | {cnt['확인']} | 값 · 의도 확인 필요 |",
         f"| 충족 | {cnt['충족']} | 이미 Y1 권장값 |",
         f"| 유지 | {cnt['유지']} | I Lake 그대로 유지 (정상) |",
         f"| NA | {cnt['NA']} | 수집 불가 · 건너뜀 |",
         f"| 수동 | {cnt['수동']} | N9K 수동 확인 |", ""]
    for title, keep in [("## 개선 대상", ("개선",)), ("## 확인 필요", ("확인",))]:
        rows = [r for r in res if r["verdict"] in keep]
        L += [title, ""]
        if not rows:
            L += ["없음", ""]
            continue
        L += ["| ID | 항목 | 현재 값 | Y1 권장 | 해석 | 제안 장 |", "|---|---|---|---|---|---|"]
        L += [f"| {r['id']} | {esc(r['item'])} | `{esc(r['value'])}` | {esc(r['y1'])} | {esc(r['meaning'])} | {r['ch']} |" for r in rows]
        L.append("")
    L += ["## 전체 결과", ""]
    for area in dict.fromkeys(r["area"] for r in res):
        L += [f"### {area}", "", "| ID | 항목 | 현재 값 | 판정 | 해석 |", "|---|---|---|---|---|"]
        L += [f"| {r['id']} | {esc(r['item'])} | `{esc(r['value'])}` | **{r['verdict']}** | {esc(r['meaning'])} |" for r in res if r["area"] == area]
        L.append("")
    L += ["## NW (N9K) 수동 확인 해석표", "", "| ID | 항목 | 명령 | 값 | 판정 | 해석 |", "|---|---|---|---|---|---|"]
    for it in CATALOG:
        if it["target"] == "nw":
            for cond, v, m in it["rules"]:
                L.append(f"| {it['id']} | {esc(it['item'])} | `{esc(it['cmd'])}` | {esc(cond)} | {v} | {esc(m)} |")
    L.append("")
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return base, cnt


def main():
    ap = argparse.ArgumentParser(description="Lake 현행 상태 일괄 점검 → 레포트")
    ap.add_argument("--out", default="./lake-check-report", help="레포트 디렉터리")
    ap.add_argument("--ns", default="kube-system", help="Cilium 네임스페이스")
    ap.add_argument("--bonds", default="bond0,bond1", help="점검할 bond (쉼표)")
    ap.add_argument("--kubeconfig", default="", help="kubeconfig (기본 : KUBECONFIG 또는 /etc/kubernetes/admin.conf)")
    ap.add_argument("--rack-label", default="rack", help="랙 라벨 키")
    ap.add_argument("--storage-selector", default="", help="랙별 대수를 셀 노드 셀렉터 (예 : node-role=storage)")
    ap.add_argument("--skip-cluster", action="store_true", help="클러스터 항목 건너뜀")
    ap.add_argument("--skip-node", action="store_true", help="노드 항목 건너뜀")
    ap.add_argument("--list", action="store_true", help="점검 항목만 출력")
    a = ap.parse_args()
    if a.list:
        for it in CATALOG:
            print(f"{it['id']}\t{it['area']}\t{it['item']}\t{it['cmd']}")
        return
    ctx = Ctx(a)
    res = evaluate(ctx)
    base, cnt = write_reports(ctx, res, a.out)
    w = max(len(r["item"]) for r in res)
    for r in res:
        if r["verdict"] != "수동":
            print(f"{r['id']:4} {r['verdict']:2}  {r['item']:<{w}}  {r['value']}")
    print("\n" + " · ".join(f"{k} {v}" for k, v in cnt.items()))
    print(f"레포트 : {base}.md  (.csv · .json)")


if __name__ == "__main__":
    main()
