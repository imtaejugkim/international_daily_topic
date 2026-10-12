#!/usr/bin/env python3
"""Turn the accumulated daily snapshots into persistence signals.

A single day's chart cannot tell a trend from a spike - roughly a fifth of
the apps that appear do so for one day and vanish. What separates them is
time: an app several weeks on the chart, or a category where several
different apps hold at once, is a trend; yesterday's one-off is not.

Reads every snapshot in the window and writes data/trendlines/<date>.json,
which is what the brief should lean on when it says something is "뜨고 있다".

Standard library only.

Environment variables:
  TREND_WINDOW   days of history to consider (default 30)
  SUSTAINED_DAYS days on chart to count as sustained (default 7)
  DRY_RUN        "1" to print instead of writing
"""

import collections
import glob
import json
import os
import sys
from datetime import datetime

DATA = "data"
WINDOW = int(os.environ.get("TREND_WINDOW", "30"))
SUSTAINED = int(os.environ.get("SUSTAINED_DAYS", "7"))
# Average rank must move at least this much between the first and last third
# of an app's history before it counts as rising or fading.
DRIFT = 3.0
TOP = 20


def load(kind):
    out = []
    for path in sorted(glob.glob(os.path.join(DATA, kind, "*.json")))[-WINDOW:]:
        try:
            with open(path, encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError) as exc:
            print("[skip] %s: %s" % (path, exc), file=sys.stderr)
    return out


def app_lines(snapshots):
    """Per app: how long it held, where, how high, and which way it is moving."""
    points = collections.defaultdict(list)   # id -> [(date, country, rank)]
    names, genres = {}, {}
    for snap in snapshots:
        date = snap["date"]
        for cc, apps in snap["charts"].items():
            for a in apps:
                points[a["id"]].append((date, cc, a["rank"]))
                names[a["id"]] = a["name"]
                if a.get("genres"):
                    genres[a["id"]] = {"ids": a.get("genre_ids", []), "names": a["genres"]}

    lines = []
    for app_id, pts in points.items():
        pts.sort()
        dates = sorted({d for d, _, _ in pts})
        countries = sorted({c for _, c, _ in pts})
        third = max(1, len(pts) // 3)
        early = sum(r for _, _, r in pts[:third]) / third
        late = sum(r for _, _, r in pts[-third:]) / third
        lines.append({
            "id": app_id,
            "name": names[app_id],
            "genres": (genres.get(app_id) or {}).get("names", []),
            "genre_ids": (genres.get(app_id) or {}).get("ids", []),
            "days": len(dates),
            "countries": countries,
            "best_rank": min(r for _, _, r in pts),
            "first_seen": dates[0],
            "last_seen": dates[-1],
            "drift": round(early - late, 1),   # positive = climbing
        })
    return lines


def genre_activity(lines):
    """Sustained apps grouped by genre id.

    Grouped by id, not name: the chart localizes names, so Entertainment and
    엔터테인먼트 are the same genre and must not split in two. This is context,
    not a verdict - a broad genre always holds many apps, so whether several
    *similar* apps rising together amounts to a wave is a judgement call left
    to whoever reads this.
    """
    by_id = collections.defaultdict(lambda: {"apps": [], "countries": set(), "names": set()})
    for line in lines:
        if line["days"] < SUSTAINED:
            continue
        for gid, gname in zip(line["genre_ids"], line["genres"]):
            slot = by_id[gid]
            slot["apps"].append({"name": line["name"], "days": line["days"],
                                 "best_rank": line["best_rank"],
                                 "countries": line["countries"]})
            slot["countries"].update(line["countries"])
            slot["names"].add(gname)
    out = []
    for gid, d in by_id.items():
        if len(d["apps"]) < 2:
            continue
        out.append({
            "genre_id": gid,
            "genre_names": sorted(d["names"]),
            "sustained_apps": len(d["apps"]),
            "countries": sorted(d["countries"]),
            "apps": sorted(d["apps"], key=lambda a: -a["days"])[:10],
        })
    return sorted(out, key=lambda w: -w["sustained_apps"])


def keyword_persistence(snapshots):
    """Search terms that come back on several days. A term that appears once
    is a news spike; one that keeps returning is something people stay on."""
    seen = collections.defaultdict(lambda: collections.defaultdict(set))
    for snap in snapshots:
        date = snap["date"]
        for cc, items in snap.get("trends", {}).items():
            for t in items:
                seen[cc][t["title"].strip().lower()].add(date)
    out = {}
    for cc, terms in seen.items():
        repeated = sorted(((len(d), k) for k, d in terms.items() if len(d) >= 3), reverse=True)
        out[cc] = [{"keyword": k, "days": n} for n, k in repeated[:12]]
    return out


def main():
    charts = load("charts")
    if not charts:
        print("no chart snapshots yet", file=sys.stderr)
        return 1
    trends = load("trends")

    lines = app_lines(charts)
    window = "%s ~ %s" % (charts[0]["date"], charts[-1]["date"])

    sustained = sorted([l for l in lines if l["days"] >= SUSTAINED],
                       key=lambda l: (-l["days"], l["best_rank"]))[:TOP]
    rising = sorted([l for l in lines if l["drift"] > DRIFT and l["days"] >= 3],
                    key=lambda l: -l["drift"])[:TOP]
    fading = sorted([l for l in lines if l["drift"] < -DRIFT and l["days"] >= 3],
                    key=lambda l: l["drift"])[:10]
    recent = {c["date"] for c in charts[-5:]}
    breaking = sorted([l for l in lines
                       if l["best_rank"] <= 10 and l["days"] <= 5 and l["last_seen"] in recent],
                      key=lambda l: l["best_rank"])[:10]
    oneday = sum(1 for l in lines if l["days"] == 1)

    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "window": window,
        "days_of_history": len(charts),
        "sustained_threshold_days": SUSTAINED,
        "note": ("sustained = 차트에 오래 머문 것 = 트렌드 후보. "
                 "one_day_only 비율이 높다는 건 하루짜리 급등은 대부분 노이즈라는 뜻."),
        "one_day_only": oneday,
        "total_apps_seen": len(lines),
        "sustained": sustained,
        "rising": rising,
        "fading": fading,
        "breaking_in": breaking,
        "genre_activity": genre_activity(lines),
        "repeated_keywords": keyword_persistence(trends),
    }

    if os.environ.get("DRY_RUN") == "1":
        print(json.dumps(payload, ensure_ascii=False, indent=1)[:4000])
        print("\n[dry-run] %d일치, 지속 %d개, 상승 %d개, 장르 묶음 %d개"
              % (len(charts), len(sustained), len(rising), len(payload["genre_activity"])),
              file=sys.stderr)
        return 0

    path = os.path.join(DATA, "trendlines", "%s.json" % payload["date"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("[saved] %s (%d일치, 지속 %d, 장르 %d)"
          % (path, len(charts), len(sustained), len(payload["genre_activity"])), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
