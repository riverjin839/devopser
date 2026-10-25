## Mac 사양 확인 - 명령어와 결과 정리 자동화

> **목표** : 내 Mac 사양을 GUI·터미널로 확인하고, 블로그·노션에 바로 올릴 MD 표로 자동 정리함

- 출처 : Apple 시스템 정보 앱, macOS 기본 명령어 (`system_profiler`, `sysctl`, `diskutil`, `ioreg`)
- 기준 버전 : macOS 27 Golden Gate (2026-10 기준)

---

## 1. 개요

- 맥 사양 확인 경로는 두 가지 → GUI(이 Mac에 관하여, 시스템 리포트), 터미널(명령어)
- 한 번 보고 끝낼 거면 GUI, 기록·공유·비교할 거면 터미널
- 터미널 결과는 스크립트로 MD 표까지 자동 생성 → 민감 정보 빼고 게시

<!-- diagram: mac-spec-overview.html -->

**사양 정리는 터미널 `-json` 출력을 스크립트로 파싱해 MD 표로 뽑는 게 가장 재현성이 좋음**

> 주의 : macOS 27 부터 Intel Mac 지원 종료됨. Intel Mac 은 macOS 26 Tahoe 가 마지막 버전임

---

## 2. 개념 정리

### 2-1. 확인 경로 두 가지

| 경로 | 위치 | 확인 가능한 정보 |
|---|---|---|
| 이 Mac에 관하여 | 좌측 상단 Apple 메뉴 | 칩, 메모리, 시리얼, macOS 버전 |
| 시스템 리포트 | 이 Mac에 관하여 → 추가 정보 → 시스템 리포트 | CPU 코어, GPU, 스토리지, 배터리, USB 등 전체 |
| 저장 공간 | 시스템 설정 → 일반 → 저장 공간 | 디스크 사용량 카테고리별 |
| 터미널 | 응용 프로그램 → 유틸리티 → 터미널 | 위 정보 전부 + 스크립트 자동화 |

- 시스템 정보 앱 바로 열기 : `Option` 누른 채 Apple 메뉴 클릭 → 시스템 정보

### 2-2. 항목별 확인 명령어

<!-- diagram: mac-spec-cmdmap.html -->

| 항목 | 명령어 | 비고 |
|---|---|---|
| OS 버전 | `sw_vers` | 제품명, 버전, 빌드 |
| 아키텍처 | `uname -m` | arm64 = Apple Silicon, x86_64 = Intel |
| 칩 이름 | `sysctl -n machdep.cpu.brand_string` | 예 : Apple M3 Pro |
| 전체 코어 | `sysctl -n hw.ncpu` | 논리 코어 수 |
| P / E 코어 | `sysctl -n hw.perflevel0.physicalcpu` / `perflevel1` | Apple Silicon 만 있음 |
| 메모리 | `sysctl -n hw.memsize` | 바이트 단위 |
| 메모리 상태 | `vm_stat`, `memory_pressure` | 페이지 단위, 압박 수준 |
| GPU | `system_profiler SPDisplaysDataType` | GPU 코어 수, 모니터 |
| 스토리지 | `df -H /`, `diskutil info /` | 용량, 사용량, SSD 여부 |
| 배터리 | `ioreg -r -c AppleSmartBattery` | 사이클, 설계·현재 용량 |
| 전체 요약 | `system_profiler SPHardwareDataType` | 모델명, 칩, 메모리, 시리얼 |

### 2-3. Apple Silicon 구성과 sysctl 키

<!-- diagram: mac-spec-silicon.html -->

- Apple Silicon = CPU · GPU · 메모리가 한 칩에 묶인 구조(SoC)
- CPU 코어가 두 종류 → 성능(P) 코어, 효율(E) 코어
- `hw.ncpu` = P + E 합계, 하이퍼스레딩 없음
- 메모리는 CPU·GPU 가 같이 쓰는 통합 메모리 → 나중에 증설 불가
- 단, Intel Mac 은 `hw.perflevel*` 키가 없음 → 스크립트에서 빈 값 처리 필요

### 2-4. 출력 형식

| 형식 | 예 | 특징 |
|---|---|---|
| 텍스트 | `system_profiler SPHardwareDataType` | 사람이 읽기 좋음, 시스템 언어 따라 항목명이 바뀔 수 있음 |
| JSON | `system_profiler SPHardwareDataType -json` | 키 고정, 스크립트 파싱용 |
| 단일 값 | `sysctl -n hw.memsize` | 값만 출력, 변수에 바로 넣기 좋음 |

- JSON 값 추출은 `plutil -extract <키경로> raw -` 로 함 (macOS 12 이상)
- `jq` 는 기본 설치 보장이 없어서 `plutil` 이 안전함

---

## 3. 도구 비교

| 도구 | 기능 | 장점 | 단점 | 언제 쓰나 |
|---|---|---|---|---|
| 시스템 리포트 | GUI 전체 사양 | 클릭만으로 확인 | 복사·자동화 어려움 | 한 번 보고 끝낼 때 |
| system_profiler | 하드웨어 전체 덤프 | `-json` 지원, 항목 가장 많음 | 전체 실행은 느림 (데이터 타입 지정 권장) | 스크립트 정리 |
| sysctl | 커널 값 조회 | 빠름, 값만 출력 | 하드웨어 일부만 | CPU·메모리 |
| diskutil / df | 디스크 정보 | 볼륨·파티션 상세 | 표시 단위 섞임 | 스토리지 |
| ioreg | IOKit 레지스트리 | 배터리 원시값 | 출력이 길고 난해함 | 배터리 건강도 |

---

## 4. Linux 대응 명령어

- 서버 운영하던 습관대로 찾으면 대응표가 편함

| 확인 대상 | Linux | macOS |
|---|---|---|
| CPU | `lscpu`, `/proc/cpuinfo` | `sysctl -n machdep.cpu.brand_string`, `hw.ncpu` |
| 메모리 | `free -h`, `/proc/meminfo` | `sysctl -n hw.memsize`, `vm_stat` |
| 디스크 | `lsblk`, `df -h` | `diskutil list`, `df -H` |
| 하드웨어 전체 | `dmidecode`, `lshw` | `system_profiler` |
| OS | `cat /etc/os-release` | `sw_vers` |
| 커널·아키텍처 | `uname -r -m` | `uname -r -m` |

> 주의 : macOS `df -h` 는 1024 단위, `-H` 는 1000 단위임. Finder 표시값과 맞추려면 `-H` 를 씀

---

## 5. 사용법 예시

### 5-1. 빠른 확인

```bash
sw_vers
uname -m
sysctl -n machdep.cpu.brand_string
echo "$(( $(sysctl -n hw.memsize) / 1024**3 )) GB"
df -H /
```

### 5-2. 결과 MD 자동 생성 스크립트

<!-- diagram: mac-spec-script.html -->

- `mac-spec.sh` 로 저장 후 실행 → `mac-spec-YYYYMMDD.md` 생성됨
- 시리얼·UUID 는 일부러 수집 안 함

```bash
#!/bin/bash
# mac-spec.sh : 맥 사양을 MD 표로 정리
OUT="mac-spec-$(date +%Y%m%d).md"

# system_profiler JSON 은 한 번만 실행해서 재사용 (느림)
HW_JSON=$(system_profiler SPHardwareDataType -json 2>/dev/null)
GPU_JSON=$(system_profiler SPDisplaysDataType -json 2>/dev/null)
hw()  { echo "$HW_JSON"  | plutil -extract "SPHardwareDataType.0.$1" raw - 2>/dev/null || echo "-"; }
gpu() { echo "$GPU_JSON" | plutil -extract "SPDisplaysDataType.0.$1" raw - 2>/dev/null || echo "-"; }

MODEL=$(hw machine_name)
MODEL_ID=$(hw machine_model)
CHIP=$(sysctl -n machdep.cpu.brand_string)
NCPU=$(sysctl -n hw.ncpu)
# Intel Mac 은 perflevel 키가 없음 → "-"
PCORE=$(sysctl -n hw.perflevel0.physicalcpu 2>/dev/null || echo "-")
ECORE=$(sysctl -n hw.perflevel1.physicalcpu 2>/dev/null || echo "-")
MEM="$(( $(sysctl -n hw.memsize) / 1024**3 )) GB"
GPU_NAME=$(gpu sppci_model)
GPU_CORES=$(gpu sppci_cores)
OS="$(sw_vers -productName) $(sw_vers -productVersion) ($(sw_vers -buildVersion))"
ARCH=$(uname -m)
read -r DISK_SIZE DISK_USED DISK_AVAIL DISK_PCT <<< "$(df -H / | awk 'NR==2{print $2, $3, $4, $5}')"

# 배터리 : 데스크톱이면 값이 비어서 행 생략
CYCLE=$(ioreg -r -c AppleSmartBattery | awk -F'= ' '/"CycleCount"/{print $2; exit}')
DESIGN=$(ioreg -r -c AppleSmartBattery | awk -F'= ' '/"DesignCapacity"/{print $2; exit}')
RAWMAX=$(ioreg -r -c AppleSmartBattery | awk -F'= ' '/"AppleRawMaxCapacity"/{print $2; exit}')
if [ -n "$DESIGN" ] && [ "$DESIGN" -gt 0 ]; then
  HEALTH="$(( RAWMAX * 100 / DESIGN ))%"
fi

cat > "$OUT" <<EOF
## 내 Mac 사양 ($(date +%Y-%m-%d) 기준)

| 항목 | 값 |
|---|---|
| 모델 | ${MODEL} (${MODEL_ID}) |
| 칩 | ${CHIP} |
| CPU 코어 | 총 ${NCPU} (P ${PCORE} / E ${ECORE}) |
| GPU | ${GPU_NAME} (${GPU_CORES}코어) |
| 메모리 | ${MEM} |
| 스토리지 | ${DISK_SIZE} (사용 ${DISK_USED} / 여유 ${DISK_AVAIL}, ${DISK_PCT}) |
| OS | ${OS} |
| 아키텍처 | ${ARCH} |
EOF

if [ -n "$CYCLE" ]; then
  echo "| 배터리 | 사이클 ${CYCLE}회 / 건강도 약 ${HEALTH} |" >> "$OUT"
fi

echo "생성 완료: $OUT"
cat "$OUT"
```

```bash
chmod +x mac-spec.sh && ./mac-spec.sh
```

### 5-3. 결과 예시

- 아래 값은 형식 예시임. 실제 값은 스크립트 결과로 채움

| 항목 | 값 |
|---|---|
| 모델 | MacBook Pro (Mac15,6) |
| 칩 | Apple M3 Pro |
| CPU 코어 | 총 12 (P 6 / E 6) |
| GPU | Apple M3 Pro (18코어) |
| 메모리 | 36 GB |
| 스토리지 | 994G (사용 412G / 여유 560G, 43%) |
| OS | macOS 27.0 |
| 아키텍처 | arm64 |
| 배터리 | 사이클 132회 / 건강도 약 94% |

- 배터리 건강도 = `AppleRawMaxCapacity / DesignCapacity × 100` 근사값
- 시스템 설정 → 배터리 화면의 최대 용량과 약간 다를 수 있음

---

## 6. 실무에서 확인

### 6-1. arm64 맥 ↔ amd64 클러스터

- 개발 맥 = arm64, 폐쇄망 bare-metal 노드 = amd64 → 로컬 빌드 이미지를 그대로 Nexus 에 올리면 노드에서 `exec format error` 남
- 반입 이미지는 `docker buildx build --platform linux/amd64` 로 빌드하거나 멀티 아키 매니페스트로 미러링
- 단, amd64 빌드는 에뮬레이션이라 느림 → 무거운 빌드는 사내 CI 빌더에서 처리

### 6-2. 로컬 K8s 리소스 기준

- kind, colima, Docker Desktop VM 메모리는 `hw.memsize` 확인 후 절반 이하로 잡음
- CPU 는 P 코어 수 기준으로 할당 → E 코어까지 꽉 채우면 IDE·브라우저가 버벅임
- 통합 메모리라 GPU 도 같은 풀을 씀 → 로컬 LLM·이미지 작업 병행 시 여유 더 둠

### 6-3. 장비 점검·자산 관리

- macOS 27 Intel 지원 종료 → 팀 장비 중 `uname -m` 이 x86_64 인 맥은 교체 대상 목록에 올림
- 자산 등록에는 시리얼이 필요함 → 사내 제출용과 블로그 게시용 결과를 분리
- 동일 스크립트를 여러 대에서 돌리면 같은 형식 표가 나와서 비교가 쉬움

### 6-4. 게시 전 마스킹

- 빼야 하는 것 : 시리얼 번호, 하드웨어 UUID, 프로비저닝 UDID, 실명 들어간 컴퓨터 이름
- `system_profiler SPHardwareDataType` 원본 출력을 그대로 붙이면 시리얼이 노출됨
- 컴퓨터 이름 확인 : `scutil --get ComputerName`

> 주의 : 스크린샷 게시도 같은 규칙임. 이 Mac에 관하여 창에는 시리얼이 바로 보임

---

## 7. 용어 정리

- **시스템 정보(System Information)** : 하드웨어·소프트웨어 사양을 보여주는 macOS 기본 앱, GUI 판 system_profiler
- **system_profiler** : 시스템 정보 앱과 같은 데이터를 터미널로 출력하는 명령, `-json` 지원
- **sysctl** : 커널 상태 값을 조회하는 명령, CPU·메모리 값이 빠름
- **SoC(System on Chip)** : CPU·GPU·메모리 컨트롤러 등을 한 칩에 넣은 구조
- **성능 코어(P-core)** : 고부하 작업용 코어, `hw.perflevel0`
- **효율 코어(E-core)** : 저전력 백그라운드 작업용 코어, `hw.perflevel1`
- **통합 메모리(Unified Memory)** : CPU·GPU 가 같이 쓰는 메모리 풀, 구매 후 증설 불가
- **plutil** : plist·JSON 을 다루는 기본 명령, `-extract ... raw` 로 값 추출
- **ioreg** : IOKit 장치 트리를 출력하는 명령, 배터리 원시값 확인용
- **APFS 컨테이너(Container)** : 여러 볼륨이 공간을 공유하는 APFS 저장 단위, `diskutil list` 에서 보임
- **arm64 / x86_64** : Apple Silicon / Intel 아키텍처 이름, `uname -m` 결과

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 빠른 확인 | Apple 메뉴 → 이 Mac에 관하여 → 시스템 리포트 |
| OS | `sw_vers`, `uname -m` |
| CPU | `machdep.cpu.brand_string`, `hw.ncpu`, `hw.perflevel0/1.physicalcpu` |
| 메모리 | `hw.memsize`, `vm_stat` |
| GPU | `system_profiler SPDisplaysDataType` |
| 디스크 | `df -H /`, `diskutil info /` |
| 배터리 | `ioreg -r -c AppleSmartBattery` |
| 자동 정리 | `-json` 출력을 plutil 로 파싱 → `mac-spec.sh` 가 MD 표 생성 |
| 게시 전 | 시리얼·UUID·컴퓨터 이름 제거 |
| 버전 | macOS 27 부터 Apple Silicon 전용 |

**사양은 스크립트로 같은 형식 표를 뽑고, 게시 전 식별 정보만 지우면 끝임**
