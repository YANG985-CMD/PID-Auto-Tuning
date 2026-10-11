# Controller comparison (simulation only)

| Method | Mean RMSE | Mean peak current (A) | Mean overshoot (rpm) | Saturation | Faults |
|---|---:|---:|---:|---:|---:|
| fixed PI baseline | 0.174773 | 2.4717 | 0.000 | 0.0089 | 0 |
| AI skill bounded search | 0.171898 | 2.3806 | 0.799 | 0.0072 | 0 |
| fuzzy PID | 0.165427 | 2.6620 | 0.000 | 0.0178 | 0 |
| neural-network PID | 0.164725 | 2.6624 | 0.000 | 0.0161 | 0 |
| TD3 Actor | 0.167076 | 2.5010 | 0.000 | 0.0094 | 0 |

## Interpretation

- All methods use the same deterministic mock plant, references, and test seeds.
- The TD3 rows come from the MATLAB TD3 evaluation report supplied to the experiment.
- The NN-PID is supervised to imitate the fuzzy gain schedule; it is not TD3.
- The bounded AI skill row is a safe candidate search, not a neural policy.
- These numbers do not authorize real-motor deployment or prove hardware performance.
