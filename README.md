# NetOps Input-Prompt Masking

Reproducible pipeline for the ICTC 2026 paper *"Privacy in LLM-Based Network
Operations Agents: A Lifecycle Taxonomy, Risk-to-Guardrail Mapping, and an
Input-Prompt Masking Case Study."*

Masking, restoration (unmask), and evaluation run as deterministic local code;
the LLM only ever sees masked input (provider-agnostic wrapper). You pick a
model at run time (Claude / GPT / Gemini / Mock), and outputs are written
separately per model.

---

## 1. Requirements

- **Python 3.10+** recommended (3.9 works but prints a harmless google-auth
  end-of-life warning).
- Install the libraries for the model(s) you plan to use:

```bash
# create & activate a virtual env (optional but recommended)
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

# install everything
pip install -r requirements.txt

# ...or only what you need:
pip install anthropic        # Claude
pip install openai           # GPT
pip install google-genai     # Gemini
# Mock mode needs nothing extra (standard library only)
```

`requirements.txt`:
```
anthropic>=0.40        # Claude (claude-haiku-4-5)
openai>=1.40           # GPT   (gpt-5.4-mini)
google-genai>=1.0      # Gemini (gemini-3.1-flash-lite)
```

---

## 2. Get an API key

| Model | Where to create a key | Env variable |
|---|---|---|
| **Claude** | Anthropic Console → API Keys: https://console.anthropic.com/settings/keys | `ANTHROPIC_API_KEY` |
| **GPT** | OpenAI Platform → API keys: https://platform.openai.com/api-keys | `OPENAI_API_KEY` |
| **Gemini** | Google AI Studio → API keys: https://aistudio.google.com/apikey | `GOOGLE_API_KEY` |
| **Mock** | none (offline test) | — |

You can supply the key two ways:

1. **At the prompt** — the script asks for it when you run (paste is allowed;
   the key is shown on screen).
2. **As an environment variable** — set it beforehand and the script will not
   prompt (key stays hidden). Example (PowerShell):
   ```powershell
   $env:GOOGLE_API_KEY="your-key-here"
   ```
   In PyCharm: Run → Edit Configurations → *Environment variables*.

---

## 3. Run

```bash
python run_experiment.py     # pick a model (1-4), enter the API key
python evaluate.py           # pick the SAME model to score it
```

`run_experiment.py` shows a menu:
```
Which model do you want to run?
  1) Claude (Haiku)                 [claude-haiku-4-5-20251001]
  2) GPT (gpt-5.4-mini)             [gpt-5.4-mini]
  3) Gemini (gemini-3.1-flash-lite) [gemini-3.1-flash-lite]
  4) Mock (offline, no key needed)  [mock-model]
Select a number (1-4):
```

Run order matters: **`run_experiment.py` first** (creates the results file),
then **`evaluate.py`** with the same model.

To run all three models, just repeat the two commands and pick a different
model each time — outputs never overwrite each other (see below).

### Non-interactive (CI / scripted)
```bash
EXP_NONINTERACTIVE=1 EXP_PROVIDER=gemini GOOGLE_API_KEY=... python run_experiment.py
EXP_NONINTERACTIVE=1 EXP_PROVIDER=gemini python evaluate.py
```
`EXP_PROVIDER` accepts `claude|gpt|gemini|mock` (or `anthropic|openai|google`).
Optional overrides: `EXP_MODEL`, `EXP_TAG`, `EXP_DATASET`, `EXP_OUT`.

---

## 4. Outputs (separated per model)

Each model writes its own files under `outputs/`, tagged by model:

| File | Meaning |
|---|---|
| `runs_<tag>.jsonl` | combined records (input to `evaluate.py`) |
| `raw_<tag>/<COND>.jsonl` | pre-restoration raw model output (leakage is measured here) |
| `unmasked_<tag>/<COND>.jsonl` | post-restoration output (validity is measured here) |
| `results_per_sample_<tag>.csv` | per-sample metrics |
| `metrics_by_condition_<tag>.csv` | final summary table |

Tags: `claude-haiku`, `gpt-5.4-mini`, `gemini-3.1-flash-lite`, `mock`.

---

## 5. Conditions

| Cond. | Masking | Description |
|---|---|---|
| **C0** | none | baseline, raw request |
| **C1** | M1 | rule-based placeholders (`[IP_1]`, `[IMSI_1]`), restored locally |
| **C2** | M2 | format-preserving pseudonym, re-randomized per occurrence |
| **C3** | M2 | format-preserving pseudonym, consistent per entity |

## 6. Metrics (`evaluate.py`)

- **field_match** (main): per-field correctness of the normalized command.
- **accuracy**: command-level (exact prefix+action = 1.0; same rule family = 0.5).
  Block-family actions `deny`/`drop`/`block` are normalized as synonyms.
- **leakage**: fraction of *original* identifiers in the *pre-restoration* output
  (lower is better; fake values and placeholders do not count).
- **cmd_valid**: executable format after restoration.
- **unmask_success**: token restoration rate (C1 only).
- latency, input/output tokens.

---

## 7. Notes & troubleshooting

- **Python 3.9 FutureWarning** (google-auth EOL): harmless; already silenced in
  the scripts. Upgrading to Python 3.10+ removes it for good.
- **`503 UNAVAILABLE` / `429`**: transient provider overload. The wrapper retries
  automatically with backoff (5→10→20…s, up to 6 times). If a model stays
  overloaded, try again later or switch the Gemini model name in `config.py`.
- **Gemini "thought_signature" warnings**: harmless (the model's thinking parts);
  silenced in the code. Results are unaffected.
- **Paste not working at the key prompt**: the prompt uses plain input so paste
  works; the key will be visible. To hide it, set the env variable instead.
- **Switching a model version**: edit one line in `config.py` (the `CHOICES`
  entry) — e.g. Gemini `gemini-3.1-flash-lite` → `gemini-2.5-flash`.

## 8. Files
| File | Role |
|---|---|
| `config.py` | model choices, selection menu, per-model output paths |
| `masking.py` | M1 placeholder & M2 format-preserving pseudonymization |
| `llm_client.py` | provider wrappers (Claude/GPT/Gemini/Mock), JSON-schema output, retries |
| `run_experiment.py` | run conditions C0–C3 over the dataset |
| `evaluate.py` | compute the metrics above |
| `B3_synthetic_config_dataset_50.jsonl` | 50 synthetic NetOps config prompts (no production traces) |

## License
MIT (see `LICENSE`). Synthetic data only; grounded in 3GPP/RFC field
conventions; not validated on production traces.
