# karlstadsenergi-ha -- General Guidelines

This document applies to the Supervisor and all subagents.

---

## Permissions

### Supervisor has authority to:

- **Approve all reads and fetches** -- Including web data, documentation, API references
- **Delegate tasks** to subagents without asking the Product Owner
- **Make technical decisions** within project scope
- **Reprioritize** as needed based on blockers

### Subagents may without asking:

- Read all documentation
- Fetch web data for research
- Create prototypes and test code
- Document their findings

### Requires Product Owner approval:

- Scope changes (new features outside plan)
- Architectural decisions affecting user experience
- Release/distribution

---

## Documentation and Sources

### Principles

1. **Save documentation for reuse**
   - All fetched documentation should be summarized and saved in `research/`
   - Avoid fetching the same source multiple times

2. **Reference management**
   - Each source must be logged with URL, date, and summary
   - Stored in `research/references.md`

3. **Currency**
   - Verify that information applies to current versions

### Directory Structure for Documentation

```
research/
+-- references.md          # Bibliography
+-- _txt/                  # Text extracts from PDFs
+-- _analys/               # Primers and summaries
```

### Reference Format

```markdown
## [Short title]

- **URL:** https://...
- **Fetched:** YYYY-MM-DD
- **Summary:**
  Brief description of content and relevance to the project.
```

---

## Communication

### Assignment Format (Supervisor -> Subagent)

```
ASSIGNMENT: [short heading]
CONTEXT: [relevant background]
TASK: [concrete what to do]
DELIVERABLE: [expected output]
DEPENDENCIES: [any blockers or collaborations]
```

### Report Format (Subagent -> Supervisor)

```
STATUS: [done / in progress / blocked]
RESULT: [what was done]
QUESTIONS: [any ambiguities requiring decisions]
NEXT: [proposed next steps]
RISKS: [identified problems]
```

---

## Code Standards

- Python 3.12+ with modern conventions
- Follow Home Assistant integration development guidelines
- Use `aiohttp` for async HTTP (bundled with HA)
- Type hints on all public functions
- No third-party libraries without approval
- Lint with `ruff` before committing

---

## Project Principles

1. **Minimalism** -- Simplest solution that works
2. **Document decisions** -- All choices must be motivated
3. **Ask rather than guess** -- When uncertain, escalate
4. **Never ignore bugs** -- Bugs found during work must be fixed immediately (< 10 min) or documented with priority. Noting "pre-existing" and moving on is not acceptable.

---

## Handling Discovered Bugs

**PRINCIPLE:** Bugs you walk past today are bugs you trip on tomorrow.

### When discovering an existing bug during ongoing work:

1. **Can be fixed immediately (< 10 min)?** -> Fix now, separate commit
2. **Requires more work?** -> Write up with priority and create a task
3. **Blocks current work?** -> Escalate to supervisor/product owner

### Reporting

Always report in the RISKS field:

```
RISKS:
- EXISTING BUG: [description]. File: [path:line]. Action: [fixed/documented/escalated]
```

### What is NOT acceptable:

- Noting that a bug is "pre-existing" and moving on
- Pushing the bug forward without documentation
- Hiding the bug in test results
