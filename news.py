#!/usr/bin/env python3
"""Collect Google News headlines per country and store a daily snapshot.

Google News RSS returns a headline, its source and a link - not article
bodies. That is what we want: the signal we are after is which subjects a
country's press keeps returning to, not any single article's detail, and
hundreds of headlines make that pattern far clearer than a handful of full
texts would.

Standard library only.

Environment variables:
  NEWS_GEOS     comma separated country codes, overrides the defaults
  NEWS_PER_FEED headlines to keep per feed (default 40)
  DRY_RUN       "1" to print instead of writing the snapshot
"""

import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from trends_to_discord import USER_AGENT, find_text, localname

# Google News exposes a top-stories feed plus per-topic sections. Business and
# technology carry most of what is useful for reading a market; the top feed
# keeps the wider context that would otherwise be invisible.
FEEDS = {
    "top": "https://news.google.com/rss?{q}",
    "business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?{q}",
    "technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?{q}",
}

# code, flag, name, Google News locale query
COUNTRIES = [
    ("KR", "\U0001F1F0\U0001F1F7", "South Korea", "hl=ko&gl=KR&ceid=KR:ko"),
    ("US", "\U0001F1FA\U0001F1F8", "United States", "hl=en-US&gl=US&ceid=US:en"),
    ("JP", "\U0001F1EF\U0001F1F5", "Japan", "hl=ja&gl=JP&ceid=JP:ja"),
    ("GB", "\U0001F1EC\U0001F1E7", "United Kingdom", "hl=en-GB&gl=GB&ceid=GB:en"),
    ("DE", "\U0001F1E9\U0001F1EA", "Germany", "hl=de&gl=DE&ceid=DE:de"),
    ("BR", "\U0001F1E7\U0001F1F7", "Brazil", "hl=pt-BR&gl=BR&ceid=BR:pt-419"),
]

DATA = "data"
# Google News appends the outlet to the headline: "Some headline - Outlet".
TRAILING_SOURCE = re.compile(r"\s+-\s+[^-]{2,40}$")


def fetch(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - report and retry
            last = exc
            if i < attempts - 1:
                time.sleep(2 * (i + 1))
    raise last


def parse(raw, limit):
    root = ET.fromstring(raw)
    out = []
    for item in [el for el in root.iter() if localname(el.tag) == "item"][:limit]:
        title = find_text(item, "title")
        if not title:
            continue
        source = find_text(item, "source")
        headline = TRAILING_SOURCE.sub("", title) if source else title
        out.append({
            "title": headline.strip(),
            "source": source,
            "published": find_text(item, "pubDate"),
        })
    return out


def collect(countries, per_feed):
    news = {}
    for code, _flag, name, query in countries:
        bucket = {}
        for section, template in FEEDS.items():
            try:
                items = parse(fetch(template.format(q=query)), per_feed)
                bucket[section] = items
                print("[ok] %s %-14s %-11s %d headlines"
                      % (code, name, section, len(items)), file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 - one feed must not kill the run
                print("[fail] %s %-14s %-11s %s" % (code, name, section, exc), file=sys.stderr)
            time.sleep(0.6)
        if bucket:
            news[code] = bucket
    return news


def main():
    per_feed = int(os.environ.get("NEWS_PER_FEED", "40"))
    geos = os.environ.get("NEWS_GEOS", "").strip()
    if geos:
        known = {c[0]: c for c in COUNTRIES}
        countries = [known[g.strip().upper()] for g in geos.split(",")
                     if g.strip().upper() in known]
    else:
        countries = COUNTRIES

    news = collect(countries, per_feed)
    if not news:
        print("no country returned headlines", file=sys.stderr)
        return 1

    total = sum(len(v) for c in news.values() for v in c.values())
    date = datetime.now().strftime("%Y-%m-%d")

    if os.environ.get("DRY_RUN") == "1":
        for code, sections in news.items():
            print("\n=== %s ===" % code)
            for section, items in sections.items():
                print("  [%s]" % section)
                for it in items[:6]:
                    print("    · %s  (%s)" % (it["title"][:78], it["source"][:22]))
        print("\n[dry-run] %d headlines across %d countries" % (total, len(news)), file=sys.stderr)
        return 0

    path = os.path.join(DATA, "news", "%s.json" % date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": date, "news": news}, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("[saved] %s (%d headlines)" % (path, total), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
