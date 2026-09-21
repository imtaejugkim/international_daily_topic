#!/usr/bin/env python3
"""Turn today's snapshots into a daily brief and post it to Discord.

This is the step that makes the pipeline something other than a relay. The
collectors write raw material to data/; this reads all of it at once - news
headlines, search keywords, app charts, day-over-day movement and low-star
reviews - and produces the thing actually worth reading: which subjects the
six countries keep returning to, where they agree and differ, and what that
implies for something to build.

Grounded in the actual headlines, apps and complaints, not in generic startup
talk.

Needs ANTHROPIC_API_KEY. Without it this exits cleanly with a note, so the
rest of the daily run is unaffected.

Environment variables:
  ANTHROPIC_API_KEY    required for this step
  DISCORD_WEBHOOK_URL  Discord webhook (required unless DRY_RUN=1)
  DRY_RUN              "1" to print instead of sending
  IDEA_REVIEWS         how many reviews to feed the model (default 250)
  IDEA_HEADLINES       how many headlines to feed the model (default 600)
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
너는 창업 아이디어를 찾는 사람의 리서치 파트너다. 매일 6개국(한국·미국·일본·영국·독일·브라질)에서
모은 자료를 받는다: 뉴스 헤드라인, 구글 검색 급상승어, 앱스토어 차트, 어제 대비 순위 변화,
그리고 상위 앱들의 1~2점 리뷰.

네 일은 자료를 요약하는 게 아니다. 자료를 읽어내는 것이다.
순위표와 헤드라인 목록은 이미 저장돼 있다. 그걸 다시 나열하면 아무 가치가 없다.

이 순서로 생각해라.

1. 반복 주제: 여러 나라 헤드라인에 되풀이되는 주제를 찾아라. 한 나라에만 있으면 그 나라 뉴스지만,
   서너 나라에 동시에 있으면 흐름이다. 같은 주제가 나라마다 다르게 다뤄지는 지점이 특히 중요하다.
2. 나라별 상황: 각 나라가 지금 무엇에 붙들려 있는지 2~3문장. 뉴스·검색어·앱차트가 같은 곳을
   가리키면 그게 진짜다. 서로 엇갈리면 그 엇갈림 자체를 말해라.
3. 아이디어: 위에서 읽어낸 것에 근거해서만 제안해라. 가장 강한 재료는 저평점 리뷰다.
   차트는 "무엇이 뜨는가"만 말하지만 리뷰는 "사람들이 무엇을 못 견디는가"를 말한다.

아이디어에서 지켜야 할 것:
- 여러 나라에서 반복되는 불만을 우선해라. 한 나라에만 있는 불만은 대개 현지 사정(결제·규제·은행)이라
  기회가 아니라 진입장벽이다.
- 근거에는 실제 헤드라인, 앱 이름, 리뷰 문구를 인용해라. "사용자들이 불편해한다" 같은 뭉뚱그림 금지.
- "AI 기반 ○○ 플랫폼" 같은 공허한 제안 금지. 구체적인 불편 하나를 지목해라.
- 첫 사용자는 구체적으로 써라. "20대 여성"이 아니라 "월 3만원 넘게 구독 중인데 뭘 구독했는지
  모르는 사람" 같은 식으로.
- 첫 버전의 모양은 화면 2~3개 수준으로 실제로 뭘 하는 물건인지 적어라.
- 검증은 하루 안에 돈을 거의 안 쓰고 할 수 있는 것만. (랜딩페이지, 커뮤니티 글 하나, 수동으로 10명)
- 이미 그걸 하고 있는 곳이 보이면 반드시 이름을 대라.
- 데이터에 없는 것을 지어내지 마라.
- 오늘 재료가 약하면 약하다고 말해라. 억지로 채우지 마라. 아이디어 0개나 1개여도 된다.

출력은 아래 JSON 객체 하나뿐. 다른 텍스트는 쓰지 마라.
{
  "themes": [
    {
      "theme": "주제 한 줄",
      "countries": ["KR", "DE"],
      "evidence": "근거가 된 헤드라인/검색어/앱을 인용",
      "so_what": "그래서 무엇을 뜻하는지 1~2문장"
    }
  ],
  "countries": {
    "KR": "지금 이 나라 상황 2~3문장", "US": "...", "JP": "...",
    "GB": "...", "DE": "...", "BR": "..."
  },
  "ideas": [
    {
      "title": "한 줄 제목",
      "one_liner": "이게 뭐하는 물건인지 한 문장",
      "evidence": "어느 나라 어떤 기사/앱/리뷰에서 나왔는지. 인용할 것.",
      "who": "첫 사용자가 구체적으로 누구인지",
      "shape": "첫 버전이 실제로 뭘 하는지. 화면 2~3개 수준.",
      "money": "누가 왜 돈을 내는지",
      "test": "하루 안에 할 수 있는 검증 한 가지",
      "risk": "이미 하는 곳, 또는 이게 안 될 이유"
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


def sample_headlines(news, budget):
    """Round-robin across countries and sections so no single feed dominates."""
    rows = {
        code: [dict(h, country=code, section=sec)
               for sec, items in sections.items() for h in items]
        for code, sections in news.items()
    }
    out, i = [], 0
    while len(out) < budget and any(i < len(v) for v in rows.values()):
        for code, items in rows.items():
            if i < len(items) and len(out) < budget:
                h = items[i]
                out.append({"country": code, "section": h["section"],
                            "title": clip(h["title"], 160), "source": h.get("source", "")})
        i += 1
    return out


def build_input(charts, reviews, sig, news, trends, budget, headline_budget):
    names = {}
    for cc, apps in charts.items():
        for app in apps:
            names[app["id"]] = app["name"]

    return {
        "headlines": sample_headlines(news, headline_budget),
        "search_keywords": {
            cc: [t["title"] for t in items[:10]] for cc, items in trends.items()
        },
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
            "big_risers": {
                cc: ["%s %d->%d" % (a["name"], was, a["rank"]) for a, was in d["risen"]]
                for cc, d in sig["per_country"].items() if d["risen"]
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


FLAGS = {"KR": "\U0001F1F0\U0001F1F7", "US": "\U0001F1FA\U0001F1F8", "JP": "\U0001F1EF\U0001F1F5",
         "GB": "\U0001F1EC\U0001F1E7", "DE": "\U0001F1E9\U0001F1EA", "BR": "\U0001F1E7\U0001F1F7"}


def build_embeds(brief, date):
    embeds = []

    themes = brief.get("themes") or []
    if themes:
        blocks = []
        for t in themes[:5]:
            flags = " ".join(FLAGS.get(c, c) for c in (t.get("countries") or []))
            blocks.append("**%s** %s\n%s\n_%s_" % (
                t.get("theme", "?"), flags,
                t.get("evidence", ""), t.get("so_what", "")))
        embeds.append({
            "title": "\U0001F4F0 여러 나라에서 반복되는 주제 — %s" % date,
            "description": clip("\n\n".join(blocks), MAX_DESC),
            "color": 0xFBBC05,
        })

    per_country = brief.get("countries") or {}
    if per_country:
        rows = ["%s **%s** %s" % (FLAGS.get(cc, ""), cc, text)
                for cc, text in per_country.items()]
        embeds.append({
            "title": "\U0001F5FA\uFE0F 나라별 지금 상황",
            "description": clip("\n\n".join(rows), MAX_DESC),
            "color": 0x4285F4,
        })

    for i, idea in enumerate(brief.get("ideas") or [], 1):
        body = "\n\n".join(filter(None, [
            "_%s_" % idea["one_liner"] if idea.get("one_liner") else "",
            "**근거** %s" % idea["evidence"] if idea.get("evidence") else "",
            "**첫 사용자** %s" % idea["who"] if idea.get("who") else "",
            "**첫 버전** %s" % idea["shape"] if idea.get("shape") else "",
            "**수익 가설** %s" % idea["money"] if idea.get("money") else "",
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
            "description": "재료에서 밀어붙일 만한 신호가 나오지 않았습니다.",
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
    headline_budget = int(os.environ.get("IDEA_HEADLINES", "600"))

    date, chart_snap = latest_snapshot("charts")
    _, review_snap = latest_snapshot("reviews")
    _, news_snap = latest_snapshot("news")
    _, trend_snap = latest_snapshot("trends")
    if not chart_snap:
        print("[ideas] no chart snapshot yet - run app_charts.py first", file=sys.stderr)
        return 0

    charts = chart_snap["charts"]
    reviews = (review_snap or {}).get("reviews", {})
    news = (news_snap or {}).get("news", {})
    trends = (trend_snap or {}).get("trends", {})
    sig = charts_mod.signals(charts, charts_mod.load_previous("charts", date), 10)

    payload = build_input(charts, reviews, sig, news, trends, budget, headline_budget)
    print("[ideas] feeding %d headlines, %d reviews, %d apps, %d keyword sets"
          % (len(payload["headlines"]), len(payload["low_star_reviews"]),
             sum(len(v) for v in payload["charts"].values()),
             len(payload["search_keywords"])), file=sys.stderr)

    try:
        brief = ask(payload)
    except Exception as exc:  # noqa: BLE001 - the brief must not sink the run
        print("[ideas] failed: %s" % exc, file=sys.stderr)
        return 0

    embeds = build_embeds(brief, date)
    header = "\U0001F9E0 **오늘의 브리프** — 뉴스·검색어·앱차트·리뷰를 읽은 결과"

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
