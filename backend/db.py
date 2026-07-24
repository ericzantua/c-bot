"""Supabase (Postgres + pgvector) client — C-Bot's single cloud data store.

Uses the service-role key (server-side only; bypasses RLS). The module-level
cache is reused across warm serverless invocations.
"""
from supabase import Client, create_client

import config

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY):
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_SERVICE_KEY not set (see backend/.env)."
            )
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    return _client
