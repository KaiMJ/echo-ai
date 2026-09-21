# Private Google tools example

The ignored `local-dev/examples/google_smoke_test.py` development example signs into Google, saves your authorization, discovers spreadsheets in Drive, and reads spreadsheet tab metadata. It does not modify Google data or display spreadsheet contents.

**Availability:** this personal example is not included in a fresh clone or the installed package. The commands below apply only to a checkout that already has it.

**Current status:** the example works independently of Echo. Google agent tools and `echo-ai google auth/status/disconnect` are planned, not available commands. You do not need to start a model or run Docker for this example.

## 1. Prepare your Google Cloud project

You need a Google account, a checkout of this repository, Python 3.12+, and [uv](https://docs.astral.sh/uv/). Run the commands below from the checkout root.

In [Google Cloud Console](https://console.cloud.google.com/):

1. Create or select your own project.
2. Under **APIs & Services**, enable **Google Drive API** and **Google Sheets API**.
3. Configure **Google Auth Platform → Branding** with an app name, support email, and developer contact information.
4. Under **Audience**, choose External for a personal Gmail account. While the app is in Testing, add the Google account you will sign in with to **Test users**.
5. Under **Clients**, create an OAuth client with application type **Desktop app** and download its JSON file.

If you already have Desktop credentials, confirm both APIs and your test user are configured in the same project. You do not need a service account, a manually configured web redirect URL, or a published app for this personal test. See Google's [Sheets Python quickstart](https://developers.google.com/workspace/sheets/api/quickstart/python).

Each user supplies their own Cloud project and client file. Do not use or distribute another contributor's credentials.

## 2. Configure local files

Store the downloaded JSON outside the checkout, for example at:

```text
~/.config/echo-ai/google/credentials.json
```

Create that directory if needed and move your downloaded file into it. Add these lines to your checkout's `.env` (create `.env` if it does not exist; preserve any existing settings):

```dotenv
GOOGLE_CREDENTIALS_FILE=~/.config/echo-ai/google/credentials.json
GOOGLE_TOKEN_FILE=~/.local/share/echo-ai/google/token.json
```

The example loads the root `.env`, expands `~`, and lets existing shell environment variables take precedence. These settings configure the example; the main Echo runtime does not yet consume them.

**The token file does not exist yet.** Google supplies the client credentials only. The example creates the token file and its parent directory after you complete browser login. Do not create an empty token file.

Existing development setups can keep their private files in `local-dev/`:

```dotenv
GOOGLE_CREDENTIALS_FILE=local-dev/google_credentials.json
GOOGLE_TOKEN_FILE=local-dev/google_token.json
```

The example resolves relative paths from the checkout root. When the variables are unset, those `local-dev/` paths are its fallback defaults. `.env` and `local-dev/` are ignored by Git. Keep credential and token JSON files private regardless of where you store them; `.gitignore` does not remove files already tracked by Git.

## 3. Check configuration and sign in

```bash
uv run --script local-dev/examples/google_smoke_test.py --check-config
uv run --script local-dev/examples/google_smoke_test.py
```

`uv` installs the example's dependencies into an isolated script environment; it does not change Echo's project dependencies. The first command checks local configuration without contacting Google. The second opens a browser and waits up to three minutes for you to sign in and approve access.

The example requests permission to read Drive file metadata and read/write Sheets, matching the planned integration. **The example itself makes only read requests.** If you do not want to grant those permissions, cancel consent. See Google's [Drive scope guide](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

Run this on the same machine as your browser. If automatic browser opening fails, use `--no-browser` and open the printed link on that machine. This flag alone does not configure OAuth for a remote server.

Successful output includes:

```text
PASS: OAuth token saved with owner-only permissions.
PASS: Drive API responded; found 10 spreadsheets in the first page.
PASS: Sheets API responded; spreadsheet has 3 tabs (names and data hidden).
Smoke test complete. No Google data was changed.
```

Counts vary by account. The example inspects the first spreadsheet returned by Drive unless you select one explicitly:

```bash
uv run --script local-dev/examples/google_smoke_test.py --spreadsheet-id YOUR_SPREADSHEET_ID
```

The ID is the segment between `/d/` and `/edit` in a spreadsheet URL. If Drive finds no spreadsheets, the example reports that the Sheets check was skipped. Create a blank spreadsheet in Google Sheets and run again with its ID.

## Returning later

Run the same command again. The example reuses the saved token and refreshes expired access tokens when possible. Keep the token private: it contains authorization to access your account.

External apps in Testing receive refresh tokens that expire after seven days for these scopes. Reauthenticate when needed:

```bash
uv run --script local-dev/examples/google_smoke_test.py --reauth
```

Tokens can also be revoked or expire for other reasons. Publishing an app is not required for this test and does not guarantee permanent tokens. See Google's [token expiration documentation](https://developers.google.com/identity/protocols/oauth2#expiration).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Credentials file missing | Check `GOOGLE_CREDENTIALS_FILE`; point it at the downloaded JSON, not its directory. |
| Client is not a Desktop app | Download a Desktop OAuth client; service-account or Web application credentials do not fit this example. |
| Access blocked during consent | Sign in with an account listed under Audience → Test users. A Workspace organization may also restrict third-party apps. |
| Google API HTTP 403 | Verify both APIs are enabled in the credentials' project, consent was granted, and the account can access the selected file. |
| Token expired, revoked, or missing scopes | Run with `--reauth` and grant the requested permissions. |
| No spreadsheet found | Create a blank spreadsheet or use `--spreadsheet-id` with a file accessible to the signed-in account. |
| Browser callback times out | Rerun on the browser's machine and finish consent within three minutes. |

To disconnect, remove the app's access in your [Google Account connections](https://myaccount.google.com/connections), then delete the local file configured by `GOOGLE_TOKEN_FILE`. Deleting the local file alone does not revoke the authorization at Google. Keep the downloaded client file if you want to reconnect later.

For implementation details and planned agent tools, see [Google tools integration](google-tools-integration.md).
