"""Base Agent class + registry — wired to Claude Agent SDK."""

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

    @property
    def model(self) -> str:
        from agents.models import resolve_model
        return resolve_model(self.id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "emoji": self.emoji,
            "tagline": self.tagline,
            "tools": self.tools,
            "model": self.model,
        }

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
                system_prompt=self.system_prompt,
                model=self.model,
            )

            text_total = 0
            async for message in query(prompt=prompt, options=options):
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
            yield {"type": "done", "content": ""}
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
