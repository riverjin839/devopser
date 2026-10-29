#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wu K8s 서비스 인벤토리 수집기

kubectl 이 설치된 master 노드에서 실행. 표준 라이브러리만 사용 (Python 3.6+).
클러스터에는 읽기(get/list)만 수행함.

수집 내용
  - 최상위 워크로드 (ownerReferences 를 끝까지 따라가 Operator CR 까지 해석)
  - 배포 경로 추정 (ArgoCD / Helm / kubectl / Operator / 단독 Pod)
  - 노출 (Ingress, HTTPRoute, LoadBalancer, NodePort) 과 ExternalName 의존성
  - ArgoCD Application (클러스터 안에 있으면), Missing 리소스
  - Helm 릴리즈 (helm 시크릿의 차트 이름·버전만 해석)
  - 담당자 단서 (owner/team 계열 label·annotation, 네임스페이스 RoleBinding)
  - ConfigMap 안의 I 지역 참조 (--ref-pattern 지정 시)
  - 네임스페이스 리소스 타입별 개수 (CRD 포함, --skip-resource-scan 으로 생략)

결과: 출력 디렉터리에 CSV(엑셀 호환 UTF-8 BOM) + summary.md, 콘솔에 서비스 목록
"""

import argparse
import base64
import csv
import datetime
import gzip
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import OrderedDict, defaultdict

VERSION = "1.0.0"

BUILTIN_WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "CronJob", "Job", "ReplicaSet", "Pod"}

# 서비스명으로 쓸 label 우선순위
NAME_LABELS = [
    "app.kubernetes.io/instance",
    "app.kubernetes.io/name",
    "app",
    "k8s-app",
    "release",
    "spark-app-name",
    "dag_id",
]

OWNER_KEY_RE = re.compile(r"(owner|team|maintainer|contact|manager|email|담당)", re.I)
KUBECTL_MANAGERS = ("kubectl", "kubectl-client-side-apply", "kubectl-create", "kubectl-edit",
                    "kubectl-patch", "kubectl-replace", "kubectl-set", "kubectl-scale",
                    "kubectl-rollout", "kubectl-label", "kubectl-annotate")


def log(msg):
    sys.stderr.write("[{}] {}\n".format(datetime.datetime.now().strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


# --------------------------------------------------------------------------- kubectl

class Kube(object):
    def __init__(self, kubectl, kubeconfig=None, context=None, timeout=300, chunk_size=500):
        self.base = [kubectl]
        if kubeconfig:
            self.base += ["--kubeconfig", kubeconfig]
        if context:
            self.base += ["--context", context]
        self.timeout = timeout
        self.chunk_size = chunk_size
        self.warnings = []

    def run(self, args):
        cmd = self.base + args
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            return 124, "", "timeout after {}s".format(self.timeout)
        except OSError as e:
            return 127, "", str(e)
        return p.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def items(self, resource, selector=None, optional=False, namespaced=True):
        args = ["get", resource, "-o", "json", "--chunk-size={}".format(self.chunk_size)]
        if namespaced:
            args.append("-A")
        if selector:
            args += ["-l", selector]
        rc, out, err = self.run(args)
        if rc != 0:
            msg = "{} 조회 실패: {}".format(resource, err.strip().splitlines()[-1] if err.strip() else rc)
            if optional:
                self.warnings.append(msg)
                log("  (건너뜀) " + msg)
                return []
            raise SystemExit("[오류] " + msg)
        try:
            return json.loads(out).get("items", []) or []
        except ValueError:
            raise SystemExit("[오류] {} 응답이 JSON 이 아님".format(resource))


# --------------------------------------------------------------------------- helpers

def md(o):
    return o.get("metadata", {}) or {}


def labels(o):
    return md(o).get("labels", {}) or {}


def annotations(o):
    return md(o).get("annotations", {}) or {}


def okey(o):
    return (md(o).get("namespace", ""), o.get("kind", ""), md(o).get("name", ""))


def managers(o):
    return sorted({m.get("manager", "") for m in (md(o).get("managedFields") or []) if m.get("manager")})


def pod_spec(o):
    kind = o.get("kind")
    spec = o.get("spec", {}) or {}
    if kind == "Pod":
        return spec
    if kind == "CronJob":
        return (((spec.get("jobTemplate") or {}).get("spec") or {}).get("template") or {}).get("spec") or {}
    return (spec.get("template") or {}).get("spec") or {}


def images_of(o):
    ps = pod_spec(o)
    out = []
    for c in (ps.get("initContainers") or []) + (ps.get("containers") or []):
        if c.get("image"):
            out.append(c["image"])
    return out


def argocd_app_from(o):
    tid = annotations(o).get("argocd.argoproj.io/tracking-id")
    if tid:
        return tid.split(":", 1)[0]
    if any("argocd" in m for m in managers(o)):
        return labels(o).get("app.kubernetes.io/instance", "")
    return ""


def helm_release_from(o):
    a = annotations(o)
    if a.get("meta.helm.sh/release-name"):
        return a["meta.helm.sh/release-name"]
    if labels(o).get("app.kubernetes.io/managed-by", "").lower() == "helm":
        return labels(o).get("app.kubernetes.io/instance") or labels(o).get("release", "")
    return ""


def owner_hints(o):
    hints = []
    for src in (labels(o), annotations(o)):
        for k, v in src.items():
            if k.startswith("kubectl.kubernetes.io/") or k.startswith("meta.helm.sh/"):
                continue
            if OWNER_KEY_RE.search(k) and v and len(v) < 200:
                hints.append("{}={}".format(k, v))
    return sorted(set(hints))


def selector_match(sel, lbls):
    return bool(sel) and all(lbls.get(k) == v for k, v in sel.items())


def disp_width(s):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s, w):
    s = str(s)
    if disp_width(s) > w - 1:
        while s and disp_width(s + "…") > w - 1:
            s = s[:-1]
        s += "…"
    return s + " " * (w - disp_width(s))


def join(vals, sep="; "):
    seen = OrderedDict()
    for v in vals:
        if v not in ("", None):
            seen[str(v)] = None
    return sep.join(seen.keys())


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([r.get(h, "") if isinstance(r, dict) else r[i] for i, h in enumerate(header)])


# --------------------------------------------------------------------------- collectors

def decode_helm_release(secret):
    raw = (secret.get("data") or {}).get("release")
    if not raw:
        return {}
    try:
        b = base64.b64decode(base64.b64decode(raw))
        if b[:2] == b"\x1f\x8b":
            b = gzip.decompress(b)
        rel = json.loads(b.decode("utf-8"))
        meta = ((rel.get("chart") or {}).get("metadata") or {})
        info = rel.get("info") or {}
        return {"chart": meta.get("name", ""), "chart_version": meta.get("version", ""),
                "app_version": meta.get("appVersion", ""), "last_deployed": info.get("last_deployed", "")}
    except Exception:
        return {}


def collect(kube, args):
    data = {}
    log("네임스페이스 조회")
    data["namespaces"] = kube.items("namespaces", namespaced=False)
    for res in ("deployments", "statefulsets", "daemonsets", "cronjobs", "jobs", "replicasets", "pods"):
        log("{} 조회".format(res))
        data[res] = kube.items(res, optional=(res == "cronjobs"))
    log("services / ingresses 조회")
    data["services"] = kube.items("services")
    data["ingresses"] = kube.items("ingresses", optional=True)
    log("Gateway API 라우트 조회 (없으면 건너뜀)")
    data["httproutes"] = kube.items("httproutes.gateway.networking.k8s.io", optional=True)
    data["grpcroutes"] = kube.items("grpcroutes.gateway.networking.k8s.io", optional=True)
    log("ArgoCD Application 조회 (없으면 건너뜀)")
    data["argo_apps"] = kube.items("applications.argoproj.io", optional=True)
    log("Helm 릴리즈 시크릿 조회")
    data["helm_secrets"] = kube.items("secrets", selector="owner=helm", optional=True)
    log("RoleBinding 조회")
    data["rolebindings"] = kube.items("rolebindings", optional=True)
    data["configmaps"] = []
    if args.ref_pattern:
        log("ConfigMap 조회 (I 지역 참조 검색)")
        data["configmaps"] = kube.items("configmaps", optional=True)
    return data


def fetch_cr_roots(kube, cr_kinds):
    """오너 체인 끝에 있는 CR 을 kind.group 단위로 한 번씩 조회"""
    out = {}
    for (api_version, kind) in sorted(cr_kinds):
        group = api_version.split("/")[0] if "/" in api_version else ""
        res = "{}.{}".format(kind.lower(), group) if group else kind.lower()
        log("CR 조회: {}".format(res))
        for o in kube.items(res, optional=True):
            out[o["metadata"].get("uid")] = o
    return out


def resource_scan(kube):
    rc, out, err = kube.run(["api-resources", "--verbs=list", "--namespaced", "-o", "name"])
    if rc != 0:
        kube.warnings.append("api-resources 실패: " + err.strip())
        return []
    rows = []
    types = [t for t in out.split() if t and t not in ("events", "events.events.k8s.io")]
    log("리소스 타입 스캔: {}개 타입".format(len(types)))
    for i, t in enumerate(types, 1):
        rc, o, e = kube.run(["get", t, "-A", "--no-headers", "--chunk-size={}".format(kube.chunk_size),
                             "-o", "custom-columns=NS:.metadata.namespace"])
        if rc != 0:
            kube.warnings.append("{} 스캔 실패".format(t))
            continue
        cnt = defaultdict(int)
        for line in o.splitlines():
            line = line.strip()
            if line:
                cnt[line] += 1
        for ns, c in sorted(cnt.items()):
            rows.append({"resource": t, "namespace": ns, "count": c})
        if i % 20 == 0:
            log("  {}/{}".format(i, len(types)))
    return rows


# --------------------------------------------------------------------------- analysis

def analyze(kube, data, args):
    sys_ns_re = re.compile(args.system_ns) if args.system_ns else None
    excl_re = re.compile(args.exclude_ns) if args.exclude_ns else None

    def ns_ok(ns):
        return not (excl_re and ns and excl_re.search(ns))

    workloads = []
    for res in ("deployments", "statefulsets", "daemonsets", "cronjobs", "jobs", "replicasets", "pods"):
        workloads += [o for o in data[res] if ns_ok(md(o).get("namespace", ""))]
    by_uid = {md(o).get("uid"): o for o in workloads}

    # 1차: 체인 끝의 CR 종류 파악
    def walk(o):
        chain = [o]
        cur = o
        seen = set()
        while True:
            refs = md(cur).get("ownerReferences") or []
            if not refs:
                return chain, None
            ref = next((r for r in refs if r.get("controller")), refs[0])
            uid = ref.get("uid")
            if uid in seen:
                return chain, None
            seen.add(uid)
            parent = by_uid.get(uid)
            if parent is None:
                return chain, dict(ref, namespace=md(cur).get("namespace", ""))
            chain.append(parent)
            cur = parent

    cr_kinds = set()
    for o in workloads:
        _, ref = walk(o)
        if ref and ref.get("kind") not in BUILTIN_WORKLOAD_KINDS:
            cr_kinds.add((ref.get("apiVersion", ""), ref.get("kind", "")))
    cr_objs = fetch_cr_roots(kube, cr_kinds) if cr_kinds else {}
    by_uid.update(cr_objs)

    # Helm 릴리즈 (최신 버전만)
    helm = {}
    for s in data["helm_secrets"]:
        l = labels(s)
        ns, name = md(s).get("namespace", ""), l.get("name", "")
        try:
            ver = int(l.get("version", "0"))
        except ValueError:
            ver = 0
        cur = helm.get((ns, name))
        if cur is None or ver > cur["revision"]:
            helm[(ns, name)] = {"namespace": ns, "release": name, "revision": ver,
                                "status": l.get("status", ""), "_secret": s}
    for h in helm.values():
        h.update(decode_helm_release(h.pop("_secret")))

    # ArgoCD 앱이 관리하는 리소스
    argo_res = {}
    argo_rows, argo_missing = [], []
    for a in data["argo_apps"]:
        spec, st = a.get("spec", {}) or {}, a.get("status", {}) or {}
        src = spec.get("source") or ((spec.get("sources") or [{}])[0])
        dest = spec.get("destination") or {}
        argo_rows.append({
            "app": md(a).get("name"), "app_namespace": md(a).get("namespace"), "project": spec.get("project", ""),
            "dest_server": dest.get("server", ""), "dest_name": dest.get("name", ""),
            "dest_namespace": dest.get("namespace", ""), "repo": src.get("repoURL", ""),
            "path_or_chart": src.get("path") or src.get("chart", ""), "revision": src.get("targetRevision", ""),
            "sync": (st.get("sync") or {}).get("status", ""), "health": (st.get("health") or {}).get("status", ""),
        })
        for r in st.get("resources") or []:
            k = (r.get("namespace", ""), r.get("kind", ""), r.get("name", ""))
            argo_res[k] = md(a).get("name")
            if (r.get("health") or {}).get("status") == "Missing":
                argo_missing.append({"app": md(a).get("name"), "namespace": k[0], "kind": k[1], "name": k[2],
                                     "sync": r.get("status", "")})

    # 루트 단위로 묶기
    roots = OrderedDict()
    pod_root = {}

    def root_of(o):
        chain, ref = walk(o)
        top = chain[-1]
        if ref is not None:
            cr = by_uid.get(ref.get("uid"))
            if cr is not None:
                return (okey(cr), cr, top, chain + [cr])
            k = (ref.get("namespace", ""), ref.get("kind", ""), ref.get("name", ""))
            return (k, None, top, chain)
        return (okey(top), top, top, chain)

    for o in workloads:
        k, robj, top, chain = root_of(o)
        r = roots.get(k)
        if r is None:
            r = roots[k] = {"key": k, "obj": robj, "top": top, "chain_keys": set(), "images": set(),
                            "pods": 0, "pods_ready": 0, "pods_running": 0}
        for c in chain:
            r["chain_keys"].add(okey(c))
        r["images"].update(images_of(o))
        if o.get("kind") == "Pod":
            pod_root[md(o).get("uid")] = k
            r["pods"] += 1
            ph = (o.get("status") or {}).get("phase", "")
            if ph == "Running":
                r["pods_running"] += 1
            cs = (o.get("status") or {}).get("containerStatuses") or []
            if cs and all(c.get("ready") for c in cs):
                r["pods_ready"] += 1

    # 노출: Service → Pod → 루트
    pods_by_ns = defaultdict(list)
    for p in data["pods"]:
        if md(p).get("uid") in pod_root:
            pods_by_ns[md(p).get("namespace", "")].append(p)
    svc_roots = {}
    exposure_rows, external_deps = [], []
    for s in data["services"]:
        ns, name = md(s).get("namespace", ""), md(s).get("name", "")
        if not ns_ok(ns):
            continue
        spec = s.get("spec", {}) or {}
        typ = spec.get("type", "ClusterIP")
        sel = spec.get("selector") or {}
        rks = sorted({pod_root[md(p)["uid"]] for p in pods_by_ns[ns] if selector_match(sel, labels(p))})
        svc_roots[(ns, name)] = rks
        if typ == "ExternalName":
            external_deps.append({"namespace": ns, "service": name, "external_name": spec.get("externalName", "")})
        if typ in ("LoadBalancer", "NodePort"):
            ips = [i.get("ip") or i.get("hostname") for i in ((s.get("status") or {}).get("loadBalancer") or {}).get("ingress") or []]
            nps = [str(p.get("nodePort")) for p in spec.get("ports") or [] if p.get("nodePort")]
            exposure_rows.append({"namespace": ns, "type": typ, "name": name, "host": "",
                                  "lb_ip": join(ips), "node_ports": join(nps), "backend": name,
                                  "targets": join("/".join(x[1:]) for x in rks)})
            for rk in rks:
                if rk in roots:
                    roots[rk].setdefault("lb", set()).update(ips)
                    roots[rk].setdefault("nodeports", set()).update(nps)

    def attach_host(ns, svc, host, kind, name):
        rks = svc_roots.get((ns, svc), [])
        for rk in rks:
            if rk in roots:
                roots[rk].setdefault("hosts", set()).add(host or "(host 없음)")
        return rks

    for ing in data["ingresses"]:
        ns = md(ing).get("namespace", "")
        if not ns_ok(ns):
            continue
        spec = ing.get("spec", {}) or {}
        rules = spec.get("rules") or [{}]
        default = ((spec.get("defaultBackend") or {}).get("service") or {}).get("name")
        for rule in rules:
            host = rule.get("host", "")
            backs = [((p.get("backend") or {}).get("service") or {}).get("name") for p in ((rule.get("http") or {}).get("paths") or [])]
            if default:
                backs.append(default)
            for b in sorted({x for x in backs if x}):
                rks = attach_host(ns, b, host, "Ingress", md(ing).get("name"))
                exposure_rows.append({"namespace": ns, "type": "Ingress", "name": md(ing).get("name"), "host": host,
                                      "lb_ip": "", "node_ports": "", "backend": b,
                                      "targets": join("/".join(x[1:]) for x in rks) or "(대상 Pod 없음)"})
    for rt in data["httproutes"] + data["grpcroutes"]:
        ns = md(rt).get("namespace", "")
        if not ns_ok(ns):
            continue
        spec = rt.get("spec", {}) or {}
        hosts = spec.get("hostnames") or [""]
        for rule in spec.get("rules") or []:
            for br in rule.get("backendRefs") or []:
                if br.get("kind", "Service") != "Service":
                    continue
                bns = br.get("namespace", ns)
                for h in hosts:
                    rks = attach_host(bns, br.get("name"), h, rt.get("kind"), md(rt).get("name"))
                    exposure_rows.append({"namespace": ns, "type": rt.get("kind"), "name": md(rt).get("name"),
                                          "host": h, "lb_ip": "", "node_ports": "", "backend": "{}/{}".format(bns, br.get("name")),
                                          "targets": join("/".join(x[1:]) for x in rks) or "(대상 Pod 없음)"})

    # 네임스페이스 정보
    ns_info = {}
    for n in data["namespaces"]:
        ns_info[md(n).get("name")] = {"hints": owner_hints(n), "created": md(n).get("creationTimestamp", ""), "rbac": set()}
    rbac_rows = []
    for rb in data["rolebindings"]:
        ns = md(rb).get("namespace", "")
        for sub in rb.get("subjects") or []:
            if sub.get("kind") in ("User", "Group"):
                rbac_rows.append({"namespace": ns, "rolebinding": md(rb).get("name"),
                                  "role": (rb.get("roleRef") or {}).get("name", ""),
                                  "subject_kind": sub.get("kind"), "subject": sub.get("name")})
                if ns in ns_info:
                    ns_info[ns]["rbac"].add("{}:{}".format(sub.get("kind")[0], sub.get("name")))

    # 루트별 상세
    wl_rows = []
    for k, r in roots.items():
        ns, kind, name = k
        obj, top = r["obj"], r["top"]
        base = obj or top
        is_cr = kind not in BUILTIN_WORKLOAD_KINDS
        argo = (argocd_app_from(obj) if obj is not None else "") or argocd_app_from(top)
        if not argo:
            for ck in r["chain_keys"] | {k}:
                if ck in argo_res:
                    argo = argo_res[ck]
                    break
        hrel = (helm_release_from(obj) if obj is not None else "") or helm_release_from(top)
        mgrs = sorted(set((managers(obj) if obj is not None else []) + managers(top)))

        paths = []
        if is_cr:
            paths.append("Operator:{}".format(kind))
        if argo:
            paths.append("ArgoCD")
        if hrel:
            paths.append("Helm")
        if not argo and not hrel:
            if any(m in KUBECTL_MANAGERS for m in mgrs) or "kubectl.kubernetes.io/last-applied-configuration" in annotations(base):
                paths.append("kubectl")
            elif kind == "Pod":
                l = labels(base)
                if "dag_id" in l or "airflow-worker" in l or "kubernetes_pod_operator" in l:
                    paths.append("Airflow-Pod")
                elif "spark-role" in l or "spark-app-name" in l:
                    paths.append("Spark-Pod")
                else:
                    paths.append("단독Pod")
            elif not is_cr:
                paths.append("미상")

        svc_name = argo or hrel
        if not svc_name:
            for lk in NAME_LABELS:
                v = labels(base).get(lk) or labels(top).get(lk)
                if v:
                    svc_name = ("airflow:" + v) if lk == "dag_id" else v
                    break
        if not svc_name:
            gen = md(base).get("generateName", "") if base else ""
            svc_name = gen.rstrip("-") if (kind == "Pod" and gen) else name

        spec = (base.get("spec") or {}) if base else {}
        st = (base.get("status") or {}) if base else {}
        desired, state = "", ""
        if kind in ("Deployment", "StatefulSet", "ReplicaSet"):
            desired = spec.get("replicas", 1)
            state = "ready {}/{}".format(st.get("readyReplicas", 0) or 0, desired)
        elif kind == "DaemonSet":
            desired = st.get("desiredNumberScheduled", "")
            state = "ready {}/{}".format(st.get("numberReady", 0) or 0, desired)
        elif kind == "CronJob":
            state = "schedule={}{} last={}".format(spec.get("schedule", ""), " (suspend)" if spec.get("suspend") else "",
                                                 st.get("lastScheduleTime", "-"))
        elif kind == "Job":
            state = "succeeded={} failed={}".format(st.get("succeeded", 0) or 0, st.get("failed", 0) or 0)
        elif kind == "Pod":
            state = st.get("phase", "")
        else:
            state = "pods ready {}/{}".format(r["pods_ready"], r["pods"])

        flags = []
        if desired == 0:
            flags.append("replicas=0")
        if kind == "CronJob" and spec.get("suspend"):
            flags.append("suspend")
        if r["pods"] and r["pods_ready"] == 0 and kind not in ("CronJob", "Job"):
            flags.append("ready Pod 없음")
        if argo_rows and not argo:
            flags.append("ArgoCD 외")
        if sys_ns_re and sys_ns_re.search(ns):
            flags.append("system")

        nsi = ns_info.get(ns, {"hints": [], "rbac": set()})
        wl_rows.append({
            "namespace": ns, "service_name": svc_name, "kind": kind, "name": name,
            "part_of": labels(base).get("app.kubernetes.io/part-of", "") or labels(top).get("app.kubernetes.io/part-of", ""),
            "deploy_path": "+".join(paths), "argocd_app": argo, "helm_release": hrel,
            "helm_chart": (lambda h: "{}-{}".format(h.get("chart", ""), h.get("chart_version", "")) if h and h.get("chart") else "")(helm.get((ns, hrel))),
            "managers": join(mgrs), "state": state, "pods": r["pods"], "pods_ready": r["pods_ready"],
            "images": join(sorted(r["images"])),
            "hosts": join(sorted(r.get("hosts", set()))), "lb_ips": join(sorted(x for x in r.get("lb", set()) if x)),
            "node_ports": join(sorted(r.get("nodeports", set()))),
            "owner_hint": join(owner_hints(base) + (owner_hints(top) if top is not base else [])),
            "ns_owner_hint": join(nsi["hints"]), "ns_rbac": join(sorted(nsi["rbac"])),
            "created": md(base).get("creationTimestamp", "") if base else "", "flags": join(flags, ","),
        })

    wl_rows.sort(key=lambda x: (x["namespace"], x["service_name"], x["kind"], x["name"]))

    # 서비스 단위 집계 (namespace + service_name)
    svc = OrderedDict()
    for w in wl_rows:
        k = (w["namespace"], w["service_name"])
        svc.setdefault(k, []).append(w)
    svc_rows = []
    for (ns, name), ws in svc.items():
        svc_rows.append({
            "namespace": ns, "service_name": name,
            "workloads": join("{}/{}".format(w["kind"], w["name"]) for w in ws),
            "deploy_path": join((w["deploy_path"] for w in ws), ", "),
            "argocd_app": join(w["argocd_app"] for w in ws), "helm_release": join(w["helm_release"] for w in ws),
            "helm_chart": join(w["helm_chart"] for w in ws),
            "pods": sum(w["pods"] for w in ws), "pods_ready": sum(w["pods_ready"] for w in ws),
            "hosts": join(h for w in ws for h in w["hosts"].split("; ")),
            "lb_ips": join(h for w in ws for h in w["lb_ips"].split("; ")),
            "images": join(i for w in ws for i in w["images"].split("; ")),
            "owner_hint": join(h for w in ws for h in w["owner_hint"].split("; ")),
            "ns_owner_hint": ws[0]["ns_owner_hint"], "ns_rbac": ws[0]["ns_rbac"],
            "flags": join((f for w in ws for f in w["flags"].split(",")), ","),
            # 사람이 채우는 칸 (가이드 7장 템플릿과 동일)
            "담당자(정)": "", "담당자(부)": "", "팀": "", "근거": "", "신뢰도": "", "분리 처리": "", "비고": "",
        })

    used_ns = {w["namespace"] for w in wl_rows}
    empty_ns = sorted(n for n in ns_info if n not in used_ns and ns_ok(n))

    cm_rows = []
    if args.ref_pattern:
        pat = re.compile(args.ref_pattern)
        for cm in data["configmaps"]:
            ns = md(cm).get("namespace", "")
            if not ns_ok(ns):
                continue
            for dk, dv in (cm.get("data") or {}).items():
                ms = list(pat.finditer(dv or ""))
                if ms:
                    snip = []
                    for m in ms[:3]:
                        s = max(0, m.start() - 30)
                        snip.append((dv[s:m.end() + 30]).replace("\n", " "))
                    cm_rows.append({"namespace": ns, "configmap": md(cm).get("name"), "key": dk,
                                    "matches": len(ms), "snippet": " | ".join(snip)})

    helm_rows = sorted(helm.values(), key=lambda h: (h["namespace"], h["release"]))
    helm_used = {(w["namespace"], w["helm_release"]) for w in wl_rows if w["helm_release"]}
    for h in helm_rows:
        h["has_workload"] = "Y" if (h["namespace"], h["release"]) in helm_used else "N"

    return {"workloads": wl_rows, "services": svc_rows, "exposure": exposure_rows, "external": external_deps,
            "argo_apps": argo_rows, "argo_missing": argo_missing, "helm": helm_rows, "rbac": rbac_rows,
            "empty_ns": empty_ns, "cm_refs": cm_rows, "ns_count": len(ns_info)}


# --------------------------------------------------------------------------- output

def print_services(res, out):
    rows = res["services"]
    w = [24, 34, 36, 30]
    head = "{}{}{}{}{}".format(pad("NAMESPACE", w[0]), pad("SERVICE", w[1]), pad("배포 경로", w[2]),
                               pad("노출(host/LB)", w[3]), "상태")
    out.write("\n== wu K8s 서비스 목록: 서비스 {}개 / 워크로드 {}개 / 네임스페이스 {}개 ==\n\n".format(
        len(rows), len(res["workloads"]), res["ns_count"]))
    out.write(head + "\n" + "-" * (sum(w) + 24) + "\n")
    for r in rows:
        expo = r["hosts"] or r["lb_ips"]
        status = "pods {}/{}".format(r["pods_ready"], r["pods"])
        if r["flags"]:
            status += "  [{}]".format(r["flags"])
        out.write("{}{}{}{}{}\n".format(pad(r["namespace"], w[0]), pad(r["service_name"], w[1]),
                                        pad(r["deploy_path"], w[2]), pad(expo or "-", w[3]), status))


def write_outputs(res, outdir, scan_rows, warnings, started):
    os.makedirs(outdir, exist_ok=True)
    write_csv(os.path.join(outdir, "services.csv"),
              ["namespace", "service_name", "workloads", "deploy_path", "argocd_app", "helm_release", "helm_chart",
               "pods", "pods_ready", "hosts", "lb_ips", "images", "owner_hint", "ns_owner_hint", "ns_rbac", "flags",
               "담당자(정)", "담당자(부)", "팀", "근거", "신뢰도", "분리 처리", "비고"], res["services"])
    write_csv(os.path.join(outdir, "workloads.csv"),
              ["namespace", "service_name", "kind", "name", "part_of", "deploy_path", "argocd_app", "helm_release",
               "helm_chart", "managers", "state", "pods", "pods_ready", "images", "hosts", "lb_ips", "node_ports",
               "owner_hint", "ns_owner_hint", "ns_rbac", "created", "flags"], res["workloads"])
    write_csv(os.path.join(outdir, "exposure.csv"),
              ["namespace", "type", "name", "host", "lb_ip", "node_ports", "backend", "targets"], res["exposure"])
    write_csv(os.path.join(outdir, "external_names.csv"), ["namespace", "service", "external_name"], res["external"])
    write_csv(os.path.join(outdir, "argocd_apps.csv"),
              ["app", "app_namespace", "project", "dest_server", "dest_name", "dest_namespace", "repo",
               "path_or_chart", "revision", "sync", "health"], res["argo_apps"])
    write_csv(os.path.join(outdir, "argocd_missing.csv"), ["app", "namespace", "kind", "name", "sync"], res["argo_missing"])
    write_csv(os.path.join(outdir, "helm_releases.csv"),
              ["namespace", "release", "revision", "status", "chart", "chart_version", "app_version",
               "last_deployed", "has_workload"], res["helm"])
    write_csv(os.path.join(outdir, "ns_rbac.csv"), ["namespace", "rolebinding", "role", "subject_kind", "subject"], res["rbac"])
    write_csv(os.path.join(outdir, "empty_namespaces.csv"), ["namespace"], [{"namespace": n} for n in res["empty_ns"]])
    if res["cm_refs"]:
        write_csv(os.path.join(outdir, "configmap_refs.csv"), ["namespace", "configmap", "key", "matches", "snippet"], res["cm_refs"])
    if scan_rows:
        write_csv(os.path.join(outdir, "resource_counts.csv"), ["resource", "namespace", "count"], scan_rows)

    by_path = defaultdict(int)
    for w in res["workloads"]:
        by_path[w["deploy_path"]] += 1
    flags = defaultdict(int)
    for w in res["workloads"]:
        for f in w["flags"].split(","):
            if f:
                flags[f] += 1
    lines = ["## wu K8s 서비스 인벤토리 요약", "",
             "- 수집 시각: {}".format(started.strftime("%Y-%m-%d %H:%M:%S")),
             "- 서비스 {}개 / 최상위 워크로드 {}개 / 네임스페이스 {}개 (워크로드 없는 NS {}개)".format(
                 len(res["services"]), len(res["workloads"]), res["ns_count"], len(res["empty_ns"])),
             "- ArgoCD 앱 {}개 (Missing 리소스 {}개), Helm 릴리즈 {}개".format(
                 len(res["argo_apps"]), len(res["argo_missing"]), len(res["helm"])),
             "- 외부 노출 항목 {}개, ExternalName {}개, ConfigMap I 지역 참조 {}건".format(
                 len(res["exposure"]), len(res["external"]), len(res["cm_refs"])), "",
             "### 배포 경로별 워크로드 수", "", "| 배포 경로 | 개수 |", "| --- | --- |"]
    for p, c in sorted(by_path.items(), key=lambda x: -x[1]):
        lines.append("| {} | {} |".format(p or "-", c))
    lines += ["", "### 확인 필요 플래그", "", "| 플래그 | 개수 |", "| --- | --- |"]
    for f, c in sorted(flags.items(), key=lambda x: -x[1]):
        lines.append("| {} | {} |".format(f, c))
    if res["empty_ns"]:
        lines += ["", "### 워크로드 없는 네임스페이스", ""] + ["- {}".format(n) for n in res["empty_ns"]]
    orphan_helm = [h for h in res["helm"] if h.get("has_workload") == "N"]
    if orphan_helm:
        lines += ["", "### 워크로드가 안 보이는 Helm 릴리즈", "",
                  "Pod 를 만들지 않는 차트(설정·CRD 전용)이거나, 실패·삭제 후 남은 릴리즈일 수 있음.", ""]
        lines += ["- {}/{} (rev {}, {})".format(h["namespace"], h["release"], h["revision"], h["status"]) for h in orphan_helm]
    if res["argo_missing"]:
        lines += ["", "### ArgoCD 에는 있는데 클러스터에 없는 리소스 (Missing)", ""]
        lines += ["- {} → {}/{}/{}".format(m["app"], m["namespace"], m["kind"], m["name"]) for m in res["argo_missing"]]
    if warnings:
        lines += ["", "### 수집 경고", ""] + ["- {}".format(w) for w in warnings]
    lines += ["", "### 이 도구로 못 잡는 것", "",
              "- 클러스터 밖 ArgoCD(I 지역 공용 등)의 Application 목록 → 해당 ArgoCD 에서 별도 확인",
              "- Jenkins Job, Git 커밋 작성자, Hubble 트래픽 → 가이드 4-6, 4-7 절차로 보완",
              "- 수집 시점에 없던 Job·단독 Pod → 1주 뒤 재실행 후 workloads.csv 비교"]
    with open(os.path.join(outdir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(outdir, "services.txt"), "w", encoding="utf-8") as f:
        print_services(res, f)


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="wu K8s 서비스 인벤토리 수집기 (읽기 전용)")
    ap.add_argument("--kubectl", default=os.environ.get("KUBECTL", "kubectl"), help="kubectl 경로 (기본: kubectl)")
    ap.add_argument("--kubeconfig", help="kubeconfig 경로")
    ap.add_argument("--context", help="kubeconfig context")
    ap.add_argument("-o", "--out", help="출력 디렉터리 (기본: inv-YYYYmmdd-HHMM)")
    ap.add_argument("--ref-pattern", help="ConfigMap 에서 찾을 I 지역 참조 정규식 (예: 'i-region\\.example\\.com|10\\.10\\.')")
    ap.add_argument("--exclude-ns", help="제외할 네임스페이스 정규식")
    ap.add_argument("--system-ns", default=r"^(kube-|default$)", help="system 플래그를 붙일 네임스페이스 정규식")
    ap.add_argument("--skip-resource-scan", action="store_true", help="리소스 타입별 개수 스캔 생략 (빠름)")
    ap.add_argument("--timeout", type=int, default=300, help="kubectl 호출 타임아웃(초)")
    ap.add_argument("--chunk-size", type=int, default=500)
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args()

    started = datetime.datetime.now()
    outdir = args.out or "inv-" + started.strftime("%Y%m%d-%H%M")
    kube = Kube(args.kubectl, args.kubeconfig, args.context, args.timeout, args.chunk_size)

    rc, out, err = kube.run(["config", "current-context"])
    log("context: {}".format(out.strip() or "(알 수 없음)"))
    rc, out, err = kube.run(["auth", "can-i", "list", "pods", "--all-namespaces"])
    if out.strip() != "yes":
        log("경고: 전체 네임스페이스 pods list 권한이 없을 수 있음 ({})".format((out or err).strip()))

    data = collect(kube, args)
    res = analyze(kube, data, args)
    scan_rows = [] if args.skip_resource_scan else resource_scan(kube)
    write_outputs(res, outdir, scan_rows, kube.warnings, started)
    print_services(res, sys.stdout)
    log("완료: {}/ (services.csv, workloads.csv, summary.md 등)".format(outdir))


if __name__ == "__main__":
    main()
