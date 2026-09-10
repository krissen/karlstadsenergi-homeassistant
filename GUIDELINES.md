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

## Quality Gates

Lint, format and secret-scanning run via [prek](https://github.com/j178/prek)
against `.pre-commit-config.yaml`. Two ways to wire it in, depending on the
machine:

**(a) Ordinary clone.**

```bash
pipx install prek==0.5.2   # or: uv tool install prek==0.5.2
brew install gitleaks       # or: https://github.com/gitleaks/gitleaks/releases
prek install
```

`make setup` does this for you and is idempotent -- safe to re-run any time
(e.g. after `.github/workflows/validate.yaml` bumps the pinned prek
version). `prek install` wires the hooks into this clone's own
`.git/hooks`, which `.pre-commit-config.yaml` is the only source of truth
for.

**(b) Maintainer machine with a global git-hook dispatcher.** If
`core.hooksPath` already points somewhere other than this clone's own
`.git/hooks` (a machine-wide convention that routes every repo through one
dispatcher), `prek install` refuses -- opt this clone in instead:

```bash
git config prek.enabled true
```

`make setup` detects this case automatically and prints the right command
instead of trying to install hooks that would never run.

**Escape hatch**, per path: on a machine using (a)'s per-clone hooks,
prek's own `SKIP=<hook-id>,<hook-id>` (or `PREK_SKIP`) skips named hooks for
one commit. On a machine using (b)'s global dispatcher, `SKIP_PREK=1 git
commit ...` skips the whole lint pass for one commit without disabling
anything else -- it has no effect under (a).

`make check` runs the same gate CI does (`prek run --all-files`, a no-fix
`ruff check .` / `ruff format --check .` pass, a full-tree `gitleaks dir .`
scan, and the test suite) and prints one line on success, the failing
output on error. CI runs the identical `.pre-commit-config.yaml` via `prek
run --all-files` (see `.github/workflows/validate.yaml`), so there is one
rule list instead of two to keep in sync.

## Code Standards

- Python 3.13+ (Home Assistant's own supported baseline; `requirements_test.txt`
  pins `homeassistant==2026.7.1`, which requires Python >=3.14.2 for the
  test venv specifically)
- Follow Home Assistant integration development guidelines
- Use `aiohttp` for async HTTP (bundled with HA)
- Type hints on all public functions
- No third-party libraries without approval
- Lint with `ruff` before committing (`make check`, or `ruff check --fix .
  && ruff format .`)

## Commit Messages

Conventional Commits 1.0, with a mandatory scope: `type(scope): subject`.

- **type**: one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
  `build`, `ci`, `chore`, `revert`.
- **scope**: lowercase, short -- a filename without extension (`sensor`, not
  `sensor.py`) or a feature/module name (`config-flow`, `waste`).
- **subject**: imperative mood, lowercase first letter, no trailing period,
  <=72 characters.
- Breaking change: `type(scope)!: subject` plus a `BREAKING CHANGE:` footer.
- One commit per logical change; a fix touching several files for one bug is
  still one commit, two unrelated fixes are two commits.
- English only.
- **Never include references to Claude, Anthropic, or other AI tools.**

Examples: `fix(sensor): correct forecast indexing`,
`chore(waste): remove verbose debug logging`.

Older history in this repository uses a `(scope) Subject` format --
Conventional Commits applies going forward, existing history is not
rewritten. A large mechanical reformat commit is recorded in
`.git-blame-ignore-revs`; run `git config blame.ignoreRevsFile
.git-blame-ignore-revs` once per clone so `git blame` skips it.

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
