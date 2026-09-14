from agents.context_pack import build_context_pack, ContextPack, adaptive_query


def test_adaptive_query_appends_titles():
    q = adaptive_query("daily plan", ["Ship the learner", "Renew passport"], ["Standup"])
    assert q.startswith("daily plan ")
    assert "Ship the learner" in q and "Renew passport" in q and "Standup" in q


def test_adaptive_query_dedupes_and_caps():
    q = adaptive_query("prefix", ["A", "B", "A"], ["C", "D", "E"], limit=3)
    terms = q.split(" ", 1)[1].split(" ")
    assert terms == ["A", "B", "C"]  # dedup'd, capped at limit, in order


def test_adaptive_query_falls_back_to_bare_prefix_when_nothing_to_add():
    assert adaptive_query("operator profile day recap") == "operator profile day recap"
    assert adaptive_query("operator profile day recap", [], None) == "operator profile day recap"


def test_pack_includes_data_and_last_artifact_and_is_stable(monkeypatch):
    # No vault → recall returns "" (OBSIDIAN_VAULT_PATH unset in conftest).
    p1 = build_context_pack("researcher", query="ai research", data="BTC 60k",
                            last_artifact="Yesterday: covered X")
    assert isinstance(p1, ContextPack)
    assert "BTC 60k" in p1.text
    assert "Yesterday: covered X" in p1.text
    # signal_hash is stable across calls with identical meaningful inputs
    p2 = build_context_pack("researcher", query="ai research", data="BTC 60k",
                            last_artifact="Yesterday: covered X")
    assert p1.signal_hash == p2.signal_hash
    # different data → different signal
    p3 = build_context_pack("researcher", query="ai research", data="BTC 61k",
                            last_artifact="Yesterday: covered X")
    assert p3.signal_hash != p1.signal_hash


def test_empty_inputs_give_empty_signal():
    p = build_context_pack("trader", query="", data="", last_artifact="")
    assert p.signal_hash == ContextPack.EMPTY_SIGNAL
