"""Base Agent class + registry — wired to Claude Agent SDK."""

import os
import sys

# Fix Windows cp1252 encoding crash when Claude SDK subprocess emits emoji.
# Must be set before any subprocess is spawned.
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.platform == "win32":
    # Force UTF-8 mode for the current process too
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from typing import ClassVar, AsyncIterator, Optional


class Agent:
    """Base class for all Borina Mesh agents.

    Subclasses must define: id, name, emoji, tagline, system_prompt.
    The default `stream()` uses Claude Agent SDK. Override for custom behavior.
    """
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    emoji: ClassVar[str] = "\U0001F916"
    tagline: ClassVar[str] = ""
    system_prompt: ClassVar[str] = ""
    tools: ClassVar[list[str]] = []
    personality: ClassVar[str] = ""

    @property
    def model(self) -> str:
        from agents.models import resolve_model
        try:
            return resolve_model(self.id)
        except KeyError:
            return "claude-sonnet-4-6"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "emoji": self.emoji,
            "tagline": self.tagline,
            "tools": self.tools,
            "model": self.model,
        }

    def load_memory(self) -> str:
        """Load this agent's memory file from the Obsidian vault."""
        from memory import read_memory
        return read_memory(self.id)

    def effective_system_prompt(self) -> str:
        """Build the full system prompt: personality + memory + system_prompt."""
        parts = []
        if self.personality:
            parts.append(self.personality)
        memory = self.load_memory()
        if memory:
            parts.append(f"## Your Memory\n{memory}")
        parts.append(self.system_prompt)
        return "\n\n".join(parts)

    async def stream(self, prompt: str, job_id: int | None = None) -> AsyncIterator[dict]:
        """Stream a response using Claude Agent SDK.

        Publishes activity events and yields chunks: {"type": str, "content": str}
        """
        from events import bus, ActivityEvent

        await bus.publish(ActivityEvent(
            agent_id=self.id,
            kind="started",
            message=f"{self.name} started: {prompt[:80]}",
            job_id=job_id,
        ))

        try:
            from claude_agent_sdk import query, ClaudeAgentOptions

            options = ClaudeAgentOptions(
                system_prompt=self.effective_system_prompt(),
                model=self.model,
                env={"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            )

            tokens_total = 0
            text_total = 0
            async for message in query(prompt=prompt, options=options):
                tokens_total += self._extract_usage(message)
                text = self._extract_text(message)
                if text:
                    text_total += len(text)
                    yield {"type": "text", "content": text}

            await bus.publish(ActivityEvent(
                agent_id=self.id,
                kind="completed",
                message=f"{self.name} completed ({text_total} chars)",
                job_id=job_id,
            ))
            yield {"type": "done", "content": "", "tokens_used": tokens_total}
        except ImportError:
            await bus.publish(ActivityEvent(
                agent_id=self.id,
                kind="failed",
                message="claude-agent-sdk not installed",
                job_id=job_id,
            ))
            yield {"type": "text", "content": "claude-agent-sdk not installed"}
            yield {"type": "done", "content": ""}
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[agent:{self.id}] FULL ERROR:\n{tb}", file=sys.stderr)
            await bus.publish(ActivityEvent(
                agent_id=self.id,
                kind="failed",
                message=f"Agent error: {e}",
                job_id=job_id,
            ))
            yield {"type": "error", "content": f"Agent error: {e}"}
            yield {"type": "done", "content": ""}

    @staticmethod
    def _extract_text(message) -> Optional[str]:
        """Extract text content from a Claude SDK message."""
        if hasattr(message, "content") and isinstance(message.content, list):
            parts = []
            for block in message.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            return "".join(parts) if parts else None
        if hasattr(message, "text"):
            return message.text
        return None

    @staticmethod
    def _extract_usage(message) -> int:
        """Extract token count from a Claude SDK message."""
        if hasattr(message, "usage"):
            u = message.usage
            return getattr(u, "input_tokens", 0) + getattr(u, "output_tokens", 0)
        return 0


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, type[Agent]] = {}

    def register(self, agent_cls: type[Agent]) -> None:
        if not agent_cls.id:
            raise ValueError("Agent must have an id")
        if agent_cls.id in self._agents:
            raise ValueError(f"Agent '{agent_cls.id}' already registered")
        self._agents[agent_cls.id] = agent_cls

    def get(self, agent_id: str) -> Optional[Agent]:
        cls = self._agents.get(agent_id)
        return cls() if cls else None

    def list(self) -> list[Agent]:
        return [cls() for cls in self._agents.values()]


registry = AgentRegistry()
