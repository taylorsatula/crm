# Phase Implementation Planning Pattern

A structured approach for planning implementation phases using red/green TDD.

---

## Phase 1: Initial Understanding

### 1.1 Explore the Codebase

Launch exploration agents to understand:

1. **Current structure**: What exists in relevant directories
2. **Established patterns**: How existing code handles similar concerns
3. **Actual interfaces**: Real method names, parameters, return types
4. **Test patterns**: Fixtures, helpers, organization in `tests/`
5. **Schema reality**: Actual table/column names vs spec assumptions

### 1.2 Identify Discrepancies

Create a reconciliation table:

| Spec Says | Actual Code/Schema | Action |
|-----------|-------------------|--------|
| `contacts` table | `customers` table | Use actual naming |
| `execute_one()` | `execute_single()` | Use actual method |

### 1.3 Clarify with User

Ask targeted questions for ambiguous points:
- Naming conflicts (spec vs schema)
- Missing dependencies
- Scope boundaries

---

## Phase 2: Design

### 2.1 Map Dependencies

Create a dependency graph showing:
- What must exist before each component
- Parallel vs sequential implementation paths
- Integration points between components

Example:
```
PostgresClient (exists) ─┐
                         ├─► AuditLogger
VaultClient (exists) ────┤
                         ├─► LLMClient ─► AttributeExtractor
```

### 2.2 Define Implementation Order

Order components by:
1. **Foundation first**: Utilities with no dependencies
2. **Models next**: Pure data structures (Pydantic)
3. **Services in dependency order**: Base → derived → integration

### 2.3 Specify Test-First Approach

For each component, list:
- Test file location
- Test classes/methods to write
- Key assertions (what behavior to verify)
- Then: implementation approach

---

## Phase 3: Write the Plan

### Plan File Structure

```markdown
# Phase N: [Name] - TDD Implementation Plan

## Schema vs Spec Corrections
[Reconciliation table from Phase 1]

## Implementation Order (Red/Green TDD)

### Phase N.0: Foundation Utilities
[For each utility:]
- Tests: `tests/path/test_file.py`
  - [List test cases]
- Implementation: [Brief description]

### Phase N.1: Domain Models
[Table of models with key tests]

### Phase N.2: Core Services
[Dependency diagram]
[For each service: test cases first]

## Critical Files
[Table of files to reference during implementation]

## Verification Checklist
- Unit test commands
- Integration test scenarios
- Data integrity checks

## Implementation Notes
[Key insights, gotchas, patterns to follow]
```

---

## Phase 4: Implementation (TDD Cycle)

### For Each Component:

1. **RED**: Write failing tests first
   ```bash
   pytest tests/path/test_file.py -v
   # All tests should FAIL (or error on import)
   ```

2. **GREEN**: Implement minimum code to pass
   ```bash
   pytest tests/path/test_file.py -v
   # All tests should PASS
   ```

3. **REFACTOR**: Clean up while tests stay green

### Track Progress

Use todo list with states:
- `pending`: Not started
- `in_progress`: Currently working (only ONE at a time)
- `completed`: Tests passing, implementation done

---

## Key Principles

### 1. Explore Before Planning
Never assume spec matches reality. Read actual code first.

### 2. Reconcile Discrepancies Explicitly
Document every difference between spec and implementation.

### 3. Test Cases Before Implementation
List specific test scenarios before writing any production code.

### 4. Dependency-Ordered Implementation
Build from bottom up - foundations before features.

### 5. One Component at a Time
Complete RED→GREEN→REFACTOR cycle before moving on.

### 6. Verify Integration Points
After each service, run integration tests that exercise dependencies.

---

## Example Planning Prompts

### For Exploration Agent:
```
Explore the current codebase structure to understand patterns established in previous phases. Focus on:
1. Directory structure - what exists under [relevant dirs]
2. How [ClientName] works - especially [relevant methods]
3. Test patterns used - fixtures, helpers
4. The existing schema for [relevant tables]

Return specific file paths and key code patterns.
```

### For Plan Agent:
```
Design a red/green TDD implementation plan for Phase N based on these findings:

**Key Schema Facts:**
- [List actual table/column names]
- [List actual method signatures]

**Missing Components to Create:**
- [List new files needed]

**Test Structure:**
- [Existing test patterns]

Design:
1. What to implement first (dependencies)
2. For each module: tests to write first, then implementation
3. How to handle spec vs schema differences
4. Critical integration points
```

---

## Verification Checklist Template

### Unit Tests
```bash
pytest tests/[module]/test_[component].py -v
```

### Integration Tests
- [ ] [End-to-end flow 1]
- [ ] [End-to-end flow 2]
- [ ] [Cross-component interaction]

### Data Integrity
- [ ] [Constraint 1 enforced]
- [ ] [Constraint 2 enforced]
- [ ] [RLS working correctly]
