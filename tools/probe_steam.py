#!/usr/bin/env python3
"""Probe Steam's public endpoints before building anything on them.

The question this answers: can we get, without an API key, (a) what is being
played right now, (b) a number per game we can track day over day to catch a
surge, and (c) enough metadata and release info to say what kind of game it
is and when it shipped.
"""

import json
import sys
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
PUBG = 578080


def get(url, label):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read()
            print("\n[%s] HTTP %s  %d bytes" % (label, r.status, len(raw)))
            return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - probing
        print("\n[%s] FAILED: %s" % (label, exc))
        return None
    finally:
        time.sleep(1)


print("=" * 64)
print("A. 지금 가장 많이 플레이되는 게임 (동시접속 기준, 키 불필요)")
print("=" * 64)
d = get("https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/", "GetMostPlayedGames")
if d:
    ranks = (d.get("response") or {}).get("ranks") or []
    print("  항목 %d개, 키: %s" % (len(ranks), sorted(ranks[0].keys()) if ranks else "?"))
    for r in ranks[:8]:
        print("   %2s위 appid=%-8s 동시접속 %-9s 최고 %s" % (
            r.get("rank"), r.get("appid"), r.get("concurrent_in_game"), r.get("peak_in_game")))

print("\n" + "=" * 64)
print("B. 특정 게임의 현재 동시접속 (급등 추적의 핵심)")
print("=" * 64)
for appid, nm in [(PUBG, "PUBG"), (730, "CS2"), (2767030, "Marvel Rivals?")]:
    d = get("https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=%d" % appid,
            "CurrentPlayers %s" % nm)
    if d:
        print("  →", d.get("response"))

print("\n" + "=" * 64)
print("C. 게임 메타데이터 (장르·출시일·가격·태그)")
print("=" * 64)
d = get("https://store.steampowered.com/api/appdetails?appids=%d&l=korean&cc=kr" % PUBG, "appdetails")
if d:
    body = (d.get(str(PUBG)) or {}).get("data") or {}
    print("  이름: %s" % body.get("name"))
    print("  장르: %s" % [g.get("description") for g in body.get("genres") or []])
    print("  카테고리: %s" % [c.get("description") for c in (body.get("categories") or [])][:6])
    print("  출시: %s" % (body.get("release_date") or {}))
    print("  가격: %s" % (body.get("price_overview") or {}).get("final_formatted"))
    print("  무료: %s  / 개발사: %s" % (body.get("is_free"), body.get("developers")))
    print("  사용 가능한 키: %s" % sorted(body.keys())[:18])

print("\n" + "=" * 64)
print("D. 신작 / 출시 예정 / 할인 (무엇이 새로 나왔나)")
print("=" * 64)
d = get("https://store.steampowered.com/api/featuredcategories?cc=kr&l=korean", "featuredcategories")
if d:
    print("  섹션: %s" % [k for k in d.keys()])
    for sec in ["new_releases", "coming_soon", "top_sellers", "specials"]:
        items = (d.get(sec) or {}).get("items") or []
        if items:
            print("  [%s] %d개  키: %s" % (sec, len(items), sorted(items[0].keys())[:10]))
            for it in items[:4]:
                print("      %-9s %s" % (it.get("id"), (it.get("name") or "")[:44]))

print("\n" + "=" * 64)
print("E. 월간 최고 신작 (GetTopReleasesPages)")
print("=" * 64)
d = get("https://api.steampowered.com/ISteamChartsService/GetTopReleasesPages/v1/", "GetTopReleasesPages")
if d:
    pages = (d.get("response") or {}).get("pages") or []
    print("  페이지 %d개" % len(pages))
    for p in pages[:3]:
        ids = p.get("item_ids") or []
        print("   %s: %d개  %s" % (p.get("name"), len(ids), [i.get("appid") for i in ids[:5]]))

print("\n" + "=" * 64)
print("F. SteamSpy (보유자 추정 - 보조)")
print("=" * 64)
d = get("https://steamspy.com/api.php?request=top100in2weeks", "steamspy")
if d:
    items = list(d.values())[:4] if isinstance(d, dict) else []
    print("  항목 %d개" % (len(d) if isinstance(d, dict) else 0))
    for it in items:
        print("   %-40s owners=%s ccu=%s" % (str(it.get("name"))[:40], it.get("owners"), it.get("ccu")))

print("\n[probe done]")
