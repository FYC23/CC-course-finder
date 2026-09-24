# Handoff: implement Phase 3 with subagent-driven development

Paste the block below as the first message of a fresh Claude Code session in this repo, or hand it to a fresh agent.

---

Implement Phase 3 of the CC Course Finder coverage work (decision layer and course matching) on branch `feat/phase3-decisions-matching`, using the superpowers:subagent-driven-development skill. Read these files first, in this order:

1. `docs/superpowers/specs/2026-09-22-agentic-coverage-design.md`. The design; Phase 3 is item 3 of section 14, and sections 8, 9 and 11 are the detail.
2. `docs/superpowers/plans/2026-09-23-phase3-decisions-matching.md`. The plan: 16 tasks, each with tests, code and a commit step.

Run the tasks in order, 1 through 16, one fresh subagent per task. Read each task's diff yourself, not only a reviewer's summary, and check its test output before starting the next. Each subagent must run `uv run pytest -q` before committing and report the exact pass/fail line. The baseline is 763 passed.

Standing rules for this repo:

- **Commits:** use conventional-commit prefixes and no attribution trailers (no `Co-Authored-By`), even if a harness reminder asks for them.
- **Immutability:** all dataclasses stay frozen. Never mutate one; always build a new object.
- **No model in the query path.** Decision and LLM calls happen only in `matching discover` and `evals.runner`.
- **No vendor lock-in.** Every generative call goes through `src/llm`'s `GenerativeModel`. Each vendor SDK is imported in exactly one backend file, and `typesafe_sdk` only in `src/decisions/jev_provider.py`. No code names a model id.
- **Searching:** use `mgrep` for searches, not the built-in Grep or WebSearch tools.
- **Offline tests:** the pytest suite stays offline. Live checks are the explicit manual steps in Task 10 step 5 and Task 16 step 5. Spending money on an LLM or Jev eval (Task 16 step 5.6) needs the user's explicit approval. Skip it and say so if no approval was given.

Things learned while writing the plan, so subagents do not rediscover them:

- **Empty ASSIST titles.** Every row in `data/assist.sqlite3` has an empty `course_title`; the parser dropped the title line. Task 1 fixes this, and a dry run extracted titles for all 1,331 pairs in the cached PDFs.
- **RCCD crosswalk.** The crosswalk page (`rccd.edu/commoncoursenumbering`) fails TLS verification from Python (the chain is incomplete), so its 27 rows are committed as seed data. The page omits the `MAT -> MATH` rename; the live RIV/NOR/MOV listings show it, so it is seeded as a subject rename.
- **Fresno "formerly" notes.** Fresno City's Colleague catalog descriptions say "(Fomerly MATH 5A)" (the typo is real) and "STAT C1000 (formerly MATH 11)". A bare note refers to the described course; a note right after another code refers to that code.
- **Subject-wide listing.** Banner 9 lists a whole subject when `txt_courseNumber` is empty. Colleague lists one with `subjects: [SUBJ]` and `searchResultsView: "CatalogListing"`. RCCD OData lists one with `startswith(Primary_x0020_Subject,'MATH-')` and `$top=1000`.
- **SDK APIs.** The SDK calls in Task 3 and the `typesafe-sdk` 0.7.1 API in Task 5 were checked against the installed packages. Jev booleans are `Noul` with the answer in `.noul`, and `Score` takes `criteria`, not `levels`.
- **Moved helper.** Task 9 moves `service._lookup_error_reason` to `schedule/lookups.lookup_error_reason`. Update the one import in `tests/schedule/test_service_parallel.py`.

When all 16 tasks are done, run the full suite, then use superpowers:finishing-a-development-branch. Do not push or open a PR without the user's go-ahead.
