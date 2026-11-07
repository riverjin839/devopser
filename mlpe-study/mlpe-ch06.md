## Machine Learning Platform Engineering 스터디 - CH6

> **목표** : BentoML 로 모델을 실시간 API 로 띄우고, Evidently 로 데이터 드리프트를 배치·실시간 두 방식으로 감시하는 구조 이해

- 원서 : Machine Learning Platform Engineering (Manning, 2026)
- 범위 : 6장 Productionizing ML models
- 실습 코드 : `github.com/practical-mlops/chapter-6`
- 버전 메모 : 책은 BentoML 1.1 (Runner API + Yatai), Evidently 0.4 계열 API. 현재 BentoML 1.4.40, Evidently 0.7.23 (2026-11)

---

## 1. 개요

5장 = 배치 추론을 파이프라인으로 자동화함. 남은 질문은 두 개.

- 모델을 **실시간 API** 로 어떻게 안정적으로 서빙함?
- 서빙 중인 모델이 시간이 지나도 **계속 잘 맞는지** 어떻게 앎?

6장은 1장 구성도의 모델 배포(6) · 모델 API(A) · 모델 모니터링(8) 을 채움.

<!-- diagram: mlpe-ch06-01-map.html -->

- 서빙 = **BentoML**. Dockerfile·K8s 매니페스트·`/metrics` 를 직접 안 만들어도 됨
- 감시 = **Evidently**. 학습 데이터(참조)와 들어오는 데이터(현재)의 분포를 통계 검정으로 비교
- 계속 소득 분류 모델(income classifier)로 실습. LLM 서빙·관측은 12~13장에서 따로 다룸

**3장에서 FastAPI 앱 하나 띄우려고 이미지·매니페스트·CI/CD 를 다 손으로 만들었음. 6장은 그 반복 작업을 도구에 넘기는 장이다.**

---

## 2. 6장 개념 정리 - Productionizing ML models

### 2-1. BentoML 이 푸는 문제

- 3장 방식 : 이미지 빌드 → K8s 매니페스트 여러 개 → 모니터링 코드 → CI/CD 구성. 데이터 사이언티스트 전원이 이걸 할 줄 알기 어려움
- **Bento** = ML 앱(모델 + 서빙 코드 + 의존성 + 설정)을 담은 배포 단위 아카이브. 도시락 통 비유
- **Yatai** = BentoML 의 K8s 배포·운영 컴포넌트. UI 에서 배포·스케일·모니터링

<!-- diagram: mlpe-ch06-02-bento.html -->

| 단계 | 하는 일 | 명령·코드 |
|---|---|---|
| 1. 모델 등록 | MLflow Production 모델을 로컬 Bento 스토어로 복사 | `bentoml.mlflow.import_model` |
| 2. 서비스 정의 | runner + service + `/predict` API | `service.py` |
| 3. 패키징 정의 | 포함 파일·의존성·환경변수 | `bentofile.yaml` |
| 4. 빌드 | Bento 생성 → 로컬 스토어 | `bentoml build` |
| 5. 로컬 테스트 | 컨테이너 만들어 실행 | `bentoml containerize` → `docker run -p 3000:3000` |
| 6. 푸시 | Yatai 원격 스토어로 모델 + Bento 업로드 | `bentoml yatai login` → `bentoml push` |
| 7. 배포 | Yatai UI 에서 Deployment 생성 → 이미지 빌더 Job → Pod | UI |

### 2-2. 서비스 구성 - Runner 와 Service

```python
# 1. 모델 가져오기 (download_model.py)
bentoml.mlflow.import_model(
    "random-forest-classifier",
    model_uri=f"models:/{model_name}/{model_stage}",   # 책 : stage 방식
)

# 2. runner + service (service.py, 책 = BentoML 1.1 API)
income_clf_runner = bentoml.mlflow.get("random-forest-classifier:latest").to_runner()
svc = bentoml.Service("income_classifier_service", runners=[income_clf_runner])

@svc.on_startup                                        # 시작 시 1회
async def initialise(context: bentoml.Context):
    # MLflow 에서 컬럼 목록(column_list.pkl) 다운로드, Feast 스토어 초기화
    context.state["store"] = feature_store.init_feature_store()
    context.state["col_list"] = col_list

@svc.api(input=JSON(pydantic_model=IncomeClassifierUsers), output=JSON(), route="/predict")
def predict(inputs, ctx):
    feature_df = ctx.state["store"].get_online_features(            # Feast 온라인 피처
        features=ctx.state["feature_list"], entity_rows=[inputs.dict()]).to_df()
    input_df = InputMapper(feature_df, ctx.state["col_list"]).generate_pandas_dataframe()
    pred = income_clf_runner.predict.run(input_df)[0]
    return {"income_category": OutputMapper(pred).map_prediction(), "user_id": inputs.user_id}
```

- **Runner** = 실제 추론 단위. 별도 파이썬 워커에서 돌고 독립적으로 수평 확장
- **Service** = API 프런트. 요청 받고 runner 에 추론을 맡김. runner 여러 개 붙이면 모델 비교도 가능
- 입력은 user_id 하나 → 피처는 서비스 안에서 Feast 로 조회. 4장 피처 스토어가 여기서 쓰임

```yaml
# bentofile.yaml - Dockerfile 보다 단순한 패키징 정의
service: "service:svc"            # 파일명:서비스 객체
labels:
  owner: ml-engineering-team
include:
  - "service.py"
  - "src/*.py"
  - "*.env"
python:
  requirements_txt: requirements.txt
docker:
  env:
    - ENV_NAME=local
```

### 2-3. Yatai 배포 결과

- Deployment 생성 → Yatai 가 `yatai-bento-image-builder-...` **K8s Job 으로 이미지 빌드**
- Pod 2종 : **API Server**(프런트, 요청 수신) + **Runner**(모델 보유, 추론). 따로 replica 지정
- 실습 결과 : API Server 1개 + Runner 2개, 둘 다 `2/2` (Istio 등 사이드카 포함)
- Ingress 자동 생성 → Swagger 문서에서 `/predict` 테스트
- `/metrics` 기본 제공 → Prometheus 가 요청 수·지연 시간 수집

**Dockerfile, 매니페스트, 메트릭 코드 없이 `bentofile.yaml` 하나로 배포 표준화. 이게 BentoML 의 핵심 가치임.**

### 2-4. 책 vs 현재 - BentoML

| 항목 | 책 (BentoML 1.1) | 현재 (BentoML 1.4) |
|---|---|---|
| 서비스 정의 | `bentoml.Service` 와 `to_runner()` | `@bentoml.service` 클래스 + `@bentoml.api` 메서드 |
| 모델 분리 실행 | Runner | 서비스 분리 + `bentoml.depends()` |
| 시작 훅 | `@svc.on_startup` | 클래스 `__init__` |
| K8s 배포 | Yatai | Yatai 는 1.2 대응 "공사 중" 상태로 2024-05 이후 커밋 없음. 공식 방향은 BentoCloud |
| 자체 K8s 대안 | - | 컨테이너화 후 일반 Deployment·KServe·ArgoCD |
| MLflow 모델 | `models:/이름/Production` | `models:/이름@champion` (alias) |

현재 문법 예시.

```python
import bentoml
from pydantic import BaseModel

class User(BaseModel):
    user_id: int

@bentoml.service(resources={"cpu": "2"}, traffic={"timeout": 10})
class IncomeClassifier:
    def __init__(self):                                   # on_startup 대신
        self.model = bentoml.mlflow.load_model("random-forest-classifier:latest")
        self.store = init_feature_store()

    @bentoml.api(route="/predict")
    def predict(self, user: User) -> dict:
        df = self.store.get_online_features(features=FEATURES,
                                            entity_rows=[user.model_dump()]).to_df()
        return {"income_category": map_label(self.model.predict(to_dummies(df))[0]),
                "user_id": user.user_id}
```

> 주의 : 책의 Yatai 설치(부록 A)는 BentoML 1.1 기준임. 1.2 이후 SDK 로 만든 Bento 는 Yatai 1.x 와 맞지 않을 수 있음. 지금 자체 클러스터에 올린다면 `bentoml containerize` 이미지를 사내 레지스트리에 넣고 GitOps 로 배포하는 쪽이 현실적임.

### 2-5. 데이터 드리프트란

배포 직후엔 잘 맞던 모델이 몇 달 뒤 성능 저하. 원인 = 학습 때 본 데이터와 지금 들어오는 데이터의 통계 성질이 달라짐.

| 유형 | 뜻 | 예 |
|---|---|---|
| 레이블 드리프트 | 정답(target) 정의 자체가 변함 | 불량 판정 기준 변경 |
| 사전확률 변화 | 클래스 비율이 변함 | 사기 거래 비율 변동 |
| 공변량 변화 | 입력 피처 분포가 변함 | 고객 연령·지역 분포 변화 |
| 급격한 드리프트 | 외부 사건으로 갑자기 변함 | 팬데믹, 시장 이벤트 |

Evidently 가 쓰는 통계 검정.

| 검정 | 대상 | 판정 |
|---|---|---|
| KS 검정 | 수치형. 누적분포(CDF) 비교 | p-value < 0.05 → 드리프트 |
| 카이제곱 검정 | 범주형. 범주 비율 비교 | p-value 기준 |
| Wasserstein 거리 | 분포 사이 "흙 옮기는 비용" | 기본 임계값 0.1 초과 → 드리프트 |

- Evidently 가 데이터 타입·크기를 보고 검정을 자동 선택. 직접 지정·커스텀 검정도 가능

### 2-6. Evidently 리포트와 대시보드

- **Metric** : 핵심 단위. 데이터셋 수준(`DatasetDriftMetric`) / 컬럼 수준(`ColumnDriftMetric`)
- **Preset** : 메트릭 묶음 템플릿. `DataDriftPreset`, `DataQualityPreset`, `RegressionPreset`
- **Report** : 참조 데이터 + 현재 데이터로 실행 → HTML·JSON
- **Workspace / Project / Snapshot** : 리포트를 시간순으로 쌓아 대시보드로 봄
- **Panel** : 대시보드 칸. `DashboardPanelCounter`(숫자 하나), `DashboardPanelPlot`(선·막대 그래프)

```python
# 책 (Evidently 0.4 계열)
report = Report(metrics=[DataDriftPreset()])
report.run(reference_data=reference_data, current_data=current_data)
report.save_html("drift_report.html")

ws = RemoteWorkspace("http://localhost:8000")          # evidently ui 서버
project = ws.create_project(name="income-classifier")
project.dashboard.add_panel(DashboardPanelCounter(
    title="Share of Drifted Features",
    value=PanelValue(metric_id="DatasetDriftMetric", field_path="share_of_drifted_columns"),
    agg=CounterAgg.LAST, size=1))
project.save()                                         # 안 하면 UI 에 반영 안 됨
```

### 2-7. 배치 드리프트 - KFP 컴포넌트

<!-- diagram: mlpe-ch06-03-drift-batch.html -->

- 5장 추론 파이프라인의 **피처 조회 와 추론 사이**에 `detect_drift` 컴포넌트 삽입
- 참조 데이터 찾기 : MLflow 모델 run 의 `dataset_inputs` 태그 → MinIO 경로 → 다운로드 (4장에서 `log_input` 으로 남긴 게 여기서 쓰임)
- 현재 데이터 = 앞 단계 Feast 피처 Parquet
- 피처 8개마다 `ColumnDriftMetric` + `ColumnSummaryMetric` → 리포트를 워크스페이스에 `add_report`
- 드리프트 감지되면 파이프라인 중단 → 잘못된 데이터로 추론 결과를 쓰지 않음
- 파이프라인 돌 때마다 대시보드 갱신. 실습 배치에선 드리프트 컬럼 0

### 2-8. 실시간 드리프트 - 마이크로배치 윈도

<!-- diagram: mlpe-ch06-04-drift-rt.html -->

- 요청 1건 vs 참조 데이터 비교는 통계적으로 의미 없음 → **최근 N건(마이크로배치)** 으로 비교
- `MonitoringService` : 요청마다 피처를 윈도에 추가 → N건 넘으면 오래된 것부터 버림 → N건 찼을 때 리포트 실행
- BentoML `on_startup` 에서 참조 데이터·워크스페이스·윈도 크기(`.env`) 초기화, `predict` 안에서 `iterate(feature_df)` 호출

```python
def iterate(self, new_rows):
    self.current = pd.concat([self.current, new_rows], ignore_index=True)
    if len(self.current) > self.window_size:
        self.current = self.current.iloc[-self.window_size:]     # 슬라이딩 윈도
    if len(self.current) < self.window_size:
        return                                                    # 아직 부족
    self.report.run(reference_data=self.reference, current_data=self.current)
    self.workspace.add_report(self.project_id, self.report)
```

책이 직접 짚은 함정.

- 윈도 50 으로 돌렸더니 **드리프트 비율 0.875** (8개 중 7개 컬럼)
- 그런데 현재 데이터를 학습셋에서 뽑았으니 실제 드리프트는 0 이어야 정상
- 원인 = **표본이 너무 작음**. 윈도를 키우거나 임계값을 다시 잡아야 함

**드리프트 수치는 표본 크기와 임계값에 따라 쉽게 거짓 경보가 됨. 윈도 크기 결정이 감시 설계의 절반이다.**

### 2-9. 드리프트가 보이면

| 대응 | 내용 |
|---|---|
| 조사 | 드리프트 유형·심각도 확인. 성능·공정성에 실제 영향 있는지 |
| 상류 수정 | 원인이 데이터 파이프라인 변경이면 파이프라인·전처리 수정 |
| 재학습 | 최신 데이터로 다시 학습 (1장 구성도의 8 → 3 재학습 화살표) |
| 피처 재선정 | 피처 중요도가 바뀌었으면 추가·제거·변경 |

### 2-10. 책 vs 현재 - Evidently

| 항목 | 책 | 현재 (0.7) |
|---|---|---|
| import | `from evidently.report import Report`, `evidently.metric_preset` | `from evidently import Report`, `from evidently.presets import DataDriftPreset` |
| 실행 결과 | `report.run()` 후 report 객체에 결과 | `snapshot = report.run(current, reference)` → 스냅숏 반환 (인자 순서 주의) |
| 워크스페이스 적재 | `ws.add_report(project.id, report)` | `ws.add_run(project.id, snapshot)` |
| 개별 메트릭 | `ColumnDriftMetric`, `DatasetDriftMetric` | `ValueDrift`, `DriftedColumnsCount` |
| 구 API | - | `evidently.legacy` 로 이동. 책 코드는 여기로 import 바꾸면 대부분 동작 |
| 추가 기능 | - | LLM 평가(descriptors), 가드레일, 테스트 조건 |

```python
from evidently import Report
from evidently.presets import DataDriftPreset
from evidently.ui.workspace import RemoteWorkspace

report = Report([DataDriftPreset()])
snapshot = report.run(current_data=feature_df, reference_data=reference_df)
RemoteWorkspace("http://evidently-ui.monitoring:8000").add_run(PROJECT_ID, snapshot)
```

---

## 3. 실무에서 확인

- **서빙 도구 선택** : Yatai 가 사실상 멈춘 상태라 책 그대로 운영 표준으로 삼기 어려움. 사내 K8s 기준 후보는 KServe(Kubeflow 일체형, 10장에서 비교), Ray Serve(Lake GPU·LLM 쪽), BentoML(이미지 빌드 도구로만 사용 후 GitOps 배포)
- **이미지 빌드 위치** : Yatai 는 클러스터 안에서 이미지 빌더 Job 을 돌림 → 폐쇄망에선 베이스 이미지·PyPI 를 외부에서 못 받음. 빌드는 CI(Jenkins 등) + 사내 Nexus PyPI 미러에서 하고 클러스터는 이미지만 받게 분리
- **비밀값** : 책은 `bentofile.yaml` `docker.env` 에 MinIO 키, `.env` 파일을 Bento 에 포함 → 이미지 안에 키가 박힘. K8s Secret 이나 Vault 주입으로 바꿀 것
- **피처 조회 지연** : 실시간 API 가 매 요청 Feast 온라인 스토어(Redis)를 조회함 → Redis 지연이 곧 API 지연. 같은 네임스페이스·노드 근접 배치, 커넥션 풀 확인
- **드리프트 위치** : 배치는 KFP 컴포넌트로, 실시간은 서빙 코드 안에 넣는 구조임. 서빙 Pod 안에서 리포트를 돌리면 추론 지연에 영향 → 요청 로그를 Kafka·S3 에 남기고 별도 배치 Job 이 주기적으로 Evidently 실행하는 비동기 방식이 운영엔 안전
- **임계값 운영** : 피처 수가 많으면 몇 개는 늘 드리프트로 잡힘. "드리프트 컬럼 비율 > X% 가 N회 연속" 처럼 알림 조건을 걸어야 알림 피로가 없음 (11장 Alertmanager 와 연결)
- **멀티테넌트** : 서빙 엔드포인트가 사용자 네임스페이스마다 생기면 Ingress·인증(Keycloak) 정책 표준이 필요. Evidently UI 는 기본 인증이 약하므로 프록시 뒤에 둘 것
- **스토리지** : Evidently 워크스페이스 스냅숏을 AIStor 버킷에 저장하면 대시보드 이력이 Pod 재시작에도 남음

> 주의 : Evidently 0.7 부터 `report.run` 인자 순서가 `(current, reference)` 임. 위치 인자로 넘기면 참조·현재가 뒤바뀐 리포트가 조용히 생성됨. 항상 키워드 인자로 넘길 것.

---

## 4. 용어 정리

- **Bento** : 모델·코드·의존성·설정을 묶은 BentoML 배포 단위
- **`bentofile.yaml`** : Bento 패키징 정의. Dockerfile 의 간소판
- **Runner** : BentoML 1.1 의 추론 실행 단위. 독립 워커·독립 확장
- **Yatai** : BentoML 의 K8s 배포 운영 컴포넌트 (현재 개발 정체)
- **Swagger(OpenAPI) 문서** : REST API 를 기계가 읽을 수 있게 기술한 명세. 브라우저에서 바로 호출 테스트
- **데이터 드리프트(data drift)** : 운영 입력 데이터 분포가 학습 데이터와 달라지는 현상
- **공변량 변화(covariate shift)** : 입력 피처 분포 변화
- **참조 데이터(reference) / 현재 데이터(current)** : 비교 기준(보통 학습셋) / 비교 대상(최근 입력)
- **KS 검정 / 카이제곱 / Wasserstein 거리** : 수치형 분포 / 범주형 비율 / 분포 간 거리 비교
- **Preset** : Evidently 메트릭 묶음 템플릿
- **마이크로배치 윈도** : 최근 N건만 모아 비교하는 슬라이딩 구간

---

## 5. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 채운 블록 | 모델 배포(6) · 모델 API(A) · 모델 모니터링(8) |
| BentoML 흐름 | MLflow 모델 import → `service.py` 와 bentofile → build → push → Yatai 배포 |
| 구성 | API Server Pod + Runner Pod, 독립 확장. Swagger · `/metrics` 자동 |
| 드리프트 | 참조 vs 현재 분포를 KS · 카이제곱 · Wasserstein 으로 비교 |
| 배치 감시 | KFP 추론 파이프라인에 detect_drift 삽입, 드리프트면 중단 |
| 실시간 감시 | 최근 N건 윈도로 리포트. 표본 작으면 거짓 경보 |
| 현재 기준 보완 | BentoML 1.4 클래스 서비스, Yatai 정체, Evidently 0.7 API 변경 |
| 실무 | CI 에서 이미지 빌드, Secret 주입, 비동기 드리프트 배치, 알림 조건 설계 |

**모델을 띄우는 것보다 띄운 모델이 계속 맞는지 아는 게 더 어렵다. 6장은 배포와 감시를 한 쌍으로 묶어 1부 구성도를 닫는 장임.**

다음 글 : 7장 Data analysis and preparation - Kubeflow 노트북으로 분석, KFP 데이터 전달, 캡스톤 데이터 준비 파이프라인
