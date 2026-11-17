## StarRocks Arrow Flight - 내부 1초 vs 외부 10초 원인 분석

> **목표** : StarRocks Arrow Flight SQL 로 내부 조회는 10초 → 1초로 줄었는데 외부 조회만 10초 그대로인 원인을 경로별로 쪼개서 판별하고, Gateway API 전환 시 노출 구조를 정함

- 출처 : StarRocks 공식 문서(Arrow Flight SQL, Arrow Flight SQL Best Practices), Kubernetes 블로그(Ingress NGINX Retirement), Gateway API v1.5 릴리즈 노트, Cilium 1.20 릴리즈 소식(InfoQ), NGINX gRPC 모듈 문서
- 기준 버전 : StarRocks 4.1.7, Apache Arrow 26.0.1, Cilium 1.20.4, Gateway API v1.7.0 (2026-11 기준 최신 태그 확인)

---

## 1. 개요

Arrow Flight 는 Arrow 컬럼 포맷 데이터를 gRPC 로 그대로 주고받는 RPC 프레임워크임. Flight SQL 은 그 위에 SQL 실행·메타데이터 조회를 표준화한 것. StarRocks 는 v3.5.1 부터 지원함.

<!-- diagram: af-01-overview.html -->

- Client → FE `GetFlightInfo` → Endpoint · Ticket 수신 → `DoGet` 으로 Arrow 배치 스트림 수신
- 행 ↔ 컬럼 변환이 없어서 대용량 결과셋에서 효과가 큼

현재 상황은 아래와 같음.

| 구분 | 결과 |
|---|---|
| 기존 MySQL 프로토콜 | 10초 |
| Arrow Flight, 클러스터 내부 Pod | 1초 |
| Arrow Flight, 클러스터 외부 | 10초 (변화 없음) |

**내부에서 1초가 나온다는 건 Arrow Flight 자체는 정상이라는 뜻이고, 문제는 외부에만 붙는 경로에 있다.**

## 2. 개념 정리

### 2-1. MySQL 프로토콜 vs Arrow Flight

<!-- diagram: af-02-row-vs-col.html -->

| 항목 | MySQL 프로토콜 | Arrow Flight SQL |
|---|---|---|
| 전송 단위 | 행 | 컬럼 배치(RecordBatch) |
| 직렬화 | BE 컬럼 → 행 바이트 → 클라에서 다시 컬럼 | 포맷 그대로 전송 |
| 전송 계층 | TCP 9030 | gRPC · HTTP/2 (FE 9408, BE 9419) |
| 병렬 수신 | 불가 | Endpoint 여러 개로 가능 |
| 압축 | 없음 | 없음 (StarRocks 설정 미지원) |

- 공식 벤치마크 기준 Python `pd.read_sql` 은 ADBC 가 PyMySQL 대비 19~97배 빠름
- 단, 벤치마크 환경은 클라이언트와 클러스터가 같은 서브넷임 → 네트워크 구간 영향은 빠져 있음

### 2-2. FE 프록시 모드

- `arrow_flight_proxy_enabled` 기본값 = true
- 켜져 있으면 BE 데이터를 FE 가 받아서 클라이언트로 넘김 → BE 에 직접 못 붙는 K8s · 사설망용
- `arrow_flight_proxy` 를 비우면 클라이언트가 처음 붙은 FE 가 프록시 역할
- 공식 문서 기준 오버헤드 = BE 직결 대비 처리량 8~10% 감소
- `SET GLOBAL` 로만 설정 가능, 새 세션부터 적용

> 주의 : 프록시가 기본 ON 이라 내부 1초 요청도 FE 프록시를 타고 있을 가능성이 높음. 그렇다면 10배 차이의 주범은 프록시가 아님

### 2-3. HTTP/2 flow control

- gRPC 는 HTTP/2 스트림 단위로 윈도우(받을 수 있는 양)를 광고함
- 처리량 상한 ≈ 윈도우 크기 ÷ RTT → RTT 가 큰 외부 구간에서 단일 스트림 속도가 묶임
- L7 프록시를 끼우면 프록시 양쪽에 HTTP/2 세션이 따로 생겨서 버퍼·윈도우가 한 번 더 걸림

## 3. 내부 vs 외부 경로 비교

<!-- diagram: af-03-in-vs-ex.html -->

| 구간 | 내부 (1초) | 외부 (10초) |
|---|---|---|
| 진입 | Pod → FE ClusterIP | 사용자망 → Cilium LB → ingress-nginx |
| 프로토콜 처리 | HTTP/2 세션 1개, 끝단 간 직결 | nginx 에서 TLS 종단, HTTP/2 재조립 후 재전송 (세션 2개) |
| 버퍼 | 영향 거의 없음 | nginx `grpc_buffer_size` 기본 32k |
| 네트워크 | 클러스터 내부 고대역 · 저지연 | 방화벽 · 외부망 구간, RTT 큼 |
| 데이터 경로 | FE 프록시 (기본 ON) | FE 프록시 + nginx + LB |
| 압축 | 없음 | 없음 → 원본 크기 그대로 외부 대역폭 소모 |

원인 후보는 3개임.

1. ingress-nginx : L7 재인코딩, 작은 gRPC 버퍼, Pod CPU limit 으로 대용량 스트림 처리량 제한 (가장 유력)
2. 외부망 대역폭 · RTT : 결과 크기 ÷ 10초 가 외부 회선 속도와 비슷하면 이쪽
3. FE 프록시 집중 : 내부도 프록시를 타고 있다면 8~10% 수준이라 주범 아님

## 4. 원인 판별과 노출 방식 비교

### 4-1. 4경로 비교 테스트

| # | 경로 | 보는 것 |
|---|---|---|
| A | 내부 Pod → FE ClusterIP | 기준선 (현재 1초) |
| B | 내부 Pod → nginx LB IP → FE | 외부망을 뺀 nginx 영향 |
| C | 외부 → 임시 L4 LB (Cilium) → FE 9408 | nginx 를 뺀 외부망 영향 |
| D | 외부 → nginx → FE | 현재 상태 (10초) |

<!-- diagram: af-04-diagnose.html -->

- B 느림, C 빠름 → nginx 원인. Gateway API(Envoy) 나 L4 분리로 해결됨
- B 빠름, C ≈ D 느림 → 외부망 원인. Gateway API 로 바꿔도 그대로다
- 전송 중 클라이언트에서 `ss -tn | grep -E '9408|9419|443'` → 실제 데이터가 FE 로 오는지 BE 로 오는지 확인

### 4-2. 노출 방식 비교

| 방식 | 장점 | 단점 | 언제 쓰나 |
|---|---|---|---|
| ingress-nginx (L7) | 기존 구성 그대로, annotation 으로 gRPC 지원 | 재인코딩 · 버퍼 튜닝 필요, 2026-03 유지보수 종료 | 전환 전 임시 |
| Cilium Gateway API GRPCRoute (L7, Envoy) | 표준 리소스, 인증 · 라우팅 기능 | L7 재처리는 여전히 있음, TLS 리스너는 ALPN 설정 필요 | 웹 UI · 일반 gRPC API |
| L4 직노출 (LB Service · TCPRoute) | 프록시 오버헤드 없음, eBPF 포워딩 | 인증은 StarRocks 에 의존, 라우팅 기능 없음 | Arrow Flight 처럼 대용량 스트림 |
| BE 별 LB IP (선택) | 프록시 우회, BE 병렬 수신 | BE 광고 주소 · DNS 정리 필요 | 처리량을 끝까지 뽑아야 할 때 |

- GRPCRoute = Gateway API v1.1 부터 Standard(GA)
- TLSRoute = Gateway API v1.5 에서 GA
- Cilium 1.20 = Gateway API 1.6 지원, TCPRoute · UDPRoute 추가

### 4-3. 권장 구조

<!-- diagram: af-05-target.html -->

- 웹 UI · HTTP API = Cilium Gateway HTTPRoute 로 이전
- Arrow Flight = L7 기능이 필요 없는 트래픽 → **Flight 포트만 L4 전용 LB IP 로 분리**
- FE 가 여러 대면 ticket 이 처음 붙은 FE 를 거치므로 `sessionAffinity: ClientIP` 로 세션 고정
- 처리량이 더 필요하면 BE 별 LB IP 와 프록시 OFF 를 검토함

## 5. 사용법 예시

### 5-1. 처리량 측정 (Python ADBC)

```bash
pip install adbc_driver_manager adbc_driver_flightsql pyarrow
```

```python
import time
import adbc_driver_flightsql.dbapi as fs

# 경로별로 주소만 바꿔서 A~D 측정
conn = fs.connect("grpc://<주소>:9408",
                  db_kwargs={"username": "user", "password": "pass"})
cur = conn.cursor()
t = time.time()
cur.execute("SELECT * FROM db.tbl WHERE dt = '2026-11-01'")
tb = cur.fetch_arrow_table()
dt = time.time() - t
# 시간뿐 아니라 MB/s 를 같이 봐야 회선 한계인지 판별 가능
print(f"{dt:.2f}s, {tb.nbytes/1e6:.0f}MB, {tb.nbytes/1e6/dt:.0f}MB/s")
```

### 5-2. C 테스트용 임시 L4 Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: sr-fe-flight-l4-test
  namespace: starrocks
spec:
  type: LoadBalancer            # Cilium LB-IPAM 이 IP 할당
  externalTrafficPolicy: Local  # 노드 간 추가 홉 제거
  sessionAffinity: ClientIP     # 같은 FE 로 고정
  selector:                     # 기존 FE svc selector 그대로 복사
    app.kubernetes.io/component: fe
  ports:
    - name: flight
      port: 9408
      targetPort: 9408
```

### 5-3. ingress-nginx 임시 완화

```yaml
# ingress-nginx-controller ConfigMap
data:
  grpc-buffer-size-kb: "1024"   # 기본 32k → 대용량 Arrow 배치 대응
```

- Ingress 에는 `nginx.ingress.kubernetes.io/backend-protocol: "GRPC"` 필요

### 5-4. Gateway API 전환 후 Flight L4 라우팅 (개념 코드)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: sr-flight-gw
  namespace: starrocks
spec:
  gatewayClassName: cilium
  listeners:
    - name: flight
      protocol: TCP
      port: 9408
---
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TCPRoute
metadata:
  name: sr-fe-flight
  namespace: starrocks
spec:
  parentRefs:
    - name: sr-flight-gw
      sectionName: flight
  rules:
    - backendRefs:
        - name: starrocks-fe-service   # FE svc 이름 확인
          port: 9408
```

> 주의 : TCPRoute 는 Experimental 채널 CRD 임. Cilium 1.20 미만이면 TCPRoute 를 지원하지 않으므로 LB Service 로 직접 노출함

## 6. 실무에서 확인

- 프록시 상태 : `SHOW VARIABLES LIKE 'arrow_flight_proxy%'` 로 ON/OFF 와 프록시 주소 확인. 내부 1초 요청이 프록시를 탔는지부터 확정함
- nginx 리소스 : 전송 중 `kubectl top pod -n ingress-nginx` 로 CPU 가 limit 에 붙는지 확인. TLS 와 HTTP/2 재조립 부하가 몰리는 구간임
- nginx 로그 : `$request_time`, `$bytes_sent` 로 처리량 계산 → C 테스트 결과와 비교
- 외부망 : 외부 client ↔ LB IP 구간 `iperf3` 측정. 방화벽 DPI · 세션 검사 장비가 gRPC 스트림 처리량을 깎는지 확인
- Cilium LB : `externalTrafficPolicy: Cluster` 면 다른 노드의 nginx Pod 로 한 번 더 넘어감 → Local 로 맞춤
- 멀티테넌트 : Flight 포트를 L4 로 열면 인증은 StarRocks 계정에만 의존함. 사용자망 대역만 허용하는 CiliumNetworkPolicy 를 같이 걸어둠
- FE 이중화 : ticket 이 처음 붙은 FE 로 묶이므로 LB 분산 시 세션 고정 필수
- 업그레이드 : ingress-nginx 는 2026-03 이후 보안 패치가 없음 → Flight 분리는 Gateway 전환과 같이 진행하는 게 효율적
- 전송량 : 외부망이 원인이면 컬럼 축소 · 서버 측 집계 · 파티션 조건으로 결과 크기를 줄이는 게 유일한 해법

## 7. 용어 정리

- **Arrow Flight** : Arrow 컬럼 데이터를 gRPC 로 주고받는 RPC 프레임워크
- **Flight SQL** : Flight 위에 SQL 실행 · 메타데이터 조회를 표준화한 프로토콜
- **ADBC(Arrow Database Connectivity)** : Arrow 네이티브 DB 드라이버 표준, JDBC/ODBC 대체 목적
- **FlightInfo** : 쿼리 결과를 받을 Endpoint 목록과 Ticket 을 담은 응답
- **Ticket** : DoGet 호출 시 어떤 결과를 받을지 지정하는 토큰
- **DoGet** : Ticket 으로 Arrow 배치 스트림을 받는 RPC
- **RecordBatch** : 같은 스키마의 컬럼 묶음, Arrow 전송 단위
- **FE 프록시 모드** : FE 가 BE 데이터를 중계하는 StarRocks 기능, 기본 ON
- **HTTP/2 flow control** : 스트림별 수신 윈도우로 송신량을 제한하는 메커니즘
- **GRPCRoute** : Gateway API 의 gRPC 라우팅 리소스, v1.1 부터 GA
- **TCPRoute** : Gateway API 의 L4 TCP 라우팅 리소스, Experimental
- **LB-IPAM** : Cilium 이 LoadBalancer Service 에 IP 를 할당하는 기능

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 현상 | 내부 1초, 외부 10초 (MySQL 프로토콜 시절과 동일) |
| 의미 | Arrow Flight 는 정상, 외부 경로가 병목 |
| 원인 후보 | ingress-nginx L7 재처리 · 외부망 대역폭 · FE 프록시 순 |
| 판별 | 외부 → 임시 L4 LB → FE 9408 로 C 테스트, MB/s 와 iperf3 비교 |
| nginx 원인이면 | Flight 포트를 L4 로 분리, 임시로 grpc 버퍼 확대 |
| 외부망 원인이면 | 전송량 축소, Gateway 전환으로는 해결 안 됨 |
| 전환 방향 | 웹 UI = Gateway HTTPRoute, Flight = L4 전용 LB IP 와 세션 고정 |

**Arrow Flight 는 L7 기능이 필요 없는 대용량 스트림이라, Gateway API 로 넘어가더라도 L4 로 따로 빼는 게 맞다.**

관련 글 : StarRocks ① 개념과 아키텍처
