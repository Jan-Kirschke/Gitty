from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import os


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 5555
    max_clients: int = 100
    timeout: float = 300.0
    log_file: Optional[str] = "gitty_server.log"
    log_level: str = "INFO"
    ping_interval: int = 30
    ping_timeout: int = 10


@dataclass
class ClientConfig:
    host: str = "127.0.0.1"
    port: int = 5555
    default_username: Optional[str] = None
    encryption_key: Optional[str] = None
    auto_reconnect: bool = False
    reconnect_interval: int = 5
    connection_timeout: float = 10.0


def load_env_config(prefix: str = "GITTY_") -> dict:
    return {
        k.replace(prefix, "").lower(): v
        for k, v in os.environ.items()
        if k.startswith(prefix)
    }


def get_default_config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    else:
        base = Path.home() / ".config"
    return base / "gitty"


def ensure_config_dir() -> Path:
    config_dir = get_default_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir
