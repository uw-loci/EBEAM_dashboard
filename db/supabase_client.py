"""Supabase client for logging beam status data."""
from supabase import ClientOptions, create_client
import os
import sys
from dotenv import load_dotenv


def _safe_console_write(message):
    stream = getattr(sys, "__stdout__", None)
    if stream is None:
        return
    try:
        stream.write(f"{message}\n")
        stream.flush()
    except Exception:
        pass


class SupabaseClient:
    """Supabase client for database operations."""

    def __init__(self, timeout_seconds=3.0):
        """Initialize the Supabase client with credentials from .env file."""
        load_dotenv()
        url = os.getenv("SUPABASE_API_URL")
        key = os.getenv("SUPABASE_API_KEY")

        if not url or not key:
            raise ValueError("SUPABASE_API_URL and SUPABASE_API_KEY must be set in .env file")

        options = ClientOptions(postgrest_client_timeout=timeout_seconds)
        self.client = create_client(url, key, options=options)
        _safe_console_write("Connected to Supabase")

    def insert_status_log(self, status):
        """
        Insert a status log entry to the short_term_logs table.

        Args:
            status: Dictionary containing status fields

        Returns:
            Boolean indicating success or failure
        """
        try:
            response = self.client.table("short_term_logs").insert({
                "data": status
            }).execute()
            return True
        except Exception as e:
            _safe_console_write(f"Supabase insert error: {e}")
            return False
