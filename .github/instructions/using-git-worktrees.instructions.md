---
applyTo: "**"
---

# Using Git Worktrees

> **Source:** `.skills/using-git-worktrees/SKILL.md`

## When to Use

Starting feature work that needs isolation from current workspace, or before executing implementation plans.

## Directory Selection (Priority Order)

1. Check existing: `.worktrees/` (preferred) or `worktrees/`
2. Check project docs for preference
3. Ask user

## Safety Verification

**MUST verify directory is git-ignored before creating project-local worktree:**
```bash
git check-ignore -q .worktrees 2>/dev/null
```
If NOT ignored → add to .gitignore + commit → then proceed.

## Creation Steps

1. Detect project name: `basename "$(git rev-parse --show-toplevel)"`
2. Create worktree: `git worktree add <path> -b <branch-name>`
3. Run project setup (auto-detect from package.json/requirements.txt/etc.)
4. Verify clean baseline — run tests
5. Report location + test results

## Red Flags — Never

- Create worktree without verifying it's ignored (project-local)
- Skip baseline test verification
- Proceed with failing tests without asking
- Assume directory location when ambiguous
