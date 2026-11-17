#!/usr/bin/env python3
"""Take today's Steam snapshot.

Three things get recorded, because together they answer "is this genre worth
a look" rather than "what is popular".

Review counts, per game. Steam publishes no sales figures, and concurrent
players measure attention right now rather than money - a paid game with
2,000 players may have sold far better than a free one with 200,000. Review
totals move with copies sold, so measuring them daily gives the closest
public read on whether a game is actually selling.

Player counts, per game. Cheap, exact, and the only same-day signal.

Per tag, the recent releases and how many reviews each got. This is the
denominator: how many games in a genre shipped, and how many were noticed at
all. Without it a genre that looks busy cannot be told from a genre that
eats everyone who enters.

Standard library only. No API key.

Environment variables:
  WATCH_LIMIT     games to poll for player counts (default 200)
  TAG_DEPTH       recent releases to check per tag (default 50)
  DETAIL_BUDGET   new games to describe per run (default 60)
  DRY_RUN         "1" to print instead of writing
"""

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import steam_tags

UA = steam_tags.UA
APPID_IN_URL = steam_tags.APPID_IN_URL

MOST_PLAYED = "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/"
PLAYERS = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=%s"
REVIEWS = ("https://store.steampowered.com/appreviews/%s"
           "?json=1&language=all&purchase_type=all&num_per_page=0")
FEATURED = "https://store.steampowered.com/api/featuredcategories?cc=kr&l=koreana"
DETAILS = "https://store.steampowered.com/api/appdetails?appids=%s&l=koreana&cc=kr"
NEW_RELEASES = ("https://store.steampowered.com/search/results/"
                "?query&category1=998&sort_by=Released_DESC&cc=kr&l=koreana"
                "&infinite=1&count=100")
UPCOMING = ("https://store.steampowered.com/search/results/"
            "?query&category1=998&filter=popularcomingsoon&cc=kr&l=koreana"
            "&infinite=1&count=50")

DATA = "data"
KST = timezone(timedelta(hours=9))
GAP = 0.22
DETAIL_GAP = 0.6

get = steam_tags.get


def most_played():
    ranks = (get(MOST_PLAYED).get("response") or {}).get("ranks") or []
    return [{"appid": str(r["appid"]), "rank": r.get("rank"),
             "last_week_rank": r.get("last_week_rank"),
             "peak_in_game": r.get("peak_in_game")} for r in ranks if r.get("appid")]


def search_appids(url, label):
    d = get(url)
    ids, seen = [], set()
    for appid in APPID_IN_URL.findall(d.get("results_html") or ""):
        if appid not in seen:
            seen.add(appid)
            ids.append(appid)
    print("[%s] %d appids (store reports %s total)"
          % (label, len(ids), d.get("total_count")), file=sys.stderr)
    return ids, d.get("total_count")


def featured_sections():
    data = get(FEATURED)
    out = {}
    for section in ("new_releases", "coming_soon", "top_sellers", "specials"):
        items = (data.get(section) or {}).get("items") or []
        out[section] = [{"appid": str(i["id"]), "name": i.get("name", "")}
                        for i in items if i.get("id")]
    return out


def review_summary(appid):
    q = (get(REVIEWS % appid, attempts=2, timeout=15) or {}).get("query_summary") or {}
    if "total_reviews" not in q:
        return None
    return {"total": q.get("total_reviews", 0),
            "positive": q.get("total_positive", 0),
            "negative": q.get("total_negative", 0),
            "score": q.get("review_score_desc", "")}


def sweep(appids, fn, label):
    out, failed = {}, 0
    for i, appid in enumerate(appids, 1):
        try:
            v = fn(appid)
            if v is not None:
                out[appid] = v
        except Exception:  # noqa: BLE001 - one game must not stop the sweep
            failed += 1
        if i % 100 == 0:
            print("  %s ...%d/%d" % (label, i, len(appids)), file=sys.stderr)
        time.sleep(GAP)
    print("[%s] %d collected, %d failed" % (label, len(out), failed), file=sys.stderr)
    return out


def player_count(appid):
    r = get(PLAYERS % appid, attempts=2, timeout=12).get("response") or {}
    return r.get("player_count") if r.get("result") == 1 else None


def load_known():
    path = os.path.join(DATA, "games.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


def fetch_details(appid):
    body = (get(DETAILS % appid, attempts=2).get(str(appid)) or {}).get("data") or {}
    if not body:
        return None
    price = body.get("price_overview") or {}
    return {
        "name": body.get("name", ""),
        "genres": [g.get("description") for g in body.get("genres") or []],
        "release_date": (body.get("release_date") or {}).get("date", ""),
        "coming_soon": bool((body.get("release_date") or {}).get("coming_soon")),
        "is_free": bool(body.get("is_free")),
        "price_krw": price.get("final"),
        "price": price.get("final_formatted", ""),
        "developers": body.get("developers") or [],
        "fetched": datetime.now(KST).strftime("%Y-%m-%d"),
    }


def enrich(known, appids, budget, reviews=None, featured_ids=()):
    """Describe games we have not seen. Budget goes to the ones a reader
    would actually ask about: featured first, then by review count."""
    reviews = reviews or {}
    missing = [a for a in appids if a not in known]
    missing.sort(key=lambda a: (a not in featured_ids,
                                -(reviews.get(a, {}).get("total", 0))))
    for appid in missing[:budget]:
        try:
            d = fetch_details(appid)
            if d:
                known[appid] = d
        except Exception as exc:  # noqa: BLE001
            print("[detail] %s failed: %s" % (appid, exc), file=sys.stderr)
        time.sleep(DETAIL_GAP)
    print("[details] +%d described (%d still unnamed)"
          % (min(budget, len(missing)), max(0, len(missing) - budget)), file=sys.stderr)
    return known


def main():
    limit = int(os.environ.get("WATCH_LIMIT", "200"))
    depth = int(os.environ.get("TAG_DEPTH", "50"))
    dry = os.environ.get("DRY_RUN") == "1"
    date = datetime.now(KST).strftime("%Y-%m-%d")

    if dry:
        limit, depth = min(limit, 25), min(depth, 10)

    top = most_played()
    print("[charts] top %d" % len(top), file=sys.stderr)
    feat = featured_sections()
    new_ids, _ = search_appids(NEW_RELEASES, "new releases")
    up_ids, _ = search_appids(UPCOMING, "popular upcoming")

    tags = steam_tags.verify_tag_ids()
    tag_releases, tag_totals = {}, {}
    for name, tagid in (list(tags.items())[:3] if dry else tags.items()):
        try:
            total, ids = steam_tags.recent_releases(tagid, depth)
            tag_releases[name], tag_totals[name] = ids, total
            print("[tag] %-24s %4s total, %d recent" % (name, total, len(ids)), file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print("[tag] %s failed: %s" % (name, exc), file=sys.stderr)
        time.sleep(GAP)

    known = load_known()

    # Players: only what is plausibly live. Polling every tag release for a
    # player count would cost thousands of requests for mostly zeros.
    play_watch, seen = [], set()
    for appid in ([t["appid"] for t in top]
                  + [i["appid"] for v in feat.values() for i in v]
                  + new_ids + sorted(known)):
        if appid not in seen:
            seen.add(appid)
            play_watch.append(appid)
    play_watch = play_watch[:limit]

    # Reviews: everything, including every tag release. This is the set the
    # success rate is computed over, so the failures have to be in it.
    review_watch, seen = [], set()
    for appid in (play_watch + new_ids + up_ids
                  + [a for ids in tag_releases.values() for a in ids]):
        if appid not in seen:
            seen.add(appid)
            review_watch.append(appid)

    print("[watch] players %d, reviews %d" % (len(play_watch), len(review_watch)),
          file=sys.stderr)
    players = sweep(play_watch, player_count, "players")
    reviews = sweep(review_watch, review_summary, "reviews")

    featured_ids = {i["appid"] for v in feat.values() for i in v}
    known = enrich(known, review_watch,
                   budget=int(os.environ.get("DETAIL_BUDGET", "60")) if not dry else 10,
                   reviews=reviews, featured_ids=featured_ids)

    payload = {
        "date": date,
        "collected_at": datetime.now(KST).isoformat(timespec="seconds"),
        "top_played": top,
        "featured": feat,
        "new_release_ids": new_ids,
        "upcoming_ids": up_ids,
        "tag_releases": tag_releases,
        "tag_totals": tag_totals,
        "players": players,
        "reviews": reviews,
    }

    if dry:
        print("\n=== %s ===" % date)
        for appid, r in sorted(reviews.items(), key=lambda kv: -kv[1]["total"])[:12]:
            g = known.get(appid, {})
            print("  리뷰 %-7s %-9s %-40s %s" % (
                "{:,}".format(r["total"]), r["score"][:9],
                (g.get("name") or appid)[:40], g.get("price", "무료" if g.get("is_free") else "")))
        print("\n[dry-run] players=%d reviews=%d tags=%d"
              % (len(players), len(reviews), len(tag_releases)), file=sys.stderr)
        return 0

    os.makedirs(os.path.join(DATA, "steam"), exist_ok=True)
    with open(os.path.join(DATA, "steam", "%s.json" % date), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(os.path.join(DATA, "games.json"), "w", encoding="utf-8") as f:
        json.dump(known, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("[saved] data/steam/%s.json" % date, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
