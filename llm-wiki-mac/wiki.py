#!/usr/bin/env python3
"""
wiki.py - Mac 로컬 LLM Wiki (Karpathy LLM Wiki 패턴을 Ollama 로 구현한 최소판)

  raw/        원본 (읽기 전용, LLM 이 수정하지 않음)
  wiki/       LLM 이 쓰는 위키 (sources/, concepts/, analyses/, index.md, log.md)
  AGENTS.md   스키마 (위키 규칙, 사람이 다듬음)

원칙 : LLM 은 "내용"만 JSON 으로 돌려주고, 파일 쓰기·링크·index·log 는 코드가 한다
      → 작은 로컬 모델(4B~8B)도 위키를 망가뜨리지 않음

사용
  python wiki.py init
  python wiki.py ingest raw/local-ai-mac.pdf
  python wiki.py query "RAG 와 LLM Wiki 차이는?" --save
  python wiki.py lint [--llm]
"""
import argparse, datetime as dt, json, os, re, sys
from pathlib import Path

import ollama

ROOT   = Path(os.environ.get("WIKI_ROOT", "."))
RAW    = ROOT / "raw"
WIKI   = ROOT / "wiki"
SCHEMA = ROOT / "AGENTS.md"
MODEL  = os.environ.get("WIKI_MODEL", "gemma3:4b")          # 16GB Mac 이면 8B Q4 까지
OPTS   = {"temperature": 0.2, "num_ctx": 8192}                # 사실 정리라 낮게, 컨텍스트는 명시
CHUNK  = int(os.environ.get("WIKI_CHUNK", "6000"))            # 글자 수. num_ctx 8192 토큰 안에 여유 있게

DEFAULT_SCHEMA = """# AGENTS.md - 위키 규칙
- 언어 : 한국어, 기술 용어는 영문 병기
- 원본(raw/)은 읽기만 함
- 요약은 원문에 있는 내용만. 추측·외부 지식 금지
- 개념(concept) 이름은 짧은 명사구, 같은 개념은 같은 이름으로 (예: "RAG", "양자화")
- 개념 메모는 원문 근거 한 줄
"""

INGEST_SCHEMA = {   # Ollama structured outputs : 응답을 이 JSON 모양으로 강제
    "type": "object",
    "properties": {
        "title":      {"type": "string"},
        "summary":    {"type": "array", "items": {"type": "string"}},
        "concepts":   {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "note": {"type": "string"}},
            "required": ["name", "note"]}},
    },
    "required": ["title", "summary", "concepts"],
}
PICK_SCHEMA = {"type": "object",
               "properties": {"pages": {"type": "array", "items": {"type": "string"}}},
               "required": ["pages"]}
LINK = re.compile(r"\[\[([^\]|#]+)")


# ── 공통 ─────────────────────────────────────────────────────────────
def slug(s: str) -> str:
    s = re.sub(r"[^\w가-힣\- ]+", "", s.strip().lower())
    return re.sub(r"\s+", "-", s)[:60] or "page"


def today() -> str:
    return dt.date.today().isoformat()


def chat_json(system: str, user: str, schema: dict) -> dict:
    r = ollama.chat(model=MODEL, format=schema, options=OPTS,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}])
    return json.loads(r["message"]["content"])


def chat_text(system: str, user: str) -> str:
    r = ollama.chat(model=MODEL, options=OPTS,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}])
    return r["message"]["content"]


def read_source(p: Path) -> str:
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages)
    return p.read_text(encoding="utf-8")


def log(kind: str, title: str):
    with open(WIKI / "log.md", "a", encoding="utf-8") as f:
        f.write(f"## [{today()}] {kind} | {title}\n")


def pages() -> list[Path]:
    return sorted(p for p in WIKI.rglob("*.md") if p.name not in ("index.md", "log.md"))


def first_line(p: Path) -> str:
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("> "):
            return line[2:].strip()
    return ""


def rebuild_index():
    """index.md 는 LLM 이 아니라 코드가 매번 다시 만듦 → 깨질 일 없음"""
    out = ["# index", ""]
    for cat in ("sources", "concepts", "analyses"):
        ps = [p for p in pages() if p.parent.name == cat]
        if ps:
            out += [f"## {cat}", ""]
            out += [f"- [[{cat}/{p.stem}]] - {first_line(p)}" for p in ps]
            out.append("")
    (WIKI / "index.md").write_text("\n".join(out), encoding="utf-8")


# ── init ────────────────────────────────────────────────────────────
def cmd_init(_):
    for d in (RAW, WIKI / "sources", WIKI / "concepts", WIKI / "analyses"):
        d.mkdir(parents=True, exist_ok=True)
    if not SCHEMA.exists():
        SCHEMA.write_text(DEFAULT_SCHEMA, encoding="utf-8")
    (WIKI / "log.md").touch()
    rebuild_index()
    print(f"init 완료 : {ROOT.resolve()}")


# ── ingest ──────────────────────────────────────────────────────────
def upsert_concept(name: str, note: str, src: str):
    p = WIKI / "concepts" / f"{slug(name)}.md"
    line = f"- [[sources/{src}]] : {note.strip()}"
    if not p.exists():
        p.write_text(f"# {name}\n\n> {note.strip()}\n\n## 근거\n\n{line}\n", encoding="utf-8")
        return "new"
    body = p.read_text(encoding="utf-8")
    if f"[[sources/{src}]]" in body:                # 같은 원본 재수집이면 중복 추가 안 함
        return "same"
    p.write_text(body.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")   # 덧붙이기만, 재작성 없음
    return "append"


def cmd_ingest(a):
    src_path = Path(a.path)
    if RAW.resolve() not in src_path.resolve().parents:
        sys.exit("원본은 raw/ 아래에 두고 넣을 것")
    text = read_source(src_path)
    chunks = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
    system = SCHEMA.read_text(encoding="utf-8") + "\n원문 조각을 읽고 JSON 으로만 답함."
    src = slug(src_path.stem)
    summary, concepts, title = [], {}, src_path.stem
    for i, ch in enumerate(chunks, 1):
        print(f"  [{i}/{len(chunks)}] {len(ch)}자")
        j = chat_json(system, f"원본: {src_path.name} ({i}/{len(chunks)})\n\n{ch}", INGEST_SCHEMA)
        if i == 1 and j.get("title"):
            title = j["title"]
        summary += j.get("summary", [])
        for c in j.get("concepts", []):
            concepts.setdefault(c["name"].strip(), c["note"])
    links = " · ".join(f"[[concepts/{slug(n)}]]" for n in concepts)
    (WIKI / "sources" / f"{src}.md").write_text(
        f"---\nsource: {src_path.as_posix()}\ningested: {today()}\nchunks: {len(chunks)}\n---\n"
        f"# {title}\n\n> {summary[0] if summary else ''}\n\n## 요약\n\n"
        + "\n".join(f"- {s}" for s in summary) + f"\n\n## 개념\n\n{links}\n", encoding="utf-8")
    stat = {"new": 0, "append": 0, "same": 0}
    for n, note in concepts.items():
        stat[upsert_concept(n, note, src)] += 1
    rebuild_index()
    log("ingest", title)
    print(f"ingest 완료 : sources/{src}.md, 개념 신규 {stat['new']} · 추가 {stat['append']} · 중복 {stat['same']}")


# ── query ───────────────────────────────────────────────────────────
def cmd_query(a):
    index = (WIKI / "index.md").read_text(encoding="utf-8")
    pick = chat_json("위키 index 를 보고 질문에 필요한 페이지 경로를 최대 5개 고름. 경로는 index 의 [[ ]] 안 문자열 그대로.",
                     f"질문: {a.question}\n\n{index}", PICK_SCHEMA)
    ctx = []
    for ref in pick.get("pages", [])[:5]:
        p = WIKI / f"{ref.strip('[] ')}.md"
        if p.exists():                                  # 모델이 지어낸 경로는 버림
            ctx.append(f"### [[{ref.strip('[] ')}]]\n{p.read_text(encoding='utf-8')}")
    if not ctx:
        sys.exit("관련 페이지를 못 찾음 → ingest 를 먼저 하거나 질문을 바꿀 것")
    ans = chat_text("주어진 위키 페이지만 근거로 한국어로 답함. 문장마다 근거 페이지를 [[경로]] 로 인용. 없으면 모른다고 답함.",
                    f"질문: {a.question}\n\n" + "\n\n".join(ctx))
    print(ans)
    if a.save:                                          # 좋은 답은 위키에 다시 넣어 축적
        p = WIKI / "analyses" / f"{slug(a.question)}.md"
        p.write_text(f"# {a.question}\n\n> {today()} 질의 결과\n\n{ans}\n", encoding="utf-8")
        rebuild_index()
        log("query", a.question)
        print(f"\n저장 : analyses/{p.stem}.md")


# ── lint ────────────────────────────────────────────────────────────
def cmd_lint(a):
    ps = pages()
    names = {f"{p.parent.name}/{p.stem}" for p in ps}
    inbound = {n: 0 for n in names}
    broken = []
    for p in ps:
        for ref in LINK.findall(p.read_text(encoding="utf-8")):
            ref = ref.strip()
            if ref in inbound:
                inbound[ref] += 1
            else:
                broken.append(f"{p.parent.name}/{p.stem} → [[{ref}]]")
    orphans = [n for n, c in inbound.items() if c == 0 and not n.startswith(("sources/", "analyses/"))]
    logged = (WIKI / "log.md").read_text(encoding="utf-8") if (WIKI / "log.md").exists() else ""
    ingested = {p.stem for p in (WIKI / "sources").glob("*.md")}
    pending = [r.name for r in RAW.rglob("*") if r.is_file() and slug(r.stem) not in ingested]
    print(f"페이지 {len(ps)} · 깨진 링크 {len(broken)} · 고아 개념 {len(orphans)} · 미수집 원본 {len(pending)}")
    for b in broken:   print("  깨진 링크 :", b)
    for o in orphans:  print("  고아      :", o)
    for r in pending:  print("  미수집    :", r)
    if a.llm:                                           # 근거가 2개 이상인 개념만 모순 검사
        for p in (WIKI / "concepts").glob("*.md"):
            body = p.read_text(encoding="utf-8")
            if body.count("[[sources/") >= 2:
                v = chat_text("개념 페이지의 근거 줄들이 서로 모순되는지 봄. 모순이면 '모순: 이유' 한 줄, 아니면 'OK'.", body)
                if not v.strip().upper().startswith("OK"):
                    print(f"  검토 필요 : concepts/{p.stem} - {v.strip()[:120]}")
    log("lint", f"broken={len(broken)} orphans={len(orphans)} pending={len(pending)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("ingest"); s.add_argument("path")
    s = sub.add_parser("query");  s.add_argument("question"); s.add_argument("--save", action="store_true")
    s = sub.add_parser("lint");   s.add_argument("--llm", action="store_true")
    a = ap.parse_args()
    {"init": cmd_init, "ingest": cmd_ingest, "query": cmd_query, "lint": cmd_lint}[a.cmd](a)


if __name__ == "__main__":
    main()
