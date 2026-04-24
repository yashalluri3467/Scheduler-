import json
import os

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from env import BASE_DIR, get_env, load_dotenv, resolve_path

SCOPES = ["https://www.googleapis.com/auth/calendar"]

load_dotenv()

DEFAULT_CREDS_FILE = BASE_DIR / "credentials.json"
DEFAULT_TOKEN_FILE = BASE_DIR / "token.json"


def _load_client_config() -> dict:
    raw_config = get_env("GOOGLE_OAUTH_CLIENT_SECRETS_JSON") or get_env(
        "GOOGLE_CLIENT_SECRETS_JSON"
    )
    if raw_config:
        return json.loads(raw_config)

    config_file = resolve_path(
        get_env("GOOGLE_OAUTH_CLIENT_SECRETS_FILE")
        or get_env("GOOGLE_CLIENT_SECRETS_FILE")
    )
    if config_file and config_file.exists():
        with config_file.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    if DEFAULT_CREDS_FILE.exists():
        with DEFAULT_CREDS_FILE.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    raise FileNotFoundError(
        "Missing Google OAuth client secrets. Set GOOGLE_OAUTH_CLIENT_SECRETS_FILE "
        "or GOOGLE_OAUTH_CLIENT_SECRETS_JSON in .env, or place credentials.json next "
        "to auth.py."
    )


def _load_token_creds() -> Credentials | None:
    raw_token = get_env("GOOGLE_OAUTH_TOKEN_JSON") or get_env("GOOGLE_TOKEN_JSON")
    if raw_token:
        return Credentials.from_authorized_user_info(json.loads(raw_token), SCOPES)

    token_file = resolve_path(
        get_env("GOOGLE_OAUTH_TOKEN_FILE") or get_env("GOOGLE_TOKEN_FILE")
    )
    if token_file and token_file.exists():
        return Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if DEFAULT_TOKEN_FILE.exists():
        return Credentials.from_authorized_user_file(str(DEFAULT_TOKEN_FILE), SCOPES)

    return None


def get_credentials() -> Credentials:
    creds = _load_token_creds()

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if os.getenv("VERCEL"):
                raise RuntimeError(
                    "Google OAuth token is missing in Vercel. Set GOOGLE_OAUTH_TOKEN_JSON "
                    "or GOOGLE_TOKEN_JSON as a Vercel environment variable."
                )
            client_config = _load_client_config()
            if "installed" in client_config or "web" in client_config:
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            else:
                raise ValueError(
                    "Google OAuth client secrets must include an 'installed' or 'web' block."
                )
            creds = flow.run_local_server(port=0, prompt="consent")

        token_file = resolve_path(
            get_env("GOOGLE_OAUTH_TOKEN_FILE") or get_env("GOOGLE_TOKEN_FILE")
        )
        if token_file is None:
            token_file = DEFAULT_TOKEN_FILE

        token_file.parent.mkdir(parents=True, exist_ok=True)
        with token_file.open("w", encoding="utf-8") as fh:
            fh.write(creds.to_json())

    return creds
