---
applyTo: "**"
---

# Finishing a Development Branch

> **Source:** `.skills/finishing-a-development-branch/SKILL.md`

## When to Use

Implementation is complete, all tests pass, and you need to decide how to integrate the work.

## The Process

### Step 1: Verify Tests
Run project's test suite. If tests fail — STOP, fix first.

### Step 2: Determine Base Branch
```bash
git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null
```

### Step 3: Present Options

```
Implementation complete. What would you like to do?

1. Merge back to <base-branch> locally
2. Push and create a Pull Request
3. Keep the branch as-is (I'll handle it later)
4. Discard this work

Which option?
```

### Step 4: Execute Choice

- **Option 1:** Checkout base → pull → merge → verify tests → delete feature branch
- **Option 2:** Push → `gh pr create` with summary + test plan
- **Option 3:** Report and preserve
- **Option 4:** Confirm first ("Type 'discard' to confirm"), then delete

### Step 5: Cleanup Worktree (for options 1, 2, 4)
