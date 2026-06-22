"""
llm_client.py — provider-agnostic LLM 호출 래퍼 (B-5)

call_llm(prompt, sample, mask_meta) -> (parsed_json, latency, in_tok, out_tok)

출력은 항상 동일 JSON 스키마(B-6):
  {
    "normalized_config": "<cmd key=value ...>",
    "sensitive_entities_in_output": [...],   # 모델 자기보고(보조용)
    "confidence": 0.0~1.0
  }

PROVIDER:
  - "anthropic": Claude Haiku (tool_use 로 스키마 강제)
  - "openai"   : gpt-5.4-mini (response_format=json_schema)
  - "mock"     : 키 없이 파이프라인 검증. 마스킹된 값을 그대로 통과시키는
                 "이상적 마스킹 준수 모델"을 시뮬레이션.
"""
import json
import time

import config

# 공통 출력 JSON 스키마
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "normalized_config": {"type": "string"},
        "sensitive_entities_in_output": {
            "type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["normalized_config", "sensitive_entities_in_output", "confidence"],
    "additionalProperties": False,
}

# ── 출력 문법 (정답 정규화 어휘에서 추출) ─────────────────────────
# task_type → (명령 prefix, 허용 key 목록)
GRAMMAR = {
    "firewall_config": ("firewall add",
        ["action", "src_ip", "dst_ip", "dst_port", "imsi", "supi",
         "access_node", "cell", "proto", "direction", "scope", "duration",
         "reason", "ue_id"]),
    "qos_config": ("qos set",
        ["rate_limit", "imsi", "src_ip", "app", "direction", "cell", "proto",
         "upf", "dst_port", "dscp", "slice", "priority", "class", "scope",
         "ue_id", "preserve_app"]),
    "sdn_flow_config": ("sdn flow",
        ["match_src", "match_dst", "action", "switch", "switches", "proto",
         "dst_port", "out_port", "imsi", "slice", "duration", "reason"]),
    "ran_handover_config": ("ran handover",  # 이웃 설정은 'ran neighbor'
        ["action", "imsi", "supi", "source_cell", "target_cell",
         "neighbor_cell", "preferred_target", "access_node", "ue_id",
         "priority", "path", "reason"]),
    "slice_policy_config": ("slice policy",
        ["app", "slice", "imsi", "supi", "upf", "src_ip", "priority",
         "from_slice", "target_class", "profile", "edge_node"]),
    "edge_acl_config": ("edge acl",
        ["node", "action", "src_ip", "path", "imsi", "source_runbook"]),
    "operator_history_config": ("firewall add",
        ["action", "src_ip", "imsi", "source_ticket", "source_tickets"]),
    "rag_doc_config": ("sdn flow",  # 또는 'ran handover'
        ["action", "switch", "match_src", "match_dst", "source_doc", "imsi",
         "source_cell", "target_cell", "source_runbook"]),
}

ACTION_ENUM = ["deny", "drop", "forward", "rate_limit", "block",
               "exclude", "force", "quarantine"]

SYSTEM = (
    "You are a network operations assistant. Convert the operator request into a "
    "SINGLE normalized command of the form `<prefix> key=value key=value ...`, "
    "e.g. `firewall add action=deny src_ip=10.0.0.1 imsi=00101...`.\n"
    "Rules:\n"
    "- Use ONLY the command prefix and key names provided for this task type. "
    "Do NOT invent or rename keys (e.g. use `access_node`, not `gnb`; "
    "`proto`, not `protocol`; `match_src`, not `src_ip` for SDN flows).\n"
    f"- The `action` value MUST be one of: {', '.join(ACTION_ENUM)}.\n"
    "- Include only keys that the request actually specifies. Keep value casing "
    "as given (lowercase enum/proto values).\n"
    "- Use ONLY values present in the request; never invent or expand identifiers. "
    "Keep placeholder tokens like [IP_1] verbatim.\n"
    "- Return ONLY the structured fields."
)


def build_prompt(masked_request: str, task_type: str = "") -> str:
    spec = GRAMMAR.get(task_type)
    grammar = ""
    if spec:
        prefix, keys = spec
        grammar = (f"\n\nTask type: {task_type}\n"
                   f"Command prefix: `{prefix}`\n"
                   f"Allowed keys: {', '.join(keys)}")
    return (f"Operator request:\n{masked_request}{grammar}\n\n"
            "Return the normalized config.")


# ── provider 구현 ─────────────────────────────────────────────────
def _call_anthropic(prompt):
    import anthropic
    client = anthropic.Anthropic()
    t0 = time.time()
    resp = client.messages.create(
        model=config.MODEL, max_tokens=config.MAX_TOKENS,
        temperature=config.TEMPERATURE, system=SYSTEM,
        tools=[{"name": "emit_config",
                "description": "Return the normalized config.",
                "input_schema": OUTPUT_SCHEMA}],
        tool_choice={"type": "tool", "name": "emit_config"},
        messages=[{"role": "user", "content": prompt}],
    )
    dt = time.time() - t0
    block = next(b for b in resp.content if b.type == "tool_use")
    return block.input, dt, resp.usage.input_tokens, resp.usage.output_tokens


def _call_openai(prompt):
    from openai import OpenAI
    client = OpenAI()
    t0 = time.time()
    resp = client.chat.completions.create(
        model=config.MODEL, temperature=config.TEMPERATURE,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": prompt}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "config_out",
                                         "schema": OUTPUT_SCHEMA, "strict": True}},
    )
    dt = time.time() - t0
    parsed = json.loads(resp.choices[0].message.content)
    u = resp.usage
    return parsed, dt, u.prompt_tokens, u.completion_tokens


def _call_mock(prompt, sample, mask_meta):
    """이상적 마스킹 준수 모델: 정답 config의 원본값을 마스킹값으로 치환해 반환.
    → C0는 원본값 누출, C1/C2/C3는 마스킹값만 출력(누출 0)을 재현."""
    t0 = time.time()
    cfg = sample["expected_answer_normalized"]
    for original, masked in sorted(mask_meta["fwd"].items(),
                                   key=lambda kv: -len(kv[0])):
        cfg = cfg.replace(original, masked)
    out = {"normalized_config": cfg,
           "sensitive_entities_in_output": [],
           "confidence": 0.9}
    return out, time.time() - t0, len(prompt) // 4, len(cfg) // 4


def call_llm(prompt, sample=None, mask_meta=None):
    if config.PROVIDER == "anthropic":
        return _call_anthropic(prompt)
    if config.PROVIDER == "openai":
        return _call_openai(prompt)
    if config.PROVIDER == "mock":
        return _call_mock(prompt, sample, mask_meta)
    raise ValueError(f"unknown PROVIDER: {config.PROVIDER}")
