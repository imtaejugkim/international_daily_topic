#!/usr/bin/env python3
"""Tell the Discord channel that today's brief did not get written.

Twelve days of collection were once lost to a brief step that failed
silently: the run went red on GitHub and nothing said so anywhere the
person actually looks. This runs only on failure and is deliberately
small - it must not fail in turn.
"""

import json
import os
import sys
import urllib.request

MESSAGE = (
    "⚠️ **오늘 브리프를 쓰지 못했습니다.** 수집한 데이터는 저장됐습니다.\n"
    "가장 흔한 원인은 토큰 만료입니다 — 로컬에서 `claude setup-token`을 다시 실행하고 "
    "`CLAUDE_CODE_OAUTH_TOKEN` 시크릿을 덮어쓰면 됩니다.\n"
    "실행 기록: <https://github.com/%s/actions/runs/%s>"
)


def main():
    hook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not hook:
        print("[notify] no webhook configured", file=sys.stderr)
        return 0

    content = MESSAGE % (os.environ.get("GITHUB_REPOSITORY", "?"),
                         os.environ.get("GITHUB_RUN_ID", "?"))
    req = urllib.request.Request(
        hook,
        data=json.dumps({"content": content}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print("[notify] sent (HTTP %s)" % resp.status, file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - a failed alert must not add noise
        print("[notify] could not send: %s" % exc, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
