#!/usr/bin/env python3
"""Deliver one request to the existing cutoff owner; never opens a Device.

Use a private FIFO as the owner's stdin and capture its stdout in events.jsonl.
This avoids terminal line limits and interactive-session input loss. A timeout
is uncertain delivery: inspect receipts and observe, never resend the batch.
"""
import argparse
import json
import os
from pathlib import Path
import select
import sys
import time


def send(fifo, events, request, timeout=20):
    if not isinstance(request, dict) or not request.get("id"):
        raise ValueError("A unique request id is required")
    deadline = time.monotonic() + timeout
    with open(events) as responses:
        responses.seek(0, os.SEEK_END)
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        try:
            payload = (json.dumps(request, ensure_ascii=False) + "\n").encode()
            while payload:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                    raise TimeoutError("Command delivery uncertain; do not resend")
                try:
                    payload = payload[os.write(fd, payload):]
                except BlockingIOError:
                    continue
        finally:
            os.close(fd)
        pending = ""
        while time.monotonic() < deadline:
            pending += responses.read()
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                value = json.loads(line)
                if value.get("id") == request["id"]:
                    return value
                if value.get("event") == "closed" and request.get("command") == "close":
                    return value
            time.sleep(.05)
    raise TimeoutError("No matching response; inspect receipts, do not resend")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fifo", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--request", default="-", help="JSON file or - for stdin")
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    request = json.loads(sys.stdin.read() if args.request == "-" else Path(args.request).read_text())
    print(json.dumps(send(args.fifo, args.events, request, args.timeout)))
