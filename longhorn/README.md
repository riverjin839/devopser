## Longhorn

| 파일 | 내용 |
|---|---|
| [longhorn-architecture-guide.md](./longhorn-architecture-guide.md) | 향후 Longhorn 구성 표준 — 구성안(로컬 NVMe / VM 디스크 / SAN) 선택, 노드 사양·커널·OS, 디스크 등록 규칙(UUID / by-id), 하이퍼바이저·V2·multipath·Longhorn 설정, 운영 절차, 현 환경 전환 체크리스트 |
| [longhorn-vm-spdk-evidence.md](./longhorn-vm-spdk-evidence.md) | V2(SPDK)·VM·SAN 이슈 판단 근거 — 공식 문서 링크와 원문 구문 발췌(E1~E11), 근거 없이 판단한 부분의 검증 방법 |
| [longhorn-device-name-troubleshooting.md](./longhorn-device-name-troubleshooting.md) | 노드 VM 재부팅 후 디바이스명 변경(/dev/sda → /dev/sdb) 원인·진단 명령어·조치(fstab UUID화, diskUUID mismatch, V2 block disk, multipath, 하이퍼바이저 serial)·재발 방지 체크리스트 |
| [longhorn-v2-hang-incident-response.md](./longhorn-v2-hang-incident-response.md) | V2(SPDK) 노드 행 장애 대응 — 확인 사실·가설 상태, I/O 경로·장애 전파 다이어그램, 코드로 확인한 NVMe timeout(keep-alive 5s 등)·#13913, 판별 지표, 온라인 완화 조치, Jenkins 이전(local-path / master hostPath)·Longhorn 중지 런북, 재개 조건 |
