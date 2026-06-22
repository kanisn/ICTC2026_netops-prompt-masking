"""
evaluate.py — 지표 산출 (B-7 / B-7.1)

지표:
  - Field match (MAIN)      : raw/unmasked의 key=value 필드 단위 일치율
  - Primary accuracy (exact): cmd prefix + action exact = 1.0
  - Partial accuracy        : rule family(cmd prefix) 일치, action 불일치 = 0.5, 무관 0.0
  - Leakage rate            : ★ raw output 기준, 원본 실제값 집합과 대조
                              = (출력에 등장한 원본 식별자 수)/(전체 원본 식별자 수)
  - Command validity        : unmask 후 출력이 cmd+key=value 형식인지
  - Unmask success (C1)     : 출력 placeholder가 모두 복원 가능한지
  - Latency / token cost

입력 : outputs/runs.jsonl
출력 : outputs/results_per_sample.csv, outputs/metrics_by_condition.csv
"""
import csv
import json
import os
import re
import statistics as st

import config

PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_\d+\]")


# ── config 파싱 ───────────────────────────────────────────────────
def parse_config(text: str):
    """`cmd subcmd key=value ...` → (prefix, {key:value})."""
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
    prefix = " ".join(head[:2])      # 예: "firewall add"
    return prefix, fields


# action 동의어: 차단 계열(block-family)은 같은 의미로 취급.
# deny/drop/block 만 병합. forward/rate_limit/exclude/force/quarantine 등은
# 의미가 다르므로 병합하지 않음(진짜 오류는 그대로 감점).
ACTION_SYNONYMS = {"deny": "deny", "drop": "deny", "block": "deny"}


def _norm_val(key, v):
    if not isinstance(v, str):
        return v
    v = v.lower()
    if key == "action":
        v = ACTION_SYNONYMS.get(v, v)
    return v


def _lc(d):
    """값 대소문자 무시 + action 동의어 정규화(deny=drop=block). 키는 그대로."""
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
    if pp == gp:                      # 같은 rule family, action만 다름
        return 0.5
    return 0.0


# ── leakage (B-7: 원본 실제값 대조) ───────────────────────────────
def leakage_rate(raw_output: str, originals):
    if not originals:
        return 0.0
    leaked = sum(1 for v in originals if v and v in raw_output)
    return leaked / len(originals)


# ── command validity ─────────────────────────────────────────────
def command_valid(unmasked: str):
    prefix, fields = parse_config(unmasked)
    ok_format = bool(prefix) and len(fields) >= 1
    no_residual = not PLACEHOLDER_RE.search(unmasked)   # 복원 잔여 토큰 없음
    return 1.0 if (ok_format and no_residual) else 0.0


# ── unmask success (C1 placeholder 전용) ─────────────────────────
def unmask_success(raw_output: str, rev: dict):
    toks = PLACEHOLDER_RE.findall(raw_output)
    if not toks:
        return None                  # placeholder 미사용 조건 → N/A
    ok = sum(1 for t in toks if t in (rev or {}))
    return ok / len(toks)


# ── 집계 ──────────────────────────────────────────────────────────
def evaluate():
    runs = [json.loads(l) for l in open(
        os.path.join(config.OUT_DIR, "runs.jsonl"), encoding="utf-8")]

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
    pf = os.path.join(config.OUT_DIR, "results_per_sample.csv")
    with open(pf, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(per[0].keys()))
        w.writeheader()
        w.writerows(per)

    # 조건별 집계
    def agg(rows, key):
        vals = [x[key] for x in rows if x[key] is not None]
        return (round(st.mean(vals), 4) if vals else "",
                round(st.pstdev(vals), 4) if len(vals) > 1 else 0)

    mf = os.path.join(config.OUT_DIR, "metrics_by_condition.csv")
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

    # 콘솔 요약
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
    evaluate()
