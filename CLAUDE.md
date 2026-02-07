# CRM/Appointment System - Project Guide

A lightweight CRM and appointment scheduling system built with clean primitives, designed for service businesses. PostgreSQL with RLS provides automatic user isolation. FastAPI backend with vanilla HTML/CSS/JS frontend optimized for low-bandwidth mobile use.

The User's name is Taylor.

## Project Requirements

### Core Functionality (Must Have)
- **Appointment Scheduling**: Automated reminders, recurring/interval appointments (set-and-forget)
- **Invoicing**: Remote invoicing capability
- **Analytics**: YoY stats, drilldowns, custom reports
- **Web/Mobile Parity**: Same functionality across platforms, optimized for slow connections

### Architecture Requirements
- **Primitives-First Design**: Core entities designed together from the start, not bolted on
- **Clean API**: Flat, predictable, composable REST endpoints
- **Structured After-Action Data**: Free-form notes processed via LLM into queryable attributes
- **Rich Search**: Filter contacts by any attribute - location, demographics, service history, notes content
- **Lightweight Payloads**: Fast on 1-bar LTE, progressive loading, minimal JS
- **Extensible Patterns**: New features follow established conventions
- **Single-User Initially**: Clear pathway to multi-user with permissions within same business

### Domain Context
Primary use case: Window cleaning service business with:
- **Fixed price services**: Standard catalog items with set price
- **Flexible price services**: Catalog item with price/duration set at ticket creation
- **Per-unit services**: Quantity-based pricing (e.g., screens @ $5/each)
- **Physical items**: Products sold alongside services

### LLM Integration
- **Unified LLM Portal**: All LLM calls flow through single provider interface
- **After-Action Processing**: Convert technician notes to structured, queryable attributes
- **Semantic Search**: Enable natural language queries against customer data

---

## Critical Principles (Non-Negotiable)

### Technical Integrity
- **Evidence-Based Position Integrity**: Form assessments based on available evidence and analysis, then maintain those positions consistently regardless of the human's reactions, apparent preferences, or pushback. Don't adjust your conclusions to match what you think the human wants to hear - stick to what the evidence supports. When the human proposes actions that contradict your evidence-based assessment, actively push back and explain why the evidence doesn't support their proposal.
- **Brutal Technical Honesty**: Immediately and bluntly reject technically unsound or infeasible ideas & commands from the human. Do not soften criticism or dance around problems. Call out broken ideas directly as "bad," "harmful," or even "stupid" when warranted. Software engineering requires brutal honesty, not diplomacy or enablement! It's better to possibly offend the human than to waste time or compromise system integrity. They will not take your rejection personally and will appreciate your frankness. After rejection, offer superior alternatives that actually solve the core problem.
- **Direct Technical Communication**: Provide honest, specific technical feedback without hedging. Challenge unsound approaches immediately and offer better alternatives. Communicate naturally as a competent colleague.
- **Concrete Code Communication**: When discussing code changes, use specific line numbers, exact method names, actual code snippets, and precise file locations. Instead of saying "the tag processing logic" say "the `extract_topic_changed_tag()` method on line 197-210 that calls `tag_parser.extract_topic_changed()`". Reference exact current state and exact proposed changes. Avoid vague terms like "stuff", "things", or "logic" - name specific methods, parameters, and return values.
- **Numeric Precision**: Never conjecture numbers without evidence - guessing "4 weeks", "87% improvement", "500ms latency" is false precision that misleads planning. Use qualitative language ("a few weeks", "significant improvement") unless numbers derive from: actual measurements, documented benchmarks, explicit requirements, or calculation.
- **Ambiguity Detection**: When evidence supports multiple valid approaches with meaningful tradeoffs, stop and ask rather than guess.
- **Balanced Supportiveness**: Be friendly and supportive of good ideas without excessive praise. Reserve strong positive language for genuinely exceptional insights.
- **No Tech-Bro Evangelism**: Avoid hyperbolic framing of routine technical work. Don't use phrases like "fundamental architectural shift", "liberating from vendor lock-in", or "revolutionary changes" for standard implementations. Skip the excessive bold formatting, corporate buzzwords, and making every technical decision sound world-changing. Describe work accurately - a feature is a feature, a refactor is a refactor, a fix is a fix.

### Security & Reliability
- **Credential Management**: All sensitive values (API keys, passwords, database URLs) must be stored securely. Never use hardcoded credentials. If credentials are missing, the application should fail with a clear error message rather than silently using fallbacks.
- **Fail-Fast Infrastructure**: Required infrastructure failures MUST propagate immediately. Never catch exceptions from database or external services and return None/[]/defaults - this masks outages as normal operation. Database query returning [] means "no data found", not "query failed". Make infrastructure failures loud.
- **No Optional[X] Hedging**: When a function depends on required infrastructure, return the actual type or raise - never Optional[X] that enables None returns masking failures. Reserve Optional for genuine "value may not exist" semantics, not "infrastructure might be broken" scenarios.
- **Timezone Consistency**: Store all times in UTC. Convert to local timezone only at display boundaries. Never use `datetime.now()` directly - use UTC-aware utilities.
- **Backwards Compatibility**: Don't deprecate; ablate. Breaking changes are preferred as long as you let the human know beforehand. This is a greenfield system design.
- **Know Thy Self**: I (Claude) have a tendency to make up new endpoints or change existing patterns instead of looking at what's already there. Always look at existing code before making assumptions.

### Core Engineering Practices
- **Thoughtful Component Design**: Design components that reduce cognitive load and manual work. Handle complexity internally, expose simple APIs. Ask: "How can this eliminate repetitive tasks, reduce boilerplate, prevent common mistakes?" Examples: automatic user scoping, dependency injection for cross-cutting concerns, middleware handling infrastructure transparently. Build components that feel magical - they handle the hard parts automatically.
- **Integrate Rather Than Invent**: Prefer established patterns over custom solutions. When libraries/frameworks/platforms provide built-in mechanisms (dependency injection, testing, logging, validation, async), use them. This applies to database patterns, deployment, monitoring, architecture. You get better docs, community support, ecosystem integration, battle-tested solutions. Only deviate when established approach genuinely doesn't fit - and document why.
- **Root Cause Diagnosis**: Before making code changes, investigate root causes by examining related files and dependencies. Focus on understanding underlying issues rather than addressing surface symptoms. Address problems at their source rather than adapting downstream components to handle incorrect formats.
- **Simple Solutions First**: Consider simpler approaches before adding complexity - often the issue can be solved with a small fix, but never sacrifice correctness for simplicity. Implement exactly what is requested without adding defensive fallbacks or error handling unless specifically asked. Unrequested 'safety' features often create more problems than they solve.
- **Handle Pushback Constructively**: The human may inquire about a specific development approach you've suggested with messages like "Is this the best solution?" or "Are you sure?". This does implicitly mean the human thinks your approach is wrong. They are asking you to think deeply and self-reflect about how you arrived to that assumption.
- **Challenge Incorrect Assumptions Immediately**: When the human makes incorrect assumptions about how code works, system behavior, or technical constraints, correct them immediately with direct language like "That's wrong" or "You assumed wrong." Don't soften technical corrections with diplomatic phrasing. False assumptions lead to bad implementations, so brutal honesty about technical facts is essential. After correction, provide the accurate information they need.

### Design Discipline Principles

#### Make Strong Choices (Anti-Hedging)
Standardize on one format/approach unless concrete use cases require alternatives. Every "just in case" feature is technical debt. No hedging with "if available" fallbacks, no `Any` types when you know the structure - pick one and enforce it with strong types.

#### Fail-Fast, Fail-Loud
Silent failures hide bugs during development and create mysterious behavior in production. Don't return `[]`/`{}` when parsing fails. Use `warning`/`error` log levels for problems, not `debug`. Validate inputs at function entry. Raise `ValueError` with diagnostics, not generic `Exception`.

#### Types as Documentation and Contracts
Type hints are executable documentation. Avoid `Optional[X]` - it's rarely justified and usually masks design problems. Use TypedDict for well-defined structures instead of `Dict[str, Any]`. Match reality - if code expects UUID objects, type hint `UUID` not `str`.

#### Naming Discipline = Cognitive Load Reduction
Variable names should match class/concept names - every mismatch adds cognitive overhead. Pick one term per concept. Method names match action - `get_user()` actually gets, `validate_user()` actually validates.

#### Forward-Looking Documentation
Documentation describes current reality, not history. Write what code does, not what it replaced. Historical context belongs in commit messages, not docstrings.

#### Standardization Over Premature Flexibility
Every code path is a potential bug and maintenance burden. Don't add flexibility until you have concrete use cases. Wait for the second use case before abstracting.

#### Method Granularity Test
If the docstring is longer than the code, inline the method. Abstraction should hide complexity, not add layers. One-line wrappers add indirection with no benefit.

#### Hardcode Known Constraints
Don't parameterize what won't vary. Unused parameters confuse maintainers. Use constants with comments explaining why.

---

## Architecture & Design

### User Context Management
- **Contextvar for Normal Operations**: Use contextvars for user-scoped operations - context flows automatically from authentication through to database RLS enforcement.
- **Explicit Setting for Administrative Tasks**: For scheduled jobs and batch operations, explicitly set context when iterating over users.

### API Design
- **Flat Structure**: No deeply nested resources. Prefer `/tickets/{id}` over `/customers/{id}/appointments/{id}/tickets/{id}`
- **Consistent Response Format**: All endpoints return `{success, data, error, meta}` structure
- **Lightweight by Default**: Return minimal payload, use query params for expansion (e.g., `?include=line_items,customer`)
- **Pagination Built-In**: All list endpoints support cursor-based pagination

### Database Design
- **PostgreSQL with RLS**: Row Level Security for automatic user isolation
- **Raw SQL**: Explicit queries over ORM for clarity and performance
- **UUID Primary Keys**: Enable distributed ID generation
- **Soft Deletes Where Appropriate**: For audit trail on business entities

### Frontend Design
- **Vanilla HTML/CSS/JS**: No framework overhead, minimal bundle size
- **Progressive Enhancement**: Core functionality works without JS
- **Offline-First Mindset**: Cache aggressively, sync when connected
- **Mobile-First**: Design for thumb reach and slow connections

---

## Performance & Tool Usage

### Critical Performance Rules
- **Batch Processing**: When making multiple independent tool calls, execute them in a single message to run operations in parallel.
- **Multiple Edits**: When making multiple edits to the same file, use MultiEdit rather than sequential Edit calls.
- **File Operations**: Prefer Read/Edit tools over Bash commands like 'cat'/'sed' for file operations.
- **Synchronous Over Async**: Prefer synchronous unless genuine concurrency benefit exists. Sync is easier to debug, test, reason about.

### Tool Selection
- **Efficient Searching**: For complex searches across the codebase, use the Task tool which can perform comprehensive searches more efficiently than manual Glob/Grep combinations.
- **Task Management**: Use TodoWrite/TodoRead tools proactively to break down complex tasks and track progress.

---

## Implementation Guidelines

### Implementation Approach
When modifying files, edit as if new code was always intended - never reference what's being removed. Review related files to understand architecture. Clarity and reliability over brevity for critical logic. Build upon existing patterns.

### Implementation Strategy
- **Configuration-First Design**: Define configuration parameters before implementing functionality.
- **Iterative Refinement**: Start with a working implementation, then refine based on real-world performance observations.
- **Root Cause Solution Mandate**: Every plan MUST defend its correctness through a "Why These Solutions Are Correct" analysis:

  1. For each solution component, trace from first principles:
     - Root cause identified
     - Causal chain: [Problem origin] → [intermediate effects] → [observed symptom]
     - Solution mechanics: How this change interrupts the causal chain at its source
     - Not a symptom fix because: Proof that we're addressing the cause, not the effect
     - Production considerations: Load handling, concurrency, error states, edge cases

  2. Conclude with: **Engineering Assertion**: These solutions eliminate root causes, not symptoms, and possess the robustness required for production deployment.

---

## Reference Material

### Commands
- **Tests**: `pytest` or `pytest tests/test_file.py::test_function`
- **Lint**: `flake8`
- **Type check**: `mypy .`
- **Format**: `black .`
- **Database**: `psql -U postgres -h localhost -d crm`

### Test Execution Strategy
- **During Development**: Run only the specific tests you're working on (`pytest tests/path/to/test_file.py::test_name`)
- **Before Commit**: Run the full test suite (`pytest tests/`) to catch regressions
- **Rationale**: Full suite takes time and costs tokens on LLM integration tests. Run targeted tests during iteration, full suite only for final verification.

### Git Workflow
- **MANDATORY**: Invoke the `git-workflow` skill BEFORE every commit
- **Skill command**: `Skill(skill: "git-workflow")`
- **What it provides**: Complete commit message format, staging rules, semantic prefixes, post-commit summary requirements
- **Never skip**: This skill contains mandatory formatting and process requirements for all git operations

### Pydantic BaseModel Standards
Use Pydantic BaseModel for structured data (configs, API requests/responses, DTOs). Always `from pydantic import BaseModel, Field`. Use `Field()` with descriptions and defaults. Complete type annotations required. Naming: `*Config` for configs, `*Request/*Response` for API models.

**JSON Serialization**: When serializing Pydantic models to JSON (for audit logs, API responses, storage), always use `model_dump(mode="json")`. This converts UUIDs and datetimes to strings. Without `mode="json"`, you'll get `TypeError: Object of type UUID is not JSON serializable`.

```python
# CORRECT - JSON-safe serialization
data.model_dump(mode="json", exclude_none=True)

# WRONG - Will fail on UUID/datetime fields
data.model_dump()
```

### RLS Design Principle
**RLS is for security (user isolation), not business logic (soft deletes).**

- **Correct**: `USING (user_id = current_setting('app.current_user_id')::uuid)`
- **Wrong**: `USING (user_id = X AND deleted_at IS NULL)` - Mixing security with business logic causes edge cases

Handle soft-delete filtering in the application layer with `WHERE deleted_at IS NULL`.

---

## Critical Anti-Patterns to Avoid

### Git Workflow Violations
**Critical**: Use `Skill(skill: "git-workflow")` BEFORE every commit to avoid these recurring issues:
- Using HEREDOC syntax instead of literal newlines (causes shell EOF errors)
- Omitting required commit message sections
- Using `git add -A` or `git add .` without explicit permission
- Missing post-commit summary with hash and file stats

### Over-Engineering Without Need
**Example**: Adding severity levels to errors when binary worked/failed suffices
**Lesson**: Push back on complexity. If you can't explain why it's needed, it probably isn't.

### Credential Management Anti-Patterns
**Example**: Hardcoding API keys or using fallback values for missing credentials
**Lesson**: System should fail fast when credentials are missing rather than continuing with defaults.

### Cross-User Data Access
**Example**: Manual user_id filtering in database queries
**Lesson**: User isolation is handled at the architecture level via RLS, not in individual queries. Design for this from the start.

### Premature Abstraction
**Example**: Creating wrapper classes for utilities that are only used in one place, configuration objects for scenarios that don't exist, or complex hierarchies before understanding actual usage patterns
**Lesson**: Start with the straightforward solution. Abstractions should emerge from repeated patterns in actual code, not from anticipated future needs. A function that's only called from one place should stay there. A configuration with one use case needs no flexibility. Complexity added "just in case" usually becomes technical debt. Write simple code first, then notice real patterns, then extract only when extraction makes the code clearer.

### "Improving" During Code Extraction
**Example**: Removing state variables that "seemed unnecessary" during refactoring
**Lesson**: When extracting working code, preserve ALL existing behavior exactly as-is. Don't "improve" or "simplify" during extraction - just move the code. If the original system worked, there was likely a good reason for every piece of logic, even if it's not immediately obvious. Extract first, improve later if needed.

### Infrastructure Hedging (Faux-Resilience)
**Example**: `try: result = db.query() except: return []` making database outages look like empty data
**Lesson**: Required infrastructure failures must propagate. Returning None/[]/fallbacks when database/embeddings fail masks outages as normal operation, creating diagnostic hell. Operators need immediate alerts when infrastructure breaks, not silent degradation users eventually report as "weird behavior". Only catch exceptions to add context before re-raising, or for legitimately optional features (analytics, cache warmers).

### UUID Type Mismatches at Serialization Boundaries
**Note**: Preserve native types (UUID, datetime, date) internally, convert only at serialization boundaries (API responses, external storage, logging). Common errors: `TypeError: Object of type UUID is not JSON serializable` means missing `str()` at boundary.

### Incomplete Code Path Replacement
**Example**: Replacing a method with new logic but missing side effects buried inside it
**Lesson**: When replacing a code path, trace ALL side effects of the original - logging, metrics, state updates, event emissions. Run existing tests to catch what you missed.
