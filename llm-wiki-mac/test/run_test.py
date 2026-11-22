"""wiki.py 를 가짜 ollama 로 끝까지 돌려 파일 처리 로직을 검증"""
import json, os, subprocess, sys, tempfile, textwrap
from pathlib import Path

KIT = Path(sys.argv[1])          # wiki.py 가 있는 폴더
work = Path(tempfile.mkdtemp())
fake = work / "fakemods"; fake.mkdir()
(fake / "ollama.py").write_text(textwrap.dedent('''
    import json
    def chat(model, messages, format=None, options=None):
        u = messages[-1]["content"]
        if format and "concepts" in json.dumps(format):
            if "Ollama" in u:
                d = {"title": "로컬 AI 책 1장", "summary": ["Ollama 는 11434 포트 서버임", "RAG 는 검색 후 생성"],
                     "concepts": [{"name": "Ollama", "note": "모델 실행기"}, {"name": "RAG", "note": "검색 증강 생성"}]}
            else:
                d = {"title": "메모", "summary": ["RAG 는 매번 검색함"],
                     "concepts": [{"name": "RAG", "note": "질문마다 원본 검색"}, {"name": "LLM Wiki", "note": "컴파일된 위키"}]}
            return {"message": {"content": json.dumps(d, ensure_ascii=False)}}
        if format:   # 페이지 고르기 - 없는 경로 하나 섞음
            return {"message": {"content": json.dumps({"pages": ["concepts/rag", "[[sources/notes]]", "concepts/없는페이지"]})}}
        if "모순" in messages[0]["content"]:
            return {"message": {"content": "모순: 근거 두 줄의 설명 범위가 다름"}}
        return {"message": {"content": "RAG 는 질문마다 원본을 검색함 [[concepts/rag]]"}}
'''), encoding="utf-8")
env = dict(os.environ, PYTHONPATH=str(fake), WIKI_ROOT=str(work), WIKI_CHUNK="40")

def run(*args):
    r = subprocess.run([sys.executable, str(KIT / "wiki.py"), *args], env=env, cwd=work,
                       capture_output=True, text=True)
    print(f"$ wiki.py {' '.join(args)}  (rc={r.returncode})\n{r.stdout}{r.stderr}")
    return r

run("init")
(work / "raw" / "book.md").write_text("Ollama 서버와 RAG 설명 " * 6, encoding="utf-8")
(work / "raw" / "notes.md").write_text("RAG 와 위키 비교 메모", encoding="utf-8")
(work / "raw" / "later.md").write_text("아직 안 넣은 원본", encoding="utf-8")
run("ingest", "raw/book.md")
run("ingest", "raw/notes.md")
run("ingest", "raw/notes.md")                    # 재수집 → 중복 근거 추가 안 돼야 함
outside = work / "x.md"; outside.write_text("밖", encoding="utf-8")
assert run("ingest", str(outside)).returncode != 0, "raw/ 밖 원본은 거부돼야 함"
run("query", "RAG 는 뭐야", "--save")
(work / "wiki" / "concepts" / "외톨이.md").write_text("# 외톨이\n\n> 아무도 링크 안 함\n\n[[concepts/없는링크]]\n", encoding="utf-8")
run("lint", "--llm")

rag = (work / "wiki" / "concepts" / "rag.md").read_text(encoding="utf-8")
print("---- concepts/rag.md\n" + rag)
print("---- index.md\n" + (work / "wiki" / "index.md").read_text(encoding="utf-8"))
print("---- log.md\n" + (work / "wiki" / "log.md").read_text(encoding="utf-8"))
assert rag.count("[[sources/notes]]") == 1 and rag.count("[[sources/book]]") == 1
assert "[[analyses/rag-는-뭐야]]" in (work / "wiki" / "index.md").read_text(encoding="utf-8")
print("ALL CHECKS PASSED")
