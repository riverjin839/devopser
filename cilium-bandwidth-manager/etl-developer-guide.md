# ETL 개발자 반영 가이드 (W → I 구간 대역폭 1G 제한)

작성일: 2026-11-19 · 대상: I 지역 Target K8s 클러스터에서 W 지역 SRC 데이터를 가져오는 Airflow DAG · Spark Job · StarRocks 적재 개발자
그림: [etl-developer-guide.drawio](./etl-developer-guide.drawio) (개발자 반영 지점 · 배포 전 확인 흐름)

## 1. 요약

W ↔ I 구간 회선은 10G이고, ETL은 이 중 **합계 1G**까지만 씁니다. 플랫폼팀이 Cilium Bandwidth Manager를 켜 두면, 개발자는 아래 세 가지를 코드에 반영하면 됩니다.

| # | 반영 위치 | 해야 할 것 |
| --- | --- | --- |
| 1 | Airflow DAG | W 지역 데이터를 가져오는 Spark 태스크에 `pool="etl_wi_bandwidth"` 지정 (동시 1개) |
| 2 | Spark 제출 설정 | executor 4개 고정, executor 파드에 ingress · egress `250M`, driver에 egress `50M` 어노테이션, `workload-type: etl` 레이블 |
| 3 | StarRocks 적재 | 파드 설정은 없음. W 지역에서 직접 읽지 말고 AIStor에 적재된 파일만 읽기, ETL 리소스 그룹 사용 |

Cilium 설정, 노드 NIC, Kyverno 정책은 플랫폼팀이 맡습니다. 개발자는 건드리지 않습니다.

**왜 250M인가**

```
파드당 상한 = 1G ÷ (동시 Spark Job 수 × Job당 executor 수) = 1G ÷ (1 × 4) = 250M
```

executor 수나 동시 Job 수를 바꾸면 합계가 1G를 넘습니다. 바꿔야 한다면 6장 절차로 플랫폼팀에 요청합니다.

## 2. Airflow DAG

W 지역 데이터를 가져오는 Spark 태스크는 모두 같은 pool에 넣습니다. pool slot이 1이라 이 태스크들은 한 번에 하나씩만 실행됩니다.

```python
from datetime import timedelta
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator

extract_w = SparkKubernetesOperator(
    task_id="extract_w_to_aistor",
    namespace="etl",
    application_file="spark/extract_w_to_aistor.yaml",  # 3장 SparkApplication
    pool="etl_wi_bandwidth",          # 필수: W → I 구간 1G 공유 pool (slot 1)
    execution_timeout=timedelta(hours=4),  # 1G 상한 기준으로 다시 잡기 (7장)
)
```

- `SparkSubmitOperator`를 쓰는 경우에도 `pool="etl_wi_bandwidth"`를 똑같이 넣습니다.
- pool은 Airflow 관리자가 한 번만 만듭니다: `airflow pools set etl_wi_bandwidth 1 "W-I 구간 ETL 1G"`.
- W 지역을 읽지 않는 태스크(AIStor → StarRocks 적재, 변환만 하는 태스크)는 이 pool에 넣지 않습니다. 넣으면 불필요하게 대기합니다.
- Airflow 밖(수동 `spark-submit`, 다른 스케줄러)에서 W 지역 데이터를 가져오는 Job은 pool에 잡히지 않아 합계가 1G를 넘습니다. 운영에서는 Airflow로만 실행합니다.

## 3. Spark Job 설정

### 3.1 SparkApplication (Spark Operator)

어노테이션은 반드시 `spec.driver` · `spec.executor` 아래에 넣습니다. `metadata.annotations`(SparkApplication 자체)에 넣으면 파드로 전달되지 않아 제한이 걸리지 않습니다.

```yaml
apiVersion: sparkoperator.k8s.io/v1beta2
kind: SparkApplication
metadata:
  name: extract-w-to-aistor
  namespace: etl
spec:
  type: Scala
  mode: cluster
  image: registry.example.com/etl/spark:3.5
  mainClass: com.example.etl.ExtractWToAIStor
  mainApplicationFile: local:///opt/etl/etl.jar
  dynamicAllocation:
    enabled: false                 # executor 수 고정
  driver:
    cores: 1
    memory: 4g
    labels:
      workload-type: etl
    annotations:
      kubernetes.io/egress-bandwidth: "50M"
  executor:
    instances: 4                   # 4개 고정 (1G ÷ 250M)
    cores: 4
    memory: 8g
    labels:
      workload-type: etl
    annotations:
      kubernetes.io/ingress-bandwidth: "250M"   # W 지역 → executor (추출)
      kubernetes.io/egress-bandwidth: "250M"    # executor → AIStor (저장)
```

### 3.2 spark-submit

```bash
spark-submit \
  --master k8s://https://<api-server>:6443 \
  --deploy-mode cluster \
  --conf spark.kubernetes.namespace=etl \
  --conf spark.executor.instances=4 \
  --conf spark.dynamicAllocation.enabled=false \
  --conf spark.kubernetes.driver.label.workload-type=etl \
  --conf spark.kubernetes.executor.label.workload-type=etl \
  --conf spark.kubernetes.driver.annotation.kubernetes.io/egress-bandwidth=50M \
  --conf spark.kubernetes.executor.annotation.kubernetes.io/ingress-bandwidth=250M \
  --conf spark.kubernetes.executor.annotation.kubernetes.io/egress-bandwidth=250M \
  ...
```

dynamic allocation이 꼭 필요하면 `spark.dynamicAllocation.maxExecutors=4`로 상한을 고정합니다.

### 3.3 읽기 · 쓰기 코드

- **W 지역 읽기는 executor에서만:** driver에서 `collect()`나 단일 JDBC 연결로 대량 데이터를 받지 않습니다. driver 상한은 50M입니다.
- **병렬도:** JDBC `numPartitions`, 파일 분할 수는 `executor 수 × cores`(예: 16) 근처로 둡니다. 더 늘려도 합계 1G는 넘지 않고 태스크만 대기합니다.
- **재시도:** 상한을 넘는 수신 패킷은 버려지고 TCP가 재전송합니다. 읽기 타임아웃(`queryTimeout`, 소켓 타임아웃)을 너무 짧게 잡지 않습니다.
- **저장:** 결과는 AIStor(S3)에 씁니다. 같은 노드의 AIStor 파드로 가는 쓰기는 제한이 걸리지 않을 수 있지만 W ↔ I 구간과는 무관합니다.
- **hostNetwork 금지:** `hostNetwork: true` 파드는 제한이 적용되지 않습니다.

## 4. StarRocks 적재

StarRocks(FE · CN)는 여러 사용자가 함께 쓰므로 파드 제한을 걸지 않습니다. 개발자는 SQL과 적재 방식만 지킵니다.

- **W 지역에서 직접 읽지 않습니다.** JDBC catalog나 `FILES()`로 W 지역 SRC를 바로 읽으면 Spark pool과 상한을 우회해 구간 1G를 넘습니다. W 지역 데이터는 Spark로 AIStor에 먼저 적재한 뒤 StarRocks가 AIStor에서 읽습니다.
- **AIStor에서 적재:** Broker Load 또는 `INSERT INTO ... SELECT * FROM FILES("path" = "s3://<bucket>/...")`를 씁니다.
- **ETL 리소스 그룹 사용:** 적재 계정을 ETL 리소스 그룹에 묶어 조회 쿼리와 CPU · 메모리를 나눕니다. 리소스 그룹 생성은 StarRocks 담당자에게 요청합니다.
- **적재 동시성:** 같은 테이블 · 파티션에 적재를 동시에 여러 개 보내지 않습니다. Airflow에서 순서대로 실행합니다.

## 5. 배포 전 확인

개발 환경에서 한 번 실행하고 아래를 확인한 뒤 운영에 반영합니다.

```bash
# 1) 파드에 어노테이션 · 레이블이 붙었는지 (Job/SparkApplication이 아니라 파드에서 확인)
kubectl -n etl get pod -l spark-role=executor \
  -o custom-columns='NAME:.metadata.name,IN:.metadata.annotations.kubernetes\.io/ingress-bandwidth,OUT:.metadata.annotations.kubernetes\.io/egress-bandwidth,TYPE:.metadata.labels.workload-type'

# 2) executor 수가 4개인지
kubectl -n etl get pod -l spark-role=executor --no-headers | wc -l
```

- 제한이 실제로 걸렸는지(`cilium-dbg bpf bandwidth list`)는 플랫폼팀이 확인합니다. 개발 환경에서 처음 적용할 때 한 번 요청합니다.
- 실행 시간이 7장 예상치와 크게 다르면 배포 전에 플랫폼팀과 확인합니다.

**PR 셀프 체크리스트**

- [ ] W 지역을 읽는 Spark 태스크에 `pool="etl_wi_bandwidth"` 지정
- [ ] executor 4개 고정 (`dynamicAllocation` 비활성 또는 `maxExecutors=4`)
- [ ] 어노테이션이 driver · executor 파드 템플릿 위치에 있음 (ingress · egress 250M, driver 50M)
- [ ] `workload-type: etl` 레이블
- [ ] driver에서 대량 데이터 수신 없음, `hostNetwork` 없음
- [ ] StarRocks가 W 지역을 직접 읽지 않음, AIStor에서 적재
- [ ] `execution_timeout`을 1G 기준 예상 시간으로 조정

## 6. 값을 바꿔야 할 때

executor 수, 동시 Job 수, 파드당 상한은 개발자가 혼자 바꾸지 않습니다. 합계 1G가 깨지기 때문입니다.

1. 필요 이유와 원하는 값(예: executor 8개)을 정리합니다.
2. 플랫폼팀에 요청합니다. 플랫폼팀이 `1G ÷ (동시 Job 수 × executor 수)`로 파드당 상한을 다시 계산해 줍니다(예: executor 8개면 `125M`).
3. 받은 값으로 2 · 3장 설정을 함께 바꿉니다.

## 7. 실행 시간 예상

1G 상한에서 W 지역 데이터 전송 시간은 대략 아래와 같습니다. 실제로는 재전송 · 오버헤드 때문에 더 걸리므로 `execution_timeout`은 넉넉히(예: 1.5배) 잡습니다.

```
전송 시간(초) ≈ 데이터 크기(바이트) × 8 ÷ 1,000,000,000
```

| 데이터 크기 | 1G 기준 최소 전송 시간 | `execution_timeout` 권장 |
| --- | --- | --- |
| 10 GB | 약 80초 | 30분 (기본값 유지) |
| 100 GB | 약 13분 | 30분 |
| 500 GB | 약 67분 | 2시간 |
| 1 TB | 약 2시간 13분 | 4시간 |

## 8. 자주 묻는 질문

- **Job이 전보다 느려졌습니다.** 정상입니다. 구간 1G 상한 때문입니다. 마감 시각을 못 맞추면 6장 절차로 요청합니다.
- **어노테이션을 넣었는데 제한이 안 걸리는 것 같습니다.** 파드에 어노테이션이 있는지 5장 명령으로 먼저 확인합니다. 파드에 있는데도 안 걸리면 플랫폼팀에 확인을 요청합니다.
- **W 지역을 읽지 않는 Job도 어노테이션이 필요합니까?** 필수는 아닙니다. 다만 AIStor로 대량 쓰기를 하면 같은 노드의 다른 서비스에 영향을 줄 수 있어 egress 제한을 권장합니다(가이드 4.1 티어 참고).

전체 배경과 플랫폼 작업은 [cilium-bandwidth-manager-etl-guide.md](./cilium-bandwidth-manager-etl-guide.md), 일정은 [cilium-bandwidth-manager-work-plan.md](./cilium-bandwidth-manager-work-plan.md)를 참고합니다.
