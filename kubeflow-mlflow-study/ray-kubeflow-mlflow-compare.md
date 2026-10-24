## Ray · Kubeflow · MLflow 비교 - 기능, 장단점, 활용

> **목표** : 세 도구가 맡는 층을 구분하고, 기능·장단점·활용 조합을 한 장에 정리

- 기준 버전 : Ray 2.59 / KubeRay 1.7, Kubeflow 26.03.1, MLflow 3.17 (mlflow-integration v2.1)
- 관련 글 : Ray 스터디, Kubeflow + MLflow 통합 스터디, MLflow 스터디

---

## 1. 개요

셋은 경쟁 관계가 아님. 맡는 층이 다름.

- **Kubeflow** = 플랫폼. 누가, 어떤 순서로, 어느 네임스페이스에서 돌리는지 관리
- **Ray** = 계산 엔진. 무거운 파이썬 계산을 여러 노드로 쪼개 실행
- **MLflow** = 장부. 실행 결과·모델·trace 를 남기고 배포할 버전 고름

<!-- diagram: mlpe-cmp-01-stack.html -->

**Kubeflow 가 판을 깔고, Ray 가 계산하고, MLflow 가 기록함.**

---

## 2. 기능 비교표

| 기능 영역 | Ray (+ KubeRay) | Kubeflow | MLflow |
|---|---|---|---|
| 핵심 정체 | 파이썬 분산 실행 엔진 | K8s 네이티브 ML 플랫폼 | ML·LLM 기록·관리 플랫폼 |
| 실행 단위 | Task·Actor (프로세스) | 단계별 Pod·CRD | 없음 (실행 안 함) |
| 워크플로·DAG | 없음. 코드 흐름 그대로 | KFP. 캐싱·재실행·리니지 | 없음 |
| 데이터 전처리 | Ray Data | Spark Operator | 없음 (Dataset 추적만) |
| 분산 학습 | Ray Train | Trainer (TrainJob) | 없음 |
| 하이퍼파라미터 튜닝 | Ray Tune | Katib | 없음 (결과 비교만) |
| 실험 추적 | 없음 | 약함 → MLflow 채택 (KEP-897) | 핵심 기능. autolog |
| 모델 레지스트리 | 없음 | Hub (구 Model Registry) | Registered Model + alias |
| 서빙 | Ray Serve / RayService | KServe | `models serve`, KServe 로 위임 |
| LLM 운영 | Ray LLM (vLLM 배치·서빙) | KServe LLMInferenceService | Tracing, 평가, 프롬프트, AI Gateway |
| 노트북 | 없음 | Notebooks (v2 alpha) | 없음 |
| 멀티테넌시 | 없음. ns 별 RayCluster | Profile = ns + Istio + RBAC | Workspaces + K8s RBAC 플러그인 |
| 오토스케일 | 자원 요청 기반 Pod 증감 | K8s HPA·KServe | 해당 없음 |
| 저장소 | 노드 공유 메모리 | 아티팩트 MinIO | PostgreSQL + MinIO |
| 설치 단위 | 오퍼레이터 1개 + CRD | 컴포넌트 다수 + Istio·Dex | 서버 1개 + DB + 버킷 |

---

## 3. 장단점 비교표

| 구분 | 장점 | 단점 |
|---|---|---|
| Ray | 파이썬 코드 그대로 수천 노드 확장 | 플랫폼 기능 없음 (DAG, 권한, 추적) |
| | Data → Train → Serve 가 한 런타임, 디스크 왕복 없음 | head 노드 단일 장애점. GCS FT 별도 구성 |
| | LLM 배치 추론·RL 후학습 생태계 강함 | 버전 일치 엄격 (head·worker·클라이언트·파이썬) |
| | 설치 가벼움 | 오토스케일이 자원 요청 기준이라 실제 부하와 어긋날 수 있음 |
| Kubeflow | 멀티테넌시·권한·감사 체계 완비 | 설치·업그레이드 무거움 (Istio, Dex, cert-manager) |
| | KFP 로 재현 가능한 파이프라인, 캐싱 | 단계마다 Pod 기동 → 짧은 단계 많으면 느림 |
| | 이질적 단계 조합 가능 (컨테이너면 다 됨) | 컴포넌트마다 성숙도 차이 큼 |
| | K8s 네이티브 → GitOps·RBAC 그대로 | 실험 추적 약함 → 외부 도구 필요 |
| MLflow | 사실상 표준 실험 추적. 프레임워크 지원 넓음 | 계산·스케줄링 없음 |
| | 모델 버전·alias 로 배포 대상 명확 | 자체 권한 약함 → 플러그인·프록시 필요 |
| | GenAI 트레이싱·평가·프롬프트까지 한 서버 | 메트릭 테이블 비대화, 정리 정책 필요 |
| | 서버 단순. 무상태라 증설 쉬움 | 마이너 버전마다 스키마 마이그레이션 |

---

## 4. 활용 정리표

| 상황 | 추천 조합 | 이유 |
|---|---|---|
| 데이터 사이언티스트 1~2명, 빠른 실험 | MLflow 단독 (+ 로컬 Ray) | 기록만 있으면 충분. 플랫폼 과함 |
| GPU 다수 분산 학습·튜닝 | Ray (KubeRay RayJob) + MLflow | 계산은 Ray, 결과 비교·등록은 MLflow |
| LLM 배치 추론·파인튜닝 | Ray LLM / Ray Train + MLflow | vLLM 연동, 트라이얼 가벼움 |
| LLM 앱·에이전트 운영 | MLflow (Tracing, 평가, Gateway) + KServe | trace 기반 품질 관리, 키·예산 중앙화 |
| 여러 팀 공유 ML 플랫폼 | Kubeflow + MLflow (mlflow-integration) | ns·RBAC 로 팀 격리, 실험 추적 통일 |
| 재현성·감사 중요 (규제) | Kubeflow KFP + MLflow | 파이프라인 리니지 + run 기록 |
| 대규모 공유 + 무거운 계산 | Kubeflow + Ray + MLflow | KFP 가 순서, RayJob 이 계산, MLflow 가 기록 |
| 정기 배치 재학습 | KFP 스케줄 또는 RayCronJob + MLflow alias 교체 | 트리거 → 학습 → alias 승격 자동화 |

---

## 5. 같이 쓰는 표준 흐름

1. 사용자가 Kubeflow Notebook (team-a ns) 에서 개발
2. KFP 파이프라인 실행 → 전처리·학습 단계 생성
3. 무거운 학습은 RayJob 으로 위임 → KubeRay 가 잡용 RayCluster 생성·삭제
4. 학습 코드가 MLflow 워크스페이스 team-a 에 param·metric·모델 기록
5. 평가 통과 모델 → Registered Model 버전 등록 → `@champion` alias 지정
6. KServe 또는 RayService 가 `models:/name@champion` 로드
7. 운영 지표·trace → MLflow 로 다시 수집 → 재학습 트리거

> 주의 : 셋 다 넣으면 운영 대상이 3배임. 처음부터 다 깔지 말고 MLflow → Ray → Kubeflow 순으로 필요할 때 붙일 것.

---

## 6. 실무에서 확인

- **현 환경 기준 출발점** : 사용자별 네임스페이스 + MinIO 이미 있음 → MLflow(+ mlflow-integration) 가 도입 비용 제일 낮음
- **GPU 클러스터 (B300 등)** : 학습 엔진으로 Ray 먼저 검토. Kueue 갱 스케줄링 같이
- **Kubeflow 전체 도입** : Istio·Dex 운영 부담 큼. KFP 단독(standalone) 설치 후 필요하면 확장
- **인증 통일** : Keycloak → oauth2-proxy → (KFP, MLflow SAR 모드, Ray 대시보드) 같은 헤더 체계로 맞출 것
- **폐쇄망** : 세 도구 모두 이미지·차트 미러링 필요. MLflow GenAI, Ray LLM 은 사내 LLM 엔드포인트로 치환

---

## 7. 한 장 요약

| 항목 | Ray | Kubeflow | MLflow |
|---|---|---|---|
| 한 줄 정의 | 계산 엔진 | 플랫폼·워크플로 | 기록·레지스트리 |
| 강한 곳 | 분산 학습·추론, LLM | 멀티테넌시, 파이프라인 | 실험 추적, 모델 버전, GenAI 관측 |
| 약한 곳 | 플랫폼 기능 | 무거움, 실험 추적 | 계산·권한 |
| K8s 연결 | KubeRay CRD | 그 자체가 K8s 앱 | mlflow-integration 플러그인 |
| 도입 순서 | 2 | 3 | 1 |

**셋은 대체 관계가 아니라 층이 다름. 기록(MLflow) → 계산(Ray) → 플랫폼(Kubeflow) 순으로 필요할 때 쌓는 게 현실적임.**
