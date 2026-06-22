# 실험 코드 (Input Prompt Masking) — 실행 가이드

Part B 설계를 구현한 코드 골격. 마스킹·언마스크·평가는 전부 로컬, LLM은 마스킹된 입력만 보는 블랙박스.

## 파일

| 파일 | 역할 |
|---|---|
| `config.py` | 모델/provider/조건/경로 설정 — **모델 교체는 이 파일만 수정** |
| `masking.py` | 로컬 결정적 마스킹 (M1 placeholder / M2 형식보존, 일관·비일관) |
| `llm_client.py` | provider-agnostic 호출 래퍼 (anthropic / openai / mock), JSON 스키마 강제 |
| `run_experiment.py` | C0~C3 × 50샘플 실행 → `outputs/raw`, `outputs/unmasked`, `outputs/runs.jsonl` |
| `evaluate.py` | 지표 산출 → `outputs/results_per_sample.csv`, `outputs/metrics_by_condition.csv` |
| `B3_synthetic_config_dataset_50.jsonl` | 데이터셋 (50개) |

## 실행

```bash
# 0) (mock) 키 없이 파이프라인 검증 — 표준 라이브러리만 필요
python run_experiment.py && python evaluate.py

# 1) Haiku 로 실제 실행
pip install anthropic
export ANTHROPIC_API_KEY=...        # Windows: set ANTHROPIC_API_KEY=...
set EXP_PROVIDER=anthropic          # 또는 export EXP_PROVIDER=anthropic
python run_experiment.py && python evaluate.py

# 2) 최종 모델 교체 (gpt-5.4-mini) — config 변경 없이 환경변수로
pip install openai
export OPENAI_API_KEY=...
EXP_PROVIDER=openai python run_experiment.py && EXP_PROVIDER=openai python evaluate.py
```

환경변수: `EXP_PROVIDER`(anthropic|openai|mock), `EXP_MODEL`, `EXP_DATASET`, `EXP_OUT`.

## 지표 (evaluate.py)

- **field_match** (MAIN): key=value 필드 단위 일치율
- **accuracy**: primary exact 1.0 / 같은 rule family 0.5 / 무관 0.0
- **action 동의어 정규화**: 채점 시 `deny=drop=block`(차단 계열)은 동일 action으로 취급. `forward/rate_limit/exclude/force/quarantine`는 의미가 달라 병합 안 함. (논문에 명시 권장)
- 재채점만 필요하면 모델 재호출 없이 `python evaluate.py`만 실행하면 됨
- **leakage**: ★ raw output 기준, 원본 실제값 대조 = 노출된 원본 식별자 / 전체 (C0만 높게 기대)
- **cmd_valid**: unmask 후 형식·잔여토큰 검사
- **unmask_success**: C1 placeholder 복원율
- latency / token

## 주의

- 누출률은 **반드시 raw output(복원 전)** 으로 측정 — `evaluate.py`가 자동 처리.
- 합성 데이터만 사용(synthetic-only). 실제 운영망 로그 외부 전송 금지.
- mock provider는 "이상적 마스킹 준수 모델"이라 C1~C3 leakage가 0으로 나옴 — 실제 모델은 누출이 발생할 수 있고 그 차이가 곧 실험 결과.
