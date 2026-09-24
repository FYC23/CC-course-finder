# Handoff: implement Phase 1 with subagent-driven development

Paste the block below as the first message of a fresh Claude Code session in this repo.

---

Implement Phase 1 of the CC Course Finder coverage work using the superpowers:subagent-driven-development skill. Read these two files first, in this order:

1. `docs/superpowers/specs/2026-09-22-agentic-coverage-design.md` (the design; Phase 1 is item 1 of section 14)
2. `docs/superpowers/plans/2026-09-22-phase1-section-model-banner9-colleague.md` (the plan; eight tasks with tests, code, and commit steps)

Dispatch one fresh subagent per task in order (1 through 8), review each task's diff and test output before starting the next, and stop for my review after Task 4 and after Task 8. Each subagent must run `uv run pytest -q` before committing and report the exact pass/fail line.

Standing rules for this repo:

- Commit messages use conventional-commit prefixes and no attribution trailers.
- All dataclasses stay frozen; never mutate, always build a new object.
- No LLM call, browser, login, or CAPTCHA handling anywhere in Phase 1. Nothing in the query path calls a model.
- Any future generative-model code goes behind a provider-agnostic interface (spec section 8.4); never wire a specific vendor directly.
- Use `mgrep` for searches, not the built-in Grep or WebSearch tools.
- Live network checks are explicit manual steps in the plan (Task 5 step 5, Task 6 steps 3 and 4). The pytest suite must stay offline.

Things I learned while writing the plan that the subagents should not rediscover the hard way:

- `src/schedule/banner_ssb_classic.py` is already a Banner 9 adapter under the wrong name; `src/schedule/banner_ellucian.py` is Colleague Self-Service under the wrong name. Tasks 3 and 4 rename them.
- Colleague term codes differ per district (`2026FA`, `2026/FA`, `2026F`, `26/FA`). The adapter resolves them from the portal's `TermFilters` and only uses `params.term_format` as an override.
- Colleague's `Days` array is 0=Sunday; Banner 9 uses `monday..sunday` booleans. `normalize.py` owns both conversions.
- A 07:30–09:00 Pacific class ends at midnight in UTC+8 and must classify as `conflicts`, not `fits`. The fit tests encode this.
- The Evergreen Valley host in `colleges.json` is dead; the working host is `https://selfservice.sjeccd.edu`. Mt. SAC, CCSF, and College of San Mateo are Banner 9 now.
- Real response samples used to write the fixtures are in the plan's Task 3 and Task 4 reference blocks; the fixtures in the tests are trimmed copies of those.
- `tests/schedule/test_pilot_provider.py` fakes ordered HTTP responses. Task 4 changes the call order (one bootstrap GET before the keyword loop, one term-resolution POST unless `term_format` is set), so that file's fake sequences need reordering, not new assertions.

When Phase 1 is done and reviewed, the next plan to write is Phase 2 (generic replay adapter and hand-written specs for the Riverside district), per spec section 14.

---
