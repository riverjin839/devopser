## Mac 사양 확인 - 명령어 하나씩 쳐보기 (실습 워크북)

> **목표** : 명령어를 한 줄씩 직접 치고 결과를 눈으로 확인함. 결과는 자동으로 MD 파일에 쌓임

- 기준 버전 : macOS 27 Golden Gate (2026-10 기준)
- 진행 방식 : Step 0 에서 기록 함수 등록 → Step 1~9 명령 실행 → Step 10 요약표 작성 → Step 11 마스킹 확인
- 각 Step 구성 : 목적 → 명령 → 결과 예시 → 확인 포인트 → 내 결과 기록

---

## Step 0. 준비 - 기록 함수 등록

- 터미널 열기 : `Cmd + Space` → "터미널" 입력
- 아래를 그대로 붙여넣음. 터미널 창을 닫으면 사라지니 실습 끝날 때까지 같은 창 유지

```bash
# 결과가 쌓일 파일
LOG=~/mac-spec-$(date +%Y%m%d).md
echo "## 내 Mac 사양 실습 기록 ($(date +%Y-%m-%d))" > "$LOG"

# step "제목" '명령' → 화면에 출력 + MD 코드블록으로 기록
step() {
  local title="$1"; shift
  {
    echo; echo "### $title"; echo
    echo '```bash'
    echo "\$ $*"
    eval "$@" 2>&1
    echo '```'
  } | tee -a "$LOG"
}
```

- 확인 : `echo $LOG` → `/Users/<내계정>/mac-spec-YYYYMMDD.md` 나오면 됨
- 사용법 : `step "제목" '명령'` 형태로 침. 명령에 `|` 가 있으면 반드시 작은따옴표로 감쌈
- 기록 없이 그냥 보고 싶으면 `step` 빼고 명령만 쳐도 됨

> 주의 : `step` 은 명령을 `eval` 로 실행함. 여기 나온 조회용 명령만 넣고, 삭제·변경 명령은 넣지 않음

---

## Step 1. OS 버전과 아키텍처

- 목적 : macOS 버전, 칩 계열(Apple Silicon / Intel) 확인

```bash
step "1-1. OS 버전" sw_vers
step "1-2. 아키텍처" uname -m
```

- 결과 예시 (형식만 참고)

```
ProductName:      macOS
ProductVersion:   27.x
BuildVersion:     xxxxx
arm64
```

- 확인 포인트
  - `arm64` = Apple Silicon, `x86_64` = Intel
  - Intel 이면 macOS 27 설치 불가, 26 Tahoe 가 마지막
  - 단, Apple Silicon 에서 Rosetta 터미널로 실행하면 `x86_64` 로 나올 수 있음 → `sysctl -n sysctl.proc_translated` 결과 1 이면 Rosetta

| 항목 | 내 결과 |
|---|---|
| macOS 버전 | |
| 빌드 | |
| 아키텍처 | |

---

## Step 2. 칩 이름

- 목적 : 정확한 칩 모델 확인

```bash
step "2. 칩 이름" sysctl -n machdep.cpu.brand_string
```

- 결과 예시 : `Apple M3 Pro`
- 확인 포인트
  - `-n` = 키 이름 빼고 값만 출력. 빼고 쳐보면 `machdep.cpu.brand_string: ...` 로 나옴 → 차이 직접 확인
  - Intel 이면 `Intel(R) Core(TM) i7-...` 형태

| 항목 | 내 결과 |
|---|---|
| 칩 | |

---

## Step 3. CPU 코어

- 목적 : 전체 코어, 성능(P) 코어, 효율(E) 코어 수 확인

```bash
step "3-1. 전체 코어" sysctl -n hw.ncpu
step "3-2. P 코어" sysctl -n hw.perflevel0.physicalcpu
step "3-3. E 코어" sysctl -n hw.perflevel1.physicalcpu
```

- 결과 예시 : `12` / `6` / `6`
- 확인 포인트
  - **P + E = 전체** 인지 직접 더해봄 → Apple Silicon 은 하이퍼스레딩 없어서 딱 맞음
  - Intel 은 3-2, 3-3 에서 `unknown oid` 에러 남 → 정상임
- 더 보기 : `sysctl hw | grep -i cpu` → CPU 관련 키 전체 목록

| 항목 | 내 결과 |
|---|---|
| 전체 코어 | |
| P 코어 | |
| E 코어 | |
| P + E = 전체? | |

---

## Step 4. 메모리

- 목적 : 총 메모리와 현재 메모리 압박 상태 확인

```bash
step "4-1. 메모리 (바이트)" sysctl -n hw.memsize
step "4-2. 메모리 (GB)" 'echo "$(( $(sysctl -n hw.memsize) / 1024**3 )) GB"'
step "4-3. 메모리 압박" 'memory_pressure | tail -1'
```

- 결과 예시 : `38654705664` / `36 GB` / `System-wide memory free percentage: 62%`
- 확인 포인트
  - 4-1 숫자를 1024 로 세 번 나누면 4-2 가 됨 → 손으로 한 번 검산
  - 여유율이 계속 낮으면(20% 아래) 스왑 사용 중일 가능성 → `sysctl vm.swapusage` 로 확인
- 더 보기 : `vm_stat` → 페이지 단위 상세 (페이지 크기는 첫 줄에 나옴)

| 항목 | 내 결과 |
|---|---|
| 총 메모리 | |
| 여유율 | |

---

## Step 5. 하드웨어 요약 (JSON 으로 골라 뽑기)

- 목적 : 모델명·모델 식별자 확인 + JSON 에서 값만 뽑는 법 연습

```bash
# 먼저 전체 구조를 눈으로 봄 (시리얼도 같이 나오니 기록은 안 함)
system_profiler SPHardwareDataType -json

# 필요한 키만 골라서 기록
step "5-1. 모델명" 'system_profiler SPHardwareDataType -json | plutil -extract SPHardwareDataType.0.machine_name raw -'
step "5-2. 모델 식별자" 'system_profiler SPHardwareDataType -json | plutil -extract SPHardwareDataType.0.machine_model raw -'
```

- 결과 예시 : `MacBook Pro` / `Mac15,6`
- 확인 포인트
  - 첫 번째 명령 출력에서 키 이름 구조 확인 → `SPHardwareDataType` 배열 → `0` 번째 → 키
  - `plutil -extract <경로> raw -` = 그 경로의 값만 출력, 마지막 `-` 는 표준입력
  - 키를 틀리게 치면 `Could not extract value` 에러 → 일부러 한 번 틀려봄
  - 텍스트 출력(`-json` 없이)은 시스템 언어 따라 항목명이 한글일 수 있음 → 스크립트엔 JSON 이 안전함

> 주의 : 전체 출력엔 시리얼 번호, 하드웨어 UUID 가 있음. 이 출력은 `step` 으로 기록하지 않음

| 항목 | 내 결과 |
|---|---|
| 모델명 | |
| 모델 식별자 | |

---

## Step 6. GPU

- 목적 : GPU 이름과 코어 수 확인

```bash
step "6-1. GPU 이름" 'system_profiler SPDisplaysDataType -json | plutil -extract SPDisplaysDataType.0.sppci_model raw -'
step "6-2. GPU 코어" 'system_profiler SPDisplaysDataType -json | plutil -extract SPDisplaysDataType.0.sppci_cores raw -'
```

- 결과 예시 : `Apple M3 Pro` / `18`
- 확인 포인트
  - 6-2 가 에러면 키 이름이 다른 것 → `system_profiler SPDisplaysDataType -json` 전체를 보고 코어 수 키를 찾아 바꿔 침
  - 같은 칩이라도 GPU 코어 수가 다른 모델이 있음 → 구매 사양 확인용으로 유용함

| 항목 | 내 결과 |
|---|---|
| GPU | |
| GPU 코어 | |

---

## Step 7. 스토리지

- 목적 : 디스크 용량, 사용량, 볼륨 구조 확인

```bash
step "7-1. 루트 볼륨 사용량" df -H /
step "7-2. 디스크 정보" 'diskutil info / | grep -E "Device Node|File System Personality|Solid State|Container Total Space|Container Free Space"'
step "7-3. 디스크 구조" diskutil list internal
```

- 결과 예시 (7-1)

```
Filesystem     Size   Used  Avail Capacity  ...  Mounted on
/dev/disk3s1s1 994G    11G   560G     2%    ...  /
```

- 확인 포인트
  - `df -H` = 1000 단위(Finder 표시와 같음), `df -h` = 1024 단위 → 둘 다 쳐서 숫자 차이 확인
  - 7-1 의 Used 가 작게 나와도 정상 → APFS 는 시스템 볼륨과 데이터 볼륨이 컨테이너 공간을 나눠 씀. 실제 사용량은 7-2 의 Container Free Space 로 봄
  - 7-3 에서 `APFS Container` 아래 여러 볼륨(Macintosh HD, Data, Preboot, Recovery, VM) 구조 확인

| 항목 | 내 결과 |
|---|---|
| 컨테이너 전체 | |
| 컨테이너 여유 | |
| SSD 여부 | |

---

## Step 8. 배터리 (맥북만)

- 목적 : 충전 사이클과 배터리 건강도 확인

```bash
step "8-1. 충전 상태" pmset -g batt
step "8-2. 배터리 원시값" 'ioreg -r -c AppleSmartBattery | grep -E "\"CycleCount\"|\"DesignCapacity\"|\"AppleRawMaxCapacity\""'
```

- 결과 예시 (8-2)

```
"AppleRawMaxCapacity" = 6020
"CycleCount" = 132
"DesignCapacity" = 6400
```

- 확인 포인트
  - 건강도 ≈ `AppleRawMaxCapacity ÷ DesignCapacity × 100` → 계산기로 직접 구해봄 (예 : 6020 ÷ 6400 = 94%)
  - 시스템 설정 → 배터리 → 배터리 성능 상태 값과 비교. 계산 방식이 달라 약간 차이 날 수 있음
  - 데스크톱(Mac mini, Studio)은 출력이 비어 있음 → 정상

| 항목 | 내 결과 |
|---|---|
| 사이클 | |
| 건강도 (계산) | |
| 시스템 설정 표시값 | |

---

## Step 9. 기록 파일 확인

- 목적 : 지금까지 쌓인 MD 확인

```bash
cat "$LOG"
open -a TextEdit "$LOG"     # 또는 원하는 편집기
```

- 확인 포인트
  - Step 마다 `### 제목` + 코드블록으로 쌓였는지 확인
  - 잘못 친 명령도 그대로 남아 있음 → 편집기에서 지우면 됨

---

## Step 10. 요약표 작성

- 목적 : Step 1~8 에서 적은 값으로 한 장 요약표 만들기
- 아래를 편집기로 `$LOG` 맨 위(제목 바로 아래)에 붙이고 값 채움

```markdown
### 요약

| 항목 | 값 |
|---|---|
| 모델 | (5-1) (5-2) |
| 칩 | (2) |
| CPU 코어 | 총 (3-1) / P (3-2) / E (3-3) |
| GPU | (6-1), (6-2)코어 |
| 메모리 | (4-2) |
| 스토리지 | 컨테이너 (7-2 전체) / 여유 (7-2 여유) |
| OS | macOS (1-1 버전) |
| 아키텍처 | (1-2) |
| 배터리 | 사이클 (8-2) / 건강도 약 __% |
```

- 손으로 채우는 게 귀찮아지면 그때 자동 스크립트(`mac-spec.sh`)로 넘어가면 됨 → 지금 친 명령이 스크립트 안에서 그대로 쓰임

---

## Step 11. 게시 전 마스킹 확인

- 목적 : 블로그·노션에 올리기 전에 식별 정보가 안 들어갔는지 확인

```bash
grep -n -i -E "serial|일련|uuid|udid|provisioning" "$LOG" || echo "식별 정보 없음"
scutil --get ComputerName
```

- 확인 포인트
  - 첫 줄 결과가 `식별 정보 없음` 이어야 함
  - 컴퓨터 이름에 실명이 있고 기록에 들어갔으면 지움

---

## 용어 정리

- **sysctl** : 커널 상태 값 조회 명령, `-n` 은 값만 출력
- **system_profiler** : 시스템 정보 앱과 같은 데이터를 터미널로 출력, `-json` 지원
- **plutil** : plist·JSON 처리 기본 명령, `-extract <경로> raw -` 로 값 추출
- **성능 코어(P-core) / 효율 코어(E-core)** : 고부하용 / 저전력용 CPU 코어
- **통합 메모리(Unified Memory)** : CPU·GPU 가 같이 쓰는 메모리 풀
- **APFS 컨테이너(Container)** : 여러 볼륨이 공간을 나눠 쓰는 저장 단위
- **Rosetta** : Intel 용 앱을 Apple Silicon 에서 돌리는 변환 계층
- **tee** : 화면 출력과 파일 기록을 동시에 하는 명령, `-a` 는 이어쓰기

---

## 한 장 요약

| Step | 명령 | 볼 것 |
|---|---|---|
| 0 | `step()` 함수 등록 | `$LOG` 경로 |
| 1 | `sw_vers`, `uname -m` | 버전, arm64 여부 |
| 2 | `sysctl -n machdep.cpu.brand_string` | 칩 이름 |
| 3 | `hw.ncpu`, `hw.perflevel0/1.physicalcpu` | P + E = 전체 |
| 4 | `hw.memsize`, `memory_pressure` | GB 환산, 여유율 |
| 5 | `system_profiler SPHardwareDataType -json` + `plutil` | 모델명, JSON 경로 |
| 6 | `SPDisplaysDataType` + `plutil` | GPU 코어 |
| 7 | `df -H /`, `diskutil info /` | 컨테이너 여유 |
| 8 | `pmset -g batt`, `ioreg` | 사이클, 건강도 계산 |
| 9~11 | `cat $LOG`, 요약표, `grep` 마스킹 | 게시 가능 여부 |

**한 줄씩 치면서 출력 구조를 눈에 익히고, 같은 명령을 나중에 스크립트로 묶으면 됨**
