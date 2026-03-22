---
applyTo: "**"
---

# Systematic Debugging

> **Source:** `.skills/systematic-debugging/SKILL.md`
> **Supporting files:** `.skills/systematic-debugging/` (root-cause-tracing.md, defense-in-depth.md, condition-based-waiting.md, find-polluter.sh)

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## The Four Phases

### Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

1. **Read Error Messages Carefully** — Don't skip past errors. Read stack traces completely. Note line numbers, file paths, error codes.
2. **Reproduce Consistently** — Can you trigger it reliably? If not reproducible → gather more data, don't guess.
3. **Check Recent Changes** — Git diff, recent commits, new dependencies, config changes.
4. **Gather Evidence in Multi-Component Systems** — Log what enters/exits each component boundary. Run once to gather evidence showing WHERE it breaks.
5. **Trace Data Flow** — Where does bad value originate? Keep tracing up until you find the source. Fix at source, not at symptom. See `.skills/systematic-debugging/root-cause-tracing.md`.

### Phase 2: Pattern Analysis

1. **Find Working Examples** — Locate similar working code in same codebase.
2. **Compare Against References** — Read reference implementation COMPLETELY, not skim.
3. **Identify Differences** — List every difference, however small.
4. **Understand Dependencies** — What other components, settings, environment does this need?

### Phase 3: Hypothesis and Testing

1. **Form Single Hypothesis** — "I think X is the root cause because Y"
2. **Test Minimally** — SMALLEST possible change, one variable at a time.
3. **Verify Before Continuing** — Didn't work? Form NEW hypothesis. DON'T add more fixes on top.

### Phase 4: Implementation

1. **Create Failing Test Case** — Use TDD skill.
2. **Implement Single Fix** — ONE change at a time. No "while I'm here" improvements.
3. **Verify Fix** — Test passes? No other tests broken?
4. **If 3+ Fixes Failed** — STOP. Question the architecture. Discuss with user before attempting more fixes.

## Red Flags - STOP and Follow Process

- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- Proposing solutions before tracing data flow
- Each fix reveals new problem in different place

**ALL of these mean: STOP. Return to Phase 1.**
