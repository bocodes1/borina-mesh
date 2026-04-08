"""Base Agent class + registry."""

from typing import ClassVar, AsyncIterator, Optional


class Agent:
    """Base class for all Borina Mesh agents.

    Subclasses must define: id, name, emoji, tagline, system_prompt.
    Override `run()` or `stream()` for custom behavior.
    """
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    emoji: ClassVar[str] = "\U0001F916"
    tagline: ClassVar[str] = ""
    system_prompt: ClassVar[str] = ""
    tools: ClassVar[list[str]] = []  # List of allowed tool names

    def to_dict(self) -> dict:
        """Return public-safe dict (no system prompt)."""
        return {
            "id": self.id,
            "name": self.name,
            "emoji": self.emoji,
            "tagline": self.tagline,
            "tools": self.tools,
        }

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """Stream a response token by token. Override in subclass.

        Yields dicts with shape: {"type": "text|tool_use|done", "content": ...}
        """
        yield "Base agent has no implementation"


class AgentRegistry:
    """In-memory registry of available agents."""

    def __init__(self):
        self._agents: dict[str, type[Agent]] = {}

    def register(self, agent_cls: type[Agent]) -> None:
        """Register an agent class. Raises if duplicate id."""
        if not agent_cls.id:
            raise ValueError("Agent must have an id")
        if agent_cls.id in self._agents:
            raise ValueError(f"Agent '{agent_cls.id}' already registered")
        self._agents[agent_cls.id] = agent_cls

    def get(self, agent_id: str) -> Optional[Agent]:
        """Get an instance of an agent by id, or None if not found."""
        cls = self._agents.get(agent_id)
        return cls() if cls else None

    def list(self) -> list[Agent]:
        """List all registered agents as instances."""
        return [cls() for cls in self._agents.values()]


# Global registry (populated by agent modules on import)
registry = AgentRegistry()
