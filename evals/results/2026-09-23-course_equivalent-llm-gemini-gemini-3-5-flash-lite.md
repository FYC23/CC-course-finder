# course_equivalent eval: llm:gemini:gemini-3.5-flash-lite

Date: 2026-09-23  
Data: `evals/data/course_equivalent.jsonl` (24 cases, 0 errors)

Accuracy at 0.5: 100.0%  
Brier score: 0.0020 (lower is better)  
Positives: 9 of 24

## Threshold sweep

| threshold | accepted | precision | recall |
|---|---|---|---|
| 0.50 | 9 | 100.0% | 100.0% |
| 0.60 | 9 | 100.0% | 100.0% |
| 0.70 | 9 | 100.0% | 100.0% |
| 0.80 | 9 | 100.0% | 100.0% |
| 0.90 | 9 | 100.0% | 100.0% |
| 0.95 | 9 | 100.0% | 100.0% |

## Calibration

| bin | count | mean predicted | observed yes |
|---|---|---|---|
| 0.0-0.1 | 14 | 0.02 | 0.0% |
| 0.1-0.2 | 1 | 0.15 | 0.0% |
| 0.9-1.0 | 9 | 0.96 | 100.0% |

## Usage

Calls: 24 (0 failed)
Tokens: 7166 in, 1409 out
Latency: 20187 ms total, 841 ms mean
