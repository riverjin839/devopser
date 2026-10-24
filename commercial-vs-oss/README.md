## 상용 vs 오픈소스 - Snowflake · Databricks 와 Lake 오픈소스 조합 비교 (2026)

> **목표** : 데이터·AI 플랫폼 상용 2강의 2026 기능을 파악하고, Lake 오픈소스 조합 대비 장점·단점·선택 기준 정리

- 출처 : Snowflake Summit 2026(6월), Databricks Data + AI Summit 2026(6월) 발표 정리 기사, Snowflake BUILD 2025, 업계 보도
- 기준 시점 : 2026-10. 기능명·상태(GA/프리뷰)는 계속 바뀜. 도입 검토 시 공식 문서로 재확인할 것
- 비교 대상 오픈소스 : StarRocks, Spark, Trino, Iceberg, Airflow, MLflow, Ray, vLLM, AIStor (앞 글들에서 정리한 Lake 구성)

---

## 1. 개요

**대세 맞음.** 데이터·AI 플랫폼 시장은 Snowflake 와 Databricks 2강 구도.

- 그 외 : Google BigQuery, Microsoft Fabric, AWS (Redshift·SageMaker) = 각 클라우드 자체 플랫폼
- 2026 흐름 : Databricks 성장 속도가 더 빠름. 매출 런레이트 약 $7B·80%+ 성장, 기업가치 $190B 라운드 보도 (2026-08). Snowflake 는 상장사로 시가총액 약 $83B 수준 보도 (2026-06)
- 둘 다 같은 방향으로 수렴 중 : **레이크하우스 + 오픈 테이블 포맷 + AI 에이전트**

출발점 차이

- **Snowflake** = SQL 데이터 웨어하우스에서 출발 → 오픈 포맷·AI 로 확장
- **Databricks** = Spark·ML 에서 출발 → SQL 웨어하우스·OLTP 로 확장

**둘 다 "저장·엔진·카탈로그·AI 를 한 계정 안에서" 파는 회사. Lake 는 같은 층을 오픈소스로 직접 조립한 구조임.**

---

## 2. Snowflake (2026)

<!-- diagram: mlpe-com-01-snowflake.html -->

### 2-1. 구조

- 3층 분리 : 클라우드 서비스(메타·보안·최적화) / 컴퓨트(Virtual Warehouse) / 스토리지
- 사용자는 웨어하우스 크기만 고름. 인덱스·파티션·튜닝 거의 없음
- 2026 은 "AI Data Cloud" 로 포지셔닝. 에이전트 기능 대거 추가

### 2-2. 주요 기능

| 영역 | 기능 | 내용 | 상태 (보도 기준) |
|---|---|---|---|
| 컴퓨트 | Gen2 Warehouse | 분석 성능 2배 이상 개선 표준 웨어하우스 | GA (2025) |
| 컴퓨트 | Adaptive Compute | 크기 지정 없이 자동 자원 조정 | 2026 발표 |
| 수집 | Openflow | Apache NiFi 기반 관리형 수집. BYOC 지원 | GA (2025) |
| 수집 | Datastream | Kafka 스트림을 1초 미만 지연으로 조회 | 2026 발표 |
| 오픈 포맷 | Iceberg v3 + Polaris | Iceberg 테이블 읽기·쓰기, Polaris(Iceberg REST 카탈로그) 양방향 쓰기 | GA (2026) |
| 거버넌스 | Horizon Catalog | 권한·리니지·분류. 외부 엔진 Iceberg REST 접근 | 외부 읽기 프리뷰 (2025) |
| 시맨틱 | Horizon Context | AI·BI 가 공유하는 비즈니스 의미 계층 | 2026 발표 |
| OLTP | Snowflake Postgres | Crunchy Data 인수 기반 관리형 Postgres | 프리뷰 (2025) → 운영 기능 확장 중 |
| 앱·ML | Snowpark Container Services | 컨테이너·GPU 워크로드를 Snowflake 안에서 실행 | GA |
| AI | Cortex AISQL | SQL 함수로 LLM 호출 (요약·분류·추출·PII 마스킹) | GA·프리뷰 혼재 |
| 에이전트 | CoWork (구 Snowflake Intelligence) | 업무용 에이전트. Deep Research, Artifacts | 2026 발표 |
| 에이전트 | CoCo (구 Cortex Code) | 코딩 에이전트. VS Code·Excel·Claude Code 확장 | 2026 발표 |
| 보안 | Agent Identity, AI-SPM | 에이전트별 신원·감사, AI 보안 상태 관리 | 2026 발표 |
| 개발 | dbt Projects | Snowflake 안에서 dbt 빌드·배포 | GA (2025) |

- Anthropic Claude 가 CoWork·CoCo 기반 모델. 기업용 MCP 플랫폼 Natoma 인수 의향 발표

---

## 3. Databricks (2026)

<!-- diagram: mlpe-com-02-databricks.html -->

### 3-1. 구조

- 컨트롤 플레인(Databricks 관리) + 데이터는 **고객 클라우드 스토리지**에 Delta·Iceberg 로 저장
- 중심은 Unity Catalog : 테이블·모델·에이전트·지표까지 한 곳에서 권한·리니지
- MLflow 원작자. ML·LLM 기능이 원래 강함

### 3-2. 주요 기능

| 영역 | 기능 | 내용 | 상태 (보도 기준) |
|---|---|---|---|
| 엔진 | Spark + Photon | 대량 ETL·스트리밍, 벡터화 엔진 | GA |
| SQL | Databricks SQL | 서버리스 웨어하우스. 런레이트 $1.5B 보도 | GA |
| SQL | Lakehouse//RT (Reyden 엔진) | Delta·Iceberg 위 저지연 읽기 전용 분석 | 베타 (2026) |
| 수집·파이프라인 | Lakeflow Connect · Designer · Jobs | 100+ 커넥터, 자연어 노코드 파이프라인, 서버리스 오케스트레이션 | GA (2026) |
| 스트리밍 | Spark Declarative Pipelines Real-Time Mode | 5ms 수준 연속 처리 | GA (2026) |
| 오픈 포맷 | Iceberg v3 | Delta 와 물리 파일 공유하는 관리형 Iceberg. v4 는 2026 Q4 목표 | GA (2026) |
| 거버넌스 | Unity Catalog | 권한·리니지, Metrics·Domains·Business Glossary | GA + 프리뷰 |
| AI 거버넌스 | Unity AI Gateway | 모델·에이전트 트래픽 단일 입구, 비용 한도, MCP 레지스트리 | GA (2026) |
| OLTP | Lakebase | 서버리스 Postgres. 브랜칭·스케일 투 제로·하이브리드 벡터 검색 | GA + 베타 |
| OLTP+분석 | LTAP | Postgres 쓰기 시점에 컬럼 포맷 변환 → CDC 없이 분석 | 발표 (예정) |
| ML | MLflow · Model Serving · AI Runtime | 추적·서빙·서버리스 GPU 멀티노드 학습 | GA + 프리뷰 |
| 에이전트 | Agent Bricks, Omnigent | 기업용 에이전트 플랫폼, 여러 프레임워크 통합 실행기 | GA / 오픈소스 |
| 에이전트 | Genie One · Code · ZeroOps | 업무 에이전트, 코딩 에이전트, 파이프라인 자동 진단 | GA + 프리뷰 |
| 공유 | OpenSharing (Delta Sharing 확장) | AI 자산·온프레미스 소스 공유, LF 호스팅 | 2026 발표 |

- Free Edition 확대 : 서버리스 GPU, Lakebase, Agent Bricks 까지 무료 체험 가능
- 고객 절반이 서버리스 컴퓨트 사용 보도

---

## 4. Lake 오픈소스 조합과 층별 대응

<!-- diagram: mlpe-com-03-layers.html -->

| 층 | Snowflake | Databricks | Lake 오픈소스 |
|---|---|---|---|
| 스토리지 | Snowflake 관리 (+ 외부 Iceberg 볼륨) | 고객 클라우드 S3 | AIStor (온프레미스 S3) |
| 테이블 포맷 | 내부 포맷 + Iceberg v3 | Delta + Iceberg v3 | Iceberg |
| 카탈로그 | Horizon · Polaris | Unity Catalog | HMS 또는 REST 카탈로그 (Polaris·Unity Catalog OSS 가능) |
| 수집 | Openflow, Datastream | Lakeflow Connect, Zerobus | Spark JDBC, (CDC 는 Kafka·Debezium 직접) |
| 오케스트레이션 | Tasks, dbt Projects | Lakeflow Jobs | Airflow |
| 대량 ETL | Snowpark | Spark + Photon | Spark |
| 고속 SQL·BI | Warehouse Gen2 | Databricks SQL, Lakehouse//RT | StarRocks |
| 연합 조회 | 외부 테이블 | Lakehouse Federation | Trino |
| OLTP | Snowflake Postgres | Lakebase | CNPG (PostgreSQL) |
| 벡터 검색 | Cortex Search | Vector Search, Lakebase Search | pgvector |
| ML 추적·레지스트리 | Snowpark ML, Model Registry | MLflow (관리형) | MLflow (직접 운영) |
| GPU 학습 | Container Services GPU | AI Runtime (서버리스 GPU) | Ray / Trainer on B300 |
| LLM 서빙 | Cortex (관리형 모델) | Model Serving, AI Gateway | vLLM, KServe, MLflow AI Gateway |
| 에이전트·업무 AI | CoWork, CoCo | Genie One, Agent Bricks | 직접 구축 (MCP, 사내 LLM) |
| 인증·권한 | 내장 RBAC, Agent Identity | Unity Catalog | Keycloak + K8s RBAC + 엔진별 권한 |

**층 구성은 셋 다 거의 같음. 차이는 "누가 운영하고, 층 사이를 누가 이어주느냐"임.**

---

## 5. 상용 제품의 장점 (오픈소스 조합 대비)

- **운영 부담 거의 0** : 업그레이드·패치·장애 대응·튜닝을 벤더가 함. Lake 처럼 Cilium·etcd·Ingress 트러블슈팅할 일 없음
- **층 간 통합** : 카탈로그 하나가 테이블·모델·에이전트·권한·리니지를 다 앎. 오픈소스는 HMS·MLflow·Keycloak·엔진 권한을 사람이 맞춰야 함
- **탄력성** : 서버리스로 쓸 때만 컴퓨트. 초 단위 증설·축소. 온프레미스는 노드 증설에 몇 달
- **자동 최적화** : 파일 압축·클러스터링·캐시·통계 수집을 엔진이 알아서 (Adaptive Compute, Predictive Optimization). Iceberg 유지보수 DAG 직접 안 짜도 됨
- **AI 기능 즉시 사용** : SQL 한 줄로 LLM 호출, 업무 에이전트, 코딩 에이전트, AI Gateway 가 출시와 동시에 켜짐
- **거버넌스·보안 인증** : SOC2·ISO 등 인증, 감사 로그, 데이터 마스킹이 기본
- **비개발자 접근성** : Genie·CoWork 로 현업이 자연어로 데이터 조회. 플랫폼팀 요청 대기 감소
- **지원·SLA** : 장애 시 벤더 책임. 인력이 적은 조직일수록 가치 큼

---

## 6. 그럼에도 단점

- **폐쇄망·온프레미스 불가** : 둘 다 퍼블릭 클라우드 SaaS. 데이터가 외부로 못 나가면 선택지 자체가 아님
- **비용 예측 어려움** : 소비량 과금. 쿼리·에이전트·GPU 사용이 늘면 청구액이 급증. 대규모 상시 워크로드는 자체 구축보다 비싸지는 지점이 옴
- **GPU 비용** : 대형 학습·상시 LLM 서빙은 보유 GPU(B300) 대비 클라우드 GPU 단가가 높음
- **종속(lock-in)** : 테이블은 Iceberg 로 열렸지만, 카탈로그 정책·시맨틱 계층·에이전트·파이프라인 정의는 여전히 벤더 고유
- **데이터 이동 비용** : 온프레미스 원천(Oracle 등) → 클라우드 전송, 클라우드 간 egress 비용
- **커스터마이징 한계** : 엔진 내부 수정·특수 하드웨어·네트워크(RDMA, IB) 최적화 불가
- **빠른 변화** : 제품명·기능이 해마다 바뀜 (Snowflake Intelligence → CoWork, Cortex Code → CoCo). 사내 표준·교육 자료가 금방 낡음
- **규제·데이터 주권** : 산업·국가 규제상 특정 데이터는 클라우드 반출 금지

---

## 7. 오픈소스 조합 재정리

| 구분 | 장점 | 단점 |
|---|---|---|
| 비용 | 라이선스 0, 보유 하드웨어 활용. 규모 클수록 유리 | 인력 비용, 운영 시간 |
| 통제 | 폐쇄망 가능, 데이터 주권, 하드웨어·네트워크 최적화 자유 | 모든 장애가 내 책임 |
| 기술 | 엔진 골라 쓰기, 최신 오픈소스 즉시 반영 | 층 사이 통합(권한·리니지·카탈로그)을 직접 맞춰야 함 |
| AI | B300 직접 사용, 사내 LLM 자유 | 에이전트·시맨틱 계층 같은 상위 기능은 직접 구축 |
| 종속 | 오픈 포맷·오픈 API → 이동 자유 | 조합이 복잡해 사내 노하우에 종속 |

---

## 8. 선택 기준

<!-- diagram: mlpe-com-04-choose.html -->

| 상황 | 추천 |
|---|---|
| 폐쇄망·데이터 주권 필수 | 오픈소스 조합 (선택지 없음) |
| 클라우드 가능 + SQL·BI 중심 + 운영 인력 적음 | Snowflake |
| 클라우드 가능 + ETL·ML·LLM 중심 | Databricks |
| 대규모 상시 GPU·온프레미스 데이터 대량 | 오픈소스 조합 (비용) |
| 하이브리드 | 민감 데이터는 온프레미스 오픈소스, 비민감 분석만 클라우드. **Iceberg 로 통일**하면 양쪽 이동 가능 |

---

## 9. 실무에서 확인

- **Lake 는 오픈소스가 정답인 환경** : 폐쇄망 + B300 보유 + 대규모 사용자. 상용 도입 검토보다 상용 기능을 **벤치마크 목록**으로 쓰는 게 실익
- **상용에서 가져올 아이디어**
  - 카탈로그 통일 → Apache Polaris 또는 Unity Catalog OSS 를 Iceberg REST 카탈로그로 온프레미스 설치 검토 (HMS 대체)
  - AI Gateway → MLflow AI Gateway 로 사내 LLM 키·예산·라우팅 중앙화
  - 시맨틱 계층·Metrics → StarRocks MV + 지표 정의 테이블로 단일 KPI 정의
  - 자동 유지보수 → Iceberg compaction·스냅샷 만료를 Airflow 공통 DAG 로 표준화
  - 업무 에이전트 → 사내 LLM + MCP 서버(StarRocks·Trino 조회 도구)로 소규모 PoC
- **비용 비교 시** : 클라우드 견적엔 컴퓨트·스토리지·egress·GPU 를 다 넣고, 자체 구축엔 하드웨어 감가·전력·인력까지 넣어야 공정함
- **오픈 포맷 유지** : 나중에 클라우드로 일부 이전하더라도 Iceberg + Parquet 이면 재적재 없이 연결 가능

> 주의 : 이 페이지의 기능 상태(GA·프리뷰)는 2026 서밋 발표·기사 기준. 실제 도입 판단 전 각 사 공식 문서로 재확인할 것.

> 주의 : 상용 vs 오픈소스는 기술 문제보다 **운영 인력·규제·비용 구조** 문제임. 기능 비교표만 보고 결정하지 말 것.

---

## 10. 용어 정리

- **AI Data Cloud** : Snowflake 의 플랫폼 포지셔닝 명칭
- **Virtual Warehouse** : Snowflake 컴퓨트 단위. 크기 지정해 켜고 끔
- **Polaris** : Iceberg REST 카탈로그. Apache 프로젝트로 오픈소스화
- **Horizon** : Snowflake 거버넌스·카탈로그 계층
- **Unity Catalog** : Databricks 통합 거버넌스 카탈로그. 오픈소스 버전 존재
- **Photon** : Databricks 벡터화 C++ 쿼리 엔진
- **Lakebase** : Databricks 서버리스 Postgres
- **LTAP** : 트랜잭션·분석을 데이터 한 벌로 처리하는 Databricks 구상
- **BYOC(Bring Your Own Cloud)** : 벤더 소프트웨어를 고객 클라우드 계정 안에서 실행
- **서버리스(serverless)** : 클러스터 관리 없이 쓴 만큼만 과금되는 컴퓨트
- **lock-in** : 특정 벤더에 묶여 이전 비용이 커지는 상태
- **egress** : 클라우드 밖으로 데이터 내보낼 때 드는 비용

---

## 11. 한 장 요약

| 항목 | Snowflake | Databricks | Lake 오픈소스 |
|---|---|---|---|
| 출발점 | SQL 웨어하우스 | Spark · ML | 직접 조립 |
| 2026 키워드 | CoWork·CoCo, Iceberg v3·Polaris, Adaptive Compute, Postgres | Genie, Agent Bricks, Lakebase·LTAP, Lakehouse//RT, AI Gateway | StarRocks·Spark·Trino·Iceberg·MLflow·Ray·vLLM |
| 강점 | 쉬움, 운영 0, SQL·BI | ETL·ML·LLM 통합, 오픈 포맷 | 폐쇄망, 비용, 통제, B300 직접 사용 |
| 약점 | 비용, 종속, 클라우드 전용 | 비용, 복잡도, 클라우드 전용 | 운영 부담, 층 간 통합 직접 |
| 어울리는 곳 | 운영 인력 적은 SQL 조직 | 데이터·ML 엔지니어 많은 조직 | 규제·폐쇄망·대규모 자체 인프라 |

**상용은 "통합과 운영"을 돈으로 사는 것이고, 오픈소스는 그걸 사람이 대신하는 대가로 통제와 비용을 얻는 것임. Lake 는 상용 기능을 목표 목록 삼아 오픈소스로 채우는 방향이 맞음.**

관련 글 : Lake 분석 플랫폼, 데이터 엔지니어링, Ray · Kubeflow · MLflow 비교
