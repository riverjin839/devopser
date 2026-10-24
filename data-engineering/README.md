## 데이터 엔지니어링 - Oracle · Hadoop → StarRocks · Iceberg on S3

> **목표** : Lake 의 데이터가 원천 DB 에서 S3(AIStor) 레이크하우스로 들어와 분석·ML 로 나가기까지의 구조, 엔진별 역할, 적재·이관·유지보수 방법 이해

- 기준 환경 : 원천 Oracle 외 여러 DB, 과거 Hadoop(HDFS) 데이터, AIStor(MinIO S3), StarRocks, Iceberg, Airflow, Spark, Trino
- 전제 : StarRocks 는 shared-data(스토리지·컴퓨트 분리) 모드로 내부 테이블도 S3 에 저장된다고 가정. 실제 구성과 다르면 2-2 만 바꿔 읽을 것

---

## 1. 개요

데이터 엔지니어링 = 분석가·ML 이 쓸 수 있는 형태로 데이터를 **옮기고, 정리하고, 유지하는 일**.

Lake 구조는 레이크하우스(lakehouse) 형태.

- 저장은 S3 한 곳 (AIStor)
- 그 위에 테이블 규칙(Iceberg)을 얹어 DB 처럼 씀
- 엔진은 용도별로 여러 개 (StarRocks, Spark, Trino) 가 **같은 데이터**를 읽음

<!-- diagram: mlpe-de-01-overall.html -->

| 흐름 | 경로 |
|---|---|
| 운영 데이터 | Oracle → Spark JDBC → Iceberg bronze → silver → StarRocks MV(gold) → BI |
| 과거 데이터 | Hadoop HDFS → distcp → S3 → Iceberg 등록 → 검증 |
| 조회 | 고속 집계 = StarRocks, 탐색·연합 조회 = Trino, 대량 가공 = Spark |
| ML 연결 | Iceberg 스냅샷 → Ray Data · Jupyter → MLflow 에 스냅샷 ID 기록 |

**저장은 하나(S3 + Iceberg), 엔진은 여럿. 엔진끼리 데이터 복사 안 하는 게 레이크하우스 핵심.**

---

## 2. 핵심 개념

### 2-1. 레이크하우스 5개 층

| 층 | 하는 일 | Lake 구성 |
|---|---|---|
| 스토리지 | 파일 보관 | AIStor (S3 API) |
| 파일 포맷 | 컬럼 단위 저장·압축 | Parquet (과거 ORC 혼재) |
| 테이블 포맷 | 파일 묶음을 테이블로. 트랜잭션·스냅샷 | Iceberg |
| 카탈로그 | 테이블 이름 → 현재 메타 위치 | Hive Metastore 또는 REST 카탈로그 |
| 엔진 | SQL·가공 실행 | StarRocks, Spark, Trino |

- 예전 Hadoop = HDFS + Hive 테이블 (디렉터리 = 테이블). 파일 단위 수정 불가, 동시 쓰기 위험
- Iceberg = 파일 목록을 메타데이터로 관리 → upsert, 스키마 변경, 시간 여행 가능

### 2-2. StarRocks 카탈로그

<!-- diagram: mlpe-de-02-catalog.html -->

- **default_catalog** : StarRocks 내부 테이블. shared-data 모드면 데이터 본체는 S3, CN 노드가 로컬 캐시로 속도 보완
- **external catalog** : 외부 테이블을 복사 없이 조회. `iceberg_catalog`, `hive_catalog`, `jdbc_catalog` 등
- 조회 이름 = `카탈로그.DB.테이블` 3단계. 카탈로그 다른 테이블끼리 조인 가능
- 비동기 MV(materialized view)로 외부 Iceberg 를 집계해 내부 테이블처럼 빠르게 서빙

default_catalog = 빠른 서빙용 사본, iceberg_catalog = 원본 레이크.

```sql
-- 외부 Iceberg 카탈로그 등록 (HMS 기준. REST 면 type 만 rest + uri)
CREATE EXTERNAL CATALOG iceberg_lake
PROPERTIES (
  "type" = "iceberg",
  "iceberg.catalog.type" = "hive",
  "hive.metastore.uris" = "thrift://hms.lake.svc:9083",
  "aws.s3.endpoint" = "http://minio.aistor.svc",
  "aws.s3.enable_path_style_access" = "true",
  "aws.s3.region" = "us-east-1",
  "aws.s3.access_key" = "${AK}",
  "aws.s3.secret_key" = "${SK}"
);

-- 카탈로그 넘나드는 조인
SELECT l.lot_id, l.step, c.product_name
FROM iceberg_lake.silver.lot_hist l
JOIN default_catalog.mart.dim_product c ON l.product_cd = c.product_cd
WHERE l.dt = '2026-10-24';

-- Iceberg 위 비동기 MV = gold
CREATE MATERIALIZED VIEW mart.daily_lot_yield
REFRESH ASYNC EVERY (INTERVAL 1 HOUR)
AS SELECT dt, product_cd, avg(yield) AS yield, count(*) AS lots
   FROM iceberg_lake.silver.lot_hist
   GROUP BY dt, product_cd;
```

### 2-3. Iceberg 구조

<!-- diagram: mlpe-de-03-iceberg.html -->

1. 카탈로그는 "지금 metadata.json 이 어디 있는지"만 앎
2. metadata.json : 스키마, 파티션 규칙, 스냅샷 목록
3. 커밋(쓰기) 1번 = 스냅샷 1개
4. 스냅샷 → manifest list → manifest → 실제 Parquet 파일
5. manifest 에 파일별 min/max 통계 → 조회 시 필요 없는 파일 건너뜀

Iceberg 가 주는 것

- **ACID 커밋** : 쓰다 실패해도 반쪽 데이터 안 보임
- **MERGE / UPDATE / DELETE** : 원천 변경분 upsert
- **스키마 진화** : 컬럼 추가·이름 변경해도 기존 파일 안 고침
- **파티션 진화** : 일 → 시간 파티션으로 바꿔도 재적재 불필요
- **시간 여행** : 특정 스냅샷 시점 조회 → 학습 데이터 재현
- 단, 커밋마다 파일·스냅샷 쌓임 → **유지보수(4장) 안 하면 느려짐**

### 2-4. 엔진 역할 분담

<!-- diagram: mlpe-de-06-medallion.html -->

| 엔진 | 잘하는 것 | 맡길 일 | 안 맡길 일 |
|---|---|---|---|
| Spark | 대량 배치, 복잡 변환, Iceberg 쓰기·유지보수 | Oracle 추출, bronze·silver 적재, compaction, 이관 | 대화형 조회 |
| Trino | 여러 소스 연합 조회, 표준 SQL | 탐색, 품질 검사, Oracle 원천과 대조 | 대량 쓰기, 장시간 배치 |
| StarRocks | 초고속 OLAP, 동시 사용자 많은 조회 | gold MV, 대시보드 서빙, 내부 마트 | 대량 ETL 원천 처리 |
| Airflow | 순서·스케줄·재시도 | 위 작업을 DAG 로 연결 | 데이터 처리 자체 |

Medallion 계층

- **bronze** : 원천 그대로 복제 + 적재 시각. 문제 생기면 여기서 재처리
- **silver** : 타입 통일, 코드값 해석, 중복 제거. 분석가·ML 이 주로 읽는 층
- **gold** : 업무 단위 집계·피처. StarRocks MV 또는 내부 테이블

---

## 3. 파이프라인 시나리오

### 3-1. Oracle → Iceberg → StarRocks

<!-- diagram: mlpe-de-04-oracle-etl.html -->

증분 방식 선택

| 방식 | 원리 | 장점 | 단점 |
|---|---|---|---|
| 전체 적재 | 매번 전 테이블 | 단순 | 큰 테이블 불가, 원천 부하 |
| 워터마크 증분 | `UPD_DT >= 마지막 적재 시각` | 구현 쉬움, 지금 바로 가능 | 삭제 못 잡음, 수정 시각 컬럼 필요 |
| CDC | 리두 로그 변경분 (GoldenGate, Debezium LogMiner) | 삭제까지 실시간 | 구성·운영 복잡, DBA 협조 필수 |

시작은 워터마크 증분, 삭제가 중요한 테이블만 CDC.

```python
# Spark : Oracle 증분 추출 → bronze MERGE
from pyspark.sql import SparkSession

spark = (SparkSession.builder.appName("ora_lot_hist")
  .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
  .config("spark.sql.catalog.lake", "org.apache.iceberg.spark.SparkCatalog")
  .config("spark.sql.catalog.lake.type", "hive")
  .config("spark.sql.catalog.lake.uri", "thrift://hms.lake.svc:9083")
  .config("spark.sql.catalog.lake.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
  .config("spark.sql.catalog.lake.s3.endpoint", "http://minio.aistor.svc")
  .config("spark.sql.catalog.lake.s3.path-style-access", "true")
  .getOrCreate())

ds = spark.conf.get("spark.etl.ds")                      # Airflow 가 넘겨준 날짜
src = (spark.read.format("jdbc")
  .option("url", "jdbc:oracle:thin:@//ora-scan:1521/MESDB")
  .option("dbtable", f"(SELECT * FROM MES.LOT_HIST "
                     f" WHERE UPD_DT >= TO_DATE('{ds}','YYYY-MM-DD')) t")
  .option("fetchsize", "10000")
  .option("partitionColumn", "LOT_SEQ").option("lowerBound", "1")
  .option("upperBound", "900000000").option("numPartitions", "8")   # 원천 세션 8개 제한
  .option("oracle.jdbc.mapDateToTimestamp", "true")
  .load())

src.createOrReplaceTempView("inc")
spark.sql("""
  MERGE INTO lake.bronze.lot_hist t
  USING (SELECT *, current_timestamp() AS _ingested_at FROM inc) s
  ON t.LOT_ID = s.LOT_ID AND t.STEP_SEQ = s.STEP_SEQ
  WHEN MATCHED THEN UPDATE SET *
  WHEN NOT MATCHED THEN INSERT *
""")
```

```python
# Airflow DAG : 추출 → 정제 → 품질 → MV 갱신
from datetime import datetime
from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator
from airflow.providers.common.sql.operators.sql import SQLCheckOperator, SQLExecuteQueryOperator

with DAG("mes_lot_hist", schedule="0 2 * * *", start_date=datetime(2026, 10, 1), catchup=False) as dag:
    bronze = SparkKubernetesOperator(task_id="oracle_to_bronze", namespace="etl",
                                     application_file="spark/oracle_to_bronze.yaml")
    silver = SparkKubernetesOperator(task_id="bronze_to_silver", namespace="etl",
                                     application_file="spark/bronze_to_silver.yaml")
    dq = SQLCheckOperator(task_id="dq_dup_check", conn_id="trino",
        sql="SELECT count(*) = count(DISTINCT lot_id || step_seq) "
            "FROM iceberg.silver.lot_hist WHERE dt = DATE '{{ ds }}'")
    mart = SQLExecuteQueryOperator(task_id="refresh_gold", conn_id="starrocks",
        sql="REFRESH MATERIALIZED VIEW mart.daily_lot_yield")
    bronze >> silver >> dq >> mart
```

- 포인트 : Oracle 은 운영 DB. 추출 시간대·병렬 세션 수를 DBA 와 합의
- `MERGE` 키 = 원천 PK. PK 없는 테이블은 bronze 에 append + silver 에서 중복 제거

### 3-2. Hadoop 과거 데이터 → S3 Iceberg

<!-- diagram: mlpe-de-05-hadoop.html -->

방법 3가지

| 방법 | 동작 | 언제 |
|---|---|---|
| `add_files` | 복사한 Parquet·ORC 파일을 재작성 없이 Iceberg 에 등록 | 대용량, 빠른 이관. 파일 그대로 써도 될 때 |
| `migrate` / `snapshot` | 같은 메타스토어의 Hive 테이블을 Iceberg 로 전환·복제 | HMS 를 같이 옮길 때 |
| CTAS 재작성 | Spark 로 읽어 새 Iceberg 테이블로 다시 씀 | 파티션·스키마 정리, 작은 파일 많을 때 |

```bash
# 1) HDFS → AIStor 복사 (파티션 단위로 끊어서)
hadoop distcp -m 64 \
  -Dfs.s3a.endpoint=http://minio.aistor.svc \
  -Dfs.s3a.path.style.access=true \
  hdfs://nn/warehouse/mes.db/lot_hist/dt=2019* \
  s3a://lake/legacy/mes/lot_hist/
```

```sql
-- 2) Spark SQL : 빈 Iceberg 테이블 만들고 파일 등록
CREATE TABLE lake.bronze.lot_hist_legacy (lot_id string, step_seq int, yield double, dt date)
USING iceberg PARTITIONED BY (dt);

CALL lake.system.add_files(
  table => 'bronze.lot_hist_legacy',
  source_table => '`parquet`.`s3a://lake/legacy/mes/lot_hist`');

-- 3) 검증 : 원본 Hive 와 건수·합계 대조 (Trino 로 양쪽 조회)
SELECT dt, count(*), sum(yield) FROM iceberg.bronze.lot_hist_legacy GROUP BY dt;
```

- 포인트 : `add_files` 는 파일을 안 고침 → 작은 파일 문제도 그대로 따라옴. 이관 후 compaction 한 번
- ORC·Parquet 혼재 가능. 단, 컬럼 타입이 테이블 스키마와 맞아야 등록됨

---

## 4. 운영 - 테이블 유지보수

Iceberg 는 쓰기만 하면 점점 느려짐. 주기 작업 필수.

| 작업 | 문제 | 명령 (Spark) | 주기 |
|---|---|---|---|
| 작은 파일 합치기 | 증분 적재마다 파일 증가 → 조회 느려짐 | `rewrite_data_files` | 일 |
| 스냅샷 만료 | 메타데이터·옛 파일 누적 | `expire_snapshots` | 일 |
| 고아 파일 삭제 | 실패한 쓰기 잔여 파일 | `remove_orphan_files` | 주 |
| manifest 정리 | manifest 너무 많음 | `rewrite_manifests` | 주 |

```sql
CALL lake.system.rewrite_data_files(table => 'silver.lot_hist',
  options => map('target-file-size-bytes', '536870912'));        -- 512MB 목표
CALL lake.system.expire_snapshots(table => 'silver.lot_hist',
  older_than => TIMESTAMP '2026-10-18 00:00:00', retain_last => 30);
CALL lake.system.remove_orphan_files(table => 'silver.lot_hist');
```

> 주의 : 스냅샷 만료 = 그 시점으로 시간 여행 불가. ML 학습에 쓴 스냅샷은 태그(`ALTER TABLE ... CREATE TAG`)로 고정해 만료에서 제외할 것.

> 주의 : 같은 Iceberg 테이블에 Spark·StarRocks·Trino 가 동시에 쓰면 커밋 충돌. **쓰기 엔진은 테이블당 하나**로 정할 것.

---

## 5. ML · LLM 과 연결

책 1장 "데이터 버전관리 표준 도구 없음" → Iceberg 스냅샷이 실무 답에 가까움.

- 학습 시작 시 읽은 테이블의 snapshot ID 를 MLflow run 에 기록
- 재현 필요하면 같은 snapshot ID 로 다시 읽음
- 학습용 스냅샷은 태그로 고정 → 유지보수에서 안 지워짐

```python
import mlflow, ray
from pyiceberg.catalog import load_catalog

cat = load_catalog("lake", **{"type": "hive", "uri": "thrift://hms.lake.svc:9083",
                              "s3.endpoint": "http://minio.aistor.svc"})
tbl = cat.load_table("silver.lot_hist")
snap = tbl.current_snapshot().snapshot_id

ds = ray.data.read_iceberg(table_identifier="silver.lot_hist",
                           catalog_kwargs={"name": "lake", "type": "hive",
                                           "uri": "thrift://hms.lake.svc:9083"},
                           snapshot_id=snap)                     # 이 시점 데이터로 고정

with mlflow.start_run():
    mlflow.log_params({"data.table": "silver.lot_hist", "data.snapshot_id": snap})
    ...                                                          # 학습
```

- 정형 피처 = gold 층 또는 StarRocks MV 를 피처 테이블로
- 문서·이미지·영상 원본 = AIStor 버킷, 목록·메타데이터만 Iceberg 테이블로 관리하면 검색·버전 관리 쉬움

---

## 6. 실무에서 확인

- **Oracle 타입 매핑** : `NUMBER` 정밀도 없으면 Spark 에서 `DECIMAL(38,10)` 등으로 흔들림 → 스키마 명시. Oracle `DATE` 는 시분초 포함 → timestamp 로 받을 것
- **원천 부하** : `numPartitions`·추출 시간대 제한. 운영 시간 중 전체 적재 금지
- **AIStor 설정** : 엔진마다 path-style, endpoint, 리전 설정 이름이 다름 (Spark `s3.path-style-access`, StarRocks `aws.s3.enable_path_style_access`, Trino `s3.path-style-access`). 하나 틀리면 버킷 못 찾음
- **카탈로그 일원화** : StarRocks·Spark·Trino 가 같은 HMS(또는 REST 카탈로그)를 봐야 같은 테이블. 엔진별 카탈로그 따로 두면 메타 꼬임
- **권한** : Keycloak 그룹 → Trino·StarRocks 역할 → AIStor 버킷 정책. 사용자 1,000명 규모면 원천 PII 컬럼은 silver 에서 마스킹
- **작은 파일** : 시간 단위 증분 + 파티션 과다 = 파일 폭증. 파티션은 일 단위부터 시작
- **Hadoop 이관 검증** : 파티션별 건수·합계·NULL 수 대조 결과를 테이블로 남김. 이관 끝난 HDFS 는 읽기 전용 유지 후 폐기
- **StarRocks MV** : 원천 Iceberg 스냅샷 바뀌면 갱신. 갱신 주기 = 대시보드 신선도 요구에 맞춤

> 주의 : StarRocks 가 shared-nothing 모드면 default_catalog 데이터는 BE 로컬 디스크에 있음. "StarRocks 거쳐 S3 저장"이 shared-data 모드인지, Iceberg 로 내보내는 구조인지 먼저 확인할 것.

---

## 7. 용어 정리

- **레이크하우스(lakehouse)** : 오브젝트 스토리지 위에 테이블 포맷을 얹어 DB 처럼 쓰는 구조
- **Iceberg** : 파일 묶음을 ACID 테이블로 관리하는 오픈 테이블 포맷
- **스냅샷(snapshot)** : Iceberg 커밋 1회 시점의 테이블 상태
- **Manifest** : 데이터 파일 목록 + 컬럼 통계 파일
- **카탈로그(catalog)** : 테이블 이름 → 현재 메타데이터 위치 매핑 (HMS, REST)
- **default_catalog** : StarRocks 내부 테이블 카탈로그
- **external catalog** : StarRocks 가 외부 테이블을 복사 없이 조회하는 연결
- **shared-data 모드** : StarRocks 데이터를 S3 에 두고 CN 노드가 연산·캐시만 맡는 구조
- **Medallion** : bronze(원천) · silver(정제) · gold(업무) 3계층 설계
- **워터마크 증분** : 마지막 적재 시각 이후 변경분만 가져오는 방식
- **CDC(Change Data Capture)** : DB 변경 로그를 읽어 변경분 실시간 전달
- **compaction** : 작은 파일을 큰 파일로 합치는 유지보수

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 구조 | AIStor(S3) + Parquet + Iceberg + HMS + 엔진 여럿 = 레이크하우스 |
| StarRocks | default_catalog(빠른 서빙) + iceberg_catalog(원본 레이크), MV 로 gold |
| Oracle 적재 | Spark JDBC 워터마크 증분 → bronze MERGE → silver 정제 → 품질 → MV |
| Hadoop 이관 | distcp → add_files(재작성 없음) → 검증 → compaction |
| 엔진 분담 | Spark = 쓰기·가공, Trino = 탐색·검증, StarRocks = 서빙, Airflow = 순서 |
| 유지보수 | rewrite_data_files, expire_snapshots, remove_orphan_files |
| ML 연결 | snapshot ID 를 MLflow 에 기록 → 학습 데이터 재현 |
| 함정 | 타입 매핑, 원천 부하, S3 설정 이름, 카탈로그 분리, 동시 쓰기 |

**데이터 엔지니어링의 핵심은 데이터를 한 번 S3 + Iceberg 에 제대로 두고, 엔진은 용도대로 붙이고, 테이블을 계속 관리하는 것임.**

관련 글 : Lake 분석 플랫폼
