#!/usr/bin/env python3
"""Take today's Steam snapshot: who is being played, and how many.

The watchlist is the top 100 by concurrent players, plus whatever Steam is
featuring as new or upcoming, plus everything seen on earlier days. Featured
and new games matter more than the top of the chart here - a solo developer
learns nothing from Counter-Strike holding half a million players, and
everything from a small game going from two thousand to twenty.

For each game on the list we record the exact concurrent player count, which
is what makes day-over-day surge detection possible at all.

Standard library only. No API key: every endpoint used here is public.

Environment variables:
  WATCH_LIMIT   max games to poll for player counts (default 220)
  DRY_RUN       "1" to print instead of writing the snapshot
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

MOST_PLAYED = "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/"
PLAYERS = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=%s"
FEATURED = "https://store.steampowered.com/api/featuredcategories?cc=kr&l=koreana"
DETAILS = "https://store.steampowered.com/api/appdetails?appids=%s&l=koreana&cc=kr"

DATA = "data"
KST = timezone(timedelta(hours=9))
GAP = 0.25          # Steam tolerates this; the player-count endpoint is cheap
DETAIL_GAP = 0.6    # the store API is stricter


def get(url, attempts=3, timeout=20):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - report and retry
            last = exc
            if i < attempts - 1:
                time.sleep(1.5 * (i + 1))
    raise last


def most_played():
    ranks = (get(MOST_PLAYED).get("response") or {}).get("ranks") or []
    return [{"appid": str(r["appid"]), "rank": r.get("rank"),
             "last_week_rank": r.get("last_week_rank"),
             "peak_in_game": r.get("peak_in_game")} for r in ranks if r.get("appid")]


def featured():
    """New releases and upcoming games - where a small game can still appear."""
    data = get(FEATURED)
    out = {}
    for section in ("new_releases", "coming_soon", "top_sellers", "specials"):
        items = (data.get(section) or {}).get("items") or []
        out[section] = [{"appid": str(i["id"]), "name": i.get("name", ""),
                         "discount": i.get("discount_percent", 0),
                         "price": i.get("final_price")}
                        for i in items if i.get("id")]
    return out


def player_counts(appids):
    counts, failed = {}, 0
    for i, appid in enumerate(appids, 1):
        try:
            r = get(PLAYERS % appid, attempts=2, timeout=12).get("response") or {}
            if r.get("result") == 1 and "player_count" in r:
                counts[appid] = r["player_count"]
        except Exception:  # noqa: BLE001 - one game must not stop the sweep
            failed += 1
        if i % 50 == 0:
            print("  ...%d/%d" % (i, len(appids)), file=sys.stderr)
        time.sleep(GAP)
    print("[players] %d counted, %d failed" % (len(counts), failed), file=sys.stderr)
    return counts


def load_known():
    """Names, genres and release dates seen before, so each game is only
    looked up once rather than every morning."""
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
    return {
        "name": body.get("name", ""),
        "genres": [g.get("description") for g in body.get("genres") or []],
        "categories": [c.get("description") for c in (body.get("categories") or [])][:8],
        "release_date": (body.get("release_date") or {}).get("date", ""),
        "coming_soon": bool((body.get("release_date") or {}).get("coming_soon")),
        "is_free": bool(body.get("is_free")),
        "price": (body.get("price_overview") or {}).get("final_formatted", ""),
        "developers": body.get("developers") or [],
        "fetched": datetime.now(KST).strftime("%Y-%m-%d"),
    }


def enrich(known, appids, budget):
    """Look up only games we have never seen. The budget keeps a day where
    many new games appear from stretching the run out."""
    missing = [a for a in appids if a not in known][:budget]
    for i, appid in enumerate(missing, 1):
        try:
            d = fetch_details(appid)
            if d:
                known[appid] = d
        except Exception as exc:  # noqa: BLE001
            print("[detail] %s failed: %s" % (appid, exc), file=sys.stderr)
        time.sleep(DETAIL_GAP)
    print("[details] %d new games described (%d unknown remain)"
          % (len(missing), max(0, len([a for a in appids if a not in known]))), file=sys.stderr)
    return known


def main():
    limit = int(os.environ.get("WATCH_LIMIT", "220"))
    dry = os.environ.get("DRY_RUN") == "1"
    date = datetime.now(KST).strftime("%Y-%m-%d")

    top = most_played()
    print("[charts] top %d by players" % len(top), file=sys.stderr)
    feat = featured()
    for k, v in feat.items():
        print("[featured] %-13s %d" % (k, len(v)), file=sys.stderr)

    known = load_known()
    # Keep watching anything seen before, so a game that falls out of the top
    # 100 still has a number tomorrow and its decline is visible.
    watch, seen = [], set()
    for appid in ([t["appid"] for t in top]
                  + [i["appid"] for v in feat.values() for i in v]
                  + sorted(known)):
        if appid not in seen:
            seen.add(appid)
            watch.append(appid)
    watch = watch[:limit]
    print("[watch] %d games" % len(watch), file=sys.stderr)

    counts = player_counts(watch)
    if dry:
        # Only the games about to be printed, so the output is readable
        # without spending a full lookup budget.
        top_by_players = [a for a, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:15]]
        known = enrich(known, top_by_players, budget=15)
    else:
        known = enrich(known, watch, budget=40)

    payload = {
        "date": date,
        "collected_at": datetime.now(KST).isoformat(timespec="seconds"),
        "top_played": top,
        "featured": feat,
        "players": counts,
    }

    if dry:
        print("\n=== %s ===" % date)
        named = sorted(counts.items(), key=lambda kv: -kv[1])[:15]
        for appid, n in named:
            print("  %9s  %-44s" % ("{:,}".format(n), (known.get(appid, {}).get("name", appid))[:44]))
        print("\n[dry-run] %d games counted" % len(counts), file=sys.stderr)
        return 0

    os.makedirs(os.path.join(DATA, "steam"), exist_ok=True)
    with open(os.path.join(DATA, "steam", "%s.json" % date), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(os.path.join(DATA, "games.json"), "w", encoding="utf-8") as f:
        json.dump(known, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("[saved] data/steam/%s.json (%d games)" % (date, len(counts)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
