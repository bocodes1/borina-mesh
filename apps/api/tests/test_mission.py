"""Missions: 'mission: <goal>' fans out to multiple read-only agents via the
CEO (decompose → parallel run → synthesize). Forbidden gate still wins."""
import asyncio
import json

import pytest

import models  # noqa: F401 — register tables before conftest's init_db runs
from dispatch.intent import resolve_intent


def test_mission_prefix_routes_to_ceo():
    intent = resolve_intent("mission: full read on BTC into CPI")
    assert intent.agent == "ceo"
    assert intent.task_type == "mission"
    assert intent.dispatchable


def test_mission_with_forbidden_action_refused():
    intent = resolve_intent("mission: buy the dip on NVDA")
    assert intent.forbidden is True and intent.dispatchable is False
