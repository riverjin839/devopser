## LLM 인가와 팀 데이터 격리 - Token Exchange · Kata Containers

> **목표** : 팀 공용 LLM 위키에서 ERP·재무·보안 데이터를 섞지 않고 쓰는 인증·인가·격리 구조 정리

- 출처 : RFC 8693 (OAuth 2.0 Token Exchange), Keycloak 공식 문서·블로그, Kata Containers 문서
- 기준 버전 : Keycloak 26.8.2, Kata Containers 4.3.1 (2026-11 기준)

---

## 1. 개요

- 개인용 LLM 위키를 팀 공용으로 넓히면 바로 권한 문제가 생김
- 팀마다 민감 데이터가 다름 → ERP 팀 = 주문·원가, 재무팀 = 손익·계좌, 보안팀 = 취약점·로그
- LLM 은 컨텍스트에 들어온 걸 전부 읽고 답함. 권한 판단 기능이 없음
- 프롬프트에 "재무팀 아니면 답하지 마" 를 넣는 건 통제가 아님 → 프롬프트 주입(prompt injection) 한 번에 뚫림

<!-- diagram: llm-authz-overview.html -->

**LLM 은 신뢰할 수 없는 계산기로 보고, 권한은 모델에 들어가기 전 게이트웨이에서 사용자 토큰 기준으로 강제함**

## 2. 개념 정리

### 2-1. 인증과 인가를 어디서 하나

| 단계 | 담당 | 하는 일 |
| --- | --- | --- |
| 인증(Authentication) | Keycloak (OIDC) | 로그인, JWT 발급, 그룹 claim (`finance`, `erp`, `sec`) |
| 인가(Authorization) | LLM 게이트웨이 | JWT 검증, 검색 필터·툴 호출 권한 결정 |
| 원천 권한 | ERP·재무 시스템 | 교환된 토큰으로 자기 권한 체계대로 재검증 |
| 모델 | vLLM 등 추론 서버 | 걸러진 컨텍스트로 생성만 함. 권한 판단 없음 |

### 2-2. 인가를 강제할 지점 4곳

- **검색(Retrieval)** : 문서 청크마다 `team`, `classification` 메타데이터를 붙임 → 검색 쿼리에 사용자 claim 기반 필터를 강제함
- **툴 호출(Tool / MCP)** : ERP API 같은 원천 시스템은 사용자 권한으로 호출함. 서비스 계정 슈퍼 권한 금지
- **캐시·대화 메모리** : 시맨틱 캐시(semantic cache), 대화 히스토리 키에 user·team 을 넣음. 공유되면 여기서 샘
- **출력(Output)** : 계좌번호·주민번호 패턴 마스킹(DLP), 질의·참조 청크 감사 로그

> 주의 : 파인튜닝·시스템 프롬프트에 민감 데이터를 넣으면 안 됨. 가중치에 들어간 데이터는 지울 수도, 권한을 걸 수도 없음. 팀 데이터는 RAG 로만 넣음

### 2-3. 격리 수준 단계

| 수준 | 방식 | 장점 | 단점 | 언제 쓰나 |
| --- | --- | --- | --- | --- |
| 개인 | 사용자 namespace 샌드박스 | 본인 외 경로 없음 | 사용자 수만큼 자원 | 개인 메모·초안·업로드 |
| L1 | 메타데이터 필터 | 구성 단순, 인덱스 하나 | 필터 누락 버그 한 번이면 노출 | 사내 공개 문서 |
| L2 | 팀별 컬렉션·인덱스 | 쿼리 실수에도 범위 제한 | 컬렉션 수 증가 | ERP 일반 데이터 |
| L3 | 팀별 namespace와 별도 DB | 네트워크 정책으로 물리 차단 | 운영 대상 증가 | 재무 데이터 |
| L4 | 전용 인스턴스·전용 모델 엔드포인트 | 공유 자원 없음 | 비용 최대 | 보안팀 데이터 |

<!-- diagram: llm-authz-tenant-layout.html -->

- 추론 서버는 공용으로 두되 **상태 없음(stateless)** 으로 운영함. 데이터 접근 권한은 게이트웨이와 팀별 retriever 만 가짐

### 2-4. 개인 데이터는 개인 샌드박스로

- 팀 데이터와 개인 데이터는 성격이 다름 → 팀 = 여러 명이 읽는 공유 자산, 개인 = 본인만 쓰는 메모·초안·업로드 파일
- 개인 데이터까지 팀 위키에 섞으면 권한 경계가 흐려짐 → 개인 위키·개인 컬렉션은 사용자별 샌드박스 안에만 둠
- 샌드박스 = 사용자 namespace 와 Kata 파드, 개인 벡터 컬렉션, 개인 버킷 묶음
- 게이트웨이는 토큰 sub 로 본인 샌드박스에만 라우팅함. 다른 사용자 샌드박스로 가는 경로 자체가 없음
- 팀 위키는 샌드박스에서 팀 claim 으로 읽기 전용 참조만 함
- 개인 위키 내용을 팀에 공유하려면 승격 절차를 거침 → 공유 요청 → 팀 리뷰 → 팀 위키로 반영

<!-- diagram: llm-authz-personal-sandbox.html -->

| 구분 | 개인 샌드박스 | 팀 위키 |
| --- | --- | --- |
| 소유 | 사용자 본인 | 팀 |
| 위치 | 사용자 namespace, 개인 컬렉션·버킷 | 팀 namespace, 팀 컬렉션·DB |
| 접근 | sub 일치 시 읽기·쓰기 | 팀 claim 일치 시 읽기 |
| 실행 | 코드 실행은 샌드박스 안에서만 | 코드 실행 없음 |
| 공유 | 승격 절차로만 팀에 반영 | 팀원 전체 공유 |

**개인 데이터는 본인 샌드박스 밖으로 나가지 않고, 팀으로 갈 때는 리뷰를 거친 승격만 허용함**

> 주의 : 개인 샌드박스에서 팀 위키를 참조한 답변을 그대로 개인 위키에 저장하면 팀 데이터 사본이 생김. 팀 권한이 빠진 뒤에도 남음 → 개인 위키에는 팀 문서 링크만 남기고 원문 청크는 저장하지 않음

### 2-5. 사용자 1만 명 규모 확장

- 병목은 위키 자체가 아니라 **추론 서버 동시 처리량**임. 게이트웨이·retriever 는 상태 없는 웹 서비스라 수평 확장이 쉬움
- 1만 명이 동시에 쓰진 않음 → 동시 요청 수를 먼저 추정함 (예 : 동시 접속 5% = 약 500 세션). 레플리카 수는 이 값과 GPU 당 처리량 실측으로 정함
- 추론 서버는 여러 레플리카 풀로 띄우고 앞에 LB 를 둠. 단, 라운드로빈 LB 로는 부족함
- 추론 인지 라우팅(inference-aware routing) = KV 캐시·프리픽스 캐시 적중, 대기열 길이를 보고 레플리카를 고름 → llm-d, Envoy AI Gateway 같은 Gateway API Inference Extension 구현체
- 위키 질의는 같은 시스템 프롬프트·같은 문서 청크가 반복됨 → 프리픽스 캐시 효과가 큼

<!-- diagram: llm-authz-scale-out.html -->

| 계층 | 확장 방식 | 기준 지표 |
| --- | --- | --- |
| 게이트웨이 | HPA 수평 확장 | CPU, 요청 수 |
| Retriever·벡터 DB | 팀별 레플리카, 읽기 복제본 | 검색 지연 |
| 추론 라우터 | 레플리카 2개 이상 | 대기열, KV 캐시 적중 |
| vLLM 풀 | 레플리카 오토스케일 | 대기열 길이, KV 캐시 사용률 |
| 개인 샌드박스 | 질의 시 기동, 유휴 시 축소 | 활성 세션 수 |

- 게이트웨이에 사용자·팀별 rate limit 과 토큰 쿼터를 둠 → 한 팀이 GPU 를 독점하지 못하게 함
- 등급별로 풀을 나눌 수도 있음 → 일반 풀 공유, 보안팀은 전용 풀 (2-3 의 L4)

> 주의 : 프리픽스 캐시는 레플리카 메모리에 남음. 팀 간 같은 레플리카를 쓰면 캐시 자체는 공유되지만 응답은 요청별 컨텍스트로만 만들어짐. 보안 등급이 다른 데이터는 풀을 분리하는 게 안전함

## 3. Token Exchange (RFC 8693)

### 3-1. 토큰을 그대로 넘기면 생기는 문제

- 토큰 A(`aud=llm-gateway`)를 ERP API 에 그대로 전달 → audience 검증이 느슨한 서비스가 받아들임. 토큰 하나 털리면 모든 백엔드가 뚫림
- 반대로 게이트웨이가 서비스 계정으로 호출 → 사용자 권한이 사라짐. 권한 없는 사용자가 AI 를 통해 재무 데이터를 봄 (혼동된 대리인, confused deputy)
- 해결 = 게이트웨이가 IdP 에 "이 사용자 대신 ERP 를 부를 토큰" 을 다시 받음

### 3-2. 교환 흐름

<!-- diagram: llm-authz-token-exchange.html -->

1. 사용자 로그인 → 토큰 A (`aud=llm-gateway`, `groups=[finance]`)
2. 게이트웨이가 토큰 A 검증 → LLM 이 ERP 툴 호출을 요청
3. 게이트웨이가 Keycloak 에 교환 요청 (`subject_token=A`, `audience=erp-api`)
4. Keycloak 이 같은 사용자(sub) 의 토큰 B 발급 (`aud=erp-api`, scope 축소)
5. 게이트웨이가 토큰 B 로 ERP API 호출 → ERP 는 자기 권한 체계로 판단

**교환된 토큰은 원 토큰보다 권한이 넓어질 수 없어서, 재무 권한 없는 사용자는 교환해도 재무 API 에 못 들어감**

- 토큰은 게이트웨이·MCP 서버 코드만 다룸. LLM 프롬프트에 절대 넣지 않음
- 대상 API 마다 별도 토큰 → ERP·재무·보안 토큰이 서로 대체 불가
- 토큰 B 에 원 사용자 sub 가 남음 → ERP 로그에 "누가 AI 를 통해 조회했는지" 기록됨

### 3-3. Keycloak 지원 현황 (2026-11 기준)

| 기능 | 상태 | 비고 |
| --- | --- | --- |
| Standard Token Exchange (V2) | GA (26.2 부터) | 같은 realm 안 internal-to-internal 만 지원 |
| Legacy Token Exchange (V1) | 프리뷰, deprecated | 신규 구성에 쓰지 않음 |
| JWT Authorization Grant 와 교환 조합 | 26.5 프리뷰로 도입 | 외부 IdP 토큰을 내부 토큰으로 바꾸는 표준 경로 |
| Delegation (`act` claim) | 프리뷰 (26.8) | 에이전트가 "누구 대신" 인지 토큰에 남김 |

> 주의 : V2 는 realm 을 넘지 못함. 팀별로 realm 을 쪼개면 교환이 막힘 → realm 하나에 팀은 그룹·클라이언트로 나누는 게 유리함

## 4. Kata Containers 활용 범위

- Kata = 파드를 경량 VM 안에서 띄워 커널을 분리하는 런타임
- 막는 것 = 컨테이너 탈출 같은 런타임 공격. 막지 못하는 것 = "누가 재무 데이터를 보나" 같은 인가 문제
- 즉 인가는 게이트웨이·토큰 몫, Kata 는 그 아래 실행 격리층임

| 런타임 | 격리 단위 | 장점 | 단점 | 언제 쓰나 |
| --- | --- | --- | --- | --- |
| runc | 커널 공유 | 빠름, GPU 연결 단순 | 커널 취약점 시 노드 전체 영향 | 게이트웨이, vLLM 추론 |
| Kata | 파드별 경량 VM | 커널 분리, RuntimeClass 로 선택 | 기동 지연, GPU 는 VFIO 패스스루 필요 | 에이전트 코드 실행, 문서 파서 |
| Confidential Containers | TEE 기반 VM | 메모리까지 암호화 | 하드웨어 요건, 운영 난이도 높음 | 최고 등급 데이터 처리 |

<!-- diagram: llm-authz-kata-scope.html -->

- 효과 큰 곳 1 = LLM 이 만든 Python·SQL 을 실행하는 샌드박스. 신뢰할 수 없는 코드라 커널 분리가 의미 있음
- 효과 큰 곳 2 = PDF·엑셀 파서 워커. 파서 취약점이 노드 전체로 번지는 걸 막음
- 안 맞는 곳 = B300 추론 서버. NVLink·IB 와 VFIO 패스스루 조합은 운영 난이도가 크게 올라감

## 5. 사용법 예시

### 5-1. Token Exchange 요청

```bash
# 게이트웨이가 사용자 토큰 A 를 erp-api 용 토큰 B 로 교환
curl -s -X POST https://keycloak.corp/realms/corp/protocol/openid-connect/token \
  -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
  -d client_id=llm-gateway -d client_secret="$GW_SECRET" \
  -d subject_token="$TOKEN_A" \
  -d subject_token_type=urn:ietf:params:oauth:token-type:access_token \
  -d audience=erp-api \
  -d scope="erp:read"
```

- Keycloak 설정 = llm-gateway 클라이언트에서 Standard token exchange 스위치를 켬, erp-api 가 audience 로 나오도록 매핑

### 5-2. 검색 필터 강제 (개념 코드)

```python
# 개념 코드 : 사용자 claim 으로 컬렉션과 필터를 강제함. LLM 은 결과 청크만 받음
def retrieve(query: str, claims: dict):
    teams = set(claims.get("groups", [])) & {"erp", "finance", "sec"}
    if not teams:
        return []
    hits = []
    for team in teams:                       # 팀별 컬렉션 분리 (L2 이상)
        hits += vdb.search(collection=f"wiki-{team}", query=query,
                           filter={"classification": {"$lte": claims["clearance"]}})
    audit.log(user=claims["sub"], query=query, chunks=[h.id for h in hits])
    return hits
```

### 5-3. 보안팀 namespace 에 Kata 강제

```yaml
# RuntimeClass : Kata 핸들러
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
---
# Kyverno : sec-* namespace 파드는 kata 런타임만 허용
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-kata-sec
spec:
  validationFailureAction: Enforce
  rules:
    - name: kata-only
      match:
        any:
          - resources:
              kinds: ["Pod"]
              namespaces: ["sec-*"]
      validate:
        message: "sec namespace 는 runtimeClassName: kata 필수"
        pattern:
          spec:
            runtimeClassName: kata
```

### 5-4. 재무 벡터 DB 는 재무 retriever 만 접근

```yaml
# CiliumNetworkPolicy : finance namespace 의 벡터 DB 는 같은 ns retriever 만 허용
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: vdb-finance-only
  namespace: llm-finance
spec:
  endpointSelector:
    matchLabels: { app: vectordb }
  ingress:
    - fromEndpoints:
        - matchLabels: { app: retriever }
```

## 6. 실무에서 확인

- **Keycloak 버전** : Standard Token Exchange 는 26.2 이상 필요. 폐쇄망 Keycloak 버전부터 확인함. 26.8 delegation 은 프리뷰라 운영 투입 보류
- **realm 구조** : 팀별 realm 이면 V2 교환 불가 → 그룹 claim 기반 단일 realm 이 전제
- **사용자별 namespace 재사용** : 이미 사용자 ~1,000명 개인 namespace 구조라 개인 샌드박스 자리가 있음. 개인 위키·컬렉션은 여기 두고, 팀 데이터만 팀 namespace(`llm-erp`, `llm-finance`, `llm-sec`)로 따로 둠
- **개인 샌드박스 자원** : 1,000명이 상시 파드를 띄우면 낭비임 → 질의 시에만 기동하고 유휴 시 축소. 개인 컬렉션은 공용 벡터 DB 의 사용자별 컬렉션으로 시작하고 ResourceQuota 로 상한을 둠
- **샌드박스 네트워크** : 사용자 namespace 는 다른 사용자 namespace 로 가는 트래픽을 Cilium 으로 기본 차단함. 팀 위키는 게이트웨이 경유로만 읽음
- **Cilium** : 팀 namespace 간 기본 차단(default deny) 후 retriever → vectordb 만 허용. 게이트웨이 → retriever 는 L7 정책으로 경로 제한 검토
- **Kata 도입 범위** : bare-metal 이라 nested virt 이슈 없음. 단, Kata 게스트 이미지도 Nexus 로 미러링해야 함. 에이전트 샌드박스·파서 워커부터 적용
- **B300 노드** : 추론은 runc 유지. GPU 노드에 Kata 를 섞으면 Kueue 갱 스케줄링·GPU Operator 구성까지 같이 검증해야 함
- **원본 저장소** : 팀별 원문은 AIStor 버킷을 팀 단위로 분리, 버킷 정책도 Keycloak 그룹과 맞춤. Isilon 공유 폴더에서 수집할 때 쿼터·export 를 팀 기준으로 확인
- **감사** : 질의, 사용자 sub, 참조 청크 id 를 남김. StarRocks 로 적재하면 "누가 어떤 재무 문서를 AI 로 조회했나" 를 바로 뽑을 수 있음
- **캐시** : 게이트웨이 시맨틱 캐시 키에 team 미포함이면 팀 간 응답이 섞임. 도입 전 키 설계부터 확인

> 주의 : 개인 위키(Karpathy 패턴) 그대로 팀에 열면 위키 페이지 자체가 여러 원문을 종합한 결과라 권한이 섞임. 위키도 팀별로 따로 컴파일해야 함

## 7. 용어 정리

- **인증(Authentication)** : 누구인지 확인. Keycloak 로그인과 JWT 발급
- **인가(Authorization)** : 무엇을 해도 되는지 판단. 게이트웨이·원천 시스템이 담당
- **Token Exchange(RFC 8693)** : 가진 토큰을 다른 audience·더 좁은 scope 의 토큰으로 바꾸는 OAuth 표준
- **audience(aud)** : 토큰을 받을 대상 서비스. 다른 서비스는 이 토큰을 거부해야 함
- **subject_token** : 교환 요청에 넣는 원래 사용자 토큰
- **혼동된 대리인(confused deputy)** : 권한 많은 중간 서비스가 권한 없는 사용자 요청을 대신 처리해 버리는 문제
- **프롬프트 주입(prompt injection)** : 입력·문서에 숨긴 지시로 모델 동작을 바꾸는 공격
- **추론 인지 라우팅(inference-aware routing)** : KV 캐시·대기열을 보고 추론 레플리카를 고르는 LB
- **시맨틱 캐시(semantic cache)** : 비슷한 질문에 이전 응답을 재사용하는 캐시. 키에 테넌트 정보 필수
- **DLP(Data Loss Prevention)** : 출력에서 민감 패턴을 찾아 막거나 마스킹하는 장치
- **Kata Containers** : 파드를 경량 VM 으로 띄우는 컨테이너 런타임
- **RuntimeClass** : 파드가 쓸 컨테이너 런타임을 고르는 K8s 리소스
- **Confidential Containers** : TEE 로 메모리까지 보호하는 컨테이너 실행 방식

## 8. 한 장 요약

| 항목 | 핵심 |
| --- | --- |
| 전제 | LLM 은 권한 판단 못 함. 프롬프트 지시는 통제가 아님 |
| 인증 | Keycloak OIDC, 그룹 claim 으로 팀 식별 |
| 인가 | 게이트웨이에서 검색 필터·툴 호출·캐시·출력 4곳 강제 |
| 격리 | 메타 필터 → 컬렉션 → namespace와 DB → 전용 인스턴스, 데이터 등급별 선택 |
| 개인 데이터 | 사용자 namespace 샌드박스, sub 일치 시만 접근, 팀 반영은 승격 절차 |
| 확장 | 추론 레플리카 풀과 추론 인지 라우팅, 게이트웨이에 팀별 쿼터 |
| 원천 호출 | Token Exchange 로 사용자 권한 그대로 audience 별 토큰 발급 |
| Keycloak | V2 는 26.2 부터 GA, 같은 realm 만, delegation 은 26.8 프리뷰 |
| Kata | 에이전트 코드 실행·파서 워커에 적용, GPU 추론은 runc 유지 |
| 금지 | 민감 데이터 파인튜닝·시스템 프롬프트, 토큰을 프롬프트에 넣기 |

**LLM 위키를 팀에 열 때 권한은 모델이 아니라 retriever·tool 게이트웨이에서 사용자 토큰으로 강제하고, 개인 데이터는 개인 샌드박스에 가두고, Kata 는 그 아래 실행 격리로 덧댐**

관련 글 : LLM 위키, CH12, API 접근 제어, Envoy AI Gateway
