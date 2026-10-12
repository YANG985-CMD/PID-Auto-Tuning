---
name: controller-hyperparameter-comparison
description: Compare, improve, and port four PID parameter self-tuning methods—AI bounded search, fuzzy PID, neural-network PID, and TD3 Actor—using common experiments and exportable implementations.
---

# PID Parameter Self-Tuning

Use this skill when the user wants PID parameter self-tuning, a comparison of these four methods, or a port to a different plant, MCU, or communication interface. The tuning targets are proportional, integral, and derivative gains (Kp, Ki, Kd). The motor speed-loop example uses the PI subset (Kd=0) and tunes Kp/Ki. For full PID, extend the action/output mapping, Kd bounds, and derivative filtering explicitly. The workflow also applies to position, attitude, temperature, pressure, flow, and other loops controlled by PID.

## The four methods

1. **AI skill bounded search** — read telemetry through a serial or other approved interface, summarize response waveforms, ask GPT-6.1-sol for bounded candidates, validate them against an objective and safety gate, apply them through an atomic command, and retain or roll back using the device's actual-application feedback. The language model is a supervisory optimizer; the real-time controller remains on the device.
2. **Fuzzy PID** — normalize error and error rate, evaluate overlapping membership functions and a rule base, defuzzify `ΔKp`/`ΔKi`, and clamp the gains. Prefer a documented 7×7 baseline, then optimize membership breakpoints or use a sparse rule base only after comparing tracking, overshoot, current, computation time, and memory.
3. **Neural-network PID** — train a small network offline to map normalized control features to bounded gains or corrections. Keep the network output bounded, add validation and out-of-distribution fallback to fuzzy/fixed PI, and export only the forward pass to C/C++ for the target device.
4. **TD3 Actor** — train the Actor, twin Critics, replay buffer, and target networks off-device. Deploy only the bounded Actor inference; keep action limits, rate limits, actual-application feedback, leases, and independent protection outside the Actor.

All four methods are intended to be portable. Adapt the state/telemetry schema, parameter bounds, objective, transport, compiler, numeric format, and timing budget to the user's target. Do not present a generated implementation as validated until its input scaling, bounds, runtime, memory, transport, fallback, and independent protection have been checked.

## Workflow

1. Define the controlled variable, PID form (PI or full PID), tunable gains, state features, sampling period, gain bounds, objective metrics, and hard rejection conditions.
2. Run the common simulation comparison from the repository root:

   ```text
   python -B scripts/controller_comparison.py --output OUTPUT \
     --td3-evaluation examples/mock-validation/evaluation-summary.json
   ```

   Use a new task output directory. The comparison is simulation-only and must use the same plant, references, seeds, and metrics for all four methods.
3. For serial tuning, keep high-rate frames local. Create fixed response windows and pass structured features—error, rise/settling time, overshoot, current, saturation, faults, applied parameter, sequence, and timestamp—to the supervisory model. Validate every candidate locally before sending it.
4. For fuzzy PID, document membership breakpoints, labels, rule tables, inference operator, defuzzification, gain map, anti-windup, and fallback. For neural PID, record training ranges, validation loss, quantization error, and the fallback region. For TD3, record the evaluation source, action bounds, exploration coverage, reward terms, and safety-gate result.
5. Compare mean and worst-case tracking error, peak/RMS current, overshoot, saturation, faults, execution time, and memory. A lower RMSE alone does not approve a method.
6. Export a target implementation only after independent evaluation. Preserve the host-side training/search artifacts and the device-side input/output contract so another user can reproduce the port.

## Paper-informed design guidance

Read [method-improvements.md](references/method-improvements.md) when the user asks how to improve one of the four methods. It links each recommendation to a paper and distinguishes literature guidance from repository evidence.

## Scope

This skill compares and ports PID parameter self-tuning methods. It does not authorize physical motion, erase or flash a board, or replace a device's real-time protection and emergency stop. Treat hardware deployment as a separate, explicitly authorized validation task.
