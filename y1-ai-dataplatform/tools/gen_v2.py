#!/usr/bin/env python3
"""Y1 보고서 v2 그림 : 그림마다 별도 draw.io + SVG 생성 (2색 테마)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from figlib2 import Page, drawio, svg

OUT = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------ 그림 1-1 : 인입 분산
def fig1_1(cube=True):
    p = Page("그림 1-1 인입 분산", 1400, 910)
    p.title("그림 1-1. 랙 서버 균등 분배 : 인입 분산",
            "패브릭은 랙(VTEP) 단위로 똑같이 나눔 → 랙당 서버 수가 다르면 서버당 부하가 달라짐. 랙당 서버 수 = 분산의 전제")

    def row(y0, label, counts, h=360):
        p.zone(30, y0, 1340, h, label)
        b = p.box(570, y0 + 30, 260, 62 if cube else 50, "Border / Super Spine\n외부 ETL 인입 (VIP)", "device", bold=True, cube=cube)
        n, w, gap = len(counts), 160, 26
        x0 = 30 + (1340 - (n * w + (n - 1) * gap)) // 2
        uniform = len(set(counts)) == 1
        for i, c in enumerate(counts):
            x = x0 + i * (w + gap)
            name = "G (증설)" if i == 6 else chr(65 + i)
            hot = c < max(counts)
            r = p.box(x, y0 + 126, w, 64 if cube else 54, f"Storage 랙 {name}\nleaf 쌍 (VTEP 2)", "device", bold=True, cube=cube)
            p.edge(b, r, "1/R", "hot" if hot else ("good" if uniform else "norm"))
            txt = "서버 M/2대\n서버당 2/(R·M)\n(다른 랙의 2배)" if hot else "서버 M대\n서버당 1/(R·M)"
            nd = p.box(x, y0 + 218, w, 82 if cube else 74, txt, "hot" if hot else ("good" if uniform else "node"), bold=True, cube=cube)
            p.edge(r, nd, "", "hot" if hot else ("good" if uniform else "norm"))

    row(104, "I Lake : 배치 정책 없음 (DCNY03 Storage 랙 M대 + 증설 랙 G 만 M/2대)", [8, 8, 8, 8, 8, 8, 4])
    p.box(60, 410, 1280, 44,
          "랙 G 서버 M/2대가 다른 랙 M대와 같은 1/R 을 받음 → 서버당 2배. PUT 본문은 인입 서버를 지나므로 랙 G NIC 이 먼저 포화",
          "note", bold=True, size=13)
    row(484, "Y1 : 원칙 = 역할별로 랙당 서버 수 균일 (DCNY03 Storage M대 · DCNY01 Compute N대), 증설은 랙 단위", [8, 8, 8, 8, 8, 8, 8], h=400)
    p.box(60, 790, 1280, 80,
          "모든 서버 1/(R·M) 로 동일 → 그 위에서 Maglev 가 전체 AIStor 백엔드로 고르게 분배\n"
          "랙마다 서버 수가 다를 수밖에 없을 때 : export-gateway-ip → 랙 단위가 아닌 서버 수 비례로 분산 (랙 몫 = 랙 서버 수 ÷ 전체 서버 수, 서버당 모두 동일)",
          "good", bold=True, size=13)
    return p


# ------------------------------------------------ 그림 1-2 : 장애 범위
def fig1_2():
    p = Page("그림 1-2 장애 범위", 1400, 860)
    p.title("그림 1-2. 랙 서버 균등 분배 : 서비스 · 데이터 배치와 장애 범위",
            "랙 = leaf · 전원 · 케이블을 공유하는 장애 단위. 핵심 Pod 와 데이터를 랙에 고르게 놓아야 랙 1개 장애가 1/N 손실로 끝남")

    def half(x0, after):
        p.zone(x0, 104, 660, 730, "Y1 : 랙 라벨 + 분산 스케줄" if after else "I Lake : 스케줄러 임의 배치")
        w, gap = 96, 8
        com = (["핵심 · CP\nEgress GW\n워커", "핵심 · CP\nEgress GW\n워커", "핵심 · CP\n워커", "워커\nmesh-api", "워커\nmesh-api", "워커"]
               if after else ["핵심 ×3\nCP ×2\nEgress ×2", "CP ×1\n워커", "워커", "워커\nmesh-api ×2", "워커", "워커"])
        p.box(x0 + 20, 140, 620, 30, "DCNY01 Compute 랙 (핵심 Pod, control plane, Egress GW, ClusterMesh apiserver, 워커)", "plain", bold=True, size=12)
        for i in range(6):
            x = x0 + 22 + i * (w + gap)
            hot = (not after) and i == 0
            p.box(x, 180, w, 134, f"랙 {chr(65+i)}\n" + com[i], "hot" if hot else ("good" if after else "node"), size=12, cube=True)
        p.box(x0 + 20, 334, 620, 30, "DCNY03 Storage 랙 (AIStor erasure set) : I Lake 랙 고려 구성 → 동일 유지", "plain", bold=True, size=12)
        for i in range(6):
            x = x0 + 22 + i * (w + gap)
            txt, kind = "set 1 · 2\n각 1/R", "good"
            p.box(x, 374, w, 106, f"랙 C{i+1}\n" + txt, kind, size=12, cube=True)
        if after:
            p.box(x0 + 20, 500, 620, 170,
                  "랙 A 장애 시\n· 핵심 Pod 3개 중 2개 유지 → 서비스 정상\n· CP 3대 중 2대 유지 → API 정상\n"
                  "· Egress GW 1대 유지 → 외부 통신 유지\n랙 C1 장애 시\n· 모든 set 이 1/R 만 잃음 → 읽기 · 쓰기 유지 (허용 장애 수 이내)",
                  "good", align="left", size=13)
            p.box(x0 + 20, 686, 620, 128,
                  "적용\n· 노드 라벨 rack=<랙> (I Lake 와 동일)\n"
                  "· 핵심 Pod · CP · Egress · mesh-api : topologySpreadConstraints (topologyKey: rack)\n"
                  "· AIStor set 별 드라이브 랙 균등 (I Lake 와 동일)", "key", align="left", size=13)
        else:
            p.box(x0 + 20, 500, 620, 170,
                  "랙 A 장애 시\n· 핵심 Pod 3개 전부 중단 → 서비스 중단\n· CP 3대 중 2대 중단 → API 쿼럼 상실\n"
                  "· Egress GW 전부 중단 → 외부 통신 중단\n(Storage 는 I Lake 도 랙 고려 구성 → 해당 없음)",
                  "hot", align="left", size=13)
            p.box(x0 + 20, 686, 620, 128,
                  "원인\n· rack 라벨은 있으나 분산 기준(topologyKey)으로 쓰지 않으면 스케줄러가 랙을 무시\n· 자원 여유가 있는 노드에 먼저 몰림", "note", align="left", size=13)

    half(30, False)
    half(710, True)
    return p


# ------------------------------------------------ 그림 1-3 : 서버 증설 배치
def fig1_3():
    p = Page("그림 1-3 서버 증설 배치", 1400, 830)
    p.title("그림 1-3. 서버 증설 배치 : Storage(AIStor) 서버 추가 (현재 R랙 × 랙당 M대)",
            "네트워크 균등(랙당 서버 수)과 데이터 장애 범위(새 pool 의 랙 분산)를 동시에 만족하는 방식만 사용")
    opts = [
        ("A. 기존 랙마다 균등 추가", "권장", [10, 10, 10, 10, 10, 10], 6,
         "기존 R랙 × +k대", "○ 랙당 M+k 대 동일", "○ 새 pool 이 전 랙에 분산",
         "랙 공간 · 전원 · leaf 포트 여유\n(leaf 쌍당 +k × 서버 포트 수)"),
        ("B. 새 랙 여러 개 동시", "권장", [8] * 6 + [6, 6], 2,
         "새 랙 여러 개 × 같은 수 L대", "△ L ≠ M 이면\n→ export-gateway-ip 필요", "△ 새 pool 이 새 랙에만\n→ 허용 장애 수 확인",
         "대규모 증설에 적합\n(새 랙 수 ≥ pool 최소 랙 수)"),
        ("C. 새 랙 1개 가득", "조건부", [8] * 6 + [8], 1,
         "새 랙 1개 × M대", "○ 랙당 M대 동일", "× 새 pool 전체가 1랙\n→ 랙 장애 = pool 중단",
         "기존 pool 확장이 아닌\n별도 용도일 때만"),
        ("D. 새 랙에 일부만", "금지", [8] * 6 + [4, 8], 2,
         "새 랙에 M 보다 적게", "× 덜 찬 랙 서버당 몫 증가", "× 새 pool 랙 편중",
         "사용하지 않음"),
    ]
    w, gap = 320, 20
    for i, (name, verdict, counts, new_racks, plan, net, data, cond) in enumerate(opts):
        x = 30 + i * (w + gap)
        rec = verdict == "권장"
        bad = verdict == "금지"
        p.zone(x, 104, w, 484, "")
        p.box(x + 10, 114, w - 20, 44, f"{name}\n[{verdict}]", "hot" if bad else ("good" if rec else "plain"), bold=True, size=13)
        p.box(x + 10, 168, w - 20, 40, plan, "plain", bold=True, size=12)
        # 랙 미니 도식
        n = len(counts)
        rw = (w - 20 - (n - 1) * 4) // n
        for j, c in enumerate(counts):
            rx = x + 10 + j * (rw + 4)
            is_new = j >= 6
            added = (not is_new) and c > 8
            kind = "hot" if (is_new and c < 8 and bad) else ("good" if (is_new or added) else "node")
            label = f"{'새' if is_new else chr(65+j)}\n" + {8: "M", 10: "M+k", 6: "L", 4: "M/2"}[c]
            p.box(rx, 222, rw, 70, label, kind, size=11, cube=True)
        p.box(x + 10, 304, w - 20, 26, "음영 = 증설 서버가 들어간 랙", "plain", size=11)
        p.box(x + 10, 344, 90, 70, "네트워크\n균등", "device", bold=True, size=12)
        p.box(x + 100, 344, w - 110, 70, net, "hot" if net.startswith("×") else ("good" if net.startswith("○") else "plain"), size=12)
        p.box(x + 10, 424, 90, 70, "데이터\n장애 범위", "device", bold=True, size=12)
        p.box(x + 100, 424, w - 110, 70, data, "hot" if data.startswith("×") else ("good" if data.startswith("○") else "plain"), size=12)
        p.box(x + 10, 504, 90, 70, "조건", "device", bold=True, size=12)
        p.box(x + 100, 504, w - 110, 70, cond, "note", size=12)
    p.box(30, 604, 1340, 200,
          "증설 배치 원칙 (순서대로 판단)\n"
          "① 수량을 랙 단위로 계획 : 랙당 서버 수(M · N)의 배수, 또는 기존 랙 수의 배수 (기존 랙마다 같은 수씩)\n"
          "② 기존 랙에 여유가 있으면 A : 모든 랙에 같은 수씩 추가 → 랙당 서버 수 유지 + 새 pool 이 전 랙에 분산\n"
          "③ 여유가 없으면 B : 새 랙을 여러 개 동시에. 새 랙끼리 서버 수를 같게, 새 pool 은 새 랙 전체에 걸쳐 구성\n"
          "④ 새 랙 서버 수가 기존과 다르면 export-gateway-ip + maximum-paths mixed 로 서버 수 비례 분산을 켬\n"
          "⑤ C 는 새 pool 이 한 랙에 갇히므로 기존 데이터 확장용으로 쓰지 않음. D 는 금지\n"
          "⑥ Compute K8s (Spark · Airflow 등) 는 데이터가 없으므로 새 랙 N대 단위 증설이 가장 단순. 핵심 Pod · CP 는 옮기지 않음\n"
          "⑦ 공통 절차 : 인벤토리 등록(랙 · ASN · 주소) → leaf 템플릿 렌더링 → 노드 라벨 → AIStor pool 추가 → T12 랙 간 편차 ±10% 확인",
          "key", align="left", size=13, valign="top")
    return p


# ------------------------------------------------ 그림 1-4 : 역할별 랙 분리 · DC 구간 분리
def fig1_4():
    p = Page("그림 1-4 역할별 랙 분리 · DC 구간", 1400, 880)
    p.title("그림 1-4. 랙 혼재(random) → 역할별 랙 분리 · DC 구간 분리 (공간 · 전력 제약)",
            "혼재 배치는 랙마다 AIStor 노드 수가 달라 VIP 분산이 깨짐 → 역할별 랙 분리로 해소. 구간 분리(DCNY01 · 02 · 03)는 불가피 → DCNY03 구간 간 링크로 관리")
    cols = [30 + i * 450 for i in range(3)]
    heads = [("A. I Lake : 랙 혼재 (random 배치)\n[개선 대상]", "hot"),
             ("B. Y1 : 역할별 랙 분리\n[개선]", "good"),
             ("C. Y1 + DC 구간 분리 (DCNY01 · 02 · 03)\n[공간 · 전력 불가피 · 조건 충족]", "key")]
    for x0, (h, k) in zip(cols, heads):
        p.zone(x0, 104, 430, 682, "")
        p.box(x0 + 10, 114, 410, 46, h, k, bold=True, size=13)
    # A : 혼재
    x0 = cols[0]
    p.zone(x0 + 10, 172, 410, 300, "DC (예시 : 랙 4개, AIStor 수 제각각)")
    b = p.box(x0 + 130, 200, 170, 54, "Border\nAIStor VIP", "device", size=12, cube=True)
    mix_s = [1, 5, 3, 2]
    for i, sN in enumerate(mix_s):
        x = x0 + 22 + i * 100
        hot = sN == 1
        r = p.box(x, 300, 92, 120, f"랙 {i+1}\nAIStor {sN}대\nCompute 나머지\n노드당 1/{4 * sN}",
                  "hot" if hot else "node", size=11, cube=True)
        p.edge(b, r, "1/4", "hot" if hot else "norm")
    p.box(x0 + 22, 430, 390, 34, "랙 1 AIStor 노드 = 랙 2 노드의 5배 인입", "hot", size=12, bold=True)
    # B : 역할별 랙
    x0 = cols[1]
    p.zone(x0 + 10, 172, 410, 300, "DC (단일 구간)")
    ss = p.box(x0 + 130, 200, 170, 54, "Super Spine\nAIStor VIP", "device", size=12, cube=True)
    cr = p.box(x0 + 30, 310, 170, 100, "Compute 랙\n랙당 N대 동일\nSpark · Airflow · ETL", "node", size=12, cube=True)
    sr = p.box(x0 + 230, 310, 170, 100, "Storage 랙\n랙당 M대 동일\nAIStor (VIP 광고)", "good", size=12, cube=True)
    p.edge(ss, cr, "S3 · ETL", "norm", both=True)
    p.edge(ss, sr, "VIP 1/R 균등", "good")
    p.box(x0 + 30, 430, 370, 34, "Storage 노드당 1/(R·M) 동일", "good", size=12, bold=True)
    # C : 역할별 + DC 구간 (DCNY01 · 02 · 03)
    x0 = cols[2]
    p.zone(x0 + 10, 172, 195, 128, "DCNY01 (Compute K8s)")
    p.zone(x0 + 225, 172, 195, 128, "DCNY02 (GPU 서버)")
    p.zone(x0 + 10, 318, 410, 104, "")
    p.box(x0 + 16, 324, 160, 22, "DCNY03 (Storage K8s)", "label", bold=True, size=13, align="left")
    c = p.box(x0 + 25, 200, 165, 88, "Compute 랙\n랙당 N대\nSpark · Airflow · ETL", "node", size=12, cube=True)
    gpu = p.box(x0 + 240, 200, 165, 88, "GPU 서버 랙\nAI 학습 · 추론", "node", size=12, cube=True)
    s = p.box(x0 + 200, 342, 200, 72, "Storage 랙\n랙당 M대 · VIP", "good", size=12, cube=True)
    p.edge(c, s, "S3 · ETL", "hot", anc=(0.5, 1, 0.25, 0))
    p.edge(gpu, s, "S3 (대용량)", "hot", anc=(0.5, 1, 0.75, 0))
    p.box(x0 + 30, 430, 370, 34, "DCNY03 구간 간 링크 = Compute + GPU 합계", "key", size=12, bold=True)
    # 비교 행
    rows = ["인입 분산", "장애 범위", "Storage\n접근 트래픽", "증설 · 운영"]
    vals = [
        ["× 랙마다 AIStor 수 다름\n→ 노드당 몫 최대 N배", "× 랙 장애 시 손실 랜덤\n(Compute · AIStor 동시)",
         "△ 일부 랙 안 로컬\n(효과 작음)", "× 랙별 포트 · 전력 제각각"],
        ["○ Storage 랙당 M대 균일\n→ 노드당 동일", "○ 역할별 랙 단위 예측 가능\n(1-2 원칙 적용)",
         "△ S3 전량 spine · super spine\n→ 비율 2:1 이내 유지", "○ 역할별 랙 단위 증설\n(1-3 원칙)"],
        ["○ B 와 동일", "○ B + 구간별 전력 · 공간 분리\n(GPU 고전력 구간 독립)",
         "△ Compute · GPU 의 S3 전량이\nDCNY03 구간 간 링크로 집중", "△ 구간 간 링크 이중화 · 지연 관리"],
    ]
    y = 488
    for r, name in enumerate(rows):
        for ci, x0 in enumerate(cols):
            p.box(x0 + 10, y, 110, 64, name, "device", bold=True, size=12)
            v = vals[ci][r]
            k = "hot" if v.startswith("×") else ("good" if v.startswith("○") else "plain")
            p.box(x0 + 126, y, 294, 64, v, k, size=12)
        y += 72
    p.box(30, 798, 1340, 72,
          "C 조건 : ① DCNY03 구간 간 링크 ≥ Compute + GPU 의 Storage 접근 합계 (non-blocking)  ② 구간 간 RTT ≤ 0.2 ms  ③ 구간마다 물리 경로 2개 이상 · 관로 분리  ④ super spine 이 세 구간에 걸치는 같은 패브릭\n"
          "구간 안에서는 1-1 ~ 1-3 원칙 동일 적용. DR 목적의 다중 DC 는 별도 (DC 별 Compute + Storage 셀)",
          "key", align="left", size=13, valign="top")
    return p


# ================================================= 2장 : 패브릭 경로 다중화
# ------------------------------------------------ 그림 2-1 : VIP 광고 방식
def fig2_1():
    p = Page("그림 2-1 VIP 광고 방식", 1400, 860)
    p.title("그림 2-1. VIP 광고 방식 : BGP 유지 (L2 는 참고)",
            "LB IPAM 은 주소만 정함. 분산은 VIP 를 알리는 방식이 결정 → L2 면 VIP 당 노드 1대, BGP 면 광고 노드 전체 ECMP")

    def half(x0, bgp):
        p.zone(x0, 104, 660, 730, "I Lake · Y1 : BGP 광고 (CiliumBGPAdvertisement) [동일 유지]" if bgp else "참고 : L2 announcement (ARP) 였다면 (I Lake 는 BGP · 해당 없음)")
        cl = p.box(x0 + 230, 140, 200, 58, "ETL client\nS3 → VIP", "plain", bold=True, cube=True)
        lf = p.box(x0 + 200, 250, 260, 64, "DCNY03 Storage leaf 쌍\n" + ("VIP /32 → 랙 노드 M개 ECMP" if bgp else "VIP → ARP 응답한 MAC 1개"),
                   "good" if bgp else "device", size=12, cube=True)
        p.edge(cl, lf, "", "good" if bgp else "norm")
        w, gap = 70, 8
        for i in range(8):
            x = x0 + 22 + i * (w + gap)
            if bgp:
                kind, txt, ek = "good", f"노드 {i+1 if i < 7 else 'M'}\n1/M", "good"
            else:
                kind, txt, ek = ("hot", "노드 1\nlease\n100%", "hot") if i == 0 else ("mute", f"노드 {i+1 if i < 7 else 'M'}\n0%", "idle")
            nd = p.box(x, 380, w, 96, txt, kind, size=12, cube=True)
            p.edge(lf, nd, "", ek)
        if bgp:
            txt = ("동작\n· 노드마다 VIP /32 를 leaf 와 eBGP 로 광고 (2세션)\n· leaf 가 랙 노드 M개로 ECMP\n"
                   "· 노드 장애 = 세션 down → 경로 제거 (hold 9s)\n· 그 위에서 Maglev 가 전체 AIStor Pod 로 분배")
            k = "good"
        else:
            txt = ("동작\n· VIP 마다 lease 를 가진 노드 1대만 ARP 응답\n· 그 VIP 의 모든 요청이 노드 1대로 인입\n"
                   "· 장애 시 lease 이전까지 끊김\n· 패브릭 ECMP · iBGP/eBGP 설정과 무관하게 쏠림")
            k = "hot"
        p.box(x0 + 20, 500, 620, 150, txt, k, align="left", size=13)
        chk = ("확인\nkubectl get ciliumbgpadvertisement -o yaml\ncilium bgp routes advertised ipv4 unicast\nshow ip route <VIP>/32 vrf PUBLIC   (next-hop = 랙 노드 수)"
               if bgp else
               "확인\nkubectl get ciliuml2announcementpolicy\nkubectl -n kube-system get lease | grep cilium-l2announce\n→ 있으면 L2 방식 = 불균형 1순위 원인")
        p.box(x0 + 20, 666, 620, 150, chk, "key" if bgp else "note", align="left", size=13, valign="top")

    half(30, False)
    half(710, True)
    return p


# ------------------------------------------------ 그림 2-2 : 경로가 줄어드는 지점
def fig2_2():
    p = Page("그림 2-2 경로 탈락 지점", 1400, 840)
    p.title("그림 2-2. BGP 경로가 줄어드는 지점 : 광고 V → 설치 1 을 V → V 로",
            "Storage leaf VTEP V개 (= Storage 랙 수 × 2) 가 VIP 를 광고해도 단계마다 경로가 떨어짐. 단계별 설정 1개씩으로 V개 유지")
    stages = [
        ("① 광고", "Storage leaf VTEP V개가 같은 VIP 광고", "V", "V", "-"),
        ("② spine · RR 전달", "RD 가 같으면 같은 경로로 보고 1개만 전달", "1", "V", "leaf 별 고유 RD (rd auto)"),
        ("③ RR 반사", "RR 은 NLRI 마다 best 1개만 반사", "1", "V", "eBGP 단일화 (또는 고유 RD)"),
        ("④ AS-path 비교", "랙별 ASN 이 달라 AS-path 내용이 다르면 탈락", "1", "V", "bestpath as-path multipath-relax"),
        ("⑤ IGP metric 비교", "VTEP 까지 IGP cost 가 다르면 탈락", "1", "V", "bestpath igp-metric ignore (I Lake 적용 완료)"),
        ("⑥ 설치 수 제한", "maximum-paths 기본값 1", "1", "V", "maximum-paths 64 (ipv4 · evpn · VRF)"),
    ]
    p.box(30, 104, 190, 40, "단계", "device", bold=True, size=13)
    p.box(230, 104, 430, 40, "경로가 떨어지는 조건", "device", bold=True, size=13)
    p.box(670, 104, 150, 40, "설정 누락 시", "hot", bold=True, size=13)
    p.box(830, 104, 360, 40, "2차 설정", "good", bold=True, size=13)
    p.box(1200, 104, 170, 40, "Y1 : 남는 경로", "good", bold=True, size=13)
    y = 156
    prev_b = prev_a = None
    for i, (st, cond, b, a, fix) in enumerate(stages):
        drop = b != "V"
        p.box(30, y, 190, 70, st, "device", bold=True, size=13)
        p.box(230, y, 430, 70, cond, "plain", size=13)
        bb = p.box(670, y, 150, 70, f"{b}개", "hot" if drop else "node", bold=True, size=18)
        p.box(830, y, 360, 70, fix, "good" if fix != "-" else "plain", size=13, bold=fix != "-")
        ab = p.box(1200, y, 170, 70, f"{a}개", "good", bold=True, size=18)
        if prev_b:
            p.edge(prev_b, bb, "", "hot" if drop else "norm")
            p.edge(prev_a, ab, "", "good")
        prev_b, prev_a = bb, ab
        y += 96
    p.box(30, y + 4, 1340, 96,
          "읽는 법\n"
          "· 한 단계라도 막히면 그 아래는 1개 → Border 가 랙 1개로만 보냄 (그림 1-1 의 쏠림이 랙 전체로 확대)\n"
          "· 2-5 진단 명령으로 I Lake 에서 어느 단계가 빠졌는지 확인 → 빠진 설정만 Y1 에 [개선], 있는 것은 [동일 유지]\n"
          "· ⑤ 는 I Lake 에 igp-metric ignore 적용 완료 → Y1 동일 유지. ② ③ ⑥ 은 I Lake 설정 대조 후 판단",
          "key", align="left", size=13, valign="top")
    return p


# ------------------------------------------------ 그림 2-3 : BGP 구조 전후
def fig2_3():
    p = Page("그림 2-3 BGP 구조 전후", 1400, 880)
    p.title("그림 2-3. 패브릭 BGP 구조 : iBGP + RR + IGP → eBGP 단일화",
            "계층마다 ASN 을 나눠 eBGP 로 통일 → RR · IGP 없이 모든 경로가 그대로 전달되고, 장비별 장애가 독립")

    def half(x0, after):
        p.zone(x0, 104, 660, 750, "Y1 : underlay · overlay 모두 eBGP [개선]" if after else "I Lake : iBGP · eBGP 혼합 (확인됨)")
        ss = p.box(x0 + 200, 140, 260, 62, "Super Spine\n" + ("계층 ASN" if after else "iBGP 구간"), "device", size=12, cube=True)
        sp = p.box(x0 + 180, 252, 300, 62, "Spine\n" + ("Pod 별 ASN" if after else "iBGP RR · best 1 반사"),
                   "good" if after else "hot", size=12, cube=True)
        p.edge(ss, sp, "eBGP" if after else "iBGP + OSPF", "good" if after else "norm", both=True)
        lfs = []
        for i in range(3):
            x = x0 + 40 + i * 200
            lf = p.box(x, 370, 180, 62, f"leaf 랙 {i+1}\n" + ("랙 별 ASN" if after else "iBGP 구간"),
                       "good" if after else "device", size=12, cube=True)
            p.edge(sp, lf, "eBGP" if after else ("best 1" if i == 0 else "미전달"),
                   "good" if after else ("hot" if i == 0 else "idle"), both=after)
            nd = p.box(x, 470, 180, 62, "노드 M대\n클러스터 ASN", "node", size=12, cube=True)
            p.edge(lf, nd, "eBGP", "norm", both=True)
        if after:
            txt = ("구성\n· underlay : 링크 /31 eBGP, 루프백 · VTEP 광고\n· overlay : l2vpn evpn eBGP, spine 은 next-hop unchanged\n"
                   "· 계층별 ASN : super spine / spine Pod 별 / leaf 랙 별 / 노드 클러스터 별\n"
                   "· 전 계층 maximum-paths 64 + multipath-relax\n· BFD (패브릭 링크), 노드 구간은 timers 3 9\n"
                   "효과\n· RR · IGP 없음 → 경로 숨김 · cost 문제 원천 제거\n· 장비 1대 장애 = 그 세션만 영향")
            k = "good"
        else:
            txt = ("구조\n· underlay : OSPF (또는 IS-IS)\n· overlay : iBGP, spine 이 RR\n· 노드 ↔ leaf 만 eBGP → VRF 안에서 eBGP · iBGP 혼재\n"
                   "문제\n· RR 이 best 1개만 반사 (RD 공통 시)\n· eBGP > iBGP 단계에서 로컬 경로만 선택\n"
                   "· maximum-paths ibgp 누락 시 1개 설치\n· IGP cost 차이로 multipath 탈락")
            k = "hot"
        p.box(x0 + 20, 556, 620, 284, txt, k, align="left", size=13, valign="top")

    half(30, False)
    half(710, True)
    return p


FIGS = [("fig1-1", fig1_1()), ("fig1-2", fig1_2()), ("fig1-3", fig1_3()), ("fig1-4", fig1_4()),
        ("fig2-1", fig2_1()), ("fig2-2", fig2_2()), ("fig2-3", fig2_3())]

if __name__ == "__main__":
    suf = "-mustard" if os.environ.get("USE_KEY") == "1" else ""
    os.makedirs(os.path.join(OUT, "drawio" + suf), exist_ok=True)
    os.makedirs(os.path.join(OUT, "figures" + suf), exist_ok=True)
    for name, p in FIGS:
        with open(os.path.join(OUT, "drawio" + suf, f"{name}.drawio"), "w", encoding="utf-8") as f:
            f.write(drawio([p]))
        with open(os.path.join(OUT, "figures" + suf, f"{name}.svg"), "w", encoding="utf-8") as f:
            f.write(svg(p))
    if suf:
        raise SystemExit(print("ok (mustard)", [n for n, _ in FIGS]))
    with open(os.path.join(OUT, "y1-ai-dataplatform-architecture-v2.drawio"), "w", encoding="utf-8") as f:
        f.write(drawio([p for _, p in FIGS]))
    print("ok", [n for n, _ in FIGS])
