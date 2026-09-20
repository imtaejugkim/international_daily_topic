#!/usr/bin/env python3
"""Probe candidate data sources for the trend pipeline.

Run this from CI (the sandbox has no outbound access to these hosts) to check
that an endpoint is alive and to see the shape of what it returns before
writing a parser against it.
"""

import json
import sys
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

CHART = "https://rss.marketingtools.apple.com/api/v2/{cc}/apps/{kind}/25/apps.json"
REVIEWS = "https://itunes.apple.com/{cc}/rss/customerreviews/page=1/id={app_id}/sortby=mostrecent/json"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def probe_charts():
    print("=" * 60)
    print("A. Apple top-free charts per country")
    print("=" * 60)
    first_app = {}
    for cc in ["kr", "us", "jp", "de", "br"]:
        try:
            status, data = get(CHART.format(cc=cc, kind="top-free"))
            results = data["feed"]["results"]
            print("\n[%s] HTTP %s  %d apps  updated=%s" % (
                cc.upper(), status, len(results), data["feed"].get("updated", "?")[:10]))
            for app in results[:5]:
                print("   %-28s %-22s %s" % (
                    app["name"][:28], app.get("artistName", "")[:22],
                    ",".join(app.get("genres", [{}])[0].get("name", "") for _ in [0])))
            first_app[cc] = (results[0]["id"], results[0]["name"])
        except Exception as exc:
            print("\n[%s] FAILED: %s" % (cc.upper(), exc))
    return first_app


def probe_reviews(first_app):
    print("\n" + "=" * 60)
    print("B. Apple customer reviews (the complaint data)")
    print("=" * 60)
    for cc in ["kr", "us"]:
        if cc not in first_app:
            continue
        app_id, app_name = first_app[cc]
        try:
            status, data = get(REVIEWS.format(cc=cc, app_id=app_id))
            entries = data.get("feed", {}).get("entry", [])
            if isinstance(entries, dict):
                entries = [entries]
            reviews = [e for e in entries if "im:rating" in e]
            low = [e for e in reviews if int(e["im:rating"]["label"]) <= 2]
            print("\n[%s] HTTP %s  app=%s (id %s)" % (cc.upper(), status, app_name, app_id))
            print("   entries=%d  reviews=%d  1-2star=%d" % (len(entries), len(reviews), len(low)))
            for e in (low or reviews)[:3]:
                print("   %s* %s" % (e["im:rating"]["label"], e["title"]["label"][:60]))
                print("      %s" % e["content"]["label"][:110].replace("\n", " "))
        except Exception as exc:
            print("\n[%s] FAILED: %s" % (cc.upper(), exc))


def probe_chart_gap(first_app):
    print("\n" + "=" * 60)
    print("C. Cross-country gap: categories present in JP but not KR")
    print("=" * 60)
    try:
        cats = {}
        for cc in ["kr", "jp"]:
            _, data = get(CHART.format(cc=cc, kind="top-free"))
            cats[cc] = {
                g["name"]
                for app in data["feed"]["results"]
                for g in app.get("genres", [])
            }
        print("KR categories: %d, JP categories: %d" % (len(cats["kr"]), len(cats["jp"])))
        print("JP-only: %s" % sorted(cats["jp"] - cats["kr"]))
        print("KR-only: %s" % sorted(cats["kr"] - cats["jp"]))
    except Exception as exc:
        print("FAILED: %s" % exc)


if __name__ == "__main__":
    apps = probe_charts()
    probe_reviews(apps)
    probe_chart_gap(apps)
    print("\n[probe done]")
    sys.exit(0)
