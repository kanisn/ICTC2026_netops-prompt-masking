"""
config.py — 실험 전역 설정 (모델 교체는 이 파일만 수정)

Part B-5: provider-agnostic. 모델명/PROVIDER만 바꿔 재실행.
"""
import os

# ── 모델 / provider ────────────────────────────────────────────────
# PROVIDER: "anthropic" | "openai" | "mock"
#   - "mock": API 키 없이 파이프라인을 오프라인 검증하기 위한 가짜 모델
PROVIDER = os.environ.get("EXP_PROVIDER", "openai")

MODEL = os.environ.get("EXP_MODEL", {
    "anthropic": "claude-haiku-4-5-20251001",   # 우선 테스트 모델 (B-5)
    "openai":    "gpt-5.4-mini",                 # 최종 후보 (B-5)
    "mock":      "mock-model",
}[PROVIDER])

TEMPERATURE = 0          # 결정성 확보 (B-2/B-6)
MAX_TOKENS = 512

# ── 실험 조건 (B-4) ────────────────────────────────────────────────
#   C0 = No Masking, C1 = M1 placeholder,
#   C2 = M2 형식보존(비일관), C3 = M2 형식보존(일관/엔티티 보존)
CONDITIONS = ["C0", "C1", "C2", "C3"]

CONDITION_SPEC = {
    "C0": {"mode": "none",        "consistent": False},
    "C1": {"mode": "placeholder", "consistent": True},   # M1
    "C2": {"mode": "pseudonym",   "consistent": False},  # M2 단발
    "C3": {"mode": "pseudonym",   "consistent": True},   # M2 일관
}

# ── 경로 ───────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.environ.get(
    "EXP_DATASET", os.path.join(HERE, "B3_synthetic_config_dataset_50.jsonl"))
OUT_DIR = os.environ.get("EXP_OUT", os.path.join(HERE, "outputs"))

# ── 민감필드 분류 (B-3 / B-7 leakage 정의) ─────────────────────────
# 직접/준식별자만 마스킹·누출 집계 대상. 운영 파라미터(포트/레이트 등)는 제외.
IDENTIFIER_TYPES = {
    "imsi", "supi", "ue_id", "ip", "src_ip", "dst_ip", "mgmt_ip",
    "cell_id", "gnb_id", "source_cell", "target_cell", "neighbor_cell",
    "preferred_cell", "s_nssai", "upf", "target_upf", "switch",
    "controller", "edge_node", "runbook_id", "ticket_id",
    "config_snapshot_id", "internal_api", "handover_path",
}

# 마스킹/누출 집계에서 제외하는 비식별 운영 파라미터
NON_IDENTIFIER_TYPES = {
    "protocol", "direction", "rate", "limit", "application", "dscp",
    "duration", "metric", "rsrp", "sinr", "latency", "profile",
    "allow_port", "drop_scope", "out_port", "dst_port", "events",
    "traffic", "controller_policy",
}


def normalize_type(key: str) -> str:
    """sensitive_fields_json의 키를 정규화 (복수형/대소문자 흡수)."""
    k = key.strip().lower()
    if k.endswith("s") and k[:-1] in IDENTIFIER_TYPES | NON_IDENTIFIER_TYPES:
        k = k[:-1]
    aliases = {"cell_ids": "cell_id", "dst_ips": "dst_ip", "imsis": "imsi",
               "upfs": "upf", "switches": "switch", "applications": "application",
               "rates": "rate", "ticket_ids": "ticket_id"}
    return aliases.get(key.strip().lower(), k)
