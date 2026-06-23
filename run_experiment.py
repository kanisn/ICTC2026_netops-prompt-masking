"""
run_experiment.py - run conditions (C0/C1/C2/C3) x dataset (B-2 pipeline)

For each (sample, condition):
  1) local masking -> masked request
  2) LLM call -> raw output (JSON)
  3) save raw output (* leakage is measured on this pre-restoration value - B-7)
  4) local unmask -> restored output for command-validity evaluation

Outputs (per model tag):
  outputs/raw_<tag>/<COND>.jsonl       : pre-restoration raw output
  outputs/unmasked_<tag>/<COND>.jsonl  : post-restoration output
  outputs/runs_<tag>.jsonl             : combined records (evaluation input)
"""
import json
import os
import sys
import warnings

# Silence the harmless "Python 3.9 EOL" FutureWarning from google-auth.
warnings.filterwarnings("ignore", category=FutureWarning, module="google")

import config
from masking import mask_text, unmask_text
from llm_client import build_prompt, call_llm


def load_dataset(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run():
    print("=" * 52)
    print(f"  MODEL  = {config.MODEL}  ({config.PROVIDER})")
    print(f"  OUTPUT = *_{config.TAG}.*")
    if config.PROVIDER == "mock":
        print("  [!] MOCK mode - not a real LLM call!")
    print("=" * 52)

    rows = load_dataset(config.DATASET_PATH)
    raw_root, unm_root = config.raw_dir(), config.unmasked_dir()
    os.makedirs(raw_root, exist_ok=True)
    os.makedirs(unm_root, exist_ok=True)

    all_records = []
    for cond in config.CONDITIONS:
        spec = config.CONDITION_SPEC[cond]
        raw_f = open(os.path.join(raw_root, f"{cond}.jsonl"),
                     "w", encoding="utf-8")
        unm_f = open(os.path.join(unm_root, f"{cond}.jsonl"),
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
                "raw_output": raw_cfg,                 # pre-restoration (leakage)
                "unmasked_output": unmasked_cfg,       # post-restoration (validity)
                "expected": r["expected_answer_normalized"],
                "originals": meta["originals"],        # leakage denominator
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

    os.makedirs(config.OUT_DIR, exist_ok=True)
    with open(config.runs_path(), "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\nTotal {len(all_records)} records -> {config.runs_path()}")
    print("Next: python evaluate.py  (select the same model)")


if __name__ == "__main__":
    # Interactive: pick model + enter API key.
    # Non-interactive: EXP_NONINTERACTIVE=1 + EXP_PROVIDER.
    if sys.stdin.isatty() and not os.environ.get("EXP_NONINTERACTIVE"):
        config.interactive_select(require_key=True)
    else:
        config.ensure_api_key()
    run()
