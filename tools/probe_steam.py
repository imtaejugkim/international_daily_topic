#!/usr/bin/env python3
"""Probe the endpoints a supply-and-demand reading would need.

Concurrent players answer "who is being played right now", which is the wrong
question for deciding what to build: it only shows games already big enough to
chart, it is not a sales figure, and by the time a game appears there the
opportunity is weeks old.

What a developer needs instead is demand against supply - how many people are
buying a kind of game versus how many such games ship - plus a signal that
arrives before release, where a four-month build can still be in time. This
checks whether that is obtainable without an API key.
"""

import json
import time
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def get(url, label, raw=False):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read()
            print("\n[%s] HTTP %s  %d bytes" % (label, r.status, len(body)))
            return body if raw else json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - probing
        print("\n[%s] FAILED: %s" % (label, exc))
        return None
    finally:
        time.sleep(1)


print("=" * 66)
print("1. 리뷰 수 — 판매량 대리지표. 매일 재면 증가 속도가 나온다")
print("=" * 66)
for appid, nm in [(3321460, "붉은사막"), (4459590, "슬롯바운드"), (578080, "PUBG")]:
    d = get("https://store.steampowered.com/appreviews/%d?json=1&language=all&num_per_page=0"
            % appid, "appreviews %s" % nm)
    if d:
        q = d.get("query_summary") or {}
        print("  총 리뷰 %-8s 긍정 %-8s 점수 %s" % (
            q.get("total_reviews"), q.get("total_positive"), q.get("review_score_desc")))
        print("  키: %s" % sorted(q.keys()))

print("\n" + "=" * 66)
print("2. 신작 전수 — 분모. 죽은 게임까지 세야 생존율이 나온다")
print("=" * 66)
d = get("https://store.steampowered.com/search/results/"
        "?query&sort_by=Released_DESC&category1=998&cc=kr&l=koreana&json=1&count=100",
        "search Released_DESC")
if isinstance(d, dict):
    items = d.get("items") or []
    print("  전체 %s개 중 %d개 반환" % (d.get("total_count", "?"), len(items)))
    print("  키: %s" % (sorted(items[0].keys()) if items else "?"))
    for it in items[:6]:
        print("     %-50s %s" % (str(it.get("name"))[:50], str(it.get("logo", ""))[-30:]))

print("\n" + "=" * 66)
print("3. 출시 예정 인기순 — 위시리스트 대리. 유일하게 시차를 이기는 신호")
print("=" * 66)
d = get("https://store.steampowered.com/search/results/"
        "?query&filter=popularcomingsoon&cc=kr&l=koreana&json=1&count=50",
        "popularcomingsoon")
if isinstance(d, dict):
    items = d.get("items") or []
    print("  전체 %s개 중 %d개 반환" % (d.get("total_count", "?"), len(items)))
    for it in items[:10]:
        print("     %s" % str(it.get("name"))[:56])

print("\n" + "=" * 66)
print("4. 태그 — Steam 장르는 너무 거칠다. 태그라야 장르가 구분된다")
print("=" * 66)
for appid, nm in [(4459590, "슬롯바운드"), (646570, "Slay the Spire")]:
    d = get("https://steamspy.com/api.php?request=appdetails&appid=%d" % appid,
            "steamspy %s" % nm)
    if d:
        tags = d.get("tags") or {}
        print("  이름: %s" % d.get("name"))
        print("  소유자: %s  / 가격: %s" % (d.get("owners"), d.get("price")))
        print("  태그 %d개: %s" % (len(tags), list(tags)[:12] if isinstance(tags, dict) else tags))

print("\n" + "=" * 66)
print("5. 리뷰 본문 — '빈자리' 트랙의 재료. 뜬 게임의 불만이 곧 기회")
print("=" * 66)
d = get("https://store.steampowered.com/appreviews/4459590"
        "?json=1&language=koreana&filter=recent&num_per_page=5&review_type=negative",
        "negative reviews")
if d:
    for rv in (d.get("reviews") or [])[:4]:
        txt = (rv.get("review") or "").replace("\n", " ")[:90]
        print("   [추천%s 플레이%s분] %s" % (
            rv.get("voted_up"), (rv.get("author") or {}).get("playtime_forever"), txt))

print("\n[probe done]")
