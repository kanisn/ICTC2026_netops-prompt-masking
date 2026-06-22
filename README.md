# NetOps Input-Prompt Masking

Reproducible pipeline for the ICTC 2026 paper *"Privacy in LLM-Based
Network Operations Agents: A Lifecycle Taxonomy, Risk-to-Guardrail
Mapping, and an Input-Prompt Masking Case Study."*

Masking, restoration (unmask), and evaluation run as deterministic local
code; the LLM only ever sees masked input (provider-agnostic wrapper).

## Contents
| File | Role |
|---|---|
| `config.py` | model/provider/condition/path settings (swap model here) |
| `masking.py` | M1 placeholder & M2 format-preserving pseudonymization |
| `llm_client.py` | provider-agnostic wrapper (Anthropic / OpenAI / mock), JSON-schema output, output grammar |
| `run_experiment.py` | run conditions C0–C3 over the dataset |
| `evaluate.py` | metrics (field match, accuracy, leakage, validity, unmask, latency/tokens) |
| `B3_synthetic_config_dataset_50.jsonl` | 50 synthetic NetOps config prompts (no production traces) |

## Conditions
- **C0** no masking (baseline) · **C1** M1 placeholders · **C2** M2 pseudonym (per-occurrence) · **C3** M2 pseudonym (consistent)

## Metrics
- **Leakage**: fraction of *original* identifiers in the *pre-restoration* output (lower is better)
- **Field match / Accuracy**: per-field and command-level correctness (action synonyms deny/drop/block normalized; strict values also reported)
- **Unmask success**: token restoration rate (M1)

## Run
```bash
pip install -r requirements.txt
# offline pipeline check (no key)
python run_experiment.py && python evaluate.py
# Anthropic (Haiku)
export ANTHROPIC_API_KEY=...   ; EXP_PROVIDER=anthropic python run_experiment.py && EXP_PROVIDER=anthropic python evaluate.py
# OpenAI (gpt-5.4-mini)
export OPENAI_API_KEY=...       ; EXP_PROVIDER=openai    python run_experiment.py && EXP_PROVIDER=openai    python evaluate.py
```
Outputs: `outputs/runs.jsonl`, `outputs/results_per_sample.csv`, `outputs/metrics_by_condition.csv`.

## Note
Synthetic data only; grounded in 3GPP/RFC field conventions. Not validated on production traces.

## License
MIT (see `LICENSE`).
