#!/usr/bin/env python3
"""lake_check.py 의 CATALOG 로 점검 시트(.xlsx) 생성. 스크립트와 시트가 같은 원본을 씀.

  python3 build_sheet.py [출력.xlsx]
"""
import os
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lake_check import CATALOG, VERDICTS  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "lake-check-sheet.xlsx")
F = "Arial"
HEAD = PatternFill("solid", fgColor="2B2A27")
INPUT = PatternFill("solid", fgColor="FFF2CC")
AREA = PatternFill("solid", fgColor="F2EFE6")
VFILL = {"개선": "F6D5C5", "확인": "FBEBC2", "충족": "D9E6D5", "유지": "E9E9E4", "NA": "FFFFFF", "수동": "E3E8EF"}
thin = Side(style="thin", color="BFBFBF")
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
TARGET = {"node": "노드", "cluster": "클러스터", "nw": "NW (수동)"}


def header(ws, row, cols, widths):
    for i, (c, w) in enumerate(zip(cols, widths), 1):
        cell = ws.cell(row=row, column=i, value=c)
        cell.font = Font(name=F, bold=True, color="FFFFFF")
        cell.fill = HEAD
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BOX
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def body(cell, wrap=True, bold=False, fill=None, center=False):
    if isinstance(cell.value, str) and cell.value.startswith("=") and not cell.value.startswith("=COUNTIF") and not cell.value.startswith("=SUM"):
        cell.data_type = "s"      # '=' 로 시작하는 문구가 수식으로 읽히지 않게
    cell.font = Font(name=F, bold=bold, size=10)
    cell.alignment = Alignment(wrap_text=wrap, vertical="top", horizontal="center" if center else "left")
    cell.border = BOX
    if fill:
        cell.fill = fill


wb = Workbook()

# ---------------------------------------------------------------- 사용법
ws = wb.active
ws.title = "사용법"
ws.column_dimensions["A"].width = 16
ws.column_dimensions["B"].width = 100
rows = [
    ("Lake 현행 상태 점검 시트", ""),
    ("기준", "Y1 AI DATAPLATFORM 제안서 항목. 판정은 I Lake 를 기준으로 Y1 권장값과 비교"),
    ("자동 수집", "sudo python3 lake_check.py --out ./report  →  report/lake-check-<노드>-<시각>.md · .csv · .json"),
    ("옵션", "--bonds bond0,bond1 · --storage-selector <라벨=값> · --rack-label rack · --skip-cluster · --skip-node · --list"),
    ("수동 기록", "'점검 항목' 탭의 노란 칸(현재 값 · 판정 · 비고)만 입력. 판정은 목록에서 선택, '해석표' 탭으로 값별 해석 확인"),
    ("NW 항목", "W01 ~ W12 는 N9K 에서 명령 실행 후 해석표 대조 (스크립트는 수동으로 표시)"),
    ("", ""),
    ("판정", "뜻"),
    ("개선", "Y1 에서 바꿀 대상 (제안서 개선 항목)"),
    ("확인", "값 · 의도 확인 필요 (협의 항목)"),
    ("충족", "이미 Y1 권장값"),
    ("유지", "I Lake 설계 그대로 유지 (정상)"),
    ("NA", "수집 불가 · 건너뜀"),
    ("수동", "N9K 수동 확인 대상"),
    ("", ""),
    ("입력 예시", "L06 LB 응답 방식 → 현재 값 'snat' · 판정 '개선' · 비고 'P3 DSR PoC 대상'"),
]
for r, (a, b) in enumerate(rows, 1):
    ws.cell(row=r, column=1, value=a).font = Font(name=F, bold=True, size=14 if r == 1 else 10)
    c = ws.cell(row=r, column=2, value=b)
    c.font = Font(name=F, size=10)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    if a in VFILL and r > 8:
        ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=VFILL[a])
    if a == "판정":
        for col in (1, 2):
            ws.cell(row=r, column=col).font = Font(name=F, bold=True, color="FFFFFF")
            ws.cell(row=r, column=col).fill = HEAD
    if a == "입력 예시":
        c.fill = INPUT

# ---------------------------------------------------------------- 점검 항목
ws = wb.create_sheet("점검 항목")
cols = ["ID", "영역", "제안 장", "항목", "대상", "확인 명령", "Y1 권장값", "현재 값 (입력)", "판정 (입력)", "비고 (입력)"]
header(ws, 1, cols, [7, 12, 8, 26, 11, 52, 26, 26, 12, 28])
dv = DataValidation(type="list", formula1='"' + ",".join(VERDICTS) + '"', allow_blank=True)
ws.add_data_validation(dv)
r = 2
for it in CATALOG:
    vals = [it["id"], it["area"], it["ch"], it["item"], TARGET[it["target"]], it["cmd"], it["y1"], None, None, None]
    for c, v in enumerate(vals, 1):
        cell = ws.cell(row=r, column=c, value=v)
        body(cell, fill=INPUT if c >= 8 else None, center=c in (1, 3, 5, 9), bold=c == 1)
    dv.add(f"I{r}")
    r += 1
last = r - 1
ws.auto_filter.ref = f"A1:J{last}"

# ---------------------------------------------------------------- 해석표
ws = wb.create_sheet("해석표")
header(ws, 1, ["ID", "영역", "항목", "값 조건", "판정", "해석"], [7, 12, 26, 26, 9, 70])
r = 2
for it in CATALOG:
    for i, (cond, verdict, meaning) in enumerate(it["rules"]):
        vals = [it["id"], it["area"], it["item"], cond, verdict, meaning]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=r, column=c, value=v if (c > 3 or i == 0) else None)
            body(cell, center=c in (1, 5), bold=c == 1,
                 fill=PatternFill("solid", fgColor=VFILL.get(verdict, "FFFFFF")) if c == 5 else (AREA if i == 0 and c <= 3 else None))
        r += 1
ws.auto_filter.ref = f"A1:F{r - 1}"

# ---------------------------------------------------------------- 요약 (수식)
ws = wb.create_sheet("요약")
areas = list(dict.fromkeys(it["area"] for it in CATALOG))
header(ws, 1, ["영역"] + VERDICTS + ["입력됨", "전체"], [14] + [9] * len(VERDICTS) + [9, 9])
src = "'점검 항목'"
for i, area in enumerate(areas + ["합계"], 2):
    ws.cell(row=i, column=1, value=area)
    body(ws.cell(row=i, column=1), bold=True)
    for j, v in enumerate(VERDICTS, 2):
        col = get_column_letter(j)
        if area == "합계":
            f = f"=SUM({col}2:{col}{i - 1})"
        else:
            f = f'=COUNTIFS({src}!$B$2:$B${last},$A{i},{src}!$I$2:$I${last},{col}$1)'
        c = ws.cell(row=i, column=j, value=f)
        body(c, center=True, fill=PatternFill("solid", fgColor=VFILL[v]))
        c.number_format = "0"
    jn, jt = len(VERDICTS) + 2, len(VERDICTS) + 3
    if area == "합계":
        fi = f"=SUM({get_column_letter(jn)}2:{get_column_letter(jn)}{i - 1})"
        ft = f"=SUM({get_column_letter(jt)}2:{get_column_letter(jt)}{i - 1})"
    else:
        fi = f"=SUM({get_column_letter(2)}{i}:{get_column_letter(len(VERDICTS) + 1)}{i})"
        ft = f'=COUNTIF({src}!$B$2:$B${last},$A{i})'
    for jj, ff in ((jn, fi), (jt, ft)):
        c = ws.cell(row=i, column=jj, value=ff)
        body(c, center=True, bold=area == "합계")
        c.number_format = "0"
note = len(areas) + 4
ws.cell(row=note, column=1, value="'점검 항목' 탭의 판정(입력) 칸을 영역별로 집계. 입력됨 < 전체 이면 미입력 항목 있음").font = Font(name=F, size=9, italic=True)

for s in wb.worksheets:
    s.sheet_view.zoomScale = 100
wb.save(OUT)
print(OUT, len(CATALOG), "items")
