import type { StreamChunk } from "./types";

/** Stream an agent chat response via Server-Sent Events. */
export async function streamChat(
  agentId: string,
  prompt: string,
  onChunk: (chunk: StreamChunk) => void,
): Promise<void> {
  const response = await fetch(`/api/chat/${agentId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`Stream error ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6);
        try {
          const chunk = JSON.parse(data) as StreamChunk;
          onChunk(chunk);
          if (chunk.type === "done") return;
        } catch {
          // ignore parse errors on keepalive pings
        }
      }
    }
  }
}
