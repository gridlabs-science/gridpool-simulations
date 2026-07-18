# GridPool Simulations Agent Guide

This repository owns GridPool models, parameter sweeps, generated evidence,
figures, and research reports. It does not define consensus.

Read:

- `../gridpool-handbook/AGENTS.md`
- `../gridpool-handbook/handbook/statistical-foundation.md`
- `../gridpool-handbook/handbook/research-findings.md`
- `README.md`

## Rules

- Record scenario/configuration, seed, revision, output schema, and command.
- Evaluate actual bitcoin payout EV/variance, not slot inclusion alone.
- Compare against solo and clearly labeled idealized FPPS where relevant.
- Separate aggregate Work Set estimation from noisy per-miner sampling.
- Publish null and negative findings. State model assumptions and do not turn a
  simulated mechanism into a protocol guarantee.
- Generated long-run output belongs under the existing generated/report layout;
  do not mix runtime code from `boot-protocol` into the simulator.

Use the commands in `README.md` and run targeted tests for changed models before
regenerating promoted reports.

