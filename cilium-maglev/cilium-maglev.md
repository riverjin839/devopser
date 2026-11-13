## Cilium Maglev - 인입 노드가 달라도 같은 백엔드를 고르는 일관 해시

> **목표** : Maglev 표가 어떻게 만들어지고 패킷 하나가 어떻게 백엔드를 고르는지 원리부터 잡고, Cilium 옵션 · 메모리 · 운영 함정까지 Y지역 AIStor VIP 기준으로 정리함

- 출처 : Maglev 논문(Eisenbud 외, NSDI 2016), Cilium 문서 kube-proxy free 의 Maglev Consistent Hashing 절, Linux IPVS mh 스케줄러, 직접 돌린 시뮬레이션(`maglev_sim.py`)
- 기준 버전 : Cilium 1.20.4 (2026-11 기준 최신 태그 확인)

---

## 1. 개요

Maglev 는 Google 이 만든 소프트웨어 L4 LB 이자, 그 안의 일관 해시 알고리즘 이름임. 여러 LB 노드가 서로 상태를 나누지 않아도 같은 연결에 대해 같은 백엔드를 고르게 해줌.

<!-- diagram: maglev-01-overview.html -->

- 라우터는 ECMP 로 VIP 패킷을 아무 노드에나 보냄. 노드가 늘거나 줄면 같은 연결이 다른 노드로 갈 수 있음
- 새로 받은 노드에는 그 연결의 CT(연결 추적) 기록이 없음 → 표를 보고 백엔드를 다시 고름
- 모든 노드가 같은 백엔드 목록과 같은 시드로 같은 표를 만들어 두므로, 다시 골라도 원래 백엔드가 나옴

**Maglev 는 노드 간 통신 없이, 같은 입력이면 어느 노드에서든 같은 답이 나오게 만든 표다.**

---

## 2. 개념 정리

### 2-1. 왜 일반 해시로는 안 되나

| 방식 | 분배 균등성 | 백엔드 1개 변경 시 이동 | 조회 비용 | 메모리 |
|---|---|---|---|---|
| hash mod N | 균등 | 거의 전부 (시뮬레이션 97.9%) | O(1) | 없음 |
| 링 해시 (consistent hash ring) | 가상 노드 수에 따라 편차 | 약 1/N | O(log V) | 가상 노드 수만큼 |
| Rendezvous (HRW) | 균등 | 약 1/N | O(N) | 없음 |
| Maglev | 거의 균등 (M 이 클수록) | 1/N 에 약간 추가 | O(1) | 서비스당 M 슬롯 |

- 데이터패스는 패킷마다 계산해야 함 → O(1) 조회가 필수
- 링 해시는 조회가 느리고, Rendezvous 는 백엔드 수만큼 해시를 돌림
- Maglev = 조회 O(1) 와 균등 분배를 얻고, 대신 변경 시 1/N 보다 조금 더 움직이는 것을 허용함

### 2-2. 표 생성 알고리즘

<!-- diagram: maglev-02-build.html -->

| 단계 | 내용 |
|---|---|
| 1. 표 크기 M | 소수로 정함. Cilium 기본 16381 |
| 2. offset · skip | 백엔드마다 해시 2개 계산. offset = h1(이름) % M, skip = h2(이름) % (M - 1) + 1 |
| 3. 선호 순열 | j 번째 선호 슬롯 = (offset + j × skip) % M. M 이 소수라 0 ~ M-1 을 한 번씩 다 돎 |
| 4. 채우기 | 백엔드들이 돌아가며 자기 순열에서 아직 빈 첫 슬롯을 하나씩 차지 |
| 5. 종료 | M 칸이 다 차면 끝. 백엔드마다 M/N 칸 안팎을 가짐 |

- M 을 소수로 두는 이유 = skip 이 무엇이든 순열이 모든 슬롯을 한 번씩 지나가게 하려는 것
- 표는 백엔드가 바뀔 때만 다시 만듦. 패킷 처리 경로에서는 조회만 함

#### 2-2-1. 손으로 따라가는 작은 예시 (M = 7, 백엔드 3개)

| 백엔드 | offset | skip | 선호 순열 |
|---|---|---|---|
| b0 | 6 | 3 | 6, 2, 5, 1, 4, 0, 3 |
| b1 | 5 | 6 | 5, 4, 3, 2, 1, 0, 6 |
| b2 | 0 | 3 | 0, 3, 6, 2, 5, 1, 4 |

- 1바퀴 : b0 → 6, b1 → 5, b2 → 0
- 2바퀴 : b0 → 2, b1 → 4, b2 → 3 (6 은 이미 참)
- 3바퀴 : b0 → 1 (5 는 이미 참) → 7칸 완성
- 결과 표 (슬롯 0~6) = b2, b0, b0, b2, b1, b1, b0
- b1 제거 후 다시 만든 표 = b2, b2, b0, b2, b0, b0, b0

> 주의 : b1 이 갖던 슬롯 4 · 5 만 바뀐 게 아니라 슬롯 1 도 b0 → b2 로 바뀜. Maglev 는 "이동 0" 이 아니라 "이동 최소" 를 목표로 함. M 이 작을수록 이 부수 이동이 커짐

### 2-3. 패킷 한 개의 처리 흐름

<!-- diagram: maglev-03-packet.html -->

- CT 에 기록이 있으면 표를 안 봄 → 같은 노드로 계속 오는 연결은 백엔드가 바뀌지 않음
- CT 가 없을 때(새 연결, 또는 ECMP 재해시로 다른 노드에 온 기존 연결)만 Maglev 표를 봄
- 해시 입력 = 5-tuple (출발지 IP · 포트, 목적지 IP · 포트, 프로토콜) 와 시드. ClientIP 세션 고정을 켜면 출발지 포트를 빼고 해시함
- 기존 연결이 다른 노드로 와도 표가 같으면 같은 백엔드로 감 → DSR 이면 백엔드 노드의 CT 가 이어받아 연결 유지

### 2-4. 백엔드가 바뀔 때

<!-- diagram: maglev-04-disruption.html -->

48개 백엔드(Y지역 AIStor 가정)로 직접 돌린 결과임.

| 표 크기 M | 백엔드당 슬롯 | 슬롯 편차 | 1개 제거 시 나머지 슬롯 이동 |
|---|---|---|---|
| 251 | 5 ~ 6 | 19.1% | 7.32% |
| 4093 | 85 ~ 86 | 1.2% | 2.10% |
| 16381 (기본) | 341 ~ 342 | 0.3% | 0.89% |
| 65521 | 1365 ~ 1366 | 0.1% | 0.44% |
| 비교 : hash mod N | - | - | 97.90% |

- 1개 추가 (M = 16381) : 기존 슬롯 3.11% 이동. 이론 최소치 1/49 = 2.04% 에서 약 1%p 추가
- M 을 키우면 균등성과 안정성이 같이 좋아짐. 대신 메모리가 늘어남
- Cilium 문서 기준 M 은 백엔드 수의 100배 이상이어야 변경 시 재배치가 1% 이내로 유지됨 → 위 결과(16381 / 48 ≈ 341배, 0.89%)와 맞음

---

## 3. Cilium 에서의 Maglev

### 3-1. 적용 범위

| 트래픽 | 백엔드 선택 | Maglev 적용 |
|---|---|---|
| 외부 → LoadBalancer · NodePort · externalIP (N-S) | 인입 노드 데이터패스 | 적용 |
| 클러스터 안 Pod → Service (E-W) | 소켓 LB 가 connect() 때 직접 지정 | 미적용 (중간 홉 없음) |
| ClusterMesh Global Service 를 Pod 가 호출 | 소켓 LB | 미적용 |

- Y지역 설계의 경로 A(Com Pod → AIStor) = 소켓 LB, 경로 B(외부 · 같은 랙 서버 → VIP) = Maglev 로 정확히 나뉨
- XDP 가속과 같이 쓸 수 있음

### 3-2. 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `loadBalancer.algorithm` | random | maglev 로 바꾸면 전체 서비스에 적용 |
| `maglev.tableSize` | 16381 | 허용값 251, 509, 1021, 2039, 4093, 8191, 16381, 32749, 65521, 131071 (소수만) |
| `maglev.hashSeed` | 내장 고정값 | base64 12바이트. 클러스터 모든 agent 가 같아야 함 |
| `bpf.lbAlgorithmAnnotation` | false | true 면 서비스별 `service.cilium.io/lb-algorithm` 사용 가능 |
| `service.cilium.io/lb-algorithm` | - | random 또는 maglev. 서비스 생성 시에만 반영 |
| `service.cilium.io/weight` (EndpointSlice) | - | Maglev 서비스에서만 유효. 0 ~ 65535, 0 = 점검(드레인) |

- 표 크기 기준 : 16381 = 서비스당 백엔드 약 160개까지, 65521 = 약 650개까지
- 가중치는 슬롯 몫을 가중치 비율로 나누는 방식 → 성능이 다른 노드 세대를 섞을 때 씀

### 3-3. 메모리 (개념 계산)

- 슬롯 1개 = 백엔드 ID 4바이트로 보면, 서비스 1개당 M × 4B → 16381 이면 약 64KB
- 전역으로 maglev 를 켜면 노드마다 서비스 수만큼 표를 가짐 → 서비스 1,000개면 노드당 약 64MB, 65521 이면 약 256MB
- 실제 사용량은 버전 · 맵 구조에 따라 다름. 도입 전 `cilium-dbg bpf lb maglev list` 와 노드 메모리 지표로 확인함

> 주의 : 서비스가 많은 클러스터에서 전역 maglev + 큰 tableSize 를 쓰면 BPF 맵 메모리가 크게 늘어남. 필요한 서비스에만 annotation 으로 켬

---

## 4. random vs Maglev, 그리고 조합

| 항목 | random | Maglev |
|---|---|---|
| 새 연결 분배 | 균등 (확률) | 균등 (슬롯 비율) |
| 노드가 바뀐 기존 연결 | 다른 백엔드로 갈 확률 높음 → 끊김 | 같은 백엔드 (표가 같을 때) |
| 노드 간 일관성 | 없음 | 있음 (시드 · 백엔드 목록 같을 때) |
| 가중치 | 미지원 | 지원 |
| 메모리 | 적음 | 서비스당 M 슬롯 |

| 조합 | 동작 | 언제 쓰나 |
|---|---|---|
| eTP Local + 아무 알고리즘 | 백엔드 후보 = 자기 노드 Pod 뿐 → Maglev 의미 거의 없음 | 노드마다 Pod 1개, 인입이 고르게 퍼질 때 |
| eTP Cluster + Maglev + SNAT | 일관 선택, 응답은 인입 노드 경유 | DSR 불가 환경 |
| eTP Cluster + Maglev + DSR(Geneve) | 일관 선택, 응답 직접 | Y지역 AIStor VIP 기본안 |

---

## 5. 사용법 예시

### 5-1. Helm values

```yaml
# 전역은 random 유지, AIStor VIP 만 maglev (메모리 절약)
loadBalancer:
  algorithm: random
  mode: hybrid
  dsrDispatch: geneve
tunnelProtocol: geneve
bpf:
  lbAlgorithmAnnotation: true
maglev:
  tableSize: 16381            # AIStor 백엔드 160개 넘으면 32749 로
  hashSeed: "<고정값>"         # Helm values 에 박아 두고 업그레이드 때도 유지
```

```bash
# 시드 생성 : 한 번 만들어 Git 에 보관 (값 자체는 민감정보 아님)
head -c12 /dev/urandom | base64 -w0
```

### 5-2. 서비스 지정

```yaml
apiVersion: v1
kind: Service
metadata:
  name: minio-global
  namespace: aistor
  annotations:
    service.cilium.io/lb-algorithm: maglev     # 생성 시점에만 반영
spec:
  type: LoadBalancer
  externalTrafficPolicy: Cluster
  selector: { app: aistor }
  ports:
  - { name: s3, port: 443, targetPort: 9000 }
```

### 5-3. 점검용 드레인 (가중치 0)

```bash
# 개념 코드 : 점검 노드의 AIStor 엔드포인트가 든 EndpointSlice 에 가중치 0
kubectl -n aistor annotate endpointslice <slice-name> service.cilium.io/weight=0 --overwrite
# 새 연결이 빠졌는지 확인 후 cordon · 작업
```

> 주의 : EndpointSlice 는 컨트롤러가 다시 만들면 annotation 이 사라질 수 있음. 드레인 절차는 PoC 에서 유지 여부를 먼저 확인함

### 5-4. 확인 명령

```bash
cilium-dbg service list                       # 서비스 · 백엔드 목록
cilium-dbg bpf lb maglev list                 # 서비스별 Maglev 표 (출력 형식은 버전별 상이)
cilium-dbg status --verbose | grep -i -A3 maglev
```

### 5-5. 시뮬레이션 직접 돌려보기

```bash
python3 maglev_sim.py     # 2-2-1 작은 예시, 2-4 표 크기별 결과가 그대로 나옴
```

- 알고리즘은 논문 그대로이고 해시 함수는 sha256 을 씀 → Cilium 실제 표와 슬롯 배치는 다름. 경향 확인용 개념 코드임

---

## 6. 실무에서 확인

- 시드 일치 : 노드마다 시드가 다르면 Maglev 의 장점이 전부 사라짐. Helm values 에 고정하고, 노드 일부만 다른 values 로 뜨는 일이 없게 ArgoCD 로 관리함
- tableSize 변경 : 바꾸면 agent 재시작이 끝날 때까지 노드마다 표가 달라 새 연결의 백엔드가 어긋날 수 있음 → Y지역은 처음부터 값을 정하고 운영 중엔 바꾸지 않음
- annotation 은 생성 시점에만 반영 : 기존 서비스에 붙이면 안 먹음. Y지역 AIStor 서비스는 처음부터 annotation 을 넣어 생성
- 엔드포인트 반영 시차 : EndpointSlice 변경이 노드마다 조금씩 늦게 도착함 → 그 사이 표가 잠깐 다름. 롤링 재시작은 한 번에 1~2개 Pod 씩
- 백엔드 수 : AIStor 48개 → 16381 이면 약 341배로 충분. 증설로 160개를 넘으면 32749 로 올리는 시점을 미리 잡음
- 메모리 : 기존 Lake 는 Ingress 7,300개 수준에 bpf-lb-map-max 포화 이력이 있음 → 전역 maglev 는 피하고 annotation 방식만 씀
- 느린 백엔드 : Maglev 는 Ready 여부만 봄. 디스크가 느려진 AIStor 노드는 가중치를 낮추는 식으로 수동 보정
- 측정 : 설계 페이지 3-7 검증 계획의 T7(노드 1대 종료)에서 끊긴 연결 비율이 1/48 수준인지 확인함

---

## 7. 용어 정리

- **일관 해시(consistent hashing)** : 백엔드가 바뀌어도 대부분의 키가 원래 자리에 남게 하는 해시 방식
- **룩업 테이블(lookup table)** : 해시값 → 백엔드를 미리 계산해 둔 배열. Maglev 는 크기 M 의 소수 배열
- **offset · skip** : 백엔드마다 선호 순열을 만드는 시작점과 보폭
- **선호 순열(preference list)** : 백엔드가 차지하고 싶은 슬롯 순서
- **부수 이동(extra disruption)** : 빠진 백엔드와 무관한 슬롯이 다른 백엔드로 바뀌는 것
- **CT(connection tracking)** : 노드가 기억하는 연결별 백엔드 기록. 있으면 표를 안 봄
- **해시 시드(hash seed)** : 해시 결과를 정하는 공통 값. 노드마다 같아야 함
- **N-S · E-W** : 클러스터 밖 ↔ 안 트래픽, 클러스터 안 Pod 간 트래픽
- **소켓 LB** : Pod 의 connect() 시점에 백엔드를 바로 지정하는 Cilium 기능. Maglev 를 안 씀
- **가중치 0 드레인** : 새 연결 몫을 0 으로 만들어 백엔드를 서서히 빼는 방법

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 정체 | 노드 간 통신 없이 같은 백엔드를 고르는 O(1) 일관 해시 표 |
| 표 생성 | 소수 M, 백엔드별 offset · skip 순열, 라운드로빈 채우기 |
| 패킷 처리 | CT 있으면 그대로, 없으면 표[해시 % M] |
| 변경 시 | 빠진 몫 1/N 과 부수 이동 1% 미만 (M=16381, N=48), mod N 은 97.9% |
| 적용 범위 | N-S 만. Pod → Service 는 소켓 LB |
| 필수 설정 | 시드 고정, tableSize ≥ 백엔드 × 100, annotation 은 생성 시 |
| Y지역 | AIStor VIP 만 annotation 으로 maglev, eTP Cluster, DSR(Geneve) |

**Maglev 의 일관성은 시드 · 표 크기 · 백엔드 목록 세 가지가 모든 노드에서 같을 때만 성립한다.**

관련 글 : Y지역 datalake 네트워크 아키텍처, Cilium Gateway API LB VIP 헤어핀
