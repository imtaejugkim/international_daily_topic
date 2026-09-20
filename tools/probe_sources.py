#!/usr/bin/env python3
"""Probe candidate data sources for the trend pipeline.

Run this from CI (the sandbox has no outbound access to these hosts) to check
that an endpoint is alive and to see the shape of what it returns before
writing a parser against it. Apple throttles rapid repeat calls, so space the
requests out and retry the timeouts.
"""

import json
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

CHART = "https://rss.marketingtools.apple.com/api/v2/{cc}/apps/{kind}/25/apps.json"
REVIEWS = "https://itunes.apple.com/{cc}/rss/customerreviews/page=1/id={app_id}/sortby=mostrecent/json"


def get(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - probing, report and retry
            last = exc
            time.sleep(2 * (i + 1))
    raise last


def genres(app):
    return [g.get("name", "") for g in (app.get("genres") or []) if g.get("name")]


def probe_charts(countries):
    print("=" * 62)
    print("A. Apple top-free charts per country")
    print("=" * 62)
    charts = {}
    for cc in countries:
        try:
            status, data = get(CHART.format(cc=cc, kind="top-free"))
            results = data["feed"]["results"]
            charts[cc] = results
            print("\n[%s] HTTP %s  %d apps" % (cc.upper(), status, len(results)))
            for app in results[:5]:
                print("   %-30s | %-20s | %s" % (
                    app.get("name", "?")[:30],
                    app.get("artistName", "?")[:20],
                    "/".join(genres(app)[:2]) or "-"))
        except Exception as exc:  # noqa: BLE001
            print("\n[%s] FAILED: %s" % (cc.upper(), exc))
        time.sleep(1.5)
    return charts


def probe_reviews(charts):
    print("\n" + "=" * 62)
    print("B. Apple customer reviews (the complaint data)")
    print("=" * 62)
    for cc in ["kr", "us"]:
        results = charts.get(cc)
        if not results:
            print("\n[%s] skipped - no chart" % cc.upper())
            continue
        app = results[0]
        app_id, app_name = app["id"], app.get("name", "?")
        try:
            status, data = get(REVIEWS.format(cc=cc, app_id=app_id))
            entries = data.get("feed", {}).get("entry", []) or []
            if isinstance(entries, dict):
                entries = [entries]
            reviews = [e for e in entries if "im:rating" in e]
            low = [e for e in reviews if int(e["im:rating"]["label"]) <= 2]
            print("\n[%s] HTTP %s  app=%s (id %s)" % (cc.upper(), status, app_name, app_id))
            print("   entries=%d  reviews=%d  1-2star=%d" % (len(entries), len(reviews), len(low)))
            for e in (low or reviews)[:3]:
                print("   %s* %s" % (e["im:rating"]["label"], e["title"]["label"][:60]))
                print("      %s" % e["content"]["label"][:120].replace("\n", " "))
        except Exception as exc:  # noqa: BLE001
            print("\n[%s] FAILED: %s" % (cc.upper(), exc))
        time.sleep(1.5)


def probe_gap(charts):
    print("\n" + "=" * 62)
    print("C. Cross-country gap (the 'new service' signal)")
    print("=" * 62)
    if not (charts.get("kr") and charts.get("jp")):
        print("skipped - need both KR and JP charts")
        return
    kr_cats = {g for app in charts["kr"] for g in genres(app)}
    jp_cats = {g for app in charts["jp"] for g in genres(app)}
    kr_apps = {app.get("name") for app in charts["kr"]}
    jp_apps = {app.get("name") for app in charts["jp"]}
    print("KR categories (%d): %s" % (len(kr_cats), sorted(kr_cats)))
    print("JP categories (%d): %s" % (len(jp_cats), sorted(jp_cats)))
    print("\nJP-only categories: %s" % (sorted(jp_cats - kr_cats) or "none"))
    print("KR-only categories: %s" % (sorted(kr_cats - jp_cats) or "none"))
    print("\nApps in both charts: %s" % (sorted(kr_apps & jp_apps) or "none"))


if __name__ == "__main__":
    charts = probe_charts(["kr", "us", "jp", "de", "br"])
    probe_reviews(charts)
    probe_gap(charts)
    print("\n[probe done] charts ok for: %s" % ",".join(sorted(charts)))
    sys.exit(0)
