#!/usr/bin/env python3
"""Third pass: two precise fixes.

Supply counting needs a total, and the plain JSON search returns only
`desc` and `items`. Steam's infinite-scroll variant of the same endpoint is
documented to carry `total_count`, so that is what gets asked for here.

Review bodies kept coming back as a megabyte of store-page HTML even though
the same endpoint returns clean JSON when asked for a count alone. The
difference is the cursor: without one the request is not treated as a review
query at all.
"""

import json
import re
import time
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
APPID_IN_URL = re.compile(r"/apps/(\d+)/")


def get(url, label):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read()
            head = body[:40].decode("utf-8", "replace").strip()
            print("\n[%s] HTTP %s  %d bytes  시작=%r" % (label, r.status, len(body), head[:28]))
            return json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("  FAILED: %s" % exc)
        return None
    finally:
        time.sleep(1)


print("=" * 64)
print("1. 리뷰 수 (판매량 대리지표) — 재확인")
print("=" * 64)
for appid, nm in [(646570, "Slay the Spire"), (4459590, "슬롯바운드"), (3321460, "붉은사막")]:
    d = get("https://store.steampowered.com/appreviews/%d?json=1&language=all&num_per_page=0"
            % appid, "reviews %s" % nm)
    if d:
        q = d.get("query_summary") or {}
        print("  총 %-8s 긍정 %-8s 부정 %-7s %s" % (
            q.get("total_reviews"), q.get("total_positive"),
            q.get("total_negative"), q.get("review_score_desc")))

print("\n" + "=" * 64)
print("2. 태그별 공급량 — infinite=1 이면 total_count 가 오나")
print("=" * 64)
for name, tagid in [("Roguelike Deckbuilder", 1091588), ("Auto Battler", 1084988),
                    ("Idler", 615955), ("Survivors-like", 0)][:3]:
    d = get("https://store.steampowered.com/search/results/"
            "?query&tags=%d&category1=998&cc=kr&l=koreana&infinite=1&count=1" % tagid,
            "supply %s" % name)
    if d:
        print("  키: %s" % sorted(d.keys()))
        print("  → '%s' 태그 게임 총 %s개" % (name, d.get("total_count")))

print("\n" + "=" * 64)
print("3. 같은 태그 + 최근 출시만 — 공급 '속도'를 낼 수 있나")
print("=" * 64)
d = get("https://store.steampowered.com/search/results/"
        "?query&tags=1091588&category1=998&sort_by=Released_DESC"
        "&cc=kr&l=koreana&infinite=1&count=50", "roguelike deckbuilder 최신순")
if d:
    print("  총 %s개" % d.get("total_count"))
    ids = APPID_IN_URL.findall(d.get("results_html") or "")
    print("  results_html 에서 appid %d개 추출: %s" % (len(ids), ids[:8]))

print("\n" + "=" * 64)
print("4. 리뷰 본문 — cursor=* 를 주면 JSON 이 오나")
print("=" * 64)
d = get("https://store.steampowered.com/appreviews/646570"
        "?json=1&language=all&review_type=negative&num_per_page=5&cursor=*",
        "negative + cursor")
if d:
    rs = d.get("reviews") or []
    print("  success=%s 리뷰 %d개  cursor=%s" % (
        d.get("success"), len(rs), str(d.get("cursor"))[:18]))
    for rv in rs[:4]:
        txt = (rv.get("review") or "").replace("\n", " ")[:86]
        print("   [추천%s %s분] %s" % (
            rv.get("voted_up"), (rv.get("author") or {}).get("playtime_forever"), txt))

print("\n[probe done]")
