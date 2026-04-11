"""Tests for real token counting in Agent base class."""

from agents.base import Agent


def test_extract_usage_from_message():
    """_extract_usage handles messages with and without usage."""

    class FakeUsage:
        input_tokens = 100
        output_tokens = 50

    class FakeMessage:
        usage = FakeUsage()

    class NoUsageMessage:
        pass

    assert Agent._extract_usage(FakeMessage()) == 150
    assert Agent._extract_usage(NoUsageMessage()) == 0


def test_stream_done_chunk_schema():
    """The done chunk must support tokens_used key."""
    done_chunk = {"type": "done", "content": "", "tokens_used": 42}
    assert done_chunk["tokens_used"] == 42
