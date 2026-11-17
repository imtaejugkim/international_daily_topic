#!/usr/bin/env python3
"""Render brief.json to Discord.

The analysis itself happens in the `daily-brief` skill, run by the Claude
Code GitHub Action, which reads the snapshots under data/ and writes
brief.json. This file only turns that into embeds and posts them, so the
model call and the delivery stay independent of each other.

Also archives each brief under data/briefs/ and echoes it to the log. The
brief is the part that needs tuning, so it has to stay readable after the
run: without a copy there is no way to see what was written, and the root
brief.json is a scratch handoff that does not survive.

Environment variables:
  DISCORD_WEBHOOK_URL  Discord webhook (required unless DRY_RUN=1)
  DRY_RUN              "1" to print instead of sending or archiving
  BRIEF_PATH           path to the brief (default brief.json)
"""

import json
import os
import sys
import time
from datetime import datetime

from discord_post import KST, MAX_DESC, chunk, clip, post

VERDICT = {
    "open":    ("\U0001F7E2", "열림"),
    "mill":    ("\U0001F534", "고기 분쇄기"),
    "unclear": ("\u26AA", "판단 보류"),
}


def build_embeds(brief, date):
    embeds = []

    genres = brief.get("genres") or []
    if genres:
        rows = []
        for g in genres[:6]:
            icon, label = VERDICT.get(g.get("verdict", ""), ("\u26AA", ""))
            rows.append("\n".join(filter(None, [
                "%s **%s** — %s" % (icon, g.get("tag", "?"), label),
                "`%s`" % g["numbers"] if g.get("numbers") else "",
                "\u00b7 %s" % g["price"] if g.get("price") else "",
                "\u00b7 %s" % g["note"] if g.get("note") else "",
            ])))
        embeds.append({
            "title": "\U0001F4CA 장르 판정 \u2014 %s" % date,
            "description": clip("\n\n".join(rows), MAX_DESC),
            "color": 0x1A73E8,
        })

    for w in (brief.get("watch") or [])[:5]:
        body = "\n\n".join(filter(None, [
            w.get("what", ""),
            "**왜 지금** %s" % w["why"] if w.get("why") else "",
            "**장르 승산** %s" % w["genre_odds"] if w.get("genre_odds") else "",
            "**정보** %s" % w["facts"] if w.get("facts") else "",
            w.get("url", ""),
        ]))
        embeds.append({
            "title": clip("\U0001F3AE %s" % w.get("name", "?"), 240),
            "description": clip(body, MAX_DESC),
            "color": 0xE8710A,
        })

    if not brief.get("watch"):
        embeds.append({
            "title": "\U0001F3AE 오늘은 볼 것 없음",
            "description": "영상을 찾아볼 만한 게임이 나오지 않았습니다.",
            "color": 0xE8710A,
        })

    if brief.get("direction"):
        embeds.append({
            "title": "\U0001F9ED 데이터가 가리키는 방향",
            "description": clip(brief["direction"], MAX_DESC),
            "color": 0x34A853,
        })

    if brief.get("counter"):
        embeds.append({
            "title": "\U0001F9CA 이 브리프가 틀렸다면",
            "description": clip(brief["counter"], MAX_DESC),
            "color": 0x5F6368,
        })
    return embeds


def main():
    path = os.environ.get("BRIEF_PATH", "brief.json")
    if not os.path.exists(path):
        print("[brief] %s not found - the analysis step did not write one" % path,
              file=sys.stderr)
        return 0

    try:
        with open(path, encoding="utf-8") as f:
            brief = json.load(f)
    except (OSError, ValueError) as exc:
        print("[brief] could not read %s: %s" % (path, exc), file=sys.stderr)
        return 0

    date = brief.get("date", "") or datetime.now(KST).strftime("%Y-%m-%d")
    embeds = build_embeds(brief, date)
    print("[brief] genres=%d watch=%d -> %d embeds"
          % (len(brief.get("genres") or []), len(brief.get("watch") or []), len(embeds)),
          file=sys.stderr)

    # Echo the rendered brief so a run's output is legible in the job log.
    for e in embeds:
        print("\n=== %s ===" % e["title"])
        print(e["description"])

    if os.environ.get("DRY_RUN") != "1":
        archive = os.path.join("data", "briefs", "%s.json" % date)
        os.makedirs(os.path.dirname(archive), exist_ok=True)
        with open(archive, "w", encoding="utf-8") as f:
            json.dump(brief, f, ensure_ascii=False, indent=1, sort_keys=True)
        print("[saved] %s" % archive, file=sys.stderr)

    header = "\U0001F3AE **오늘의 게임 브리프** — 어디가 열려 있나 · 뭘 볼까"

    if os.environ.get("DRY_RUN") == "1":
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
