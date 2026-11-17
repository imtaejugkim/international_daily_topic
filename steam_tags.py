#!/usr/bin/env python3
"""The tags this watches, and what the store says about each one.

Not all 429 Steam tags: a few thousand requests a morning would get refused,
and most tags are irrelevant anyway. These lean toward short-loop,
high-repetition designs - the "dopamine" shape - plus the adjacent genres a
small team can finish.

The number that matters per tag is not how many games carry it. Tags are
applied by players, so the raw count includes spam and abandoned builds. What
counts is how many recent releases cleared a review threshold: that ratio is
the odds of a game in this genre being noticed at all.
"""

import json
import os
import re
import sys
import time
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
APPID_IN_URL = re.compile(r"/apps/(\d+)/")

SEARCH = ("https://store.steampowered.com/search/results/"
          "?query&tags=%d&category1=998&sort_by=Released_DESC"
          "&cc=kr&l=koreana&infinite=1&count=%d")
TAGLIST = "https://store.steampowered.com/tagdata/populartags/english"

# tag name -> tagid. Confirmed against the live tag list.
TAGS = {
    "Roguelike Deckbuilder": 1091588,
    "Auto Battler": 1084988,
    "Deckbuilding": 32322,
    "Roguelite": 3959,
    "Idler": 615955,
    "Bullet Hell": 1666,
    "Tower Defense": 1645,
    "Survival": 1662,
    "Card Game": 1666665,
    "Turn-Based Tactics": 1708767,
    "Time Management": 4094,
    "Automation": 255534,
    "Incremental": 4700,
    "Dungeon Crawler": 1716,
    "Action Roguelike": 42804,
}

# A release nobody reviewed is not a release that competed.
ALIVE_REVIEWS = int(os.environ.get("ALIVE_REVIEWS", "10"))
# Clearing this is roughly where a game starts being visible on Steam at all.
NOTICED_REVIEWS = int(os.environ.get("NOTICED_REVIEWS", "50"))


def get(url, attempts=3, timeout=25):
    """Fetch and parse JSON.

    Timeouts are short by default and must stay short: store.steampowered.com
    throttles by stalling rather than refusing, so a generous timeout times
    hundreds of requests turns a few minutes of collection into an hour. A
    sweep over many games should pass attempts=1 and a small timeout and
    accept the misses.
    """
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i < attempts - 1:
                time.sleep(1.5 * (i + 1))
    raise last


def recent_releases(tagid, count):
    """Most recent releases carrying this tag, newest first."""
    d = get(SEARCH % (tagid, count))
    ids, seen = [], set()
    for appid in APPID_IN_URL.findall(d.get("results_html") or ""):
        if appid not in seen:
            seen.add(appid)
            ids.append(appid)
    return d.get("total_count"), ids


def verify_tag_ids():
    """Tag ids are stable but not guaranteed; check them against the store
    rather than trusting a hardcoded table silently."""
    try:
        live = {t["name"]: t["tagid"] for t in get(TAGLIST) if t.get("name")}
    except Exception as exc:  # noqa: BLE001
        print("[tags] could not verify ids: %s" % exc, file=sys.stderr)
        return TAGS
    ok, fixed, missing = {}, 0, []
    for name, tagid in TAGS.items():
        if name not in live:
            missing.append(name)
            continue
        ok[name] = live[name]
        if live[name] != tagid:
            fixed += 1
            print("[tags] %s: %d -> %d" % (name, tagid, live[name]), file=sys.stderr)
    if missing:
        print("[tags] no longer in the store's list: %s" % ", ".join(missing), file=sys.stderr)
    print("[tags] %d verified, %d corrected" % (len(ok), fixed), file=sys.stderr)
    return ok
