## AIStor - 운영 인계 매뉴얼

> **목표** : AIStor 를 처음 맡는 운영자가 1시간 안에 구조·쿼럼·일상 점검·장애 대응을 이해함

- 출처 : MinIO AIStor 공식 문서(docs.min.io/aistor), 사내 구축 내역
- 기준 버전 : aistor-operator / aistor-objectstore chart 2026-06-24 릴리즈 (2026-10 기준 운영 중)
- 인계 순서 : 개념 10분 → 구조 10분 → 요청 흐름 10분 → 점검·mc 실습 10분 → 배포·모니터링 10분 → 장애 대응·Q&A 10분

---

## 1. 개요

- 사내 S3 = MinIO 상용판 오브젝트 스토리지(AIStor)
- Lake 데이터의 최종 저장소임. Spark, Trino, Airflow, StarRocks 가 S3 로 읽고 씀
- Storage 전용 K8s 클러스터로 따로 운영함. Lake K8s 와는 Cilium ClusterMesh 로 연결됨

<!-- diagram: aistor-01-overview.html -->

**AIStor 가 느려지면 Lake 전체가 느려짐. 그래서 판단 기준은 항상 "한 Set 안에서 몇 개 죽었나" 임**

---

## 2. 개념 정리

### 2-1. 핵심 개념

| 개념 | 설명 | 운영 포인트 |
|---|---|---|
| 버킷·객체(Bucket·Object) | 버킷 = 최상위 이름공간, 객체 = key + 데이터 + 메타 | prefix 는 폴더처럼 보여도 폴더 아님 |
| 드라이브(Drive) | 데이터가 놓이는 디스크 1개 | 최소 장애 단위 |
| 이레이저 세트(Erasure Set) | 드라이브 N개 묶음. 우리는 12개 | 객체 1개는 Set 1개에만 저장됨 |
| 풀(Pool) | Set 여러 개 묶음. 확장 단위 | 우리는 Pool 1개 |
| 이레이저 코딩(EC) | 객체를 data + parity 조각으로 나눠 분산 | 우리는 EC:4 = data 8 + parity 4 |
| 쿼럼(Quorum) | 읽기·쓰기 성공에 필요한 최소 드라이브 수 | 깨지면 그 Set 객체 전부 실패 |
| 힐(Heal) | 잃은 조각을 parity 로 재생성 | 교체 후 자동. 기본 대응은 기다림 |

- 파일시스템 아님 → rename, append, 부분 수정 없음. 객체는 통째로 쓰고 통째로 교체함

### 2-2. 우리 스토리지 구성

<!-- diagram: aistor-02-layout.html -->

| 항목 | 값 |
|---|---|
| 노드 | 6대 (Dell R760, PERC H755) |
| 노드당 드라이브 | SAS HDD 3.5TiB × 24 |
| 전체 드라이브 | 144개 |
| Stripe size | 12 (Set 당 드라이브 수) |
| Erasure Set | 12개 (144 ÷ 12) |
| Parity | EC:4 → data 8 + parity 4 |
| Raw 용량 | 144 × 3.5TiB = 504 TiB |
| 가용 용량 | 504 × 8/12 ≈ 336 TiB (메타데이터 오버헤드 전) |
| 저장 효율 | 66.7% |

- 대칭 배치 기준 → Set 1개가 노드마다 드라이브 2개씩 가짐 (12 = 6 × 2)

> 주의 : 노드별 2개 배치는 대칭 배치 가정임. `mc admin info --json` 의 Set 별 endpoint 로 실제 분포를 한 번 확인함

### 2-3. 쿼럼과 장애 허용

| 구분 | 필요 드라이브 | 의미 |
|---|---|---|
| Read quorum | 8 / 12 | Set 안에서 4개까지 죽어도 읽힘 |
| Write quorum | 8 / 12 | Set 안에서 4개까지 죽어도 쓰기 됨 |

- data(8) ≠ parity(4) → 쓰기 쿼럼 = data 수 = 8
- 단, data = parity 이면 쓰기 쿼럼이 data + 1 로 올라감 (예 : 8드라이브 EC:4 → 5/8)

<!-- diagram: aistor-04-fault.html -->

| 장애 | Set 당 잃는 드라이브 | 읽기·쓰기 |
|---|---|---|
| 드라이브 1개 | 1개 (그 Set 만) | 정상 |
| 노드 1대 | 모든 Set 에서 2개 | 정상, 여유 2개 |
| 노드 2대 | 모든 Set 에서 4개 | 정상, 여유 0 |
| 노드 3대 | 모든 Set 에서 6개 | 쿼럼 상실 → 전체 중단 |

**운영 원칙 : 노드는 한 번에 1대만 내림 (점검·재부팅·업그레이드 모두)**

### 2-4. 요청 흐름

<!-- diagram: aistor-03-put.html -->

- PUT : 아무 노드나 받음(master 없음) → 객체 이름 해시로 Set 결정 → data 8 + parity 4 분할 → 12개 드라이브에 병렬 기록 → 8개 성공 시 200 OK
- GET : 담당 Set 계산 → 조각 8개 읽음 → 조각별 비트롯(bitrot) 체크섬 검증 → 복원 후 응답. 깨진 조각은 heal 대상으로 등록
- LIST : 객체가 모든 Set 에 흩어져 있음 → 12개 Set, HDD 144개 전부에 fan-out 함. 가장 비싼 요청임

> 주의 : LIST 카운터는 "완료 시점" 에 올라감. LIST 가 막히면 처리량 지표는 떨어지고 inflight·goroutine 은 치솟음. 부하가 준 게 아니라 막힌 것임

- HDD 라서 seek 비용이 큼 → LIST·소형 객체 부하에 SSD 보다 약함
- 3.5TiB HDD 1개 heal 은 수 시간 걸림 → 작업 계획 때 heal 시간 감안함

---

## 3. 우리 환경 구조

### 3-1. 클러스터

- AIStor K8s = Storage 전용, Lake K8s(Compute) 와 물리 분리
- 연결 = Cilium ClusterMesh
- 노드는 DC1·DC2 에 걸쳐 있음. 네트워크 = leaf → spine → super spine
- AIStor 드라이브와 별개 디스크에 OpenEBS(XFS) 로컬 볼륨도 있음
- 노드마다 nkia 모니터링 agent 동작

### 3-2. K8s 오브젝트

| 구성 요소 | 역할 |
|---|---|
| aistor-operator chart | Operator 설치 (object-store-operator, adminjob-operator) |
| aistor-objectstore chart | ObjectStore CR 생성 → Operator 가 워크로드·Service·인증서 생성 |
| ObjectStore CR | "이런 스토리지 만들어라" 선언. Operator 가 계속 맞춤 |
| 서버 파드 | 노드당 1개, 그 노드 HDD 24개 담당 |
| Service | S3 API, Console 노출 |
| Secret | root 크리덴셜·환경변수. 외부 공유 금지 |

### 3-3. 접속 경로

| 클라이언트 | 경로 |
|---|---|
| 외부 (사용자 PC, 타 시스템) | 도메인 → Cilium LB-IP → Ingress → AIStor Service |
| Lake K8s 워크로드 | minio-global.aistor.svc.cluster.local:80 (ClusterMesh global service) |
| AIStor K8s 내부 | 클러스터 내부 Service |

- 이미지·차트 = dmz-nexus 프록시 (upstream lake-nexus). master 에서 바로 helm repo add 가능

---

## 4. 비교

### 4-1. Stripe 12 에서 parity 선택

| 항목 | EC:2 | EC:3 | EC:4 (현재) |
|---|---|---|---|
| data + parity | 10 + 2 | 9 + 3 | 8 + 4 |
| 가용 용량 | 약 420 TiB | 약 378 TiB | 약 336 TiB |
| Set 당 허용 장애 | 2개 | 3개 | 4개 |
| 노드 장애 허용 | 1대 (여유 0) | 1대 (여유 1) | 2대 (여유 0) |
| 언제 쓰나 | 용량 우선, 장애 위험 낮음 | 중간 | 노드 2대 동시 장애까지 버텨야 할 때 |

- EC:4 = 용량 33% 를 내주고 노드 2대 장애까지 버팀
- 단, 노드 2대가 빠지면 여유 0 → 그 상태로 오래 두지 않음

### 4-2. AIStor 와 Isilon NAS

| 항목 | AIStor (S3) | Isilon NAS (NFS) |
|---|---|---|
| 접근 방식 | S3 API, 객체 단위 | POSIX 파일, RWX 마운트 |
| 장점 | 수평 확장, Spark·Trino·Iceberg 와 바로 붙음 | 기존 앱 수정 없이 사용 |
| 단점 | rename·append 없음, LIST 비쌈 | 메타데이터·잠금 병목, 지연 민감 앱에 약함 |
| 언제 쓰나 | Lake 테이블·대용량 데이터 | 공유 홈·설정·레거시 앱 |

---

## 5. 사용법 예시

### 5-1. 접속

```bash
# 운영자 개인 access key 로 alias 등록 (root 키 사용 지양)
mc alias set aistor https://<s3-endpoint-domain> <ACCESS_KEY> <SECRET_KEY>
mc ping aistor          # 노드별 응답
mc ready aistor         # 클러스터 ready 여부
```

### 5-2. 상태 확인 (매일)

```bash
mc admin info aistor    # 서버·드라이브·용량·parity 요약

# 비정상 드라이브만 출력
mc admin info aistor --json | jq '[.info.servers[].drives[] | select(.state!="ok")]'

mc admin heal aistor    # heal 상태
```

### 5-3. 실시간 진단

```bash
mc admin trace aistor --errors                          # 에러난 호출만
mc admin trace aistor -v --response-threshold 1s        # 1초 넘는 요청만
mc admin trace aistor --call s3 --path '<bucket>/*'     # 특정 버킷만
mc admin top locks aistor                               # 오래 잡힌 lock
```

- trace 는 부하가 있음 → 원인 잡으면 바로 Ctrl+C

### 5-4. 버킷·권한

```bash
mc mb aistor/<bucket>                                   # 버킷 생성
mc du aistor/<bucket>                                   # 사용량
mc quota set aistor/<bucket> --size 10TiB               # 쿼터
mc ilm rule add aistor/<bucket> --prefix "tmp/" --expire-days 30   # 만료 정책

mc admin policy create aistor <policy> ./policy.json    # 버킷 단위 최소 권한 정책
mc admin policy attach aistor <policy> --user <user>
mc admin accesskey create aistor <user>                 # 서비스용 키 발급
```

### 5-5. 배포·업그레이드

<!-- diagram: aistor-05-deploy.html -->

```bash
# 현재 상태
helm list -n aistor
helm get values <objectstore-release> -n <ns> > current-values.yaml
kubectl get objectstore -A
kubectl get pods -n <ns> -o wide

# 업그레이드 : operator 먼저, objectstore 나중
helm upgrade aistor <repo>/aistor-operator -n aistor -f aistor-operator-values.yaml --version <ver>
helm upgrade <objectstore-release> <repo>/aistor-objectstore -n <ns> -f aistor-objectstore-values.yaml --version <ver>
```

- 파드 직접 수정 안 함 → values → helm upgrade → Operator 반영
- 업그레이드 전 조건 = 드라이브 전부 ok, heal 없음
- 이후 릴리즈에 RDMA 정식 지원(Operator chart 6.0.0+), AIStor Tables(관리형 Iceberg) 추가됨. 도입은 별도 계획

### 5-6. 위험 명령 (승인 없이 실행 금지)

| 명령 | 이유 |
|---|---|
| mc admin service restart | 전 노드 동시 재시작 → 전체 순단 |
| mc admin service stop | 전체 중지 |
| mc rb --force | 버킷과 데이터 삭제 |
| mc rm --recursive --force | 대량 삭제 |
| mc admin decom start | Pool 퇴역, 장시간 고부하 |
| mc support perf | 성능 측정 부하 큼, 업무시간 금지 |

---

## 6. 실무에서 확인

### 6-1. 일상 점검

- 매일 : mc admin info 로 offline 0 확인 → kubectl 로 Running 아닌 파드 확인 → 5xx·TTFB·inflight 확인 → 용량 80% 미만 확인
- 매주 : 버킷별 사용량 추이, 쿼터 근접 버킷, 미사용 access key, iDRAC SMART·RAID 경고
- 변경 전 : mc admin info --json 스냅샷 저장 → offline·heal 있으면 작업 보류

### 6-2. 모니터링 (metrics v3)

| 분류 | 볼 것 | 경고 기준 |
|---|---|---|
| 드라이브 | offline 수 | 1개 이상 확인, 한 Set 3개 이상 긴급 (한계 4) |
| 노드 | online 서버 수 | 1대 빠짐 경고, 2대 빠짐 긴급 (여유 0) |
| 용량 | 사용률 | 80% 경고, 90% 긴급 |
| API | inflight·goroutine | 급증과 처리량 하락 동시 = 막힘 신호 |
| 지연 | TTFB | 평시 p99 의 2배 |
| Heal | 대기 객체 수 | 오래 줄지 않음 |

- 사용자별 Prometheus 지표 없음 → 호출 주체는 audit log 로 찾음

> 주의 : 벤더 지원팀은 v2 지표명으로 답하는 경우가 많음. 티켓 첫 줄에 "metrics v3 사용" 을 적고 이름 매핑을 요청함

### 6-3. 장애 대응

<!-- diagram: aistor-06-incident.html -->

| 증상 | 판단 | 조치 |
|---|---|---|
| 드라이브 1개 offline | 여유 충분 | iDRAC·PERC 로그 확인 → 교체 일정 → 자동 heal 확인 |
| 한 Set 3개 이상 offline | 쿼럼 근접 | 긴급. 추가 작업 중단, 벤더 티켓, 교체 최우선 |
| 노드 1대 다운 | Set 당 2개 손실 | 서비스 유지. 노드 복구 최우선 |
| 노드 2대 다운 | Set 당 4개 손실 | 여유 0. 1개만 더 죽으면 중단 → 즉시 에스컬레이션 |
| 느림 + goroutine 급증 | LIST 막힘 | trace·audit 로 대량 LIST 주체 찾아 제한 요청 |
| 403 급증 | 키·정책 문제 | 키 만료·비활성, 정책 변경 이력 확인 |
| minio-global 간헐 끊김 | ClusterMesh 경로 | Lake → AIStor 구간별 확인 (원인 조사 중인 이슈) |

- 드라이브 교체 순서 : 위치 확인(endpoint ↔ 슬롯) → 같은 Set 나머지 정상 확인 → 교체(PERC 설정 동일) → 같은 경로 마운트 → 자동 heal → 끝날 때까지 그 Set 작업 금지

### 6-4. 하지 말 것

- 서버 파드·노드를 한 번에 1대 넘게 내림
- 문제 해결용으로 mc admin service restart 사용
- 드라이브 디렉토리(.minio.sys, xl.meta) 직접 수정
- AIStor HDD 와 OpenEBS XFS 디스크 혼동. 포맷 전 디바이스 3번 확인
- root 크리덴셜을 앱·개인에게 공유
- heal 중 추가 드라이브 작업·업그레이드

### 6-5. 에스컬레이션

| 단계 | 대상 | 준비물 |
|---|---|---|
| 1 | 플랫폼팀 담당 | mc admin info 결과, 증상 시간대 |
| 2 | 벤더 (SUBNET) | mc support diag 번들, trace 발췌, metrics v3 명시 |
| 3 | 네트워크팀 | DC 간·ClusterMesh 의심 시 노드 IP, 시간대 |
| 4 | 서버(HW) | iDRAC·PERC 로그, 드라이브 슬롯 |

---

## 7. 용어 정리

- **스트라이프 크기(Stripe size)** : Set 1개를 이루는 드라이브 수. 우리는 12
- **이레이저 세트(Erasure Set)** : 객체가 저장되는 드라이브 묶음. 우리는 12개
- **패리티(Parity, EC:N)** : 복구용 조각 수. 이만큼 잃어도 읽힘
- **쿼럼(Quorum)** : 성공 판정에 필요한 최소 드라이브 수
- **힐(Heal)** : 잃은 조각을 parity 로 재생성하는 작업
- **비트롯(Bitrot)** : 디스크에서 조용히 데이터가 깨지는 현상. 체크섬으로 잡음
- **디커미션(Decommission)** : Pool 퇴역. 데이터를 다른 Pool 로 옮김
- **리밸런스(Rebalance)** : Pool 간 데이터 재분배
- **ILM(Lifecycle)** : 객체 만료·전환 정책
- **오퍼레이터(Operator)** : ObjectStore CR 을 보고 K8s 리소스를 맞추는 컨트롤러
- **클러스터메시(ClusterMesh)** : Cilium 의 멀티 클러스터 연결 기능
- **SUBNET** : MinIO 상용 지원·라이선스 포털

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 정체 | 사내 S3. Lake 데이터 최종 저장소 |
| 구성 | 노드 6 × HDD 24 = 144 드라이브 → Set 12개 × Stripe 12 → Pool 1개 |
| 용량 | raw 504 TiB, 가용 약 336 TiB (EC:4, 효율 66.7%) |
| 쿼럼 | 읽기 8/12, 쓰기 8/12 → Set 당 4개까지 허용 |
| 노드 장애 | 1대 정상, 2대 여유 0, 3대 전체 중단 |
| 매일 | mc admin info 하나로 대부분 파악 |
| 느릴 때 | trace --errors, goroutine 급증과 처리량 하락 = LIST 막힘 |
| 변경 | values → helm upgrade. operator 먼저 |
| 금지 | 노드 동시 다운, service restart, 드라이브 직접 수정 |
| 벤더 | support diag + metrics v3 명시 |

**노드는 한 번에 1대만 내리고, 장애는 항상 Set 단위로 셈**

관련 글 : AIStor 영문판 · 중문판 · MinIO
