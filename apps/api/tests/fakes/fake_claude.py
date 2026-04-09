#!/usr/bin/env python
"""Fake claude CLI: emits canned stream-json for worker tests."""
import json, sys, time

LINES = [
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "doing the work"}]}},
    {"type": "result", "subtype": "success", "result": "task complete"},
]
for line in LINES:
    sys.stdout.write(json.dumps(line) + "\n")
    sys.stdout.flush()
    time.sleep(0.01)
