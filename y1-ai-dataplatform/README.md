## y1-ai-dataplatform

Y1 AI DATAPLATFORM 인프라 아키텍처 설계 제안 (Compute K8s · GPU · Storage(AIStor) K8s, Cilium BGP native routing · N9K VXLAN EVPN).

### 문서

| 파일 | 내용 |
|---|---|
| [y1-ai-dataplatform-proposal-summary.md](./y1-ai-dataplatform-proposal-summary.md) | 요약 제안서 (10분) |
| [y1-ai-dataplatform-proposal-detail.md](./y1-ai-dataplatform-proposal-detail.md) | 상세 제안서 (명령어 제외) |
| [y1-ai-dataplatform-proposal-detail-cmd.md](./y1-ai-dataplatform-proposal-detail-cmd.md) | 상세 제안서 (적용 · 검증 명령 포함) |
| [y1-ai-dataplatform-tech-learning.md](./y1-ai-dataplatform-tech-learning.md) | 개선 기술 학습 문서 (원리 · 근거 · 검증 명령) |

### 그림

| 경로 | 내용 |
|---|---|
| `figures/` | 그림 23종 SVG (문서 본문에서 참조) |
| `preview/` · `preview-contact-sheet.png` | PNG 목업 |
| `drawio/` · `y1-ai-dataplatform-all-figures.drawio` | draw.io 원본 (단독 23개 · 통합본) |
| `drawio-gliffy/` · `y1-ai-dataplatform-all-figures-gliffy.drawio` | Confluence Gliffy 가져오기용 (cube 회전 속성 제거) |

### 도구

| 파일 | 내용 |
|---|---|
| `tools/gen_v3.py` · `gen_v2.py` · `figlib2.py` | 그림 생성기 (draw.io · SVG 동시 생성). `cd tools && USE_KEY=1 python3 gen_v3.py` |
| `tools/ilake-node-check.sh` | K8s 노드 점검 스크립트 (`sudo bash ilake-node-check.sh`) |

- 운영 환경 식별값(클러스터 이름 · ASN 등)은 일반 표기(`cluster-name`, `ASN-A` 등)로 바꿔 둠
- PNG 목업 재생성 : `for f in figures/*.svg; do rsvg-convert -b white -o preview/$(basename $f .svg).png $f; done`
