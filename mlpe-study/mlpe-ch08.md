## Machine Learning Platform Engineering 스터디 - CH8

> **목표** : 7장 데이터 준비 파이프라인 뒤에 YOLO 학습·검증 컴포넌트를 붙이고, 시스템 의존성은 container_component 로 처리하며, 지표를 KFP 에 남겨 비교하는 흐름 이해

- 원서 : Machine Learning Platform Engineering (Manning, 2026)
- 범위 : 8장 Model training and validation: Part 1
- 실습 코드 : 책 캡스톤 1 레포 (신분증 탐지, `mng.bz/yNwJ`)
- 버전 메모 : 책은 YOLOv8 (Ultralytics 8.0~8.3), KFP 2.11. 현재 Ultralytics 8.4 (YOLO11 · YOLO12 · YOLO26), KFP 2.18 (2026-11)

---

## 1. 개요

7장 = 데이터를 받아서 나눔. 8장 = 그 데이터로 **학습하고 검증**하는 컴포넌트.

1장 구성도의 모델 학습(4) · 평가 검증(5).

<!-- diagram: mlpe-ch08-01-map.html -->

노트북에서 학습해도 되지만 운영으로는 안 늘어남. 학습을 컴포넌트로 만들면 얻는 것.

- 소스 관리에서 버전·추적
- 어느 환경에서나 같은 결과
- 데이터 준비 파이프라인과 바로 연결
- 지표를 체계적으로 기록·비교

학습 컴포넌트가 맡는 일 3가지.

1. train · val · test 이미지와 라벨을 제자리에 내려받기
2. 데이터셋 설정 (경로, 클래스, 라벨 매칭)
3. 실제 학습과 평가

**학습 코드는 Ultralytics 가 대부분 해줌. 8장의 초점은 학습 알고리즘이 아니라 학습을 파이프라인 부품으로 만드는 방법이다.**

---

## 2. 8장 개념 정리 - Model training and validation Part 1

### 2-1. YOLO 커스텀 데이터 설정

```python
data = {
    "path": "/dataset/",
    "train": "train/images",       # 라벨은 train/labels 에 있다고 가정
    "val": "val/images",
    "test": "test/images",
    "names": {0: "id_card"},       # 탐지할 클래스 1개
}
with open("custom_data.yaml", "w") as f:
    yaml.dump(data, f)
```

```python
from ultralytics import YOLO

model = YOLO("yolov8n.pt")                  # 사전학습 가중치 다운로드
results = model.train(
    data="custom_data.yaml",
    imgsz=640,                              # 640x640, 비정방형은 letterbox 패딩
    epochs=epochs, batch=batch,             # 파이프라인 파라미터로 받음
    name="yolov8n_custom",
    project=project_path,                   # 가중치·혼동행렬·PR 곡선·샘플 추론 저장 위치
)
```

- 학습 중 epoch 마다 샘플 추론 이미지를 project 경로에 자동 저장 → 진행 상황 눈으로 확인

### 2-2. 모델 크기 선택

| 크기 | 특징 | 어울리는 곳 |
|---|---|---|
| n (Nano) | 가장 빠르고 작음 | 엣지, 실시간 카메라 |
| s · m | 중간 | 일반 서버 추론 |
| l · x | 가장 정확, 자원 많이 씀 | 자율주행처럼 정확도 우선 |

책이 Nano 로 시작한 이유.

- 계산 자원 절약
- 작은 모델로 "되긴 되는지" 빠르게 확인 (feasibility)
- 부족하면 그 결과를 근거로 큰 모델로 키움

공개 벤치마크가 좋아도 내 요구사항(지연·메모리·정확도)과의 trade-off 를 모르면 나중에 문제됨.

### 2-3. 주요 하이퍼파라미터

| 키 | 기본값 | 의미 | 조정 포인트 |
|---|---|---|---|
| `model` | - | 모델 파일 (`yolov8n.pt`) | 용도에 맞는 구조·가중치 |
| `data` | - | 데이터 설정 YAML | 라벨 품질·양 |
| `epochs` | 20 | 반복 횟수 | 늘리면 보통 좋아지지만 시간 증가 |
| `batch` | 4 | 배치 크기 (-1 = AutoBatch) | GPU 메모리 한도 |
| `imgsz` | 640 | 입력 크기 | 정밀 위치가 필요하면 크게 |
| `pretrained` | True | 사전학습 가중치 사용 | 대부분 True 가 출발점 |
| `optimizer` | auto | SGD · Adam · AdamW 등 | auto = 반복 1만 회 초과 SGD, 이하 AdamW |
| `exist_ok` | False | 같은 이름 덮어쓰기 | 특별한 이유 없으면 False |
| `val` | True | 학습 중 검증 | - |

처음엔 노출 파라미터를 최소로 시작 → 수렴 안 하면 lr · batch · epochs 부터 조정 → 필요할 때 늘림.

### 2-4. container_component - 시스템 패키지가 필요할 때

<!-- diagram: mlpe-ch08-03-container.html -->

- Ultralytics 를 slim 이미지에서 돌리면 `ImportError: libGL.so.1` 발생
- 해결은 `apt-get` 으로 시스템 라이브러리 설치 → `@dsl.component` 는 파이썬 패키지만 다룸
- `@dsl.container_component` + `dsl.ContainerSpec` = 이미지·명령·인자를 직접 지정. Dockerfile 없이 파이썬 코드 안에서 처리

```python
@dsl.container_component
def train_model(epochs: int, batch: int, yolo_model_name: str,
                train_dataset: Input[Dataset], validation_dataset: Input[Dataset],
                test_dataset: Input[Dataset],
                model_output: Output[Model], data_yaml: Output[Artifact]):
    return dsl.ContainerSpec(
        image="python:3.11-slim",
        command=["bash", "-c"],
        args=[f"""
          apt-get update && apt-get install -y --no-install-recommends libgl1-mesa-glx libglib2.0-0 && \
          pip install --no-cache-dir ultralytics torch opencv-python-headless minio tqdm pyyaml && \
          cat << 'EOF' > /train.py
{TRAINING_SCRIPT}
EOF
          python3 /train.py --train-path "$0" --val-path "$1" --test-path "$2" \
            --epochs "$3" --batch "$4" --model-name "$5" --model-output "$6" --data-yaml "$7"
        """,
        train_dataset.path, validation_dataset.path, test_dataset.path,      # → $0 $1 $2
        epochs, batch, yolo_model_name, model_output.path, data_yaml.path],  # → $3 ~ $7
    )
```

- 학습 스크립트 = `argparse` 로 경로·값을 받는 독립 스크립트. 로컬에서 따로 실행 가능
- 스크립트 끝에서 Ultralytics 가 고른 `weights/best.pt` 를 `model_output` 경로로 복사
- heredoc(`cat << 'EOF'`)으로 스크립트를 컨테이너 안 파일로 씀 → bash 위치 인자 `$0~$7` 로 KFP 입력을 스크립트 인자에 연결
- 장점 = 유연함. 단점 = 읽기 어렵고, 실행할 때마다 apt · pip 설치

### 2-5. 검증 컴포넌트

검증이 하는 일은 정확도 하나 재는 것보다 넓음.

- 성능 저하 조기 발견
- 데이터 조각별 성능 이해
- 배포 여부 판단 근거
- 성능 이력 보관

```python
@dsl.component(base_image="ultralytics/ultralytics:8.0.194-cpu",   # 의존성 구워진 공식 이미지
               packages_to_install=["minio", "tqdm"])
def validate_model(data_yaml: Input[Artifact], model: Input[Model],
                   validation_dataset: Input[Dataset], metrics: Output[Metrics]):
    from ultralytics import YOLO
    import os
    m = YOLO(os.path.join(model.path, "best.pt"))
    r = m.val(data=os.path.join(data_yaml.path, "data.yaml"), imgsz=640, batch=1)
    metrics.log_metric("map50-95", r.box.map)      # COCO 지표
    metrics.log_metric("map50", r.box.map50)
    metrics.log_metric("map75", r.box.map75)
```

- `requirements.txt` 로 다 깔면 TensorFlow · PyTorch · OpenCV 버전 충돌 = **의존성 지옥** → 공식 베이스 이미지 + 부족한 것만 `packages_to_install`
- 아티팩트 4종 사용 : `Artifact`(설정) · `Model`(가중치) · `Dataset`(검증셋) · `Metrics`(결과)

mAP 읽는 법.

| 지표 | 뜻 |
|---|---|
| `map50` | IoU 0.5 기준 평균 정밀도. 박스가 절반쯤 겹치면 정답 |
| `map75` | IoU 0.75 기준. 박스가 더 정확해야 정답 |
| `map50-95` | IoU 0.5~0.95 구간 평균. COCO 대표 지표, 가장 엄격 |

IoU = 예측 박스와 정답 박스가 겹친 면적 / 합친 면적. 1장의 precision · recall 을 "박스가 얼마나 겹쳐야 맞은 걸로 칠지" 기준별로 계산한 게 mAP 임.

### 2-6. 파이프라인 조립과 실행

<!-- diagram: mlpe-ch08-02-yolo.html -->

```python
@dsl.pipeline(name="YOLO Object Detection Pipeline")
def pipeline(epochs: int = 1, batch: int = 8, random_state: int = 42,
             yolo_model_name: str = "yolov8n_custom"):
    download_op = download_dataset()
    split_op = split_dataset(random_state=random_state,
                             input_dataset=download_op.outputs["output_dataset"])
    train_op = train_model(epochs=epochs, batch=batch, yolo_model_name=yolo_model_name,
                           train_dataset=split_op.outputs["train_dataset"],
                           validation_dataset=split_op.outputs["validation_dataset"],
                           test_dataset=split_op.outputs["test_dataset"])
    validate_model(data_yaml=train_op.outputs["data_yaml"],
                   model=train_op.outputs["model_output"],
                   validation_dataset=split_op.outputs["validation_dataset"])
```

- container_component 도 사용법은 일반 컴포넌트와 같음
- Run 생성 화면의 파라미터 = 파이프라인 함수 기본값으로 자동 채워짐
- 책 환경에서 **1 epoch 약 1시간**
- Ultralytics 로그 : 모델 구조(층·파라미터 수), 옵티마이저, 데이터 수·손상 이미지 수, epoch 별 GPU 메모리·loss·mAP, 남은 시간
- Run output 탭 · Output artifacts 에서 지표 확인, 파이프라인 Run 목록에서 run 끼리 지표 비교

### 2-7. 사람이 직접 확인 - trust, but verify

자동 검증만 믿지 말고 가중치를 받아 직접 돌려볼 것. 책 저자들이 넘겨받은 모델이 한참 뒤에야 안 되는 걸로 밝혀진 경험을 얘기함.

```python
import glob, cv2
from ultralytics import YOLO

model = YOLO("weights/best.pt")            # Output artifacts 에서 받은 tar 안의 best.pt
for f in glob.glob("samples/**.png"):
    res = model(cv2.imread(f))
    cv2.imshow("result", res[0].plot()); cv2.waitKey(0)
```

| 가중치 | 결과 |
|---|---|
| 사전학습 `yolov8n.pt` | 얼굴은 person(0.79), 신분증은 book(0.28) 으로 오분류. 박스 위치는 대체로 맞음 |
| 1 epoch 학습 | id_card 로 맞게 분류. 박스는 카드 대부분만 덮음 |
| 5 epoch 학습 | 카드 전체를 덮고 신뢰도도 괜찮음 |

- 신뢰도(confidence) 0~1. 낮은 탐지는 임계값으로 걸러냄
- `best.pt` = 검증 성능이 가장 좋았던 epoch. 100 epoch 중 4번째일 수도 있음. 다만 epoch 를 너무 적게 주면 best 도 덜 학습된 상태
- 다음 단계 = 이 확인을 자동화. "검증셋 신뢰도 ≥ X, 박스 좌표 허용 오차 내" 같은 조건을 테스트로

### 2-8. 책 vs 현재

| 항목 | 책 | 현재 |
|---|---|---|
| 모델 | YOLOv8n | Ultralytics 8.4 에 YOLO11 · YOLO12 · YOLO26 포함. 같은 API (`YOLO("yolo11n.pt")`) |
| 베이스 이미지 | `python:3.11-slim` 와 `libgl1-mesa-glx` | `libgl1-mesa-glx` 는 Debian 12(bookworm) 부터 저장소에서 빠짐 → 현재 slim(bookworm · trixie)에선 설치 실패. `libgl1` 로 바꾸거나 `opencv-python-headless` 만 쓰면 libGL 자체가 불필요 |
| 검증 이미지 | `ultralytics/ultralytics:8.0.194-cpu` | 9장에선 8.3.56. 버전 태그 고정은 그대로 유지할 것 |
| 컨테이너 컴포넌트 | `@dsl.container_component` | 문법 동일 (KFP 2.18) |
| 라이선스 | 언급 없음 | Ultralytics = **AGPL-3.0**. 사내 서비스에 넣으면 소스 공개 의무 검토 또는 Enterprise 라이선스 |

---

## 3. 실무에서 확인

- **런타임 설치 금지** : 책 container_component 는 실행할 때마다 `apt-get` · `pip install` → 폐쇄망에선 바로 실패, 외부망에서도 실행마다 수 GB 다운로드. 의존성은 CI 에서 이미지로 굽고(사내 Nexus 미러 사용) 컴포넌트는 그 이미지 + 스크립트만 실행
- **스크립트 주입 방식** : heredoc 으로 코드를 문자열 주입하면 리뷰·린트·테스트가 어려움. 학습 스크립트는 이미지 안에 패키지로 넣고 `command: python -m train` 으로 호출하는 게 관리하기 쉬움
- **GPU 지정** : 책 예시는 CPU 기준. B300 노드로 보내려면 `task.set_accelerator_type("nvidia.com/gpu").set_accelerator_limit(1)` + toleration · nodeSelector (`kfp.kubernetes.add_toleration`)
- **학습 시간** : 1 epoch 1시간이면 실험 반복이 느림. 데이터 일부(MINIDATA)로 먼저 확인 → 전체 학습은 야간 recurring run
- **라이선스 검토** : AGPL 모델·라이브러리를 사내 서비스 API 로 제공하는 경우 법무 확인 필요. 대안 = Apache-2.0 계열 탐지 모델(RT-DETR 계열 일부, torchvision detection)
- **지표 저장 위치** : KFP Metrics 는 파이프라인 run 비교에 좋고, 팀·기간 걸친 비교는 MLflow 가 나음 (9장)
- **아티팩트 크기** : project 디렉터리 전체(샘플 이미지·플롯 포함)를 아티팩트로 남기면 run 마다 수백 MB. 필요한 것(`best.pt`, 지표, 대표 플롯)만 남기기

> 주의 : `opencv-python` 과 `opencv-python-headless` 를 같이 설치하면 서로 덮어써서 libGL 오류가 다시 나는 경우가 있음. 서버 이미지는 headless 하나만 유지할 것.

---

## 4. 용어 정리

- **YOLO(You Only Look Once)** : 이미지를 한 번 훑어 객체 위치와 종류를 동시에 예측하는 탐지 모델 계열
- **Ultralytics** : YOLO 학습·검증·추론 파이썬 라이브러리
- **사전학습 가중치(pretrained weights)** : 대규모 데이터로 미리 학습된 시작점. 내 데이터로 이어서 학습(fine-tuning)
- **epoch / batch** : 학습 데이터 전체 1회 순회 / 한 번에 넣는 샘플 수
- **letterbox** : 비율 유지하며 패딩으로 정사각형 맞추기
- **container_component / ContainerSpec** : 이미지·명령·인자를 직접 지정하는 KFP 컴포넌트
- **heredoc** : `<< 'EOF'` 로 여러 줄 문자열을 파일·명령에 넘기는 셸 문법
- **IoU(Intersection over Union)** : 예측 박스와 정답 박스의 겹침 비율
- **mAP(mean Average Precision)** : 클래스·IoU 기준별 평균 정밀도. 탐지 모델 대표 지표
- **신뢰도(confidence score)** : 탐지 결과에 대한 모델 확신 정도 0~1
- **best.pt** : 학습 중 검증 성능이 가장 좋았던 가중치

---

## 5. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 채운 블록 | 모델 학습(4) · 평가 검증(5) |
| YOLO 설정 | data.yaml (경로 · 클래스) + `model.train()` |
| 모델 크기 | Nano 로 가능성 확인 후 키움. 요구사항과 trade-off 우선 |
| 시스템 의존성 | `@dsl.container_component` 와 ContainerSpec 으로 apt · pip · 스크립트 실행 |
| 검증 | 공식 베이스 이미지 + `model.val()` → mAP 를 `Metrics` 로 기록 |
| 파이프라인 | download → split → train → validate, 결과는 KFP UI 에서 비교 |
| 수동 확인 | best.pt 로 직접 추론. 1 → 5 epoch 에서 눈에 띄게 개선 |
| 현재 기준 보완 | YOLO11 · 26, libgl1 패키지명, AGPL 라이선스 |
| 실무 | 의존성은 이미지로, GPU 지정, 일부 데이터로 먼저 확인 |

**학습은 라이브러리가 하고, 플랫폼은 그 학습을 재현 가능하게 반복시키는 일을 함. 자동 지표와 사람의 눈 확인을 같이 가져가야 믿을 수 있는 모델이 된다.**

다음 글 : 9장 Model training and validation Part 2 - PVC 로 데이터 공유, TensorBoard · MLflow 추적, 추천 모델 레지스트리 승격
