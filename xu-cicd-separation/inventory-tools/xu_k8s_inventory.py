#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xu K8s 서비스 인벤토리 수집기

kubectl 이 설치된 master 노드에서 실행. 표준 라이브러리만 사용 (Python 3.6+).

운영 영향 방지 장치
  - 허용된 읽기 명령(get, get --raw, api-resources, config current-context, version)만 실행.
    그 외 kubectl 명령은 실행 전에 차단 (create/apply/patch/delete/scale/exec/auth 등)
  - 목록은 API 페이지 단위(기본 500개)로 받고 페이지 사이 대기(기본 0.3초) → apiserver·etcd 순간 부하 제한
  - 받은 즉시 필요한 필드만 남기고 나머지 버림 → master 노드 메모리 사용 제한
  - 시작 전 예상 조회량·남은 메모리 확인 후 y/N 확인, 낮은 CPU 우선순위(nice)로 실행
  - --dry-run 으로 실제 실행 없이 호출할 명령만 출력 가능

수집 내용
  - 최상위 워크로드 (ownerReferences 를 끝까지 따라가 Operator CR 까지 해석)
  - 배포 경로 추정 (ArgoCD / Helm / kubectl / Operator / 단독 Pod)
  - 노출 (Ingress, HTTPRoute, LoadBalancer, NodePort) 과 ExternalName 의존성
  - ArgoCD Application (클러스터 안에 있으면), Missing 리소스
  - Helm 릴리즈 차트 이름·버전 (--helm-releases 지정 시에만, 배포 경로 판정은 annotation 으로 항상 함)
  - 담당자 단서 (owner/team 계열 label·annotation, 네임스페이스 RoleBinding)
  - ConfigMap 안의 I 지역 참조 (--ref-pattern 지정 시)
  - 네임스페이스 리소스 타입별 개수 (CRD 포함, --resource-scan 지정 시에만)

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
import time
import unicodedata
from collections import OrderedDict, defaultdict
from urllib.parse import urlencode

VERSION = "1.2.0"
LAST_APPLIED = "kubectl.kubernetes.io/last-applied-configuration"
API_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*/[a-z0-9]+$")
KIND_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
RESOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")

# 객체 하나가 큰 리소스는 페이지를 작게 (응답 바이트 = etcd 단일 range read 크기)
PAGE_CAP = {"helm_secrets": 20, "configmaps": 50, "argo_apps": 50}

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

def is_read_only(args):
    """허용된 읽기 명령만 True. kubectl get --raw 는 항상 HTTP GET."""
    if not args:
        return False
    if args[0] == "get":
        return not any(a in ("-w", "--watch", "--watch-only") or a.startswith("--watch") for a in args)
    if args[:2] == ["config", "current-context"]:
        return True
    return args[0] in ("api-resources", "version")


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

    def _fail(self, what, err, rc, optional):
        msg = "{} 조회 실패: {}".format(what, (err.strip().splitlines() or [str(rc)])[-1])
        if optional:
            self.warnings.append(msg)
            log("  (건너뜀) " + msg)
            return []
        raise SystemExit("[오류] " + msg)

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
                return self._fail(path, err, rc, optional)
            try:
                d = json.loads(out)
            except ValueError:
                return self._fail(path, "응답이 JSON 이 아님", rc, optional)
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

    def count(self, path, selector=None):
        """limit=1 조회로 전체 개수 추정 (remainingItemCount)"""
        q = [("limit", "1")] + ([("labelSelector", selector)] if selector else [])
        rc, out, err = self.run(["get", "--raw", path + "?" + urlencode(q)])
        if self.dry_run or rc != 0:
            return None, err
        try:
            d = json.loads(out)
        except ValueError:
            return None, "응답이 JSON 이 아님"
        n = len(d.get("items") or [])
        meta = d.get("metadata") or {}
        if not meta.get("continue"):
            return n, ""
        rem = meta.get("remainingItemCount")
        return (n + rem if rem is not None else None), ""

    def plural_of(self, api_version, kind):
        """discovery(GET /apis/<group>/<version>)로 kind 의 복수형 리소스 이름을 찾음"""
        if not API_VERSION_RE.match(api_version or "") or not KIND_RE.match(kind or ""):
            return None
        rc, out, err = self.run(["get", "--raw", "/apis/" + api_version])
        if rc != 0 or self.dry_run:
            return None
        try:
            for r in json.loads(out).get("resources") or []:
                if r.get("kind") == kind and "/" not in r.get("name", "") and "list" in (r.get("verbs") or []):
                    return r["name"]
        except ValueError:
            pass
        return None


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


def strip_userinfo(url):
    """https://user:token@host/... → https://host/... (CSV 에 자격증명이 남지 않게)"""
    return re.sub(r"^([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@]*@", r"\1", url or "")


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

API = OrderedDict([
    ("namespaces", "/api/v1/namespaces"),
    ("deployments", "/apis/apps/v1/deployments"),
    ("statefulsets", "/apis/apps/v1/statefulsets"),
    ("daemonsets", "/apis/apps/v1/daemonsets"),
    ("cronjobs", "/apis/batch/v1/cronjobs"),
    ("jobs", "/apis/batch/v1/jobs"),
    ("replicasets", "/apis/apps/v1/replicasets"),
    ("pods", "/api/v1/pods"),
    ("services", "/api/v1/services"),
    ("ingresses", "/apis/networking.k8s.io/v1/ingresses"),
    ("httproutes", "/apis/gateway.networking.k8s.io/v1/httproutes"),
    ("grpcroutes", "/apis/gateway.networking.k8s.io/v1/grpcroutes"),
    ("argo_apps", "/apis/argoproj.io/v1alpha1/applications"),
    ("helm_secrets", "/api/v1/secrets"),
    ("rolebindings", "/apis/rbac.authorization.k8s.io/v1/rolebindings"),
    ("configmaps", "/api/v1/configmaps"),
])
REQUIRED = {"namespaces", "deployments", "statefulsets", "daemonsets", "jobs", "replicasets", "pods", "services"}


def slim_meta(o, keep_managers=True):
    m = md(o)
    ann = dict(m.get("annotations") or {})
    if LAST_APPLIED in ann:
        ann[LAST_APPLIED] = "(있음)"  # 큰 값이라 존재 여부만 남김
    out = {k: m[k] for k in ("name", "namespace", "uid", "labels", "ownerReferences", "generateName", "creationTimestamp")
           if m.get(k) is not None}
    out["annotations"] = ann
    if keep_managers:
        out["managedFields"] = [{"manager": x["manager"]} for x in (m.get("managedFields") or []) if x.get("manager")]
    return out


def slim_podspec(ps):
    return {"containers": [{"image": c.get("image")} for c in ps.get("containers") or []],
            "initContainers": [{"image": c.get("image")} for c in ps.get("initContainers") or []]}


def slim_workload(o):
    kind, spec, st = o.get("kind"), o.get("spec") or {}, o.get("status") or {}
    s = {k: spec[k] for k in ("replicas", "schedule", "suspend") if k in spec}
    ps = slim_podspec(pod_spec(o))
    if kind == "Pod":
        s.update(ps)
        st = {"phase": st.get("phase"), "containerStatuses": [{"ready": c.get("ready")} for c in st.get("containerStatuses") or []]}
    else:
        if kind == "CronJob":
            s["jobTemplate"] = {"spec": {"template": {"spec": ps}}}
        else:
            s["template"] = {"spec": ps}
        st = {k: st[k] for k in ("readyReplicas", "desiredNumberScheduled", "numberReady", "lastScheduleTime",
                                 "succeeded", "failed") if k in st}
    return {"kind": kind, "metadata": slim_meta(o, keep_managers=kind not in ("Pod", "ReplicaSet")), "spec": s, "status": st}


def slim_service(o):
    spec = o.get("spec") or {}
    return {"kind": o.get("kind"), "metadata": slim_meta(o, False),
            "spec": {"type": spec.get("type", "ClusterIP"), "selector": spec.get("selector"),
                     "externalName": spec.get("externalName"),
                     "ports": [{"nodePort": p.get("nodePort")} for p in spec.get("ports") or []]},
            "status": {"loadBalancer": (o.get("status") or {}).get("loadBalancer") or {}}}


def slim_spec_only(o):
    return {"kind": o.get("kind"), "metadata": slim_meta(o, False), "spec": o.get("spec") or {}}


def slim_rolebinding(o):
    return {"kind": o.get("kind"), "metadata": slim_meta(o, False), "roleRef": o.get("roleRef") or {},
            "subjects": [s for s in o.get("subjects") or [] if s.get("kind") in ("User", "Group")]}


def slim_argo_app(o):
    spec, st = o.get("spec") or {}, o.get("status") or {}
    return {"kind": "Application", "metadata": slim_meta(o, False),
            "spec": {k: spec.get(k) for k in ("project", "source", "sources", "destination")},
            "status": {"sync": {"status": (st.get("sync") or {}).get("status")},
                       "health": {"status": (st.get("health") or {}).get("status")},
                       "resources": [{"namespace": r.get("namespace", ""), "kind": r.get("kind", ""), "name": r.get("name", ""),
                                      "status": r.get("status", ""), "health": {"status": (r.get("health") or {}).get("status")}}
                                     for r in st.get("resources") or []]}}


def slim_helm_secret(o):
    """차트 이름·버전만 뽑고 시크릿 데이터는 즉시 버림"""
    return {"kind": "Secret", "metadata": {"namespace": md(o).get("namespace", ""), "name": md(o).get("name", ""),
                                           "labels": md(o).get("labels") or {}},
            "_chart": decode_helm_release(o)}


def make_cm_matcher(pattern, sink):
    pat = re.compile(pattern)

    def f(cm):
        ns = md(cm).get("namespace", "")
        for dk, dv in (cm.get("data") or {}).items():
            ms = list(pat.finditer(dv or ""))
            if ms:
                # 주변 문맥(비밀번호 등)이 섞이지 않게 매칭된 문자열만 남김
                hits = sorted({m.group(0) for m in ms})[:5]
                sink.append({"namespace": ns, "configmap": md(cm).get("name"), "key": dk,
                             "matches": len(ms), "snippet": " | ".join(hits)})
        return None  # ConfigMap 본문은 보관하지 않음
    return f


TRANSFORM = {"namespaces": lambda o: {"kind": "Namespace", "metadata": slim_meta(o, False)},
             "services": slim_service, "ingresses": slim_spec_only, "httproutes": slim_spec_only,
             "grpcroutes": slim_spec_only, "argo_apps": slim_argo_app, "helm_secrets": slim_helm_secret,
             "rolebindings": slim_rolebinding}
for _k in ("deployments", "statefulsets", "daemonsets", "cronjobs", "jobs", "replicasets", "pods"):
    TRANSFORM[_k] = slim_workload


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


def selector_for(key):
    # 최신(deployed) 리비전만: 과거 리비전 시크릿까지 받으면 조회량이 리비전 수배로 늘어남
    return "owner=helm,status=deployed" if key == "helm_secrets" else None


def preflight(kube, args):
    """조회 전에 대상 개수·페이지 수·남은 메모리를 보여주고 확인받음"""
    keys = [k for k in API if (k != "configmaps" or args.ref_pattern) and (k != "helm_secrets" or args.helm_releases)]
    rows, total_pages = [], 0
    for k in keys:
        n, err = kube.count(API[k], selector_for(k))
        if n is None and err and k in REQUIRED:
            raise SystemExit("[오류] {} 조회 권한/접속 확인 실패: {}".format(k, (err.strip().splitlines() or ["?"])[-1]))
        ps = min(PAGE_CAP.get(k, kube.page_size), kube.page_size)
        pages = (n // ps + 1) if n is not None else 1
        total_pages += pages
        rows.append((k, "-" if n is None else n, pages))
        time.sleep(kube.throttle)
    if kube.dry_run:
        return
    print("\n조회 예정 (읽기 전용, {}개씩 페이지 조회, 페이지 간 {}초 대기)".format(kube.page_size, kube.throttle))
    for k, n, p in rows:
        print("  {:<14} {:>8}개  {:>4}페이지".format(k, n, p))
    est = total_pages * (kube.throttle + 0.5)
    print("  총 {}페이지, 예상 소요 약 {:.0f}초 + CR 조회{}".format(total_pages, est, " + 리소스 스캔" if args.resource_scan else ""))
    mem = mem_available_mb()
    pods = next((n for k, n, _ in rows if k == "pods" and n != "-"), 0)
    need = 450 + pods * 0.01  # 슬림 보관분 + 페이지 1개 처리 중 버퍼(원본의 4~5배) 대략치 (MB)
    if mem is not None:
        print("  이 노드 남은 메모리 {} MB / 예상 사용 약 {:.0f} MB (최소 여유 기준 {} MB)".format(mem, need, args.min_free_mb))
        if mem - need < args.min_free_mb:
            raise SystemExit("[중단] 남은 메모리가 부족함. master 대신 다른 노드에서 실행하거나 --min-free-mb 조정")
    if not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit("[중단] 비대화형 실행은 --yes 필요")
        if input("\n진행할까요? [y/N] > ").strip().lower() not in ("y", "yes", "ㅛ"):
            raise SystemExit("취소함")


def mem_available_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (IOError, OSError, ValueError):
        return None
    return None


def collect(kube, args):
    data = {"cm_refs": []}
    data["helm_secrets"] = []
    for k, path in API.items():
        if k == "helm_secrets" and not args.helm_releases:
            continue  # 기본 꺼짐: selector 를 써도 etcd 에서는 시크릿 전체를 읽음 (helm list -A 와 같은 부하)
        if k == "configmaps":
            if args.ref_pattern:
                log("configmaps 조회 (I 지역 참조 검색, 본문은 보관 안 함)")
                kube.list_raw(path, optional=True, transform=make_cm_matcher(args.ref_pattern, data["cm_refs"]),
                              page_size=PAGE_CAP["configmaps"])
            continue
        log("{} 조회".format(k))
        data[k] = kube.list_raw(path, selector=selector_for(k), optional=k not in REQUIRED, transform=TRANSFORM.get(k),
                                page_size=PAGE_CAP.get(k))
        time.sleep(kube.throttle)
    return data


def fetch_cr_roots(kube, cr_kinds):
    """오너 체인 끝에 있는 CR 을 kind.group 단위로 한 번씩 조회"""
    out = {}
    for (api_version, kind) in sorted(cr_kinds):
        plural = kube.plural_of(api_version, kind)
        time.sleep(kube.throttle)
        if not plural:
            kube.warnings.append("CR {} ({}) 경로 확인 실패 — 이름만 사용".format(kind, api_version))
            continue
        log("CR 조회: {}/{}".format(api_version, plural))
        for o in kube.list_raw("/apis/{}/{}".format(api_version, plural), optional=True, page_size=100,
                               transform=lambda o: {"kind": o.get("kind"), "apiVersion": o.get("apiVersion"),
                                                    "metadata": slim_meta(o), "spec": {}, "status": {}}):
            out[md(o).get("uid")] = o
        time.sleep(kube.throttle)
    return out


def resource_scan(kube):
    rc, out, err = kube.run(["api-resources", "--verbs=list", "--namespaced", "-o", "name"])
    if rc != 0:
        kube.warnings.append("api-resources 실패: " + err.strip())
        return []
    rows = []
    skip = {"events", "events.events.k8s.io", "secrets", "configmaps"}
    types = [t for t in out.split() if t and t not in skip and RESOURCE_RE.match(t)]
    log("리소스 타입 스캔: {}개 타입 (서버 측 표 형식으로 이름만 받음)".format(len(types)))
    for i, t in enumerate(types, 1):
        time.sleep(kube.throttle)
        # 기본 표 출력은 서버가 행(이름 등)만 내려줌 → 객체 전체를 받지 않음
        rc, o, e = kube.run(["get", t, "-A", "--no-headers", "--chunk-size={}".format(kube.page_size)])
        if rc != 0:
            kube.warnings.append("{} 스캔 실패".format(t))
            continue
        cnt = defaultdict(int)
        for line in o.splitlines():
            parts = line.split()
            if parts:
                cnt[parts[0]] += 1
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
            if ref.get("kind") == "Node" or "/" not in (ref.get("apiVersion") or ""):
                return chain, None  # static(mirror) Pod 등 코어 리소스 소유 → 그 객체 자체가 루트
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
                                "status": l.get("status", ""), "_chart": s.get("_chart") or {}}
    for h in helm.values():
        h.update(h.pop("_chart"))

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
            "dest_namespace": dest.get("namespace", ""), "repo": strip_userinfo(src.get("repoURL", "")),
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
                if any(r.get("kind") == "Node" for r in md(base).get("ownerReferences") or []):
                    paths.append("StaticPod")
                elif "dag_id" in l or "airflow-worker" in l or "kubernetes_pod_operator" in l:
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

    cm_rows = [r for r in data["cm_refs"] if ns_ok(r["namespace"])]

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
    out.write("\n== xu K8s 서비스 목록: 서비스 {}개 / 워크로드 {}개 / 네임스페이스 {}개 ==\n\n".format(
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
    lines = ["## xu K8s 서비스 인벤토리 요약", "",
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
    ap = argparse.ArgumentParser(description="xu K8s 서비스 인벤토리 수집기 (읽기 전용)")
    ap.add_argument("--kubectl", default=os.environ.get("KUBECTL", "kubectl"), help="kubectl 경로 (기본: kubectl)")
    ap.add_argument("--kubeconfig", help="kubeconfig 경로")
    ap.add_argument("--context", help="kubeconfig context")
    ap.add_argument("-o", "--out", help="출력 디렉터리 (기본: inv-YYYYmmdd-HHMM)")
    ap.add_argument("--ref-pattern", help="ConfigMap 에서 찾을 I 지역 참조 정규식 (예: 'i-region\\.example\\.com|10\\.10\\.')")
    ap.add_argument("--exclude-ns", help="제외할 네임스페이스 정규식")
    ap.add_argument("--system-ns", default=r"^(kube-|default$)", help="system 플래그를 붙일 네임스페이스 정규식")
    ap.add_argument("--helm-releases", action="store_true",
                    help="Helm 릴리즈 시크릿에서 차트 이름·버전 조회 (helm list -A 와 같은 부하, 기본 꺼짐)")
    ap.add_argument("--resource-scan", action="store_true", help="CRD 포함 전 리소스 타입별 개수 스캔 (조회량 많음, 기본 꺼짐)")
    ap.add_argument("--page-size", type=int, default=500, help="API 페이지 크기 (기본 500)")
    ap.add_argument("--throttle", type=float, default=0.3, help="페이지·호출 사이 대기 초 (기본 0.3)")
    ap.add_argument("--min-free-mb", type=int, default=2048, help="실행 후에도 남겨둘 노드 메모리 (기본 2048MB)")
    ap.add_argument("--timeout", type=int, default=120, help="kubectl 호출 1회 타임아웃(초)")
    ap.add_argument("-y", "--yes", action="store_true", help="조회 전 확인 질문 생략")
    ap.add_argument("--dry-run", action="store_true", help="실행하지 않고 호출할 kubectl 명령만 출력")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args()
    if args.page_size < 50 or args.page_size > 1000:
        raise SystemExit("--page-size 는 50~1000 사이로 지정")

    try:
        os.nice(10)  # kubectl 자식 프로세스까지 낮은 CPU 우선순위
    except (OSError, AttributeError):
        pass

    os.umask(0o077)  # 결과 파일은 실행한 사용자만 읽기 (내부 호스트·IP·권한 정보 포함)
    started = datetime.datetime.now()
    outdir = args.out or "inv-" + started.strftime("%Y%m%d-%H%M")
    kube = Kube(args.kubectl, args.kubeconfig, args.context, args.timeout, args.page_size, args.throttle, args.dry_run)

    rc, out, err = kube.run(["config", "current-context"])
    log("context: {}".format(out.strip() or "(알 수 없음)"))
    preflight(kube, args)
    data = collect(kube, args)
    if args.dry_run:
        print("DRY-RUN  (이후 Operator CR 이 있으면 'kubectl get <kind>.<group> -A -o json' 이 kind 별 1회 추가됨)")
        if args.resource_scan:
            resource_scan(kube)
        log("dry-run 끝: kubectl 호출 {}건 (페이지 반복분 제외), 클러스터에 아무 요청도 보내지 않음".format(kube.calls))
        return
    res = analyze(kube, data, args)
    scan_rows = resource_scan(kube) if args.resource_scan else []
    write_outputs(res, outdir, scan_rows, kube.warnings, started)
    print_services(res, sys.stdout)
    log("완료: {}/ (services.csv, workloads.csv, summary.md 등)".format(outdir))


if __name__ == "__main__":
    main()
