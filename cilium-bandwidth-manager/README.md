## cilium-bandwidth-manager

Cilium 1.18.4 Bandwidth Manager 적용과 ETL Job 파드 대역폭 제어 문서 모음.

| 파일 | 내용 |
|---|---|
| [cilium-bandwidth-manager-work-plan.md](./cilium-bandwidth-manager-work-plan.md) | I 지역 Target 클러스터 적용 작업 계획서 (사전 확인, 단계별 일정, D-day 절차, 영향도, 검증 기준, 롤백, R&R, 리스크) |
| [cilium-bandwidth-manager-etl-guide.md](./cilium-bandwidth-manager-etl-guide.md) | Bandwidth Manager 활성화, ETL Job·CronJob·Spark·Airflow 어노테이션 적용, 검증·모니터링, 트러블슈팅 가이드 |
| [cilium-bandwidth-manager.drawio](./cilium-bandwidth-manager.drawio) | 구조 흐름도(설정 경로 → BPF 맵 → egress EDT / ingress 토큰 버킷), 적용 절차 흐름도 (2페이지) |
| [i-region-etl-bandwidth.drawio](./i-region-etl-bandwidth.drawio) | I 지역 Target 클러스터 ETL 흐름(W 지역 SRC → Airflow · Spark · StarRocks → AIStor), 구간 10G 중 ETL 1G 대역폭 제어 적용 지점 (2페이지) |
