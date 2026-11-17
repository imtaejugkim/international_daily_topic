#!/usr/bin/env python3
"""Why do review-count requests fail?

The collector reported 210 of 210 failures, which tells us nothing: it
catches every exception the same way, so a timeout, a 429 and a page of HTML
parsed as JSON all look identical.

This separates them. For each request it records the status, the elapsed
time, what the body actually starts with, and the exact exception - then
repeats at different pacings to find where it breaks.

Summary goes last, because logs get read from the end.
"""

import json
import sys
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
URL = ("https://store.steampowered.com/appreviews/%s"
       "?json=1&language=all&purchase_type=all&num_per_page=0")

# A spread of real appids: huge, mid, tiny, brand new.
APPIDS = ["646570", "578080", "730", "4459590", "3321460", "1145360",
          "427520", "892970", "1794680", "2767030", "413150", "322330"]


def attempt(appid, timeout):
    """One request, fully described."""
    started = time.monotonic()
    row = {"appid": appid, "status": None, "kind": None,
           "bytes": 0, "head": "", "error": ""}
    try:
        req = urllib.request.Request(URL % appid, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            row["status"] = r.status
            row["bytes"] = len(body)
            row["head"] = body[:34].decode("utf-8", "replace").replace("\n", " ")
            try:
                d = json.loads(body.decode("utf-8"))
                q = d.get("query_summary") or {}
                if "total_reviews" in q:
                    row["kind"] = "JSON-OK(%s리뷰)" % q["total_reviews"]
                else:
                    row["kind"] = "JSON-빈값"
            except ValueError:
                row["kind"] = "HTML"
    except urllib.error.HTTPError as exc:
        row["status"], row["kind"] = exc.code, "HTTP오류"
        row["error"] = str(exc)[:40]
    except Exception as exc:  # noqa: BLE001
        row["kind"] = type(exc).__name__
        row["error"] = str(exc)[:40]
    row["secs"] = round(time.monotonic() - started, 1)
    return row


def run(label, appids, gap, timeout):
    print("\n--- %s (간격 %.2fs, 타임아웃 %ds) ---" % (label, gap, timeout))
    rows = []
    for appid in appids:
        r = attempt(appid, timeout)
        rows.append(r)
        print("  %-8s %-4s %-16s %5.1fs %7d바이트 %s%s" % (
            r["appid"], r["status"] or "-", r["kind"], r["secs"], r["bytes"],
            r["head"][:26], (" ← " + r["error"]) if r["error"] else ""))
        time.sleep(gap)
    return rows


def tally(rows):
    out = {}
    for r in rows:
        key = r["kind"].split("(")[0]
        out[key] = out.get(key, 0) + 1
    return out


results = {}
results["빠르게 연속 (수집기와 동일)"] = run("빠르게 연속", APPIDS, 0.22, 8)
time.sleep(5)
results["느리게"] = run("느리게", APPIDS[:6], 2.0, 20)
time.sleep(20)
results["20초 쉰 뒤 한 건"] = run("휴식 후 단발", APPIDS[:3], 3.0, 20)

print("\n" + "=" * 60)
print("요약")
print("=" * 60)
for label, rows in results.items():
    counts = tally(rows)
    ok = sum(v for k, v in counts.items() if k == "JSON-OK")
    print("  %-26s %d/%d 성공   %s" % (label, ok, len(rows), counts))

print("\n판정:")
allrows = [r for rows in results.values() for r in rows]
kinds = tally(allrows)
if kinds.get("JSON-OK"):
    print("  엔드포인트 자체는 동작한다. 실패는 호출 속도 문제다.")
else:
    print("  어떤 간격으로도 JSON이 오지 않는다. 엔드포인트 접근 방식을 바꿔야 한다.")
if kinds.get("HTML"):
    print("  HTML 응답이 섞여 있다 = 스토어가 리뷰 질의로 취급하지 않는 요청이 있다.")
if kinds.get("timeout") or kinds.get("TimeoutError") or kinds.get("URLError"):
    print("  타임아웃/연결 오류가 있다 = 지연으로 막히는 중.")
if kinds.get("HTTP오류"):
    print("  명시적 HTTP 오류가 있다 = 상태 코드로 차단 사유를 알 수 있다.")
print("\n[probe done]")
