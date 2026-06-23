"""
evaluate.py - compute metrics (B-7 / B-7.1)

Metrics:
  - Field match (MAIN)      : per-field (key=value) match rate of unmasked output
  - Primary accuracy (exact): cmd prefix + action exact = 1.0
  - Partial accuracy        : same rule family (cmd prefix), action mismatch = 0.5, else 0.0
  - Leakage rate            : * measured on raw output, compared to the set of original values
                              = (original identifiers appearing in output) / (total original identifiers)
  - Command validity        : whether the unmasked output is a cmd+key=value form
  - Unmask success (C1)     : whether all output placeholders can be restored
  - Latency / token cost

Input  : outputs/runs_<tag>.jsonl
Output : outputs/results_per_sample_<tag>.csv, outputs/metrics_by_condition_<tag>.csv
"""
import csv
import json
import os
import re
import statistics as st
import warnings

# Silence the harmless "Python 3.9 EOL" FutureWarning from google-auth.
warnings.filterwarnings("ignore", category=FutureWarning, module="google")

import config

PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_\d+\]")


# ── config parsing ────────────────────────────────────────────────
def parse_config(text: str):
    """`cmd subcmd key=value ...` -> (prefix, {key:value})."""
    toks = text.strip().split()
    if not toks:
        return "", {}
    fields, head = {}, []
    for tok in toks:
        if "=" in tok:
            k, v = tok.split("=", 1)
            fields[k] = v
        elif not fields:
            head.append(tok)
    prefix = " ".join(head[:2])      # e.g. "firewall add"
    return prefix, fields


# Action synonyms: the block-family is treated as one meaning.
# Only deny/drop/block are merged. forward/rate_limit/exclude/force/quarantine
# differ in meaning and are NOT merged (genuine errors still lose points).
ACTION_SYNONYMS = {"deny": "deny", "drop": "deny", "block": "deny"}


def _norm_val(key, v):
    if not isinstance(v, str):
        return v
    v = v.lower()
    if key == "action":
        v = ACTION_SYNONYMS.get(v, v)
    return v


def _lc(d):
    """Case-insensitive values + action-synonym normalization (deny=drop=block). Keys unchanged."""
    return {k: _norm_val(k, v) for k, v in d.items()}


def field_match(pred: str, gold: str):
    _, pf = parse_config(pred)
    _, gf = parse_config(gold)
    pf, gf = _lc(pf), _lc(gf)
    if not gf:
        return 0.0
    hit = sum(1 for k, v in gf.items() if pf.get(k) == v)
    return hit / len(gf)


def primary_partial(pred: str, gold: str):
    pp, pf = parse_config(pred)
    gp, gf = parse_config(gold)
    pf, gf = _lc(pf), _lc(gf)
    action_ok = pf.get("action") == gf.get("action")
    has_action = "action" in gf
    if pp == gp and (action_ok or not has_action):
        return 1.0
    if pp == gp:                      # same rule family, action differs
        return 0.5
    return 0.0


# ── leakage (B-7: compare against original real values) ───────────
def leakage_rate(raw_output: str, originals):
    if not originals:
        return 0.0
    leaked = sum(1 for v in originals if v and v in raw_output)
    return leaked / len(originals)


# ── command validity ─────────────────────────────────────────────
def command_valid(unmasked: str):
    prefix, fields = parse_config(unmasked)
    ok_format = bool(prefix) and len(fields) >= 1
    no_residual = not PLACEHOLDER_RE.search(unmasked)   # no leftover tokens
    return 1.0 if (ok_format and no_residual) else 0.0


# ── unmask success (C1 placeholder only) ─────────────────────────
def unmask_success(raw_output: str, rev: dict):
    toks = PLACEHOLDER_RE.findall(raw_output)
    if not toks:
        return None                  # no placeholders in this condition -> N/A
    ok = sum(1 for t in toks if t in (rev or {}))
    return ok / len(toks)


# ── aggregation ───────────────────────────────────────────────────
def evaluate():
    print(f"Evaluating: {config.MODEL}  ->  {os.path.basename(config.runs_path())}")
    if not os.path.exists(config.runs_path()):
        print(f"\n[!] Not found: {config.runs_path()}")
        print(f"    Run the experiment for this model first:")
        print(f"      python run_experiment.py   (select the same model)")
        return
    runs = [json.loads(l) for l in open(config.runs_path(), encoding="utf-8")]

    per = []
    for r in runs:
        raw, unm, gold = r["raw_output"], r["unmasked_output"], r["expected"]
        per.append({
            "sample_id": r["sample_id"], "condition": r["condition"],
            "task_type": r["task_type"],
            "field_match": round(field_match(unm, gold), 4),
            "accuracy": primary_partial(unm, gold),
            "leakage": round(leakage_rate(raw, r["originals"]), 4),
            "cmd_valid": command_valid(unm),
            "unmask_success": unmask_success(raw, r.get("rev")),
            "latency_sec": r["latency_sec"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
        })

    # per-sample CSV
    pf = config.results_path()
    with open(pf, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(per[0].keys()))
        w.writeheader()
        w.writerows(per)

    # per-condition aggregation
    def agg(rows, key):
        vals = [x[key] for x in rows if x[key] is not None]
        return (round(st.mean(vals), 4) if vals else "",
                round(st.pstdev(vals), 4) if len(vals) > 1 else 0)

    mf = config.metrics_path()
    cols = ["condition", "n", "field_match", "accuracy", "leakage",
            "cmd_valid", "unmask_success", "mean_latency",
            "mean_in_tok", "mean_out_tok"]
    with open(mf, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for cond in config.CONDITIONS:
            rows = [x for x in per if x["condition"] == cond]
            if not rows:
                continue
            fm, _ = agg(rows, "field_match")
            ac, _ = agg(rows, "accuracy")
            lk, _ = agg(rows, "leakage")
            cv, _ = agg(rows, "cmd_valid")
            us, _ = agg(rows, "unmask_success")
            lat, _ = agg(rows, "latency_sec")
            it, _ = agg(rows, "input_tokens")
            ot, _ = agg(rows, "output_tokens")
            w.writerow([cond, len(rows), fm, ac, lk, cv, us, lat, it, ot])

    # console summary
    print(f"\nProvider={config.PROVIDER}  Model={config.MODEL}")
    print(f"{'COND':5}{'field':>8}{'acc':>7}{'leak':>7}{'valid':>7}{'unmask':>8}")
    for cond in config.CONDITIONS:
        rows = [x for x in per if x["condition"] == cond]
        if not rows:
            continue
        fm, _ = agg(rows, "field_match")
        ac, _ = agg(rows, "accuracy")
        lk, _ = agg(rows, "leakage")
        cv, _ = agg(rows, "cmd_valid")
        us, _ = agg(rows, "unmask_success")
        print(f"{cond:5}{fm:>8}{ac:>7}{lk:>7}{cv:>7}{str(us):>8}")
    print(f"\n→ {pf}\n→ {mf}")


if __name__ == "__main__":
    import sys
    # 평가할 모델 선택(키 불필요). 비대화형은 EXP_NONINTERACTIVE=1 + EXP_PROVIDER.
    if sys.stdin.isatty() and not os.environ.get("EXP_NONINTERACTIVE"):
        config.interactive_select(require_key=False)
    evaluate()
