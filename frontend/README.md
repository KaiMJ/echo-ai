# Echo landing page

Static Next.js landing page for Echo. See the [landing-page development guide](../docs/development/landing-page.md) for structure, checks, terminal captures, and deployment.

## Local development

From the repository root, use the Node.js and pnpm versions pinned in `.nvmrc` and `package.json`:

```bash
cd frontend
nvm install
nvm use
npm install --global pnpm@12.5.1
pnpm install --frozen-lockfile
pnpm dev
```

## Deploy to Cloudflare Pages

Add your deployment credentials to the repository-root `.env` (one directory
above `frontend/`):

```dotenv
CLOUDFLARE_API_TOKEN=your-api-token
CLOUDFLARE_ACCOUNT_ID=your-account-id
```

Then, from `frontend/`:

```bash
pnpm run deploy
```

The command builds the site, loads the root `.env` for Wrangler, and deploys to
`echo-agent`. No manual export or browser login is needed with a valid token.
Existing shell variables take precedence; a missing `.env` is allowed for CI.
The build step does not load the root `.env` through this wrapper.

Use `pnpm run cloudflare whoami` to check authentication, or
`pnpm run cloudflare --help` to see Wrangler commands with the same env loading.
