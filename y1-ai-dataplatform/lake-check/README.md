## lake-check

Y1 제안서 항목 기준으로 현재 Lake(I Lake) 상태를 점검하는 도구. 노드 하나에서 실행하면 노드 · 클러스터 값을 모아 판정 · 해석이 붙은 레포트를 만든다.

| 파일 | 내용 |
|---|---|
| `lake_check.py` | 일괄 점검 → 레포트 (`.md` · `.csv` · `.json`). Python 3.6+ 표준 라이브러리만 사용 |
| `lake-check-sheet.xlsx` | 점검 시트 : 사용법 · 점검 항목(명령 · Y1 권장값 · 입력 칸) · 해석표 · 요약(수식) |
| `build_sheet.py` | `lake_check.py` 의 점검 목록으로 시트 재생성 (openpyxl) |

점검 항목은 `lake_check.py` 의 `CATALOG` 하나에만 정의. 항목을 바꾸면 `python3 build_sheet.py` 로 시트를 다시 만든다.

### 실행

```bash
sudo python3 lake_check.py --out ./report
# Storage 노드만 랙별 대수 집계
sudo python3 lake_check.py --storage-selector node-role=storage --rack-label rack
# 점검 항목 목록만
python3 lake_check.py --list
```

| 옵션 | 기본값 | 내용 |
|---|---|---|
| `--out` | `./lake-check-report` | 레포트 디렉터리 |
| `--ns` | `kube-system` | Cilium 네임스페이스 |
| `--bonds` | `bond0,bond1` | 점검할 bond |
| `--kubeconfig` | `KUBECONFIG` 또는 `/etc/kubernetes/admin.conf` | kubectl 설정 |
| `--rack-label` | `rack` | 랙 라벨 키 |
| `--storage-selector` | 없음 (전체 노드) | 랙별 대수를 셀 노드 셀렉터 |
| `--skip-cluster` · `--skip-node` | - | 클러스터 · 노드 항목 건너뜀 |

- Cilium 값 : `cilium-config` ConfigMap, `cilium-dbg status · bgp peers` (kubectl exec → crictl exec 순)
- kubectl 이 없으면 노드 항목만 수집, 나머지는 `NA`
- N9K 항목(W01 ~ W12)은 `수동` : 레포트 끝 해석표의 명령을 스위치에서 실행해 대조

### 판정

| 판정 | 뜻 |
|---|---|
| 개선 | Y1 에서 바꿀 대상 (제안서 개선 항목) |
| 확인 | 값 · 의도 확인 필요 (협의 항목) |
| 충족 | 이미 Y1 권장값 |
| 유지 | I Lake 설계 그대로 유지 (정상) |
| NA | 수집 불가 · 건너뜀 |
| 수동 | N9K 수동 확인 |

### 점검 범위 (61개)

| 영역 | ID | 예 |
|---|---|---|
| L4 LB | L01 ~ L17 | KPR · Maglev annotation · LB 모드(SNAT/DSR) · eTP Local · 소켓 LB · 맵 크기 · LB IP 풀 |
| 노드 | N01 ~ N21 | netkit · host routing · bond 모드 · LACP rate · MTU · BBR · 버퍼 · tuned · IRQ · NIC 큐 NUMA |
| 클러스터 | K01 ~ K11 | IPAM · ClusterMesh · KVStoreMesh · 랙별 노드 수 · BGP 세션 · 타이머 |
| NW (N9K) | W01 ~ W12 | RD · maximum-paths · multipath-relax · Border 경로 수 · resilient · BFD · MTU · uRPF |
