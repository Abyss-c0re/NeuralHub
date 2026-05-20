from .headless_runner import HeadlessAgentRunner

__all__ = ["HeadlessAgentRunner"]

# The official extension points for people writing richer runners are the
# protected methods on HeadlessAgentRunner:
#
#   _iter_agent_events(...)   – the shared async generator that drives the agent
#   _handle_event(...)        – per-event hook called for every yielded event
#   _stop_bridge()            – hook for graceful WebSocket bridge shutdown
#
# They are not in __all__ (standard Python convention for _ names) but are
# intentionally public, stable, and documented on the class.
# See NeuralVoid's HeadlessAgentRunner for a real-world subclass example.
