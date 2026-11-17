#!/usr/bin/env python3
"""Second pass: fix what the first probe broke, and test a better way to
count supply.

Two things came back wrong. Search results carry no appid, only a name and a
logo URL - but the appid is in that URL's path, so it should be recoverable.
And SteamSpy knows nothing about a game released five days ago, which is
exactly the population that matters, so per-game tagging cannot be the way
supply is counted.

The alternative tested here is to count supply by querying the store per tag
instead of tagging each game: if a tag search reports how many games match,
that number is the supply, directly.
"""

import json
import re
import time
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
APPID_IN_URL = re.compile(r"/(?:apps|steam/apps)/(\d+)/")


def get(url, label, as_json=True):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read()
            print("\n[%s] HTTP %s  %d bytes" % (label, r.status, len(body)))
            return json.loads(body.decode("utf-8")) if as_json else body.decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        print("\n[%s] FAILED: %s" % (label, exc))
        return None
    finally:
        time.sleep(1)


print("=" * 66)
print("1. 리뷰 수 = 판매량 대리지표 (확인)")
print("=" * 66)
for appid, nm in [(3321460, "붉은사막"), (4459590, "슬롯바운드"), (646570, "Slay the Spire")]:
    d = get("https://store.steampowered.com/appreviews/%d?json=1&language=all&num_per_page=0"
            % appid, "reviews %s" % nm)
    if d:
        q = d.get("query_summary") or {}
        print("  총 %-7s 긍정 %-7s 부정 %-6s %s" % (
            q.get("total_reviews"), q.get("total_positive"),
            q.get("total_negative"), q.get("review_score_desc")))

print("\n" + "=" * 66)
print("2. 검색 결과에서 appid 복원 (logo URL 경로에 들어있나)")
print("=" * 66)
d = get("https://store.steampowered.com/search/results/"
        "?query&sort_by=Released_DESC&category1=998&cc=kr&l=koreana&json=1&count=20",
        "search Released_DESC")
if isinstance(d, dict):
    items = d.get("items") or []
    print("  응답 최상위 키: %s" % sorted(d.keys()))
    got = 0
    for it in items[:8]:
        m = APPID_IN_URL.search(it.get("logo") or "")
        if m:
            got += 1
        print("   appid=%-9s %s" % (m.group(1) if m else "못찾음", str(it.get("name"))[:44]))
    print("  → %d/%d 에서 appid 복원" % (got, len(items[:8])))
    print("  logo 원문 예: %s" % (items[0].get("logo") if items else "")[:110])

print("\n" + "=" * 66)
print("3. 태그별 공급량 — 게임마다 태그를 붙이는 대신 태그로 세기")
print("=" * 66)
tags = get("https://store.steampowered.com/tagdata/populartags/english", "populartags")
if isinstance(tags, list):
    print("  태그 %d개, 예: %s" % (len(tags), [t.get("name") for t in tags[:8]]))
    want = {"Roguelike Deckbuilder", "Auto Battler", "Idler", "Survivors-like",
            "Roguelite", "Deckbuilding"}
    found = {t["name"]: t["tagid"] for t in tags if t.get("name") in want}
    print("  관심 태그 id: %s" % found)
    for name, tagid in list(found.items())[:3]:
        d = get("https://store.steampowered.com/search/results/"
                "?query&tags=%d&sort_by=Released_DESC&category1=998&cc=kr&l=koreana"
                "&json=1&count=1" % tagid, "supply '%s'" % name)
        if isinstance(d, dict):
            print("     '%s' 로 나온 게임 총 %s개" % (name, d.get("total_count")))

print("\n" + "=" * 66)
print("4. 부정 리뷰 본문 (1차에서 HTML이 돌아왔다 - 파라미터 교정)")
print("=" * 66)
for label, url in [
    ("all/negative", "https://store.steampowered.com/appreviews/646570"
                     "?json=1&language=all&review_type=negative&num_per_page=5&purchase_type=all"),
    ("korean/recent", "https://store.steampowered.com/appreviews/646570"
                      "?json=1&language=korean&filter=recent&num_per_page=5&purchase_type=all"),
]:
    d = get(url, label)
    if isinstance(d, dict):
        rs = d.get("reviews") or []
        print("  success=%s 리뷰 %d개" % (d.get("success"), len(rs)))
        for rv in rs[:3]:
            txt = (rv.get("review") or "").replace("\n", " ")[:80]
            print("     [추천%s %s분] %s" % (
                rv.get("voted_up"), (rv.get("author") or {}).get("playtime_forever"), txt))

print("\n[probe done]")
