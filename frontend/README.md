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
