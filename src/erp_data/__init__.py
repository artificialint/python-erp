"""erp_data — caller-side data layer for the ERP.

Persistence (SQLAlchemy + SQLite), Excel import/export, permission queries, and
the module manifest registry. Used by the desktop caller (and any future Python
caller). It has NO dependency on ``erp_engine`` — CONTRACT_v1 §8.1: the
deterministic engine never opens a DB. Callers use ``erp_data`` to resolve data,
then hand a resolved CONTRACT_v1 payload to the engine.
"""
