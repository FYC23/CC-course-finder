# course_equivalent eval: jev

Date: 2026-09-23  
Data: `evals/data/course_equivalent.jsonl` (24 cases, 0 errors)

Accuracy at 0.5: 100.0%  
Brier score: 0.0395 (lower is better)  
Positives: 9 of 24

## Threshold sweep

| threshold | accepted | precision | recall |
|---|---|---|---|
| 0.50 | 9 | 100.0% | 100.0% |
| 0.60 | 8 | 100.0% | 88.9% |
| 0.70 | 8 | 100.0% | 88.9% |
| 0.80 | 7 | 100.0% | 77.8% |
| 0.90 | 2 | 100.0% | 22.2% |
| 0.95 | 0 | n/a | 0.0% |

## Calibration

| bin | count | mean predicted | observed yes |
|---|---|---|---|
| 0.0-0.1 | 11 | 0.03 | 0.0% |
| 0.1-0.2 | 1 | 0.11 | 0.0% |
| 0.3-0.4 | 1 | 0.38 | 0.0% |
| 0.4-0.5 | 2 | 0.44 | 0.0% |
| 0.5-0.6 | 1 | 0.57 | 100.0% |
| 0.7-0.8 | 1 | 0.76 | 100.0% |
| 0.8-0.9 | 5 | 0.84 | 100.0% |
| 0.9-1.0 | 2 | 0.92 | 100.0% |

## Usage

Calls: not recorded by this backend
