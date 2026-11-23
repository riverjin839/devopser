> **목표** : Apache Ambari 를 모듈 단위로 뜯어보고, PEP(devops_management) 에 옮겨 쓸 운영 패턴을 고름

- 출처 : github.com/apache/ambari (trunk `77de245`, 2026-11-23 커밋), 레포 `AGENTS.md` · `docs/` · `ambari-server/docs/api/v1`
- 기준 버전 : 3.0.0 (최신 릴리스 태그 `release-3.0.0`, 2026-11 기준). 구조 설명은 trunk 기준

---

## 1. 개요

- Ambari = 하둡 계열 클러스터를 설치(프로비저닝)·관리·모니터링하는 도구
- Server(Java) 1대 + 호스트마다 Agent(Python) 1개 + Web UI + Stack 정의 묶음으로 구성됨
- 서비스별 지식(설치 방법, 설정, 알람, 순서)은 코드가 아니라 Stack 폴더의 선언 파일에 들어감

<!-- diagram: amb-overview.html -->

**서비스 지식은 Stack 정의 폴더에 선언으로 넣고, Server 는 그걸 해석해 Agent 에 명령을 나르는 범용 엔진임**

---

## 2. 개념 정리

### 2-1. 모듈 지도

| 모듈 | 언어 | 역할 |
|---|---|---|
| ambari-server | Java (JDK 17) | REST API, 명령 계획(ActionManager), 상태·설정 저장, 알람 집계, 업그레이드 |
| ambari-agent | Python | 호스트당 1개. 명령 스크립트 실행, 상태 점검, 알람 수집, 자가복구, Prometheus exporter |
| ambari-web/latest | React · TS · Vite | 새 프런트엔드 (2026 전환 진행 중) |
| ambari-web/classic | Ember | 기존 프런트엔드. 전환 끝나면 정리 대상 |
| ambari-admin | JS | 사용자·권한·뷰 관리 화면 |
| ambari-server-spi | Java | 업그레이드 체크·액션 확장 인터페이스(SPI) |
| ambari-serviceadvisor | Java | 서비스별 설정 추천·검증 실행기 |
| ambari-metrics | RPM | VictoriaMetrics 고정 버전 번들 (구 AMS·Ganglia 대체) |
| ambari-views · contrib | Java · JS | 플러그인 화면, 관리팩(mpack) 예시 |
| dev-support | Python · Docker | 빌드, mpack 수용 테스트, ambari-ai 도구 |

- 파일 수 약 1만 개 중 절반이 ambari-server (main java 2,200여 개)
- server 패키지 = actionmanager · agent · alerts · checks · stageplanner · topology · upgrade · state 등 30여 개

### 2-2. Stack 과 서비스 정의

- Stack = 서비스 정의 묶음 + 버전. 현재 기본 Stack 은 BIGTOP 3.2.0 / 3.3.0 / 3.4.0
- 서비스 하나 = 폴더 하나. 폴더 안 파일마다 역할이 정해져 있음

<!-- diagram: amb-stack.html -->

| 파일 | 담는 것 | 누가 읽나 |
|---|---|---|
| metainfo.xml | 컴포넌트 목록, 분류(MASTER·SLAVE·CLIENT), 카디널리티(`1+`), 명령 스크립트·타임아웃, 커스텀 명령 | Server |
| configuration/*.xml | 설정 타입(zoo.cfg, hdfs-site) 과 기본값 | Server · Web |
| service_advisor.py | 토폴로지 보고 설정 추천·검증 | Server (advisor 실행기) |
| role_command_order.json | 명령 선후 관계 | Server (RoleGraph) |
| package/scripts/*.py | INSTALL · START · STOP · STATUS 구현 | Agent |
| alerts.json | 알람 정의 (PORT · WEB · METRIC · SCRIPT · AGGREGATE) | Server → Agent |
| telemetry.json | 메트릭 경로·포맷·인증 계약 | Server (할당 컴파일러) |
| kerberos.json · quicklinks · themes | 보안 주체, UI 링크, 설정 화면 배치 | Server · Web |

#### 2-2-1. Stack 상속

- `3.3.0/metainfo.xml` 은 `<extends>3.2.0</extends>` 한 줄로 상위 버전 상속
- 3.3.0 HDFS 폴더에는 metainfo.xml 하나만 있음 → 바뀐 부분만 덮어쓰는 구조
- 단, 상속 단계가 깊어지면 실제 적용 값 추적이 어려워짐

### 2-3. 명령 실행 흐름

- 운영자 요청 1건 = Request → 여러 Stage → Stage 마다 호스트별 Task
- Stage 를 나누는 기준이 `role_command_order.json` 의 선후 그래프(RoleGraph)

<!-- diagram: amb-command.html -->

- 형식 = `"막히는 역할-명령": ["먼저 끝나야 할 역할-명령", ...]`
  - 예 : `"HBASE_MASTER-START": ["ZOOKEEPER_SERVER-START"]`
  - 정지는 반대 방향 : `"ZOOKEEPER_SERVER-STOP": ["HBASE_MASTER-STOP", ...]`
- 섹션이 조건부로 갈림 : `general_deps` 는 항상, `namenode_optional_ha` 는 HA 구성일 때만 적용
- Server ↔ Agent 는 STOMP(웹소켓 위 메시지 프로토콜) 로 명령·상태를 주고받음

> 주의 : Agent 프로세스 종료 코드 0 만으로 성공 처리하지 않음. 레포 `AGENTS.md` 가 "로그 문자열·exit code 로 업무 상태를 추론하지 말고 권위 있는 API 필드와 작업 ID 로 확인" 을 규칙으로 못박음

### 2-4. 알람 프레임워크

<!-- diagram: amb-alert.html -->

| source 타입 | 판정 방식 | 실행 위치 |
|---|---|---|
| PORT | TCP 연결 응답 시간 | Agent |
| WEB | HTTP 응답 코드·시간 | Agent |
| METRIC | JMX · 메트릭 값 임계 | Agent |
| SCRIPT | Python 스크립트 결과 | Agent |
| AGGREGATE | 하위 알람 중 비정상 비율(%) | Server |
| RECOVERY · SERVER | 자가복구 횟수, 서버 내부 상태 | Agent · Server |

- 정의마다 `reporting` 에 ok · warning · critical 문구 템플릿과 임계값을 둠
  - 예 : ZooKeeper 프로세스 알람 = PORT, 응답 1.5초 넘으면 warning
  - 예 : ZooKeeper 가용률 알람 = AGGREGATE, 비정상 35% warning · 70% critical
- 포트 같은 값은 `{{zoo.cfg/clientPort}}` 처럼 설정 참조로 씀 → 설정이 바뀌면 알람도 따라감
- 유지보수 모드(Maintenance Mode) 대상은 알림에서 빠지고 일괄 작업에서도 제외됨

### 2-5. Agent 자가복구

<!-- diagram: amb-recovery.html -->

- 목표 상태(desired) 가 STARTED 인데 현재 상태가 INSTALLED 이면 Agent 가 스스로 START 실행
- 무한 재시작을 막는 복구 예산을 둠 (`RecoveryManager.py` 코드 기본값)

| 항목 | 기본값 | 의미 |
|---|---|---|
| max_count | 6 | 창 안 최대 시도 |
| window_in_min | 60 | 창 크기(분) |
| retry_gap | 5 | 시도 간격(분) |
| max_lifetime_count | 12 | 누적 최대 시도 |

### 2-6. 2026 변화

| 변화 | 상태 (2026-11 기준) | 요점 |
|---|---|---|
| Prometheus · VictoriaMetrics 텔레메트리 | trunk 반영 | AMS·Ganglia 대체. Agent `/metrics` exporter + 컴포넌트 라우트 |
| React 프런트엔드 | 전환 진행 중 | Ember 기준선 문서와 기능 동등성 비교하며 이관 |
| Mpack V1 | 수용 테스트 진행 중 | Rocky 8 주요 경로 통과, 전체 매트릭스 미완 |
| 멀티 클러스터 통합 관리 | 목표 설계, 검증 진행 중 | 서버 1대·DB 1개로 여러 클러스터. 서버 HA 는 범위 밖 |
| AGENTS.md | trunk 반영 | AI 에이전트 작업 규칙 (결과 판정 규칙 포함) |

---

## 3. 구조 깊게 보기

### 3-1. 텔레메트리 할당 구조

- 제어(control plane) 와 데이터(data plane) 를 분리함
  - 제어 = Stack 의 `telemetry.json` + 토폴로지 + 실효 설정 → Server 가 호스트별 할당을 컴파일 → STOMP 로 배포
  - 데이터 = vmagent 가 Ambari HTTP SD 로 대상 발견 → Agent `/metrics`, `/metrics/components/{routeId}` 수집 → VictoriaMetrics
- routeId 는 Server 가 발급 → 임의 URL 프록시로 악용 불가 (모르는 경로는 404)
- Agent 는 마지막 정상 할당(last-known-good) 만 저장, 메트릭 값은 캐시하지 않음
- 라벨 수 상한을 계약으로 둠 : 프로세스·명령줄·사용자 라벨 금지, 수집기 하나 실패가 나머지를 막지 않음

### 3-2. 업그레이드 사전 점검 SPI

- `ambari-server-spi` 의 `UpgradeCheck` 인터페이스 + `UpgradeCheckRegistry` 로 체크를 등록
- 체크마다 그룹·등급·적용 조건(qualification) 을 가짐 → 업그레이드 종류에 따라 필요한 체크만 실행
- 기본 체크 예 : HostsHeartbeatCheck, ServicesUpCheck, HostMaintenanceModeCheck, PreviousUpgradeCompleted, ComponentsInstallationCheck, ConfigurationMergeCheck

### 3-3. 배치 요청 스케줄

- `request_schedules` = 여러 요청을 `order_id` 순서로 실행, 하나 실패하면 이후 배치 중단
- 롤링 재시작이 이 구조 위에 있음 (예 : NodeManager 3대씩 2배치)

---

## 4. 비교

| 도구 | 기능 | 장점 | 단점 | 언제 쓰나 |
|---|---|---|---|---|
| Ambari | 베어메탈 하둡 서비스 설치·설정·알람·업그레이드 | 선언형 Stack, 오픈소스, REST 전부 노출 | 하둡 계열 중심, 서버 단일 장애점 | Bigtop 기반 온프렘 하둡 |
| Cloudera Manager | CDP 클러스터 관리 | 상용 지원, 기능 폭 넓음 | 라이선스, 폐쇄 | CDP 사용 조직 |
| K8s Operator + ArgoCD | CR 로 서비스 상태 선언, GitOps 동기화 | 자가 치유가 기본, 버전 관리 | 노드 OS·데몬 설정은 범위 밖 | K8s 위 워크로드 |
| PEP | K8s 운영 콘솔 + 노드 설정·점검·알람 | 폐쇄망·현장 맞춤, UI-First | 서비스 정의가 코드 시드에 흩어짐 | 우리 K8s 플랫폼 |

- Ambari 와 Operator 는 같은 문제(목표 상태 수렴)를 다른 층에서 풂 → Ambari = 호스트 데몬, Operator = K8s 리소스
- PEP 의 노드 설정 영역(etcd · containerd · kubelet 데몬) 은 Ambari 쪽 문제에 가까움

---

## 5. 사용법 예시

### 5-1. 롤링 재시작 배치 등록 (REST)

```bash
# NodeManager 를 3대씩 나눠 재시작. 1배치 실패 시 2배치는 실행 안 됨
curl -u admin -X POST http://ambari:8080/api/v1/clusters/c1/request_schedules -d '[{
  "RequestSchedule": {"batch": [{"requests": [
    {"order_id": 1, "request_type": "POST", "request_uri": "/api/v1/clusters/c1/requests",
     "RequestBodyInfo": {"RequestInfo": {"context": "batch 1 of 2", "command": "RESTART",
       "service_name": "YARN", "component_name": "NODEMANAGER", "hosts": "host1,host2,host3"}}}
  ]}]}
}]'
```

### 5-2. 집계 알람 정의 (alerts.json 형식)

```json
{
  "name": "zookeeper_server_process_percent",
  "scope": "SERVICE",
  "interval": 1,
  "source": {
    "type": "AGGREGATE",
    "alert_name": "zookeeper_server_process",
    "reporting": {
      "warning":  {"text": "affected: [{1}], total: [{0}]", "value": 35},
      "critical": {"text": "affected: [{1}], total: [{0}]", "value": 70},
      "units": "%", "type": "PERCENT"
    }
  }
}
```

- K8s 매니페스트는 해당 없음 → Ambari 는 호스트에 RPM 으로 설치하는 구조

---

## 6. 실무에서 확인

### 6-1. Ambari 자체 도입은 안 맞음

- 우리 데이터 스택(StarRocks shared-data, Iceberg, Trino, Airflow, CNPG) 은 K8s 위 Operator·Helm 운영 → Ambari 관리 대상 밖
- Bigtop Stack 에 Spark · Flink · Kafka · Hive 는 있으나 Trino · StarRocks 는 없음
- 서버 1대·DB 1개 구조 → 300+ 노드 다중 클러스터에서 서버 장애가 전 클러스터 관리 중단으로 번짐
- 그래서 도구가 아니라 패턴을 PEP 로 옮김

### 6-2. PEP 적용 추천

<!-- diagram: amb-pep-map.html -->

| 순위 | 기능 | Ambari 원형 | PEP 적용 지점 |
|---|---|---|---|
| 1 | 업그레이드 사전 점검 레지스트리 | UpgradeCheck SPI | `/versions` 에 업그레이드 준비도. 노드 Ready, etcd 상태, PDB 막힘, 폐기 API, 버전 skew, 이전 작업 완료 체크를 BLOCK · WARN 등급으로 |
| 2 | 실행 순서 그래프 | role_command_order | `/k8s-services` 다중 서비스 적용을 Stage 로 분할. etcd → apiserver → controller-manager·scheduler → kubelet, 정지는 역순 |
| 3 | 유지보수 모드 | Maintenance Mode | 노드·서비스·클러스터 단위 기간 플래그 → `/alerts` 알림 억제(인박스엔 기록), `/bulk-exec`·적용 대상 기본 제외 |
| 4 | 집계 알람 | AGGREGATE | 노드 에이전트·NIC 판정을 서비스 단위 % 임계로 묶음 (kubelet 비정상 35% warn · 70% crit) |
| 5 | 재시작 대기 표시 | stale_configs | 설정 파일은 바뀌었는데 프로세스 시작 시각이 더 이름 → "재시작 필요" 배지 + 롤링 재시작 |
| 6 | 자동 복구 예산 | RecoveryManager | opt-in 조치 경로에 창·간격·누적 상한. 초과 시 알람으로 사람 호출 |
| 7 | 결과 판정 규칙 | AGENTS.md | exit code·로그 문자열로 성공 판정 금지. K8s API 필드·실행 ID 로 확인 |

- PEP 에 이미 있는 것 : 배치 적용·실패 시 중단(서비스 구성 적용), 노드 그룹(Config Group 대응), 의존 규칙(Service Advisor 대응), 알림 중복 억제
- 단, 4·6 은 노드 파라미터 에이전트 보고 주기에 의존 → 에이전트 무응답 감시와 같이 봐야 함

> 주의 : 6번 자동 복구는 장애 분석기(분석 전용) 와 분리해야 함. 분석기가 클러스터를 바꾸지 않는다는 PEP 규칙 유지

### 6-3. 폐쇄망 관점 함정

- Ambari 3.0 메트릭 번들은 VictoriaMetrics 고정 릴리스 + 체크섬 파일로 묶음 → 미러링 시 체크섬까지 같이 반입
- mpack 은 tarball 하나로 반입 가능 → 사내 Nexus raw 저장소 경유가 단순함
- 서비스 보안은 Kerberos 전제가 많고, 콘솔 로그인 문서는 LDAP · SSO 기준 → Keycloak 연동 방식은 별도 확인 필요

---

## 7. 용어 정리

- **스택(Stack)** : 서비스 정의 묶음 + 버전. 상위 버전 상속 가능
- **관리팩(Mpack)** : Stack·서비스 정의를 별도 배포하는 tarball 패키지
- **컴포넌트(Component)** : 서비스를 이루는 프로세스 단위 (NameNode, DataNode)
- **카디널리티(Cardinality)** : 컴포넌트 설치 개수 규칙 (`1`, `1+`, `0-1`)
- **RoleGraph** : role_command_order 로 만든 명령 선후 그래프
- **Stage** : 같이 실행해도 되는 Task 묶음. 앞 Stage 가 끝나야 다음 진행
- **집계 알람(AGGREGATE Alert)** : 하위 알람 비정상 비율로 판정하는 서비스 단위 알람
- **유지보수 모드(Maintenance Mode)** : 알림 억제 + 일괄 작업 제외 플래그
- **설정 그룹(Config Group)** : 일부 호스트에만 다른 설정 값을 주는 묶음
- **서비스 어드바이저(Service Advisor)** : 토폴로지 보고 설정을 추천·검증하는 모듈
- **블루프린트(Blueprint)** : 호스트 그룹 + 설정으로 클러스터를 한 번에 생성하는 템플릿
- **STOMP** : 웹소켓 위에서 쓰는 단순 메시지 프로토콜. Server ↔ Agent 통신

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 정체 | 하둡 계열 베어메탈 클러스터 설치·관리·모니터링 도구, 최신 3.0.0 |
| 구조 | Java Server 1 + Python Agent N + React Web + Stack 선언 폴더 |
| 핵심 설계 | 서비스 지식은 선언 파일, 엔진은 범용 |
| 실행 | 요청 → RoleGraph → Stage·Task → STOMP → Agent → 구조화 결과 |
| 알람 | PORT·WEB·METRIC·SCRIPT 를 Agent 가, AGGREGATE 를 Server 가 판정 |
| 자가복구 | 60분 6회·간격 5분·누적 12회 예산 |
| 2026 | VictoriaMetrics 텔레메트리, React 전환, Mpack V1, 멀티 클러스터 |
| PEP 적용 | 업그레이드 사전 점검, 실행 순서 그래프, 유지보수 모드 우선 |

**Ambari 는 그대로 들여올 도구가 아니라, 선언형 서비스 정의와 순서·알람·복구 예산 패턴을 PEP 에 옮겨 올 설계 교과서임**
