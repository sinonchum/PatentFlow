from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

import redislite

DATA = Path(__file__).resolve().parents[1] / ".local-redis.db"

redis = redislite.Redis(str(DATA), serverconfig={"port": "6379", "bind": "127.0.0.1"})
print("redislite ready on redis://127.0.0.1:6379/0", flush=True)

running = True

def stop(signum, frame):
    global running
    running = False

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

try:
    while running:
        try:
            redis.ping()
        except Exception as exc:
            print(f"redislite ping failed: {exc}", file=sys.stderr, flush=True)
            break
        time.sleep(1)
finally:
    try:
        redis.shutdown()
    except Exception:
        pass
