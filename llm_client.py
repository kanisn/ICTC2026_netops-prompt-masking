"""
llm_client.py - provider-agnostic LLM call wrapper (B-5)

call_llm(prompt, sample, mask_meta) -> (parsed_json, latency, in_tok, out_tok)

Output always follows the same JSON schema (B-6):
  {
    "normalized_config": "<cmd key=value ...>",
    "sensitive_entities_in_output": [...],   # model self-report (auxiliary)
    "confidence": 0.0~1.0
  }

PROVIDER:
  - "anthropic": Claude Haiku (schema enforced via tool_use)
  - "openai"   : gpt-5.4-mini (response_format=json_schema)
  - "google"   : Gemini (response_schema + JSON mime type)
  - "mock"     : offline pipeline check; simulates an "ideal masking-compliant
                 model" by passing the masked values straight through.
"""
import json
import logging
import os
import re
import time

import config

# Quiet the google-genai "non-text parts (thought_signature)" warnings.
for _n in ("google_genai", "google_genai.types", "google.genai"):
    logging.getLogger(_n).setLevel(logging.ERROR)

# Shared output JSON schema
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

# ── Output grammar (extracted from the gold normalized vocabulary) ─
# task_type -> (command prefix, allowed key list)
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
    "ran_handover_config": ("ran handover",  # neighbor setup uses 'ran neighbor'
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
    "rag_doc_config": ("sdn flow",  # or 'ran handover'
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


# ── provider implementations ──────────────────────────────────────
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


def _gemini_text(resp):
    """Extract JSON text from a Gemini response.

    Reads the text parts directly (skipping 'thought' parts) so we do NOT touch
    resp.text, which emits a noisy SDK warning when thought parts are present.
    """
    try:
        parts = resp.candidates[0].content.parts or []
        texts = [p.text for p in parts
                 if getattr(p, "text", None) and not getattr(p, "thought", False)]
        if texts:
            return "".join(texts)
    except Exception:
        pass
    return getattr(resp, "text", "") or ""


def _loads_loose(s):
    """Tolerant JSON parse: strip code fences, else extract the first {...}."""
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _call_gemini(prompt):
    from google import genai
    from google.genai import types
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    # Gemini response schema (OpenAPI subset): no additionalProperties
    gemini_schema = {
        "type": "object",
        "properties": {
            "normalized_config": {"type": "string"},
            "sensitive_entities_in_output": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": ["normalized_config", "sensitive_entities_in_output", "confidence"],
        "propertyOrdering": ["normalized_config", "sensitive_entities_in_output", "confidence"],
    }
    # Disable "thinking" so the token budget is not consumed by thought parts
    # (which can truncate the JSON); give a comfortable output budget.
    cfg_kwargs = dict(
        system_instruction=SYSTEM,
        temperature=config.TEMPERATURE,
        max_output_tokens=max(config.MAX_TOKENS, 1024),
        response_mime_type="application/json",
        response_schema=gemini_schema,
    )
    try:
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass
    t0 = time.time()
    resp = client.models.generate_content(
        model=config.MODEL, contents=prompt,
        config=types.GenerateContentConfig(**cfg_kwargs),
    )
    dt = time.time() - t0
    parsed = _loads_loose(_gemini_text(resp))
    um = resp.usage_metadata
    return parsed, dt, um.prompt_token_count, (um.candidates_token_count or 0)


def _call_mock(prompt, sample, mask_meta):
    """Ideal masking-compliant model: returns the gold config with original
    values replaced by their masked values.
    -> reproduces C0 leaking originals, and C1/C2/C3 emitting only masked
    values (zero leakage)."""
    t0 = time.time()
    cfg = sample["expected_answer_normalized"]
    for original, masked in sorted(mask_meta["fwd"].items(),
                                   key=lambda kv: -len(kv[0])):
        cfg = cfg.replace(original, masked)
    out = {"normalized_config": cfg,
           "sensitive_entities_in_output": [],
           "confidence": 0.9}
    return out, time.time() - t0, len(prompt) // 4, len(cfg) // 4


def _dispatch(prompt, sample, mask_meta):
    if config.PROVIDER == "anthropic":
        return _call_anthropic(prompt)
    if config.PROVIDER == "openai":
        return _call_openai(prompt)
    if config.PROVIDER == "google":
        return _call_gemini(prompt)
    if config.PROVIDER == "mock":
        return _call_mock(prompt, sample, mask_meta)
    raise ValueError(f"unknown PROVIDER: {config.PROVIDER}")


# Substrings that mark a transient (retryable) server/rate-limit error.
_TRANSIENT = ("503", "unavailable", "429", "resource_exhausted", "overloaded",
              "500", "internal", "deadline", "timeout", "temporarily")


def call_llm(prompt, sample=None, mask_meta=None, retries=6):
    """Dispatch to the selected provider, retrying transient errors with backoff."""
    for attempt in range(retries):
        try:
            return _dispatch(prompt, sample, mask_meta)
        except Exception as e:
            msg = str(e).lower()
            if any(t in msg for t in _TRANSIENT) and attempt < retries - 1:
                wait = min(60, 5 * (2 ** attempt))   # 5,10,20,40,60,...
                print(f"  [retry {attempt + 1}/{retries}] transient error; waiting {wait}s ...")
                time.sleep(wait)
                continue
            raise
