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

KIND = {
    "surge":    ("\U0001F680", "급등", 0xE8710A),
    "new":      ("\U0001F195", "신규", 0x1A73E8),
    "climbing": ("\U0001F4C8", "상승", 0x34A853),
    "sinking":  ("\U0001F4C9", "급락", 0x5F6368),
}

TRACKS = {
    "ride":  ("\U0001F30A", "흐름에 올라타기", 0x1A73E8),
    "twist": ("\U0001F300", "비틀기", 0xF9AB00),
    "gap":   ("\U0001F3AF", "빈자리", 0x9334E6),
}


def build_embeds(brief, date):
    embeds = []

    moved = brief.get("moved") or []
    if moved:
        blocks = []
        for m in moved[:6]:
            icon, label, _ = KIND.get(m.get("kind", ""), ("\u2022", "", 0))
            head = "%s **%s**" % (icon, m.get("name", "?"))
            if m.get("numbers"):
                head += "  `%s`" % m["numbers"]
            blocks.append("\n".join(filter(None, [
                head,
                m.get("what", ""),
                "\u00b7 왜 %s" % m["why"] if m.get("why") else "",
                "\u00b7 %s" % m["age"] if m.get("age") else "",
            ])))
        embeds.append({
            "title": "\U0001F3AE 오늘 움직인 게임 \u2014 %s" % date,
            "description": clip("\n\n".join(blocks), MAX_DESC),
            "color": 0xE8710A,
        })

    if brief.get("reading"):
        embeds.append({
            "title": "\U0001F50E 읽히는 흐름",
            "description": clip(brief["reading"], MAX_DESC),
            "color": 0x34A853,
        })

    for idea in (brief.get("ideas") or [])[:3]:
        icon, label, color = TRACKS.get(idea.get("track", ""), ("\U0001F4A1", "아이디어", 0x9334E6))
        body = "\n\n".join(filter(None, [
            "_%s_" % idea["one_liner"] if idea.get("one_liner") else "",
            "**어느 신호에서** %s" % idea["from"] if idea.get("from") else "",
            "**핵심 루프** %s" % idea["loop"] if idea.get("loop") else "",
            "**규모** %s" % idea["scope"] if idea.get("scope") else "",
            "**왜 지금** %s" % idea["why_now"] if idea.get("why_now") else "",
            "**걸림돌** %s" % idea["risk"] if idea.get("risk") else "",
        ]))
        embeds.append({
            "title": clip("%s %s \u00b7 %s" % (icon, label, idea.get("title", "?")), 240),
            "description": clip(body, MAX_DESC),
            "color": color,
        })

    if not brief.get("ideas"):
        embeds.append({
            "title": "\U0001F4A1 오늘은 제안 없음",
            "description": "신호에서 밀어붙일 만한 게 나오지 않았습니다.",
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

    date = brief.get("date", "") or datetime.now(KST).strftime("%Y-%m-%d")
    embeds = build_embeds(brief, date)
    print("[brief] moved=%d ideas=%d -> %d embeds"
          % (len(brief.get("moved") or []), len(brief.get("ideas") or []), len(embeds)),
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

    header = "\U0001F3AE **오늘의 게임 브리프** — 뭐가 떴나 · 왜 떴나 · 뭘 만들까"

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
