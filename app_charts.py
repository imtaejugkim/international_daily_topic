#!/usr/bin/env python3
"""Collect per-country App Store top charts and low-star reviews, store a
daily snapshot under data/, derive day-over-day and cross-country signals,
and post a digest to Discord.

Apps are matched across countries by App Store id and categories by genreId -
the names come back localized, so matching on them compares languages rather
than markets.

Standard library only (the optional Korean annotation is isolated in
korean.py and degrades to a no-op).

Environment variables:
  DISCORD_WEBHOOK_URL  Discord webhook (required unless DRY_RUN=1)
  DRY_RUN              "1" to print instead of sending, and skip writing data
  CHART_GEOS           comma separated storefronts, overrides the defaults
  CHART_SIZE           apps per country chart (default 25)
  REVIEW_APPS          apps per country to pull reviews for (default 10)
"""

import glob
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import korean
from trends_to_discord import MAX_DESC, USER_AGENT, chunk, clip, post

CHART_URL = "https://rss.marketingtools.apple.com/api/v2/{cc}/apps/top-free/{n}/apps.json"
REVIEW_URL = "https://itunes.apple.com/{cc}/rss/customerreviews/page=1/id={app_id}/sortby=mostrecent/json"

COUNTRIES = [
    ("kr", "\U0001F1F0\U0001F1F7", "South Korea"),
    ("us", "\U0001F1FA\U0001F1F8", "United States"),
    ("jp", "\U0001F1EF\U0001F1F5", "Japan"),
    ("gb", "\U0001F1EC\U0001F1E7", "United Kingdom"),
    ("de", "\U0001F1E9\U0001F1EA", "Germany"),
    ("br", "\U0001F1E7\U0001F1F7", "Brazil"),
]

KST = timezone(timedelta(hours=9))
DATA = "data"
EMBED_COLOR = 0x34A853

# A chart position this much better than yesterday is worth calling out.
RISE_THRESHOLD = 5
# An app in this many of our countries is a global wave, not a local hit.
GLOBAL_MIN_COUNTRIES = 4
# Apple throttles rapid repeat calls (504s and read timeouts), so pace them.
REQUEST_GAP = 1.2


def fetch(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - report and retry
            last = exc
            if i < attempts - 1:
                time.sleep(2 * (i + 1))
    raise last


def parse_chart(data, size):
    apps = []
    for rank, app in enumerate(data["feed"]["results"][:size], 1):
        genres = app.get("genres") or []
        apps.append(
            {
                "rank": rank,
                "id": app.get("id", ""),
                "name": app.get("name", ""),
                "artist": app.get("artistName", ""),
                "genre_ids": [g.get("genreId", "") for g in genres if g.get("genreId")],
                "genres": [g.get("name", "") for g in genres if g.get("name")],
            }
        )
    return apps


def parse_reviews(data):
    entries = (data.get("feed") or {}).get("entry") or []
    if isinstance(entries, dict):
        entries = [entries]
    reviews = []
    for e in entries:
        if "im:rating" not in e:
            continue  # the feed's first entry is the app itself, not a review
        try:
            rating = int(e["im:rating"]["label"])
        except (KeyError, ValueError):
            continue
        reviews.append(
            {
                "rating": rating,
                "title": (e.get("title") or {}).get("label", ""),
                "content": (e.get("content") or {}).get("label", ""),
                "updated": (e.get("updated") or {}).get("label", ""),
            }
        )
    return reviews


def collect(countries, size, review_apps):
    charts, reviews = {}, {}
    for cc, _flag, name in countries:
        try:
            charts[cc] = parse_chart(fetch(CHART_URL.format(cc=cc, n=size)), size)
            print("[ok] %s %-15s %d apps" % (cc.upper(), name, len(charts[cc])), file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - one country must not kill the run
            print("[fail] %s %-15s %s" % (cc.upper(), name, exc), file=sys.stderr)
            continue
        time.sleep(REQUEST_GAP)

        low = {}
        for app in charts[cc][:review_apps]:
            try:
                got = parse_reviews(fetch(REVIEW_URL.format(cc=cc, app_id=app["id"])))
                bad = [r for r in got if r["rating"] <= 2]
                if bad:
                    low[app["id"]] = bad
            except Exception as exc:  # noqa: BLE001
                print("[fail] reviews %s %s: %s" % (cc, app["id"], exc), file=sys.stderr)
            time.sleep(REQUEST_GAP)
        reviews[cc] = low
        print("     %s reviews: %d apps with 1-2star, %d total"
              % (cc.upper(), len(low), sum(len(v) for v in low.values())), file=sys.stderr)
    return charts, reviews


def snapshot_path(kind, date):
    return os.path.join(DATA, kind, "%s.json" % date)


def save(kind, date, payload):
    path = snapshot_path(kind, date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("[saved] %s" % path, file=sys.stderr)


def load_previous(kind, date):
    """Most recent snapshot strictly before `date`, or None on the first run."""
    paths = sorted(glob.glob(os.path.join(DATA, kind, "*.json")))
    earlier = [p for p in paths if os.path.basename(p)[:-5] < date]
    if not earlier:
        return None
    with open(earlier[-1], encoding="utf-8") as f:
        return json.load(f)


def signals(charts, previous, review_apps):
    """Day-over-day movement plus the cross-country view."""
    prev_charts = (previous or {}).get("charts", {})
    per_country = {}
    for cc, apps in charts.items():
        before = {a["id"]: a["rank"] for a in prev_charts.get(cc, [])}
        new, risen = [], []
        for app in apps:
            was = before.get(app["id"])
            if before and was is None:
                new.append(app)
            elif was is not None and was - app["rank"] >= RISE_THRESHOLD:
                risen.append((app, was))
        per_country[cc] = {"new": new, "risen": risen, "had_previous": bool(before)}

    # Cross-country: the same App Store id in several storefronts is one app.
    seen = {}
    for cc, apps in charts.items():
        for app in apps:
            entry = seen.setdefault(app["id"], {"name": app["name"], "countries": []})
            entry["countries"].append(cc)

    universal = sorted(
        (e for e in seen.values() if len(e["countries"]) >= GLOBAL_MIN_COUNTRIES),
        key=lambda e: -len(e["countries"]),
    )
    # High in one country and absent everywhere else: the gap worth a look.
    solo = []
    for cc, apps in charts.items():
        for app in apps[:review_apps]:
            if len(seen[app["id"]]["countries"]) == 1:
                solo.append((cc, app))
    return {"per_country": per_country, "universal": universal, "solo": solo}


def chart_description(cc, apps, sig, ko):
    marks = {a["id"]: "\U0001F195" for a in sig["per_country"].get(cc, {}).get("new", [])}
    for app, was in sig["per_country"].get(cc, {}).get("risen", []):
        marks[app["id"]] = "\U0001F4C8%d" % (was - app["rank"])

    lines = []
    for app in apps[:15]:
        mark = marks.get(app["id"], "")
        name = clip(korean.label(app["name"], ko), 52)
        lines.append("`%2d.` **%s**%s" % (app["rank"], name, " " + mark if mark else ""))

    out = ""
    for line in lines:
        candidate = (out + "\n" + line) if out else line
        if len(candidate) > MAX_DESC:
            break
        out = candidate
    return out or "_no data_"


def signal_description(sig, reviews, ko):
    parts = []

    if sig["universal"]:
        rows = ["\U0001F30D **여러 나라 동시 상위** (%d개국 이상)" % GLOBAL_MIN_COUNTRIES]
        for e in sig["universal"][:6]:
            rows.append("· %s — %s" % (
                clip(korean.label(e["name"], ko), 40),
                "".join(c.upper() + " " for c in e["countries"]).strip()))
        parts.append("\n".join(rows))

    if sig["solo"]:
        rows = ["\U0001F3AF **한 나라에만 있는 상위 앱** (격차 후보)"]
        for cc, app in sig["solo"][:8]:
            rows.append("· `%s` %s" % (cc.upper(), clip(korean.label(app["name"], ko), 40)))
        parts.append("\n".join(rows))

    total_reviews = sum(len(v) for c in reviews.values() for v in c.values())
    if total_reviews:
        parts.append("\U0001F4DD 저평점 리뷰 **%d건** 수집·저장 (분석은 LLM 연결 후)" % total_reviews)

    fresh = [cc for cc, d in sig["per_country"].items() if not d["had_previous"]]
    if fresh:
        parts.append("_첫 수집이라 신규/급상승 비교 대상이 없습니다 (내일부터 표시)_")

    return clip("\n\n".join(parts) or "_no signals_", MAX_DESC)


def build_embeds(countries, charts, sig, reviews, ko):
    embeds = []
    for cc, flag, name in countries:
        if cc not in charts:
            continue
        embeds.append({
            "title": "%s %s — App Store Top Free" % (flag, name),
            "description": chart_description(cc, charts[cc], sig, ko),
            "color": EMBED_COLOR,
        })
    embeds.append({
        "title": "\U0001F50E 신호 요약",
        "description": signal_description(sig, reviews, ko),
        "color": 0xEA4335,
    })
    return embeds


def main():
    size = int(os.environ.get("CHART_SIZE", "25"))
    review_apps = int(os.environ.get("REVIEW_APPS", "10"))
    geos = os.environ.get("CHART_GEOS", "").strip()
    if geos:
        known = {c[0]: c for c in COUNTRIES}
        wanted = [g.strip().lower() for g in geos.split(",") if g.strip()]
        countries = [known.get(g, (g, "\U0001F3F3️", g.upper())) for g in wanted]
    else:
        countries = COUNTRIES

    now = datetime.now(KST)
    date = now.strftime("%Y-%m-%d")
    dry = os.environ.get("DRY_RUN") == "1"

    charts, reviews = collect(countries, size, review_apps)
    if not charts:
        print("no country returned a chart", file=sys.stderr)
        return 1

    previous = load_previous("charts", date)
    sig = signals(charts, previous, review_apps)

    ko = korean.annotate([a["name"] for apps in charts.values() for a in apps])

    if not dry:
        save("charts", date, {"date": date, "charts": charts})
        save("reviews", date, {"date": date, "reviews": reviews})

    header = "\U0001F4F1 **국가별 앱 차트** — %s KST" % now.strftime("%Y-%m-%d %H:%M")
    embeds = build_embeds(countries, charts, sig, reviews, ko)

    if dry:
        print(header)
        for e in embeds:
            print("\n=== %s ===" % e["title"])
            print(e["description"])
        print("\n[dry-run] %d/%d countries" % (len(charts), len(countries)), file=sys.stderr)
        return 0

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("DISCORD_WEBHOOK_URL is not set (use DRY_RUN=1 to test)", file=sys.stderr)
        return 2

    if os.environ.get("SEND_RAW", "1") != "1":
        print("[skip] SEND_RAW is off - collected and saved only", file=sys.stderr)
        return 0

    for i, group in enumerate(chunk(embeds)):
        payload = {"embeds": group}
        if i == 0:
            payload["content"] = header
        status = post(webhook, payload)
        print("[discord] sent %d embeds (HTTP %s)" % (len(group), status), file=sys.stderr)
        time.sleep(1)
    print("[done] %d/%d countries" % (len(charts), len(countries)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
