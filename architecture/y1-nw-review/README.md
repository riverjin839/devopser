## y1-nw-review

Y1 AI DATAPLATFORM 네트워크 고도화 검토 요청 (서버 배치 · Switch N/W · K8s Cilium N/W). 서버 인프라 · 고객 · N/W 인프라 담당 검토용.

| 파일 | 내용 |
|---|---|
| [y1-nw-review-request.md](./y1-nw-review-request.md) | 검토 요청서 : 서버 인프라(DC 구간 분리 · 랙 균등, 최우선) · Switch(S01 ~ S17) · Cilium(C01 ~ C14) · 장애 시나리오 · 담당별 회신 양식 · 검증 계획 |
| `y1-nw-review-diagrams.drawio` | 전통 N/W 다이어그램 (Cisco 아이콘) 5페이지 : N-0 ~ N-4 |
| `y1-cilium-node-diagrams.drawio` | Cilium 문서 스타일 노드 다이어그램 3페이지 : C-1 ~ C-3 |
| `drawio/` | 페이지별 단독 draw.io |
| `images/` | 목업 PNG (draw.io 렌더링) |
| `tools/` | 다이어그램 생성기 (`nwdiag.py` · `ciliumstyle.py`) |

| 그림 | 내용 |
|---|---|
| N-0 | DC 구간 역할 분리 · Storage 랙 실장도 (랙당 같은 수) |
| N-1 | 전체 토폴로지 (FA Core · Super Spine · 구간 Spine · Leaf 쌍 · 노드) |
| N-2 | 랙 · 노드 연결 (bond0 PUBLIC · bond1 PRIVATE · Cilium BGP 인스턴스) |
| N-3 | eBGP only · EVPN 제어 구조 (계층별 ASN · leaf 별 고유 RD) |
| N-4 | 트래픽 경로 (외부 S3 · 내부 Global Service · ClusterMesh) |
| C-1 | Storage 노드 내부 (Pod · netkit · eBPF · Routing Table · cilium agent) |
| C-2 | 외부 요청 노드 처리 (eTP Local) |
| C-3 | 내부 client → AIStor (소켓 LB · bond1 · NAT 없음) |

- 그림(draw.io)에는 구조 · 짧은 라벨만, 설명 · 범례는 검토 요청서의 각 그림 아래
- IP 는 예시값, ASN 은 `<SS>` · `<SP-n>` · `<LF-n>` · `<CL-n>` 표기
- 목업 PNG 의 Cisco 아이콘은 근사 모양 (draw.io 에서는 실제 Cisco 아이콘)
- 재생성 : `cd tools && python3 nwdiag.py && python3 ciliumstyle.py`
