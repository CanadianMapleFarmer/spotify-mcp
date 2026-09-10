import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "spotify-mcp"
SCOPES = (
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-library-read",
    "user-top-read",
    "user-read-recently-played",
    "user-read-private",
)


class SettingsError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    redirect_uri: str = DEFAULT_REDIRECT_URI
    config_dir: Path = DEFAULT_CONFIG_DIR

    @classmethod
    def from_env(cls, *, require_credentials: bool = True) -> "Settings":
        client_id = os.environ.get("SPOTIFY_CLIENT_ID") or ""
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET") or ""
        if require_credentials:
            missing = [
                name
                for name, value in (("SPOTIFY_CLIENT_ID", client_id), ("SPOTIFY_CLIENT_SECRET", client_secret))
                if not value
            ]
            if missing:
                raise SettingsError(
                    f"Missing required environment variable(s): {', '.join(missing)}. "
                    "Set them and re-run, e.g. `export SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=...`."
                )
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI") or DEFAULT_REDIRECT_URI,
            config_dir=Path(os.environ.get("SPOTIFY_MCP_CONFIG_DIR") or str(DEFAULT_CONFIG_DIR)).expanduser(),
        )

    @property
    def token_path(self) -> Path:
        return self.config_dir / "token.json"

    @property
    def callback(self) -> tuple[str, int, str]:
        u = urlparse(self.redirect_uri)
        return u.hostname or "127.0.0.1", u.port or 80, u.path or "/"
