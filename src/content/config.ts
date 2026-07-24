import { defineCollection, z } from 'astro:content';

// Each project = one Markdown file in src/content/projects/
const projects = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    summary: z.string(),
    // Lower order number shows first (1, 2, 3, ...)
    order: z.number().default(999),
    date: z.coerce.date().optional(),
    // Links
    repo: z.string().url().optional(),      // GitHub repo URL
    website: z.string().url().optional(),   // attached live site
    // Presentation
    tags: z.array(z.string()).default([]),
    featured: z.boolean().default(false),
  }),
});

export const collections = { projects };
