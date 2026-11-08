## Local AI Models on a Mac - Ollama·Whisper·Streamlit 음성 챗봇

> **목표** : Mac 한 대에서 Ollama + MLX Whisper + Streamlit 으로 완전 로컬 음성 챗봇을 만드는 책 한 권을 구조 중심으로 정리함

- 출처 : Keiji Kamigusa, *Build Applications with Local AI Models on a Mac* (Manning liveBook, 2026-09), 18장 + 부록 2
- 예제 코드 : `github.com/kamigusa/building_your_own_ai_on_mac`
- 기준 버전 : 책 예시 = Ollama 0.6.2, Python 3.13, ollama-python 0.4.7, streamlit 1.41.1, 기본 모델 `gemma3:4b` / 현재 확인 = Ollama 0.40.11, ollama-python 0.6.3, streamlit 1.66.1, mlx-whisper 0.4.3, chromadb 1.5.9 (2026-10 기준)

---

## 1. 개요

- 프로그래밍 경험 없는 사람 기준으로 터미널 여는 것부터 시작하는 입문서
- 3부 구성 → Part 1 환경(1~3장), Part 2 챗봇 제작(4~11장), Part 3 모델 선택·튜닝·확장(12~18장)
- 완성물 = 브라우저에서 말하면 Whisper 가 받아 적고 Ollama 가 답하는 음성 챗봇. 데이터가 Mac 밖으로 안 나감

<!-- diagram: localai-overview.html -->

**도구 5개(Ollama, MLX Whisper, Python, Streamlit, VS Code)를 하나씩 붙여 가는 구조라, 각 장이 앞 장 결과물 위에 한 층씩 쌓인다**

> 주의 : Part 3 소개문은 17장 = 로드맵, 18장 = 2026 모델 지형이라고 적었지만 실제 본문은 반대임 (17장 = 2026 오픈모델, 18장 = 로드맵)

---

## 2. 개념 정리

### 2-1. 왜 로컬인가

- 이유 4가지 → 프라이버시, 음성 프라이버시, 약관·가격 변경에서 자유, 직접 조립하며 구조 이해
- 클라우드와 양자택일 아님. 최신 정보·복잡한 추론 = 클라우드, 민감 데이터·오프라인·학습 목적 = 로컬

| 항목 | 클라우드 | 로컬 (Ollama) |
|---|---|---|
| 모델 크기 | 수천억 파라미터 | 1B~70B |
| 최신성 | 계속 갱신 | 학습 시점에서 멈춤 |
| 데이터 | 업체 서버로 전송 | 기기 밖으로 안 나감 |
| 비용 | 월 구독 또는 토큰 과금 | 전기료만 |
| 인터넷 | 항상 필요 | 모델 pull 할 때만 |
| 커스터마이징 | 서비스가 허용하는 만큼 | 모델·파라미터 전부 통제 |

- LLM = 다음 토큰을 확률로 고르는 모델. 사실을 꺼내는 게 아니라 패턴으로 추측함 → 환각(hallucination) 생김

### 2-2. Ollama - 모델 실행기

- Ollama 는 AI 가 아니라 실행기(runtime). 비유하면 음악 플레이어, 모델은 곡
- `ollama serve` 가 `127.0.0.1:11434` 에서 대기 → 터미널·Python·브라우저 요청을 동시에 받음
- 첫 요청 때 디스크의 모델을 통합 메모리(unified memory)에 올림. 마지막 사용 후 몇 분 지나면 자동 언로드

<!-- diagram: localai-ollama.html -->

- 모델 이름 = `패밀리:태그` → `gemma3:4b` 는 Gemma 3 계열의 4B 변형. 태그 생략 시 `latest`
- 양자화(quantization) = 가중치 정밀도를 낮춰 메모리 절약. Q4 는 Q8 의 약 절반 크기

| 크기 | RAM | 용도 |
|---|---|---|
| 1~3B | 2~4GB | 간단한 Q&A, 텍스트 정리 |
| 7~9B | 5~8GB | 일반 대화, 글쓰기, 코딩 보조 |
| 13~14B | 10~16GB | 복잡한 분석 |
| 27~32B | 20~32GB | 고급 추론 |
| 70B 이상 | 40GB 이상 | 연구급 |

> 주의 : `ollama serve` 를 띄운 터미널 창은 서버가 점유함. 명령은 두 번째 창에서 쳐야 함. 책이 꼽은 입문자 최다 막힘 지점임

### 2-3. ollama.chat - 역할과 스트리밍

- 책 전체가 `ollama.chat()` 하나만 씀 (`generate` 안 씀)
- 메시지 역할(role) 3개 → `system` = 성격·규칙, `user` = 사람 입력, `assistant` = 이전 답변
- `stream=True` = 응답을 토큰 단위로 받음. 총 생성 시간은 같고 체감만 빨라짐
- **LLM 은 기억이 없음(stateless). 기억하는 것처럼 보이려면 앱이 매번 전체 대화를 다시 보내야 한다**

```python
import ollama

history = [{"role": "system", "content": "답은 두세 문장으로 짧게"}]
history.append({"role": "user", "content": "양자화가 뭐야?"})

reply = ""
for chunk in ollama.chat(model="gemma3:4b", messages=history, stream=True):
    piece = chunk["message"]["content"]
    print(piece, end="", flush=True)   # 줄바꿈 없이 바로 출력
    reply += piece
history.append({"role": "assistant", "content": reply})   # 다음 턴에 같이 보냄
```

### 2-4. Streamlit - 매번 처음부터 다시 실행

- Python 파일 하나로 웹 화면을 만드는 프레임워크. 실행은 `streamlit run app.py`, 기본 포트 8501
- 사용자가 뭘 누를 때마다 스크립트 전체를 위에서 아래로 다시 실행(rerun)함 → 콜백 없이 단순함
- 단, 일반 변수는 rerun 마다 초기화됨 → 남겨야 할 값은 `st.session_state` 에 둠
- 배치 관례 = 설정은 sidebar, 대화는 main

### 2-5. MLX Whisper - 음성을 텍스트로

- Whisper = OpenAI 의 음성 인식 모델 (2022, 68만 시간 다국어 학습)
- 원본은 PyTorch 라 Mac 에서는 CPU 로 돎. MLX 포트는 Apple Silicon GPU 를 써서 책 측정 기준 4~6배 빠름
- 녹음 규칙 3개 → 16kHz(Whisper 학습 주파수), mono, float32 로 받고 WAV 는 int16 으로 저장

| 모델 | 파라미터 | 다운로드 | RAM | 30초 처리 |
|---|---|---|---|---|
| tiny | 39M | 약 75MB | 약 200MB | 약 1초 |
| small | 244M | 약 480MB | 약 800MB | 약 4초 |
| medium | 769M | 약 1.4GB | 약 2GB | 약 8초 |
| large-v3 | 1550M | 약 2.9GB | 약 4GB | 약 18초 |

- 모델은 `mlx-community/whisper-{size}-mlx` 레포에서 받아 `~/.cache/huggingface/hub/` 에 캐시함
- 선택 기준 → 8GB 는 small, 16GB 이상은 medium 부터, 정확도 우선이면 large-v3
- 측정 환경은 Mac Mini M2 8GB. 보장값 아님

> 주의 : 책 본문은 small 크기를 약 244MB 로, 표는 약 480MB 로 적음. 244M 은 파라미터 수와 섞인 것으로 보임

---

## 3. 구조 - 최종 음성 챗봇

### 3-1. 데이터 흐름

<!-- diagram: localai-arch.html -->

- 녹음은 9장의 `sounddevice` 대신 브라우저 쪽 `st.audio_input()` 을 씀 → WAV bytes 가 Python 으로 넘어옴
- Whisper 가 파일 경로를 받기 때문에 임시 WAV 를 만들고 `try/finally` 로 바로 지움 → 오디오가 디스크에 안 남음
- 음성·텍스트 입력이 `handle_user_message()` 하나로 모임 → LLM 입장에서는 입력 출처 무관, 입력 방식 추가가 쉬움
- 파일 구성 = `voice_chat.py`, `model_config.json`(모델 목록·기본값), `setup_ollama.sh`(서버 기동·모델 pull)

| 단계 | 시간 (M2 8GB, 5초 음성) |
|---|---|
| 업로드 | 약 0.1초 |
| Whisper small 전사 | 약 1.5초 |
| Ollama 첫 토큰 (gemma3:4b) | 약 0.5초 |
| 첫 단어까지 | 약 2.1초 |

- 말한 뒤 침묵은 못 참고, 생성이 느린 건 참음 → 전사 중에는 `st.spinner` 로 진행 표시

### 3-2. 대화 기록 관리

- 20~30턴 넘으면 반복·모순·지연이 생김 → 고장이 아니라 컨텍스트 창(context window) 한계다
- 두 문제를 분리함 → 화면에 보일 기록 저장, 모델에 보낼 양 조절

<!-- diagram: localai-history.html -->

```python
max_history = 10                           # 사이드바 슬라이더 값 (대화 쌍 수)
max_messages = max_history * 2 + 1         # 완료된 N쌍 + 지금 질문 1개
to_model = st.session_state.messages[-max_messages:]   # 모델엔 최근만
```

- 화면 = 전체 기록, 모델 = 최근 21개 (슬라이딩 윈도우)
- 응답이 끝나면 assistant 메시지를 `session_state` 에 다시 append 함
- 토큰 어림 = 글자 수 ÷ 4. 응답 하나 200~500 토큰 → 20턴이면 5,000~10,000 토큰
- 단, 개수 기준이라 아주 긴 메시지면 여전히 넘침. 대안은 요약 삽입 또는 RAG
- `session_state` 는 탭 닫기·새로고침·서버 재시작 시 사라짐. 디스크 저장은 연습문제로만 다룸

> 주의 : 10장 `voice_chat.py` 는 기록을 자르지 않고 전부 보냄. 자르기는 11장 텍스트 챗봇에서만 시연함

---

## 4. 비교 - 모델 선택과 동작 바꾸기

### 4-1. 모델 고르기

- RAM 이 하드 리밋. 넘치면 스왑으로 50~100배 느려짐 → 빠른 작은 모델이 느린 큰 모델보다 낫다
- 8GB 머신은 OS·브라우저 빼면 모델에 2~4GB 정도만 남음

| RAM | 권장 최대 | 예 |
|---|---|---|
| 8GB | 2~3B | gemma2:2b, llama3.2:3b |
| 16GB | 7~9B | llama3.1:8b, gemma2:9b |
| 32GB | 14~27B | qwen2.5:14b, gemma2:27b |
| 64GB 이상 | 70B | llama3.1:70b |

| 계열 | 강점 | 언제 쓰나 |
|---|---|---|
| Gemma (Google) | 체급 대비 성능 | 책 기본 경로, 작은 Mac |
| Llama (Meta) | 범용, 커뮤니티 큼 | 고민되면 출발점 |
| Qwen (Alibaba) | 다국어, 코딩·수학 | 한·중·일 언어 |
| Mistral | 유럽어, 추론 | 유럽어 위주 |
| DeepSeek | 추론(R1), 저비용 학습 | 추론 실험 |

- MoE(mixture of experts) = 전체 파라미터 = 지식 용량, 활성 파라미터 = 토큰당 연산량. `A3B` = 토큰당 3B 활성
- 벤치마크는 참고만. 같은 질문을 여러 모델에 던져 시간·품질을 직접 비교하라는 입장

### 4-2. 동작 바꾸기 - 가벼운 것부터

<!-- diagram: localai-custom.html -->

| 방법 | 바뀌는 것 | 비유 |
|---|---|---|
| System prompt | 성격·형식 | 지시 |
| 생성 파라미터 | 답의 다양성 | 말투 온도 |
| RAG | 참고할 지식 | 참고서 |
| 파인튜닝 | 근본 행동 | 재교육 |

| 파라미터 | 책 시작값 | 낮으면 / 높으면 |
|---|---|---|
| temperature | 0.7 | 보수적 / 창의적, 1.5 이상은 횡설수설 위험 |
| top_k | 40 | 후보 고정 개수, 작으면 집중 |
| top_p | 0.9 | 누적 확률 기준 가변 후보 |
| repeat_penalty | 1.1 | 반복 억제, 과하면 어색 |
| num_ctx | 보통 2048 | 늘리면 긴 대화 가능, RAM 증가 |

- 대부분 temperature 만 만져도 충분하다
- Modelfile = 베이스 모델 위에 설정 레이어만 얹는 파일. 가중치 복제 없음

```text
FROM gemma3:4b
PARAMETER temperature 0.8
PARAMETER num_ctx 4096
SYSTEM """비유를 들어 설명하고, 마지막에 더 알고 싶은지 물어봄"""
```

- `ollama create studybuddy -f Modelfile` → `ollama run studybuddy`

### 4-3. RAG - 내 문서를 근거로

<!-- diagram: localai-rag.html -->

- 문서를 약 500자씩 자르고 벡터로 바꿔 ChromaDB 에 넣음 → 질문도 벡터로 바꿔 가까운 조각을 찾아 프롬프트에 넣음
- 지시문에 "context 에 없으면 모른다고 답하라" 를 넣어 환각을 줄임
- 책 예제는 별도 임베딩 모델을 지정하지 않음 → ChromaDB 기본 임베딩에 문서를 바로 넣는 방식
- 확장 지도 → Open WebUI(Docker, 완성형 UI·내장 RAG), LangChain(`prompt | llm | parser` 체인), 에이전트(도구 호출 루프, 7B 이상부터 쓸 만함)

### 4-4. 파인튜닝과 GGUF

- 흐름 = 입출력 쌍 JSONL → Unsloth 로 학습(Colab) → GGUF 로 export → Modelfile `FROM ./x.gguf` → `ollama create`
- GGUF = 소비자 하드웨어용 양자화 모델 표준 포맷

| 포맷 | 7B 파일 | 품질 손실 | 용도 |
|---|---|---|---|
| F16 | 약 14GB | 없음 | 최고 품질 |
| Q8_0 | 약 8GB | 거의 없음 | 준무손실 |
| Q4_K_M | 약 4.6GB | 작음 | 균형, Ollama 대부분 기본 |
| Q2_K | 약 2.7GB | 큼 | 실험용 |

### 4-5. 오프라인·비용·2026 오픈모델

- 오프라인 검증 = Wi-Fi 끄고 `ping` 실패 확인 후 대화·모델 전환·파라미터 변경까지 해 봄 (비행기 모드 테스트)
- 비용 → 구독 약 $20/월, API 는 헤비 사용 시 월 $100~500 이상, 로컬은 하드웨어만. 단, 팀 공유 배포는 운영·보안 비용이 붙음
- 2026-02 오픈모델 3종이 주요 벤치에서 상용과 대등했다는 게 17장 주장

| 모델 | 규모 (전체 / 활성) | 라이선스 | 책 서술 |
|---|---|---|---|
| GLM-5 (Zhipu) | 744B / 약 40B | MIT | Huawei Ascend 로만 학습 |
| Qwen3-Coder-Next | 80B / 3B | Open | 코딩 에이전트용, Ollama 공식 태그 있음 |
| MiniMax M2.5 | 230B / 약 10B | Modified-MIT | API 가 상용 대비 약 1/20 가격 |

- 벤치 수치는 벤더 자체 보고. 통제 비교 아님
- 활성 3B 라도 q4 가중치 다운로드는 약 52GB → "활성 파라미터가 작으니 16GB 에 들어간다" 고 가정하면 안 됨

> 주의 : 책 안에서 GLM-5 출시일(2월 11일 / 12일), GPT-5.2·Opus 출력 단가(표 16.1 / 17.1)가 서로 다르게 적힘. 날짜가 명시된 표 16.1 을 기준으로 봄

---

## 5. 사용법 예시

### 5-1. 설치 (Apple Silicon)

```bash
brew install ollama python@3.13 ffmpeg
ollama serve                         # 이 창은 서버 전용으로 둠
# 새 창
ollama pull gemma3:4b                # 약 3.3GB
mkdir ~/my-ai-chatbot && cd ~/my-ai-chatbot
python3.13 -m venv .venv && source .venv/bin/activate
pip install ollama streamlit mlx-whisper
pip freeze > requirements.txt
```

### 5-2. 최소 음성 챗봇 (개념 코드)

```python
# app.py - 책 10장 구조를 줄인 개념 코드
import os, tempfile
import ollama, mlx_whisper, streamlit as st

st.set_page_config(page_title="Voice AI Chat")          # 첫 Streamlit 호출
if "messages" not in st.session_state:
    st.session_state.messages = []                      # rerun 에도 유지

def transcribe(audio):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio.read()); path = f.name
    try:
        r = mlx_whisper.transcribe(path, path_or_hf_repo="mlx-community/whisper-small-mlx")
        return r["text"].strip()
    finally:
        os.unlink(path)                                 # 녹음 파일 즉시 삭제

def handle(text):                                        # 음성·텍스트 공통 진입점
    st.session_state.messages.append({"role": "user", "content": text})
    with st.chat_message("assistant"):
        out = st.write_stream(
            c["message"]["content"]
            for c in ollama.chat(model="gemma3:4b", messages=st.session_state.messages, stream=True))
    st.session_state.messages.append({"role": "assistant", "content": out})

for m in st.session_state.messages:
    st.chat_message(m["role"]).write(m["content"])

audio = st.audio_input("말하기")
if audio and hash(audio.getvalue()) != st.session_state.get("last_audio"):
    st.session_state.last_audio = hash(audio.getvalue())   # 같은 녹음 재처리 방지
    if text := transcribe(audio):
        handle(text)
if prompt := st.chat_input("입력"):
    handle(prompt)
```

- 실행 = `streamlit run app.py` → `http://localhost:8501`
- 책 원본은 `st.empty()` 에 토큰을 누적하는 방식. 위 코드는 `st.write_stream` 으로 줄인 버전임
- `st.audio_input` 은 rerun 때마다 마지막 녹음을 계속 돌려줌 → 해시로 처리한 녹음을 기억해 두지 않으면 텍스트 입력 때 직전 음성이 또 들어감

### 5-3. 사내 GPU 노드에 Ollama 올릴 때 (개념 코드)

```yaml
# 책 범위 밖. 폐쇄망 K8s 에서 개인 실험용으로 띄울 때의 최소 형태
apiVersion: apps/v1
kind: Deployment
metadata: { name: ollama, namespace: user-woong }
spec:
  replicas: 1
  selector: { matchLabels: { app: ollama } }
  template:
    metadata: { labels: { app: ollama } }
    spec:
      containers:
        - name: ollama
          image: dmz-nexus.example/ollama/ollama:0.40.11   # 미러링한 이미지
          env:
            - { name: OLLAMA_HOST, value: "0.0.0.0:11434" }  # 파드 안에서만 열고 Service 로 제한
            - { name: OLLAMA_MODELS, value: /models }
          ports: [{ containerPort: 11434 }]
          resources: { limits: { nvidia.com/gpu: 1 } }
          volumeMounts: [{ name: models, mountPath: /models }]
      volumes:
        - name: models
          persistentVolumeClaim: { claimName: ollama-models }   # 미리 받아 둔 모델 적재
```

---

## 6. 실무에서 확인

### 6-1. 내 Mac 기준

- M1 Pro 16GB = 책 표 기준 7~9B 구간. 앞서 계산한 결과도 8B Q4 가 대화용 상한
- 음성 챗봇 조합 → `gemma3:4b` + whisper medium 이 메모리 여유 있는 선택. 8B 를 쓰면 whisper 는 small 로 내림
- `num_ctx` 기본이 작게 잡히는 경우가 많음 → 긴 대화 테스트 전에 `ollama ps` 로 실제 할당 확인

### 6-2. 폐쇄망 K8s 로 가져갈 때

- 모델 반입 → `ollama pull` 은 registry.ollama.ai 로 나감. 폐쇄망은 외부망에서 받은 `~/.ollama/models` 를 반입하거나 GGUF 를 Nexus HF 프록시로 받아 Modelfile `FROM ./x.gguf` 로 등록
- Whisper 모델 → `path_or_hf_repo` 가 HF 허브로 나감. HF 프록시 경유(`HF_ENDPOINT`) 또는 로컬 폴더 경로 지정
- 인증 → Ollama API 자체에 인증 없음. `0.0.0.0` 노출 금지, Service 는 ClusterIP 로 두고 Cilium NetworkPolicy 로 해당 네임스페이스만 허용
- 사용자용 UI → Open WebUI 는 OIDC 연동이 있어 Keycloak 에 붙일 수 있음. 단, 대화 DB 를 사용자별로 분리할지 먼저 정해야 함
- 서빙 규모 → Ollama 는 1인·소수 동시 요청 전제. B300 노드에서 다수 사용자 서빙은 vLLM 쪽이 맞음 (배치·KV 캐시 관리)
- RAG 저장소 → 실험은 ChromaDB 로 충분. 공용 지식베이스로 가면 AIStor 에 원본 두고 벡터 DB 는 별도 운영 필요

> 주의 : 책 예시 버전(Ollama 0.6.2)과 현재(0.40.11) 차이가 큼. 명령 형식은 같지만 모델 태그·기본값은 바뀌었을 수 있음 → `ollama show` 로 직접 확인

---

## 7. 용어 정리

- **실행기(runtime)** : 모델을 받아 메모리에 올리고 요청을 처리하는 프로그램. Ollama 의 정체
- **통합 메모리(unified memory)** : CPU·GPU·Neural Engine 이 같은 RAM 을 공유하는 Apple Silicon 구조. 복사 없이 GPU 로 추론
- **양자화(quantization)** : 가중치 비트 수를 줄여 메모리를 아끼는 기법. Q4_K_M 이 균형점
- **GGUF** : 양자화 모델을 담는 표준 파일 포맷. Ollama·llama.cpp 가 읽음
- **역할(role)** : 메시지 종류. system / user / assistant
- **스트리밍(streaming)** : 토큰을 생성되는 대로 받는 방식. 체감 속도만 개선
- **stateless** : 호출 간 기억이 없음. 대화 맥락은 앱이 매번 다시 보냄
- **컨텍스트 창(context window)** : 한 번에 모델에 넣을 수 있는 토큰 한도. `num_ctx` 로 할당
- **session_state** : Streamlit rerun 에도 살아남는 딕셔너리. 앱 메모리이지 모델 메모리 아님
- **MoE(mixture of experts)** : 토큰마다 일부 전문가만 쓰는 구조. 전체 = 지식, 활성 = 연산량
- **Modelfile** : 베이스 모델에 system prompt·파라미터를 얹는 설정 파일
- **RAG(retrieval-augmented generation)** : 검색한 문서 조각을 프롬프트에 넣어 근거 기반으로 답하게 하는 방식

---

## 8. 한 장 요약

| 항목 | 핵심 |
|---|---|
| 정체 | Ollama, MLX Whisper, Streamlit 으로 Mac 안에서 끝나는 음성 챗봇 제작 입문서 |
| Ollama | 11434 포트 서버, 첫 요청 때 모델을 통합 메모리에 로드 |
| 대화 | LLM 은 stateless, 앱이 기록을 매번 다시 보냄 |
| Streamlit | 상호작용마다 전체 rerun, 남길 값은 session_state |
| 음성 | 16kHz mono 녹음, MLX Whisper small 기준 약 1.5초 전사 |
| 기록 관리 | 화면은 전체, 모델엔 최근 2N+1 개만 |
| 모델 선택 | RAM 이 하드 리밋, 8GB 는 2~3B, 16GB 는 7~9B |
| 동작 변경 | system prompt, 파라미터, Modelfile, RAG, 파인튜닝 순으로 무거워짐 |
| 실무 | 폐쇄망은 모델 반입·인증 부재·동시성 한계부터 해결 |

**로컬 LLM 앱의 뼈대는 모델 연결, 기록 관리, 입력 통합 세 가지이고, 나머지는 그 위에 얹는 옵션이다**

관련 글 : 내 MacBook 스펙 결과 · Mac 사양 확인 - Python 실습 프로그램 · Hands-On LLM Serving and Optimization Study
