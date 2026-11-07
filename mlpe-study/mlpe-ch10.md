## Machine Learning Platform Engineering 스터디 - CH10

> **목표** : 9장에서 학습·등록한 모델을 BentoML 로 추론 서버로 만들고, MLflow 레지스트리 연동 · MLflow 단독 서빙 · KServe 를 비교해 서빙 도구 선택 기준 이해

- 원서 : Machine Learning Platform Engineering (Manning, 2026)
- 범위 : 10장 Model inference and serving
- 실습 코드 : 캡스톤 1 `serving` 디렉터리 (YOLO), 캡스톤 2 (추천)
- 버전 메모 : 책 본문은 BentoML 1.1.6 Runner API, 추천 서비스는 1.2+ `@bentoml.service`. 현재 BentoML 1.4.40, MLflow 3.18, KServe 0.21 (2026-11)

---

## 1. 개요

8 · 9장 = 모델을 만들고 레지스트리에 올림. 10장 = 그 모델을 **API 로 내보내는 일**.

1장 구성도의 모델 배포(6) · 모델 API(A). 6장이 소득 분류 모델로 맛보기였다면 10장은 캡스톤 2개로 본격 서빙.

<!-- diagram: mlpe-ch10-01-map.html -->

셀프서비스 배포가 주는 것.

| 이점 | 내용 |
|---|---|
| 오류 감소 | 수작업 배포는 실수 많고 반복이 안 됨 |
| 조기 검증 | 이 모델이 배포 가능한지 일찍 확인 |
| 자원 실험 | 로컬보다 큰 K8s 자원으로 시험, 반대로 작은 장비 최적화도 |
| 병목 제거 | ML 엔지니어 기다리는 시간 없음 |
| 협업 | 데이터 사이언티스트와 엔지니어 사이 간극 축소 |

단, 셀프서비스는 **비운영 환경까지**. 운영 배포는 여전히 ML 엔지니어 몫.

**데이터 사이언티스트가 스테이징까지 직접 올려 보고, 운영은 엔지니어가 받아 가는 구조. 서빙 도구는 이 경계를 매끄럽게 만드는 물건이다.**

---

## 2. 10장 개념 정리 - Model inference and serving

### 2-1. 모델 배포가 어려운 이유

일반 소프트웨어 배포(버전 관리, 테스트, CI/CD) 위에 ML 만의 문제가 더 얹힘.

| 항목 | 질문 |
|---|---|
| 추론 패턴 | 배치? 실시간? 둘 다? |
| 확장성 | 부하 변동에 어떻게 늘리고 줄임? |
| 모니터링 · 로깅 | 성능 · 드리프트 추적 (11장) |
| 지속 학습 | 재학습 모델 자동 배포 |
| 데이터 의존성 | 학습 때 전처리를 서빙에서도 똑같이 |
| 하드웨어 | GPU 필요 여부 |
| 버전 · 롤백 | 여러 버전 관리 |
| 설명 가능성 | 규제 산업에서 결정 근거 요구 (11장) |
| 자원 관리 | 서빙과 다른 컴포넌트 사이 자원 배분 |
| 보안 · 개인정보 | 민감 정보 유출, 적대적 공격 |

### 2-2. BentoML 이 해주는 것

- 프레임워크 상관없이 같은 방식으로 패키징 · 서빙 (PyTorch, TF, sklearn)
- 실시간 API + 배치 추론
- **적응형 마이크로배칭** : 들어오는 요청을 자동으로 묶어 처리량 향상
- 헬스체크 · 메트릭 기본 제공
- 모델 · 의존성 · 서빙 로직을 한 번에 묶어 재현 가능한 빌드

### 2-3. Service 와 Runner

<!-- diagram: mlpe-ch10-02-service.html -->

- **Service** = API 서버 1개 이상 + Runner 1종 이상을 감싼 단위
- **API 서버** = HTTP 요청 수신, 입력 파싱 · 검증. 여러 개 띄워 수평 확장 · 부하 분산 · 병렬 처리
- **Runner** = 모델을 감싼 계산 단위. 각자 파이썬 워커에서 돌고 여러 인스턴스 병렬 실행

```python
import bentoml, json, os, PIL
from bentoml.io import Image, JSON
from ultralytics import YOLO

class YOLOv8Runnable(bentoml.Runnable):
    def __init__(self):
        self.model = YOLO("yolov8_custom.pt")              # 8장 best.pt

    @bentoml.Runnable.method(batchable=False)              # 이미지 1장씩
    def inference(self, input_img):
        return json.loads(self.model(input_img)[0].tojson())

    @bentoml.Runnable.method(batchable=False)
    def render(self, input_img):
        r = self.model(input_img, save=True, project=os.getcwd())
        return PIL.Image.open(os.path.join(r[0].save_dir, r[0].path))   # 박스 그린 이미지

yolo_v8_runner = bentoml.Runner(YOLOv8Runnable, name="yolov8_runnable")   # 이름 명시 권장
svc = bentoml.Service("yolo_v8", runners=[yolo_v8_runner])

@svc.api(input=Image(), output=JSON())
async def invocation(input_img):
    return await yolo_v8_runner.inference.async_run([input_img])
```

| 엔드포인트 | 출력 | 용도 |
|---|---|---|
| `/inference` (`/invocation`) | 클래스 · 신뢰도 · 박스 좌표 JSON | 다른 시스템 연동 |
| `/render` | 박스 · 라벨 그린 이미지 | 디버깅 · 데모 · 눈 확인 |

`await` 가 필요한 이유.

- `async_run` 은 결과가 아니라 "나중에 줄 결과(future)" 를 바로 반환
- `await` 없이 쓰면 아직 없는 결과를 처리하려다 오류
- `await` 하는 동안 서버는 다른 요청을 받음 → 응답성 유지

### 2-4. Runner 여러 개

```python
svc = bentoml.Service("object_detectors",
                      runners=[grayscale_converter, object_detector_1, object_detector_2])

@svc.api(input=Image(), output=JSON())
async def predict(input_image):
    x = await grayscale_converter.async_run(input_image)        # 전처리
    a, b = await asyncio.gather(                                 # 두 모델 동시 실행
        object_detector_1.async_run(x), object_detector_2.async_run(x))
    return {"results": {"model_a": a, "model_b": b}}
```

- 전처리 → 추론 다단계 구성
- 두 버전 모델 동시 비교 (A/B, 섀도 테스트)

### 2-5. 관측 엔드포인트 기본 제공

| 엔드포인트 | 용도 |
|---|---|
| `/healthz` · `/livez` | liveness. 실패하면 K8s 가 Pod 재시작 |
| `/readyz` | readiness. 준비 전엔 트래픽 안 받음 |
| `/metrics` | Prometheus 형식 요청 수 · 지연 · 진행 중 요청 |

프로브 · 메트릭을 직접 구현할 필요 없음 → 반복 작업 · 실수 감소.

### 2-6. Bento 빌드와 태그

```yaml
service: "service.py:svc"
include:
  - "service.py"
  - "yolov8_custom.pt"                                   # 가중치를 Bento 안에 포함
docker:
  base_image: "ultralytics/ultralytics:8.0.203-cpu"      # 시스템 의존성 해결된 이미지
```

```bash
bentoml build                                            # → yolo_v8:3jghhcfxvwsrnbsb
bentoml containerize yolo_v8:3jghhcfxvwsrnbsb            # → OCI 이미지
docker run --rm -p 3000:3000 yolo_v8:3jghhcfxvwsrnbsb    # Swagger UI 에서 테스트
```

- **Bento 태그** = `서비스명:버전라벨`. 빌드마다 자동 생성
- `yolo_v8` 만 써도 최신을 가리키지만 Docker 태그처럼 **항상 명시**가 원칙 → 배포 일관성 · 재현성 · 디버깅

### 2-7. MLflow 레지스트리 + BentoML

<!-- diagram: mlpe-ch10-03-mlflow-bento.html -->

- MLflow = 데이터 사이언티스트용 추적 · 실험. BentoML = 운영 엔지니어용 배포 · 모니터링
- 9장에서 `@prod` alias 붙인 추천 모델을 서비스 시작 때 끌어옴

```python
import bentoml, mlflow, torch, numpy as np
from mlflow import MlflowClient

@bentoml.service(resources={"cpu": "2"}, traffic={"timeout": 10})   # 1.2+ 문법
class RecommenderRunnable:
    def __init__(self, registered_model_name="recommender_production", device="cpu"):
        mlflow.set_tracking_uri("http://mlflow:8080")
        prod = MlflowClient().get_model_version_by_alias(registered_model_name, "prod")
        bentoml.mlflow.import_model("recommender", f"runs:/{prod.run_id}/model")
        path = bentoml.mlflow.get("recommender:latest").path_of(bentoml.mlflow.MLFLOW_MODEL_FOLDER)
        self.model = mlflow.pytorch.load_model(path).to(device).eval()
        self.device = device

    @bentoml.api                                   # → /predict 자동 생성
    def predict(self, user_id: int, top_k: int = 10, ranked_movies: np.ndarray = None) -> np.ndarray:
        ...                                        # 안 본 영화 예상 평점 → topk
```

```yaml
service: "service:RecommenderRunnable"
labels: {owner: mlops, stage: demo}
include: ["*.py"]
python:
  requirements_txt: ./requirements.txt
```

- `bentoml build` → `bentoml serve recommender_runnable:latest` → `bentoml containerize`
- 파이프라인 안이라면 MLflow 클라이언트 조회 대신 앞 단계가 넘긴 모델 URI 를 파라미터로 받으면 됨
- 활용 : 스테이징 모델을 개발자 PC 에서 바로 띄워 확인, 전처리만 다른 모델로 A/B 테스트

**API 서버 · 헬스 · 메트릭 · 배칭 · GPU 처리 · API 문서를 직접 만들 필요 없이 파일 2개로 모델 서버가 나옴.**

### 2-8. MLflow 단독 서빙

```bash
export MLFLOW_TRACKING_URI=http://mlflow:5000
mlflow models serve -m "models:/recommender_production@prod"        # 로컬 REST 서버

mlflow models build-docker -m "models:/recommender_production@prod" \
  -n recommender_service --enable-mlserver                         # 이미지 생성
```

- `/health`, `/invocations` 엔드포인트 제공
- K8s 지식 없이 가능, 도구 하나로 수명주기 전체 → 작은 조직 · 단순함 우선일 때
- 세밀한 배포 옵션 · 모니터링이 필요하면 BentoML 조합이 나음

### 2-9. KServe

<!-- diagram: mlpe-ch10-04-paths.html -->

- Kubeflow 에 포함된 K8s 네이티브 서빙. `InferenceService` CRD 하나로 배포

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: pytorch-yolo
  namespace: pytorch-yolo
spec:
  predictor:
    model:
      modelFormat:
        name: sklearn                         # 책 예시 그대로. 실제 YOLO 면 pytorch · onnx 등으로
      storageUri: "gs://yolov8/models/pytorch/1.0/model"
```

- DNS 설정돼 있으면 서비스 URL 자동 할당
- K8s 지식이 꽤 필요 → 개발자 셀프 테스트용으론 문턱. 대신 Kubeflow 생태계 안에서 확장성이 기본

| 항목 | KServe | BentoML | MLflow |
|---|---|---|---|
| 초점 | K8s 서빙 오케스트레이션 | 쉬운 패키징 · 서빙 | ML 수명주기 전체 |
| 프레임워크 | 무관 | 무관 | 무관 |
| K8s 중심 | ○ | ✕ | ✕ |
| 사용 난이도 | 높음 (설정 · K8s 지식) | 낮음 | 낮음 |
| 실험 추적 | ✕ | ✕ | ○ |

책 결론 : 쉽게 빨리 = BentoML, 수명주기 통합 = MLflow, K8s 세밀 제어 = KServe.

### 2-10. 책 vs 현재

| 항목 | 책 | 현재 |
|---|---|---|
| BentoML API | YOLO = 1.1 Runner, 추천 = 1.2 `@bentoml.service` 혼재 | 1.4 는 `@bentoml.service` 가 표준. Runner 는 레거시 |
| 1.4 다중 모델 | `runners=[...]` | 서비스 여러 개 + `bentoml.depends()` 로 연결 |
| 배칭 | `batchable=True` | `@bentoml.api(batchable=True, max_batch_size=...)` |
| 입출력 | `bentoml.io.Image`, `JSON` | 타입 힌트 (`PIL.Image.Image`, pydantic) 로 자동 |
| Yatai | 중앙 저장 · 서빙 장점으로 언급 | 2024-05 이후 개발 정체. BentoCloud 또는 자체 GitOps |
| MLflow 서빙 | `--enable-mlserver` | 동일. MLflow 3 에선 KServe 와 같은 V2 추론 프로토콜(MLServer) |
| KServe | 예시 수준 | 0.21. `modelFormat: mlflow` 지원, LLM 서빙 기능 확대 |

---

## 3. 실무에서 확인

- **Lake 기준 선택** : Kubeflow 26.03 에 KServe 가 이미 포함 → 운영 표준은 KServe, 개발자 셀프 테스트는 BentoML · `mlflow models serve` 로 나누는 구성이 무난. LLM · 대형 GPU 서빙은 Ray Serve · vLLM 계열 (Ray 스터디 참고)
- **이미지 빌드** : `bentoml containerize` · `mlflow models build-docker` 모두 빌드 시 PyPI · 베이스 이미지 접근 → 폐쇄망은 CI 에서 사내 미러로 빌드, 결과 이미지만 Harbor · Nexus 로
- **가중치 위치** : 책은 `.pt` 를 Bento 안에 포함 → 모델 바꿀 때마다 이미지 재빌드. 큰 모델은 이미지와 분리해 AIStor · PVC 에서 로드 (KServe `storageUri` 방식)
- **시작 시 레지스트리 조회** : 추천 서비스처럼 `__init__` 에서 MLflow 조회 → MLflow 가 죽으면 Pod 기동 실패, 재시작 때마다 다른 버전이 뜰 수 있음. 운영에선 배포 시점에 버전 번호를 고정해 주입
- **프로브 튜닝** : 모델 로딩이 길면 readiness 전에 liveness 가 Pod 를 죽임 → `startupProbe` 로 로딩 시간 확보
- **GPU 서빙** : B300 한 장을 작은 모델 하나가 독점하면 낭비. MIG 분할, 여러 모델 한 서버(멀티모델), KServe ModelMesh 류 검토
- **멀티테넌트** : 사용자 네임스페이스마다 InferenceService 생성 → Istio · Gateway 인증(Keycloak), 네임스페이스별 GPU 쿼터
- **A/B · 카나리** : KServe 는 `canaryTrafficPercent` 로 트래픽 분할 기본 제공. BentoML 다중 Runner 비교는 한 Pod 안이라 자원 격리가 약함

> 주의 : 책의 KServe 예시는 YOLO PyTorch 모델에 `modelFormat: sklearn` 으로 적혀 있음. 그대로 쓰면 sklearn 서버가 모델을 못 읽음. 실제로는 ONNX 변환 후 `onnx` 또는 커스텀 predictor 이미지 사용.

---

## 4. 용어 정리

- **서빙(serving)** : 학습된 모델을 요청에 응답하는 서비스로 제공
- **Service / Runner** : BentoML 의 API 단위 / 모델 실행 단위 (1.1 기준)
- **적응형 마이크로배칭(adaptive batching)** : 짧은 시간 안 요청을 묶어 한 번에 추론
- **async / await** : 결과를 기다리는 동안 다른 작업을 처리하는 비동기 문법
- **liveness / readiness probe** : 살아 있는지 / 트래픽 받을 준비 됐는지 K8s 가 확인
- **Bento 태그** : `서비스명:버전`. Bento 고유 식별자
- **InferenceService** : KServe 의 모델 배포 CRD
- **storageUri** : KServe 가 모델 파일을 받아올 저장소 경로
- **MLServer · V2 추론 프로토콜** : 서빙 서버 공통 REST · gRPC 규격
- **A/B 테스트 · 카나리** : 두 버전에 트래픽을 나눠 비교 / 일부만 새 버전으로

---

## 5. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 채운 블록 | 모델 배포(6) · 모델 API(A) |
| 배포 난제 | 추론 패턴, 확장, 데이터 의존성, GPU, 버전, 설명, 보안 |
| BentoML 구조 | API 서버 × N 와 Runner, async 호출, 다중 Runner |
| 기본 제공 | `/healthz` · `/readyz` · `/metrics`, Swagger, 배칭 |
| 패키징 | bentofile → build → 태그 → containerize |
| MLflow 연동 | `@prod` alias 모델을 import 해 서비스 |
| MLflow 단독 | `models serve` · `build-docker`, 단순함 우선 |
| KServe | InferenceService CRD, K8s 네이티브, 문턱 높음 |
| 현재 기준 보완 | BentoML 1.4 서비스 API, Yatai 정체, KServe 0.21 |
| 실무 | 운영 KServe · 개발 BentoML, 가중치 분리, 버전 고정, startupProbe |

**서빙 도구는 누가 쓰느냐로 고르면 됨. 개발자 손엔 쉬운 BentoML, 플랫폼 표준엔 K8s 네이티브 KServe, 그 사이를 MLflow 레지스트리가 잇는다.**

다음 글 : 11장 Monitoring and explainability - Prometheus · Grafana · Loki · Alertmanager, 이미지 · 추천 드리프트, Eigen-CAM · 설명 가능 추천
