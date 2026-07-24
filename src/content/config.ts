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

// Each debate writeup = one Markdown file in src/content/debate/
// PUBLIC by design: method, system design, and retrospective results only.
// Never put live competitive prep (current-topic cases/blocks) here.
const debate = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    summary: z.string(),
    order: z.number().default(999),
    date: z.coerce.date().optional(),
    // 'method' = how the system works · 'results' = a retrospective round story
    kind: z.enum(['method', 'results']).default('method'),
    tags: z.array(z.string()).default([]),
  }),
});

export const collections = { projects, debate };
