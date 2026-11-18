# Longhorn 노드 VM — 재부팅 후 디바이스명 변경(/dev/sda → /dev/sdb) 트러블슈팅

## 1. 원인

`/dev/sdX` 이름은 **영구적이지 않다**. 커널이 부팅 시 디스크를 인식한 순서대로 붙이는 이름이라 재부팅마다 바뀔 수 있다. Longhorn 노드에서 특히 잘 바뀌는 이유:

- **Longhorn 볼륨도 `/dev/sdX`로 잡힌다** — v1 엔진은 볼륨을 iSCSI로 호스트에 붙인다. 부팅 시 iSCSI 세션이 로컬 디스크보다 먼저/사이에 붙으면 순서가 섞인다.
- **하이퍼바이저 디스크 순서** — 디스크 추가·제거, 컨트롤러 혼재(virtio-scsi / SATA / PVSCSI), 핫플러그.
- **multipathd가 Longhorn iSCSI 디바이스를 가로챔** — Longhorn의 대표적인 알려진 이슈.

## 2. 진단 명령어 (노드에서)

```bash
# 1) 디스크를 이름이 아닌 실제 식별자로 보기 (TRAN=iscsi 이면 Longhorn 볼륨)
lsblk -o NAME,SIZE,TYPE,FSTYPE,UUID,SERIAL,WWN,TRAN,MOUNTPOINT

# 2) 영구 경로 확인
ls -l /dev/disk/by-id/ /dev/disk/by-uuid/ /dev/disk/by-path/

# 3) 마운트 설정이 /dev/sdX로 박혀 있는지 ← 가장 흔한 원인
cat /etc/fstab
findmnt /var/lib/longhorn        # Longhorn 디스크 경로 (기본값 또는 지정 경로)

# 4) Longhorn iSCSI 세션 / SCSI 매핑
iscsiadm -m session -P 3 | grep -E "Target|Attached scsi disk"
lsscsi -t

# 5) multipath가 sd 디바이스를 잡고 있는지
multipath -ll

# 6) 부팅 시 인식 순서
dmesg | grep -iE "sd[a-z]|scsi"
```

Longhorn 쪽 확인:

```bash
kubectl -n longhorn-system get nodes.longhorn.io <node> -o yaml   # status.diskStatus conditions
cat <디스크경로>/longhorn-disk.cfg                                 # diskUUID
kubectl -n longhorn-system logs -l app=longhorn-manager --tail=200 | grep -i disk
```

| 증상 | 의미 |
|---|---|
| 디스크 `Ready=False`, `diskUUID mismatch` | 해당 경로에 **다른 디스크**가 마운트됨 |
| 디스크 경로가 루트 FS에 그대로 있음 (용량 = OS 디스크) | 데이터 디스크 마운트 실패 → 빈 디렉터리에 쓰는 중 |
| `multipath -ll`에 Longhorn 볼륨이 보임 | multipath 충돌 (아래 D) |

## 3. 조치

> ⚠️ **먼저**: Longhorn UI에서 해당 노드 **Scheduling Disable**. 그 노드의 볼륨들이 다른 노드에 정상 replica를 갖고 있는지 확인. replica가 이 노드에만 있다면 디스크를 마운트/해제하기 전에 백업부터 받는다.

### A. fstab을 UUID 기반으로 교체 (핵심)

```bash
blkid /dev/sdX          # 데이터 디스크 UUID 확인
```

```
# /etc/fstab
UUID=xxxx-xxxx  /var/lib/longhorn  ext4  defaults,nofail,x-systemd.device-timeout=30s  0 2
```

`nofail`은 디스크가 없어도 부팅이 멈추지 않게 한다. 단, 그 경우 Longhorn이 빈 디렉터리를 쓰게 될 수 있으니 2번 표의 증상을 함께 점검한다.

### B. 잘못된 디스크가 마운트된 경우

1. `umount` 후 올바른 디스크(UUID로 찾은 것)를 다시 마운트한다.
2. `longhorn-disk.cfg`의 diskUUID가 Longhorn 노드 CR 값과 같은지 확인한다.
3. 해당 노드의 `longhorn-manager` 파드를 재시작한다.
4. 디스크 Ready 복귀와 replica 재연결을 확인한다.

### C. V2 데이터 엔진(block 타입 디스크)을 쓰는 경우

디스크 경로가 `/dev/sdb`처럼 지정되어 있다면 매우 위험하다. `/dev/disk/by-id/...`로 바꿔야 하며, 경로는 직접 변경할 수 없으므로:

1. 해당 디스크의 replica eviction
2. 디스크 삭제
3. by-id 경로로 디스크 재추가

### D. multipath 충돌

`/etc/multipath.conf`에 추가 후 `systemctl restart multipathd` (multipath를 실제로 쓰지 않으면 서비스를 꺼도 된다):

```
blacklist {
    devnode "^sd[a-z0-9]+"
}
```

### E. 하이퍼바이저에서 디스크 식별자 고정

| 플랫폼 | 설정 |
|---|---|
| VMware | VM 옵션 `disk.EnableUUID = TRUE` (없으면 `/dev/disk/by-id`가 비어 있는 경우가 많음) |
| Proxmox | 디스크 옵션 `serial=` 지정 |
| libvirt/KVM | 디스크 정의에 `<serial>` 지정 |

디스크 컨트롤러 종류는 하나로 통일하는 것이 좋다.

### F. 그 밖에 하드코딩된 곳 점검

```bash
grep -rn "/dev/sd" /etc/ /usr/local/bin/ 2>/dev/null
```

udev 규칙, 백업 스크립트, LVM 필터, Longhorn 노드 CR의 디스크 경로에 `/dev/sdX`가 없는지 확인한다.

## 4. 재발 방지 체크리스트

- [ ] fstab · LVM · 스크립트에 `/dev/sdX` 직접 참조 없음 (UUID / by-id만 사용)
- [ ] 하이퍼바이저에서 디스크 serial/UUID 노출
- [ ] multipath 블랙리스트 적용
- [ ] 재부팅 절차: drain → Longhorn 스케줄링 비활성화 → 재부팅 → 디스크 Ready 확인 → 스케줄링 재활성화
