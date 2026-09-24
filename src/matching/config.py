"""Discover-pass settings (spec 9.2). The thresholds are PROVISIONAL: set them from an eval
results file under evals/results/ and cite that file here when you change them."""

ACCEPT_THRESHOLD = 0.9  # best candidate at or above this becomes an `accepted` alias (used at query time)
REVIEW_THRESHOLD = 0.5  # other candidates at or above this wait in the review queue
CANDIDATES_PER_COURSE = 5  # decision calls per unmatched ASSIST course, best title overlap first
