# Echo landing page

Next.js App Router, Tailwind CSS, locally bundled Manrope, and [thinking-orbs](https://github.com/Jakubantalik/thinking-orbs). Exports a static site for Cloudflare Pages. Terminal sessions on the page are explicitly illustrative, not a live agent connection.

## Local development

Uses Node.js 26.9.0 (the latest stable Current release at setup) through nvm, and pnpm 12.5.1. The versions are pinned in `.nvmrc` and `package.json`.

```bash
cd frontend
nvm install
nvm use
npm install --global pnpm@12.5.1
pnpm install --frozen-lockfile
pnpm dev
```

## Cloudflare

Provide `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` with **Account → Cloudflare Pages → Edit** permissions, then

```bash
pnpm exec wrangler pages project create echo-agent --production-branch main
pnpm run deploy
```
