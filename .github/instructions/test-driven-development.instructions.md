---
applyTo: "**"
---

# Test-Driven Development (TDD)

> **Source:** `.skills/test-driven-development/SKILL.md`
> **Supporting files:** `.skills/test-driven-development/testing-anti-patterns.md`

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over. No exceptions.

## Red-Green-Refactor

### RED — Write Failing Test
- One minimal test showing what should happen
- One behavior, clear name, real code (no mocks unless unavoidable)

### Verify RED — Watch It Fail (MANDATORY)
- Test fails (not errors)
- Failure message is expected
- Fails because feature missing (not typos)
- **Test passes?** You're testing existing behavior. Fix test.

### GREEN — Minimal Code
- Simplest code to pass the test
- Don't add features, refactor other code, or "improve" beyond the test

### Verify GREEN — Watch It Pass (MANDATORY)
- Test passes, other tests still pass, output pristine

### REFACTOR — Clean Up
- After green only: remove duplication, improve names, extract helpers
- Keep tests green. Don't add behavior.

## When to Use

**Always:** New features, bug fixes, refactoring, behavior changes.

**Exceptions (ask user):** Throwaway prototypes, generated code, configuration files.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Need to explore first" | Fine. Throw away exploration, start with TDD. |
| "TDD will slow me down" | TDD faster than debugging. |
| "Keep as reference" | You'll adapt it. That's testing after. Delete means delete. |

## Red Flags — STOP and Start Over

- Code before test
- Test passes immediately
- Tests added "later"
- "I already manually tested it"
- "This is different because..."

**All of these mean: Delete code. Start over with TDD.**
