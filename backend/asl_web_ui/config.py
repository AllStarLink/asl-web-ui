"""Settings for asl-web-ui itself, read from /etc/asl-web-ui/asl-web-ui.ini."""

import configparser
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("/etc/asl-web-ui/asl-web-ui.ini")


@dataclass(frozen=True)
class Settings:
    allow_insecure_http: bool = False
    log_level: str = "info"


def load(path: Path = DEFAULT_PATH) -> Settings:
    """Read settings; a missing file or missing keys fall back to defaults."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)  # silently ignores a missing file
    return Settings(
        allow_insecure_http=parser.getboolean("web", "allow_insecure_http", fallback=False),
        log_level=parser.get("logging", "level", fallback="info").lower(),
    )
