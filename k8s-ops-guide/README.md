## K8s 운영 가이드

폐쇄망 bare-metal K8s 클러스터 운영 절차 모음.

| 폴더 | 내용 |
|---|---|
| [node-drain](./node-drain) | 노드 drain 무중단 가이드 (OpenEBS · Fluent Bit · OpenSearch · StarRocks · Airflow), 서비스별 노드 중단 시 동작, 1대 · 다중 노드 배치 판단, PDB 예시, Archify 다이어그램 5종 |

### node-drain

| 파일 | 내용 |
|---|---|
| [node-drain-guide.md](./node-drain/node-drain-guide.md) | drain 이 해주는 일과 안 해주는 일, 영향 유형 4가지, 서비스별 준비 · 복귀 절차, 배치 규칙, 검증 게이트, 용어, 한 장 요약 |
| [diagrams/](./node-drain/diagrams) | Archify 동적 다이어그램 HTML 5개 (Autumn 테마) + 정의 파일 `specs.py` |

- 다이어그램은 HTML 파일이라 GitHub 에서는 소스로 보임 → 내려받아 브라우저로 열면 됨
- 본문의 `<!-- diagram: X.html -->` 는 그림 자리 표시임
