# MinIO 고루틴 부하 분석 다이어그램 (Autumn leaves)
S = dict(size=[230, 100], stepx=300, stepy=170)

SPECS = {
    "minio-gr-01-overview": dict(
        S, title="MinIO 고루틴 생성 지점 전체 그림", title_on="MinIO 고루틴 생성 지점",
        hero=["grid"], strong=["drive", "list"], io=["client", "bg"],
        nodes=[N("client", "external", "S3 클라이언트", "GET · PUT · LIST", 0, 0, "1"),
               N("gate", "security", "maxClients", "초과 시 즉시 503", 1, 0, "2"),
               N("set", "backend", "Erasure Set", "드라이브 수만큼 go", 2, 0, "3"),
               N("grid", "messagebus", "grid RPC 수신", "요청마다 go · 상한 없음", 2, 1, "4"),
               N("drive", "database", "드라이브 I/O", "WithDeadline 30s", 1, 1, "5"),
               N("list", "backend", "ListObjects", "set × askDisks", 0, 1),
               N("bg", "cloud", "백그라운드", "스캐너 · 힐 · 복제", 2, 2)],
        edges=[E("client", "gate", "요청"), E("gate", "set", "토큰 획득", "emphasis"),
               E("set", "grid", "원격 드라이브", "emphasis"), E("grid", "drive", "로컬 실행", "emphasis"),
               E("gate", "list", "LIST"), E("list", "grid", "WalkDir 스트림"),
               E("bg", "grid", "S3 상한 우회", "dashed")]),

    "minio-gr-02-get-put": dict(
        S, title="GET 과 PUT 의 고루틴 패턴 차이",
        hero=["pr"], strong=["rb"], io=["get", "put"],
        nodes=[N("get", "external", "GET 요청", "1GiB · EC 12+4", 0, 0, "1"),
               N("meta", "backend", "메타 읽기", "errgroup × 16", 1, 0, "2"),
               N("pr", "backend", "parallelReader", "블록마다 go × 12", 2, 0, "3"),
               N("put", "external", "PUT 요청", "1GiB · EC 12+4", 0, 1, "1"),
               N("enc", "backend", "Encode 루프", "순차 Write", 1, 1, "2"),
               N("rb", "database", "CreateFile", "드라이브당 go 1개", 2, 1, "3")],
        edges=[E("get", "meta", "HEAD 단계"), E("meta", "pr", "1024 블록 반복", "emphasis"),
               E("put", "enc", "1MiB 단위"), E("enc", "rb", "ringbuffer", "emphasis")]),

    "minio-gr-03-list-fanout": dict(
        S, title="ListObjects fan-out",
        hero=["raw"], strong=["remote"], io=["req", "resp"],
        nodes=[N("req", "external", "ListObjects", "prefix 하나", 0, 0, "1"),
               N("merged", "backend", "listMerged", "set 수만큼 go", 1, 0, "2"),
               N("raw", "backend", "listPathRaw", "askDisks 만큼 WalkDir", 2, 0, "3"),
               N("remote", "messagebus", "원격 WalkDir", "스트림당 go 4~5개", 2, 1, "4"),
               N("merge", "backend", "결과 병합", "채널 정렬 병합", 1, 1, "5"),
               N("resp", "external", "응답", "최대 1000개", 0, 1, "6")],
        edges=[E("req", "merged", "32 set"), E("merged", "raw", "set 마다", "emphasis"),
               E("raw", "remote", "16 드라이브", "emphasis"), E("remote", "merge", "엔트리 스트림"),
               E("merge", "resp", "페이지 반환")]),

    "minio-gr-04-drive-hang": dict(
        S, title="드라이브 hang 시 고루틴 누적 흐름",
        hero=["hang"], strong=["pile"], io=["req", "block"],
        nodes=[N("req", "external", "요청 유입", "초당 수천 건", 0, 0, "1"),
               N("wd", "backend", "WithDeadline", "작업 go 생성", 1, 0, "2"),
               N("hang", "database", "syscall 정지", "D-state · 스레드 점유", 2, 0, "3"),
               N("to", "backend", "30s 타임아웃", "호출자만 복귀", 2, 1, "4"),
               N("pile", "backend", "고루틴 누적", "요청 수 × 최대 45s", 1, 1, "5"),
               N("mon", "security", "쓰기 검사", "15s 주기 → faulty", 0, 1, "6"),
               N("block", "external", "errFaultyDisk", "신규 요청 차단", 0, 2, "7"),
               N("crash", "cloud", "pids.max 초과", "스레드 생성 실패", 1, 2)],
        edges=[E("req", "wd", "드라이브 호출"), E("wd", "hang", "작업 실행", "emphasis"),
               E("hang", "to", "응답 없음", "emphasis"), E("to", "pile", "작업 go 잔존", "emphasis"),
               E("pile", "mon", "검사 대기"), E("mon", "block", "offline 전환"),
               E("pile", "crash", "한도 도달", "dashed")]),
}
