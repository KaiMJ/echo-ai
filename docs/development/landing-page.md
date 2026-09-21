# Landing-page development

The landing page lives in [`frontend/`](../../frontend/README.md). It is a static Next.js App Router site using Tailwind CSS, locally bundled Manrope, and thinking-orbs. Its interactive examples are illustrative sessions, not a connection to a running Echo agent.

## Structure

| Location | Purpose |
| --- | --- |
| `frontend/app/page.tsx` | Page content and links to the user guides |
| `frontend/app/globals.css` | Layout, typography, responsive styles, and motion rules |
| `frontend/components/` | Orb controls, illustrative terminal, and command-copy buttons |
| `frontend/app/layout.tsx` | Page metadata and social image reference |
| `frontend/app/robots.ts`, `sitemap.ts` | Search-engine metadata for the site domain |
| `frontend/public/` | Published assets and Cloudflare response headers |
| `tests/scripts/capture_tui.py` | Synthetic captures rendered through Echo's real terminal UI |

Keep generated `.next/`, `out/`, `.wrangler/`, `node_modules/`, and TypeScript build caches out of Git. The frontend ignore rules already cover these paths. Keep Cloudflare credentials in the environment, not the source or public assets.

## Run and verify

Follow the [frontend setup instructions](../../frontend/README.md) to select the pinned Node.js/pnpm versions and install dependencies. From `frontend/`:

```bash
pnpm dev
```

Before committing site changes, run:

```bash
pnpm typecheck
pnpm build
```

The build exports static files into `frontend/out/`. Use `pnpm preview` to serve that output with Wrangler. Check narrow and wide layouts, keyboard navigation, copy buttons, reduced motion, and links to setup and sandbox documentation when changing the corresponding UI. Keep user-facing links pointed at `docs/guides/`; implementation plans are not setup instructions.

## Capture the terminal UI

From the repository root, after `uv sync --locked`:

```bash
uv run python tests/scripts/capture_tui.py --theme dark --scenario session --output /tmp/echo-session.ansi
uv run python tests/scripts/capture_tui.py --theme light --scenario welcome --output /tmp/echo-welcome.ansi
```

The helper renders a synthetic session at 100 × 28 terminal cells through the real TUI. It uses temporary configuration and does not call a model or load your real credentials or conversation history. The output is an ANSI/VT stream for a terminal renderer, not a PNG. Store intermediate captures outside the repository; add a deliberate asset under `frontend/public/` or `docs/` only when a page uses it. The current landing-page terminal example is a React component and does not consume these captures.

## Deploy

Deployment is a separate operation from building or committing. The existing deploy script builds the site and publishes it to the Cloudflare Pages project `echo-agent`.

Put `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in the repository-root
`.env`, as shown in the [frontend README](../../frontend/README.md#deploy-to-cloudflare-pages).
The `cloudflare` script uses Node's env-file support to load that file for
Wrangler; existing shell variables take precedence. CI can supply them directly
without a local `.env`. No manual exports or browser login are needed when using
a valid API token. From `frontend/`:

```bash
# Once, if the project does not already exist:
pnpm run cloudflare pages project create echo-agent --production-branch main

# Publish the site:
pnpm run deploy
```

The account ID and API token are supplied through `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. Before publishing under a different domain, update the canonical/Open Graph URL in `app/layout.tsx` and the URLs in `app/robots.ts` and `app/sitemap.ts` together.
