#!/usr/bin/env python3
"""Posting embeds to a Discord webhook, within Discord's limits.

Shared by anything that sends. The limits are the reason this is a module
rather than a few inline lines: a message takes at most 10 embeds and 6000
characters across them, and exceeding either is a 400 with the whole message
lost, so grouping has to be done by measured size rather than by count.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# Discord's hard limits: title 256, description 4096, 10 embeds and 6000
# characters per message. chunk() keeps every message under MAX_MESSAGE_CHARS.
MAX_TITLE = 240
MAX_DESC = 1900
EMBEDS_PER_MESSAGE = 3
MAX_MESSAGE_CHARS = 5500


def clip(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def embed_len(embed):
    return len(embed.get("title", "")) + len(embed.get("description", ""))


def chunk(embeds):
    """Group embeds into messages that fit Discord's per-message limits."""
    out, current, size = [], [], 0
    for embed in embeds:
        too_big = current and (
            len(current) >= EMBEDS_PER_MESSAGE
            or size + embed_len(embed) > MAX_MESSAGE_CHARS
        )
        if too_big:
            out.append(current)
            current, size = [], 0
        current.append(embed)
        size += embed_len(embed)
    if current:
        out.append(current)
    return out


def post(webhook, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if exc.code == 429:
            try:
                wait = float(json.loads(body).get("retry_after", 2))
            except Exception:  # noqa: BLE001
                wait = 2.0
            time.sleep(min(wait + 0.5, 30))
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status
        raise RuntimeError("Discord %s: %s" % (exc.code, body)) from exc


def send(webhook, embeds, header, dry=False):
    """Post the embeds, header on the first message only."""
    if dry:
        print(header)
        for e in embeds:
            print("\n=== %s ===" % e["title"])
            print(e["description"])
        return 0
    for i, group in enumerate(chunk(embeds)):
        payload = {"embeds": group}
        if i == 0:
            payload["content"] = header
        status = post(webhook, payload)
        print("[discord] sent %d embeds (HTTP %s)" % (len(group), status), file=sys.stderr)
        time.sleep(1)
    return 0
