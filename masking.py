"""
masking.py — 로컬 결정적 마스킹 모듈 (B-0 역할분담: 마스킹은 전부 로컬)

지원 모드:
  - "none"        : 마스킹 없음 (C0)
  - "placeholder" : M1, 식별자 → [TYPE_n] 토큰 (C1)
  - "pseudonym"   : M2, 식별자 → 형식 보존 가짜값 (C2 비일관 / C3 일관)

형식 보존 방식: 값의 문자 클래스(숫자/대문자/소문자/구두점)를 보존한 채
치환 → IP의 점, IMSI 길이, Cell-17A 패턴 등 구조가 그대로 유지됨.
모든 식별자 타입에 동일 로직이 통하므로 타입별 규칙이 필요 없음.

반환:
  masked_text : LLM에 보낼 마스킹 입력
  meta = {
    "rev":  {masked_token_or_value: original},  # unmask·누출대조용
    "fwd":  {original: first_masked},            # mock 모델용
    "originals": [original identifier values...], # 누출률 분모(B-7)
  }
"""
import json
import random
import re

from config import IDENTIFIER_TYPES, normalize_type


# ── 식별자 값 추출 ─────────────────────────────────────────────────
def identifier_values(sensitive_fields: dict):
    """(type, value) 리스트. 식별자 타입만, 리스트 필드는 평탄화."""
    out = []
    for key, val in sensitive_fields.items():
        t = normalize_type(key)
        if t not in IDENTIFIER_TYPES:
            continue
        vals = val if isinstance(val, list) else [val]
        for v in vals:
            out.append((t, str(v)))
    return out


# ── 형식 보존 치환 ────────────────────────────────────────────────
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
            chars.append(ch)  # 점/하이픈/슬래시 등 구조 보존
    out = "".join(chars)
    return out if out != value else _format_preserving(value, rng) if value.strip(".-_/ ") else out


def _seeded(*parts) -> random.Random:
    return random.Random("|".join(map(str, parts)))


# ── 메인 마스킹 ───────────────────────────────────────────────────
def mask_text(text: str, sensitive_fields: dict, mode: str, consistent: bool):
    idents = identifier_values(sensitive_fields)
    rev, fwd = {}, {}

    meta = {"rev": rev, "fwd": fwd,
            "originals": [v for _, v in idents]}

    if mode == "none" or not idents:
        return text, meta

    masked = text
    type_counter = {}

    # 긴 값 먼저 치환 → 부분 문자열 충돌 방지
    for t, val in sorted(idents, key=lambda x: -len(x[1])):
        if val not in masked:
            # 값이 본문에 그대로 없을 수 있음(라벨만 존재) — rev엔 등록해 둠
            pass

        if mode == "placeholder":
            if val in fwd:                      # 동일 값 일관 토큰 (M1은 항상 일관)
                token = fwd[val]
            else:
                n = type_counter.get(t, 0) + 1
                type_counter[t] = n
                token = f"[{t.upper()}_{n}]"
                fwd[val] = token
                rev[token] = val
            masked = masked.replace(val, token)

        elif mode == "pseudonym":
            if consistent:                      # C3: 엔티티당 고정 가짜값
                if val not in fwd:
                    fake = _format_preserving(val, _seeded("C3", val))
                    fwd[val] = fake
                    rev[fake] = val
                masked = masked.replace(val, fwd[val])
            else:                               # C2: 출현마다 다른 가짜값
                counter = {"i": 0}

                def _sub(_m, _val=val):
                    counter["i"] += 1
                    fake = _format_preserving(_val, _seeded("C2", _val, counter["i"]))
                    rev[fake] = _val
                    fwd.setdefault(_val, fake)
                    return fake
                masked = re.sub(re.escape(val), _sub, masked)

    return masked, meta


# ── 언마스크 (출력 복원, B-7 command validity 단계) ────────────────
def unmask_text(text: str, rev: dict) -> str:
    out = text
    for masked in sorted(rev, key=len, reverse=True):
        out = out.replace(masked, rev[masked])
    return out


if __name__ == "__main__":
    # 간단 자가 테스트
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
