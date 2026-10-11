# Controller comparison (simulation only)

| Method | Mean RMSE | Mean peak current (A) | Mean overshoot (rpm) | Saturation | Faults |
|---|---:|---:|---:|---:|---:|
| fixed PI baseline | 0.174773 | 2.4717 | 0.000 | 0.0089 | 0 |
| AI skill bounded search | 0.171898 | 2.3806 | 0.799 | 0.0072 | 0 |
| fuzzy PID | 0.165461 | 2.7177 | 0.000 | 0.0194 | 0 |
| neural-network PID | 0.164814 | 2.6925 | 0.000 | 0.0178 | 0 |
| TD3 Actor | 0.166923 | 2.5023 | 0.000 | 0.0100 | 0 |

## Interpretation

- All methods use the same deterministic mock plant, references, and test seeds.
- The TD3 rows come from the MATLAB TD3 evaluation report supplied to the experiment.
- The NN-PID is supervised to imitate the fuzzy gain schedule; it is not TD3.
- The bounded AI skill row is a safe candidate search, not a neural policy.
- These numbers do not authorize real-motor deployment or prove hardware performance.
