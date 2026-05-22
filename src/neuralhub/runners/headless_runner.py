from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Tuple

from neuralcore import Agent, Logger
from ..bridge.websocket import WebSocketBridge

logger = Logger.get_logger()


class HeadlessAgentRunner:
    """
    Headless runner with bidirectional WebSocket support.

    This is the canonical implementation (moved from NeuralVoid).
    Rich clients (such as NeuralVoid's CLI runner) subclass this and
    override presentation logic while reusing the core driver.

    Extension points intended for subclass authors
    ----------------------------------------------
    _iter_agent_events(prompt, system_prompt, max_tokens, temperature=None)
        Async generator that yields every (event, payload) from the underlying
        agent. Handles stop_event creation, optional WebSocketBridge startup,
        and guaranteed cleanup. This is the main method to consume when you
        want custom event handling.

    _handle_event(event_type, payload)
        Called for every event yielded by the agent (after _iter_agent_events).
        Default implementation forwards to ``agent.on_background_event`` if present.

    _stop_bridge()
        Hook called during cleanup. Override to perform graceful shutdown
        (e.g. ``await self._bridge.stop()``) instead of just task cancellation.

    _write_status(status, **kwargs)
        Write to the status file. The rich CLI version replaces this with
        a much more detailed throttled writer.
    """

    def __init__(
        self,
        agent: Agent,
        status_file: str | Path | None = None,
        pid_file: str | Path | None = None,
        websocket_port: int = 8765,
        status_update_throttle_sec: float = 1.0,
        skip_bridge: bool = False,
        app_root: Path | None = None,
    ):
        self.agent = agent
        self.app_root = app_root or getattr(agent, "app_root", None) or Path.cwd()

        # Default status/pid paths relative to the app root for cleanliness
        default_status = self.app_root / ".neuralvoid" / f"{agent.agent_id}.status.json"
        default_pid = self.app_root / ".neuralvoid" / f"{agent.agent_id}.pid"

        self.status_path = Path(status_file).resolve() if status_file else default_status.resolve()
        self.pid_path = Path(pid_file).resolve() if pid_file else default_pid.resolve()

        self.websocket_port = websocket_port
        self.throttle_sec = status_update_throttle_sec
        self._skip_bridge = skip_bridge

        self._last_status_write: float = 0.0
        self._running = False
        self._success = False
        self._start_time: Optional[datetime] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._bridge: Optional[WebSocketBridge] = None
        self._bridge_task: Optional[asyncio.Task] = None

    def _write_status(self, status: str, **kwargs):
        # Minimal status writer for now
        try:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"status": status, "agent": self.agent.agent_id, **kwargs}
            self.status_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _write_pid(self):
        try:
            self.pid_path.parent.mkdir(parents=True, exist_ok=True)
            self.pid_path.write_text(str(os.getpid()))
        except Exception:
            pass

    async def _handle_event(self, event_type: str, payload: Any) -> None:
        """Extension point for subclasses.

        Called for every event yielded by the underlying agent.
        Base implementation forwards to the agent's optional
        ``on_background_event`` hook (used by some workflows/hub coordination).
        """
        if hasattr(self.agent, "on_background_event"):
            try:
                await getattr(self.agent, "on_background_event")(event_type, payload)
            except Exception:
                pass

    async def _stop_bridge(self) -> None:
        """Hook for graceful shutdown of the WebSocket bridge.

        The base implementation does nothing beyond the task cancellation
        already performed in ``_iter_agent_events``. Rich subclasses
        (e.g. NeuralVoid's CLI runner) override this to perform an orderly
        ``await self._bridge.stop()``.
        """
        pass

    async def _iter_agent_events(
        self,
        prompt: Optional[str] = None,
        system_prompt: str = "",
        max_tokens: int = 12000,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[Tuple[str, Any]]:
        """
        Shared core driver for both minimal and rich runners.

        Responsibilities (single source of truth):
          - Ensure a stop_event exists (reuses one if the caller already created it
            for signal handlers, etc.)
          - Start the optional WebSocketBridge + its background task
          - Yield every (event_type, payload) from the underlying Agent.run(...)
          - Guarantee bridge task cancellation on exit (via finally)
        """
        if self._stop_event is None:
            self._stop_event = asyncio.Event()

        if not self._skip_bridge:
            self._bridge = WebSocketBridge(
                agent=self.agent, port=self.websocket_port
            )
            self._bridge_task = asyncio.create_task(self._bridge.start())

        try:
            async for event_type, payload in self.agent.run(
                user_prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                chat_mode=False,
                stop_event=self._stop_event,
            ):
                yield event_type, payload
        finally:
            # Best-effort cleanup of the bridge task + hook for graceful stop.
            if self._bridge_task and not self._bridge_task.done():
                self._bridge_task.cancel()
            await self._stop_bridge()

    async def run(
        self,
        prompt: Optional[str] = None,
        system_prompt: str = "",
        max_tokens: int = 12000,
    ) -> bool:
        """Run the agent headless. Returns True on success."""
        self._start_time = datetime.utcnow()
        self._write_pid()
        self._write_status("starting", prompt=prompt)

        try:
            self._write_status("running")
            self._success = True
            async for event_type, payload in self._iter_agent_events(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                # temperature left as None → agent default
            ):
                if self._stop_event.is_set():
                    self._success = False
                    break
                if event_type in ("error", "cancelled", "reflection_stuck"):
                    self._success = False
                # Give subclasses / hooks a chance to react to every event
                await self._handle_event(event_type, payload)
            self._write_status("finished", success=self._success)
            return self._success
        except asyncio.CancelledError:
            logger.info(f"Headless run cancelled for {self.agent.agent_id}")
            self._success = False
            self._write_status("cancelled")
            return False
        except Exception as e:
            logger.error(f"Headless run failed for {self.agent.agent_id}: {e}")
            self._write_status("error", error=str(e))
            return False
        finally:
            self._write_status("stopped")

            # Ensure the agent's internal background manager (watchers, training jobs, etc.)
            # is shut down. This prevents orphaned background processes after Ctrl+C or normal exit.
            try:
                if hasattr(self.agent, "shutdown"):
                    # Run shutdown in a best-effort way if we're in a finally
                    asyncio.create_task(self.agent.shutdown())
            except Exception:
                pass

            # Bridge cleanup now lives inside _iter_agent_events (its finally)
