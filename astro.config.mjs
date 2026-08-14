// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// For GitHub Pages.
// - If your repo is named `<username>.github.io`, keep `base` as '/'.
// - If your repo has any other name (e.g. `personal-website`), set
//   base: '/personal-website' and update `site` accordingly.
export default defineConfig({
  site: 'https://andydgreat12345.github.io',
  base: '/',
  // Generates sitemap-index.xml so search engines can discover every page,
  // minus the operational ones — /hq is internal state, not public content.
  integrations: [sitemap({ filter: (page) => !/\/hq\/?$/.test(page) })],
});
