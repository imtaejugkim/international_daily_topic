#!/usr/bin/env python3
"""Turn today's snapshot into a short idea brief and post it to Discord.

Reads the chart and review snapshots app_charts.py writes and asks Claude to
read them the way a founder would - grounded in the actual apps and the actual
complaints, not in generic startup talk.

Needs ANTHROPIC_API_KEY. Without it this exits cleanly with a note, so the
rest of the daily run is unaffected.

Environment variables:
  ANTHROPIC_API_KEY    required for this step
  DISCORD_WEBHOOK_URL  Discord webhook (required unless DRY_RUN=1)
  DRY_RUN              "1" to print instead of sending
  IDEA_REVIEWS         how many reviews to feed the model (default 250)
"""

import glob
import json
import os
import sys
import time
from datetime import datetime

import app_charts as charts_mod
from trends_to_discord import MAX_DESC, chunk, clip, post

MODEL = "claude-opus-5"
REVIEWS_PER_APP = 5
REVIEW_CHARS = 300

SYSTEM = """\
너는 창업 아이디어를 찾는 사람의 리서치 파트너다. 매일 6개국(한국·미국·일본·영국·독일·브라질)
앱스토어 차트와 그 앱들의 1~2점 리뷰를 받아, 하루치 브리프를 쓴다.

가장 중요한 재료는 저평점 리뷰다. 차트는 "무엇이 뜨는가"만 말해주지만,
리뷰는 "사람들이 무엇을 못 견디는가"를 말해준다. 후자가 기회다.

지켜야 할 것:
- 데이터에 실제로 있는 것만 써라. 없는 사실을 지어내지 마라.
- 근거에는 실제 앱 이름, 국가, 리뷰 문구를 인용해라. "사용자들이 불편해한다" 같은 뭉뚱그림 금지.
- 여러 나라에서 반복되는 불만을 우선해라. 한 나라에만 있는 불만은 대개 현지 사정(결제·규제·은행)이라
  기회가 아니라 진입장벽이다.
- 검증 방법은 하루 안에, 돈을 거의 안 쓰고 할 수 있는 것으로만 제시해라.
  (랜딩페이지, 커뮤니티 글 하나, 수동으로 10명에게 해보기 같은 것)
- 이미 그걸 하고 있는 경쟁자가 보이면 반드시 이름을 대라.
- "AI 기반 ~ 플랫폼" 같은 공허한 제안을 하지 마라. 구체적인 불편 하나를 지목해라.
- 오늘 데이터가 약하면 약하다고 말해라. 아이디어를 억지로 채우지 마라. 0개나 1개여도 된다.

출력은 아래 JSON 객체 하나뿐. 다른 텍스트는 쓰지 마라.
{
  "reading": "오늘 데이터에서 실제로 읽히는 흐름. 3~4문장.",
  "ideas": [
    {
      "title": "한 줄 제목",
      "evidence": "어느 나라 어떤 앱, 어떤 리뷰에서 나왔는지. 문구를 인용할 것.",
      "why_now": "왜 지금인지. 2문장 이내.",
      "test": "하루 안에 할 수 있는 검증 한 가지.",
      "risk": "이미 하는 곳, 또는 이게 안 될 이유."
    }
  ],
  "counter": "오늘 브리프가 틀렸을 가능성. 데이터의 한계나 과잉해석 지점을 짚어라."
}"""


def latest_snapshot(kind):
    paths = sorted(glob.glob(os.path.join(charts_mod.DATA, kind, "*.json")))
    if not paths:
        return None, None
    with open(paths[-1], encoding="utf-8") as f:
        return os.path.basename(paths[-1])[:-5], json.load(f)


def sample_reviews(reviews, budget):
    """Worst-rated reviews first, spread across countries so one loud
    storefront cannot crowd the others out."""
    per_country = {}
    for cc, apps in reviews.items():
        rows = []
        for app_id, items in apps.items():
            for r in sorted(items, key=lambda r: r["rating"])[:REVIEWS_PER_APP]:
                rows.append({
                    "app_id": app_id,
                    "rating": r["rating"],
                    "text": clip("%s %s" % (r.get("title", ""), r.get("content", "")), REVIEW_CHARS),
                })
        per_country[cc] = rows

    out, i = [], 0
    while len(out) < budget and any(i < len(v) for v in per_country.values()):
        for cc, rows in per_country.items():
            if i < len(rows) and len(out) < budget:
                out.append(dict(rows[i], country=cc))
        i += 1
    return out


def build_input(charts, reviews, sig, budget):
    names = {}
    for cc, apps in charts.items():
        for app in apps:
            names[app["id"]] = app["name"]

    return {
        "charts": {
            cc: [{"rank": a["rank"], "id": a["id"], "name": a["name"],
                  "genres": a["genres"]} for a in apps[:15]]
            for cc, apps in charts.items()
        },
        "signals": {
            "in_many_countries": [
                {"name": e["name"], "countries": e["countries"]} for e in sig["universal"][:10]
            ],
            "only_one_country": [
                {"country": cc, "name": a["name"]} for cc, a in sig["solo"][:15]
            ],
            "new_entrants": {
                cc: [a["name"] for a in d["new"]]
                for cc, d in sig["per_country"].items() if d["new"]
            },
        },
        "app_names": names,
        "low_star_reviews": sample_reviews(reviews, budget),
    }


def ask(payload):
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("refused: %s" % response.stop_details)
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    usage = response.usage
    print("[ideas] in=%d out=%d tokens" % (usage.input_tokens, usage.output_tokens), file=sys.stderr)
    return json.loads(text)


def build_embeds(brief, date):
    embeds = [{
        "title": "\U0001F4D6 오늘 읽히는 것 — %s" % date,
        "description": clip(brief.get("reading", ""), MAX_DESC),
        "color": 0xFBBC05,
    }]

    for i, idea in enumerate(brief.get("ideas", []), 1):
        body = "\n\n".join(filter(None, [
            "**근거** %s" % idea["evidence"] if idea.get("evidence") else "",
            "**왜 지금** %s" % idea["why_now"] if idea.get("why_now") else "",
            "**하루 검증** %s" % idea["test"] if idea.get("test") else "",
            "**걸림돌** %s" % idea["risk"] if idea.get("risk") else "",
        ]))
        embeds.append({
            "title": clip("\U0001F4A1 %d. %s" % (i, idea.get("title", "?")), 240),
            "description": clip(body, MAX_DESC),
            "color": 0x9334E6,
        })

    if not brief.get("ideas"):
        embeds.append({
            "title": "\U0001F4A1 오늘은 제안 없음",
            "description": "데이터에서 밀어붙일 만한 신호가 나오지 않았습니다.",
            "color": 0x9334E6,
        })

    if brief.get("counter"):
        embeds.append({
            "title": "\U0001F9CA 이 브리프가 틀렸다면",
            "description": clip(brief["counter"], MAX_DESC),
            "color": 0x5F6368,
        })
    return embeds


def main():
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("[ideas] ANTHROPIC_API_KEY not set - skipping the idea brief", file=sys.stderr)
        return 0
    try:
        import anthropic  # noqa: F401
    except ImportError:
        print("[ideas] anthropic package not installed - skipping", file=sys.stderr)
        return 0

    budget = int(os.environ.get("IDEA_REVIEWS", "250"))
    date, chart_snap = latest_snapshot("charts")
    _, review_snap = latest_snapshot("reviews")
    if not chart_snap:
        print("[ideas] no chart snapshot yet - run app_charts.py first", file=sys.stderr)
        return 0

    charts = chart_snap["charts"]
    reviews = (review_snap or {}).get("reviews", {})
    sig = charts_mod.signals(charts, charts_mod.load_previous("charts", date), 10)

    payload = build_input(charts, reviews, sig, budget)
    print("[ideas] feeding %d apps, %d reviews"
          % (sum(len(v) for v in payload["charts"].values()),
             len(payload["low_star_reviews"])), file=sys.stderr)

    try:
        brief = ask(payload)
    except Exception as exc:  # noqa: BLE001 - the brief must not sink the run
        print("[ideas] failed: %s" % exc, file=sys.stderr)
        return 0

    embeds = build_embeds(brief, date)
    header = "\U0001F9E0 **오늘의 아이디어 브리프**"

    if os.environ.get("DRY_RUN") == "1":
        print(header)
        for e in embeds:
            print("\n=== %s ===" % e["title"])
            print(e["description"])
        return 0

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("DISCORD_WEBHOOK_URL is not set", file=sys.stderr)
        return 2

    for i, group in enumerate(chunk(embeds)):
        payload = {"embeds": group}
        if i == 0:
            payload["content"] = header
        status = post(webhook, payload)
        print("[discord] sent %d embeds (HTTP %s)" % (len(group), status), file=sys.stderr)
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
