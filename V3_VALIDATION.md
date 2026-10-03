# V3 validation — 2026-10-04

`python -m unittest discover -s tests -q`: **70 tests, OK**.

Tests include original research/data/API/wallet/durable-order tests, plus 21 competition tests: start boundary, execute-before-start block, read-only block, account-mode and per-submit gate, same-bar suppression, exposure targets, order slicing, cash reserve, persistent drawdown exit independent of Binance, stale quotes, host clock drift, account reservations, unsupported assets, once-only recovery counter, wrong start rejection, recent test proof, durable initial verification, simulated complete order/wallet cycle, and simulated separate-process verifier.

The simulated exchange integration goes through actual durable submit/recover functions and confirms three mocked orders, records fill counters, includes fees in a simulated wallet, and reconciles final NAV. It is **not** a real Roostoo fill, live credentials test, latency/slippage test, or actual EC2 reboot test.

Source compiles; shell scripts pass bash syntax checks. The installer generates an inactive systemd unit; it has not been installed on the user's EC2 by this assistant. systemd and startup behavior require user-side AWS verification.

Private API credentials are absent from the deliverable. No actual orders were submitted by the assistant. Real test fill verification and actual-account read-only checks remain user-side requirements before initial competition execution.

Strategy unchanged: 24h momentum + EMA20/50 + inverse volatility on closed 15-minute BTC/ETH/SOL bars. Competition risk parameters are conservative engineering defaults, not newly optimized or performance-validated. Historical V1 metrics do not establish V3 profitability.

Limits: per-host/user account locks, no distributed lock across machines; pending/unknown submissions block without blind retries; read failures retry at most three polls when no order intent exists; fatal errors stop, Restart=no; only supported spot assets and empty margin/short state accepted; capped sell-only risk exits may take several polls and leave dust; scoring active days not guaranteed; no organizer-confirmed end-time gate.

Runtime state, audit logs, credentials and verification are excluded from Git and ZIP. Retain them during upgrades. Review code/config migrations instead of deleting account state.

Start-time correction: user confirmed Oct 4 20:00 HKT = 12:00 UTC. Updated runtime configuration, hard validation, boundary fixtures and instructions. Additional tests prove exact old-config-only migration preserves account binding, unresolved order intent, halted flag and fill counters, and rejects unrelated risk changes. Original 08:00 HKT is blocked by the new gate.
