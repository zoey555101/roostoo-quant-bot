LearningByMistakes — Roostoo Quant Trading Bot
Team: Team61-LearningByMistakes (HKU)
Competition: Roostoo APAC Quant Trading Hackathon
Documentation date: 17 October 2026, Hong Kong time
Confirmed competition entry point: python -m quant.hybrid_v3_competition --execute
1. Overview and evidence boundary
Our project implements an automated, unleveraged, long/cash portfolio on Roostoo's simulated exchange. The strategy combines confirmed trend signals, volatility- and covariance-aware exposure, variable holding count, and hybrid limit/market execution. It trades eligible cryptocurrencies and exchange-listed bStock instruments; these are platform instruments, not direct purchases of conventional shares through a stock broker.
The design aims to retain participation in positive trends while limiting portfolio risk and unnecessary turnover. It does not assume that more assets, greater exposure, or more frequent signals necessarily increase net returns.
The competition account progressed from an initial three-coin strategy to Cross-Asset V2 and then Hybrid V3. Consequently, the competition account's full return history must not be attributed entirely to Hybrid V3. Fusion V4 is a separate TEST-account research candidate; production migration has not been confirmed. The latest Fusion exit-filter patch was not confirmed as uploaded or installed when this document was prepared.
A service record supplied on 17 October identifies Hybrid V3, with a process start at 2026-10-07T18:35:08Z and an abnormal exit at 2026-10-09T12:45:51Z (exit status 1). This is evidence of an operational interruption, not continuous operation through the competition end. Subsequently supplied systemd status confirmed the service remained failed at the time of inspection on 17 October. The journal records Stopped safely: Invalid Free. A read-only competition balance query identified SPCXB Free = -0.001, with zero Lock, PendingOrders and ShortCollateral. Exchange AmountPrecision is 3, so the deficit equals one quantity increment. This does not by itself prove the exchange or client caused the discrepancy. No final account return, official ratio, or rank is asserted here without the final records.
2. Competition evaluation
The final organizer announcement supplied to the team specifies:
- 50% of the screening score comes from portfolio ratios and 50% from the private strategy repository and README.
- Within the ratio component: 40% Sortino, 30% Sharpe, and 30% Calmar.
- Fewer than eight trading days results in a scoring penalty, rather than automatic disqualification.
- HFT/latency-arbitrage activity also results in a scoring penalty under the revised announcement. Our design does not deliberately implement either activity.
- A private GitHub repository containing source, backtest/forward-test code, results, and a thorough README must be shared with judges.
The stated repository submission deadline is 15 October, 12:00 HKT. This document was prepared afterwards; it does not imply that a late submission or amendment is accepted. Organizer acceptance and judge access require separate confirmation.
We do not manufacture trades solely to accumulate active days. A normal execution day counted in local logs is not proof that the organizer recognizes it as a qualifying trading day.
3. Data and tradable universe
Public signal data and execution prices
Signals use completed five-minute Binance spot candles. The strategy obtains fresh Roostoo quotes for execution and account valuation. Signal symbols such as BTCUSDT map to Roostoo execution pairs such as BTC/USD; MSTRBUSDT maps to MSTRB/USD.
Historical research uses official Binance archives with SHA256 checksum validation. Data checks address timestamp units, duplicates, missing bars, OHLCV validity, and cross-asset alignment. Research prices are not assumed identical to Roostoo execution prices.
Public-data repair work introduced a shared closed-bar cutoff, continuous common windows, and explicit unavailability handling without filling missing prices. Where installed, missing public data blocks new signal-based entries and ordinary rebalancing while retaining available account-level protective handling. This cannot protect the account while the process itself is stopped.
Configured Hybrid V3 universe
The registered configuration contains 12 cryptocurrencies:
BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LINK, AVAX, LTC, SUI, UNI
It also contains 21 bStock identifiers:
AMDB, METAB, TSLAB, INTCB, GOOGLB, NBISB, LITEB, PLTRB, SPCXB, GLWB, CBRSB, MSFTB, SKHYB, COINB, QCOMB, CRCLB, MUB, NVDAB, MSTRB, WDCB, SNDKB
Configured membership is not a guarantee of eligibility or actual holdings. Valid aligned history, quotes, exchange trading status, liquidity, and signals determine participation. The number of holdings is dynamic; there is no mandatory top-three holding limit in Hybrid V3.
4. Hybrid V3 signal factors
All normal signal decisions use closed candles, rather than treating an incomplete candle as final.
Factor or filter	Implementation	Purpose
Momentum	288-bar close return, approximately 24 hours	Positive trend participation
Trend	EMA60 minus EMA150, divided by close	Distinguish sustained trend from individual price moves
Volatility	Rolling 288-bar return standard deviation	Scale relative asset weights
Covariance	Recent 576-bar return window in the risk allocator	Estimate portfolio variability including co-movement
ATR	72-bar average true range	Adapt confirmation buffer and protective stops
Liquidity proxy	Rolling 288-bar sum of close × volume, at least $5m equivalent	Exclude weakly traded signal series
Data/trading checks	Positive current candle volume, valid quotes, exchange permissions	Reject unusable observations


For entry, momentum and normalized EMA gap must both exceed 0.25 × ATR / close. The liquidity condition must hold, current volume must be positive, and price must be no more than three ATR above EMA60. Entry conditions must hold for two consecutive closed bars.
For a held asset, a trend exit is confirmed after three consecutive closed bars satisfying negative momentum or negative EMA-gap conditions below the ATR buffer, or loss of the liquidity condition, with positive candle volume. Failure to qualify for a new entry alone does not force an immediate sale: existing positions can be held through the hysteresis rule until an exit or risk constraint applies.
This is primarily a trend-following system. It does not claim to identify the exact bottom or top. Selling below acquisition price can be a deliberate risk exit; systematically doing so after unnecessary reversals is nevertheless a cost and signal-quality problem that we investigate.
5. Dynamic allocation and exposure
The allocator normalizes inverse-volatility weights across eligible assets, estimates the mix's daily volatility from recent covariance, and scales exposure toward a 0.5% modeled daily risk target. Hybrid V3 disables additional breadth scaling. The risk target is a model input, not a guaranteed loss limit.
Targets are smoothed using 0.25 × new allocation + 0.75 × prior target. Confirmation, holding hysteresis, and subsequent caps can change the raw allocation.
Registered competition setting	Value
Gross target exposure ceiling	60% NAV
Per-instrument target ceiling	10% NAV
Aggregate bStock target ceiling	30% NAV
Normal minimum trade	$100
Normal deviation band	1% NAV
Maximum order slice	$5,000
Maximum normal orders per signal bar	4
Maximum normal new notional per signal bar	$20,000
Normal daily turnover budget, HKT day	$100,000


Residual allocation remains cash. Caps are target/planning constraints: price movement, minimum sizes, pending orders, and staged execution can temporarily cause differences between targets and actual holdings. Dollar turnover counts traded notional, not unique capital invested. Larger order sizes do not reduce a percentage commission rate by themselves.
6. Selling, protective exits, and re-entry
The system sells for three principal reasons:
1. Confirmed trend exit: the persistence rule described above sets that asset's target to zero.
2. ATR protective exit: a trailing stop uses three ATR, bounded to a 1%–5% stop fraction. The tracked peak and stop move in one direction; increased volatility must not loosen an existing stop.
3. Portfolio risk or exposure reduction: a 3% drawdown from the preserved portfolio high-water mark triggers a permanent halt and liquidation attempts; exposure caps can also require reductions.
The 3% threshold is not a hard maximum realized loss. Gaps, polling, stale data, failed requests, pending orders, and execution costs can cause overshoot. For inherited positions, protection starts from the first observed activation mark rather than an invented acquisition cost or historical peak.
After a completed asset exit, the normal re-entry cooldown is six five-minute bars. Ordinary opposite-direction trading requires both a three-bar cooldown and a favorable price movement of at least 0.3%; forced exits bypass this ordinary economic filter. These mechanisms reduce rapid reversals but do not eliminate whipsaw losses.
7. Hybrid execution and fee accounting
Normal adjustments and initial confirmed exits use passive limit prices. Unfilled limits have a 180-second TTL. Confirmed exits that remain overdue after 300 seconds may use market execution; ATR and portfolio emergencies use market orders immediately when evaluated.
The documented exchange fee schedule and observed test fills are:
Execution	Commission
Maker limit fill	0.05% of executed notional
Taker market fill	0.10% of executed notional


Fee accounting uses the exchange-reported commission and role rather than assuming every submitted limit fills as intended. A $50,000 fill at 0.1% costs $50; dividing it into ten $5,000 fills at the same rate still costs approximately $50. Lower turnover and a greater maker share can reduce costs; larger tickets alone do not.
Normal quote checks include a 0.5% maximum spread and a 3% reference-price deviation check. Normal polling is 60 seconds; five-minute bars do not require a trade every five minutes. The competition runner has a five-second subsequent polling interval during certain risk/overdue exits, used for liquidation management rather than a latency-arbitrage signal.
Only one owned live order is managed at a time. Submission intent is persisted before the API request; fills are reconciled by order ID. Cancellation requires exchange confirmation before replacement. Unknown submission outcomes are retained for reconciliation rather than blindly resubmitted.
8. Account integrity and operations
TEST and COMPETITION use separate credentials, bindings, and recovery directories. Account locks prevent two cooperating runners from submitting concurrently on one account. Competition execution requires the explicit flag, matching configuration/account identity, migration verification, and exchange-time start gate (2026-10-04T12:00:00Z, 20:00 HKT).
Wallet valuation uses Free + Lock. Observed PendingOrders can mirror Lock and must not be added again to NAV. Unsupported reservations, negative balances, shorts, or ambiguous orders block execution instead of being silently normalized. These safeguards can stop the service and require investigation.
Operational failures encountered include missing/misaligned cross-asset bars, order-response placeholder fields, pending-reservation schema handling, and negative precision-sized TEST balances. Repairs and tests address particular cases; they do not establish uninterrupted production reliability. The known abnormal service exit on 9 October is a material limitation of the competition run.
Read-only monitoring
From the project root on AWS:
sudo systemctl status roostoo-competition --no-pager -l
sudo journalctl -u roostoo-competition -n 60 --no-pager
.venv/bin/python -m quant.hybrid_v3_competition_status
The status module reads saved local state; a recent local snapshot is not an independent exchange confirmation. Plan summaries labeled orders are planned actions, not proof that every listed order filled. Use reconciled fills, exchange responses, and final statements for results.
9. Historical research and findings
We retained unsuccessful candidates rather than reporting only the best result. Historical studies below concern earlier research candidates, not a validated backtest of the final Hybrid V3 or Fusion V4 implementation.
Study	Reported scope	Main finding
Fixed-parameter validation	63 paths: June/July/September × seven candidates/baselines × three cost cases	46 paths triggered permanent exit; no candidate justified a production upgrade on this evidence alone
P&L attribution	99 original/matched-baseline paths	Price P&L, fees, and slippage were reconciled; turnover could erase positive price gains
Lower-turnover study	288 paths, including complete months, independent 14-day windows, tails, controls and baselines	Four-hour and twelve-hour variants improved all 12 monthly comparisons against the old hourly V3 control, but did not establish stable superiority to passive baselines


For the old three-coin v3_current research control at 10 bps fee / 5 bps slippage per side:
Independent month	Price P&L	Fees	Slippage	Net P&L on $100,000
June 2026	$231.74	$540.62	$270.31	-$579.19
July 2026	$596.93	$588.70	$294.35	-$286.12
September 2026	$575.50	$700.66	$350.33	-$475.49


This motivated reduced unnecessary turnover and explicit maker/taker execution, rather than indiscriminate increases in trading frequency or position size. These are independently cash-started months, not a continuous compounded performance record.
Research caveats include selection after viewing some data, non-independent cost scenarios, USD/USDT and venue differences, incomplete historical order-book modeling, and permanent exits that alter subsequent paths. A higher-cost run sometimes loses less because its path exits earlier; this is not a benefit of higher fees.
The team-reported detailed study directories are reports/offline_validation_20261005/, reports/offline_attribution_20261005/, and reports/offline_low_turnover_20261005/. Their reports, frozen settings, commands, trade/equity CSVs and checksums must accompany the submission to substantiate these summaries. They were produced in a separate research workspace; their presence in the submitted repository has not been verified. Do not treat an absent archive or this summary alone as a reproducible result bundle.
10. Forward execution evidence and its limits
TEST-account exchange queries confirmed maker and taker fills and a terminal cancellation. Examples recorded during execution verification include maker SELL order 3427824 (DOGE/USD, 0.05%), taker BUY 3428189 (ETH/USD, 0.10%), and canceled limit BUY 3428385 (BTC/USD). These demonstrate execution paths, not profitable signals.
On the competition account, limit SELL 3428318 for 60.37 CRCLB was independently queried as filled at 82.82, notional $4,999.8434 and commission $2.499921 (0.05%). Available local audit records also showed whipsaw losses and fee drag. A partial FIFO audit excludes unknown inherited costs and missing earlier fills; it is not a whole-account attribution.
Final competition return, daily NAV series, trading-day count, maker share, fee total, drawdown and official ratios require the final account export and complete time-stamped records. No final figures are fabricated or inferred from old snapshots. Availability of code tests and execution proofs does not validate profitability.
Investigated SPCXB exit and service failure
Read-only order queries returned filled limit BUY orders 3447524 (19.173 at 166.63, USD fee 1.597398) and 3447612 (8.972 at 166.44, USD fee 0.746649), followed by filled limit SELL 3447641 (28.145 at 165.89, USD fee 2.334487). The two buy quantities sum exactly to the sell quantity. For this isolated matched lot, the reported average prices imply approximately $-19.12 price P&L and $-23.80 after reported fees; this is not whole-account attribution and assumes no other inventory interactions. The negative 0.001 SPCXB balance cannot be explained simply by subtracting these three quantities or a SPCXB-denominated fee. Complete inventory and exchange balance-delta evidence is needed to identify the cause.
No production repair trade or restart was performed as part of this documentation investigation. The lack of a monitored recovery path allowed a small balance-validation failure to leave the strategy service unavailable. Trading, software validation and account P&L must be assessed separately: stopping the process does not liquidate existing holdings.
11. Fusion V4: separate TEST research
Fusion V4 adds tighter trend-entry location checks and a bounded mean-reversion sleeve for qualifying cryptocurrencies. The mean-reversion hypothesis requires a flat regime, a depressed price followed by a rebound, and sufficient distance to a reference mean after estimated costs. This distance is not a guaranteed expected return. It also includes known-cost filtering for ordinary profit-taking, while protective exits may realize losses.
Testing exposed a negative ADA balance after final liquidation. A bounded, explicitly authorized TEST repair and a final-sell quantity reserve were introduced. Further inspection found an old reference-price filter could block already confirmed exits while overdue exits also prevented signal refresh. A TEST-only patch removes that reference-price filter for forced exits while preserving ordinary checks. The patch's installation and successful forward behavior remain unconfirmed.
Fusion V4 must not be presented as the strategy producing the competition account's historical results. Historical results from earlier candidates are not its backtest. No production activation is implied by including its code in this repository.
12. Reproduction and repository navigation
Use Python 3.11 or newer in an isolated environment:
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
Historical research commands and input manifests should be run from each included study's archived commands.sh. Preserve its data hashes, frozen parameters, cost cases and output paths. The original python -m quant demo uses synthetic data and is a software demonstration, not a real-market result.
Module or file	Responsibility
quant/roostoo.py	API requests, signing and exchange clock synchronization
quant/cross_asset_v2_market.py, quant/market_alignment.py	Public data and alignment repair, where installed
quant/cross_asset_v2_allocator.py, quant/cross_asset_v2_risk.py	Dynamic allocation and modeled risk scaling
quant/hybrid_v3_live_strategy.py	Registered competition signals, targets and stops
quant/hybrid_v3_live_orders.py	Competition execution and reconciliation
quant/hybrid_v3_live_engine.py	Competition cycle orchestration
quant/hybrid_v3_competition.py	Competition entry point
competition.hybrid_v3.json	Fixed competition configuration
quant/hybrid_v3_competition_status.py	Local competition status
quant/fusion_v4_*	Separate TEST candidate, where included
tests/	Accounting, signals, order-state and recovery regression tests


Later modules may exist only in downloaded patch packages or the deployed AWS working tree. A ZIP uploaded to GitHub does not automatically install its source into the repository. The final private submission must include the actual source files and compatible configuration, not merely this README and assorted patch ZIPs. Preserve commit dates and distinguish post-deadline documentation/repairs from code used during competition.
Evidence to include with the private submission
- The source revision(s) actually deployed, configuration without credentials, and migration history.
- Historical research scripts, frozen parameters, input provenance/checksums and complete results, including unsuccessful candidates.
- Redacted forward-test execution proof and cancellation/recovery evidence.
- Final competition NAV/return records and trades, with timestamps, fees and coverage gaps.
- Service interruption logs and the final revision mapping; do not claim uninterrupted uptime.
Do not commit API keys, secrets, credential JSON files, or unreviewed private runtime dumps. Supply reviewed, redacted evidence. Share the private repository with the judges using organizer-provided identities; changing repository visibility alone does not grant access.
13. Conclusions and remaining limitations
The project's strongest demonstrated properties are transparent accounting, explicit risk and execution controls, and a research process that retained negative findings. The studies show material cost sensitivity and unstable signal advantage; they do not establish robust out-of-sample profitability. Broadening the universe and risk scaling increase flexibility but can introduce correlation, instrument-specific session effects, stale prices and additional failure modes.
The live run also revealed that process availability and coherent exit/data handling are essential strategy components. These weaknesses should remain visible in evaluation. Future work should use fixed-parameter prospective evaluation, deployment monitoring, complete forward records, and stronger integration tests before increasing exposure or activating additional strategy sleeves.
Sources
- Organizer's final screening announcement supplied to the team; submission form: https://forms.gle/crws1EgNnLaaC9B39
- Roostoo API documentation: https://github.com/roostoo/Roostoo-API-Documents
- Binance public-data documentation: https://github.com/binance/binance-public-data
- Binance official archives: https://data.binance.vision/
Research metrics and execution examples above are attributed to the team's archived reports and supplied exchange/log outputs. Organizer-calculated scoring remains authoritative.
