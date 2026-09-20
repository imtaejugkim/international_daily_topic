#!/usr/bin/env python3
"""Optional Korean annotation for foreign keywords and app names.

Uses the Anthropic API when ANTHROPIC_API_KEY is set and the `anthropic`
package is installed. Without either, every lookup returns nothing and callers
fall back to the original text. Nothing here raises: a missing translation
must never take the daily run down with it.
"""

import json
import os
import re
import sys

MODEL = "claude-opus-5"
BATCH = 100

# Hangul syllables plus standalone jamo - text containing any of these is
# already Korean and needs no annotation.
HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")

SYSTEM = """\
너는 각국 트렌드 키워드와 앱 이름에 한국어 표기를 붙이는 도구다.

규칙:
- 인명·팀명·브랜드 같은 고유명사는 한글 음차로 적는다. ("cj carr" -> "씨제이 카")
- 일반명사와 구문은 뜻을 옮긴다. ("flüge" -> "항공권", "hotels" -> "호텔")
- 널리 쓰이는 약어는 무엇인지 드러낸다. ("ufc" -> "종합격투기 UFC")
- 앱 이름은 부제를 빼고 핵심만 짧게 옮긴다.
- 10자 이내로 간결하게. 설명문을 쓰지 마라.
- 옮기는 게 무의미하거나 확신이 서지 않는 항목은 결과에서 빼라. 지어내지 마라.

입력은 JSON 문자열 배열이다.
출력은 {"원문": "한글표기"} 형태의 JSON 객체 하나뿐. 다른 텍스트는 쓰지 마라."""


def needs_korean(text):
    """True when this text is worth annotating (non-empty and not Korean)."""
    return bool(text and text.strip()) and not HANGUL.search(text)


def _parse(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if k and v}


def annotate(texts):
    """Return {original: korean}. Always a dict, never raises."""
    targets = sorted({t.strip() for t in texts if needs_korean(t)})
    if not targets:
        return {}

    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("[korean] ANTHROPIC_API_KEY not set - skipping annotation", file=sys.stderr)
        return {}

    try:
        import anthropic
    except ImportError:
        print("[korean] anthropic package not installed - skipping", file=sys.stderr)
        return {}

    client = anthropic.Anthropic()
    out = {}
    for i in range(0, len(targets), BATCH):
        batch = targets[i : i + BATCH]
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=8000,
                system=SYSTEM,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": json.dumps(batch, ensure_ascii=False)}],
            )
            if response.stop_reason == "refusal":
                print("[korean] refused: %s" % response.stop_details, file=sys.stderr)
                continue
            text = "".join(b.text for b in response.content if b.type == "text")
            out.update(_parse(text))
        except Exception as exc:  # noqa: BLE001 - annotation is best-effort
            print("[korean] batch failed: %s" % exc, file=sys.stderr)

    print("[korean] annotated %d/%d" % (len(out), len(targets)), file=sys.stderr)
    return out


def label(text, korean):
    """Render text with its Korean annotation appended, when there is one."""
    ko = korean.get(text.strip()) if korean else None
    return "%s (%s)" % (text, ko) if ko and ko != text else text
