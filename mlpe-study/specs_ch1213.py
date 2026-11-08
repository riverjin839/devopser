def LMAP(title, hero):
    return dict(
        title=title, hero=hero,
        nodes=[N("k8s", "cloud", "K8s · CI/CD", "기존 플랫폼", 0, 0),
               N("mlflow", "database", "MLflow", "실험 · 레지스트리", 1, 0),
               N("prom", "security", "Prometheus", "인프라 지표", 2, 0),
               N("ingest", "backend", "문서 수집", "PDF · MD · HTML", 0, 1, "12"),
               N("vdb", "database", "벡터 DB", "FAISS · 임베딩", 1, 1, "12"),
               N("llm", "frontend", "LLM 생성", "Gemini · 라우팅", 2, 1, "12"),
               N("prompt", "messagebus", "프롬프트 관리", "Langfuse 라벨", 0, 2, "13"),
               N("guard", "security", "가드레일", "입력 · 출력 검사", 1, 2, "13"),
               N("trace", "messagebus", "LLM 관측", "트레이스 · 비용", 2, 2, "12"),
               N("eval", "security", "평가 · 레드팀", "DeepEval · Promptfoo", 0, 3, "13"),
               N("cache", "database", "시맨틱 캐시", "RedisVL", 1, 3, "13"),
               N("ui", "external", "채팅 UI", "Chainlit 스트리밍", 2, 3, "12")],
        edges=[E("ingest", "vdb", "임베딩", "emphasis"), E("vdb", "llm", "검색 문서", "emphasis"),
               E("prompt", "llm", "템플릿"), E("guard", "llm", "검증된 입력"),
               E("llm", "trace", "트레이스"), E("cache", "ui", "캐시 적중", "dashed"),
               E("ui", "guard", "질문", "emphasis"), E("eval", "prompt", "회귀 테스트", "dashed"),
               E("k8s", "ingest", "", "dashed"), E("trace", "prom", "", "dashed")],
        boundaries=[("LLMOps 확장", ["ingest", "vdb", "llm", "prompt", "guard", "trace", "eval", "cache", "ui"])])


SPECS = {
    "ch12-01-map": LMAP("LLMOps 확장 구성도 - 12장 범위", ["vdb", "ingest", "llm", "trace", "ui"]),
    "ch12-02-rag": dict(
        title="DakkaBot RAG - 빌드 시점과 질의 시점", hero=["vdb"],
        nodes=[N("docs", "external", "사내 문서", "Markdown · ADR · 런북", 0, 0, "1"),
               N("split", "backend", "청크 분할", "1000자 · 겹침 200", 1, 0, "2"),
               N("vdb", "database", "FAISS 인덱스", "임베딩 저장 · save_local", 2, 0, "3"),
               N("ui", "frontend", "Chainlit 응답", "출처 먼저 · 토큰 스트리밍", 0, 1, "7"),
               N("gen", "messagebus", "생성", "Gemini · temperature 0", 1, 1, "6"),
               N("ret", "backend", "검색 · 증강", "질문 임베딩 → top-k 5", 2, 1, "5")],
        edges=[E("docs", "split", "DirectoryLoader", "emphasis"), E("split", "vdb", "임베딩", "emphasis"),
               E("vdb", "ret", "유사도 검색", "emphasis"), E("ret", "gen", "컨텍스트 + 질문", "emphasis"),
               E("gen", "ui", "astream", "emphasis")]),
    "ch12-03-graph": dict(
        title="LangChain 순차 체인 vs LangGraph 그래프", hero=["route"],
        nodes=[N("q1", "external", "질문", "체인 시작", 0, 0),
               N("chain", "backend", "LangChain", "임베딩 → 검색 → 증강 → 생성", 1, 0),
               N("a1", "frontend", "응답", "단순 RAG 에 적합", 2, 0),
               N("route", "security", "의도 분류", "LangGraph 노드", 0, 1),
               N("paths", "backend", "캐시 · 검색 · 되묻기", "조건 분기 · 병렬", 1, 1),
               N("check", "messagebus", "검증 → 재작성 루프", "통과할 때까지", 2, 1)],
        edges=[E("q1", "chain", "", "emphasis"), E("chain", "a1", "", "emphasis"),
               E("route", "paths", "분기", "emphasis"), E("paths", "check", "생성", "emphasis"),
               E("check", "paths", "실패 시", "dashed")]),
    "ch12-04-trace": dict(
        title="Langfuse 로 RAG 단계 추적", hero=["lf"],
        nodes=[N("user", "external", "사용자", "질문", 0, 0, "1"),
               N("core", "backend", "DakkaBotCore", "검색 · 프롬프트 · 생성", 1, 0, "2"),
               N("llm", "frontend", "Gemini", "토큰 입출력", 2, 0, "3"),
               N("dash", "frontend", "대시보드", "비용 · 지연 퍼센타일", 0, 1, "5"),
               N("lf", "messagebus", "Langfuse", "트레이스 · 스팬 · 토큰", 1, 1, "4"),
               N("meta", "database", "메타데이터", "doc_count · context_length", 2, 1)],
        edges=[E("user", "core", "", "emphasis"), E("core", "llm", "invoke", "emphasis"),
               E("core", "lf", "CallbackHandler", "emphasis"), E("meta", "lf", "", "dashed"),
               E("lf", "dash", "", "emphasis")]),

    "ch13-01-map": LMAP("LLMOps 확장 구성도 - 13장 범위", ["guard", "prompt", "eval", "cache"]),
    "ch13-02-prompt": dict(
        title="Langfuse 프롬프트 관리 - 라벨로 배포", hero=["reg"],
        nodes=[N("edit", "frontend", "프롬프트 편집", "UI · 코드 create_prompt", 0, 0, "1"),
               N("reg", "database", "프롬프트 저장소", "버전 · 라벨 · config", 1, 0, "2"),
               N("label", "security", "라벨 이동", "staging → production", 2, 0, "3"),
               N("fb", "external", "경계 프롬프트", "실패 시 안내 문구", 0, 1),
               N("llm", "frontend", "LLM 호출", "model · temperature 적용", 1, 1, "5"),
               N("get", "backend", "get_prompt", "캐시 · compile 변수 채움", 2, 1, "4")],
        edges=[E("edit", "reg", "새 버전", "emphasis"), E("reg", "label", "", "emphasis"),
               E("label", "get", "production 조회", "emphasis"), E("get", "llm", "messages · version", "emphasis"),
               E("llm", "fb", "예외 시", "dashed")]),
    "ch13-03-test": dict(
        title="LLM 테스트 - 의미 평가 + 레드팀", hero=["gate"],
        nodes=[N("golden", "database", "골든 데이터셋", "질문 · 기대 동작", 0, 0, "1"),
               N("geval", "security", "DeepEval G-Eval", "LLM 심판 · 기준 문장", 1, 0, "2"),
               N("gate", "messagebus", "CI 게이트", "임계값 미달 = 배포 차단", 2, 0, "3"),
               N("bot", "frontend", "DakkaBot", "provider 브리지", 0, 1),
               N("pf", "security", "Promptfoo redteam", "plugins × strategies", 1, 1, "4"),
               N("fix", "backend", "프롬프트 · 가드 보강", "실패 케이스 = 회귀 테스트", 2, 1, "5")],
        edges=[E("golden", "geval", "", "emphasis"), E("geval", "gate", "점수", "emphasis"),
               E("pf", "bot", "공격 프롬프트"), E("pf", "fix", "실패 목록", "emphasis"),
               E("fix", "gate", "", "dashed")]),
    "ch13-04-guard": dict(
        title="운영 요청 흐름 - 가드 · 캐시 · 라우팅", hero=["route"], stepy=150,
        nodes=[N("user", "external", "질문", "", 0, 0, "1"),
               N("in", "security", "입력 가드", "PII 마스킹 · 경쟁사 차단", 1, 0, "2"),
               N("cache", "database", "시맨틱 캐시", "유사 질문 재사용", 2, 0, "3"),
               N("out", "security", "출력 가드", "유출 · 범위 · 어조", 0, 1, "6"),
               N("llm", "frontend", "LLM + 안전 설정", "SafetySetting", 1, 1, "5"),
               N("route", "messagebus", "모델 라우팅", "lite · flash · pro", 2, 1, "4"),
               N("resp", "external", "응답", "비용 기록", 0, 2, "7")],
        edges=[E("user", "in", "", "emphasis"), E("in", "cache", "", "emphasis"),
               E("cache", "route", "캐시 미스", "emphasis"), E("route", "llm", "", "emphasis"),
               E("llm", "out", "", "emphasis"), E("out", "resp", "", "emphasis"),
               E("cache", "resp", "적중", "dashed")]),
}

for _k, _v in SPECS.items():
    if "map" not in _k:
        _v.setdefault("size", [300, 110]); _v["stepx"] = 360; _v["stepy"] = max(_v.get("stepy", 150) + 80, 230)
    else:
        _v["size"] = [250, 100]; _v["stepx"] = 320; _v["stepy"] = 190
