"""Streamed chat answers (owner request 2026-11-19: "i want the chat answers
streamed. line by line. we wait too long").

Route: POST /kb/chat/stream — same request body as POST /kb/chat (which is
unchanged). Response: `text/event-stream` (SSE). Every event is one
`data: <json>\\n\\n` frame, the JSON being exactly one of:

  {"type": "delta", "text": "<raw text chunk>"}
      Append to the bubble. RAW model text: {{myphoto:Pn}} handles, unchecked
      links etc. may appear — they are only resolved in `done`.
  {"type": "reset"}
      Discard everything streamed so far (Claude Max died mid-answer and the
      metered-API fallback is answering instead). Deltas may follow.
  {"type": "done", "reply": "...", "mode": "...", "mode_switched": bool,
   ["private_notes": [...]], ["private_stripped": n]}
      Final. Exactly the dict POST /kb/chat returns, plus "type". `reply` is
      the full POST-PROCESSED text (photos rendered, links validated) and is
      authoritative — REPLACE the streamed text with it.
  {"type": "error", "status": 400|502|500, "detail": "<readable message>"}
      Final. Same messages /kb/chat would put in its HTTPException detail.

Errors detectable before any model work (unknown model, nothing left after
private stripping) are still plain HTTP 400 JSON responses, as on /kb/chat.

Context assembly is NOT here: the route calls the same `run_kb_chat` as
/kb/chat with an `on_delta` callback, so the context is identical by
construction. The blocking call runs in a worker thread; deltas cross to the
event loop through an asyncio.Queue, so the loop is never blocked. If the
client disconnects, the next delta raises inside the worker, which aborts
the Ollama read / kills the Claude CLI child.

Which providers truly stream: local (Ollama, token deltas; leading <think>
hidden like the non-stream path) and max:* (Claude CLI
--include-partial-messages). Metered Anthropic / OpenAI / Bedrock answer
non-streamed and arrive as ONE delta, then `done`.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import AsyncIterator, Callable


class StreamCancelled(Exception):
    """Raised inside the worker when the HTTP client has gone away."""


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def stream_chat_events(
    work: Callable[[Callable[[str | None], None]], dict],
    error_of: Callable[[Exception], tuple[int, str] | None],
) -> AsyncIterator[str]:
    """Runs `work(on_delta)` in a thread and yields SSE frames: deltas as the
    worker pushes them, then `done` (work's returned dict) or `error`.
    `error_of` maps a raised exception to (status, detail); None means
    unexpected (reported as status 500 with the exception text)."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    cancelled = threading.Event()

    def put(item: tuple) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def on_delta(text: str | None) -> None:
        if cancelled.is_set():
            raise StreamCancelled()
        if text is None:
            put(("reset", None))
        elif text:
            put(("delta", text))

    def run() -> None:
        try:
            put(("done", work(on_delta)))
        except StreamCancelled:
            put(("cancelled", None))
        except Exception as e:  # noqa: BLE001 — every failure becomes an error event
            put(("error", e))

    worker = loop.run_in_executor(None, run)
    try:
        while True:
            kind, value = await queue.get()
            if kind == "delta":
                yield sse({"type": "delta", "text": value})
            elif kind == "reset":
                yield sse({"type": "reset"})
            elif kind == "done":
                yield sse({"type": "done", **value})
                break
            elif kind == "error":
                mapped = error_of(value)
                status, detail = mapped if mapped else (500, f"{type(value).__name__}: {value}")
                yield sse({"type": "error", "status": status, "detail": detail})
                break
            else:
                break
    finally:
        # Normal end or client disconnect (generator closed): stop the worker
        # at its next delta. We don't await it — it finishes on its own.
        cancelled.set()
        worker.add_done_callback(lambda f: f.exception())
