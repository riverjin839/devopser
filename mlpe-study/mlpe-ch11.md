## Machine Learning Platform Engineering 스터디 - CH11

> **목표** : 서빙 중인 두 캡스톤 모델에 메트릭 · 로그 · 알림을 붙이고, 이미지 · 추천 데이터의 드리프트를 잡고, Eigen-CAM 과 설명 가능 추천으로 모델 판단 근거를 보는 흐름 이해

- 원서 : Machine Learning Platform Engineering (Manning, 2026)
- 범위 : 11장 Monitoring and explainability (3부 마지막 장)
- 실습 코드 : 캡스톤 1 (YOLO), 캡스톤 2 (추천)
- 버전 메모 : 책은 Yatai PodMonitor · 대시보드, Loki Helm, deepchecks. 현재 prometheus-client 0.26, deepchecks 0.19.1 (2024-12 이후 릴리스 없음), Promtail EOL → Grafana Alloy (2026-11)

---

## 1. 개요

10장까지 = 모델이 API 로 떠 있음. 11장 = 그 API 가 **잘 돌고 있는지, 왜 그렇게 판단하는지** 보는 장.

1장 구성도의 모델 모니터링(8) · 로깅(E).

<!-- diagram: mlpe-ch11-01-map.html -->

| 영역 | 묻는 것 | 도구 |
|---|---|---|
| 기본 모니터링 | 서비스가 살아 있고 빠른가 (SLA) | Prometheus · Grafana |
| 로그 | 무슨 일이 있었나 | BentoML 로거 · Loki |
| 알림 | 누가 언제 알아야 하나 | Alertmanager |
| 드리프트 | 들어오는 데이터가 학습 때와 같은가 | deepchecks |
| 설명 가능성 | 모델이 왜 그렇게 판단했나 | Eigen-CAM, EMF |

- SLA 대표 지표 = 가동률, 처리량, 응답 지연, 응답 품질
- **에러 버짓** = 서비스가 허용하는 비신뢰 수준. 이걸 넘기 전에 대응해야 함

**모니터링은 "잘 돌고 있나", 설명 가능성은 "왜 그렇게 돌았나". 둘이 있어야 운영 중 모델을 믿을 수 있다.**

---

## 2. 11장 개념 정리 - Monitoring and explainability

### 2-1. 기본 모니터링 - 무엇을 보나

| 분류 | 지표 | 이유 |
|---|---|---|
| 자원 사용 | CPU · 메모리 · Pod 수 | limit 과 최대 replica 안에서 버티는지, 자원 배분 최적화 |
| 요청 추적 | 지연 시간, 200 아닌 응답 수, RPS, 진행 중 요청 | 느린 응답 · 앱 오류 조기 발견 |

<!-- diagram: mlpe-ch11-02-obs.html -->

순서.

1. BentoML `/metrics` 를 Prometheus 가 긁는지 확인 : Prometheus UI → Status → Service Discovery 에서 bento 검색
2. 안 보이면 **PodMonitor** 적용 (책은 Yatai 레포의 `bentodeployment-podmonitor.yaml`)
3. Graph 탭에서 `bento` 메트릭 확인
4. BentoML 제공 Grafana 대시보드 JSON import → 진행 중 요청 · RPS · 엔드포인트별 성공률 · CPU · 메모리

PodMonitor = 어떤 Pod 의 어떤 포트 · 경로를 얼마 주기로 긁을지 정의하는 Prometheus Operator CR. Pod 가 생겼다 사라져도 라벨로 자동 추적.

### 2-2. 커스텀 메트릭

기본 메트릭은 앱 동작을 다 못 보여줌. 모델 · 비즈니스 관점 지표를 직접 추가.

```python
# metrics.py
from prometheus_client import Histogram, Counter

confidence_histogram = Histogram(
    name="confidence_score",
    documentation="The confidence score of the prediction",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1),   # 0~1 을 10 구간
)

# service.py - 추론할 때마다 기록
@bentoml.Runnable.method(batchable=False)
def inference(self, input_img):
    response = json.loads(self.model(input_img)[0].tojson())
    confidence_histogram.observe(response[0]["confidence"])
    return response
```

```promql
# 최근 5분 신뢰도 90 퍼센타일
histogram_quantile(0.9, sum(rate(confidence_score_bucket[5m])) by (le))
```

| 프로젝트 | 메트릭 | 타입 | 의미 |
|---|---|---|---|
| 신분증 탐지 | `confidence_score` | Histogram | 신뢰도 분포. 떨어지면 이미지 품질 저하 · 모델 열화 신호 |
| 영화 추천 | `ranked_movie_present_counter` 등 | Counter | 요청에 시청 이력이 있는 비율 |

- **Histogram** = 값을 구간(bucket)별로 셈 → 분포 · 퍼센타일 계산 (`le` = 이하)
- **Counter** = 증가만 하는 누적값. 재시작 때 0
- Grafana 에서 Gauge(현재 값) · 시계열 그래프로 표시

> 주의 : 책 코드는 absent 카운터의 `name` 도 `ranked_movie_present_counter` 로 적혀 있음. 같은 이름을 두 번 등록하면 `Duplicated timeseries` 오류. absent 쪽 이름을 바꿀 것.

### 2-3. 로깅

- 메트릭 = 수치(얼마나). 로그 = 맥락(무엇이 · 왜). 에러 메시지, 스택 트레이스, 사건 순서
- BentoML 로거 = 일반 파이썬 `logging` 의 `"bentoml"` 로거

```python
import logging
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
bentoml_logger = logging.getLogger("bentoml")
bentoml_logger.addHandler(ch)
bentoml_logger.setLevel(logging.DEBUG)

if len(results) == 0:
    bentoml_logger.error("Error while processing object detection, model returned 0 results")
    return {"status": "failed"}
```

- 로그에 `trace` · `span` ID 가 자동으로 붙음 → 요청 단위 추적
- 클라우드(GKE · EKS) 기본 로그를 쓰면 메트릭은 Grafana, 로그는 CloudWatch 로 흩어짐 → **한 곳으로 모으는 게 원칙**
- **Loki** = 로그 본문이 아니라 라벨(메타데이터)만 인덱싱 → 싸고 가볍게 확장. Grafana 에서 메트릭과 로그를 같은 화면에서 연결

```bash
helm install loki grafana/loki --namespace loki --create-namespace
```

### 2-4. 알림 - Prometheus 규칙 + Alertmanager

- Prometheus 가 규칙(PromQL 조건)을 평가 → 발동 시 Alertmanager 로 전송 → 그룹 · 라우팅 → 메일 · Slack · PagerDuty

| 규칙 | 식 | 잡는 상황 |
|---|---|---|
| ServiceDown | `up{job="yatai/bento-deployment", ...} == 0` | 타깃은 있는데 스크레이프 실패 (앱 오류) |
| MissingUpMetric | `absent(up{...}) == 1` | 배포 자체가 삭제 · 종료돼 타깃이 사라짐 |

```yaml
# Prometheus Helm values
serverFiles:
  bentoDeploymentRules.yaml:
    groups:
    - name: BentoDeploymentServiceAlerts
      rules:
      - alert: ServiceDown
        expr: up{job="yatai/bento-deployment", yatai_ai_bento_deployment_component_type=~"api-server|runner"} == 0
        for: 5m                                    # 5분 지속돼야 발동
        labels:
          severity: critical
        annotations:
          summary: "Service {{ $labels.job }} on instance {{ $labels.instance }} is down"
```

- 알림 상태 : 초록(inactive) → 노랑(**pending**, 조건 성립 · `for` 대기 중) → 빨강(**firing**)
- 실습 : Yatai 에서 배포 Terminate → MissingUpMetric pending → 5분 뒤 firing → 메일 수신

```yaml
# Alertmanager
config:
  global:
    smtp_smarthost: "smtp.gmail.com:587"
    smtp_auth_password: "<app password>"     # Gmail 2단계 인증 + 앱 비밀번호
  route:
    receiver: gmail-alerts
    group_by: [alertname, job]
    group_wait: 30s                           # 첫 알림 전 묶는 시간
    group_interval: 5m                        # 같은 그룹 추가 알림 간격
    repeat_interval: 3h                       # 해결 안 되면 재알림 간격
  receivers:
  - name: gmail-alerts
    email_configs:
    - to: "<recipient>"
      send_resolved: true                     # 해결 알림도
```

- `routes` 로 severity · namespace 별 수신자 분기 (critical → PagerDuty, medium · low → 메일)

### 2-5. 이미지 드리프트 - deepchecks

<!-- diagram: mlpe-ch11-03-drift-vision.html -->

6장 Evidently 는 표 데이터. 이미지는 피처가 정해져 있지 않음 → **이미지 속성**(밝기, 대비, 면적, 종횡비, RGB 강도)의 분포를 비교.

deepchecks 기능.

- 데이터 무결성 (이상치, 결측, 타입)
- 모델 검증 (과적합, 클래스 불균형, 편향)
- 드리프트 감지 (핵심)
- 커스텀 검사

실습 = 이미지 100장 밝기를 일부러 낮춤(`ImageEnhance.Brightness`, factor < 1) → 원본 vs 변형 비교.

```python
from deepchecks.vision.checks import ImagePropertyDrift

train_ds = load_dataset(train=True, object_type="VisionData")    # 원본
test_ds = load_dataset(train=False, object_type="VisionData")    # 밝기 변형
result = ImagePropertyDrift().run(train_ds, test_ds)
result.save_as_html("deepcheck_vision_drift_check.html")
```

| 속성 | 드리프트 점수 (KS) | 해석 |
|---|---|---|
| Brightness | 0.619 | 바꾼 속성. 크게 감지 |
| RMS Contrast | 0.310 | 밝기 변경 영향 |
| Mean Green | 0.289 | 색 강도도 같이 움직임 |
| Mean Red | 0.139 | 〃 |
| Mean Blue | 0.068 | 〃 |
| Area · Aspect Ratio | 0.0 | 안 바꿈 → 0 |

- 운영 적용 = 추론 이미지 · 예측을 버킷 · DB 에 저장 → 주기적으로 학습 이미지와 비교

### 2-6. 추천 드리프트 - 잠재 요인 비교

- 행렬 분해 모델은 새 사용자 · 영화 때문에 자주 재학습 필요
- 평점 변화 = 취향 · 인기 변화 → **임베딩(user · item factor) 분포** 비교로 감지

```python
def introduce_item_drift(df, movie_ids, drift_amount=1):        # 영화 1~100 평점 +1
    idx = df["itemId"].isin(movie_ids)
    df.loc[idx, "rating"] += drift_amount
    df["rating"] = df["rating"].clip(1, 5)
    return df

# 원본 · 드리프트 데이터로 각각 학습 → item_factors.weight 추출 → 전치해 열 = 아이템
from deepchecks.tabular import Dataset
from deepchecks.tabular.checks import FeatureDrift
FeatureDrift(columns=["item_factor_2"]).run(
    Dataset(df_item_factors_t1, label=None), Dataset(df_item_factors_t2, label=None))
```

- 영화 2번의 잠재 요인 분포가 이동 → 이 영화에 대한 선호 변화
- 잠재 요인 분포를 시간 흐름으로 추적하면 인기 · 취향 변화를 읽을 수 있음

### 2-7. 설명 가능성(XAI)

필요한 이유 = 이해관계자 신뢰, 디버깅, 규제 대응, 성능 개선.

- 금융 예 : 미국 ECOA 는 대출 거절 시 구체 사유(신용점수, 소득, 부채비율) 제시 의무 → 설명 가능한 모델 필수

| 분류 | 방식 | 예 |
|---|---|---|
| 모델 기반 | 구조 자체가 해석 가능 | 선형 회귀, 결정 트리, EMF |
| 사후(post hoc) | 학습 끝난 블랙박스를 바깥에서 해석 | SHAP, LIME, Eigen-CAM |

<!-- diagram: mlpe-ch11-04-xai.html -->

### 2-8. 탐지 모델 - Eigen-CAM

- CAM 계열 시각 설명. 모델이 **이미지 어디를 보고** 판단했는지 히트맵
- 재학습 · 모델 수정 불필요, 복잡한 구조에도 적용

```python
from ultralytics import YOLO
from yolo_cam.eigen_cam import EigenCAM
from yolo_cam.utils.image import show_cam_on_image

model = YOLO("../serving/yolov8_custom.pt")
target_layers = [model.model.model[-2], model.model.model[-3], model.model.model[-4]]   # 추상 특징 · 공간 정보
cam = EigenCAM(model, target_layers, task="od")
grayscale_cam = cam(rgb_img)[0, :, :]
plt.imshow(show_cam_on_image(np.float32(img) / 255, grayscale_cam, use_rgb=True))
```

- 결과 : 신분증에 잘 집중함, 이미지 모서리도 약간 봄
- 활용 아이디어 : 얼굴 부분을 안 본다면 → 얼굴 없는 ID 카드로도 일반화 가능
- 재학습 때마다 돌려 여전히 맞는 곳을 보는지 확인

### 2-9. 추천 모델 - 설명 가능 행렬 분해(EMF)

- 잠재 공간에서 **비슷한 사용자 · 아이템 이웃**을 찾음
- 설명 점수 = 이 아이템을 평가한 사용자 중 나와 비슷한 사용자 비율 → 학습 가중치로 사용

```python
emf = EMFModel(learning_rate=0.01, reg_term=0.001, expl_reg_term=0.0,
               latent_dim=80, epochs=10, positive_threshold=3, knn=10)
emf.fit(train)                                                   # MovieLens 100K
recommendations = Recommender(train, emf).recommend_all()
recs = EMFExplainer(emf, recommendations, data).explain_recommendations()
```

| 순위 | 설명 `{평점: 비슷한 사용자 수}` | 읽는 법 |
|---|---|---|
| 1 | `{}` | 비슷한 사용자 평가 없음 → 설명 불가 |
| 3 | `{3: 1, 4: 4, 5: 4}` | 비슷한 9명 중 8명이 4점 이상 |
| 10 | `{5: 6}` | 비슷한 6명 전부 5점 |

- "당신과 비슷한 50명이 5점을 줬습니다" 같은 문구 → 사용자 신뢰 · 만족도 향상, 콘텐츠 구매 · 제작 판단 근거

### 2-10. 책 vs 현재

| 항목 | 책 | 현재 |
|---|---|---|
| 스크레이프 대상 | Yatai PodMonitor · `job="yatai/bento-deployment"` | Yatai 정체 → 일반 Deployment 에 PodMonitor · ServiceMonitor 직접 작성 |
| 로그 수집기 | 언급 없음 (Loki Helm 만) | Promtail 은 2026-03 EOL → Grafana Alloy 로 수집 |
| Alertmanager 라우팅 | `match: severity: medium` | `match` 는 폐기 예정 → `matchers: ['severity="medium"']` |
| 드리프트 (이미지) | deepchecks 0.19 | 2024-12 이후 릴리스 없음. Evidently 0.7 도 이미지 · 임베딩 드리프트는 제한적 → 이미지 속성은 직접 계산 + 통계 검정이 현실적 |
| 사후 설명 | SHAP · LIME 언급 | SHAP 0.54 활발. LLM 쪽은 12 · 13장 관측 도구로 이어짐 |
| Eigen-CAM | 외부 레포 `YOLO-V8-CAM` | 개인 레포 의존. 사내 반입 시 코드 검토 · 고정 필요 |

---

## 3. 실무에서 확인

- **기존 관측 스택 재사용** : 클러스터에 이미 Prometheus · Grafana · Loki(또는 OpenSearch)가 있으면 ML 서빙도 같은 스택으로. ML 전용 스택을 따로 만들지 말 것
- **라벨 카디널리티** : 커스텀 메트릭에 user_id · 이미지명 같은 고유값을 라벨로 넣으면 시계열 폭증 → Prometheus 메모리 문제. 라벨은 모델명 · 버전 · 엔드포인트 정도로
- **알림 설계** : `up == 0` 같은 생존 알림 + 모델 지표 알림(신뢰도 p90 하락, 드리프트 비율) 을 severity 로 구분. 1,000명 멀티테넌트면 namespace 라벨로 팀별 라우팅 → SmartITSM 같은 티켓 시스템 webhook 연동
- **메일 계정** : 책처럼 개인 Gmail 앱 비밀번호를 values.yaml 에 넣지 말 것. 사내 SMTP 릴레이 + Secret
- **이미지 저장 정책** : 드리프트 분석용으로 추론 이미지를 저장하면 신분증 = **개인정보**. 원본 저장 대신 속성값(밝기 · 대비 · 크기)만 저장하거나 마스킹 · 보관 기한 · 접근 통제 필수
- **드리프트 주기** : 실시간이 아니라 일 · 주 단위 배치 Job (KFP recurring run 또는 Airflow) 로. 결과 수치를 Prometheus Pushgateway · 메트릭으로 내보내면 같은 알림 체계에 태울 수 있음
- **설명 가능성 범위** : 규제 · 고객 응대가 필요한 모델(신용, 의료)은 사전에 설명 방식 확정. 내부 도구 수준이면 주기적 Eigen-CAM 샘플 점검 정도로 충분
- **Loki 저장소** : Loki 청크를 AIStor 버킷에 두면 장기 보관이 싸짐. 보관 기간(retention)은 감사 요구에 맞춤

> 주의 : `absent()` 알림은 라벨 셀렉터가 틀려도 항상 발동함. 배포 직후 오탐이 쏟아지면 셀렉터 오타부터 의심할 것.

---

## 4. 용어 정리

- **SLA(Service Level Agreement)** : 서비스가 약속한 가동률 · 지연 등 수준
- **에러 버짓(error budget)** : SLA 안에서 허용되는 실패 여유분
- **PodMonitor / ServiceMonitor** : Prometheus Operator 의 스크레이프 대상 정의 CR
- **Histogram / Counter / Gauge** : 구간별 분포 / 누적 증가값 / 현재 값
- **PromQL** : Prometheus 질의 언어
- **Loki** : 라벨 인덱스 기반 로그 집계 시스템
- **Alertmanager** : 알림 그룹 · 중복 제거 · 라우팅 담당
- **pending / firing** : 조건 성립 후 대기 / 알림 발동
- **deepchecks** : 데이터 · 모델 검증, 드리프트 검사 라이브러리
- **잠재 요인(latent factor)** : 행렬 분해가 학습한 사용자 · 아이템 벡터
- **XAI(Explainable AI)** : 모델 판단을 사람이 이해하게 만드는 기법
- **SHAP / LIME** : 피처 기여도 계산 / 국소 근사 모델로 설명하는 사후 기법
- **CAM / Eigen-CAM** : CNN 이 주목한 영역 히트맵 / 주성분으로 만드는 CAM

---

## 5. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 채운 블록 | 모델 모니터링(8) · 로깅(E), 3부 마무리 |
| 기본 모니터링 | `/metrics` → PodMonitor → Prometheus → Grafana 대시보드 |
| 커스텀 메트릭 | 신뢰도 Histogram, 요청 유형 Counter, PromQL 퍼센타일 |
| 로그 | `bentoml` 로거 → Loki 로 중앙화 |
| 알림 | `up == 0` 와 `absent()` 규칙 → Alertmanager 라우팅 |
| 이미지 드리프트 | 이미지 속성 분포를 deepchecks 로 KS 비교 |
| 추천 드리프트 | 아이템 잠재 요인 분포 비교 |
| 설명 가능성 | Eigen-CAM 히트맵, EMF 이웃 평점 설명 |
| 현재 기준 보완 | Yatai 의존 제거, Alloy, `matchers`, deepchecks 정체 |
| 실무 | 기존 관측 스택 재사용, 라벨 카디널리티, 개인정보 이미지 저장 정책 |

**모델은 배포한 날부터 낡기 시작함. 메트릭 · 로그 · 알림으로 증상을 보고, 드리프트로 원인을 좁히고, 설명 가능성으로 판단 근거를 확인하는 순서가 운영의 기본이다.**

다음 글 : 12장 Designing LLM-powered systems - LLMOps, RAG 챗봇 DakkaBot, UI, LLM 관측
