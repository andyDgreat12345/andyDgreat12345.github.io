# Personal Website

A personal site to track projects and achievements. Built with [Astro](https://astro.build), deploys as a static site to GitHub Pages.

## Run locally

```bash
npm install      # first time only
npm run dev      # start dev server → http://localhost:4321
```

## Add content

- **A project:** copy any file in `src/content/projects/` and edit the fields at the top (`title`, `summary`, `repo`, `website`, `tags`, `featured`).
- **An achievement:** copy any file in `src/content/achievements/`.
- **Your identity / links:** edit the constants at the top of `src/pages/index.astro`.
- **About page:** edit `src/pages/about.astro`.

Files are auto-picked-up — no code changes needed to add entries.

## Build

```bash
npm run build    # outputs static site to ./dist
npm run preview  # preview the production build
```

## Deploy to GitHub Pages

1. Create a GitHub repo and push this folder.
2. If the repo is **not** named `<username>.github.io`, set `base: '/<repo-name>'`
   in `astro.config.mjs`.
3. Add the GitHub Actions workflow (see project setup notes) and enable Pages
   under repo Settings → Pages → Source: GitHub Actions.
