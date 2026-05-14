import os
import logging
import sys
from pathlib import Path

logger = logging.getLogger("SystemValidation")

def validate_environment():
    """Run strict startup checks to ensure stability (Phase 1)."""
    logger.info("Running environment validation checks...")
    
    # Check LLM API Keys
    groq_key = os.getenv("GROQ_API_KEY")
    or_key = os.getenv("OPENROUTER_API_KEY")
    
    if not groq_key and not or_key:
        logger.error("CRITICAL: Neither GROQ_API_KEY nor OPENROUTER_API_KEY is set in the environment.")
        logger.error("Please add an API key to the .env file. The assistant cannot function without an LLM.")
        sys.exit(1)
        
    if groq_key and "your_" in groq_key.lower():
        logger.error("CRITICAL: GROQ_API_KEY contains a placeholder ('your_'). Please provide a real key.")
        sys.exit(1)

    # Check Google Workspace Credentials
    root = Path(__file__).resolve().parent.parent
    cred_path = root / "data" / "credentials.json"
    
    if not cred_path.exists():
        logger.warning(
            "WARNING: Google Workspace 'credentials.json' not found in data/. "
            "Google integrations (Gmail, Calendar, Docs, Sheets) will fail."
        )
    else:
        logger.info("Google Workspace credentials found.")
        
    logger.info("Environment validation passed.")
