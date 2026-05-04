"""Constants for the Katja Schedule integration."""
import hashlib

DOMAIN = "katja_schedule"
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes

CONF_API_URL = "api_url"
CONF_API_TOKEN = "api_token"
CONF_SCAN_INTERVAL = "scan_interval"


def stable_id(api_url: str, suffix: str) -> str:
    """Generate a unique_id that survives config entry deletion/re-creation."""
    url_hash = hashlib.md5(api_url.encode()).hexdigest()[:8]
    return f"ks_{url_hash}_{suffix}"
