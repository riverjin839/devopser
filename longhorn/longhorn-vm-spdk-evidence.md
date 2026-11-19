# Longhorn V2(SPDK) · VM · SAN 환경 이슈 — 근거 문서 및 원문 발췌

- 작성일: 2026-11-19
- 목적: "VM 1번(Longhorn 워커) nvme 에러, SAN(SSD + NVMe 캐시) 디스크, V2(SPDK) VM 호환성" 검토에서 근거로 삼은 공식 문서의 **링크와 원문 구문**을 남긴다.
- 표기: `> 원문`은 해당 페이지의 영어 원문을 그대로 옮긴 것이다(Longhorn 문서는 CC-BY-4.0). 아래 `→`는 우리 환경에 대한 해석이다.
- 화면 캡처가 필요하면 각 링크에서 인용 구문을 검색(Ctrl+F)해 캡처한다. 버전별 문서는 내용이 바뀔 수 있으니 링크의 버전 번호를 함께 기록한다.

---

## E1. 커널 6.7 미만: nvme-tcp ↔ SPDK IO timeout으로 커널 패닉

- 링크: https://longhorn.io/docs/1.7.1/v2-data-engine/prerequisites (SUSE 미러: https://documentation.suse.com/cloudnative/storage/1.9/en/longhorn-system/v2-data-engine/prerequisites.html)

> In Longhorn environments the kernel panic can be caused by prevalent IO timeouts in communications between the nvme-tcp driver and SPDK. Update the Linux kernel on Longhorn nodes to version 6.7 or later to prevent the issue from occurring.

→ VM에서 보이는 `nvme ... timeout / reconnect` 에러가 Longhorn V2 볼륨(nvme-tcp)에서 난 것이라면, 커널 버전에 따라 패닉·재부팅까지 이어질 수 있다. **V2 노드 커널은 6.7 이상이어야 한다.**

## E2. 커널 5.15: IO 에러 시 예기치 않은 재부팅 / 6.7 미만: 메모리 손상

- 링크: https://longhorn.io/docs/1.11.0/v2-data-engine/prerequisites/

> Host machines with Linux kernel 5.15 may unexpectedly reboot when volume-related IO errors occur. Update the Linux kernel on Longhorn nodes to version 5.19 or later to prevent such issues.

> v6.7 or later is recommended for improved system stability

> Memory corruption may occur on hosts using versions of the Linux kernel earlier than 6.7, as highlighted by this SPDK upstream issue: https://github.com/spdk/spdk/issues/3116#issuecomment-1890984674.

→ 앞서 있었던 "재부팅 후 디바이스명 변경" 이슈의 재부팅 자체가 IO 에러로 인한 것일 가능성도 점검해야 한다(`journalctl -b -1`, `last -x`).

## E3. NVMe 직접 사용(vfio-pci)에는 IOMMU 그룹 격리 필요, 아니면 AIO 모드

- 링크: https://longhorn.io/docs/1.11.0/v2-data-engine/prerequisites/

> For the V2 Data Engine (SPDK) to claim a disk, the NVMe device must be isolatable. Because SPDK uses vfio-pci, the following hardware constraints apply:

- 링크: https://longhorn.io/docs/latest/best-practices/

> If the device shares an IOMMU group with a PCIe bridge, it cannot be used with the SPDK NVMe driver and must be used in AIO mode instead.

→ VM에 SAN LUN을 가상 디스크로 붙인 구조에서는 SPDK가 NVMe 드라이버로 디스크를 직접 잡을 수 없고 **AIO 경로**가 된다. 즉 SPDK의 성능 이점(커널 우회, zero-copy)은 거의 얻지 못한다.

## E4. V2에는 로컬 NVMe 디스크 강력 권장

- 링크: https://longhorn.io/docs/1.11.3/v2-data-engine/prerequisites/

> Because of this, using local NVMe disks is highly recommended for enabling V2 volumes to achieve optimal storage performance.

- 링크: https://longhorn.io/docs/1.12.1/best-practices/

> Local NVMe SSDs are strongly recommended for V2 volumes to achieve optimal storage performance

> Linux kernel 6.7 or later for NVMe/TCP support and be…  *(검색 결과 스니펫이 여기서 잘림 — 원문 페이지에서 확인)*

## E5. spdk_tgt는 전용 CPU 코어 100% 폴링 — VM CPU 스로틀 시 IO 멈춤

- 링크: https://longhorn.io/docs/1.12.1/best-practices/

> Additional 1 CPU core per node dedicated to each V2 instance-manager pod (the spdk_tgt process uses intensive polling and consumes 100% of a dedicated CPU core)

> Additional 2 GiB memory per node reserved for huge pages (1024 × 2 MiB-sized pages)

- 링크: https://documentation.suse.com/external-tree/en-us/cloudnative/storage/latest/en/troubleshooting-maintenance/v2-data-engine-issues.html (섹션: *V2 Data Engine I/O Operations May Get Stuck on Burstable VMs*)

> When using the V2 Data Engine on burstable virtual machines (such as AWS EC2 T-series), I/O operations may time out or become stuck, especially during heavy workloads such as concurrent volume backups or restores.

> This issue is typically caused by the node exhausting its allocated CPU credits. The V2 Data Engine relies on the SPDK target daemon (spdk_tgt), which requires a dedicated CPU core and uses intensive polling. When a burstable VM runs out of CPU credits, the cloud provider's hypervisor severely throttles the CPU. This can cause the V2 data plane to become unresponsive, resulting in I/O timeouts or stuck operations.

→ 문서 사례는 클라우드 burstable VM이지만, 온프렘 하이퍼바이저에서 vCPU 오버커밋으로 **CPU Ready/steal이 높으면 같은 메커니즘**으로 IO timeout이 날 수 있다(우리 판단 — 하이퍼바이저 지표로 검증 필요).

## E6. `/dev/sd*` 경로로 추가한 AIO 디스크의 V2 볼륨은 업그레이드 후 복구 불가

- 링크: https://documentation.suse.com/external-tree/en-us/cloudnative/virtualization/v1.6/en/storage/longhorn-v2-data-engine.html

> If you are using the SPDK AIO bdev driver (specifically, if disks were added using /dev/sd* device paths), V2 volumes created before the upgrade become unusable and cannot be recovered after the upgrade. For more information, see issue #10461.

→ 디바이스명 변경 이슈와 직결. **block-type 디스크는 `/dev/sdX`가 아닌 `/dev/disk/by-id/...`로 등록**해야 한다.

## E7. block-type 디스크 크기는 4096의 배수 / 깨끗한 디스크만 추가 가능

- 링크: https://documentation.suse.com/en-us/cloudnative/storage/1.11/en/troubleshooting-maintenance/v2-data-engine-issues.html

> 2. Partition the block-type disk using the fdisk utility and ensure that the partition size is a multiple of the block size 4096.
> 3. Add the partitioned disk to the Longhorn node.

- 링크: https://longhorn.io/docs/latest/best-practices/

> Ensure disk is clean before adding: Starting with v1.11.0, Longhorn prevents adding block disks that contain an existing file system or partition table. Run wipefs -a /path/to/block/device before adding a disk.

## E8. V2 GA는 v1.12.0 / 클러스터당 엔진 하나 권장

- 링크: https://longhorn.io/docs/1.13.0/important-notes/

> The V2 Data Engine became generally available in Longhorn v1.12.0.

- 링크: https://longhorn.io/docs/1.12.1/best-practices/

> Important: We recommend enabling only one data engine (V1 or V2) per cluster.

→ v1.12 미만에서 V2를 쓰고 있다면 실험 기능을 운영에 쓰는 상태다.

## E9. 필요 커널 모듈 / hugepage

- 링크: https://documentation.suse.com/en-us/cloudnative/storage/1.9/en/longhorn-system/v2-data-engine/prerequisites.html

> Linux kernel modules: vfio_pci, uio_pci_generic, nvme-tcp — Huge page support: 2 GiB of 2 MiB-sized pages  *(목록 형식을 한 줄로 옮김)*

- 링크: https://documentation.suse.com/cloudnative/storage/1.11/en/longhorn-system/v2-data-engine/prerequisites.html

> Specifically, 1024 pages (equivalent to a total of 2 GiB) must be available on each Longhorn node.

## E10. 일반(V1 포함) 구성 권장: 전용 디스크, SSD/NVMe, 지연(latency)이 핵심

- 링크: https://longhorn.io/docs/1.6.0/best-practices

> It's recommended to dedicate a disk for Longhorn storage for production, instead of using the root disk

> Warning: While Longhorn can function with HDDs (spinning disks) as storage, it is important to understand that latency plays a much more important role in volume stability than IOPS or throughput.

- 링크: https://longhorn.io/docs/1.7.2/best-practices

> Latency, not just throughput, is the most important factor in ensuring system stability.

- 링크: https://longhorn.io/docs/1.12.1/best-practices/

> SSD/NVMe or similar performance block device on the node for storage (recommended)

- 링크: https://longhorn.io/docs/latest/best-practices/

> Don't use a symbolic link for the extra disks. Use mount --bind instead of ln -s and make sure it's in the fstab file.

→ SAN 캐시 flush·destage나 다른 VM 부하로 **지연이 튀는 구조는 Longhorn 볼륨 안정성에 직접 불리**하다.

## E11. multipathd가 Longhorn 디바이스를 가로채는 문제

- 링크: https://longhorn.io/kb/troubleshooting-volume-with-multipath/

> This is caused by multipath creating a multipath device for any eligible device path including every Longhorn volume device not explicitly blacklisted.

> Notice that Longhorn device names start with /dev/sd[x]

```
blacklist {
    devnode "^sd[a-z0-9]+"
}
```

→ ⚠️ **SAN을 multipath로 붙이고 있다면 이 블랙리스트를 그대로 넣으면 SAN 경로까지 빠진다.** 이 경우 SAN LUN을 `blacklist_exceptions { wwid ... }`로 예외 처리하거나, Longhorn 디바이스만 vendor/product로 블랙리스트한다(구성 가이드 4.4 참고).

---

## 근거 없이 판단한 부분 (검증 필요)

| 항목 | 판단 | 검증 방법 |
|---|---|---|
| VM의 nvme 에러 출처 | SAN 내부 NVMe 캐시는 게스트에 보이지 않으므로 ① Longhorn V2 nvme-tcp ② 가상 NVMe 컨트롤러 ③ NVMe-oF SAN 중 하나 | `nvme list -v`, `/sys/class/nvme/nvme*/transport`, `subsysnqn` |
| SAN 위 Longhorn 복제 | 모든 replica가 같은 SAN이면 장애 도메인이 같고, 쓰기 증폭만 생긴다 | SAN LUN·RAID 그룹 매핑 확인 |
| 온프렘 CPU 오버커밋 | E5와 같은 IO 멈춤 유발 가능 | 하이퍼바이저 CPU Ready / steal(`top`의 `st`) |
