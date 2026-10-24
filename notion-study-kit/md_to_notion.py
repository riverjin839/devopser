"""블로그 MD → 노션 MD 변환 + 다이어그램 임베드 삽입.

usage: python3 md_to_notion.py <in.md> <out.notion.md> <ids.json> [related.json]
- in.md 의 `<!-- diagram: NAME.html -->` 줄 → <embed source="file-upload://ID" />
- ids.json : {"NAME": "file_upload_id", ...}  (NAME = .html 뺀 파일명)
- related.json (선택) : {"line": "관련 글 : ...", "urls": ["https://app.notion.com/p/...", ...]}
  → 그 줄을 노션 페이지 멘션으로 교체
"""
import json, re, subprocess, sys, os, tempfile
src, dst, idsf = sys.argv[1:4]
rel = json.load(open(sys.argv[4])) if len(sys.argv) > 4 else None
ids = json.load(open(idsf))
s = open(src, encoding="utf-8").read()
s = re.sub(r'<!-- diagram: (\S+)\.html -->', lambda m: 'EMBEDTOKEN' + re.sub(r'\W', 'X', m.group(1)), s)
if rel: s = s.replace(rel["line"], "RELATEDTOKEN")
here = os.path.dirname(os.path.abspath(__file__))
with tempfile.TemporaryDirectory() as d:
    tmp = os.path.join(d, "t.md"); open(tmp, "w", encoding="utf-8").write(s)
    subprocess.run([sys.executable, os.path.join(here, "to_notion.py"), tmp], check=True)
    s = open(os.path.join(d, "t.notion.md"), encoding="utf-8").read()
for k, v in ids.items():
    s = s.replace('EMBEDTOKEN' + re.sub(r'\W', 'X', k), f'<embed source="file-upload://{v}" />')
if rel:
    s = s.replace("RELATEDTOKEN", rel["line"].split(":")[0].strip() + " : " +
                  " · ".join(f'<mention url="{u}"/>' for u in rel["urls"]))
# 한 장 요약 표 : 항목 열 좁게, 내용 열 넓게 (줄바꿈 방지)
def _widths(m):
    tbl = m.group(2)
    ncol = tbl.split("</tr>")[0].count("<td>")
    if ncol <= 1: return m.group(0)
    cols = [120, 640] if ncol == 2 else [110] + [650 // (ncol - 1)] * (ncol - 1)
    cg = "<colgroup>\n" + "".join(f'<col width="{w}" />\n' for w in cols) + "</colgroup>\n"
    return m.group(1) + tbl.replace(">\n", ">\n" + cg, 1)
s = re.sub(r'(## [^\n]*한 장 요약[^\n]*\n\n)(<table[^>]*>\n(?:.|\n)*?</table>)', _widths, s, count=1)
left = re.findall(r'EMBEDTOKEN\w+|RELATEDTOKEN', s)
if left: sys.exit(f"치환 안 된 토큰: {left}")
open(dst, "w", encoding="utf-8").write(s)
print("embeds:", s.count("<embed"), "chars:", len(s))
