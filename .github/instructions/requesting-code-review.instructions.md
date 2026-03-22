---
applyTo: "**"
---

# Requesting Code Review

> **Source:** `.skills/requesting-code-review/SKILL.md`
> **Supporting files:** `.skills/requesting-code-review/code-reviewer.md`

## When to Request Review

**Mandatory:**
- After each task in subagent-driven development
- After completing major feature
- Before merge to main

**Optional but valuable:**
- When stuck (fresh perspective)
- Before refactoring (baseline check)
- After fixing complex bug

## How to Request

1. Get git SHAs (base + head)
2. Dispatch code-reviewer subagent using template at `.skills/requesting-code-review/code-reviewer.md`
3. Fill placeholders: `{WHAT_WAS_IMPLEMENTED}`, `{PLAN_OR_REQUIREMENTS}`, `{BASE_SHA}`, `{HEAD_SHA}`, `{DESCRIPTION}`
4. Act on feedback:
   - Fix Critical issues immediately
   - Fix Important issues before proceeding
   - Note Minor issues for later
   - Push back if reviewer is wrong (with reasoning)

## Red Flags — Never

- Skip review because "it's simple"
- Ignore Critical issues
- Proceed with unfixed Important issues
- Argue with valid technical feedback
