## StarRocks on Kubernetes 운영자·사용자 매뉴얼

> 대상: K8s에 Operator로 배포한 StarRocks(shared-data, FE + CN + 오브젝트 스토리지) 환경
> 독자: 운영자(Part A), 사용자(Part B)
> 표기: `<ns>` 테넌트 네임스페이스, `<sr>` StarRocksCluster 이름, `<SR_VERSION>` StarRocks 이미지 버전, `<s3-endpoint>` AIStor/MinIO 엔드포인트
> 구성 흐름 그림: `starrocks-k8s-flow.drawio` (본문 ①~⑤ 번호와 매칭)

---

### 0. 한 장 요약

| 구분 | 핵심 |
|---|---|
| 구조 | FE(메타·SQL 파싱·플랜) → CN(실행) → 오브젝트 스토리지(영구 데이터) |
| 배포 | StarRocks Operator가 `StarRocksCluster` CR을 watch → FE/CN StatefulSet·Service·HPA 생성 |
| 접속 | `<sr>-fe-service.<ns>.svc:9030` (MySQL 프로토콜), Web UI는 `:8030` |
| 데이터 | 테이블 데이터는 S3(AIStor)에 저장, CN 로컬 디스크는 캐시일 뿐이다 |
| 운영 포인트 | FE 메타 PVC 보호, CN mem_limit < 컨테이너 limit, Operator watch 범위 축소 |
| 사용 포인트 | 내부망에서 접속, Stream Load는 CN 8040 직접, 대량 적재는 `INSERT ... FILES()` |

---

### 1. 아키텍처 요약

#### 1-1. 컴포넌트

| 컴포넌트 | 역할 | 상태 저장 | K8s 리소스 |
|---|---|---|---|
| FE | SQL 파싱, 옵티마이저, 메타데이터 관리, 리더 선출(BDB JE) | O (meta PVC) | StatefulSet |
| CN | 쿼리 실행, 적재 실행, 로컬 Data Cache | X (캐시만) | StatefulSet + HPA |
| BE | shared-nothing 모드의 실행+저장 노드 | O (데이터 PVC) | StatefulSet (이 문서 범위 외) |
| Operator | CR watch → Reconcile → 하위 리소스 생성·롤링 | X | Deployment |
| 오브젝트 스토리지 | 테이블 데이터 영구 저장 (shared-data) | O | 외부(AIStor/MinIO) |

- shared-data 모드에서는 CN이 죽어도 데이터는 안 날아간다. 캐시만 비워진다.
- FE 메타가 날아가면 클러스터 전체가 날아간다. FE PVC가 제일 중요한 자산이다.

#### 1-2. 주요 흐름 (그림 번호)

1. ① 사용자 → FE `:9030` SQL 접속
2. ② FE → CN 플랜 Fragment 분배 (brpc `:8060`, thrift `:9060`)
3. ③ CN → 로컬 Data Cache 조회
4. ④ 캐시 miss 시 S3 GET, 적재 시 S3 PUT
5. ⑤ FE → External Catalog(Iceberg/HMS) 메타 조회
6. Operator는 CR 변경을 watch 해서 FE/CN을 생성·롤링한다.
7. Prometheus는 FE `:8030/metrics`, CN `:8040/metrics`를 수집한다.

#### 1-3. 포트

| 컴포넌트 | 포트 | 용도 |
|---|---|---|
| FE | 8030 | HTTP (Web UI, Stream Load 진입, metrics) |
| FE | 9020 | thrift RPC |
| FE | 9030 | MySQL 프로토콜 쿼리 |
| FE | 9010 | edit log (FE 간 메타 복제) |
| CN | 8040 | HTTP (Stream Load, metrics) |
| CN | 9060 | thrift |
| CN | 9050 | heartbeat |
| CN | 8060 | brpc |
| CN | 9070 | starlet (shared-data) |

#### 1-4. Operator가 만드는 리소스 이름 규칙

| 리소스 | 이름 |
|---|---|
| FE Pod | `<sr>-fe-0`, `<sr>-fe-1`, ... |
| FE Service | `<sr>-fe-service` (접속용), `<sr>-fe-search` (headless) |
| CN Pod | `<sr>-cn-0`, ... |
| CN Service | `<sr>-cn-service`, `<sr>-cn-search` |
| CN HPA | `<sr>-cn-autoscaler` |

---

## Part A. 운영자 매뉴얼

### 2. 설치

#### 2-1. Helm 저장소 등록 (폐쇄망)

외부 반입 대신 사내 Nexus Helm 프록시를 쓴다.

```bash
helm repo add starrocks https://<nexus-host>/repository/<helm-proxy>/
helm repo update
helm search repo starrocks
# starrocks/kube-starrocks  (operator + starrocks 묶음)
# starrocks/operator        (operator 단독)
# starrocks/starrocks       (클러스터 단독)
```

이미지도 Nexus Docker 프록시 경로로 바꿔둔다.

```bash
helm show values starrocks/operator > operator-values.yaml
# image.repository 를 <nexus-docker>/starrocks/operator 로 수정
```

#### 2-2. Operator 설치

```bash
helm install starrocks-operator starrocks/operator \
  -n starrocks-operator --create-namespace \
  -f operator-values.yaml
kubectl get crd | grep starrocks
# starrocksclusters.starrocks.com
```

> **watch 범위를 반드시 좁힌다.** Operator가 클러스터 전체 ConfigMap을 watch 하면 테넌트 수가 많을 때 etcd/apiserver에 부하가 몰린다. `watchNamespace` 같은 범위 설정과 Operator 리소스를 values에서 확인한다.

#### 2-3. 테넌트 클러스터 생성

ConfigMap 먼저 만든다. shared-data 핵심 설정은 FE conf에 들어간다.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: <sr>-fe-cm
  namespace: <ns>
data:
  fe.conf: |
    LOG_DIR = ${STARROCKS_HOME}/log
    JAVA_OPTS = -Xmx8g -XX:+UseG1GC
    http_port = 8030
    rpc_port = 9020
    query_port = 9030
    edit_log_port = 9010
    run_mode = shared_data
    cloud_native_meta_port = 6090
    cloud_native_storage_type = S3
    aws_s3_endpoint = <s3-endpoint>
    aws_s3_path = <bucket>/<ns>
    aws_s3_region = us-east-1
    aws_s3_enable_path_style_access = true
    aws_s3_use_instance_profile = false
    aws_s3_access_key = <access-key>
    aws_s3_secret_key = <secret-key>
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: <sr>-cn-cm
  namespace: <ns>
data:
  cn.conf: |
    sys_log_level = INFO
    thrift_port = 9060
    webserver_port = 8040
    heartbeat_service_port = 9050
    brpc_port = 8060
    starlet_port = 9070
    mem_limit = 85%
    datacache_enable = true
```

> 키는 Secret으로 빼고 env로 주입하는 게 맞다. 위는 흐름 설명용이다.

CR을 만든다.

```yaml
apiVersion: starrocks.com/v1
kind: StarRocksCluster
metadata:
  name: <sr>
  namespace: <ns>
spec:
  starRocksFeSpec:
    image: <nexus-docker>/starrocks/fe-ubuntu:<SR_VERSION>
    replicas: 3
    requests: { cpu: "4", memory: 16Gi }
    limits:   { cpu: "4", memory: 16Gi }
    configMapInfo:
      configMapName: <sr>-fe-cm
      resolveKey: fe.conf
    storageVolumes:
      - name: fe-meta
        storageClassName: <local-sc>
        storageSize: 20Gi
        mountPath: /opt/starrocks/fe/meta
      - name: fe-log
        storageClassName: <local-sc>
        storageSize: 20Gi
        mountPath: /opt/starrocks/fe/log
  starRocksCnSpec:
    image: <nexus-docker>/starrocks/cn-ubuntu:<SR_VERSION>
    requests: { cpu: "8", memory: 32Gi }
    limits:   { cpu: "8", memory: 32Gi }
    configMapInfo:
      configMapName: <sr>-cn-cm
      resolveKey: cn.conf
    storageVolumes:
      - name: cn-cache
        storageClassName: <local-sc>
        storageSize: 200Gi
        mountPath: /opt/starrocks/cn/storage
      - name: cn-log
        storageClassName: <local-sc>
        storageSize: 20Gi
        mountPath: /opt/starrocks/cn/log
    autoScalingPolicy:
      version: v2
      minReplicas: 2
      maxReplicas: 8
      hpaPolicy:
        metrics:
          - type: Resource
            resource:
              name: cpu
              target: { type: Utilization, averageUtilization: 70 }
        behavior:
          scaleDown:
            stabilizationWindowSeconds: 600
```

```bash
kubectl apply -f <sr>-cm.yaml -f <sr>-cluster.yaml
kubectl -n <ns> get starrocksclusters
kubectl -n <ns> get pods -w
```

FE meta 스토리지 원칙:

- FE meta는 BDB JE라 fsync 지연에 민감하다. NFS보다 로컬 PV를 쓴다.
- CN cache도 로컬 PV가 좋다. 날아가도 캐시라 재생성된다.

#### 2-4. Storage Volume 등록

FE conf로 기본 볼륨이 잡히지만, 버킷을 나누거나 교체할 때는 SQL로 관리한다.

```sql
CREATE STORAGE VOLUME sv_main
TYPE = S3
LOCATIONS = ("s3://<bucket>/<ns>/")
PROPERTIES (
  "enabled" = "true",
  "aws.s3.region" = "us-east-1",
  "aws.s3.endpoint" = "<s3-endpoint>",
  "aws.s3.enable_path_style_access" = "true",
  "aws.s3.use_aws_sdk_default_behavior" = "false",
  "aws.s3.use_instance_profile" = "false",
  "aws.s3.access_key" = "<access-key>",
  "aws.s3.secret_key" = "<secret-key>"
);
SET sv_main AS DEFAULT STORAGE VOLUME;
SHOW STORAGE VOLUMES;
DESC STORAGE VOLUME sv_main;
```

---

### 3. 일상 점검

#### 3-1. K8s 레벨

```bash
kubectl -n <ns> get starrocksclusters <sr> -o jsonpath='{.status.phase}{"\n"}'
kubectl -n <ns> get pods -l app.kubernetes.io/instance=<sr> -o wide
kubectl -n <ns> get hpa
kubectl -n <ns> top pods
kubectl -n <ns> get events --sort-by=.lastTimestamp | tail -20
```

#### 3-2. StarRocks 레벨

```sql
SHOW FRONTENDS;          -- Alive, Role(LEADER/FOLLOWER), ReplayedJournalId 차이
SHOW COMPUTE NODES;      -- Alive, LastHeartbeat, ErrMsg
SHOW PROC '/current_queries';
SHOW PROCESSLIST;
SHOW LOAD WHERE STATE = 'CANCELLED' ORDER BY CreateTime DESC LIMIT 10;
SHOW ROUTINE LOAD;
```

체크 기준:

| 항목 | 정상 |
|---|---|
| FE Alive | 전부 true, LEADER 1개 |
| FE ReplayedJournalId | Follower가 Leader와 거의 같음 |
| CN Alive | 전부 true, ErrMsg 비어 있음 |
| 실패 적재 | 반복 패턴 없음 |
| HPA | min~max 사이에서 출렁임, max 고정이면 증설 검토 |

---

### 4. 설정 변경

#### 4-1. 동적 변경 (재시작 없음, 휘발성)

```sql
ADMIN SHOW FRONTEND CONFIG LIKE '%query_timeout%';
ADMIN SET FRONTEND CONFIG ("max_routine_load_task_num_per_be" = "32");
```

- `ADMIN SET` 은 FE 재시작 시 원복된다. ConfigMap에도 같이 반영한다.
- CN 동적 설정은 `UPDATE information_schema.be_configs SET value='...' WHERE name='...'` 형태로 바꾼다.

#### 4-2. 정적 변경 (ConfigMap)

```bash
kubectl -n <ns> edit cm <sr>-fe-cm
kubectl -n <ns> get pods -w   # Operator 롤링 재시작 확인
```

- ConfigMap 변경 시 롤링 재시작 여부는 Operator 버전마다 다르다. 반영이 안 되면 CR에 annotation 하나 바꿔서 롤링을 유도한다.

---

### 5. 스케일링

| 대상 | 방식 | 주의 |
|---|---|---|
| CN | HPA 자동 / `maxReplicas` 조정 | HPA 쓰면 `replicas` 직접 지정하지 않는다 (충돌) |
| CN 축소 | HPA scaleDown | 실행 중 쿼리 실패 가능, 캐시 손실 → 안정화 윈도우 길게 |
| FE | `replicas` 1 또는 3 (홀수) | 운영 중 FE 수 변경은 드물게, 사전 메타 백업 필수 |

```bash
kubectl -n <ns> patch starrocksclusters <sr> --type merge \
  -p '{"spec":{"starRocksCnSpec":{"autoScalingPolicy":{"maxReplicas":12}}}}'
```

---

### 6. 업그레이드

1. 릴리즈 노트에서 메타 포맷 변경, 비호환 설정 확인
2. FE 메타 이미지 생성 및 백업 (7장)
3. 이미지 반입 (Nexus 프록시 경로 확인)
4. CR의 FE/CN `image` 태그 변경 후 apply
5. Operator 롤링 진행 확인

```bash
kubectl -n <ns> patch starrocksclusters <sr> --type merge -p '
spec:
  starRocksFeSpec: { image: <nexus-docker>/starrocks/fe-ubuntu:<NEW> }
  starRocksCnSpec: { image: <nexus-docker>/starrocks/cn-ubuntu:<NEW> }'
kubectl -n <ns> get pods -w
```

- 업그레이드 순서 원칙은 CN/BE → FE, 다운그레이드는 FE → CN/BE 이다. Operator가 순서를 관리하지만 롤링 중 Pod 순서를 눈으로 확인한다.
- 테넌트가 많으면 카나리 네임스페이스 몇 개 먼저 올리고 하루 지켜본다.
- 마이너 버전 건너뛰기 업그레이드는 하지 않는다.

---

### 7. 백업·복구

#### 7-1. FE 메타

```sql
ALTER SYSTEM CREATE IMAGE;   -- 최신 메타 image 강제 생성
```

```bash
kubectl -n <ns> exec <sr>-fe-0 -- ls -lt /opt/starrocks/fe/meta/image | head
kubectl -n <ns> cp <sr>-fe-0:/opt/starrocks/fe/meta/image ./backup/<ns>-fe-image-$(date +%F)
```

#### 7-2. 테이블 데이터

- shared-data는 데이터가 오브젝트 스토리지에 있다. 버킷 단위 버저닝·복제(AIStor replication)가 1차 방어선이다.
- 논리 백업이 필요하면 `CREATE REPOSITORY` + `BACKUP SNAPSHOT` 을 쓴다. shared-data에서의 지원 범위는 버전별로 확인한다.

```sql
CREATE REPOSITORY repo_s3 WITH BROKER
ON LOCATION "s3://<backup-bucket>/<ns>/"
PROPERTIES (
  "aws.s3.endpoint" = "<s3-endpoint>",
  "aws.s3.enable_path_style_access" = "true",
  "aws.s3.access_key" = "<access-key>",
  "aws.s3.secret_key" = "<secret-key>"
);
BACKUP SNAPSHOT sales_db.snap_20261021 TO repo_s3 ON (sales);
SHOW BACKUP;
```

#### 7-3. 오브젝트 스토리지 주의

- StarRocks가 쓰는 prefix는 사람이 직접 지우거나 lifecycle 정책을 걸면 안 된다. 메타와 데이터가 어긋나면 복구가 어렵다.

---

### 8. 모니터링

| 대상 | 엔드포인트 | 볼 것 |
|---|---|---|
| FE | `:8030/metrics` | 쿼리 수·에러율·지연, JVM heap, journal 지연 |
| CN | `:8040/metrics` | 프로세스 메모리, 쿼리 실행 수, Data Cache hit |
| K8s | kube-state-metrics | Pod 재시작, OOMKilled, HPA 현재/최대 |

ServiceMonitor 예시:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: starrocks
  namespace: monitoring
spec:
  namespaceSelector: { any: true }
  selector:
    matchLabels: { app.kubernetes.io/component: fe }
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

알람 최소 세트:

- FE Pod 재시작 / LEADER 부재
- CN Alive=false 5분 이상
- CN OOMKilled
- HPA가 maxReplicas에 30분 이상 고정
- 쿼리 에러율 급증

---

### 9. 장애 대응

| 증상 | 원인 후보 | 확인 | 조치 |
|---|---|---|---|
| FE CrashLoop | 메타 손상, 시간 차이, 디스크 풀 | `fe.log`, `fe.warn.log`, `df -h` | NTP 확인, 디스크 확보, 메타 image 복구 |
| LEADER 없음 | Follower 과반 다운 | `SHOW FRONTENDS` | 과반 FE 우선 기동, 네트워크 9010 확인 |
| CN Alive=false | heartbeat 9050 불통, Service 엔드포인트 이상 | `SHOW COMPUTE NODES` ErrMsg, `kubectl get ep` | CN 재기동, CNI 상태 확인 |
| CN 간헐 통신 실패 | Cilium LB map 포화 | `cilium status --verbose`, `cilium bpf lb list \| wc -l` | `bpf-lb-map-max` 상향, Service 수 점검 |
| CN OOMKilled | `mem_limit` ≥ 컨테이너 limit | `kubectl describe pod`, cn.conf | `mem_limit` 을 limit의 80~85%로 |
| 쿼리 급격히 느림 | 캐시 미스, CN 축소 직후, 스큐 | Query Profile, cache hit | 안정화 윈도우 확대, 버킷 키 재설계 |
| 외부에서 Stream Load 실패 | FE가 CN Pod 주소로 redirect | curl `-v` 로 Location 확인 | 클러스터 내부 실행 또는 CN 8040 직접 호출 |
| too many versions | 너무 잦은 소량 적재 | `SHOW LOAD`, 에러 메시지 | 배치 크기 키우기, 적재 주기 늘리기 |
| etcd slow_apply | Operator 전역 ConfigMap watch | etcd 지표, apiserver watch 수 | watch 범위 축소, etcd 튜닝 |

긴급 시 먼저 할 것:

```sql
SHOW PROC '/current_queries';
KILL QUERY '<query_id>';
```

```bash
kubectl -n <ns> logs <sr>-fe-0 --tail=200
kubectl -n <ns> exec <sr>-fe-0 -- tail -200 /opt/starrocks/fe/log/fe.warn.log
kubectl -n <ns> logs <sr>-cn-0 --previous --tail=200
```

---

### 10. 운영 체크리스트

- [ ] Operator watch 범위가 필요한 네임스페이스로 제한돼 있다
- [ ] FE meta는 로컬 PV, 주기적 image 백업이 돈다
- [ ] CN `mem_limit` < 컨테이너 memory limit
- [ ] HPA 쓰는 클러스터는 CR에 `replicas` 직접 지정 안 했다
- [ ] S3 키는 Secret으로 관리한다
- [ ] StarRocks 버킷 prefix에 lifecycle 정책이 없다
- [ ] FE/CN metrics 수집, 최소 알람 세트가 걸려 있다
- [ ] 업그레이드는 카나리 네임스페이스부터 진행한다

---

## Part B. 사용자 매뉴얼

### 11. 접속

#### 11-1. 클러스터 내부 (Airflow, Spark, Pod)

```text
host: <sr>-fe-service.<ns>.svc.cluster.local
port: 9030
JDBC: jdbc:mysql://<sr>-fe-service.<ns>.svc.cluster.local:9030/<db>
```

#### 11-2. 로컬 PC에서 임시 접속

```bash
kubectl -n <ns> port-forward svc/<sr>-fe-service 9030:9030 8030:8030
mysql -h 127.0.0.1 -P 9030 -u <user> -p
```

#### 11-3. 클라이언트별

| 클라이언트 | 설정 |
|---|---|
| mysql CLI | MySQL 5.7/8.0 클라이언트 그대로 사용 |
| DBeaver | MySQL 드라이버, 포트 9030 |
| Python | `pymysql` 또는 SQLAlchemy `starrocks://user:pw@host:9030/db` |
| Airflow | MySQL Connection(포트 9030) + `SQLExecuteQueryOperator` |
| Spark | StarRocks Spark Connector (FE 8030/9030 지정) |

Web UI: `http://<fe-ingress-domain>` 또는 port-forward 후 `http://127.0.0.1:8030`

---

### 12. 계정·권한

```sql
CREATE USER 'alice'@'%' IDENTIFIED BY '<password>';
CREATE ROLE analyst;
GRANT USAGE ON DATABASE sales_db TO ROLE analyst;
GRANT SELECT ON ALL TABLES IN DATABASE sales_db TO ROLE analyst;
GRANT analyst TO USER 'alice'@'%';
SET DEFAULT ROLE analyst TO 'alice'@'%';

SHOW GRANTS FOR 'alice'@'%';
ALTER USER 'alice'@'%' IDENTIFIED BY '<new-password>';
```

- 개인 계정과 배치(ETL) 계정은 분리한다.
- `root` 는 운영자만 쓴다.

---

### 13. 테이블 설계

#### 13-1. 테이블 타입 고르기

| 타입 | 언제 | 예 |
|---|---|---|
| Duplicate Key | 원본 로그, 추가만 | 이벤트 로그 |
| Aggregate Key | 미리 합계가 필요 | 일별 지표 |
| Unique Key | 최신 값 덮어쓰기(레거시) | — |
| Primary Key | upsert/delete, 실시간 갱신 | 주문, 사용자 상태 |

신규 갱신형 테이블은 Primary Key로 간다.

#### 13-2. 예시

```sql
CREATE DATABASE IF NOT EXISTS sales_db;
USE sales_db;

CREATE TABLE orders (
  order_id   BIGINT NOT NULL,
  dt         DATE   NOT NULL,
  user_id    BIGINT,
  amount     DECIMAL(18,2),
  status     VARCHAR(20),
  updated_at DATETIME
)
PRIMARY KEY (order_id, dt)
PARTITION BY date_trunc('day', dt)
DISTRIBUTED BY HASH(order_id)
PROPERTIES (
  "datacache.enable" = "true"
);
```

설계 규칙:

- 파티션은 시간 컬럼으로 자른다. 쿼리 WHERE에 거의 항상 들어가는 컬럼이다.
- 버킷 키는 카디널리티 높은 컬럼으로 고른다. 스큐가 나면 쿼리 하나가 CN 하나에 몰린다.
- 버킷 수는 생략하면 자동 결정된다. 특별한 이유 없으면 생략한다.
- Primary Key에는 파티션 컬럼이 포함돼야 한다.

---

### 14. 데이터 적재

| 방식 | 언제 | 진입점 |
|---|---|---|
| `INSERT ... SELECT FROM FILES()` | S3의 parquet/orc/csv 대량 적재 | SQL (9030) |
| Stream Load | 파일·API로 수 GB 이하 적재 | HTTP (CN 8040 또는 FE 8030) |
| Routine Load | Kafka 실시간 적재 | SQL |
| Spark Connector | Spark ETL 결과 적재 | Spark |
| `INSERT INTO ... SELECT` | 내부/외부 테이블 간 변환 | SQL |

#### 14-1. S3 파일 → 테이블

```sql
INSERT INTO orders
SELECT * FROM FILES (
  "path" = "s3://<bucket>/raw/orders/dt=2026-10-21/*.parquet",
  "format" = "parquet",
  "aws.s3.endpoint" = "<s3-endpoint>",
  "aws.s3.enable_path_style_access" = "true",
  "aws.s3.access_key" = "<access-key>",
  "aws.s3.secret_key" = "<secret-key>"
);
```

스키마 미리보기:

```sql
DESC FILES ("path" = "s3://<bucket>/raw/orders/*.parquet", "format" = "parquet", ...);
```

#### 14-2. Stream Load

```bash
curl --location-trusted -u <user>:<password> \
  -H "label:orders_20261021_01" \
  -H "format:csv" -H "column_separator:," \
  -T orders.csv \
  http://<sr>-cn-service.<ns>.svc.cluster.local:8040/api/sales_db/orders/_stream_load
```

- FE 8030으로 보내면 FE가 CN Pod 주소로 redirect 한다. 클러스터 밖에서는 그 주소가 안 보여서 실패한다. 클러스터 안에서 실행하거나 CN 8040으로 직접 보낸다.
- `label` 은 중복 적재 방지 키다. 재시도 시 같은 label을 쓰면 두 번 안 들어간다.

#### 14-3. Kafka Routine Load

```sql
CREATE ROUTINE LOAD sales_db.rl_orders ON orders
COLUMNS (order_id, dt, user_id, amount, status, updated_at)
PROPERTIES ("format" = "json", "desired_concurrent_number" = "3")
FROM KAFKA (
  "kafka_broker_list" = "<broker>:9092",
  "kafka_topic" = "orders",
  "property.kafka_default_offsets" = "OFFSET_END"
);

SHOW ROUTINE LOAD FOR sales_db.rl_orders;
PAUSE ROUTINE LOAD FOR sales_db.rl_orders;
RESUME ROUTINE LOAD FOR sales_db.rl_orders;
```

#### 14-4. 적재 상태 확인

```sql
SHOW LOAD FROM sales_db ORDER BY CreateTime DESC LIMIT 10;
SELECT * FROM information_schema.loads ORDER BY CREATE_TIME DESC LIMIT 10;
```

---

### 15. 외부 데이터 조회 (External Catalog)

```sql
CREATE EXTERNAL CATALOG iceberg_cat
PROPERTIES (
  "type" = "iceberg",
  "iceberg.catalog.type" = "hive",
  "hive.metastore.uris" = "thrift://<hms-host>:9083",
  "aws.s3.endpoint" = "<s3-endpoint>",
  "aws.s3.enable_path_style_access" = "true",
  "aws.s3.access_key" = "<access-key>",
  "aws.s3.secret_key" = "<secret-key>"
);

SHOW CATALOGS;
SHOW DATABASES FROM iceberg_cat;
SELECT * FROM iceberg_cat.lake_db.events WHERE dt = '2026-10-21' LIMIT 10;

-- 내부 테이블과 조인
SELECT o.order_id, e.event_type
FROM default_catalog.sales_db.orders o
JOIN iceberg_cat.lake_db.events e ON o.user_id = e.user_id
WHERE o.dt = '2026-10-21';
```

- 자주 보는 외부 데이터는 비동기 MV로 내부에 당겨둔다.

```sql
CREATE MATERIALIZED VIEW mv_daily_events
REFRESH ASYNC EVERY (INTERVAL 1 HOUR)
AS SELECT dt, event_type, count(*) cnt
   FROM iceberg_cat.lake_db.events GROUP BY dt, event_type;
```

---

### 16. 쿼리 가이드

#### 16-1. 기본 습관

- 파티션 컬럼 조건을 항상 건다.
- `SELECT *` 대신 필요한 컬럼만 쓴다. 컬럼형 스토리지라 읽는 양이 바로 줄어든다.
- 큰 결과는 `LIMIT` 걸고 확인한 뒤 내보낸다.

#### 16-2. 느릴 때

```sql
EXPLAIN SELECT ...;                 -- 파티션 프루닝, 조인 방식 확인
SET enable_profile = true;          -- 세션 단위 프로파일
SELECT ...;
SHOW PROFILELIST LIMIT 5;
ANALYZE PROFILE FROM '<query_id>';
```

| 플랜에서 볼 것 | 의미 |
|---|---|
| `partitions=1/365` | 프루닝 잘 됨 |
| `partitions=365/365` | 파티션 조건 누락 |
| BROADCAST JOIN 대용량 | 작은 쪽이 사실 큰 테이블일 수 있음 |
| 한 Fragment만 오래 걸림 | 버킷 스큐 |

#### 16-3. 세션 변수

```sql
SET query_timeout = 600;        -- 초
SET query_mem_limit = 17179869184;  -- 16GB
SHOW VARIABLES LIKE '%timeout%';
```

#### 16-4. 내 쿼리 정리

```sql
SHOW PROCESSLIST;
KILL QUERY '<query_id>';
```

---

### 17. FAQ

| 질문 | 답 |
|---|---|
| CN Pod 재시작되면 데이터 날아가나 | 안 날아간다. 데이터는 S3에 있고 캐시만 비워진다 |
| 첫 쿼리만 느린 이유 | 캐시 미스다. 같은 데이터 반복 조회 시 빨라진다 |
| MySQL 문법 다 되나 | 프로토콜 호환이지 MySQL 엔진은 아니다. 트랜잭션·인덱스 개념이 다르다 |
| 외부 PC에서 Stream Load 안 됨 | 14-2 참고, CN 8040 직접 또는 클러스터 내부 실행 |
| 소량 INSERT 수천 번 해도 되나 | 안 된다. 버전이 쌓여 too many versions가 난다. 모아서 한 번에 넣는다 |
| 쿼리 타임아웃 | `query_timeout` 늘리기 전에 파티션 조건부터 확인한다 |

---

### 18. 용어 정리

| 용어 | 뜻 |
|---|---|
| FE | Frontend. 메타·SQL·플랜 담당, BDB JE로 리더 선출 |
| CN | Compute Node. 저장 없이 실행만 하는 무상태 노드 |
| shared-data | 데이터는 오브젝트 스토리지, 컴퓨트는 CN으로 분리한 모드 |
| Data Cache | CN 로컬 디스크/메모리에 S3 데이터를 캐싱하는 계층 |
| Storage Volume | shared-data에서 데이터를 쓸 S3 위치 정의 |
| Tablet | 파티션 × 버킷 단위 데이터 조각 |
| Fragment | 분산 실행 플랜의 단위, CN에 나눠 보내진다 |
| Label | 적재 작업 식별자, 중복 적재 방지 |
| External Catalog | Iceberg/Hive 등 외부 메타를 그대로 붙여 조회하는 기능 |
| Reconcile | Operator가 CR의 원하는 상태와 실제 상태를 맞추는 루프 |
