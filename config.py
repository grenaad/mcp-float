"""Configuration loaded from environment variables."""

import os


def get_email() -> str:
    """Get Float login email from environment."""
    value = os.environ.get("FLOAT_EMAIL", "")
    if not value:
        raise ValueError("FLOAT_EMAIL environment variable is required")
    return value


def get_password() -> str:
    """Get Float login password from environment."""
    value = os.environ.get("FLOAT_PASSWORD", "")
    if not value:
        raise ValueError("FLOAT_PASSWORD environment variable is required")
    return value


def get_base_url() -> str:
    """Get Float instance base URL from environment."""
    return os.environ.get("FLOAT_BASE_URL", "https://justsolve-solutions.float.com")


def get_session_cache_path() -> str:
    """Get path for session cache file."""
    return os.environ.get(
        "FLOAT_SESSION_CACHE",
        os.path.join(os.path.expanduser("~"), ".float-session.json"),
    )
