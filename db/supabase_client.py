"""Supabase client for logging beam status data."""
from supabase import create_client
import os
from dotenv import load_dotenv


class SupabaseClient:
    """Supabase client for database operations."""

    def __init__(self):
        """Initialize the Supabase client with credentials from .env file."""
        load_dotenv()
        url = os.getenv("SUPABASE_API_URL")
        key = os.getenv("SUPABASE_API_KEY")

        if not url or not key:
            raise ValueError("SUPABASE_API_URL and SUPABASE_API_KEY must be set in .env file")

        self.client = create_client(url, key)
        print("Connected to Supabase")

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
            print(f"Supabase insert error: {e}")
            return False
