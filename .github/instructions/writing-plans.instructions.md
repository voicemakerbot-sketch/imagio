---
applyTo: "**"
---

# Writing Plans

> **Source:** `.skills/writing-plans/SKILL.md`

## When to Use

When you have a spec or requirements for a multi-step task, before touching code.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" — step
- "Run it to make sure it fails" — step
- "Implement the minimal code to make the test pass" — step
- "Run the tests and make sure they pass" — step
- "Commit" — step

## Plan Document Header

Every plan MUST start with:

```markdown
# [Feature Name] Implementation Plan

**Goal:** [One sentence describing what this builds]
**Architecture:** [2-3 sentences about approach]
**Tech Stack:** [Key technologies/libraries]
```

## Task Structure

Each task must include:
- **Files:** Create/Modify/Test with exact paths
- **Steps:** With exact code, exact commands, expected output
- **Commit:** After each task

## Save Location

`docs/plans/YYYY-MM-DD-<feature-name>.md`

## Remember

- Exact file paths always
- Complete code in plan (not "add validation")
- Exact commands with expected output
- DRY, YAGNI, TDD, frequent commits

## Execution Handoff

After saving the plan, offer:
1. **Subagent-Driven (this session)** — dispatch fresh subagent per task
2. **Parallel Session (separate)** — open new session with executing-plans
