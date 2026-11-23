## MinIO 고루틴 부하 분석 - 생성 지점과 폭증 경로

> **목표** : MinIO 코드에서 고루틴이 어디서, 요청당 몇 개씩 생기는지 파악하고 폭증 경로 3곳을 운영 지표로 잡음

- 출처 : github.com/minio/minio (`cmd/`, `internal/`), github.com/minio/pkg (`sync/errgroup`, `workers`)
- 기준 버전 : master `7aac2a2` (2026-02 커밋), 최신 릴리즈 태그 `RELEASE.2025-10-15T17-29-55Z`, minio/pkg v3.1.3 (2026-11 확인)

---

## 1. 개요

MinIO 는 요청 하나를 드라이브·노드 수만큼 쪼개서 병렬로 처리하는 구조임. 그래서 고루틴 수는 요청 수가 아니라 **요청 수 × fan-out(팬아웃)** 으로 늘어남.

- 테스트를 뺀 `go` 문 299개, 다수가 드라이브·노드 단위 fan-out
- S3 진입은 `maxClients` 토큰으로 제한, 노드 간 RPC 와 백그라운드는 이 제한 밖

<!-- diagram: minio-gr-01-overview.html -->

**평소 부하는 잘 통제되고, 폭증은 드라이브 hang · 리스팅 fan-out · 상한 없는 grid 수신 세 경로에서 생긴다.**

---

## 2. 개념 정리

### 2-1. 고루틴을 만드는 4가지 패턴

| 패턴 | 위치 | 동작 | 개수 상한 |
|---|---|---|---|
| errgroup.WithNErrs | minio/pkg sync/errgroup | Go() 호출마다 go 1개 | 없음 |
| errgroup.WithConcurrency(n) | 같은 패키지 | go 먼저 생성 → 안에서 토큰 대기 | 없음 (실행만 n) |
| workers.Take / Give | minio/pkg workers | 토큰 먼저 획득 → go 생성 | n |
| xioutil.WithDeadline | internal/ioutil/ioutil.go:121 | 작업 go 1개 + 타이머 select | 없음 |

- 사용 빈도 : sync.WaitGroup 91곳, errgroup.WithNErrs 64곳, workers.New 11곳, WithDeadline·DeadlineWorker 30곳 이상
- WithConcurrency 와 workers 는 이름이 비슷해도 다름 → 고루틴 수를 묶는 건 workers 쪽뿐임

> 주의 : `WithConcurrency(32)` 를 걸어도 대상이 1만 개면 고루틴 1만 개가 잠깐 떠 있음 (bucket-handlers.go:154, peer-s3-server.go:220, iam-store.go:401)

### 2-2. 진입 제한 - maxClients

- 위치 : cmd/handler-api.go:310
- `requestsPool` 채널에 토큰을 넣는 select 에 `default` 가 있음 → 자리 없으면 바로 503(ErrTooManyRequests)
- 대기열을 두지 않음 → 넘친 요청이 고루틴을 붙잡지 않음
- `requests_max` 미설정 시 자동 계산 : `MemLimit / (set 드라이브 수 × (1MiB + 32KiB) + 2MiB)`
- 예 : MemLimit 192GiB, set 16드라이브 → 노드당 약 11,000

### 2-3. 요청 경로별 fan-out

<!-- diagram: minio-gr-02-get-put.html -->

| 경로 | 생성 방식 | EC 12+4, 1GiB 기준 |
|---|---|---|
| 메타 읽기 (HEAD·GET 앞단) | 드라이브마다 errgroup + WithDeadline | 요청 노드 약 20, 원격 합계 약 24 |
| GET 본문 | 1MiB 블록마다 dataBlocks 개 새로 생성 | 동시 12 안팎, 누적 생성 약 12,000 |
| PUT 본문 | 드라이브당 오래 사는 go 1개 (ringbuffer → CreateFile) | 16 |
| 분산 락 | 락 호스트 수만큼 lock·release + refresh 1 | 호스트 8대면 약 18 |

- GET = 개수보다 생성·소멸 반복이 문제 → 스케줄러·GC 부담 (erasure-decode.go:126 `parallelReader.Read`)
- PUT = 블록 수와 무관, 객체당 드라이브 수만큼 (bitrot-streaming.go:103)
- 원격 드라이브 읽기는 스트림을 한 번 열고 재사용함 → 블록마다 원격 고루틴이 늘지 않음
- 락 서버는 드라이브가 아니라 호스트 단위 (erasure-sets.go:386)

---

## 3. 폭증 경로 3곳

### 3-1. grid RPC 수신 - 상한 없음

- 위치 : internal/grid/connection.go:1414 `handleRequest`
- single RPC 가 들어올 때마다 `go func(m message)` 1개, 토큰·세마포어 없음
- 스트림 RPC 는 `newMuxStream` (muxserver.go:72) 에서 ack, inbound, handler, sender, 생존 확인으로 1개당 4~5개
- ReadVersion, StatVol, Delete, 락 RPC 가 전부 이 경로로 들어옴
- 스캐너·힐·복제·메트릭처럼 S3 상한을 거치지 않는 내부 트래픽도 같은 경로
- 덤 : `newMuxStateless` (muxserver.go:65) 에 빈 `go func(){ // TODO }()` 가 남아 있음, 바로 끝나서 영향은 미미

### 3-2. ListObjects fan-out

<!-- diagram: minio-gr-03-list-fanout.html -->

- `listMerged` (metacache-server-pool.go:259) : pool × set 마다 go 1개
- `listPathRaw` (metacache-set.go:996) : set 마다 askDisks 개 드라이브에 WalkDir
- 원격 드라이브 WalkDir 는 grid 스트림 → 원격 노드에 스트림당 4~5개
- `list_quorum` 기본 strict → askDisks = set 드라이브 수 (metacache-set.go:613)
- 예 : 1풀 × 32set × 16드라이브 → 요청 노드 약 540, 클러스터 전체 2,000 이상

| list_quorum | askDisks (16드라이브 set) | 장점 | 단점 |
|---|---|---|---|
| strict (기본) | 16 | 리스팅 정합성 최고 | fan-out 최대 |
| optimal | 8 | fan-out 절반 | 직후 쓰기·삭제 반영이 느슨 |
| reduced | 2 | 가장 가벼움 | 정합성 가장 약함 |
| auto | 상황에 따라 | 균형 | 동작 예측이 어려움 |

- metacache 가 같은 prefix 반복 리스팅은 흡수함 → prefix 가 서로 다른 동시 리스팅이 몰릴 때 그대로 곱해짐

### 3-3. 드라이브 hang - WithDeadline 잔존 고루틴

<!-- diagram: minio-gr-04-drive-hang.html -->

- WithDeadline 은 작업 go 를 띄우고 타임아웃(기본 30s, `MINIO_DRIVE_MAX_TIMEOUT`) 시 호출자만 돌려보냄
- 작업 go 는 syscall 에 붙잡힌 채 남음 → OS 스레드(M) 도 하나씩 점유
- 차단 시점 : `monitorDiskWritable` (xl-storage-disk-id-check.go) 이 15s 마다 쓰기·읽기 검사 → 타임아웃 초과 시 faulty 전환 → `TrackDiskHealth` 가 errFaultyDisk 즉시 반환
- 누적 구간 = 최대 약 15s + 30s
- `setMaxResources` (server-rlimit.go:48) 가 Go 스레드 한도를 커널 threads-max 의 90% 로 올려둠

> 주의 : 컨테이너 `pids.max`(K8s podPidsLimit) 가 커널 한도보다 낮으면 그쪽에 먼저 걸림 → `failed to create new OS thread` 로 프로세스 종료 가능

**세 경로 중 가장 위험한 건 드라이브 hang 이다. 개수 상한도 없고 OS 스레드까지 같이 쌓인다.**

---

## 4. 백그라운드 워커 비교

| 기능 | 위치 | 크기 | 비고 |
|---|---|---|---|
| 복제 워커 | bucket-replication.go:1872 | auto 100 · fast 500 · slow 50 | large 10, MRF 4 |
| 힐 | global-heal.go:212 | numHealers | workers.New |
| 배치·만료·로테이트 | batch-*.go | GOMAXPROCS/2 | workers.New |
| 디커미션·리밸런스 | decom.go:758, rebalance.go:580 | workerSize | workers.New |
| Peer 알림 | notification.go:76 | 지정 수 | Take 먼저 → 진짜 상한 |
| 클러스터 메트릭 | notification.go:1257 | peer 수 | 스크래핑마다 생성 |

- 복제는 고루틴보다 큐 메모리가 큼 → 워커 채널 버퍼 개당 10,000 × 100, mrfReplicaCh 100,000
- 메트릭은 노드 수 × 스크래핑 주기로 늘어남 → cluster 엔드포인트보다 노드별 수집이 가벼움

---

## 5. 사용법 예시

### 5-1. 고루틴 프로파일 확인

```bash
# 30초 고루틴 프로파일 수집
mc support profile ALIAS --type goroutines --duration 30s

# 많이 쌓인 스택 상위 확인
go tool pprof -top goroutine.pprof | head -30

# 의심 스택
#  ioutil.WithDeadline[...].func1 + syscall      → 드라이브 hang
#  grid.(*Connection).handleRequest.func1        → grid 수신 폭주
#  listPathRaw.func* / WalkDir                   → 리스팅 fan-out
#  parallelReader.Read.func1                     → 대용량 GET 생성 반복
```

### 5-2. 드라이브 대기 수 확인

```bash
# totalWaiting 이 계속 늘면 hang 의심
mc admin info ALIAS --json | jq '.info.servers[].drives[] | {endpoint, state, w: .metrics.totalWaiting}'
```

### 5-3. 리스팅 쿼럼 조정

```bash
# strict → optimal, fan-out 절반
mc admin config set ALIAS api list_quorum=optimal
mc admin config get ALIAS api
```

### 5-4. 알람 - PrometheusRule

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: minio-goroutine
  namespace: monitoring
spec:
  groups:
    - name: minio-goroutine
      rules:
        # 평소 대비 3배 이상, 5분 지속
        - alert: MinioGoroutineSpike
          expr: |
            minio_node_go_routine_total
              > 3 * avg_over_time(minio_node_go_routine_total[1d] offset 1h)
          for: 5m
          labels: {severity: warning}
        # 드라이브 offline 과 같이 보면 hang 구분이 빠름
        - alert: MinioDriveOfflineWithGoroutine
          expr: |
            minio_cluster_drive_offline_total > 0
              and on() max(minio_node_go_routine_total) > 20000
          for: 2m
          labels: {severity: critical}
```

- v3 메트릭명은 `minio_system_process_go_routine_total`
- 임계값 20000 은 예시 → 평소 값 보고 조정

---

## 6. 실무에서 확인

- AIStor 는 상용 포크 → 분석한 커뮤니티 코드와 세부 구현이 다를 수 있음, 서포트에 같은 구조인지 확인 필요
- 드라이브 hang
  - 앞서 겪은 XFS hung task, SAS HDD 다중 offline 이 바로 3-3 경로임
  - 그때 고루틴·스레드 수 그래프를 같이 보면 누적 구간을 확인할 수 있음
  - kubelet `podPidsLimit`, 노드 `kernel.threads-max`, `kernel.pid_max` 를 AIStor 노드 기준으로 점검
- 리스팅 fan-out
  - Spark·Trino 의 Iceberg 파티션 스캔, Airflow 센서의 prefix 폴링이 동시 리스팅을 만듦
  - StarRocks shared-data 도 리스팅이 잦음 → 버킷별 리스팅 빈도부터 측정
  - `list_quorum` 변경은 정합성과 맞바꾸는 것 → 클러스터 전체 설정이라 사용자 1,000명 영향, 바로 바꾸지 않음
- grid 수신
  - 노드 수가 늘수록 노드당 받는 RPC 가 커짐 → 증설 전후 고루틴 수 비교
  - Cilium 쪽 노드 간 지연이 늘면 grid 스트림이 오래 살아서 누적이 커짐
- 메트릭 수집
  - Prometheus 를 여러 대 붙였으면 cluster 엔드포인트 중복 스크래핑부터 정리
- 버전 업그레이드
  - grid 와 WithDeadline 은 릴리즈마다 손이 자주 가는 영역 → 업그레이드 노트에서 해당 파일 변경 여부 확인

---

## 7. 용어 정리

- **고루틴(goroutine)** : Go 런타임이 관리하는 경량 실행 단위, 시작 스택 수 KiB
- **팬아웃(fan-out)** : 요청 하나를 여러 드라이브·노드로 쪼개 병렬 처리하는 것
- **이레이저 세트(erasure set)** : 데이터·패리티를 나눠 저장하는 드라이브 묶음, 보통 16개
- **dataBlocks** : 원본 복원에 필요한 최소 샤드 수, EC 12+4 면 12
- **grid** : MinIO 노드 간 RPC 계층, 연결 하나에 여러 요청을 다중화(mux)
- **maxClients** : S3 요청 동시 처리 상한을 거는 미들웨어
- **WithDeadline** : 작업을 별도 고루틴으로 돌리고 타임아웃 시 먼저 돌아오는 헬퍼
- **D-state** : 커널 I/O 대기 중 깨울 수 없는 프로세스 상태
- **M 스레드** : Go 런타임이 고루틴을 실행하는 OS 스레드
- **list_quorum** : 리스팅 시 몇 개 드라이브에 물어볼지 정하는 설정
- **MRF(Most Recent Failures)** : 복제·힐 실패 항목을 다시 처리하는 큐
- **metacache** : 리스팅 결과를 드라이브에 캐시해 반복 리스팅을 줄이는 구조

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 기본 구조 | 고루틴 수 = 요청 수 × 드라이브·노드 fan-out |
| 진입 제한 | maxClients 토큰, 넘치면 즉시 503, 대기 고루틴 없음 |
| GET | 1MiB 블록마다 dataBlocks 개 생성, 개수보다 생성 반복이 부담 |
| PUT | 드라이브당 오래 사는 고루틴 1개, 안정적 |
| 위험 1 | grid RPC 수신이 요청마다 go, 상한 없음 |
| 위험 2 | ListObjects = set × askDisks, strict 기본 |
| 위험 3 | 드라이브 hang 시 WithDeadline 고루틴과 OS 스레드 누적, 최대 약 45s |
| 확인 지표 | go_routine_total, totalWaiting, drive offline, pprof goroutine |

**드라이브 hang 이 고루틴 폭증의 1순위 원인이고, podPidsLimit 과 리스팅 쿼럼이 그다음 점검 대상이다.**

관련 글 : AIStor drive offline 트러블슈팅 · AIStor SAS HDD 다중 오프라인 · MinIO DirectPV & Performance
