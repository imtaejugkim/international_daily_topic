#!/usr/bin/env python3
"""Render brief.json to Discord.

The analysis itself happens in the `daily-brief` skill, run by the Claude
Code GitHub Action, which reads the snapshots under data/ and writes
brief.json. This file only turns that into embeds and posts them, so the
model call and the delivery stay independent of each other.

Environment variables:
  DISCORD_WEBHOOK_URL  Discord webhook (required unless DRY_RUN=1)
  DRY_RUN              "1" to print instead of sending
  BRIEF_PATH           path to the brief (default brief.json)
"""

import json
import os
import sys
import time

from trends_to_discord import MAX_DESC, chunk, clip, post

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

    date = brief.get("date", "")
    embeds = build_embeds(brief, date)
    print("[brief] %d themes, %d ideas -> %d embeds"
          % (len(brief.get("themes") or []), len(brief.get("ideas") or []), len(embeds)),
          file=sys.stderr)

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
