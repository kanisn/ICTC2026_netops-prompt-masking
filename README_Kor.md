# NetOps Input-Prompt Masking (한국어)

ICTC 2026 논문 *"Privacy in LLM-Based Network Operations Agents: A Lifecycle
Taxonomy, Risk-to-Guardrail Mapping, and an Input-Prompt Masking Case Study"*
의 재현용 파이프라인입니다.

마스킹·복원(unmask)·평가는 전부 로컬에서 결정적으로 수행하고, LLM은 마스킹된
입력만 봅니다(provider 비종속 래퍼). 실행 시 모델(Claude / GPT / Gemini / Mock)을
고르며, 출력은 모델별로 분리되어 저장됩니다.

> 영어 정본은 `README.md` 입니다. 본 문서는 한국어 정리본입니다.

---

## 1. 사전 준비 (설치)

- **Python 3.10 이상 권장** (3.9도 동작하지만 google-auth의 무해한 "수명 종료"
  경고가 뜹니다 — 코드에서 이미 숨김 처리).
- 사용할 모델에 맞는 라이브러리를 설치합니다.

```bash
# (선택) 가상환경 생성·활성화
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

# 전체 설치
pip install -r requirements.txt

# ...또는 필요한 것만
pip install anthropic        # Claude
pip install openai           # GPT
pip install google-genai     # Gemini
# Mock 모드는 추가 설치 불필요(표준 라이브러리만 사용)
```

`requirements.txt`:
```
anthropic>=0.40        # Claude (claude-haiku-4-5)
openai>=1.40           # GPT   (gpt-5.4-mini)
google-genai>=1.0      # Gemini (gemini-3.1-flash-lite)
```

---

## 2. API 키 발급

| 모델 | 키 발급 사이트 | 환경변수 |
|---|---|---|
| **Claude** | Anthropic Console → API Keys: https://console.anthropic.com/settings/keys | `ANTHROPIC_API_KEY` |
| **GPT** | OpenAI Platform → API keys: https://platform.openai.com/api-keys | `OPENAI_API_KEY` |
| **Gemini** | Google AI Studio → API keys: https://aistudio.google.com/apikey | `GOOGLE_API_KEY` |
| **Mock** | 불필요(오프라인 테스트) | — |

키를 넣는 방법은 두 가지입니다.

1. **프롬프트에 입력** — 실행하면 키를 물어봅니다(붙여넣기 가능, 단 화면에 키가
   보입니다).
2. **환경변수로 미리 설정** — 미리 넣어두면 프롬프트가 안 뜨고 키도 숨겨집니다.
   예(PowerShell):
   ```powershell
   $env:GOOGLE_API_KEY="여기에-키"
   ```
   PyCharm이면: Run → Edit Configurations → *Environment variables*.

---

## 3. 실행

```bash
python run_experiment.py     # 모델 선택(1-4) → API 키 입력
python evaluate.py           # 같은 모델 선택 → 채점
```

`run_experiment.py` 실행 시 메뉴:
```
Which model do you want to run?
  1) Claude (Haiku)                 [claude-haiku-4-5-20251001]
  2) GPT (gpt-5.4-mini)             [gpt-5.4-mini]
  3) Gemini (gemini-3.1-flash-lite) [gemini-3.1-flash-lite]
  4) Mock (offline, no key needed)  [mock-model]
Select a number (1-4):
```

**순서가 중요합니다.** 반드시 `run_experiment.py`(결과 파일 생성)를 먼저,
그다음 같은 모델로 `evaluate.py`를 실행하세요.

세 모델을 모두 돌리려면 두 명령을 모델만 바꿔 반복하면 됩니다 — 출력 파일이
모델별로 분리되어 서로 덮어쓰지 않습니다(아래 참조).

### 비대화형(CI/스크립트)
```bash
EXP_NONINTERACTIVE=1 EXP_PROVIDER=gemini GOOGLE_API_KEY=... python run_experiment.py
EXP_NONINTERACTIVE=1 EXP_PROVIDER=gemini python evaluate.py
```
`EXP_PROVIDER` 값: `claude|gpt|gemini|mock` (또는 `anthropic|openai|google`).
추가 옵션: `EXP_MODEL`, `EXP_TAG`, `EXP_DATASET`, `EXP_OUT`.

---

## 4. 출력 파일 (모델별 분리)

각 모델은 `outputs/` 아래에 모델 태그를 붙여 자기 파일을 만듭니다.

| 파일 | 의미 |
|---|---|
| `runs_<tag>.jsonl` | 통합 레코드(`evaluate.py` 입력) |
| `raw_<tag>/<COND>.jsonl` | 복원 전 raw 출력 (★ 누출은 여기서 측정) |
| `unmasked_<tag>/<COND>.jsonl` | 복원 후 출력 (유효성은 여기서 측정) |
| `results_per_sample_<tag>.csv` | 샘플별 지표 |
| `metrics_by_condition_<tag>.csv` | 최종 요약 표 |

태그: `claude-haiku`, `gpt-5.4-mini`, `gemini-3.1-flash-lite`, `mock`.

---

## 5. 실험 조건

| 조건 | 마스킹 | 설명 |
|---|---|---|
| **C0** | 없음 | 기준선(원본 요청) |
| **C1** | M1 | 규칙 기반 플레이스홀더(`[IP_1]`, `[IMSI_1]`), 로컬에서 복원 |
| **C2** | M2 | 형식 보존 가명화, 출현마다 재무작위화 |
| **C3** | M2 | 형식 보존 가명화, 엔티티당 일관 |

## 6. 평가 지표 (`evaluate.py`)

- **field_match**(메인): 정규화 명령의 필드 단위 정확도.
- **accuracy**: 명령 수준(정확 prefix+action = 1.0, 같은 rule family = 0.5).
  차단 계열 action `deny`/`drop`/`block`은 동의어로 정규화.
- **leakage**: ★복원 전 출력에 남은 **원본 식별자** 비율(낮을수록 좋음; 가짜값·
  토큰은 제외).
- **cmd_valid**: 복원 후 실행 가능한 형식인지.
- **unmask_success**: 토큰 복원율(C1 전용).
- 지연(latency), 입·출력 토큰.

---

## 7. 참고 / 문제 해결

- **Python 3.9 FutureWarning**(google-auth 수명 종료): 무해, 코드에서 이미 숨김.
  Python 3.10+로 올리면 완전히 사라집니다.
- **`503 UNAVAILABLE` / `429`**: provider 일시 과부하. 래퍼가 백오프로 자동
  재시도(5→10→20…초, 최대 6회). 계속 과부하면 잠시 뒤 재시도하거나 `config.py`의
  Gemini 모델명을 바꾸세요.
- **Gemini "thought_signature" 경고**: 무해(모델의 사고 파트), 코드에서 숨김.
  결과에는 영향 없음.
- **키 입력칸에서 붙여넣기 안 됨**: 프롬프트는 일반 입력이라 붙여넣기가 됩니다
  (키가 화면에 보임). 숨기려면 환경변수로 설정하세요.
- **모델 버전 교체**: `config.py`의 `CHOICES` 한 줄만 수정 — 예: Gemini
  `gemini-3.1-flash-lite` → `gemini-2.5-flash`.

## 8. 파일 구성
| 파일 | 역할 |
|---|---|
| `config.py` | 모델 선택지, 선택 메뉴, 모델별 출력 경로 |
| `masking.py` | M1 플레이스홀더 & M2 형식 보존 가명화 |
| `llm_client.py` | provider 래퍼(Claude/GPT/Gemini/Mock), JSON 스키마 출력, 재시도 |
| `run_experiment.py` | 조건 C0–C3 실행 |
| `evaluate.py` | 위 지표 산출 |
| `B3_synthetic_config_dataset_50.jsonl` | 합성 NetOps config 프롬프트 50개(실데이터 미사용) |

## 라이선스
MIT (`LICENSE` 참조). 합성 데이터만 사용하며 3GPP/RFC 필드 관례에 근거합니다.
실제 운영망 트레이스로는 검증되지 않았습니다.
