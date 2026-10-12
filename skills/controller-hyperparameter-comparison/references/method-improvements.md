# Paper-informed improvements for PID parameter self-tuning

These references are design inputs, not proof that a method is safe or superior on a new plant.

## AI skill bounded search

[A Physics-Informed Framework for PID Tuning of Chemical Processes Using Large Language Model Agents](https://arxiv.org/abs/2607.26594) structures LLM tuning around closed-loop response features, control-engineering diagnoses, physical priors, candidate gains, and acceptance criteria. Apply that pattern by keeping raw serial frames local, producing a typed response-window summary, requiring bounded candidates, and recording candidate/reason/acceptance/rollback traces. The paper evaluates chemical processes; validate the same workflow on the user's plant.

## Fuzzy PID

[Fuzzy Logic Driven Self-Tuned PI Controller for Enhanced Speed Regulation of PMSM Drives](https://doi.org/10.1155/jece/7690514) is a reference for 7×7 membership/rule structures and centroid defuzzification. [A New Method for the Speed Control of a Brushless DC Motor Based on Optimized Fuzzy Control](https://doi.org/10.5152/electrica.2026.25063) motivates offline optimization of membership functions and rules. [Design of Fuzzy PID Controller Based on Sparse Fuzzy Rule Base for CNC Machine Tools](https://doi.org/10.3390/machines11010081) motivates reducing rules when MCU cost matters. Compare 5×5, 7×7, and sparse variants on both control quality and target resource use.

## Neural-network PID

[A New On-Line PID Tuning Method Using Neural Networks](https://doi.org/10.1016/S1474-6670(17)38283-6) uses a neural model to estimate process characteristics before updating PID gains. [ANN Based Self-Tuned PID-Like Adaptive Controller Design for High Performance PMSM Position Control](https://doi.org/10.1016/j.eswa.2014.06.040) motivates small recurrent structures and recursive adaptation. [Artificial Neural Network-Based Real-Time PID Controller Tuning](https://doi.org/10.1016/B978-0-443-15274-0.50256-0) motivates multi-operating-point training. For an MCU port, keep the network small, train across load/setpoint/parameter variation, bound outputs, detect out-of-distribution inputs, and fall back to a verified controller.

## TD3 Actor

[Addressing Function Approximation Error in Actor-Critic Methods](https://arxiv.org/abs/1802.09477) provides TD3's twin Critics, delayed policy updates, and target policy smoothing. [A Novel Entropy-Maximizing TD3-based Reinforcement Learning for Automatic PID Tuning](https://arxiv.org/abs/2210.02381) motivates staged exploration before deterministic exploitation. [Stability-Preserving Automatic Tuning of PID Control with Reinforcement Learning](https://arxiv.org/abs/2112.15187) motivates rejecting candidates that do not preserve a stability condition. [Safe Reinforcement Learning Using Robust Action Governor](https://arxiv.org/abs/2102.10643) motivates an external safety supervisor. Keep these mechanisms outside the MCU Actor and test on unseen operating conditions.
