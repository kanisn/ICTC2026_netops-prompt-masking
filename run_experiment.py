"""
run_experiment.py — 조건(C0/C1/C2/C3) × 데이터셋 실행 (B-2 파이프라인)

각 (sample, condition)마다:
  1) 로컬 마스킹 → masked request
  2) LLM 호출 → raw output (JSON)
  3) raw output 저장 (★ leakage는 복원 전 이 값으로 측정 — B-7)
  4) 로컬 unmask → command validity 평가용 복원본

산출:
  outputs/raw/<COND>.jsonl       : 복원 전 raw output
  outputs/unmasked/<COND>.jsonl  : 복원 후
  outputs/runs.jsonl             : 통합 레코드(평가 입력)
"""
import json
import os

import config
from masking import mask_text, unmask_text
from llm_client import build_prompt, call_llm


def load_dataset(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run():
    print("=" * 52)
    print(f"  PROVIDER = {config.PROVIDER}")
    print(f"  MODEL    = {config.MODEL}")
    if config.PROVIDER == "mock":
        print("  ⚠️  MOCK 모드입니다 — 실제 LLM 호출이 아닙니다!")
        print("     실제 실행: 환경변수 EXP_PROVIDER=anthropic 설정 후 재실행")
    print("=" * 52)

    rows = load_dataset(config.DATASET_PATH)
    os.makedirs(os.path.join(config.OUT_DIR, "raw"), exist_ok=True)
    os.makedirs(os.path.join(config.OUT_DIR, "unmasked"), exist_ok=True)

    all_records = []
    for cond in config.CONDITIONS:
        spec = config.CONDITION_SPEC[cond]
        raw_f = open(os.path.join(config.OUT_DIR, "raw", f"{cond}.jsonl"),
                     "w", encoding="utf-8")
        unm_f = open(os.path.join(config.OUT_DIR, "unmasked", f"{cond}.jsonl"),
                     "w", encoding="utf-8")

        for r in rows:
            sf = json.loads(r["sensitive_fields_json"])
            masked_req, meta = mask_text(
                r["natural_language_request_ko"], sf,
                spec["mode"], spec["consistent"])

            prompt = build_prompt(masked_req, r["task_type"])
            out, latency, in_tok, out_tok = call_llm(prompt, sample=r, mask_meta=meta)

            raw_cfg = out.get("normalized_config", "")
            unmasked_cfg = unmask_text(raw_cfg, meta["rev"])

            rec = {
                "sample_id": r["sample_id"],
                "task_type": r["task_type"],
                "condition": cond,
                "model": config.MODEL,
                "provider": config.PROVIDER,
                "masked_request": masked_req,
                "raw_output": raw_cfg,                 # 복원 전 (leakage 측정)
                "unmasked_output": unmasked_cfg,       # 복원 후 (validity 측정)
                "expected": r["expected_answer_normalized"],
                "originals": meta["originals"],        # 누출 분모
                "rev": meta["rev"],
                "c3_required": r.get("c3_required", "no"),
                "latency_sec": round(latency, 4),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
            }
            all_records.append(rec)
            raw_f.write(json.dumps({**rec, "rev": None}, ensure_ascii=False) + "\n")
            unm_f.write(json.dumps({"sample_id": r["sample_id"],
                                    "condition": cond,
                                    "unmasked_output": unmasked_cfg},
                                   ensure_ascii=False) + "\n")
        raw_f.close()
        unm_f.close()
        print(f"[{cond}] {len(rows)} samples done")

    with open(os.path.join(config.OUT_DIR, "runs.jsonl"), "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\nTotal {len(all_records)} records → {config.OUT_DIR}/runs.jsonl")


if __name__ == "__main__":
    run()
