"""Operator brain — profile read/write/validate + nightly learner. Text-only."""
import pytest

import operator_brain as ob

VALID = """# Operator profile — Bo
_Updated: 2026-06-24 (eod)_

## Active threads
- borina-mesh planner: shipping the learner — last touched 2026-06-24
- store launch: PDP copy — last touched 2026-06-23

## Recurring priorities
- mesh health

## Working rhythms
- deep work mornings

## Preferences
- mornings protected

## Recently completed / closed
- (none)
"""


def test_read_profile_empty_without_vault(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "")
    assert ob.read_profile() == ob.EMPTY_PROFILE


def test_write_rejects_invalid(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    assert ob.write_profile("garbage, no sections") is None
    assert ob.read_profile() == ob.EMPTY_PROFILE  # nothing written


def test_write_then_read_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    p = ob.write_profile(VALID)
    assert p is not None and p.exists()
    assert ob.read_profile() == VALID


def test_count_active_threads():
    assert ob._count_active_threads(VALID) == 2
    assert ob._count_active_threads(ob.EMPTY_PROFILE) == 0
