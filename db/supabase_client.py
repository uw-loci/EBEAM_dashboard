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

    def insert_status_log(self, timestamp, status):
        """
        Insert a status log entry to the beam_logs table.

        Args:
            timestamp: String timestamp in format "YYYY-MM-DD HH:MM:SS"
            status: Dictionary containing status fields

        Returns:
            Boolean indicating success or failure
        """
        try:
            data, count = self.client.table("beam_logs").insert({
                "experiment_time": timestamp,
                "log_data": status
            }).execute()
            return True
        except Exception as e:
            print(f"Supabase insert error: {e}")
            return False
