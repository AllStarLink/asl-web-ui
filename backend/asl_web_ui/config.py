"""Settings for asl-web-ui itself, read from /etc/asl-web-ui/asl-web-ui.ini."""

import configparser
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("/etc/asl-web-ui/asl-web-ui.ini")


@dataclass(frozen=True)
class Settings:
    allow_insecure_http: bool = False
    log_level: str = "info"
    # Path under which the web server publishes the UI (cookie path).
    url_prefix: str = "/asl-web-ui"
    auth_socket: str = "/run/asl-web-ui-auth/auth.sock"
    login_group: str = "asl-web-ui"
    # "Keep me signed in": absolute and idle limits, in seconds.
    keep_max_age: int = 30 * 86400
    keep_idle: int = 7 * 86400
    # Normal sessions.
    session_max_age: int = 8 * 3600
    session_idle: int = 30 * 60
    # Password re-entry window for destructive actions.
    recent_auth: int = 10 * 60
    # Asterisk configuration directory, and where snapshots and the audit
    # log are kept (the service's StateDirectory).
    config_dir: str = "/etc/asterisk"
    state_dir: str = "/var/lib/asl-web-ui"
    # Set only by --dev; never read from the settings file.
    dev: bool = False


def load(path: Path = DEFAULT_PATH) -> Settings:
    """Read settings; a missing file or missing keys fall back to defaults."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)  # silently ignores a missing file
    return Settings(
        allow_insecure_http=parser.getboolean("web", "allow_insecure_http", fallback=False),
        log_level=parser.get("logging", "level", fallback="info").lower(),
    )
