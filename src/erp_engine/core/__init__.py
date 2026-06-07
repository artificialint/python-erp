"""Shared core utilities — Excel readers, rule engine primitives, output emitters.

Anything shared across modules lives here. Module-specific logic must NOT
land in `core/` — that is the over-abstraction trap Codex flagged. Promote
to `core/` only when a second module needs the same primitive.
"""
