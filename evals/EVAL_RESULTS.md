# Retrieval Eval Results

- Goldset: 78 items · mode: lexical-only
- Block-anchored subset: 26 items
- Generation eval: disabled (run with --judge)

## Full goldset

| strategy | n | hit@1 | hit@4 | MRR | avg top score | avg retrieve ms |
|---|---|---|---|---|---|---|
| naive | 78 | 61.5% | 82.0% | 0.696 | 0.435 | 10.11 |
| hybrid | 78 | 70.5% | 85.9% | 0.768 | 0.433 | 25.36 |
| hybrid_parent_child | 78 | 73.1% | 83.3% | 0.775 | 0.394 | 32.23 |

## Block-anchored subset (strategy differences only show here)

| strategy | n | hit@1 | hit@4 | MRR | avg retrieve ms |
|---|---|---|---|---|---|
| naive | 26 | 65.4% | 84.6% | 0.734 | 10.23 |
| hybrid | 26 | 69.2% | 88.5% | 0.769 | 25.67 |
| hybrid_parent_child | 26 | 73.1% | 88.5% | 0.798 | 32.76 |
