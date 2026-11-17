#!/usr/bin/env python3
"""Can SteamSpy replace the review counts?

The store's appreviews endpoint returns a megabyte of HTML for every appid at
every pacing - it is not serving review queries at all, so the success rate
cannot be built on it.

SteamSpy answered cleanly in an earlier probe, and crucially its tag query
returns a whole tag at once rather than one game per request. This checks the
shape of that, how much it covers, whether it carries anything usable as a
sales proxy, and what it does when asked repeatedly.

Summary last.
"""

import json
import time
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
API = "https://steamspy.com/api.php?%s"


def get(query, label, timeout=40):
    started = time.monotonic()
    try:
        req = urllib.request.Request(API % query, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            secs = time.monotonic() - started
            head = body[:24].decode("utf-8", "replace").replace("\n", " ")
            print("\n[%s] HTTP %s  %d바이트  %.1fs  시작=%r"
                  % (label, r.status, len(body), secs, head))
            return json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("\n[%s] FAILED (%.1fs): %s" % (label, time.monotonic() - started, exc))
        return None


results = {}

print("=" * 62)
print("1. 태그 한 번에 전체 — 게임당 요청이 사라지나")
print("=" * 62)
for tag in ["Auto Battler", "Roguelike Deckbuilder", "Idler"]:
    d = get("request=tag&tag=%s" % urllib.request.quote(tag), "tag %s" % tag)
    if isinstance(d, dict):
        results[tag] = d
        sample = next(iter(d.values()), {})
        print("  게임 %d개, 항목 키: %s" % (len(d), sorted(sample)[:14]))
        rows = sorted(d.values(), key=lambda g: -(g.get("positive", 0) + g.get("negative", 0)))
        for g in rows[:4]:
            tot = g.get("positive", 0) + g.get("negative", 0)
            print("     %-38s 리뷰 %-7s 소유자 %s" % (
                str(g.get("name"))[:38], tot, g.get("owners")))

print("\n" + "=" * 62)
print("2. 신작이 들어 있나 — 성공률 분모의 신선도")
print("=" * 62)
d = results.get("Auto Battler") or {}
if d:
    years = {}
    for g in d.values():
        tot = g.get("positive", 0) + g.get("negative", 0)
        years[tot >= 50] = years.get(tot >= 50, 0) + 1
    print("  리뷰 50개 이상: %d개 / 미만: %d개 → 성공률 %.1f%%" % (
        years.get(True, 0), years.get(False, 0),
        100.0 * years.get(True, 0) / max(1, len(d))))
    zero = sum(1 for g in d.values() if (g.get("positive", 0) + g.get("negative", 0)) == 0)
    print("  리뷰 0개(= 신작이거나 데이터 없음): %d개" % zero)

print("\n" + "=" * 62)
print("3. 연속 호출을 견디나")
print("=" * 62)
ok = 0
for i, tag in enumerate(["Bullet Hell", "Tower Defense", "Card Game", "Roguelite"], 1):
    d = get("request=tag&tag=%s" % urllib.request.quote(tag), "연속 %d" % i, timeout=40)
    if isinstance(d, dict) and d:
        ok += 1
    time.sleep(2)

print("\n" + "=" * 62)
print("요약")
print("=" * 62)
print("  태그 조회 성공: %d/3 (1부) + %d/4 (연속)" % (len(results), ok))
if results:
    sample = next(iter(results.values()))
    g = next(iter(sample.values()), {})
    has = [k for k in ("positive", "negative", "owners", "price",
                       "average_forever", "median_forever", "ccu") if k in g]
    print("  쓸 수 있는 필드: %s" % has)
    print("\n판정:")
    print("  태그 1건 = 요청 1회. 게임당 조회가 필요 없다.")
    if "positive" in g:
        print("  리뷰 수가 positive+negative 로 들어온다 → 성공률 계산 가능.")
    if "median_forever" in g:
        print("  중앙 플레이타임이 있다 → 루프가 붙잡는지 볼 수 있다.")
else:
    print("  태그 조회 실패. 이 경로도 못 쓴다.")
print("\n[probe done]")
