"""
masking.py - local deterministic masking module (B-0: masking is all local)

Supported modes:
  - "none"        : no masking (C0)
  - "placeholder" : M1, identifier -> [TYPE_n] token (C1)
  - "pseudonym"   : M2, identifier -> format-preserving fake value
                    (C2 non-consistent / C3 consistent)

Format preservation: replaces each character by its class
(digit/upper/lower/punctuation), so structure stays intact - the dots in an
IP, the IMSI length, the Cell-17A pattern, etc. The same logic works for every
identifier type, so no per-type rules are needed.

Returns:
  masked_text : the masked input to send to the LLM
  meta = {
    "rev":  {masked_token_or_value: original},   # for unmask / leakage compare
    "fwd":  {original: first_masked},            # for the mock model
    "originals": [original identifier values...], # leakage denominator (B-7)
  }
"""
import json
import random
import re

from config import IDENTIFIER_TYPES, normalize_type


# ── extract identifier values ─────────────────────────────────────
def identifier_values(sensitive_fields: dict):
    """List of (type, value). Identifier types only; list fields are flattened."""
    out = []
    for key, val in sensitive_fields.items():
        t = normalize_type(key)
        if t not in IDENTIFIER_TYPES:
            continue
        vals = val if isinstance(val, list) else [val]
        for v in vals:
            out.append((t, str(v)))
    return out


# ── format-preserving substitution ───────────────────────────────
def _format_preserving(value: str, rng: random.Random) -> str:
    chars = []
    for ch in value:
        if ch.isdigit():
            chars.append(str(rng.randint(0, 9)))
        elif ch.isupper():
            chars.append(chr(rng.randint(ord("A"), ord("Z"))))
        elif ch.islower():
            chars.append(chr(rng.randint(ord("a"), ord("z"))))
        else:
            chars.append(ch)  # keep structure: dots/hyphens/slashes, etc.
    out = "".join(chars)
    return out if out != value else _format_preserving(value, rng) if value.strip(".-_/ ") else out


def _seeded(*parts) -> random.Random:
    return random.Random("|".join(map(str, parts)))


# ── main masking ──────────────────────────────────────────────────
def mask_text(text: str, sensitive_fields: dict, mode: str, consistent: bool):
    idents = identifier_values(sensitive_fields)
    rev, fwd = {}, {}

    meta = {"rev": rev, "fwd": fwd,
            "originals": [v for _, v in idents]}

    if mode == "none" or not idents:
        return text, meta

    masked = text
    type_counter = {}

    # replace longer values first -> avoid substring collisions
    for t, val in sorted(idents, key=lambda x: -len(x[1])):
        if val not in masked:
            # value may not appear verbatim in the text (label only) - still register in rev
            pass

        if mode == "placeholder":
            if val in fwd:                      # same value -> consistent token (M1 is always consistent)
                token = fwd[val]
            else:
                n = type_counter.get(t, 0) + 1
                type_counter[t] = n
                token = f"[{t.upper()}_{n}]"
                fwd[val] = token
                rev[token] = val
            masked = masked.replace(val, token)

        elif mode == "pseudonym":
            if consistent:                      # C3: fixed fake value per entity
                if val not in fwd:
                    fake = _format_preserving(val, _seeded("C3", val))
                    fwd[val] = fake
                    rev[fake] = val
                masked = masked.replace(val, fwd[val])
            else:                               # C2: different fake value per occurrence
                counter = {"i": 0}

                def _sub(_m, _val=val):
                    counter["i"] += 1
                    fake = _format_preserving(_val, _seeded("C2", _val, counter["i"]))
                    rev[fake] = _val
                    fwd.setdefault(_val, fake)
                    return fake
                masked = re.sub(re.escape(val), _sub, masked)

    return masked, meta


# ── unmask (restore output, B-7 command-validity step) ────────────
def unmask_text(text: str, rev: dict) -> str:
    out = text
    for masked in sorted(rev, key=len, reverse=True):
        out = out.replace(masked, rev[masked])
    return out


if __name__ == "__main__":
    # quick self-test
    sf = {"IMSI": "001010000000103", "IP": "10.20.4.11",
          "CELL_IDs": ["Cell-17A", "Cell-18C"]}
    txt = ("log1: IMSI=001010000000103 IP=10.20.4.11 CELL=Cell-17A\n"
           "log2: IMSI=001010000000103 IP=10.20.4.11 CELL=Cell-18C")
    for mode, cons, name in [("placeholder", True, "C1"),
                             ("pseudonym", False, "C2"),
                             ("pseudonym", True, "C3")]:
        m, meta = mask_text(txt, sf, mode, cons)
        print(f"\n=== {name} ===\n{m}")
        print("rev:", meta["rev"])
