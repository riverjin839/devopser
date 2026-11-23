## ambari-study

Apache Ambari (3.0.0, trunk 2026-11 기준) 구조 정리 + PEP 적용 패턴 스터디.

- 본문 : `ambari.md` (블로그 MD, `<!-- diagram: X.html -->` 마커 = 노션 임베드 위치)
- 다이어그램 : Archify 그린 테마 단일 HTML

| 파일 | 내용 |
|---|---|
| `diagrams/amb-overview.html` | 전체 구조 (Web · API · Server · Agent · Stack · VictoriaMetrics) |
| `diagrams/amb-stack.html` | 서비스 정의 폴더 구성 |
| `diagrams/amb-command.html` | 명령 실행 흐름 (RoleGraph → Stage → Agent) |
| `diagrams/amb-alert.html` | 알람 프레임워크 |
| `diagrams/amb-recovery.html` | Agent 자가복구 루프 |
| `diagrams/amb-pep-map.html` | Ambari 패턴 → PEP 적용 매핑 |
