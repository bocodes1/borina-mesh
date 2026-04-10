"""Base Agent class + registry — wired to Claude Agent SDK."""

import os
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
    model: ClassVar[str] = "claude-opus-4-6"

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

    async def stream(self, prompt: str) -> AsyncIterator[dict]:
        """Stream a response using Claude Agent SDK.

        Yields: {"type": "text|tool_use|done", "content": str}
        """
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            yield {"type": "text", "content": "ANTHROPIC_API_KEY not set in .env"}
            yield {"type": "done", "content": ""}
            return

        try:
            from claude_agent_sdk import query, ClaudeAgentOptions

            options = ClaudeAgentOptions(
                system_prompt=self.system_prompt,
                model=self.model,
            )

            async for message in query(prompt=prompt, options=options):
                text = self._extract_text(message)
                if text:
                    yield {"type": "text", "content": text}

            yield {"type": "done", "content": ""}
        except ImportError:
            yield {"type": "text", "content": "claude-agent-sdk not installed"}
            yield {"type": "done", "content": ""}
        except Exception as e:
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
