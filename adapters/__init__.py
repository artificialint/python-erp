"""Adapter layer — entry points for callers (PHP shell, desktop UI, etc.).

Adapters are thin: they parse input from the transport layer (stdin, HTTP
request body, function call), invoke the library, and serialise the output
back to the transport layer.

No business logic lives here. If you want to add a rule or compute
something, do it in `erp_engine.modules.<name>` and call from the adapter.
"""
