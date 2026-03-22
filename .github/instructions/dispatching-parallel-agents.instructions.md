---
applyTo: "**"
---

# Dispatching Parallel Agents

> **Source:** `.skills/dispatching-parallel-agents/SKILL.md`

## When to Use

- 2+ independent tasks that can be worked on without shared state
- Multiple failures across different test files/subsystems
- Each problem can be understood without context from others

## When NOT to Use

- Failures are related (fix one might fix others)
- Need to understand full system state
- Agents would interfere (editing same files, shared resources)

## The Pattern

### 1. Identify Independent Domains
Group failures by what's broken. Each domain = independent.

### 2. Create Focused Agent Tasks
Each agent gets:
- **Specific scope:** One test file or subsystem
- **Clear goal:** Make these tests pass
- **Constraints:** Don't change other code
- **Expected output:** Summary of findings and fixes

### 3. Dispatch in Parallel
All agents run concurrently.

### 4. Review and Integrate
- Read each summary
- Verify fixes don't conflict
- Run full test suite
- Spot check — agents can make systematic errors

## Agent Prompt Structure

1. **Focused** — One clear problem domain
2. **Self-contained** — All context needed
3. **Specific about output** — What should agent return?
4. **Constrained** — "Do NOT change production code" or "Fix tests only"
