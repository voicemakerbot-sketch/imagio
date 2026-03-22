---
applyTo: "**/*.html,**/*.tsx,**/*.jsx,**/*.vue,**/*.svelte,**/*.css,**/*.scss"
---

# UI/UX Pro Max — Design Intelligence

> **Source:** `.skills/ui-ux-pro-max/SKILL.md`
> **Supporting files:** `.skills/ui-ux-pro-max/` (data, scripts — search.py for design system generation)

## When to Apply

- Designing new UI components or pages
- Choosing color palettes and typography
- Reviewing code for UX issues
- Building landing pages or dashboards
- Implementing accessibility requirements

## Workflow

### Step 1: Analyze Requirements
Extract: product type, style keywords, industry, stack.

### Step 2: Generate Design System (REQUIRED)
```bash
python3 .skills/ui-ux-pro-max/scripts/search.py "<product_type> <industry> <keywords>" --design-system [-p "Project Name"]
```

### Step 3: Supplement with Detailed Searches
```bash
python3 .skills/ui-ux-pro-max/scripts/search.py "<keyword>" --domain <domain> [-n <max_results>]
```

### Step 4: Stack Guidelines
```bash
python3 .skills/ui-ux-pro-max/scripts/search.py "<keyword>" --stack html-tailwind
```

## Critical Rules

| Rule | Do | Don't |
|------|----|----|
| Icons | Use SVG (Heroicons, Lucide) | Use emojis as UI icons |
| Hover | Color/opacity transitions | Scale transforms that shift layout |
| Cursor | `cursor-pointer` on all clickable | Default cursor on interactive elements |
| Contrast | 4.5:1 minimum for text | Light gray text on white |
| Touch | 44x44px minimum targets | Tiny tap targets |

## Pre-Delivery Checklist

- [ ] No emojis as icons, consistent icon set
- [ ] All clickable elements have `cursor-pointer`
- [ ] Light/dark mode contrast verified
- [ ] Responsive at 375px, 768px, 1024px, 1440px
- [ ] All images have alt text, form inputs have labels
- [ ] `prefers-reduced-motion` respected
