# /// script
# requires-python = ">=3.12"
# dependencies = ["gspread>=6,<7", "google-auth-oauthlib>=1,<2", "google-api-python-client>=2,<3", "python-dotenv>=1,<2"]
# ///
"""Local OAuth and read-only API smoke test. Run with uv run --script."""

import argparse
import json
import os
import tempfile
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parents[1]
# Match the proposed integration grant; this script performs no API writes.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]


def save_token(path, credentials):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".google-token-")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(credentials.to_json())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-config", action="store_true", help="Check local files only; no login or network")
    parser.add_argument("--no-browser", action="store_true", help="Print the login link instead of opening a browser")
    parser.add_argument("--spreadsheet-id", help="Existing spreadsheet to inspect; otherwise use the first discovered sheet")
    parser.add_argument("--reauth", action="store_true", help="Request fresh consent; replace token only after success")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    paths = []
    for variable, filename in [
        ("GOOGLE_CREDENTIALS_FILE", "google_credentials.json"),
        ("GOOGLE_TOKEN_FILE", "google_token.json"),
    ]:
        path = Path(os.environ.get(variable) or str(ROOT / "scripts" / filename)).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        paths.append(path)
    client_path, token_path = paths
    if client_path.resolve() == token_path.resolve():
        raise ValueError("Credentials and token paths must differ.")
    if not client_path.is_file():
        raise ValueError("Credentials file missing; set GOOGLE_CREDENTIALS_FILE in the root .env.")
    client = json.loads(client_path.read_text())
    if not all(client.get("installed", {}).get(key) for key in ("client_id", "client_secret", "auth_uri", "token_uri")):
        raise ValueError("Download OAuth credentials for a Desktop app (installed client).")
    print("PASS: Desktop OAuth credentials found (contents hidden).")
    print(f"Token file: {'present' if token_path.is_file() else 'absent; it will be created after login'}")
    if args.check_config:
        print("Configuration check complete. Cloud API enablement and consent are not checked yet.")
        return

    credentials = None
    if token_path.is_file() and not args.reauth:
        credentials = Credentials.from_authorized_user_file(str(token_path))
        if not credentials.has_scopes(SCOPES):
            raise ValueError("Saved token lacks required scopes. Run again with --reauth.")
        if not credentials.valid and credentials.refresh_token:
            credentials.refresh(Request())
    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
        print("Sign in on this machine and approve the requested scopes. Waiting up to 180 seconds.", flush=True)
        credentials = flow.run_local_server(
            port=0, open_browser=not args.no_browser, timeout_seconds=180,
            prompt="consent", access_type="offline",
        )
    if not credentials.has_scopes(SCOPES):
        raise ValueError("Required scopes were not granted. Run again with --reauth.")
    save_token(token_path, credentials)
    print("PASS: OAuth token saved with owner-only permissions.")

    with build("drive", "v3", credentials=credentials) as drive:
        result = drive.files().list(
            pageSize=10,
            q="trashed = false and mimeType = 'application/vnd.google-apps.spreadsheet'",
            fields="files(id)",
        ).execute(num_retries=0)
    files = result.get("files", [])
    print(f"PASS: Drive API responded; found {len(files)} spreadsheets in the first page.")
    spreadsheet_id = args.spreadsheet_id or (files[0]["id"] if files else None)
    if not spreadsheet_id:
        print("SKIP: No spreadsheet found. Create a blank sheet or supply --spreadsheet-id to test Sheets.")
        return
    sheets = gspread.authorize(credentials)
    sheets.set_timeout(30)
    spreadsheet = sheets.open_by_key(spreadsheet_id)
    tabs = spreadsheet.worksheets()
    print(f"PASS: Sheets API responded; spreadsheet has {len(tabs)} tabs (names and data hidden).")
    print("Smoke test complete. No Google data was changed.")


if __name__ == "__main__":
    try:
        main()
    except RefreshError:
        raise SystemExit("Authorization expired or revoked. Run again with --reauth.") from None
    except HttpError as error:
        raise SystemExit(
            f"Google API HTTP {error.resp.status}. Check API enablement, consent scopes, and file access in the credentials' Cloud project."
        ) from None
    except (OSError, ValueError) as error:
        # Do not echo JSON fragments or OAuth responses containing credentials.
        if isinstance(error, json.JSONDecodeError):
            raise SystemExit("Invalid JSON in credentials or token file.") from None
        raise SystemExit(str(error)) from None
    except Exception as error:  # noqa: BLE001 -- avoid leaking OAuth responses in tracebacks
        raise SystemExit(f"Smoke test failed ({type(error).__name__}); check connection, consent, and API enablement.") from None
