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

from trends_to_discord import KST, MAX_DESC, chunk, clip, post

FLAGS = {"KR": "\U0001F1F0\U0001F1F7", "US": "\U0001F1FA\U0001F1F8", "JP": "\U0001F1EF\U0001F1F5",
         "GB": "\U0001F1EC\U0001F1E7", "DE": "\U0001F1E9\U0001F1EA", "BR": "\U0001F1E7\U0001F1F7"}

TRACKS = {
    "ride":    ("\U0001F30A", "트렌드 올라타기", 0x1A73E8),
    "improve": ("\U0001F527", "기존 서비스 개선", 0xF9AB00),
    "new":     ("\u2728", "아직 없는 것", 0x9334E6),
}


def flag(code):
    return FLAGS.get((code or "").upper(), "")


def build_embeds(brief, date):
    embeds = []

    now = brief.get("now") or []
    if now:
        blocks = []
        for t in now[:6]:
            codes = t.get("countries") or ([t["country"]] if t.get("country") else [])
            head = "%s **%s**" % (" ".join(flag(c) for c in codes), t.get("trend", "?"))
            if t.get("duration"):
                head += "  `%s`" % t["duration"]
            blocks.append("\n".join(filter(None, [
                head,
                t.get("what", ""),
                "· 근거 %s" % t["evidence"] if t.get("evidence") else "",
                "· 누가 %s" % t["who"] if t.get("who") else "",
            ])))
        embeds.append({
            "title": "\U0001F4CD 지금 뜨고 있는 것 — %s" % date,
            "description": clip("\n\n".join(blocks), MAX_DESC),
            "color": 0x34A853,
        })

    coming = brief.get("coming") or []
    if coming:
        blocks = []
        for c in coming[:5]:
            flags = " ".join(flag(x) for x in (c.get("countries") or []))
            blocks.append("**%s** %s — %s\n· 수요 %s" % (
                c.get("when", "?"), flags, c.get("event", ""), c.get("demand", "")))
        embeds.append({
            "title": "\U0001F4C5 앞으로 오는 것",
            "description": clip("\n\n".join(blocks), MAX_DESC),
            "color": 0xEA8600,
        })

    for idea in (brief.get("ideas") or [])[:3]:
        icon, label, color = TRACKS.get(idea.get("track", ""), ("\U0001F4A1", "아이디어", 0x9334E6))
        body = "\n\n".join(filter(None, [
            "_%s_" % idea["one_liner"] if idea.get("one_liner") else "",
            "**어느 트렌드에서** %s" % idea["from"] if idea.get("from") else "",
            "**첫 사용자** %s" % idea["who"] if idea.get("who") else "",
            "**첫 버전** %s" % idea["shape"] if idea.get("shape") else "",
            "**수익 가설** %s" % idea["money"] if idea.get("money") else "",
            "**하루 검증** %s" % idea["test"] if idea.get("test") else "",
            "**걸림돌** %s" % idea["risk"] if idea.get("risk") else "",
        ]))
        embeds.append({
            "title": clip("%s %s · %s" % (icon, label, idea.get("title", "?")), 240),
            "description": clip(body, MAX_DESC),
            "color": color,
        })

    if not brief.get("ideas"):
        embeds.append({
            "title": "\U0001F4A1 오늘은 제안 없음",
            "description": "트렌드에서 밀어붙일 만한 게 나오지 않았습니다.",
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
    print("[brief] now=%d coming=%d ideas=%d -> %d embeds"
          % (len(brief.get("now") or []), len(brief.get("coming") or []),
             len(brief.get("ideas") or []), len(embeds)), file=sys.stderr)

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

    header = "\U0001F9E0 **오늘의 브리프** — 지금 뜨는 것 · 앞으로 올 것 · 만들 것"

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
