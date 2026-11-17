#!/usr/bin/env python3
"""Work out which genres are worth a look, and which games to look at.

The headline number is the success rate: of the games that recently shipped
carrying a tag, what share got noticed at all. A genre where forty recent
releases produced twelve noticed games is open. One where a hundred produced
three is a mill - it looks busy for the same reason a mill looks busy, and
entering it costs six months to find that out.

The per-game lists are a shortlist, not an analysis. Someone reading this
goes and watches the game; the job here is to be right about which ones are
worth that time, so precision matters more than depth.

Standard library only.

Environment variables:
  SIGNAL_WINDOW   days of history to read (default 60)
  SURGE_PCT       day-over-day review growth that counts as a surge (default 25)
  MIN_REVIEWS     ignore games below this review count (default 20)
  DRY_RUN         "1" to print instead of writing
"""

import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import steam_tags

DATA = "data"
KST = timezone(timedelta(hours=9))

WINDOW = int(os.environ.get("SIGNAL_WINDOW", "60"))
SURGE_PCT = float(os.environ.get("SURGE_PCT", "25"))
# Percentages on tiny numbers are noise: 2 reviews becoming 6 is +200%.
MIN_REVIEWS = int(os.environ.get("MIN_REVIEWS", "20"))
ALIVE = steam_tags.ALIVE_REVIEWS
NOTICED = steam_tags.NOTICED_REVIEWS
GIANT_REVIEWS = 50000


def load_snapshots():
    out = []
    for path in sorted(glob.glob(os.path.join(DATA, "steam", "*.json")))[-WINDOW:]:
        try:
            with open(path, encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError) as exc:
            print("[skip] %s: %s" % (path, exc), file=sys.stderr)
    return out


def load_games():
    path = os.path.join(DATA, "games.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


def days_since_release(game):
    raw = (game or {}).get("release_date") or ""
    for fmt in ("%Y년 %m월 %d일", "%d %b, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(raw.strip(), fmt).date()
            return (datetime.now(KST).date() - d).days
        except ValueError:
            continue
    return None


def tag_health(today, reviews, games):
    """Per tag: how many recent releases cleared each bar.

    Deliberately not the store's own total for the tag - players apply tags,
    so that count carries spam and dead builds. Only releases we measured
    count, and only the ones with reviews count as having competed.
    """
    out = []
    for name, appids in (today.get("tag_releases") or {}).items():
        measured = [a for a in appids if a in reviews]
        if not measured:
            continue
        alive = [a for a in measured if reviews[a]["total"] >= ALIVE]
        noticed = [a for a in measured if reviews[a]["total"] >= NOTICED]
        prices = [games[a]["price_krw"] for a in noticed
                  if games.get(a, {}).get("price_krw")]
        free = sum(1 for a in noticed if games.get(a, {}).get("is_free"))
        out.append({
            "tag": name,
            "store_total": (today.get("tag_totals") or {}).get(name),
            "recent_measured": len(measured),
            "alive": len(alive),
            "noticed": len(noticed),
            "noticed_rate": round(100.0 * len(noticed) / len(measured), 1),
            "alive_rate": round(100.0 * len(alive) / len(measured), 1),
            "median_price_krw": sorted(prices)[len(prices) // 2] if prices else None,
            "free_share": round(100.0 * free / len(noticed), 1) if noticed else None,
            "top": sorted(
                ({"name": games.get(a, {}).get("name", a),
                  "reviews": reviews[a]["total"],
                  "score": reviews[a]["score"]} for a in noticed),
                key=lambda x: -x["reviews"])[:5],
        })
    return sorted(out, key=lambda t: -t["noticed_rate"])


def game_moves(snapshots, games):
    today = snapshots[-1]
    prev = snapshots[-2] if len(snapshots) > 1 else None
    now_r = today.get("reviews") or {}
    prev_r = (prev or {}).get("reviews") or {}
    players = today.get("players") or {}
    new_ids = set(today.get("new_release_ids") or [])
    up_ids = set(today.get("upcoming_ids") or [])

    rows = []
    for appid, r in now_r.items():
        total = r["total"]
        if total < MIN_REVIEWS:
            continue
        was = (prev_r.get(appid) or {}).get("total")
        gained = (total - was) if was is not None else None
        pct = (gained / was * 100) if was else None
        g = games.get(appid, {})
        rows.append({
            "appid": appid,
            "name": g.get("name", appid),
            "genres": g.get("genres", []),
            "price": g.get("price", ""),
            "is_free": g.get("is_free", False),
            "days_since_release": days_since_release(g),
            "reviews": total,
            "reviews_gained": gained,
            "pct_change": round(pct, 1) if pct is not None else None,
            "score": r["score"],
            "positive_rate": round(100.0 * r["positive"] / total, 1) if total else None,
            "players": players.get(appid),
            "is_new_release": appid in new_ids,
            "store_url": "https://store.steampowered.com/app/%s/" % appid,
        })

    def surged(x):
        return x["pct_change"] is not None and x["pct_change"] >= SURGE_PCT

    return {
        # Selling fast right now, in review terms.
        "surging": sorted([x for x in rows if surged(x)],
                          key=lambda x: -(x["reviews_gained"] or 0))[:12],
        # Shipped recently and already noticed: the comparable cases.
        "young_and_noticed": sorted(
            [x for x in rows if (x["days_since_release"] or 9999) <= 60
             and x["reviews"] >= NOTICED],
            key=lambda x: -x["reviews"])[:12],
        # Settled, and listed only so they can be skipped.
        "settled_giants": sorted(
            [{"name": x["name"], "reviews": x["reviews"], "pct_change": x["pct_change"]}
             for x in rows if x["reviews"] >= GIANT_REVIEWS and not surged(x)],
            key=lambda x: -x["reviews"])[:8],
        "upcoming_watch": [
            {"name": games.get(a, {}).get("name", a),
             "release_date": games.get(a, {}).get("release_date", ""),
             "store_url": "https://store.steampowered.com/app/%s/" % a}
            for a in list(up_ids)[:12]],
        "counted": len(rows),
        "compared_against": prev["date"] if prev else None,
    }


def main():
    snaps = load_snapshots()
    if not snaps:
        print("no steam snapshots stored yet - nothing to compare against", file=sys.stderr)
        return 0
    games = load_games()
    today = snaps[-1]
    reviews = today.get("reviews") or {}

    out = {
        "date": today["date"],
        "window": "%s ~ %s" % (snaps[0]["date"], today["date"]),
        "days_of_history": len(snaps),
        "thresholds": {"alive_reviews": ALIVE, "noticed_reviews": NOTICED,
                       "surge_pct": SURGE_PCT, "min_reviews": MIN_REVIEWS},
        "note": ("noticed_rate 는 그 태그로 최근 출시된 게임 중 리뷰 %d개를 넘긴 비율이다. "
                 "낮을수록 들어가기 어려운 시장이다. store_total 은 유저가 단 태그라 "
                 "스팸이 섞여 있으니 분모로 쓰지 마라." % NOTICED),
        "tag_health": tag_health(today, reviews, games),
    }
    out.update(game_moves(snaps, games))

    if os.environ.get("DRY_RUN") == "1":
        print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])
        return 0

    path = os.path.join(DATA, "signals", "%s.json" % out["date"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("[saved] %s  태그 %d / 급등 %d / 신작주목 %d"
          % (path, len(out["tag_health"]), len(out["surging"]),
             len(out["young_and_noticed"])), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
