"""Computer Use wrapper — drives a real browser via Claude vision + mouse/keyboard.

Uses the Anthropic Computer Use beta. Falls back to a screenshot-only mode
(no action execution) if the host lacks mouse/keyboard control libraries.
"""

import os
import base64
from pathlib import Path
from dataclasses import dataclass
from typing import AsyncIterator


def is_computer_use_available() -> bool:
    """Check if Computer Use dependencies are available."""
    try:
        import anthropic  # noqa
        # pyautogui is the common mouse/keyboard backend
        import pyautogui  # noqa
        return True
    except ImportError:
        return False


@dataclass
class ComputerUseStep:
    """Single step emitted during a Computer Use session."""
    kind: str  # "thinking" | "screenshot" | "action" | "text" | "done"
    content: str
    screenshot_b64: str | None = None


class ComputerUseSession:
    """A single autonomous Computer Use session driving the local display."""

    def __init__(
        self,
        model: str = "claude-opus-4-6",
        display_width: int = 1920,
        display_height: int = 1080,
        display_number: int = 0,
    ):
        self.model = model
        self.display_width = display_width
        self.display_height = display_height
        self.display_number = display_number

    async def run(self, task: str, max_iterations: int = 30) -> AsyncIterator[ComputerUseStep]:
        """Run a Computer Use task autonomously.

        Yields ComputerUseStep events as the session progresses.
        The model sees the screen, decides what to do, executes actions.
        """
        if not is_computer_use_available():
            yield ComputerUseStep(
                kind="text",
                content="Computer Use not available. Install: pip install anthropic pyautogui",
            )
            yield ComputerUseStep(kind="done", content="")
            return

        try:
            from anthropic import Anthropic
        except ImportError:
            yield ComputerUseStep(kind="text", content="anthropic SDK not installed")
            yield ComputerUseStep(kind="done", content="")
            return

        # If ANTHROPIC_API_KEY is unset, the client will fail — Computer Use
        # currently requires direct API access (not the Claude Code subprocess path).
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            yield ComputerUseStep(
                kind="text",
                content="Computer Use requires ANTHROPIC_API_KEY (not supported via Claude CLI subprocess).",
            )
            yield ComputerUseStep(kind="done", content="")
            return

        client = Anthropic(api_key=api_key)

        tools = [
            {
                "type": "computer_20250124",
                "name": "computer",
                "display_width_px": self.display_width,
                "display_height_px": self.display_height,
                "display_number": self.display_number,
            }
        ]

        messages = [{"role": "user", "content": task}]
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            yield ComputerUseStep(kind="thinking", content=f"Iteration {iteration}")

            try:
                response = client.beta.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    tools=tools,
                    messages=messages,
                    betas=["computer-use-2025-01-24"],
                )
            except Exception as e:
                yield ComputerUseStep(kind="text", content=f"API error: {e}")
                yield ComputerUseStep(kind="done", content="")
                return

            # Process response blocks
            tool_use_blocks = []
            for block in response.content:
                if hasattr(block, "text"):
                    yield ComputerUseStep(kind="text", content=block.text)
                elif hasattr(block, "type") and block.type == "tool_use":
                    tool_use_blocks.append(block)
                    yield ComputerUseStep(
                        kind="action",
                        content=f"{block.name}: {block.input}",
                    )

            # Stop condition: no tool use = model is done
            if not tool_use_blocks:
                yield ComputerUseStep(kind="done", content="Session complete")
                return

            # Execute actions and collect results
            tool_results = []
            for tool_use in tool_use_blocks:
                result = await self._execute_action(tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })
                if result and isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict) and item.get("type") == "image":
                            yield ComputerUseStep(
                                kind="screenshot",
                                content="screen captured",
                                screenshot_b64=item.get("source", {}).get("data"),
                            )

            # Append assistant response + tool results for next turn
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            if response.stop_reason == "end_turn":
                yield ComputerUseStep(kind="done", content="Session complete")
                return

        yield ComputerUseStep(kind="done", content=f"Max iterations ({max_iterations}) reached")

    async def _execute_action(self, action: dict) -> list:
        """Execute a single computer action and return result blocks."""
        import pyautogui

        action_type = action.get("action", "")

        try:
            if action_type == "screenshot":
                screenshot = pyautogui.screenshot()
                import io
                buf = io.BytesIO()
                screenshot.save(buf, format="PNG")
                return [{
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(buf.getvalue()).decode("utf-8"),
                    },
                }]
            elif action_type == "left_click":
                coords = action.get("coordinate", [0, 0])
                pyautogui.click(x=coords[0], y=coords[1])
                return [{"type": "text", "text": f"clicked at {coords}"}]
            elif action_type == "type":
                text = action.get("text", "")
                pyautogui.typewrite(text, interval=0.02)
                return [{"type": "text", "text": f"typed: {text[:50]}"}]
            elif action_type == "key":
                key = action.get("text", "")
                pyautogui.press(key)
                return [{"type": "text", "text": f"pressed: {key}"}]
            elif action_type == "mouse_move":
                coords = action.get("coordinate", [0, 0])
                pyautogui.moveTo(coords[0], coords[1])
                return [{"type": "text", "text": f"moved to {coords}"}]
            elif action_type == "scroll":
                coords = action.get("coordinate", [0, 0])
                direction = action.get("scroll_direction", "down")
                amount = action.get("scroll_amount", 3)
                pyautogui.moveTo(coords[0], coords[1])
                pyautogui.scroll(-amount * 100 if direction == "down" else amount * 100)
                return [{"type": "text", "text": f"scrolled {direction} {amount}"}]
            else:
                return [{"type": "text", "text": f"unsupported action: {action_type}"}]
        except Exception as e:
            return [{"type": "text", "text": f"action failed: {e}"}]
