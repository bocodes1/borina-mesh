"""External provider integrations for the Life-OS tabs.

Every module follows the same contract (see `base.py`):
- reads its credentials from the environment (`.env`),
- NEVER raises out of a public function — failures become a graceful
  `IntegrationResult(connected=False, error=...)`,
- returns `connected=False` with a clear reason when its key is absent,
- so every tab can render a "Connect X" state instead of crashing.

Read-only by design. None of these place orders, move funds, or send
messages. Calendar event *creation* is the single write path and is gated on
an explicit user-initiated flag (see `google_calendar.create_event`).
"""

from .base import IntegrationResult, not_connected, ok, safe  # noqa: F401
