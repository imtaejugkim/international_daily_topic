#!/usr/bin/env python3
"""Find what moved, not what is big.

A chart of concurrent players says the same thing every day: Counter-Strike,
Dota, PUBG. Those games have settled audiences, so their absolute size is not
information - a developer deciding what to build learns nothing from it. What
carries information is change: a game that doubled overnight, one climbing for
a week straight, one that just appeared.

So every game is classified by how it moved rather than how large it is, and
the settled giants are put in their own bucket and labelled as carrying no
signal, so they stop crowding out everything else.

Standard library only.

Environment variables:
  SIGNAL_WINDOW  days of history to read (default 30)
  SURGE_PCT      day-over-day rise that counts as a surge (default 30)
  NOISE_FLOOR    ignore games below this player count (default 500)
  DRY_RUN        "1" to print instead of writing
"""

import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

DATA = "data"
KST = timezone(timedelta(hours=9))

WINDOW = int(os.environ.get("SIGNAL_WINDOW", "30"))
SURGE_PCT = float(os.environ.get("SURGE_PCT", "30"))
# Below this, a percentage is meaningless: 8 players becoming 80 is +900% and
# tells us nothing.
NOISE_FLOOR = int(os.environ.get("NOISE_FLOOR", "500"))
# A big game moving less than this either way is simply where it always is.
FLAT_PCT = 7.0
GIANT = 50000
CLIMB_DAYS = 3


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


def series(snapshots):
    """appid -> [(date, players)] in date order."""
    out = {}
    for snap in snapshots:
        for appid, n in (snap.get("players") or {}).items():
            out.setdefault(appid, []).append((snap["date"], n))
    for v in out.values():
        v.sort()
    return out


def climbing(points):
    """Consecutive rises at the end of the series."""
    run = 0
    for a, b in zip(points, points[1:]):
        run = run + 1 if b[1] > a[1] else 0
    return run


def days_since_release(game):
    raw = (game or {}).get("release_date") or ""
    for fmt in ("%Y년 %m월 %d일", "%d %b, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(raw.strip(), fmt).date()
            return (datetime.now(KST).date() - d).days
        except ValueError:
            continue
    return None


def classify(snapshots, games):
    if not snapshots:
        return None
    today = snapshots[-1]
    prev = snapshots[-2] if len(snapshots) > 1 else None
    now = today.get("players") or {}
    before = (prev or {}).get("players") or {}
    ranks = {t["appid"]: t for t in today.get("top_played") or []}
    prev_top = {t["appid"] for t in (prev or {}).get("top_played") or []}
    hist = series(snapshots)

    featured_ids = {i["appid"] for v in (today.get("featured") or {}).values() for i in v}

    rows = []
    for appid, players in now.items():
        if players < NOISE_FLOOR:
            continue
        was = before.get(appid)
        pct = ((players - was) / was * 100) if was else None
        pts = hist.get(appid, [])
        peak = max((n for _, n in pts), default=players)
        g = games.get(appid, {})
        r = ranks.get(appid, {})
        rows.append({
            "appid": appid,
            "name": g.get("name", appid),
            "genres": g.get("genres", []),
            "release_date": g.get("release_date", ""),
            "days_since_release": days_since_release(g),
            "is_free": g.get("is_free", False),
            "price": g.get("price", ""),
            "players": players,
            "players_prev": was,
            "pct_change": round(pct, 1) if pct is not None else None,
            "rank": r.get("rank"),
            "last_week_rank": r.get("last_week_rank"),
            "rank_delta": (r.get("last_week_rank") - r.get("rank"))
                          if r.get("rank") and r.get("last_week_rank") else None,
            "days_tracked": len(pts),
            "climb_streak": climbing(pts),
            "at_own_peak": players >= peak,
            "featured": appid in featured_ids,
        })

    def surged(x):
        return x["pct_change"] is not None and x["pct_change"] >= SURGE_PCT

    surging = sorted([x for x in rows if surged(x)], key=lambda x: -x["pct_change"])
    # New only counts once there is a previous day to be new against.
    new_entry = sorted(
        [x for x in rows if prev and x["appid"] not in before],
        key=lambda x: -x["players"])
    climbers = sorted(
        [x for x in rows if x["climb_streak"] >= CLIMB_DAYS and not surged(x)],
        key=lambda x: -x["climb_streak"])
    sinking = sorted(
        [x for x in rows if x["pct_change"] is not None and x["pct_change"] <= -SURGE_PCT],
        key=lambda x: x["pct_change"])
    # The settled giants, named so they can be set aside rather than reported.
    giants = sorted(
        [x for x in rows if x["players"] >= GIANT
         and x["pct_change"] is not None and abs(x["pct_change"]) < FLAT_PCT],
        key=lambda x: -x["players"])
    fresh = sorted(
        [x for x in rows if (x["days_since_release"] or 9999) <= 30],
        key=lambda x: -x["players"])

    return {
        "date": today["date"],
        "window": "%s ~ %s" % (snapshots[0]["date"], today["date"]),
        "days_of_history": len(snapshots),
        "thresholds": {"surge_pct": SURGE_PCT, "noise_floor": NOISE_FLOOR,
                       "giant_players": GIANT, "flat_pct": FLAT_PCT},
        "note": ("absolute player counts are not a signal - the top of the chart is the "
                 "same every day. surging / new_entry / climbing are the signal; "
                 "settled_giants is listed only so it can be ignored."),
        "surging": surging[:20],
        "new_entry": new_entry[:20],
        "climbing": climbers[:15],
        "sinking": sinking[:10],
        "recently_released": fresh[:20],
        "settled_giants": [{"name": x["name"], "players": x["players"],
                            "pct_change": x["pct_change"]} for x in giants[:10]],
        "counted": len(rows),
    }


def main():
    snaps = load_snapshots()
    if not snaps:
        print("no steam snapshots yet - run steam_collect.py first", file=sys.stderr)
        return 1
    out = classify(snaps, load_games())

    if os.environ.get("DRY_RUN") == "1":
        print(json.dumps(out, ensure_ascii=False, indent=1)[:3500])
        return 0

    path = os.path.join(DATA, "signals", "%s.json" % out["date"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("[saved] %s  급등 %d / 신규 %d / 상승 %d / 거인 %d"
          % (path, len(out["surging"]), len(out["new_entry"]),
             len(out["climbing"]), len(out["settled_giants"])), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
