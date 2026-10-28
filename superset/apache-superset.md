## Apache Superset - 오픈소스 BI 구조와 운영

> **목표** : Superset 구조·권한 모델·K8s 배포 방식을 이해하고, 폐쇄망 Lake(StarRocks·Trino) 앞단 BI 로 올릴 때 확인할 점을 정리함

- 출처 : apache/superset 레포 (docs/admin_docs, UPDATING.md), apache/superset-kubernetes-operator 레포, Preset 6.1 릴리즈 글
- 기준 버전 : Superset 6.1.0 GA (2026-06 발표), 7.0.0rc2 투표 중 (2026-10 기준) / Operator v0.3.1 (2026-10-21)

---

## 1. 개요

- Superset = 브라우저에서 SQL·차트·대시보드를 만드는 오픈소스 BI 웹앱. Airbnb 사내 해커톤 도구로 시작, 지금은 Apache Top-Level 프로젝트
- 데이터를 직접 저장하지 않음. 차트를 열 때마다 원본 DB 로 SQL 을 보냄 → 결과를 캐시에 두고 시각화함
- 백엔드 = Python Flask + SQLAlchemy, 프론트 = React. SQLAlchemy 방언(dialect)만 있으면 거의 모든 SQL DB 에 붙음

<!-- diagram: superset-01-overview.html -->

**Superset 은 데이터를 갖지 않는 "SQL 생성기 + 캐시 + 권한 레이어" 임. 느리면 대부분 뒤의 DB 가 느린 것임**

---

## 2. 개념 정리

### 2-1. 구성 요소

| 구성 요소 | 역할 | 필수 여부 |
|---|---|---|
| 웹 앱(Web Server) | Flask API + React UI. 차트 요청 받아 SQL 생성·실행 | 필수 |
| 메타DB(Metastore) | 차트·대시보드 정의, 사용자, 권한, 로그 저장 | 필수. 운영은 PostgreSQL |
| 캐시(Redis·Valkey) | 쿼리 결과 캐시 + Celery 브로커 | 사실상 필수 |
| 워커·비트(Celery Worker·Beat) | 비동기 쿼리, 알림·리포트, 썸네일. Beat = 스케줄러 | 기능 쓰려면 필수 |
| 웹소켓 서버(Websocket) | 비동기 쿼리 결과를 브라우저로 푸시 (GAQ) | 선택 |
| MCP 서버 | AI 어시스턴트가 차트·대시보드·SQL 을 다루는 별도 프로세스 | 선택. 6.1 신규 |

- 메타DB 는 데이터 소스가 아님. 메타DB = Superset 자기 상태, 데이터 소스 = StarRocks·Trino 같은 조회 대상
- 기본 SQLite 는 운영 금지. 운영은 별도 PostgreSQL + 정기 백업

### 2-2. 객체 모델

| 객체 | 설명 | 비고 |
|---|---|---|
| 데이터베이스(Database) | SQLAlchemy URI 로 등록한 연결 1개 | 드라이버가 이미지에 있어야 함 |
| 데이터셋(Dataset) | 테이블 1개(물리) 또는 SQL 1개(가상) | 메트릭·계산 컬럼을 여기 정의 |
| 차트(Chart) | 데이터셋 1개 + 시각화 설정 | 쿼리 단위 = 차트 단위 |
| 대시보드(Dashboard) | 차트 묶음 + 네이티브 필터 | 공개 범위는 대시보드 단위로도 지정 |
| SQL Lab | 브라우저 SQL 편집기 | 결과를 바로 가상 데이터셋으로 저장 가능 |

<!-- diagram: superset-02-objects.html -->

- 권한은 데이터셋 기준이 기본임. 데이터셋 접근 권한 = 그 데이터셋을 쓰는 차트·대시보드 조회 가능
- 단, 가상 데이터셋은 SQL 을 그대로 감싸므로 RLS 적용 방식이 다름 (2-4-2)

### 2-3. 차트 한 개가 그려지는 흐름

<!-- diagram: superset-03-query.html -->

- 1 대시보드 열림 → 차트마다 `/api/v1/chart/data` 호출
- 2 권한 확인 → 데이터셋 접근 권한 없으면 여기서 거부
- 3 SQL 생성 → 메트릭·필터·RLS 조건을 붙여 DB 방언 SQL 로 컴파일
- 4 캐시 확인 → 같은 쿼리 결과가 캐시에 있으면 DB 안 감
- 5 DB 실행 → 결과를 캐시에 저장 → 브라우저에서 렌더
- 비동기 모드(GAQ)면 4~5 를 Celery 워커가 처리하고 웹소켓·폴링으로 결과를 받음

### 2-4. 권한 모델

#### 2-4-1. 기본 역할

| 역할 | 할 수 있는 것 | 주의 |
|---|---|---|
| Admin | 전부. 권한 부여·회수 포함 | 모든 DB 접근 |
| Alpha | 모든 데이터 소스 접근, 자기 객체만 수정 | 권한 부여는 못 함 |
| Gamma | 접근 허락된 데이터셋 기반 차트·대시보드만 조회 | 데이터 권한 별도 부여 필요 |
| sql_lab | SQL Lab 사용 | DB 단위 접근 권한 따로 줘야 함 |
| Public | 비로그인 사용자 | 기본 데이터 접근 없음 |

- 기본 역할은 `superset init` 때 권한이 다시 동기화됨 → 직접 고친 내용이 업그레이드 때 덮어써짐. 커스텀은 복사한 새 역할에 할 것
- 6.x 부터 주체(Subject) 개념 = User · Group · Role. 리소스별 편집자·조회자는 Group 으로 주는 게 권장임. Role = "무엇을 할 수 있나", Group = "누구인가"

#### 2-4-2. 행 수준 보안(RLS)

| 항목 | 내용 |
|---|---|
| Regular 필터 | 지정한 주체에게만 WHERE 조건 추가 |
| Base 필터 | 지정한 주체를 뺀 모두에게 조건 추가. `1 = 0` 이면 기본 차단 |
| 그룹 키 | 같은 키 = OR, 다른 키 = AND |
| Jinja | `ENABLE_TEMPLATE_PROCESSING` 켜면 `{{ current_username() }}` 사용 가능 |

<!-- diagram: superset-04-auth.html -->

> 주의 : RLS 는 Superset 이 만든 SQL 에만 붙음. SQL Lab 직접 쿼리는 RLS 대상이 아님 → 민감 데이터는 DB 계정 권한(StarRocks RBAC 등)으로 한 번 더 막아야 함

---

## 3. 배포 구조 - Helm 차트에서 Operator 로

| 항목 | Helm 차트 (`helm/superset`) | Superset Operator |
|---|---|---|
| 상태 | 6.1 문서까지 공식. master(7.0) 문서에서 deprecated | 신규 권장. API 는 아직 `v1alpha1` |
| 단위 | values.yaml + configOverrides | `Superset` CR 1개 |
| DB 마이그레이션 | init Job 훅 | 이미지 태그 바뀌면 migrate Job 자동 실행 |
| 비밀값 | values 또는 Secret | 운영 모드에서 인라인 금지, `*From` 으로 Secret 참조 강제 |
| 운영 기능 | 수동 구성 | HPA, PDB, NetworkPolicy, ServiceMonitor, Gateway API 내장 |
| MCP | 직접 구성 | `mcpServer: {}` 한 줄 |

<!-- diagram: superset-05-operator.html -->

- Operator 는 CR 하나로 web · celeryWorker · celeryBeat · celeryFlower · websocketServer · mcpServer 를 각각 Deployment 로 만듦
- 설정은 체크섬 기반 롤아웃 → config 바뀌면 해당 컴포넌트만 재기동
- 테스트된 K8s = 1.35~1.37. CEL 검증 때문에 실사용 하한 = 1.25

> 주의 : 이미지 태그를 `latest` 같은 가변 태그로 쓰면 migrate Job 이 안 돔. Operator 는 `repository:tag` 문자열 변화로 마이그레이션 여부를 판단함 → 반드시 고정 태그

---

## 4. 대안 비교

| 도구 | 장점 | 단점 | 언제 쓰나 |
|---|---|---|---|
| Superset | DB 지원 폭 넓음, SQL Lab, RLS, 시각화 종류 많음, Apache 라이선스 | 초기 설정·운영 부담 큼, 학습 곡선 | 사내 공용 BI, 분석가 다수, 멀티 DB |
| Metabase | 설치 쉬움, 비개발자용 질문 빌더 | 고급 권한·RLS·SSO 는 유료판 위주 | 소규모 팀, 빠른 셀프서비스 |
| Grafana | 시계열·모니터링 최강, 알람 | BI 용 탐색·피벗은 약함 | 메트릭·로그 대시보드 |
| Redash | 가볍고 SQL 중심 | 기능 확장 속도 느림 | 단순 SQL 공유 |
| 상용 BI (Tableau 등) | 완성도, 지원 | 비용, 폐쇄망 라이선스 관리 | 경영 보고, 지원 계약 필요 시 |

- 우리 환경 기준 = 이미 Grafana 는 인프라 모니터링에 있음. Superset 은 Lake 데이터 분석 BI 용으로 역할이 겹치지 않음

---

## 5. 사용법 예시

### 5-1. Operator 설치

```bash
# 폐쇄망 : 차트·이미지를 dmz-nexus 로 미러링 후 레지스트리 주소만 바꿔서 설치
helm install superset-operator \
  oci://ghcr.io/apache/superset-kubernetes-operator/charts/superset-operator \
  --version 0.3.1 \
  --namespace superset-operator-system --create-namespace
```

### 5-2. 드라이버 포함 이미지

```dockerfile
# 공식 이미지는 PostgreSQL 드라이버 정도만 있음 → 조회 대상 DB 드라이버를 추가해 사내 이미지로 빌드
FROM apache/superset:6.1.0
USER root
RUN uv pip install --no-cache starrocks mysqlclient trino
USER superset
```

- 빌드 전에 pip 프록시(Nexus) 를 `UV_INDEX_URL` 로 지정해야 폐쇄망에서 받아짐
- 위 Dockerfile 은 개념 코드임. 6.1 이미지의 패키지 설치 방식(uv · venv 경로)은 빌드 전에 확인할 것

### 5-3. Superset CR (운영 모드)

```yaml
apiVersion: superset.apache.org/v1alpha1
kind: Superset
metadata:
  name: superset
  namespace: bi
spec:
  image:
    repository: nexus.internal/superset   # 사내 미러 이미지
    tag: "6.1.0-lake1"                     # 고정 태그
  secretKeyFrom:                           # SECRET_KEY 는 Secret 참조만 허용
    name: superset-secret
    key: secret-key
  metastore:
    uriFrom:                               # CNPG 가 만든 접속 Secret
      name: superset-pg-app
      key: uri
  valkey:
    host: valkey.bi.svc                    # 캐시 + Celery 브로커 + 결과 저장
    passwordFrom:
      name: valkey-credentials
      key: password
  featureFlags:
    ENABLE_TEMPLATE_PROCESSING: true       # RLS Jinja 용
    ALERT_REPORTS: true
  webServer: {}
  celeryWorker: {}
  celeryBeat: {}
```

### 5-4. Keycloak SSO 연결 (개념 코드)

```python
# superset_config.py 일부 - 그룹 클레임으로 역할 매핑
from flask_appbuilder.security.manager import AUTH_OAUTH

AUTH_TYPE = AUTH_OAUTH
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = "Public"     # 매핑 안 된 사용자는 최소 권한
AUTH_ROLES_SYNC_AT_LOGIN = True             # 로그인마다 그룹 → 역할 재동기화
AUTH_ROLES_MAPPING = {
    "superset_admins": ["Admin"],
    "superset_analysts": ["Alpha", "sql_lab"],
    "superset_viewers": ["Gamma"],
}
OAUTH_PROVIDERS = [{
    "name": "keycloak",
    "token_key": "access_token",
    "remote_app": {
        "client_id": "superset",
        "client_secret": "<Secret 에서 주입>",
        "server_metadata_url": "https://keycloak.internal/realms/lake/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email profile"},
    },
}]
```

- 그룹 정보를 userinfo 에서 읽는 커스텀 SecurityManager 가 필요함. 공식 문서 Keycloak 예시(PKCE + 그룹 매핑)를 기준으로 붙일 것

### 5-5. StarRocks · Trino 연결 URI

```text
starrocks://<user>:<password>@<fe-host>:9030/<catalog>.<database>
trino://<user>@<trino-host>:<port>/<catalog>
```

---

## 6. 실무에서 확인

### 6-1. 폐쇄망 이미지

- 공식 이미지에 조회 대상 DB 드라이버가 없음 → StarRocks · Trino 드라이버 넣은 사내 이미지 필수
- 7.0 부터 스크린샷이 Playwright + Chromium 전용. Selenium · Firefox 설정 키 삭제됨 → 알림·리포트 쓰면 Chromium 포함 이미지인지 확인
- 7.0 기본 이미지는 Chromium 포함이라 더 커짐 → Nexus 저장 용량·풀 시간 고려
- Operator 이미지 · 차트(OCI) · Valkey · CNPG 이미지까지 미러링 목록에 넣을 것
- 지도 차트(Mapbox · 타일)는 외부 호출임 → 폐쇄망에서는 내부 타일 서버 없으면 꺼둘 것

### 6-2. 멀티테넌트 권한 (사용자 ~1,000명)

- 사용자별 네임스페이스 구조와 Superset 권한은 별개임. Superset 은 인스턴스 1개 안에서 데이터셋 권한 + RLS 로 나눔
- Keycloak 그룹 → Superset 역할은 "능력" 만 매핑. 팀별 대시보드 공유는 Superset Group 으로 줄 것
- 기본 역할(Gamma 등) 직접 수정 금지. 업그레이드 `superset init` 에서 덮어써짐
- SQL Lab 은 RLS 우회 경로임 → SQL Lab 허용 역할은 최소화. DB 계정도 팀별로 분리

### 6-3. 데이터 소스 연결

- StarRocks shared-data = MySQL 프로토콜(9030) 로 연결. 외부 카탈로그(Iceberg)는 `catalog.database` 로 지정
- Trino = Iceberg · Hive 횡단 조회용. 무거운 대시보드는 StarRocks 머티리얼라이즈드 뷰로 빼는 게 나음
- Superset 쿼리 타임아웃(웹 30~60초)보다 긴 쿼리는 비동기(Celery)로 돌려야 함 → 안 그러면 게이트웨이 타임아웃
- 대시보드 1개 = 차트 N개 동시 쿼리 → 필터 바꿀 때마다 StarRocks FE 에 동시 부하. 캐시 TTL 과 StarRocks 리소스 그룹 같이 설계

### 6-4. 메타DB · 캐시

- 메타DB = CNPG PostgreSQL 클러스터. Operator 문서도 CNPG 연동을 예시로 듦
- 메타DB 백업이 곧 대시보드 백업임. CNPG 백업 대상을 AIStor(S3) 로 두면 기존 체계 재사용 가능
- Valkey 는 캐시 + 브로커 겸용. 장애 시 비동기 쿼리·리포트 전부 멈춤 → 최소 레플리카 구성

### 6-5. 버전 업그레이드 함정

- 6.1 → 7.0 : Python 3.11 이상 필요, Selenium 제거, 일부 URL 라우트 접두어 제거(북마크 깨짐), CSS 변수 기본 활성화
- 메타DB 스키마 마이그레이션은 되돌리기 어려움 → 업그레이드 전 CNPG 백업 필수
- Helm 차트로 이미 운영 중이면 Operator 마이그레이션 가이드를 먼저 볼 것. 7.0 과 Operator 전환을 한 번에 하지 말고 나눠서 진행
- Operator 는 `v1alpha1` → CRD 스키마가 릴리즈마다 바뀔 수 있음. 운영 반영 전 스테이징에서 CR 검증

### 6-6. MCP (AI 연동)

- 6.1 에서 MCP 서버 추가. AI 클라이언트가 데이터셋 조회, 차트 생성, SQL 실행 가능
- 폐쇄망이면 외부 AI 클라이언트 연결 자체가 막힘 → 내부 LLM(Lake GPU 서빙) 과 붙일 때만 의미 있음
- MCP 는 Superset RBAC 를 그대로 따름. 단, SQL 실행 도구는 SQL Lab 과 같은 RLS 우회 위험이 있음

---

## 7. 용어 정리

- **메타DB(Metastore)** : Superset 자신의 상태(차트·대시보드·권한) 저장 DB
- **데이터셋(Dataset)** : 차트의 입력. 물리 테이블 또는 가상 SQL
- **SQL Lab** : 브라우저 SQL 편집기
- **RLS(Row Level Security)** : 주체별로 WHERE 조건을 자동 추가하는 행 단위 제한
- **주체(Subject)** : 권한을 받는 대상. User · Group · Role
- **GAQ(Global Async Queries)** : 차트 쿼리를 워커가 비동기로 처리하는 모드
- **Celery Beat** : 알림·리포트 스케줄러
- **기능 플래그(Feature Flag)** : `FEATURE_FLAGS` 로 켜고 끄는 실험·선택 기능
- **SQLAlchemy 방언(Dialect)** : DB 별 SQL 차이를 흡수하는 드라이버 계층
- **Superset CR** : Operator 가 읽는 커스텀 리소스. 배포 전체를 정의
- **MCP(Model Context Protocol)** : AI 클라이언트가 도구를 호출하는 표준 프로토콜
- **GTF(Global Task Framework)** : 6.1 신규 비동기 작업 추적·취소 프레임워크. 기본 꺼짐

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 정체 | 데이터를 저장하지 않는 SQL 생성 · 캐시 · 권한 레이어 BI |
| 구성 | Web + 메타DB(PG) + Valkey + Celery Worker·Beat, 선택으로 Websocket · MCP |
| 객체 | Database → Dataset → Chart → Dashboard |
| 권한 | 데이터셋 권한이 기본, RLS 로 행 제한, Group 으로 공유 |
| 배포 | 6.1 까지 Helm, 7.0 문서부터 Operator(v1alpha1) 권장 |
| 폐쇄망 | 드라이버 포함 사내 이미지, 7.0 은 Chromium 포함 |
| 함정 | SQL Lab 은 RLS 우회, 가변 태그면 마이그레이션 안 돔 |

**Superset 성능은 StarRocks 가, 보안은 데이터셋 권한과 DB 계정이 결정함**

관련 글 : StarRocks ① 개념과 아키텍처 · StarRocks ④ k8s 배포 설정과 흐름 · 데이터 엔지니어링 맛보기
