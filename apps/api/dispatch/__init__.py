"""Autonomous Telegram dispatch (spec §8b): intent routing + agent dispatch.

Security model: this package is only ever reached for messages that already
passed the webhook's secret-token + allow-list checks. It maps a free-text
message to a registered *research/intel* agent and never to a write action —
forbidden intents are refused here, not executed.
"""
