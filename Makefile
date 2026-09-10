.PHONY: setup check

# One-command contributor bootstrap for the local quality gate -- see
# scripts/setup.sh for the full rationale (pinned prek, hooksPath
# detection, idempotent re-runs).
setup:
	@scripts/setup.sh

# Same gate as CI: prek over the whole tree (this runs ruff-check --fix +
# ruff-format, so it CAN autofix and silently pass a brand-new, unstaged
# file -- no index entry for `prek run --files` to diff against), a
# separate `ruff check .` WITHOUT --fix as a second, non-autofixing pass
# over the same tree, `ruff format --check .` so an unstaged formatting
# error is caught the same way, a full-tree gitleaks scan (the gitleaks
# hook only scans `git --staged`, a no-op here since nothing is staged --
# mirrors the CI job's separate step), and the full test suite. Requires
# `prek` and `gitleaks` -- run `make setup` first if either is missing.
# Prefers the version-scoped prek binary `make setup` installs under
# ~/.local/state/karlstadsenergi-prek/<version>/bin/ over a bare PATH
# lookup: an ordinary clone's `make setup` never puts that directory on
# PATH, and a stray global `prek` (a different version, or none) would
# otherwise be picked up silently, defeating the pinning. Falls back to
# PATH for machines where prek is already installed globally (e.g. via
# brew) and `make setup` only checked for it rather than installing it
# (the core.hooksPath case -- see scripts/setup.sh). `.venv` must have
# both requirements_dev.txt (ruff) and requirements_test.txt (pytest +
# homeassistant) installed -- see CONTRIBUTING.md. Full output goes to
# .check.log (gitignored); on success only a one-line summary is
# printed, on failure the actual errors.
check:
	@prek_version=$$(grep -o 'prek==[0-9][0-9.]*' .github/workflows/validate.yaml | head -n1 | cut -d= -f3); \
	persist_bin="$$HOME/.local/state/karlstadsenergi-prek/$$prek_version/bin/prek"; \
	if [ -x "$$persist_bin" ]; then \
		prek_bin="$$persist_bin"; \
	elif command -v prek >/dev/null 2>&1; then \
		prek_bin="prek"; \
	else \
		echo "missing: prek -- run make setup"; exit 1; \
	fi; \
	command -v gitleaks >/dev/null 2>&1 || { echo "missing: gitleaks -- run make setup"; exit 1; }; \
	[ -x .venv/bin/ruff ] || { echo "missing: .venv/bin/ruff -- pip install -r requirements_dev.txt -r requirements_test.txt in .venv"; exit 1; }; \
	rm -f .check.log; \
	( \
		"$$prek_bin" run --all-files >> .check.log 2>&1 && \
		.venv/bin/ruff check . >> .check.log 2>&1 && \
		.venv/bin/ruff format --check . >> .check.log 2>&1 && \
		gitleaks dir . --no-banner >> .check.log 2>&1 && \
		.venv/bin/python -m pytest >> .check.log 2>&1 \
	) && echo "check: OK" || (echo "check: FAILED -- see .check.log" && tail -n 60 .check.log && exit 1)
