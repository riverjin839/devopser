"""Maglev 표 생성 시뮬레이션 (개념 코드, 논문 알고리즘 그대로, Cilium 해시 함수와는 다름)
usage: python3 maglev_sim.py
"""
import hashlib
from collections import Counter


def h(name, seed):
    return int.from_bytes(hashlib.sha256(f"{seed}:{name}".encode()).digest()[:8], "big")


def build(backends, M):
    # 1) 백엔드별 offset · skip → 선호 순열 (offset + j*skip) % M
    perm = [(h(b, "offset") % M, h(b, "skip") % (M - 1) + 1) for b in backends]
    nxt = [0] * len(backends)
    table = [-1] * M
    filled = 0
    # 2) 라운드로빈으로 각 백엔드가 자기 순열에서 빈 슬롯 하나씩 차지
    while True:
        for i, (off, skip) in enumerate(perm):
            c = (off + nxt[i] * skip) % M
            while table[c] >= 0:
                nxt[i] += 1
                c = (off + nxt[i] * skip) % M
            table[c] = i
            nxt[i] += 1
            filled += 1
            if filled == M:
                return [backends[x] for x in table]


def spread(table):
    cnt = Counter(table)
    return min(cnt.values()), max(cnt.values())


def moved(old, new, removed=None):
    # 제거된 백엔드가 갖고 있던 슬롯은 어차피 옮겨야 하므로 빼고 셈
    keep = [i for i in range(len(old)) if old[i] != removed]
    return sum(old[i] != new[i] for i in keep) / len(keep)


def modn(backends, keys):
    return [backends[h(k, "flow") % len(backends)] for k in keys]


if __name__ == "__main__":
    print("== 작은 예시 : M=7, 백엔드 3개 ==")
    small = ["b0", "b1", "b2"]
    for b in small:
        off, skip = h(b, "offset") % 7, h(b, "skip") % 6 + 1
        print(f"{b}: offset={off} skip={skip} 순열={[(off + j * skip) % 7 for j in range(7)]}")
    t = build(small, 7)
    print("표:", t)
    print("b1 제거 후:", build(["b0", "b2"], 7))

    N = 48
    bk = [f"aistor-{i:02d}" for i in range(N)]
    for M in (251, 4093, 16381, 65521):
        a = build(bk, M)
        lo, hi = spread(a)
        b = build([x for x in bk if x != "aistor-17"], M)
        print(f"M={M:6d} N={N}: 백엔드당 슬롯 {lo}~{hi} (편차 {100 * (hi - lo) / (M / N):.1f}%), "
              f"1개 제거 시 나머지 슬롯 재배치 {100 * moved(a, b, 'aistor-17'):.2f}%")

    # 비교 : hash mod N
    keys = [f"flow-{i}" for i in range(200000)]
    a = modn(bk, keys)
    b = modn([x for x in bk if x != "aistor-17"], keys)
    keep = [i for i in range(len(keys)) if a[i] != "aistor-17"]
    print(f"hash mod N, 1개 제거 시 나머지 연결 재배치 {100 * sum(a[i] != b[i] for i in keep) / len(keep):.2f}%")

    # 백엔드 추가
    M = 16381
    a = build(bk, M)
    c = build(bk + ["aistor-48"], M)
    print(f"M={M}, 1개 추가 시 기존 슬롯 재배치 {100 * moved(a, c):.2f}% (이상값 1/49 = {100 / 49:.2f}%)")
