## n9k-ecmp

Cisco N9K 사용법과 ECMP 동작을 K8s(Cilium BGP) 기준으로 정리한 스터디 문서.

| 파일 | 내용 |
|---|---|
| [n9k-ecmp-k8s.md](./n9k-ecmp-k8s.md) | 블로그용 MD (N9K 기본 명령, ECMP 해시, Cilium BGP v2 리소스, 노드 장애 재해시) |
| [diagrams/specs.py](./diagrams/specs.py) | Archify 다이어그램 4종 스펙 (Autumn leaves 테마) |
| diagrams/n9k-ecmp-*.html | 빌드 결과 (overview, hash-flow, cilium-config, node-failure) |

- 다이어그램 HTML 4종은 `diagrams/` 에 있음 (Archify 동적, Autumn leaves 테마). MD 의 `<!-- diagram: n9k-*.html -->` 마커 자리에 임베드됨
- NX-OS 설정 예시는 개념 코드임. 장비·버전에서 검증 후 적용
