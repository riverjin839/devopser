# Longhorn 구성 가이드 (향후 표준)

- 작성일: 2026-11-19
- 배경: 노드 VM 재부팅 후 디바이스명 변경(`/dev/sdX`) 이슈, VM 1번 워커의 nvme 에러, SAN(SSD + NVMe 캐시) 디스크 위의 Longhorn 운영
- 근거: [longhorn-vm-spdk-evidence.md](./longhorn-vm-spdk-evidence.md)의 E1~E11 (본문에 `[E번호]`로 표기). 표기가 없는 항목은 운영 판단이다.

---

## 1. 핵심 원칙

1. **Longhorn은 "노드 로컬 디스크 + 노드 간 복제" 구조다.** 디스크는 노드에 전용으로 붙은 저지연 SSD/NVMe여야 한다 [E10].
2. **지연(latency)이 안정성을 결정한다** [E10]. 지연이 튀는 공유 스토리지(SAN) 위에 올리면 replica timeout → rebuild 폭주 → 부하 증가의 악순환이 생긴다.
3. **디바이스는 이름(`/dev/sdX`)이 아니라 영구 식별자로 참조한다.** 파일시스템 디스크는 UUID, raw block 디스크는 by-id [E6].
4. **데이터 엔진은 클러스터당 하나** [E8]. V2(SPDK)는 조건이 맞는 노드에서만 쓴다.

## 2. 구성안 선택

| 구성안 | 디스크 | 엔진 | 권장도 | 비고 |
|---|---|---|---|---|
| **A. 표준** | 노드 로컬 NVMe (베어메탈, 또는 VM에 NVMe **PCI passthrough**) | V2 (조건 충족 시) / V1 | ✅ 권장 | V2 성능 이점을 실제로 얻는 유일한 구성 [E3, E4] |
| **B. 과도기** | VM 가상 디스크(로컬 SSD 데이터스토어) | **V1** | △ | V2를 써도 AIO 경로라 이점이 작다 [E3] |
| **C. 현행** | VM 가상 디스크 ← SAN(SSD + NVMe 캐시) | V1만 | ⚠️ 비권장 | 장애 도메인 공유, 쓰기 증폭, 지연 스파이크. 유지해야 한다면 4.6 조건 적용 |

> SAN을 계속 써야 하는 워크로드라면 Longhorn을 거치지 말고 **SAN 벤더 CSI 드라이버로 PV를 직접 제공**하는 것이 구조적으로 더 맞다(복제는 SAN이 담당).

**결정 순서:** 로컬 NVMe 확보 가능? → 예: A / 아니오: 로컬 SSD 데이터스토어 가능? → 예: B(V1) / 아니오: C(V1) + SAN CSI 병행 검토.

## 3. 노드 사양

| 항목 | V1 | V2 추가 요구 |
|---|---|---|
| 노드 수 | 3 이상 | 동일 |
| CPU | 4 vCPU 이상 | **+1 코어 전용**(spdk_tgt 100% 폴링) [E5] |
| 메모리 | 4 GiB 이상 | **+2 GiB hugepage**(2 MiB × 1024) [E5, E9] |
| 디스크 | 전용 SSD/NVMe, 루트 디스크 금지 [E10] | **로컬 NVMe 강력 권장** [E4] |
| 커널 | 배포판 지원 최신 | **6.7 이상 필수 운영 기준** [E1, E2] (5.15는 IO 에러 시 재부팅 위험) |
| 커널 모듈 | iscsi_tcp | `vfio_pci`, `uio_pci_generic`, `nvme-tcp` [E9] |
| Longhorn 버전 | 최신 안정판 | **v1.12.0 이상**(V2 GA) [E8] |

**OS 선택 참고 (커널 6.7 이상 기준)** — 기본 커널 기준이며 도입 전 `uname -r`로 재확인한다.

| OS | 기본 커널 | V2 적합 |
|---|---|---|
| Ubuntu 24.04 LTS | 6.8 | ✅ |
| RHEL/Rocky 10 | 6.12 | ✅ |
| RHEL/Rocky 9 | 5.14(백포트) | ❌ 버전 기준 미달 → V1 사용 |
| Ubuntu 22.04 GA | 5.15 | ❌ (HWE 커널 6.x로 올리면 검토 가능) |

## 4. 상세 구성

### 4.1 디스크 등록 규칙

**V1 (파일시스템 디스크)**

```bash
mkfs.ext4 /dev/disk/by-id/<데이터디스크>     # 또는 xfs
blkid /dev/disk/by-id/<데이터디스크>          # UUID 확인
```

```
# /etc/fstab — 반드시 UUID
UUID=<uuid>  /var/lib/longhorn  ext4  defaults,nofail,x-systemd.device-timeout=30s  0 2
```

- 추가 디스크를 심볼릭 링크로 연결하지 않는다. `mount --bind` + fstab [E10].
- 전용 디스크라면 `Storage Minimal Available Percentage`를 10%까지 낮출 수 있다.

**V2 (block-type 디스크)**

- raw 디바이스라 파일시스템 UUID가 없다 → **`/dev/disk/by-id/...` 경로로 등록**한다. `/dev/sdX` 등록 금지 [E6].
- 추가 전 `wipefs -a` 필수 (v1.11부터 기존 FS/파티션이 있으면 추가 거부) [E7].
- 크기가 4096의 배수가 아니면 파티션으로 맞춘다 [E7].
- NVMe 드라이버로 쓰려면 IOMMU 그룹이 격리돼야 한다. 아니면 AIO 모드 [E3].

```bash
ls -l /dev/disk/by-id/ | grep -v part
find /sys/kernel/iommu_groups/ -type l | sort -V     # NVMe가 브리지와 같은 그룹인지 확인
```

### 4.2 하이퍼바이저 (노드가 VM인 경우)

| 항목 | 설정 |
|---|---|
| 디스크 식별자 노출 | VMware `disk.EnableUUID=TRUE` / Proxmox `serial=` / libvirt `<serial>` — by-id가 생성되도록 |
| 로컬 NVMe 제공 | 가능하면 **PCI passthrough**(구성안 A) |
| CPU | Longhorn 노드 VM은 **CPU reservation / 오버커밋 금지**. V2면 spdk_tgt 코어 고정 [E5] |
| 메모리 | reservation(hugepage가 swap·balloon 대상이 되지 않게) |
| 컨트롤러 | 디스크 컨트롤러 종류 통일 |
| 배치 | Longhorn 노드 VM을 **서로 다른 물리 호스트**에 anti-affinity로 분산 |

### 4.3 V2 노드 준비

```bash
cat <<'EOF' > /etc/modules-load.d/longhorn-v2.conf
vfio_pci
uio_pci_generic
nvme-tcp
EOF
modprobe vfio_pci uio_pci_generic nvme-tcp

echo "vm.nr_hugepages=1024" >> /etc/sysctl.d/90-longhorn-v2.conf && sysctl --system
grep Huge /proc/meminfo
systemctl restart kubelet     # hugepages-2Mi 리소스 반영
```

- V2를 쓰지 않을 노드에는 `node.longhorn.io/disable-v2-data-engine` 레이블.
- CPU 마스크(`data-engine-cpu-mask`)를 CPU-pinned 워크로드와 겹치지 않게 지정.

### 4.4 multipath

- multipath를 쓰지 않으면 `multipathd`를 비활성화한다.
- 쓰지 않는다면 Longhorn KB대로 블랙리스트 [E11]:

```
blacklist {
    devnode "^sd[a-z0-9]+"
}
```

- ⚠️ **SAN을 multipath로 붙인 노드**는 위 설정이 SAN 경로까지 막는다. 이 경우 Longhorn 디바이스만 제외한다:

```
# Longhorn(v1) iSCSI 디바이스의 vendor/product를 먼저 확인
#   udevadm info -q property -n /dev/sdX | grep -E "ID_VENDOR|ID_MODEL"
blacklist {
    device {
        vendor  "<확인한 Longhorn vendor>"
        product "<확인한 Longhorn product>"
    }
}
```

### 4.5 Longhorn 설정

| 설정 | 권장값 |
|---|---|
| 데이터 엔진 | 클러스터당 하나 [E8] |
| Default Replica Count | 3 (구성안 C에서는 4.6 참고) |
| Replica Node Level Soft Anti-Affinity | false (같은 노드에 replica 금지) |
| Data Locality | best-effort |
| Guaranteed Instance Manager CPU | 설정(노드 CPU의 일정 비율 예약) |
| Backup Target | 외부(NFS/S3) 필수 — 복제는 백업이 아니다 |
| Concurrent Replica Rebuild Per Node Limit | 낮게(예: 2) — rebuild 폭주로 인한 지연 확산 방지 |

### 4.6 구성안 C(SAN 위)를 유지해야 할 때의 최소 조건

1. **V1 엔진만** 사용 (V2는 AIO 경로 + CPU 스로틀 + nvme-tcp timeout 위험 [E1, E3, E5]).
2. 노드별 디스크를 **가능하면 서로 다른 RAID 그룹 / 컨트롤러 / 풀의 LUN**으로 분리한다.
3. SAN이 이미 RAID로 보호되므로 replica 수를 2로 낮추는 것을 검토(용량·쓰기 증폭 감소). 단, 노드 장애 내성은 줄어든다.
4. SAN 캐시 상태(write-back 유지, 배터리/미러링)와 LUN 지연을 모니터링하고 Longhorn 알람과 같은 시간축으로 본다.

## 5. 운영 절차

**재부팅/유지보수**

1. `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data`
2. Longhorn UI → 노드 **Scheduling Disable**, 볼륨이 모두 Healthy인지 확인
3. 재부팅
4. 디스크 Ready 확인: `kubectl -n longhorn-system get nodes.longhorn.io <node> -o yaml`
5. Scheduling Enable → `kubectl uncordon`

**업그레이드**

- Longhorn: 지원 경로대로 한 단계씩. V2는 v1.13부터 instance-manager live upgrade 지원.
- 커널: V2 노드는 6.7 미만으로 내려가지 않게 커널 버전을 고정·관리.

**모니터링 항목**

| 대상 | 지표/로그 |
|---|---|
| 노드 | `dmesg`의 nvme timeout / reset / reconnect, `iscsi`, `I/O error` 알람 |
| Longhorn | volume robustness(Degraded/Faulted), replica rebuild 수, disk Ready |
| 하이퍼바이저 | VM 디스크 latency, CPU Ready/steal |
| SAN | 캐시 상태, LUN latency |

## 6. 현 환경 전환 체크리스트

- [ ] VM 1번 nvme 에러 출처 확인 (`nvme list -v` — tcp면 Longhorn V2, pcie면 가상 NVMe)
- [ ] 전 노드 `uname -r`, Longhorn 버전, 볼륨별 `spec.dataEngine` 수집
- [ ] V2 볼륨이 있고 커널 < 6.7 이면: V1로 이전(백업 → V1 StorageClass로 복원) 또는 커널 업그레이드
- [ ] block-type 디스크 경로가 `/dev/sdX`면 by-id로 재등록 (replica eviction → 삭제 → 재추가) [E6]
- [ ] fstab 전부 UUID화 (완료 — [디바이스명 변경 가이드](./longhorn-device-name-troubleshooting.md))
- [ ] 하이퍼바이저: disk.EnableUUID/serial, CPU·메모리 reservation, 노드 VM anti-affinity
- [ ] multipath 정책 결정 (SAN multipath 사용 여부에 따라 4.4)
- [ ] 중장기: 로컬 NVMe 노드(구성안 A) 확보 또는 SAN 워크로드는 SAN CSI로 분리
