// Turns a growing text buffer of Server-Sent Events into parsed events.
// Returns the complete events and the unfinished rest of the buffer.
export function parseSSE(buffer) {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop();
  const events = [];
  for (const block of blocks) {
    let event = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) continue;
    try {
      events.push({ event, data: JSON.parse(data) });
    } catch {
      // ignore a malformed event instead of breaking the whole stream
    }
  }
  return { events, rest };
}
