# Decision evals

Hand-labeled cases for the decision questions in `src/decisions/questions.py`, plus a
runner that scores whichever backend `DECISION_PROVIDER` selects. Runs cost money and
hit a vendor API; they are manual, not part of pytest.

    DECISION_PROVIDER=llm LLM_PROVIDER=anthropic LLM_MODEL=<model id> \
      uv run python -m evals.runner course-equivalent
    DECISION_PROVIDER=jev uv run python -m evals.runner section-modality --limit 50

Each run writes `evals/results/<date>-<question>-<backend>.md`. Commit it: it is the
evidence for the thresholds in `src/matching/config.py` and for the backend choice.
Set `LLM_PRICE_INPUT_PER_MTOK` / `LLM_PRICE_OUTPUT_PER_MTOK` to add a cost estimate.

## Labeling

Targets (spec 8.3): 300 `course_equivalent` pairs across at least 10 colleges, 200
`section_modality` rows. The seed rows carry `source` so every label is traceable.

- `course_equivalent`: `label` is true only when the live course is the same course,
  renumbered or renamed. Good negatives are hard ones: the neighboring course in the
  same sequence, a support course, a same-titled course at a different level. Remove any
  "(Formerly ...)" note from `live_description`; the discover pass reads those notes
  deterministically, so the decision backend only sees pairs without them.
  `matching discover` output (`review` rows especially) is a good source of candidates.
- `section_modality`: label from what the schedule shows, not from the token alone.
  Leave a row out rather than guess.
