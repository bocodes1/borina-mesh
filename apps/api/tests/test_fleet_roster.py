"""Fleet roster — lean-fleet states, id-space bridge, routing + scheduling gates."""
import pytest

import fleet_roster as fr
from dispatch.intent import resolve_intent


@pytest.fixture(autouse=True)
def _seed(tmp_path, monkeypatch):
    # Hermetic: seed the roster into the test DB (conftest provides the engine).
    from db import engine
    fr.seed_roster(engine)
    yield


def test_seed_is_idempotent():
    from db import engine
    fr.seed_roster(engine)
    n2 = fr.seed_roster(engine)        # second run adds nothing
    assert n2 == 0


def test_decided_states():
    assert fr.get_state("trader") == fr.ACTIVE
    assert fr.get_state("inbox-triage") == fr.ACTIVE
    assert fr.get_state("ceo") == fr.ACTIVE
    assert fr.get_state("researcher") == fr.ACTIVE
    assert fr.get_state("adset-optimizer") == fr.PARKED
    assert fr.get_state("ecommerce-scout") == fr.PARKED
    assert fr.get_state("qa_director") == fr.RETIRED


def test_short_alias_bridges_to_long_id():
    # get_state accepts the intent short alias too.
    assert fr.get_state("scout") == fr.PARKED          # scout -> ecommerce-scout
    assert fr.get_state("adset") == fr.PARKED


def test_routable_rules():
    assert fr.is_routable("trader") is True
    assert fr.is_routable("scout", direct=False) is False   # parked, keyword off
    assert fr.is_routable("scout", direct=True) is True      # parked, explicit on
    assert fr.is_routable("qa_director", direct=True) is False # retired, never


def test_parked_agent_not_keyword_routed():
    # "scout some products" keyword would have routed to scout; parked → fall
    # through to the general researcher instead.
    intent = resolve_intent("scout some winning ecommerce products")
    assert intent.agent == "researcher"
    assert intent.source == "fallback"


def test_parked_agent_still_directly_addressable():
    intent = resolve_intent("adset: review my roas")
    assert intent.agent == "adset"
    assert intent.dispatchable is True


def test_unmatched_keyword_falls_through_to_researcher():
    intent = resolve_intent("what are the prediction market odds today")
    assert intent.agent == "researcher"      # no specialist claims it
    assert intent.dispatchable is True


def test_active_agent_routes_normally():
    intent = resolve_intent("how's the trading bot health")
    assert intent.agent == "trader"
    assert intent.dispatchable is True


def test_set_state_changes_routing():
    fr.set_state("ecommerce-scout", fr.ACTIVE)
    assert fr.is_routable("scout", direct=False) is True
    fr.set_state("ecommerce-scout", fr.PARKED)


def test_active_scheduled_filter():
    defaults = {"trader": "*/30 * * * *", "qa_director": "0 8 * * *",
                "adset-optimizer": "0 17 * * *", "ceo": "0 7 * * *"}
    active = fr.active_scheduled_agents(defaults)
    assert "trader" in active and "ceo" in active
    assert "qa_director" not in active   # retired
    assert "adset-optimizer" not in active     # parked


def test_list_roster_excludes_retired():
    roster = fr.list_roster()
    ids = {r["id"] for r in roster}
    assert "trader" in ids and "ecommerce-scout" in ids
    assert "polymarket-intel" not in ids and "qa_director" not in ids
    # active sorts first
    assert roster[0]["state"] == fr.ACTIVE
