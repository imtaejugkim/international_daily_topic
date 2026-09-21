#!/usr/bin/env python3
"""Fetch Google Trends daily trending searches for several countries and post
them to a Discord channel via webhook.

Standard library only.

Environment variables:
  DISCORD_WEBHOOK_URL  Discord webhook URL (required unless DRY_RUN=1)
  DRY_RUN              "1" to print to stdout instead of sending
  TREND_GEOS           optional comma separated geo codes, overrides defaults
  TOP_N                how many keywords per country (default 10)
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import korean

RSS_URL = "https://trends.google.com/trending/rss?geo={geo}"

# geo code, flag, display name
COUNTRIES = [
    ("KR", "\U0001F1F0\U0001F1F7", "South Korea"),
    ("US", "\U0001F1FA\U0001F1F8", "United States"),
    ("JP", "\U0001F1EF\U0001F1F5", "Japan"),
    ("GB", "\U0001F1EC\U0001F1E7", "United Kingdom"),
    ("DE", "\U0001F1E9\U0001F1EA", "Germany"),
    ("BR", "\U0001F1E7\U0001F1F7", "Brazil"),
]

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

KST = timezone(timedelta(hours=9))

# Discord hard limits: embed title 256, description 4096, 10 embeds per
# message, 6000 chars total per message. chunk() packs embeds by measured
# size so the per-message total can never be reached.
MAX_TITLE = 240
MAX_DESC = 1900
EMBEDS_PER_MESSAGE = 3
MAX_MESSAGE_CHARS = 5500

EMBED_COLOR = 0x4285F4

# {keyword: korean}, filled in once per run by main().
KOREAN = {}


def localname(tag):
    """Return an XML tag without its namespace."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def find_text(parent, name):
    for child in parent:
        if localname(child.tag) == name:
            return (child.text or "").strip()
    return ""


def fetch(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - report and retry
            last = exc
            if i < attempts - 1:
                time.sleep(2 ** i)
    raise last


def parse_feed(raw, top_n):
    """Parse a Google Trends RSS feed into a list of trend dicts."""
    root = ET.fromstring(raw)
    items = [el for el in root.iter() if localname(el.tag) == "item"]

    trends = []
    for item in items[:top_n]:
        title = find_text(item, "title")
        if not title:
            continue
        news = None
        for child in item:
            if localname(child.tag) == "news_item":
                news = {
                    "title": find_text(child, "news_item_title"),
                    "url": find_text(child, "news_item_url"),
                    "source": find_text(child, "news_item_source"),
                }
                break
        trends.append(
            {
                "title": title,
                "traffic": find_text(item, "approx_traffic"),
                "link": find_text(item, "link"),
                "news": news,
            }
        )
    return trends


def collect(countries, top_n):
    results = []
    for geo, flag, name in countries:
        try:
            raw = fetch(RSS_URL.format(geo=geo))
            trends = parse_feed(raw, top_n)
            results.append({"geo": geo, "flag": flag, "name": name, "trends": trends})
            print("[ok] %s %-14s %d keywords" % (geo, name, len(trends)), file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - one country must not kill the run
            results.append({"geo": geo, "flag": flag, "name": name, "trends": [], "error": str(exc)})
            print("[fail] %s %-14s %s" % (geo, name, exc), file=sys.stderr)
        time.sleep(0.5)
    return results


def clip(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_description(country):
    if country.get("error"):
        return clip("⚠️ fetch failed: %s" % country["error"], MAX_DESC)
    if not country["trends"]:
        return "_no data_"

    lines = []
    for i, t in enumerate(country["trends"], 1):
        line = "`%2d.` **%s**" % (i, clip(korean.label(t["title"], KOREAN), 80))
        if t["traffic"]:
            line += " · %s" % t["traffic"]
        news = t.get("news") or {}
        if news.get("url") and news.get("title"):
            line += " [\U0001F4F0](%s)" % news["url"]
        lines.append(line)

    out = ""
    for line in lines:
        candidate = (out + "\n" + line) if out else line
        if len(candidate) > MAX_DESC:
            break
        out = candidate
    return out or clip(lines[0], MAX_DESC)


def build_embeds(results):
    return [
        {
            "title": clip("%s %s — Daily Trends" % (c["flag"], c["name"]), MAX_TITLE),
            "description": build_description(c),
            "color": EMBED_COLOR,
            "url": "https://trends.google.com/trending?geo=%s" % c["geo"],
        }
        for c in results
    ]


def post(webhook, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if exc.code == 429:
            try:
                wait = float(json.loads(body).get("retry_after", 2))
            except Exception:  # noqa: BLE001
                wait = 2.0
            time.sleep(min(wait + 0.5, 30))
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status
        raise RuntimeError("Discord %s: %s" % (exc.code, body)) from exc


def embed_len(embed):
    return len(embed["title"]) + len(embed["description"])


def chunk(embeds):
    """Group embeds into messages that fit Discord's per-message limits."""
    out, current, size = [], [], 0
    for embed in embeds:
        grows_too_big = current and (
            len(current) >= EMBEDS_PER_MESSAGE
            or size + embed_len(embed) > MAX_MESSAGE_CHARS
        )
        if grows_too_big:
            out.append(current)
            current, size = [], 0
        current.append(embed)
        size += embed_len(embed)
    if current:
        out.append(current)
    return out


def send(webhook, results, header):
    for i, group in enumerate(chunk(build_embeds(results))):
        payload = {"embeds": group}
        if i == 0:
            payload["content"] = header
        status = post(webhook, payload)
        print("[discord] sent %d embeds (HTTP %s)" % (len(group), status), file=sys.stderr)
        time.sleep(1)


def dump(results, header):
    print(header)
    for c in results:
        print("\n%s %s (%s)" % (c["flag"], c["name"], c["geo"]))
        print(build_description(c))


def save(results, date):
    path = os.path.join("data", "trends", "%s.json" % date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "date": date,
        "trends": {
            c["geo"]: [
                {"title": t["title"], "traffic": t["traffic"],
                 "news": (t.get("news") or {}).get("title", "")}
                for t in c["trends"]
            ]
            for c in results
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("[saved] %s" % path, file=sys.stderr)


def main():
    top_n = int(os.environ.get("TOP_N", "10"))
    geos = os.environ.get("TREND_GEOS", "").strip()
    if geos:
        wanted = [g.strip().upper() for g in geos.split(",") if g.strip()]
        known = {c[0]: c for c in COUNTRIES}
        countries = [known.get(g, (g, "\U0001F3F3️", g)) for g in wanted]
    else:
        countries = COUNTRIES

    results = collect(countries, top_n)

    global KOREAN
    KOREAN = korean.annotate([t["title"] for c in results for t in c["trends"]])

    if os.environ.get("DRY_RUN") != "1":
        save(results, datetime.now(KST).strftime("%Y-%m-%d"))

    header = "\U0001F310 **World Trending Keywords** — %s KST" % datetime.now(KST).strftime(
        "%Y-%m-%d %H:%M"
    )

    ok = sum(1 for c in results if c["trends"])
    if os.environ.get("DRY_RUN") == "1":
        dump(results, header)
        print("\n[dry-run] %d/%d countries parsed" % (ok, len(results)), file=sys.stderr)
        return 0 if ok else 1

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("DISCORD_WEBHOOK_URL is not set (use DRY_RUN=1 to test)", file=sys.stderr)
        return 2

    if not ok:
        print("no country returned data; not sending", file=sys.stderr)
        return 1

    # Once the brief is running it is the thing worth reading; the raw dump
    # stays available behind SEND_RAW=1 and in data/.
    if os.environ.get("SEND_RAW", "1") != "1":
        print("[skip] SEND_RAW is off - collected and saved only", file=sys.stderr)
        return 0

    send(webhook, results, header)
    print("[done] %d/%d countries" % (ok, len(results)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
