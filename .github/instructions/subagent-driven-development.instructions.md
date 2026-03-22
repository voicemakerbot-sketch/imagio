---
applyTo: "**"
---

# Subagent-Driven Development

> **Source:** `.skills/subagent-driven-development/SKILL.md`
> **Supporting files:** `.skills/subagent-driven-development/` (implementer-prompt.md, spec-reviewer-prompt.md, code-quality-reviewer-prompt.md)

## When to Use

- Have implementation plan with independent tasks
- Want to stay in current session
- Fresh subagent per task + two-stage review

## The Process

For each task:
1. **Dispatch implementer subagent** (using `.skills/subagent-driven-development/implementer-prompt.md`)
2. If subagent asks questions → answer, then re-dispatch
3. Subagent implements, tests, commits, self-reviews
4. **Dispatch spec reviewer** (`.skills/subagent-driven-development/spec-reviewer-prompt.md`) — confirms code matches spec
5. If spec issues → implementer fixes → re-review until ✅
6. **Dispatch code quality reviewer** (`.skills/subagent-driven-development/code-quality-reviewer-prompt.md`)
7. If quality issues → implementer fixes → re-review until ✅
8. Mark task complete

After all tasks: dispatch final code reviewer → use finishing-a-development-branch skill.

## Red Flags — Never

- Skip reviews (spec compliance OR code quality)
- Proceed with unfixed issues
- Dispatch multiple implementation subagents in parallel
- Start code quality review before spec compliance is ✅
- Move to next task while either review has open issues
