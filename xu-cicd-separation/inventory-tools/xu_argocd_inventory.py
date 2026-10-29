#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ArgoCD 기준 서비스 인벤토리 수집기 (대화형)

ArgoCD 가 설치된 K8s 클러스터의 노드(kubectl 사용 가능)에서 실행. 표준 라이브러리만 사용 (Python 3.6+).
argocd CLI 로그인 없이 kubectl 로 ArgoCD CRD(Application, AppProject, ApplicationSet)와
클러스터 등록 시크릿을 읽기만 함.

흐름
  1) 클러스터 이름 입력 (엔터만 치면 등록된 클러스터 목록 표시)
  2) ArgoCD 에 등록된 클러스터인지 확인 → 접속 서버 URL 과 IP 를 보여주고 맞는지 확인
  3) 그 클러스터를 목적지로 하는 Application 을 모아 서비스 목록과 CSV 생성

클러스터 시크릿에서는 name, server 두 값만 디코딩하고 나머지(자격증명 config 포함)는 받는 즉시 버림.
파일·화면 어디에도 남기지 않음.

운영 영향 방지 장치 (xu_k8s_inventory.py 와 동일)
  - 허용된 읽기 명령(get, get --raw, config current-context, version)만 실행, 그 외는 실행 전에 차단
  - API 페이지 단위(기본 500개) 조회 + 페이지 사이 대기, 받은 즉시 필요한 필드만 남김
  - 낮은 CPU 우선순위(nice), 남은 메모리 확인, --dry-run 지원

비대화형 실행: --cluster <이름> --yes
"""

import argparse
import base64
import csv
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import time
import unicodedata
from collections import OrderedDict, defaultdict
from urllib.parse import urlencode, urlparse

VERSION = "1.1.0"
ARGO_API = "/apis/argoproj.io/v1alpha1"
IN_CLUSTER_SERVER = "https://kubernetes.default.svc"

# 서비스 구성(설정)용 kind — 이 외의 kind 는 워크로드로 봄 (CR 포함)
CONFIG_KINDS = {
    "Service", "ConfigMap", "Secret", "ServiceAccount", "Role", "RoleBinding", "ClusterRole",
    "ClusterRoleBinding", "PersistentVolumeClaim", "PersistentVolume", "NetworkPolicy",
    "CiliumNetworkPolicy", "CiliumClusterwideNetworkPolicy", "PodDisruptionBudget",
    "HorizontalPodAutoscaler", "VerticalPodAutoscaler", "Namespace", "Endpoints", "EndpointSlice",
    "Ingress", "HTTPRoute", "GRPCRoute", "TLSRoute", "TCPRoute", "Gateway", "ServiceMonitor",
    "PodMonitor", "PrometheusRule", "CustomResourceDefinition", "StorageClass", "LimitRange",
    "ResourceQuota", "Certificate", "Issuer", "ClusterIssuer", "ExternalSecret", "SecretStore",
    "MutatingWebhookConfiguration", "ValidatingWebhookConfiguration", "PriorityClass",
    "IngressClass", "GatewayClass", "ReferenceGrant", "CiliumLoadBalancerIPPool",
}
EXPOSE_KINDS = {"Ingress", "HTTPRoute", "GRPCRoute", "TLSRoute", "TCPRoute", "Gateway"}
OWNER_KEY_RE = re.compile(r"(owner|team|maintainer|contact|manager|email|담당)", re.I)


def log(msg):
    sys.stderr.write("[{}] {}\n".format(datetime.datetime.now().strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def is_read_only(args):
    """허용된 읽기 명령만 True. kubectl get --raw 는 항상 HTTP GET."""
    if not args:
        return False
    if args[0] == "get":
        return not any(a in ("-w", "--watch", "--watch-only") or a.startswith("--watch") for a in args)
    if args[:2] == ["config", "current-context"]:
        return True
    return args[0] == "version"


class Kube(object):
    def __init__(self, kubectl, kubeconfig=None, context=None, timeout=120, page_size=500, throttle=0.3, dry_run=False):
        self.base = [kubectl]
        if kubeconfig:
            self.base += ["--kubeconfig", kubeconfig]
        if context:
            self.base += ["--context", context]
        self.timeout = timeout
        self.page_size = page_size
        self.throttle = throttle
        self.dry_run = dry_run
        self.warnings = []
        self.calls = 0

    def run(self, args):
        if not is_read_only(args):
            raise SystemExit("[차단] 읽기 전용이 아닌 kubectl 명령은 실행하지 않음: kubectl " + " ".join(args))
        self.calls += 1
        if self.dry_run:
            print("DRY-RUN  " + " ".join(self.base + args))
            return 0, "", ""
        try:
            # 별도 프로세스 그룹: 타임아웃 시 kubectl 과 인증 플러그인 자식까지 같이 정리
            p = subprocess.Popen(self.base + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        except OSError as e:
            return 127, "", str(e)
        try:
            out, err = p.communicate(timeout=self.timeout)
        except KeyboardInterrupt:
            try:
                os.killpg(p.pid, 9)  # Ctrl-C 시 실행 중인 kubectl 도 같이 정리
            except OSError:
                pass
            raise
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, 9)
            except OSError:
                p.kill()
            try:
                p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return 124, "", "timeout after {}s".format(self.timeout)
        return p.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def list_raw(self, path, selector=None, optional=False, transform=None, page_size=None):
        """API 를 page_size 단위로 페이지 조회. 페이지마다 transform 으로 필요한 필드만 남김."""
        items, cont, restarted = [], "", False
        limit = min(page_size or self.page_size, self.page_size)
        while True:
            q = [("limit", str(limit))]
            if selector:
                q.append(("labelSelector", selector))
            if cont:
                q.append(("continue", cont))
            rc, out, err = self.run(["get", "--raw", path + "?" + urlencode(q)])
            if self.dry_run:
                return []
            if rc != 0:
                if cont and not restarted and ("expired" in err.lower() or "410" in err):
                    log("  continue 토큰 만료 → 처음부터 다시 조회")
                    items, cont, restarted = [], "", True
                    time.sleep(self.throttle)
                    continue
                msg = "{} 조회 실패: {}".format(path, (err.strip().splitlines() or [str(rc)])[-1])
                if optional:
                    self.warnings.append(msg)
                    log("  (건너뜀) " + msg)
                    return []
                raise SystemExit("[오류] " + msg)
            try:
                d = json.loads(out)
            except ValueError:
                if optional:
                    self.warnings.append("{} 응답이 JSON 이 아님".format(path))
                    return []
                raise SystemExit("[오류] {} 응답이 JSON 이 아님".format(path))
            kind = d.get("kind", "")
            kind = kind[:-4] if kind.endswith("List") else kind
            for it in d.get("items") or []:
                it.setdefault("kind", kind)
                it = transform(it) if transform else it
                if it is not None:
                    items.append(it)
            cont = (d.get("metadata") or {}).get("continue") or ""
            d = out = None  # 원본 페이지는 바로 버림
            if not cont:
                return items
            time.sleep(self.throttle)


def mem_available_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (IOError, OSError, ValueError):
        return None
    return None


def slim_meta(o):
    m = o.get("metadata") or {}
    return {k: m[k] for k in ("name", "namespace", "labels", "annotations", "creationTimestamp") if m.get(k) is not None}


def slim_app(o):
    spec, st = o.get("spec") or {}, o.get("status") or {}
    op = st.get("operationState") or {}
    hist = st.get("history") or []
    return {"kind": "Application", "metadata": slim_meta(o),
            "spec": {"project": spec.get("project"), "source": spec.get("source"), "sources": spec.get("sources"),
                     "destination": spec.get("destination"),
                     "syncPolicy": {"automated": (spec.get("syncPolicy") or {}).get("automated")}},
            "status": {"sync": {k: (st.get("sync") or {}).get(k) for k in ("status", "revision", "revisions")},
                       "health": {"status": (st.get("health") or {}).get("status")},
                       "resources": [{"group": r.get("group", ""), "kind": r.get("kind", ""), "namespace": r.get("namespace", ""),
                                      "name": r.get("name", ""), "status": r.get("status", ""),
                                      "health": {"status": (r.get("health") or {}).get("status")}}
                                     for r in st.get("resources") or []],
                       "summary": {"images": (st.get("summary") or {}).get("images") or [],
                                   "externalURLs": (st.get("summary") or {}).get("externalURLs") or []},
                       "operationState": {"phase": op.get("phase"), "finishedAt": op.get("finishedAt"),
                                          "operation": {"initiatedBy": (op.get("operation") or {}).get("initiatedBy") or {}}},
                       "history": hist[-1:]}}


def slim_project(o):
    spec = o.get("spec") or {}
    return {"kind": "AppProject", "metadata": slim_meta(o),
            "spec": {"description": spec.get("description"),
                     "roles": [{"groups": r.get("groups") or []} for r in spec.get("roles") or []]}}


def slim_appset(o):
    return {"kind": "ApplicationSet", "metadata": slim_meta(o), "spec": o.get("spec") or {}}


def slim_cluster_secret(o):
    """name/server/project 만 디코딩하고 자격증명(config)이 든 data 는 버림"""
    d = o.get("data") or {}
    return {"secret": (o.get("metadata") or {}).get("name", ""), "name": b64(d.get("name", "")),
            "server": b64(d.get("server", "")), "project": b64(d["project"]) if d.get("project") else ""}


# --------------------------------------------------------------------------- helpers

def md(o):
    return o.get("metadata", {}) or {}


def b64(s):
    try:
        return base64.b64decode(s).decode("utf-8", "replace")
    except Exception:
        return ""


def join(vals, sep="; "):
    seen = OrderedDict()
    for v in vals:
        if v not in ("", None):
            seen[str(v)] = None
    return sep.join(seen.keys())


def norm_server(s):
    return (s or "").rstrip("/")


def disp_width(s):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s, w):
    s = str(s)
    if disp_width(s) > w - 1:
        while s and disp_width(s + "…") > w - 1:
            s = s[:-1]
        s += "…"
    return s + " " * (w - disp_width(s))


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([r.get(h, "") for h in header])


def ask(prompt):
    if not sys.stdin.isatty():
        raise SystemExit("[중단] 터미널이 아닌 곳에서 실행됨 — 비대화형으로 쓰려면 --cluster <이름> --yes 지정")
    try:
        return input(prompt).strip()
    except EOFError:
        raise SystemExit("\n입력이 끝남 — 비대화형으로 쓰려면 --cluster 와 --yes 를 지정")


def server_ips(server):
    host = urlparse(server).hostname or ""
    if not host:
        return host, []
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host) or ":" in host:
        return host, [host]
    try:
        infos = socket.getaddrinfo(host, None)
        return host, sorted({i[4][0] for i in infos})
    except socket.gaierror:
        return host, []


def owner_hints(o):
    out = []
    for src in ((md(o).get("labels") or {}), (md(o).get("annotations") or {})):
        for k, v in src.items():
            if k.startswith("notifications.argoproj.io/subscribe"):
                out.append("알림 {}={}".format(k.split("subscribe.", 1)[-1], v))
            elif OWNER_KEY_RE.search(k) and v and len(v) < 200 and not k.startswith("kubectl.kubernetes.io/"):
                out.append("{}={}".format(k, v))
    return out


def strip_userinfo(url):
    """https://user:token@host/... → https://host/... (CSV 에 자격증명이 남지 않게)"""
    return re.sub(r"^([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@]*@", r"\1", url or "")


def repo_group(url):
    """git URL 에서 조직/그룹 경로 추출 (담당 팀 단서)"""
    if not url:
        return ""
    u = url
    if u.startswith("git@"):
        u = "ssh://" + u.replace(":", "/", 1)
    path = (urlparse(u).path or "").strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else ""


# --------------------------------------------------------------------------- clusters

def load_clusters(kube, argocd_ns, apps):
    clusters = OrderedDict()
    secs = kube.list_raw("/api/v1/namespaces/{}/secrets".format(argocd_ns),
                         selector="argocd.argoproj.io/secret-type=cluster", optional=True, transform=slim_cluster_secret)
    for s in secs:
        server = norm_server(s["server"])
        if server:
            clusters[server] = {"name": s["name"] or s["secret"], "server": server, "source": "secret:" + s["secret"],
                                "project": s["project"]}
    if IN_CLUSTER_SERVER not in clusters:
        clusters[IN_CLUSTER_SERVER] = {"name": "in-cluster", "server": IN_CLUSTER_SERVER, "source": "기본(in-cluster)", "project": ""}
    # 시크릿 조회 권한이 없을 때를 대비해 Application 목적지에서도 보충
    for a in apps:
        dest = (a.get("spec") or {}).get("destination") or {}
        srv = norm_server(dest.get("server"))
        if srv and srv not in clusters:
            clusters[srv] = {"name": dest.get("name") or "", "server": srv, "source": "Application 목적지", "project": ""}
    counts = defaultdict(int)
    by_name = {c["name"]: s for s, c in clusters.items() if c["name"]}
    for a in apps:
        dest = (a.get("spec") or {}).get("destination") or {}
        srv = norm_server(dest.get("server")) or by_name.get(dest.get("name"), "")
        counts[srv] += 1
    for s, c in clusters.items():
        c["apps"] = counts.get(s, 0)
    return list(clusters.values())


def print_clusters(cl):
    print("\n  #   {}{}{}".format(pad("클러스터 이름", 28), pad("서버", 52), "앱 수"))
    for i, c in enumerate(cl, 1):
        print("  {:<3} {}{}{}".format(i, pad(c["name"] or "(이름 없음)", 28), pad(c["server"], 52), c["apps"]))
    print("")


def choose_cluster(clusters, preset=None, assume_yes=False):
    while True:
        name = preset if preset is not None else ask("\n[1/2] 클러스터 이름을 입력 (엔터: 목록 보기, q: 종료) > ")
        preset = None
        if name.lower() == "q":
            raise SystemExit(0)
        if not name:
            print_clusters(clusters)
            continue
        exact = [c for c in clusters if c["name"] == name or c["server"] == norm_server(name)]
        cand = exact or [c for c in clusters if name.lower() in (c["name"] or "").lower() or name.lower() in c["server"].lower()]
        if not cand:
            print("  '{}' 클러스터가 ArgoCD 에 없음. 엔터로 전체 목록을 볼 수 있음.".format(name))
            if assume_yes:
                raise SystemExit(2)
            continue
        if len(cand) > 1:
            print("  '{}' 와 비슷한 클러스터가 {}개 있음:".format(name, len(cand)))
            print_clusters(cand)
            if assume_yes:
                raise SystemExit("  --yes 모드에서는 정확한 이름이 필요함")
            sel = ask("  번호 선택 (엔터: 다시 입력) > ")
            if not sel.isdigit() or not (1 <= int(sel) <= len(cand)):
                continue
            c = cand[int(sel) - 1]
        else:
            c = cand[0]

        host, ips = server_ips(c["server"])
        print("\n  클러스터 : {}".format(c["name"]))
        print("  서버 URL : {}".format(c["server"]))
        print("  서버 IP  : {}".format(", ".join(ips) if ips else "{} (이 노드에서 DNS 해석 안 됨)".format(host)))
        print("  등록 출처: {}   대상 앱: {}개".format(c["source"], c["apps"]))
        if assume_yes:
            return c, ips
        yn = ask("\n[2/2] 이 서버가 맞습니까? [y/N] > ").lower()
        if yn in ("y", "yes", "ㅛ"):
            return c, ips
        print("  다시 입력함.")


# --------------------------------------------------------------------------- analysis

def analyze(cluster, apps, projects, appsets):
    srv, cname = cluster["server"], cluster["name"]
    proj = {md(p).get("name"): p for p in projects}

    def targets(a):
        dest = (a.get("spec") or {}).get("destination") or {}
        return norm_server(dest.get("server")) == srv or (cname and dest.get("name") == cname)

    app_rows, res_rows, svc_rows, missing, expose = [], [], [], [], []
    for a in sorted((x for x in apps if targets(x)), key=lambda x: md(x).get("name", "")):
        name = md(a).get("name")
        spec, st = a.get("spec") or {}, a.get("status") or {}
        srcs = spec.get("sources") or ([spec["source"]] if spec.get("source") else [])
        dest = spec.get("destination") or {}
        op = st.get("operationState") or {}
        init = ((op.get("operation") or {}).get("initiatedBy") or {})
        hist = st.get("history") or []
        p = proj.get(spec.get("project"))
        p_hints = []
        if p is not None:
            ps = p.get("spec") or {}
            if ps.get("description"):
                p_hints.append("project 설명=" + ps["description"])
            groups = sorted({g for r in ps.get("roles") or [] for g in (r.get("groups") or [])})
            if groups:
                p_hints.append("project 그룹=" + ",".join(groups))
            p_hints += ["project " + h for h in owner_hints(p)]
        a_hints = owner_hints(a)
        sync_user = init.get("username", "") if not init.get("automated") else "(자동 sync)"

        resources = st.get("resources") or []
        workloads, exposes = [], []
        for r in resources:
            kind = r.get("kind", "")
            row = {"app": name, "namespace": r.get("namespace", "") or dest.get("namespace", ""), "group": r.get("group", ""),
                   "kind": kind, "name": r.get("name", ""), "sync": r.get("status", ""),
                   "health": (r.get("health") or {}).get("status", ""),
                   "role": "노출" if kind in EXPOSE_KINDS else ("설정" if kind in CONFIG_KINDS else "워크로드")}
            res_rows.append(row)
            if row["role"] == "워크로드":
                workloads.append("{}/{}".format(kind, row["name"]))
            if row["role"] == "노출":
                exposes.append("{}/{}".format(kind, row["name"]))
                expose.append(row)
            if row["health"] == "Missing":
                missing.append(row)

        summ = st.get("summary") or {}
        repos = [strip_userinfo(s.get("repoURL", "")) for s in srcs]
        app_row = {
            "app": name, "app_namespace": md(a).get("namespace"), "project": spec.get("project", ""),
            "dest_name": dest.get("name", "") or cname, "dest_server": dest.get("server", "") or srv,
            "dest_namespace": dest.get("namespace", ""),
            "repo": join(repos), "path_or_chart": join(s.get("path") or s.get("chart", "") for s in srcs),
            "target_revision": join(s.get("targetRevision", "") for s in srcs),
            "synced_revision": (st.get("sync") or {}).get("revision", "") or join((st.get("sync") or {}).get("revisions") or []),
            "sync": (st.get("sync") or {}).get("status", ""), "health": (st.get("health") or {}).get("status", ""),
            "auto_sync": "Y" if (spec.get("syncPolicy") or {}).get("automated") is not None else "N",
            "last_sync": op.get("finishedAt", "") or (hist[-1].get("deployedAt", "") if hist else ""),
            "last_sync_phase": op.get("phase", ""), "last_sync_by": sync_user,
            "workloads": join(workloads), "workload_count": len(workloads),
            "expose": join(exposes), "external_urls": join(summ.get("externalURLs") or []),
            "images": join(summ.get("images") or []),
            "owner_hint": join(a_hints + p_hints + (["repo 그룹=" + g for g in map(repo_group, repos) if g])),
            "created": md(a).get("creationTimestamp", ""),
        }
        app_rows.append(app_row)

        flags = []
        if app_row["sync"] and app_row["sync"] != "Synced":
            flags.append(app_row["sync"])
        if app_row["health"] and app_row["health"] != "Healthy":
            flags.append(app_row["health"])
        if not workloads:
            flags.append("워크로드 없음")
        svc_rows.append({
            "namespace": app_row["dest_namespace"], "service_name": name, "argocd_app": name, "project": app_row["project"],
            "workloads": app_row["workloads"], "repo": app_row["repo"], "path_or_chart": app_row["path_or_chart"],
            "external_urls": app_row["external_urls"], "expose": app_row["expose"], "images": app_row["images"],
            "last_sync_by": sync_user, "owner_hint": app_row["owner_hint"], "flags": ",".join(flags),
            "담당자(정)": "", "담당자(부)": "", "팀": "", "근거": "", "신뢰도": "", "분리 처리": "", "비고": "",
        })

    # 이 클러스터를 대상으로 앱을 찍어내는 ApplicationSet
    set_rows = []
    for s in appsets:
        blob = json.dumps(s.get("spec") or {})
        gens = [list(g.keys())[0] for g in ((s.get("spec") or {}).get("generators") or []) if g]
        hit = (srv in blob) or (cname and '"{}"'.format(cname) in blob) or ("clusters" in gens)
        if hit:
            set_rows.append({"applicationset": md(s).get("name"), "namespace": md(s).get("namespace"),
                             "generators": ",".join(gens),
                             "match": "server/name 명시" if (srv in blob or (cname and '"{}"'.format(cname) in blob)) else "clusters 제너레이터(전체 대상 가능)"})
    return app_rows, res_rows, svc_rows, missing, expose, set_rows


# --------------------------------------------------------------------------- output

def print_services(cluster, svc_rows, out):
    w = [26, 34, 22, 34]
    out.write("\n== ArgoCD 기준 서비스 목록: {} ({}) — 앱 {}개 ==\n\n".format(cluster["name"], cluster["server"], len(svc_rows)))
    out.write("{}{}{}{}{}\n".format(pad("NAMESPACE", w[0]), pad("SERVICE(App)", w[1]), pad("PROJECT", w[2]), pad("워크로드", w[3]), "상태"))
    out.write("-" * (sum(w) + 20) + "\n")
    for r in sorted(svc_rows, key=lambda x: (x["namespace"], x["service_name"])):
        out.write("{}{}{}{}{}\n".format(pad(r["namespace"] or "-", w[0]), pad(r["service_name"], w[1]), pad(r["project"], w[2]),
                                        pad(r["workloads"] or "-", w[3]), r["flags"] or "OK"))


def write_outputs(outdir, cluster, ips, app_rows, res_rows, svc_rows, missing, expose, set_rows, warnings, started):
    os.makedirs(outdir, exist_ok=True)
    write_csv(os.path.join(outdir, "services.csv"),
              ["namespace", "service_name", "argocd_app", "project", "workloads", "repo", "path_or_chart", "external_urls",
               "expose", "images", "last_sync_by", "owner_hint", "flags",
               "담당자(정)", "담당자(부)", "팀", "근거", "신뢰도", "분리 처리", "비고"], svc_rows)
    write_csv(os.path.join(outdir, "apps.csv"),
              ["app", "app_namespace", "project", "dest_name", "dest_server", "dest_namespace", "repo", "path_or_chart",
               "target_revision", "synced_revision", "sync", "health", "auto_sync", "last_sync", "last_sync_phase",
               "last_sync_by", "workload_count", "workloads", "expose", "external_urls", "images", "owner_hint", "created"], app_rows)
    write_csv(os.path.join(outdir, "app_resources.csv"), ["app", "namespace", "group", "kind", "name", "role", "sync", "health"], res_rows)
    write_csv(os.path.join(outdir, "missing.csv"), ["app", "namespace", "kind", "name", "sync", "health"], missing)
    write_csv(os.path.join(outdir, "applicationsets.csv"), ["applicationset", "namespace", "generators", "match"], set_rows)

    by_proj = defaultdict(int)
    for a in app_rows:
        by_proj[a["project"]] += 1
    out_sync = [a for a in app_rows if a["sync"] != "Synced"]
    unhealthy = [a for a in app_rows if a["health"] not in ("Healthy", "")]
    lines = ["## ArgoCD 기준 서비스 인벤토리 요약", "",
             "- 수집 시각: {}".format(started.strftime("%Y-%m-%d %H:%M:%S")),
             "- 대상 클러스터: {} / {} / IP {}".format(cluster["name"], cluster["server"], ", ".join(ips) or "확인 불가"),
             "- 앱 {}개, 관리 리소스 {}개 (워크로드 {}개), Missing {}개".format(
                 len(app_rows), len(res_rows), sum(1 for r in res_rows if r["role"] == "워크로드"), len(missing)),
             "- OutOfSync 등 {}개, Healthy 아님 {}개, 관련 ApplicationSet {}개".format(len(out_sync), len(unhealthy), len(set_rows)),
             "", "### 프로젝트별 앱 수", "", "| project | 앱 수 |", "| --- | --- |"]
    lines += ["| {} | {} |".format(p, c) for p, c in sorted(by_proj.items(), key=lambda x: -x[1])]
    if missing:
        lines += ["", "### Missing 리소스", ""] + ["- {} → {}/{}/{}".format(m["app"], m["namespace"], m["kind"], m["name"]) for m in missing]
    if warnings:
        lines += ["", "### 수집 경고", ""] + ["- " + w for w in warnings]
    lines += ["", "### 다음 단계", "",
              "- 대상 클러스터 master 에서 xu_k8s_inventory.py 결과와 app_resources.csv 를 비교 (네임스페이스/kind/이름 키)",
              "- 클러스터 쪽에만 있는 워크로드 = ArgoCD 밖 배포 → Helm·Jenkins 로 추적"]
    with open(os.path.join(outdir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(outdir, "services.txt"), "w", encoding="utf-8") as f:
        print_services(cluster, svc_rows, f)


def main():
    ap = argparse.ArgumentParser(description="ArgoCD 기준 서비스 인벤토리 수집기 (대화형, 읽기 전용)")
    ap.add_argument("--kubectl", default=os.environ.get("KUBECTL", "kubectl"))
    ap.add_argument("--kubeconfig")
    ap.add_argument("--context")
    ap.add_argument("--argocd-ns", default="argocd", help="ArgoCD 설치 네임스페이스 (기본: argocd)")
    ap.add_argument("--cluster", help="클러스터 이름 (지정하면 첫 질문 생략)")
    ap.add_argument("-y", "--yes", action="store_true", help="서버 확인 질문 생략 (비대화형)")
    ap.add_argument("-o", "--out", help="출력 디렉터리 (기본: argo-inv-<클러스터>-YYYYmmdd-HHMM)")
    ap.add_argument("--page-size", type=int, default=500, help="API 페이지 크기 (기본 500)")
    ap.add_argument("--throttle", type=float, default=0.3, help="페이지·호출 사이 대기 초 (기본 0.3)")
    ap.add_argument("--min-free-mb", type=int, default=2048, help="노드에 남겨둘 최소 메모리 (기본 2048MB)")
    ap.add_argument("--timeout", type=int, default=120, help="kubectl 호출 1회 타임아웃(초)")
    ap.add_argument("--dry-run", action="store_true", help="실행하지 않고 호출할 kubectl 명령만 출력")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args()
    if args.page_size < 50 or args.page_size > 1000:
        raise SystemExit("--page-size 는 50~1000 사이로 지정")
    try:
        os.nice(10)
    except (OSError, AttributeError):
        pass

    os.umask(0o077)  # 결과 파일은 실행한 사용자만 읽기
    started = datetime.datetime.now()
    kube = Kube(args.kubectl, args.kubeconfig, args.context, args.timeout, args.page_size, args.throttle, args.dry_run)
    rc, ctx, _ = kube.run(["config", "current-context"])
    log("context: {}".format(ctx.strip() or "(알 수 없음)"))
    mem = mem_available_mb()
    if mem is not None and mem < args.min_free_mb + 300 and not args.dry_run:
        raise SystemExit("[중단] 이 노드 남은 메모리 {}MB — 다른 노드에서 실행하거나 --min-free-mb 조정".format(mem))

    log("Application 조회 ({}개씩 페이지, 읽기 전용)".format(args.page_size))
    apps = kube.list_raw(ARGO_API + "/applications", transform=slim_app, page_size=50)  # 앱 객체가 커서 작은 페이지
    time.sleep(args.throttle)
    log("AppProject / ApplicationSet 조회")
    projects = kube.list_raw(ARGO_API + "/appprojects", optional=True, transform=slim_project)
    time.sleep(args.throttle)
    appsets = kube.list_raw(ARGO_API + "/applicationsets", optional=True, transform=slim_appset)
    time.sleep(args.throttle)
    log("ArgoCD 등록 클러스터 조회 ({} 네임스페이스)".format(args.argocd_ns))
    clusters = load_clusters(kube, args.argocd_ns, apps)
    if args.dry_run:
        log("dry-run 끝: kubectl 호출 {}건, 클러스터에 아무 요청도 보내지 않음".format(kube.calls))
        return
    log("등록 클러스터 {}개, Application {}개".format(len(clusters), len(apps)))

    cluster, ips = choose_cluster(clusters, args.cluster, args.yes)
    app_rows, res_rows, svc_rows, missing, expose, set_rows = analyze(cluster, apps, projects, appsets)

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", cluster["name"] or "cluster")
    outdir = args.out or "argo-inv-{}-{}".format(safe, started.strftime("%Y%m%d-%H%M"))
    write_outputs(outdir, cluster, ips, app_rows, res_rows, svc_rows, missing, expose, set_rows, kube.warnings, started)
    print_services(cluster, svc_rows, sys.stdout)
    log("완료: {}/ (services.csv, apps.csv, app_resources.csv, summary.md 등)".format(outdir))


if __name__ == "__main__":
    main()
