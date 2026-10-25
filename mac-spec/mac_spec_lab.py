#!/usr/bin/env python3
"""mac_spec_lab.py - Mac 사양 확인 실습 + 로컬 AI 구성 가능 범위 계산

실행
  python3 mac_spec_lab.py              # 실습 모드 : 명령을 직접 쳐보며 진행
  python3 mac_spec_lab.py --auto       # 입력 없이 전부 자동 실행
  python3 mac_spec_lab.py --ctx 32768  # 로컬 AI 계산 시 컨텍스트 길이 지정 (기본 8192)
  python3 mac_spec_lab.py --demo       # 맥이 아닌 곳에서 흐름 확인용 (샘플 출력)

입력 편의 (실습 모드)
  Tab      : 다음 단어 자동완성 (한 번에 한 단어씩)
  ↑ / ↓    : 이전에 친 명령 불러오기 (~/.mac_spec_lab_history 에 저장)

출력
  ~/mac-spec-report-YYYYMMDD.md  (사양 요약 + 로컬 AI 계산 + 실습 로그)

표준 라이브러리만 사용함. 실행하는 명령은 아래 STEPS 에 정의된 조회 명령뿐이고,
사용자가 입력한 문자열은 정답 비교에만 쓰고 직접 실행하지 않음.
"""
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys

# ---------------------------------------------------------------- 터미널 색 (Autumn leaves 근사)
USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text, code):
    return "\033[{}m{}\033[0m".format(code, text) if USE_COLOR else text


def h1(t):   return c(t, "1;38;5;214")   # #FFB343
def h2(t):   return c(t, "1;38;5;172")   # #DB9A39
def dim(t):  return c(t, "38;5;137")     # #B37E2E
def ink(t):  return c(t, "38;5;94")      # #614419
def ok(t):   return c(t, "1;38;5;71")
def warn(t): return c(t, "1;38;5;167")


# ---------------------------------------------------------------- 실습 단계 정의
# key  : 결과를 담을 이름 / parse : 파서 이름 / sensitive : 로그 기록 안 함
STEPS = [
    dict(group="1. OS 와 아키텍처", key="os", title="OS 버전", cmd="sw_vers",
         purpose="macOS 버전과 빌드 번호 확인",
         check="ProductVersion 이 macOS 버전임. 27 이상이면 Apple Silicon 전용 버전임", parse="sw_vers"),
    dict(group="1. OS 와 아키텍처", key="arch", title="아키텍처", cmd="uname -m",
         purpose="칩 계열 확인",
         check="arm64 = Apple Silicon, x86_64 = Intel (또는 Rosetta 터미널)", parse="strip"),
    dict(group="1. OS 와 아키텍처", key="rosetta", title="Rosetta 실행 여부", cmd="sysctl -n sysctl.proc_translated",
         purpose="지금 터미널이 Rosetta 로 돌고 있는지 확인",
         check="1 = Rosetta, 0 = 네이티브. Intel 맥은 에러가 정상임", parse="strip", optional=True),
    dict(group="2. 칩", key="chip", title="칩 이름", cmd="sysctl -n machdep.cpu.brand_string",
         purpose="정확한 칩 모델 확인",
         check="-n 을 빼고 쳐보면 키 이름까지 같이 나옴. 차이를 비교해봄", parse="strip"),
    dict(group="3. CPU 코어", key="ncpu", title="전체 코어", cmd="sysctl -n hw.ncpu",
         purpose="논리 코어 수 확인", check="Apple Silicon 은 하이퍼스레딩이 없어서 물리 코어와 같음", parse="int"),
    dict(group="3. CPU 코어", key="pcore", title="성능(P) 코어", cmd="sysctl -n hw.perflevel0.physicalcpu",
         purpose="고성능 코어 수 확인", check="Intel 은 이 키가 없어서 에러가 정상임", parse="int", optional=True),
    dict(group="3. CPU 코어", key="ecore", title="효율(E) 코어", cmd="sysctl -n hw.perflevel1.physicalcpu",
         purpose="저전력 코어 수 확인", check="P + E = 전체 코어 인지 다음 화면에서 자동 검산함", parse="int", optional=True),
    dict(group="4. 메모리", key="memsize", title="메모리 (바이트)", cmd="sysctl -n hw.memsize",
         purpose="총 메모리 확인", check="1024 로 세 번 나누면 GB. 자동 환산해서 보여줌", parse="int"),
    dict(group="4. 메모리", key="mempress", title="메모리 여유율", cmd="memory_pressure | tail -1",
         purpose="지금 메모리 압박 수준 확인", check="여유율이 20% 아래로 계속 머물면 스왑 사용 가능성이 큼", parse="percent"),
    dict(group="5. 모델 정보 (JSON)", key="hwjson", title="하드웨어 전체 (보기만)", cmd="system_profiler SPHardwareDataType -json",
         purpose="JSON 구조 눈으로 확인. 시리얼이 들어 있어서 리포트에는 기록 안 함",
         check="SPHardwareDataType 배열 → 0 번째 → 키 이름 구조를 봐둠", parse="none", sensitive=True),
    dict(group="5. 모델 정보 (JSON)", key="model", title="모델명",
         cmd="system_profiler SPHardwareDataType -json | plutil -extract SPHardwareDataType.0.machine_name raw -",
         purpose="JSON 에서 값 하나만 뽑기", check="plutil -extract <경로> raw - = 그 경로의 값만 출력. 마지막 - 는 표준입력", parse="plutil"),
    dict(group="5. 모델 정보 (JSON)", key="model_id", title="모델 식별자",
         cmd="system_profiler SPHardwareDataType -json | plutil -extract SPHardwareDataType.0.machine_model raw -",
         purpose="모델 식별자 확인", check="예 : Mac15,6. 같은 이름이라도 세대가 다르면 식별자가 다름", parse="plutil"),
    dict(group="6. GPU", key="gpu", title="GPU 이름",
         cmd="system_profiler SPDisplaysDataType -json | plutil -extract SPDisplaysDataType.0.sppci_model raw -",
         purpose="GPU 이름 확인", check="Apple Silicon 은 칩 이름과 같게 나옴", parse="plutil"),
    dict(group="6. GPU", key="gpu_cores", title="GPU 코어",
         cmd="system_profiler SPDisplaysDataType -json | plutil -extract SPDisplaysDataType.0.sppci_cores raw -",
         purpose="GPU 코어 수 확인", check="같은 칩이라도 GPU 코어 수가 다른 모델이 있음. 로컬 AI 속도에 영향 큼", parse="int", optional=True),
    dict(group="7. 스토리지", key="df", title="루트 볼륨 사용량", cmd="df -H /",
         purpose="디스크 크기 확인", check="-H = 1000 단위(Finder 와 같음), -h = 1024 단위", parse="df"),
    dict(group="7. 스토리지", key="container", title="APFS 컨테이너 여유",
         cmd="diskutil info / | grep -E 'Solid State|Container Total Space|Container Free Space'",
         purpose="실제 남은 공간 확인", check="APFS 는 볼륨끼리 공간을 나눠 씀. 실제 여유는 Container Free Space 로 봄", parse="container"),
    dict(group="8. 배터리", key="battery", title="배터리 원시값",
         cmd="ioreg -r -c AppleSmartBattery | grep -E '\"CycleCount\"|\"DesignCapacity\"|\"AppleRawMaxCapacity\"'",
         purpose="충전 사이클과 건강도 확인", check="건강도 ≈ AppleRawMaxCapacity ÷ DesignCapacity × 100. 데스크톱은 비어 있는 게 정상",
         parse="battery", optional=True),
]

QUIZ = {
    "1. OS 와 아키텍처": ("uname -m 결과가 arm64 면 무슨 칩일까?", ["Intel", "Apple Silicon"], 2,
                        "arm64 = Apple Silicon. 단, Rosetta 터미널이면 x86_64 로 보일 수 있음"),
    "3. CPU 코어": ("Apple Silicon 에서 hw.ncpu 와 같은 값은?", ["P 코어 × 2", "P 코어 + E 코어"], 2,
                  "하이퍼스레딩이 없어서 P + E 가 그대로 전체 코어임"),
    "4. 메모리": ("통합 메모리는 구매 후 늘릴 수 있을까?", ["가능", "불가"], 2,
                "칩 패키지에 붙어 있어서 증설 불가. 로컬 AI 는 처음 고른 메모리가 상한임"),
    "5. 모델 정보 (JSON)": ("스크립트에서 system_profiler 를 쓸 때 -json 을 쓰는 이유는?", ["출력이 빨라서", "항목 이름이 언어와 상관없이 고정이라서"], 2,
                          "텍스트 출력은 시스템 언어 따라 항목명이 바뀔 수 있음"),
    "7. 스토리지": ("APFS 에서 실제 남은 공간은 어디서 보는 게 정확할까?", ["df 의 Avail", "Container Free Space"], 2,
                  "볼륨들이 컨테이너 공간을 나눠 써서 컨테이너 기준이 정확함"),
}

# ---------------------------------------------------------------- 데모용 샘플 출력
DEMO = {
    "sw_vers": "ProductName:\t\tmacOS\nProductVersion:\t\t27.0\nBuildVersion:\t\t26A100",
    "uname -m": "arm64",
    "sysctl -n sysctl.proc_translated": "0",
    "sysctl -n machdep.cpu.brand_string": "Apple M4 Pro",
    "sysctl -n hw.ncpu": "14",
    "sysctl -n hw.perflevel0.physicalcpu": "10",
    "sysctl -n hw.perflevel1.physicalcpu": "4",
    "sysctl -n hw.memsize": "51539607552",
    "memory_pressure | tail -1": "System-wide memory free percentage: 58%",
    "system_profiler SPHardwareDataType -json": '{ "SPHardwareDataType" : [ { "machine_name" : "MacBook Pro", "serial_number" : "XXXXXXXXXX" } ] }',
    "model": "MacBook Pro", "model_id": "Mac16,8", "gpu": "Apple M4 Pro", "gpu_cores": "20",
    "df -H /": "Filesystem      Size   Used  Avail Capacity iused ifree %iused  Mounted on\n/dev/disk3s1s1  994G    12G   612G     2%    453k  4.3G    0%   /",
    "container": "   Solid State:               Yes\n   Container Total Space:     994.7 GB (994662584320 Bytes) (exactly 1942700360 512-Byte-Units)\n   Container Free Space:      612.3 GB (612330000000 Bytes) (exactly 1195957031 512-Byte-Units)",
    "battery": '      "AppleRawMaxCapacity" = 6120\n      "CycleCount" = 88\n      "DesignCapacity" = 6480',
}

# ---------------------------------------------------------------- 로컬 AI 계산 기준값
# 메모리 대역폭 GB/s (Apple 공개 사양). 키는 칩 이름 소문자, GPU 코어로 갈리는 칩은 (코어 수: 대역폭)
BANDWIDTH = {
    "m1": 68, "m1 pro": 200, "m1 max": 400, "m1 ultra": 800,
    "m2": 100, "m2 pro": 200, "m2 max": 400, "m2 ultra": 800,
    "m3": 100, "m3 pro": 150, "m3 max": {30: 300, 40: 400}, "m3 ultra": 819,
    "m4": 120, "m4 pro": 273, "m4 max": {32: 410, 40: 546},
    "m5": 153,
}
# (이름, 파라미터 수(B), KV 캐시 MB/토큰 (FP16, GQA 기준 근사))
MODELS = [
    ("1B급", 1.2, 0.03), ("3B급", 3.2, 0.11), ("8B급", 8.0, 0.13), ("14B급", 14.0, 0.19),
    ("24B급", 24.0, 0.16), ("32B급", 32.0, 0.25), ("70B급", 70.0, 0.31),
]
# (이름, 파라미터당 바이트)  Q4_K_M ≈ 4.85bit, Q8_0 ≈ 8.5bit
QUANTS = [("Q4", 0.61), ("Q8", 1.06), ("FP16", 2.0)]
OTHER = [("음성 인식 Whisper large-v3", 4), ("임베딩 모델 (RAG 검색용)", 1.5),
         ("이미지 생성 SDXL", 8), ("이미지 생성 FLUX.1 dev (FP8)", 16)]
RUNTIME_OVERHEAD_GB = 1.0
DECODE_EFF = 0.6        # 메모리 대역폭 실효율 근사
INTERACTIVE_TPS = 10    # 대화용 최소 속도 기준
SENSITIVE = re.compile(r"serial|일련|uuid|udid|provisioning", re.I)   # 로그에서 지울 식별 정보


# ---------------------------------------------------------------- 실행·파싱
def run(cmd, demo, key):
    if demo:
        out = DEMO.get(cmd, DEMO.get(key, ""))
        return 0, out
    shell = "/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/bash"
    try:
        p = subprocess.run(cmd, shell=True, executable=shell, capture_output=True, text=True, timeout=120)
        return p.returncode, (p.stdout + p.stderr).rstrip()
    except subprocess.TimeoutExpired:
        return 1, "(시간 초과)"


def parse(kind, out, rc):
    out = out.strip()
    if kind == "none":
        return None
    if rc != 0 and kind not in ("battery", "container"):
        return None
    try:
        if kind == "strip":
            return out.splitlines()[0].strip() if out else None
        if kind == "int":
            return int(out.split()[0])
        if kind == "plutil":
            return None if ("Could not" in out or not out) else out.splitlines()[0].strip()
        if kind == "percent":
            m = re.search(r"(\d+)%", out)
            return int(m.group(1)) if m else None
        if kind == "sw_vers":
            v = re.search(r"ProductVersion:\s*(\S+)", out)
            b = re.search(r"BuildVersion:\s*(\S+)", out)
            return {"version": v.group(1) if v else None, "build": b.group(1) if b else None}
        if kind == "df":
            cols = out.splitlines()[1].split()
            return {"size": cols[1], "used": cols[2], "avail": cols[3], "cap": cols[4]}
        if kind == "container":
            t = re.search(r"Container Total Space:\s*([\d.]+ [KMGT]B)", out)
            f = re.search(r"Container Free Space:\s*([\d.]+ [KMGT]B)", out)
            s = re.search(r"Solid State:\s*(\w+)", out)
            return {"total": t.group(1) if t else None, "free": f.group(1) if f else None,
                    "ssd": s.group(1) if s else None}
        if kind == "battery":
            g = lambda k: re.search(r'"{}"\s*=\s*(\d+)'.format(k), out)
            cyc, des, raw = g("CycleCount"), g("DesignCapacity"), g("AppleRawMaxCapacity")
            if not (cyc and des and raw):
                return None
            return {"cycle": int(cyc.group(1)), "health": round(int(raw.group(1)) * 100 / int(des.group(1)))}
    except (IndexError, ValueError, AttributeError):
        return None
    return out


def norm(s):
    return " ".join(s.replace('"', "'").split())


# ---------------------------------------------------------------- 입력 편의 : Tab 자동완성 · ↑↓ 히스토리
try:
    import readline
except ImportError:          # Windows 등 readline 없는 환경 → 기능 없이 동작
    readline = None

HISTORY_FILE = os.path.expanduser("~/.mac_spec_lab_history")
EXTRA_WORDS = ["sysctl -a", "sysctl hw", "system_profiler -listDataTypes", "df -h /", "diskutil list", "pmset -g batt"]
_complete = {"current": "", "pool": []}


def _completer(text, state):
    """줄 전체를 보고, 알려진 명령 중 앞부분이 같은 것의 '다음 한 단어'까지만 채움"""
    if state == 0:
        line = readline.get_line_buffer()
        pool = [_complete["current"]] + _complete["pool"]
        seen, cands = set(), []
        for cmd in pool:
            if not cmd or not cmd.startswith(line):
                continue
            rest = cmd[len(line):]
            if rest.startswith(" "):                 # 단어 끝까지 친 상태 → 공백 포함 다음 단어
                nxt = " " + rest[1:].split(" ")[0]
            else:
                nxt = rest.split(" ")[0]
                if len(cmd) > len(line) + len(nxt):  # 뒤에 더 있으면 공백까지 붙여줌
                    nxt += " "
            cand = line + nxt
            if cand not in seen:
                seen.add(cand)
                cands.append(cand)
        _complete["cands"] = cands
    cands = _complete.get("cands", [])
    return cands[state] if state < len(cands) else None


def setup_readline(enabled):
    if not (enabled and readline):
        return
    _complete["pool"] = [st["cmd"] for st in STEPS] + EXTRA_WORDS
    readline.set_completer(_completer)
    readline.set_completer_delims("")                # 줄 전체를 하나로 보고 완성
    if "libedit" in (readline.__doc__ or ""):        # macOS 기본 python3 (libedit)
        readline.parse_and_bind("bind ^I rl_complete")
    else:                                            # GNU readline
        readline.parse_and_bind("tab: complete")
        readline.parse_and_bind("set show-all-if-ambiguous on")
    readline.set_history_length(500)
    try:
        readline.read_history_file(HISTORY_FILE)
    except (OSError, IOError):
        pass


def save_history():
    if readline:
        try:
            readline.write_history_file(HISTORY_FILE)
        except (OSError, IOError):
            pass


def _rl_prompt(p):
    """색 코드를 readline 이 길이 계산에서 빼도록 감쌈 (↑↓ 로 줄 다시 그릴 때 깨짐 방지)"""
    if readline and USE_COLOR:
        return re.sub(r"(\033\[[0-9;]*m)", "\001\\1\002", p)
    return p


def _forget_last_history(before):
    """명령이 아닌 입력(Enter, 퀴즈 번호, s/q)은 히스토리에서 지움"""
    if not readline:
        return
    n = readline.get_current_history_length()
    if n > before:
        try:
            readline.remove_history_item(n - 1)
        except (ValueError, IndexError):
            pass


def ask(prompt, keep=False):
    before = readline.get_current_history_length() if readline else 0
    try:
        s = input(_rl_prompt(prompt))
    except EOFError:
        return ""
    except KeyboardInterrupt:
        print("\n중단함")
        save_history()
        sys.exit(1)
    if not keep or s.strip().lower() in ("", "s", "q"):
        _forget_last_history(before)
    return s


def type_command(cmd):
    """명령 직접 입력 연습. 반환 : True=실행, False=건너뜀, None=종료"""
    tries = 0
    _complete["current"] = cmd
    while True:
        s = ask(ink("  직접 쳐봐 (Enter=자동 입력, s=건너뛰기, q=종료, Tab=자동완성, ↑↓=이전 명령) > "), keep=True).strip()
        if s == "":
            print(dim("  → " + cmd))
            return True
        if s.lower() == "s":
            return False
        if s.lower() == "q":
            return None
        if norm(s) == norm(cmd):
            print(ok("  정확함"))
            return True
        tries += 1
        a, b = norm(s).split(), norm(cmd).split()
        i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
        hint = b[i] if i < len(b) else "(끝)"
        print(warn("  다름 → {}번째 단어부터 확인. 힌트 : '{}'".format(i + 1, hint)))
        if tries >= 2:
            print(dim("  정답 : " + cmd))


# ---------------------------------------------------------------- 로컬 AI 계산
def gb(v):
    return v / 1024 ** 3


def bandwidth_for(chip, gpu_cores):
    name = (chip or "").lower().replace("apple ", "").strip()
    if name in BANDWIDTH:          # 정확히 일치할 때만 (M5 Pro 를 M5 로 잘못 잡지 않게)
        bw = BANDWIDTH[name]
        if isinstance(bw, dict):
            if gpu_cores in bw:
                return bw[gpu_cores], "공개 사양"
            return min(bw.values()), "공개 사양 (GPU 코어 확인 못 해서 낮은 값)"
        return bw, "공개 사양"
    return None, None


def local_ai(r, ctx, interactive):
    total_gb = gb(r["memsize"]) if r.get("memsize") else None
    arch = r.get("arch") or ""
    apple = arch == "arm64" or (r.get("chip") or "").startswith("Apple")
    res = {"ctx": ctx, "apple": apple, "total_gb": total_gb}
    if not total_gb:
        return res
    if apple:
        ratio = 0.75 if total_gb >= 64 else 0.67      # macOS 기본 GPU 사용 한도 근사
        bw, src = bandwidth_for(r.get("chip"), r.get("gpu_cores"))
        if bw is None:
            if interactive:
                s = ask(ink("  칩 대역폭(GB/s)을 표에서 못 찾음. 알면 입력, 모르면 Enter > ")).strip()
                if s.replace(".", "", 1).isdigit():
                    bw, src = float(s), "직접 입력"
            if bw is None and r.get("gpu_cores"):
                bw, src = r["gpu_cores"] * 10, "GPU 코어 × 10 추정"
            if bw is None:
                bw, src = 100, "기본값 추정"
    else:
        ratio, bw, src = 0.5, 40, "Intel CPU 추론 근사"
    usable = total_gb * ratio
    res.update(ratio=ratio, usable=usable, bw=bw, bw_src=src)

    free_gb = None
    if r.get("container") and r["container"].get("free"):
        n, u = r["container"]["free"].split()
        free_gb = float(n) * {"KB": 1e-6, "MB": 1e-3, "GB": 1, "TB": 1000}[u]
    res["free_gb"] = free_gb

    rows = []
    for name, params, kv_mb in MODELS:
        for qn, bpp in QUANTS:
            weights = params * bpp
            need = weights + kv_mb * ctx / 1024 + RUNTIME_OVERHEAD_GB
            if need <= usable * 0.9:
                verdict = "여유"
            elif need <= usable:
                verdict = "빠듯"
            else:
                verdict = "불가"
            tps = bw * DECODE_EFF / weights
            rows.append(dict(model=name, params=params, quant=qn, file=weights, need=need, verdict=verdict, tps=tps))
    res["rows"] = rows
    fit = [x for x in rows if x["verdict"] != "불가"]
    daily = [x for x in fit if x["quant"] == "Q4" and x["verdict"] == "여유" and x["tps"] >= INTERACTIVE_TPS]
    res["daily"] = max(daily, key=lambda x: x["params"]) if daily else None
    res["max"] = max(fit, key=lambda x: (x["params"], -x["need"])) if fit else None
    res["other"] = [(n, m, "가능" if m <= usable * 0.9 else ("빠듯" if m <= usable else "불가")) for n, m in OTHER]
    return res


# ---------------------------------------------------------------- 리포트
def fmt(v, suffix=""):
    return "-" if v in (None, "") else "{}{}".format(v, suffix)


def report(r, logs, ai, path):
    today = datetime.date.today().isoformat()
    os_ = r.get("os") or {}
    df = r.get("df") or {}
    ct = r.get("container") or {}
    bat = r.get("battery")
    mem = "{:.0f} GB".format(ai["total_gb"]) if ai.get("total_gb") else "-"
    cores = "총 {} (P {} / E {})".format(fmt(r.get("ncpu")), fmt(r.get("pcore")), fmt(r.get("ecore")))
    L = []
    L.append("## 내 Mac 사양 리포트 ({})".format(today))
    L.append("")
    L.append("> **목표** : 실습으로 확인한 사양을 정리하고, 이 사양으로 로컬 AI 를 어디까지 돌릴 수 있는지 계산함")
    L.append("")
    L.append("- 생성 : mac_spec_lab.py")
    L.append("- 시리얼·하드웨어 UUID 는 수집·기록하지 않음")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 1. 사양 요약")
    L.append("")
    L.append("| 항목 | 값 |")
    L.append("|---|---|")
    L.append("| 모델 | {} ({}) |".format(fmt(r.get("model")), fmt(r.get("model_id"))))
    L.append("| 칩 | {} |".format(fmt(r.get("chip"))))
    L.append("| CPU 코어 | {} |".format(cores))
    L.append("| GPU | {} ({}코어) |".format(fmt(r.get("gpu")), fmt(r.get("gpu_cores"))))
    L.append("| 메모리 | {} (여유율 {}) |".format(mem, fmt(r.get("mempress"), "%")))
    L.append("| 스토리지 | 컨테이너 {} / 여유 {} (SSD {}) |".format(fmt(ct.get("total")), fmt(ct.get("free")), fmt(ct.get("ssd"))))
    L.append("| 루트 볼륨 | {} (사용 {}, {}) |".format(fmt(df.get("size")), fmt(df.get("used")), fmt(df.get("cap"))))
    L.append("| OS | macOS {} ({}) |".format(fmt(os_.get("version")), fmt(os_.get("build"))))
    L.append("| 아키텍처 | {}{} |".format(fmt(r.get("arch")), " (Rosetta)" if r.get("rosetta") == "1" else ""))
    if bat:
        L.append("| 배터리 | 사이클 {}회 / 건강도 약 {}% |".format(bat["cycle"], bat["health"]))
    L.append("")
    if r.get("ncpu") and r.get("pcore") is not None and r.get("ecore") is not None:
        same = r["pcore"] + r["ecore"] == r["ncpu"]
        L.append("- 검산 : P {} + E {} = {} → 전체 {} 와 {}".format(r["pcore"], r["ecore"], r["pcore"] + r["ecore"], r["ncpu"], "일치" if same else "불일치"))
    if bat:
        L.append("- 배터리 건강도는 원시값 기준 근사치임. 시스템 설정 → 배터리 표시값과 약간 다를 수 있음")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 2. 로컬 AI 구성 가능 범위")
    L.append("")
    if not ai.get("usable"):
        L.append("- 메모리 값을 못 읽어서 계산 생략함")
    else:
        L.append("### 2-1. 계산 기준")
        L.append("")
        L.append("| 항목 | 값 |")
        L.append("|---|---|")
        L.append("| 총 메모리 | {:.0f} GB |".format(ai["total_gb"]))
        if ai["apple"]:
            L.append("| GPU 사용 가능 메모리 | 약 {:.1f} GB (총 메모리의 {:.0f}%, macOS 기본 한도 근사) |".format(ai["usable"], ai["ratio"] * 100))
        else:
            L.append("| 모델 적재 가능 메모리 | 약 {:.1f} GB (Intel, CPU 추론 기준 근사) |".format(ai["usable"]))
        L.append("| 메모리 대역폭 | {} GB/s ({}) |".format(ai["bw"], ai["bw_src"]))
        L.append("| 컨텍스트 길이 | {:,} 토큰 |".format(ai["ctx"]))
        if ai.get("free_gb") is not None:
            L.append("| 디스크 여유 | 약 {:.0f} GB |".format(ai["free_gb"]))
        L.append("")
        L.append("- 필요 메모리 = 가중치(파라미터 × 양자화 바이트) + KV 캐시(컨텍스트 비례) + 런타임 {:.0f}GB".format(RUNTIME_OVERHEAD_GB))
        L.append("- 생성 속도 ≈ 대역폭 × {:.0%} ÷ 가중치 크기 → 토큰마다 가중치를 한 번 읽는다고 본 근사".format(DECODE_EFF))
        L.append("- 판정 : 여유 = 사용 가능 메모리의 90% 이하, 빠듯 = 90~100%, 불가 = 초과")
        L.append("")
        L.append("### 2-2. 결론")
        L.append("")
        d, m = ai.get("daily"), ai.get("max")
        if d:
            L.append("- 일상 대화용 추천 : **{} Q4** (필요 약 {:.1f}GB, 약 {:.0f} tok/s)".format(d["model"], d["need"], d["tps"]))
        else:
            L.append("- 일상 대화용 추천 : 기준({} tok/s, 여유 판정)을 만족하는 조합 없음 → 3B 이하 소형 모델 권장".format(INTERACTIVE_TPS))
        if m:
            L.append("- 최대 적재 가능 : **{} {}** (필요 약 {:.1f}GB, 약 {:.0f} tok/s)".format(m["model"], m["quant"], m["need"], m["tps"]))
        if not ai["apple"]:
            L.append("- Intel 맥은 Metal GPU 가속이 제한적이라 CPU 추론 위주 → 속도는 위 수치보다 더 낮을 수 있음")
        L.append("")
        L.append("### 2-3. 모델 크기 · 양자화별 판정")
        L.append("")
        L.append("| 모델 | 양자화 | 파일 크기 | 필요 메모리 | 판정 | 예상 속도 |")
        L.append("|---|---|---|---|---|---|")
        for x in ai["rows"]:
            spd = "{:.0f} tok/s".format(x["tps"]) if x["verdict"] != "불가" else "-"
            L.append("| {} | {} | {:.1f} GB | {:.1f} GB | {} | {} |".format(x["model"], x["quant"], x["file"], x["need"], x["verdict"], spd))
        L.append("")
        L.append("### 2-4. 기타 워크로드 (메모리 기준 대략치)")
        L.append("")
        L.append("| 워크로드 | 필요 메모리 | 판정 |")
        L.append("|---|---|---|")
        for n, mm, v in ai["other"]:
            L.append("| {} | 약 {} GB | {} |".format(n, mm, v))
        L.append("")
        L.append("### 2-5. 실행 도구")
        L.append("")
        L.append("| 도구 | 특징 | 언제 쓰나 |")
        L.append("|---|---|---|")
        L.append("| Ollama | 설치·모델 받기가 가장 쉬움, GGUF 기반 | 처음 시작할 때 |")
        L.append("| llama.cpp | Metal 가속, 양자화 선택 폭 넓음 | 세밀하게 튜닝할 때 |")
        L.append("| MLX (mlx-lm) | Apple Silicon 전용 프레임워크 | 맥에서 속도 우선일 때 |")
        L.append("| LM Studio | GUI, 모델 검색·비교 쉬움 | 터미널 없이 써볼 때 |")
        L.append("")
        L.append("> 주의 : 위 수치는 근사치임. 실제 속도는 모델 구조(MoE 여부), 런타임, 프롬프트 길이, 발열에 따라 달라짐. 프롬프트 처리(prefill)는 GPU 코어 수 영향이 더 큼")
        L.append("")
        L.append("> 주의 : GPU 메모리 한도는 `sudo sysctl iogpu.wired_limit_mb=<MB>` 로 늘릴 수 있지만, 너무 올리면 OS·앱이 쓸 메모리가 부족해짐. 재부팅하면 원래 값으로 돌아감")
        L.append("")
    L.append("---")
    L.append("")
    L.append("## 3. 실습 로그")
    L.append("")
    for g, title, cmd, out in logs:
        L.append("### {} - {}".format(g, title))
        L.append("")
        L.append("```bash")
        L.append("$ " + cmd)
        safe = "\n".join(l for l in (out or "").splitlines() if not SENSITIVE.search(l))
        L.append(safe if safe else "(출력 없음)")
        L.append("```")
        L.append("")
    L.append("---")
    L.append("")
    L.append("## 4. 한 장 요약")
    L.append("")
    L.append("| 항목 | 핵심 |")
    L.append("|---|---|")
    L.append("| 칩 · 메모리 | {} · {} |".format(fmt(r.get("chip")), mem))
    if ai.get("usable"):
        L.append("| AI 가용 메모리 | 약 {:.0f} GB, 대역폭 {} GB/s |".format(ai["usable"], ai["bw"]))
        if ai.get("daily"):
            L.append("| 일상용 | {} Q4 |".format(ai["daily"]["model"]))
        if ai.get("max"):
            L.append("| 최대 | {} {} |".format(ai["max"]["model"], ai["max"]["quant"]))
    L.append("")
    if ai.get("daily"):
        L.append("**이 맥은 {} Q4 를 대화용으로 무난히 돌릴 수 있음**".format(ai["daily"]["model"]))
    text = "\n".join(L) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------- 메인
def main():
    ap = argparse.ArgumentParser(description="Mac 사양 확인 실습 + 로컬 AI 계산")
    ap.add_argument("--auto", action="store_true", help="입력 없이 전부 자동 실행")
    ap.add_argument("--demo", action="store_true", help="샘플 출력으로 흐름 확인 (맥이 아니어도 됨)")
    ap.add_argument("--ctx", type=int, default=8192, help="로컬 AI 계산용 컨텍스트 길이 (기본 8192)")
    ap.add_argument("--out", default=None, help="리포트 경로 (기본 ~/mac-spec-report-YYYYMMDD.md)")
    a = ap.parse_args()
    interactive = not a.auto and sys.stdin.isatty()
    setup_readline(interactive)
    out_path = os.path.expanduser(a.out or "~/mac-spec-report-{}.md".format(datetime.date.today().strftime("%Y%m%d")))

    if sys.platform != "darwin" and not a.demo:
        print(warn("macOS 가 아님. 흐름만 보려면 --demo 로 실행"))
        sys.exit(1)

    width = min(shutil.get_terminal_size((80, 20)).columns, 80)
    print(h1("=" * width))
    print(h1(" Mac 사양 확인 실습") + dim("  (총 {}단계, 결과는 {} 에 저장)".format(len(STEPS), out_path)))
    print(h1("=" * width))
    if interactive:
        print(ink(" 각 단계에서 명령을 직접 쳐보면 정답인지 알려줌. 귀찮으면 Enter 로 자동 입력"))
        print(ink(" 실행되는 건 화면에 보이는 조회 명령뿐임"))
        if readline:
            print(ink(" Tab = 다음 단어 자동완성, ↑↓ = 이전에 친 명령 불러오기"))
        ask(dim(" 시작하려면 Enter "))

    r, logs, last_group, quit_early = {}, [], None, False
    for i, st in enumerate(STEPS, 1):
        g = st["group"]
        if g != last_group:
            if last_group in QUIZ and interactive:
                quiz(QUIZ[last_group])
            print()
            print(h2("■ " + g))
            last_group = g
        print()
        print(h1("[{}/{}] {}".format(i, len(STEPS), st["title"])) + dim("  - " + st["purpose"]))
        print(ink("  명령 : ") + c(st["cmd"], "1"))
        if interactive:
            go = type_command(st["cmd"])
            if go is None:
                quit_early = True
                break
            if go is False:
                print(dim("  건너뜀"))
                continue
        rc, out = run(st["cmd"], a.demo, st["key"])
        shown = out if len(out) < 1500 else out[:1500] + "\n... (생략)"
        print(dim("  ┌ 결과"))
        for line in (shown or "(출력 없음)").splitlines():
            print(dim("  │ ") + line)
        print(dim("  └"))
        val = parse(st["parse"], out, rc)
        if st["parse"] != "none":
            r[st["key"]] = val
            if val is None:
                print(warn("  값을 못 읽음") + (dim(" (선택 항목이라 괜찮음)") if st.get("optional") else ""))
            elif st["key"] == "memsize":
                print(ok("  → {:.0f} GB".format(gb(val))))
            elif st["key"] == "ecore" and r.get("pcore") is not None and r.get("ncpu"):
                s = r["pcore"] + val
                print(ok("  → P {} + E {} = {} / 전체 {} : {}".format(r["pcore"], val, s, r["ncpu"], "일치" if s == r["ncpu"] else "불일치")))
            elif st["key"] == "battery":
                print(ok("  → 사이클 {}회, 건강도 약 {}%".format(val["cycle"], val["health"])))
            elif st["key"] == "os":
                print(ok("  → macOS {} (빌드 {})".format(val["version"], val["build"])))
            elif st["key"] == "df":
                print(ok("  → 크기 {}, 사용 {}, 남음 {} ({})".format(val["size"], val["used"], val["avail"], val["cap"])))
            elif st["key"] == "container":
                print(ok("  → 컨테이너 {} 중 여유 {} (SSD {})".format(val["total"], val["free"], val["ssd"])))
            else:
                print(ok("  → {}".format(val)))
        print(ink("  확인 포인트 : ") + st["check"])
        if not st.get("sensitive"):
            logs.append((g, st["title"], st["cmd"], out))
        if interactive:
            nxt = ask(dim("  다음 단계 Enter (q=여기서 리포트 생성) > ")).strip().lower()
            if nxt == "q":
                quit_early = True
                break
    if last_group in QUIZ and interactive and not quit_early:
        quiz(QUIZ[last_group])

    print()
    print(h2("■ 로컬 AI 구성 가능 범위 계산"))
    ai = local_ai(r, a.ctx, interactive)
    if ai.get("usable"):
        print(ink("  사용 가능 메모리 약 {:.1f} GB, 대역폭 {} GB/s ({})".format(ai["usable"], ai["bw"], ai["bw_src"])))
        if ai.get("daily"):
            d = ai["daily"]
            print(ok("  일상 대화용 : {} Q4 (약 {:.0f} tok/s)".format(d["model"], d["tps"])))
        if ai.get("max"):
            m = ai["max"]
            print(ok("  최대 적재   : {} {} (필요 약 {:.1f} GB)".format(m["model"], m["quant"], m["need"])))
    else:
        print(warn("  메모리 값이 없어 계산 생략"))

    save_history()
    report(r, logs, ai, out_path)
    print()
    print(h1("리포트 저장 : ") + out_path)
    print(dim("열기 : open \"{}\"".format(out_path)))


def quiz(q):
    question, choices, answer, explain = q
    print()
    print(h2("  [질문] ") + question)
    for k, ch in enumerate(choices, 1):
        print(ink("    {}) {}".format(k, ch)))
    s = ask(ink("  번호 > ")).strip()
    if s == str(answer):
        print(ok("  정답. ") + explain)
    else:
        print(warn("  정답은 {}번. ".format(answer)) + explain)


if __name__ == "__main__":
    main()
