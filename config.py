"""
config.py - global experiment settings (provider-agnostic, model selectable)

Part B-5: at run time, pick Claude / GPT / Gemini, enter the matching API key,
and outputs are written separately per model.

Selection:
  - interactive: `python run_experiment.py` shows a menu + key prompt
  - non-interactive (CI/offline): env EXP_PROVIDER + EXP_NONINTERACTIVE=1
"""
import os

# ── Selectable models (exact model names) ──────────────────────────
CHOICES = {
    "claude": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001",
               "tag": "claude-haiku",    "key_env": "ANTHROPIC_API_KEY",
               "label": "Claude (Haiku)"},
    "gpt":    {"provider": "openai",    "model": "gpt-5.4-mini",
               "tag": "gpt-5.4-mini",    "key_env": "OPENAI_API_KEY",
               "label": "GPT (gpt-5.4-mini)"},
    "gemini": {"provider": "google",    "model": "gemini-3.1-flash-lite",
               "tag": "gemini-3.1-flash-lite", "key_env": "GOOGLE_API_KEY",
               "label": "Gemini (gemini-3.1-flash-lite)"},
    "mock":   {"provider": "mock",      "model": "mock-model",
               "tag": "mock",            "key_env": None,
               "label": "Mock (offline, no key needed)"},
}

_ALIASES = {"anthropic": "claude", "openai": "gpt", "google": "gemini",
            "gemini": "gemini", "claude": "claude", "gpt": "gpt", "mock": "mock"}


def _norm(choice):
    return _ALIASES.get((choice or "").strip().lower(), (choice or "").strip().lower())


# ── Current selection (default from env, falls back to gpt) ─────────
CHOICE = _norm(os.environ.get("EXP_PROVIDER", "gpt"))
if CHOICE not in CHOICES:
    CHOICE = "gpt"
_C = CHOICES[CHOICE]
PROVIDER = _C["provider"]                                    # anthropic|openai|google|mock
MODEL = os.environ.get("EXP_MODEL", _C["model"])
TAG = os.environ.get("EXP_TAG", _C["tag"])                   # output-file tag

TEMPERATURE = 0          # deterministic decoding (B-2/B-6)
MAX_TOKENS = 512


def apply_choice(choice):
    """Apply a selection and update globals (PROVIDER/MODEL/TAG)."""
    global CHOICE, PROVIDER, MODEL, TAG, _C
    choice = _norm(choice)
    if choice not in CHOICES:
        raise ValueError(f"unknown choice: {choice} (use {list(CHOICES)})")
    CHOICE, _C = choice, CHOICES[choice]
    PROVIDER = _C["provider"]
    MODEL = os.environ.get("EXP_MODEL", _C["model"])
    TAG = os.environ.get("EXP_TAG", _C["tag"])


def ensure_api_key():
    """If the selected model's API key is missing, prompt and set it in env.

    Uses plain input() so the key can be pasted (it will be visible on screen).
    To keep the key hidden, set the env var beforehand and it won't prompt.
    """
    env = _C["key_env"]
    if env and not os.environ.get(env):
        os.environ[env] = input(f"  Enter {env} (paste OK): ").strip()


def interactive_select(require_key=True):
    """Show a menu to pick a model and (optionally) enter the key. Returns the choice key."""
    order = ["claude", "gpt", "gemini", "mock"]
    print("\nWhich model do you want to run?")
    for i, k in enumerate(order, 1):
        print(f"  {i}) {CHOICES[k]['label']}  [{CHOICES[k]['model']}]")
    sel = input("Select a number (1-4): ").strip()
    pick = {"1": "claude", "2": "gpt", "3": "gemini", "4": "mock"}.get(sel)
    if pick is None:
        pick = _norm(sel) if _norm(sel) in CHOICES else "gpt"
    apply_choice(pick)
    if require_key:
        ensure_api_key()
    return CHOICE


# ── Experiment conditions (B-4) ────────────────────────────────────
#   C0 = No Masking, C1 = M1 placeholder,
#   C2 = M2 format-preserving (per-occurrence), C3 = M2 format-preserving (consistent)
CONDITIONS = ["C0", "C1", "C2", "C3"]
CONDITION_SPEC = {
    "C0": {"mode": "none",        "consistent": False},
    "C1": {"mode": "placeholder", "consistent": True},   # M1
    "C2": {"mode": "pseudonym",   "consistent": False},  # M2 per-occurrence
    "C3": {"mode": "pseudonym",   "consistent": True},   # M2 consistent
}

# ── Paths (separated per model tag) ────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.environ.get(
    "EXP_DATASET", os.path.join(HERE, "B3_synthetic_config_dataset_50.jsonl"))
OUT_DIR = os.environ.get("EXP_OUT", os.path.join(HERE, "outputs"))


def runs_path():       return os.path.join(OUT_DIR, f"runs_{TAG}.jsonl")
def raw_dir():         return os.path.join(OUT_DIR, f"raw_{TAG}")
def unmasked_dir():    return os.path.join(OUT_DIR, f"unmasked_{TAG}")
def results_path():    return os.path.join(OUT_DIR, f"results_per_sample_{TAG}.csv")
def metrics_path():    return os.path.join(OUT_DIR, f"metrics_by_condition_{TAG}.csv")


# ── Sensitive-field classification (B-3 / B-7 leakage definition) ──
# Only direct/quasi identifiers are masked and counted as leakage.
# Operational parameters (ports, rates, ...) are excluded.
IDENTIFIER_TYPES = {
    "imsi", "supi", "ue_id", "ip", "src_ip", "dst_ip", "mgmt_ip",
    "cell_id", "gnb_id", "source_cell", "target_cell", "neighbor_cell",
    "preferred_cell", "s_nssai", "upf", "target_upf", "switch",
    "controller", "edge_node", "runbook_id", "ticket_id",
    "config_snapshot_id", "internal_api", "handover_path",
}
# Non-identifier operational parameters, excluded from masking/leakage.
NON_IDENTIFIER_TYPES = {
    "protocol", "direction", "rate", "limit", "application", "dscp",
    "duration", "metric", "rsrp", "sinr", "latency", "profile",
    "allow_port", "drop_scope", "out_port", "dst_port", "events",
    "traffic", "controller_policy",
}


def normalize_type(key: str) -> str:
    """Normalize a sensitive_fields_json key (absorb plural/casing)."""
    k = key.strip().lower()
    if k.endswith("s") and k[:-1] in IDENTIFIER_TYPES | NON_IDENTIFIER_TYPES:
        k = k[:-1]
    aliases = {"cell_ids": "cell_id", "dst_ips": "dst_ip", "imsis": "imsi",
               "upfs": "upf", "switches": "switch", "applications": "application",
               "rates": "rate", "ticket_ids": "ticket_id"}
    return aliases.get(key.strip().lower(), k)
