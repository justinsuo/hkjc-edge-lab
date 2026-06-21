# HKJC Edge-Detection Tool — Phase 0 Research Report & Feasibility Assessment

**Date:** 2026-06-15
**Status:** Phase 0 (research only). No code beyond this document. Awaiting go/no-go decision before Phase 1.
**Author's mandate:** Determine *honestly* whether a retail-accessible, public-data tool can detect persistent positive-EV or arbitrage opportunities at the Hong Kong Jockey Club (HKJC). The default expected answer is "NO."

---

## TL;DR (read this first)

1. **Risk-free arbitrage on HKJC is effectively impossible for a retail bettor** — provably so *within* a pool (it is an algebraic certainty that you lose exactly the takeout), structurally so *across* pools, and practically + *legally* so across offshore books (betting with non-HKJC operators is a criminal offence in Hong Kong under the Gambling Ordinance, Cap. 148).
2. **The HKJC win market is one of the most efficient betting markets on earth.** The classic favourite–longshot bias is *absent* in Hong Kong. The public odds alone are a near-optimal forecaster. The closing line is set largely by sophisticated, late-betting computer syndicates.
3. **The single greatest practitioner (Bill Benter) could not beat this market with a fundamental model alone** — his model only became profitable when *blended with the public odds*, bet at massive scale on near-final odds, and given **rebates** that retail users cannot get.
4. **You start every bet ~17.5% in the hole** (Win/Place/Quinella/QPL takeout), rising to 23–25% on exotics. A realistic public-data model adds only a *small* increment of information over the market — historically too small to clear that takeout net without scale + rebates.
5. **Recommended framing: this is a research / learning project, not an income source.** Build it to learn quantitative modelling, market-efficiency testing, and honest backtesting. Treat any "edge" it reports as the extraordinary claim it is, and make "NO BET" the loud default. **Realistic probability of finding a persistent, retail-exploitable edge against the closing line with public data and no rebates: very low (low single-digit percent).**

> **GO / NO-GO recommendation:** **Conditional GO — as a research project only.** Proceed to Phase 1 *if and only if* you accept that the most likely honest outcome of Phase 3 is "no detectable edge / cannot beat the closing line," and that this outcome is a *success* of the validation process, not a failure to engineer around. Do **not** proceed if the goal is reliable profit.

---

## 1. Market efficiency of HKJC betting & the history of computerized syndicates

### 1.1 The HKJC pool is unusually efficient

- **No favourite–longshot bias (FLB).** The near-universal bias where longshots are overbet and favourites underbet — documented in the US, UK, Australia, Germany — is *absent* in Hong Kong. Busche & Hall (1988) found no FLB across 2,653 HK races; Busche (1994) confirmed it on a further 2,690. HK is *the* textbook counterexample. **Implication:** the crudest "edges" (back favourites / fade longshots) do not work here. *(Caveat: these studies are 30+ years old; "no FLB" ≠ "perfectly efficient today," but it does mean simple crowd biases are not exploitable.)*
- **The public odds are a near-optimal forecaster.** In Benter's own out-of-sample HK data (1986–1993), the public's implied probabilities achieved an explanatory power (R²-type statistic) of **~0.122**, while his elaborate 9-factor fundamental model reached only **~0.125** — i.e. decades of modelling barely out-predicted the crowd. Only the *combination* of model + public odds reached ~0.140.
- **Efficiency rises with volume.** Walls & Busche (1996) found betting volume is a significant determinant of cross-race efficiency: high-turnover races are more efficient. HKJC turnover is enormous (~HK$138.85bn / US$17.7bn racing turnover in 2024/25, plus ~HK$31.8bn commingled "World Pool"), so the marquee pools are extremely deep and sharp.

### 1.2 Who sets the price

The closing line at HKJC is shaped heavily by **professional computer syndicates ("computer teams")** — organisations reportedly exceeding 200 people doing form analysis, modelling and global data-gathering. They deliberately bet **as late as possible** (to use parade/gate information and to avoid signalling), so late odds moves are typically "the tote finally catching up with what the professionals already thought was the right price." You are not betting against a naive crowd; you are betting into a price the sharps have already corrected.

### 1.3 The Benter/Woods syndicate — what it actually took

- **People & timeline:** Bill Benter (physicist, ex-blackjack counter) and Alan Woods moved to Hong Kong c. 1984 and **lost money for ~3 years (1984–87)** before turning a profit.
- **Method:** a **multinomial / conditional logit** model (after Bolton & Chapman 1986). The published 1994 version used **9 significant fundamental factors**, estimated on ~3,198 HK races; the live system later grew to ~120 variables per horse.
- **The load-bearing finding:** the **fundamental model alone was not safely profitable.** Benter showed it was *biased and not independent of the public estimate* — when his model rated a horse above the market, actual win frequency sat much closer to the *market's* number (he called this "disastrous from a wagering point of view"). Only a **two-stage model** that fed both the fundamental probability **and the public's implied probability** into a second logit produced unbiased, bettable numbers. **In plain terms: the crowd is most of the signal; you can only win by modelling horses *and then deferring heavily to the public price.***
- **Structural advantages a retail user cannot replicate:**
  - **Rebates** on large losing bets (≈10% Win/Place, 12% Quinella pools) that cut the *effective* takeout for whales — "all they have to do is lose less than their rebate."
  - **Late, high-volume bet timing** with automated infrastructure, betting on near-final odds.
  - **A multi-year head start** when essentially nobody else was modelling HK racing, plus 200-person operations and bespoke data pipelines.
- **The edge decayed.** As more syndicates entered, the market became efficient *because* of them — "the money bet reflected the true probabilities." The edge that existed in 1990 has largely been competed away; today a handful of large, rebated, late-betting teams compete against *each other* for what's left after takeout.

**Bottom line:** the historical record says a retail bettor with only public data and no rebates should assume **negative EV after the ~17.5% takeout**, and treat any claimed edge as extraordinary. *(Honesty notes: the ~US$1bn lifetime / ~US$100m peak-season figures for Benter are journalistic estimates, not audited; the "no FLB" studies are old; the often-quoted "~20% of bets are syndicates" figure is for US racing, not HK.)*

---

## 2. Current HKJC takeout / commission rates per pool

HKJC pools are **pari-mutuel**: all bets enter a pool, HKJC removes a fixed **takeout (commission)**, and the remainder ("dividend payout") is shared among winners. `1 − takeout = dividend payout rate`.

| Pool | Dividend payout to winners | **HKJC takeout** | Notes |
|---|---|---|---|
| **Win** | 82.5% | **17.5%** | |
| **Place** | 82.5% | **17.5%** | |
| **Quinella (QIN)** | 82.5% | **17.5%** | |
| **Quinella Place (QPL)** | 82.5% | **17.5%** | |
| **Double (DBL)** | 82.5% | **17.5%** | |
| **Forecast (FCT)** | 80.5% | **19.5%** | |
| **Trio (TRI)** | 77% | **23%** | |
| **Tierce (TCE)** | 75% | **25%** | |
| **First 4 (F4) / Quartet (QTT)** | 75% | **25%** | |
| **Treble** | 75% | **25%** | |
| **Triple Trio (TT)** | 75% current + 7.5% to jackpot reserve | **17.5%** true commission | 7.5% returns to punters via jackpot |
| **Double Trio (DT)** | 75% (+0.5% operator reserve) | **~24.5%** effective | |
| **Six Up** | 75% (+2% operator reserve) | **~23%** effective | |

**Effective blended rate** across all bet types is sometimes quoted at ~18–18.7% historically (older IFHA analysis). For modelling, use the per-pool figures above.

### Government betting duty (important nuance)

Hong Kong levies **horse-racing betting duty at a progressive 72.5%–75%** — but **on HKJC's net stake receipts (turnover − dividends), i.e. out of HKJC's margin, NOT as an extra deduction from the punter's pool.** The punter only ever loses the takeout. (The "Special Football Betting Duty" applies to football only, not racing.) No change to racing-duty rates or pool takeouts in the 2024/25–2026/27 budgets.

### Rebates — and why they barely help retail

HKJC runs a published **Rebate** scheme, open to all account holders but triggered only by **large losing bets**:

- **Threshold:** a single losing ticket/bet-line of **≥ HK$10,000** on an eligible pool.
- **Eligible pools:** Win, Place, Quinella, Quinella Place only.
- **Rates (of the losing amount):** **10%** Win/Place (local), **12%** Quinella/QPL (local), **6%** overseas races.

This is a volume discount for high-stakes players that trims effective takeout on the qualifying pools (e.g. Win effective takeout drops toward ~15.7% for a large staker). It is **not realistically accessible** to a normal retail bankroll betting modest amounts, and it does **not** reduce the headline pool takeout that sets the dividend. *(Authoritative figures from HKJC's own betting guides and rebate pages; the formal Betting Rules PDFs are the legal authority but render as scanned binaries.)*

---

## 3. Is arbitrage realistically possible? (Honest answer: no)

**Foundational point:** pari-mutuel ≠ fixed-odds. Real arbitrage requires **locking a price** at the moment you transact. In a tote, displayed odds are *provisional projections*; only the final pool determines dividends. **There is no price to lock.** This single fact defeats nearly every scheme below.

### (a) Within a single pool (e.g. dutching the whole Win field) — **provably impossible**

Let takeout = `t` (= 0.175 for Win). With final pool `P` and amount `sᵢ` on horse `i`, the decimal dividend if `i` wins is `dᵢ = (1−t)·P / sᵢ`. Summing inverse odds over the whole field:

```
Σ (1/dᵢ) = Σ sᵢ / [(1−t)·P] = P / [(1−t)·P] = 1 / (1−t) = 1/0.825 ≈ 1.2121
```

The overround is **always exactly 1/(1−t) ≈ 121.2%** — an algebraic identity, never < 1. Backing every horse (dutching) returns a fixed gross `R` for an outlay of `R/(1−t)`, so your return on capital is exactly `1−t = 0.825`: a **guaranteed −17.5% loss**. It's worse in practice, because (i) you bet against *provisional* odds but are paid on *final* odds, and (ii) your own stakes move the pool (you are the marginal price-setter). **Verdict: covering all outcomes is the cleanest possible way to pay the full vig — the opposite of arbitrage.**

### (b) Across HKJC pools (Win vs Quinella vs Place vs QPL) — **not arbitrage**

Tempting idea: derive pair probabilities from the Win pool and exploit discrepancies vs the Quinella pool. It fails as arbitrage for four independent reasons:

1. **Different settlement events + separate takeouts.** A Win bet (horse 1st) and a Quinella bet (two horses 1st–2nd) are not opposite sides of one contract, and each already nets its own takeout. There is no single state space where the two net to a constant.
2. **The Win↔exotic link is a *modelling assumption*, not an identity.** Converting Win probs to pair/ordered probs requires a model (standard choice: **Harville 1973**, assuming conditional independence). Harville is **known to be biased**. So a "discrepancy" may just be *your model's error*, not a real edge.
3. **Provisional, self-moving odds.** Both legs are pari-mutuel; you can't lock either, and each bet shifts its own pool.
4. **No lay side.** HKJC tote is back-only; you cannot sell an outcome, so you can never build a flat position.

**What *is* true:** cross-pool consistency is a legitimate **value signal** (information) — if the Quinella pool overbets a pair relative to the Win-implied estimate, that's a positive-EV *opportunity if your model is right and the edge exceeds takeout*. It is value betting with variance, **not** risk-free arbitrage.

### (c) HKJC vs offshore fixed-odds books — **theoretical, and illegal in HK**

- **Legality is the dealbreaker.** The **Gambling Ordinance (Cap. 148)** criminalises betting in Hong Kong with any operator other than HKJC, including offshore/internet operators (2002 amendment). Individuals face up to 9 months' imprisonment and a HK$30,000 fine. For a HK-based user this is not a footnote.
- **Settlement circularity.** Many offshore books settle *on the HKJC final tote* — so "book vs HKJC" is comparing a price to a slightly worse version of itself; the apparent edge is the book's margin.
- **Practical barriers:** winners get limited/closed; stake caps; timing/settlement risk (you lock the fixed leg early but the tote finalises at the gate); currency/FX friction.
- Fleeting **fixed-vs-fixed** arbs between two offshore books can momentarily exist (as in any sport) but are tiny, stake-limited, account-closing, and not HKJC arbitrage — and not legally available to a HK user.

| Case | Risk-free arbitrage? | Why |
|---|---|---|
| (a) Within one pool | **No — provably impossible** | Overround = 1/(1−t) ≈ 121%; full-field dutching = guaranteed −17.5% |
| (b) Across HKJC pools | **No** | Different events, separate takeouts, model-dependent links, no lay side — at best a *value signal* |
| (c) HKJC vs offshore | **No (practically); illegal in HK** | Settlement circularity, timing risk, account closures, FX — and criminal liability |

**The honest "arbitrage" module in this tool can only be a cross-pool *consistency check* (a signal), never a risk-free arb. It must say so.**

---

## 4. Available data sources, formats, and legal/ToS status

HKJC publishes an unusually rich set of racing data for free, almost all as **server-rendered HTML reached via predictable query-string URLs**, plus an **undocumented internal GraphQL API** behind live odds.

| Data type | Source / URL pattern | Format | Availability |
|---|---|---|---|
| Racecards (draw, weight, jockey, trainer, gear, rating, class, distance, going, form) | `racing.hkjc.com/en-us/local/information/racecard?racedate=YYYY/MM/DD&Racecourse=ST&RaceNo=N` | HTML tables | **Public** |
| Results & dividends (all pools, running positions, finish time) | `racing.hkjc.com/en-us/local/information/localresults?...` | HTML | **Public** |
| **Sectional & finishing times** | `racing.hkjc.com/en-us/local/information/displaysectionaltime?racedate=DD/MM/YYYY&RaceNo=N` | HTML | **Public** (HKJC is unusually generous here) |
| Live Win/Place + exotic odds, within-race odds trend | `bet.hkjc.com/en/racing/wp/` (internal **GraphQL** JSON) | Real-time JSON | **Public (live only)** |
| **Historical odds-movement archive** | — | — | **NOT published by HKJC** (biggest gap; must self-collect by polling, or buy) |
| Going / track condition / weather | "Weather and Track Condition" + embedded in cards | HTML | **Public** |
| Barrier trials, trackwork | `.../btresult`, `.../localtrackwork` (+ video) | HTML / video | **Public** |
| Veterinary records (lameness, surgeries, exams) | `racing.hkjc.com/en-us/local/information/veterinaryrecord` | HTML | **Public** |
| Horse form/history (back to 1979), gear changes | per-horse pages, form-line report | HTML | **Public** |
| Jockey/trainer stats, draw statistics | `.../jkcstat`, `.../draw`, odds charts | HTML | **Public** |
| Pool/betting rules | `hkjc.com/.../HorseRace_Rule_3_Eng.pdf` + e-Win guides | PDF + HTML | **Public** |

**Key gaps & format notes:**
- **No official public API or bulk-download product.** Everything is built for human browsing. The GraphQL endpoint is reverse-engineered (community wrappers cap ~4 odds-types per call).
- **HKJC does not archive historical odds snapshots.** Capturing odds *movement* requires polling `bet.hkjc.com` at intervals before the off and storing your own time series — this is essential design work for any closing-line-value analysis.
- Date formats are inconsistent across page types (results use `YYYY/MM/DD`, sectional pages use `DD/MM/YYYY`); legacy `.aspx` URLs sometimes 302-redirect to a maintenance page, so the scraper must track the current `/en-us/local/information/...` scheme.

### robots.txt & Terms of Service (verified live)

- `https://racing.hkjc.com/robots.txt` → **404** (no robots.txt on the subdomain hosting the racecard/results/sectional data). Absence ≠ permission; copyright/ToS still govern.
- `https://www.hkjc.com/robots.txt` → 302 to a maintenance/404 page.
- `https://bet.hkjc.com/robots.txt` → **exists**: `Disallow: /info/*` and `/ContentServer/*`; **Allow** `/racing`, `/football`, `/marksix` and localized variants. The racing/odds paths are *not* disallowed by robots.txt.
- **Binding eWin / Members' Terms & Conditions** explicitly prohibit users from "reproduce, distribute, make available, **resell**, sublicense or otherwise tamper with" the platform/content, and from providing it to third parties.
- **Honest legal posture:** scraping is **legally gray, leaning restrictive.** Factual race data isn't copyrightable per se, and the racing subdomain has no robots disallow — but the compiled tables are HKJC copyright, and the T&C forbid redistribution/resale. **Low-risk zone = personal/research use, modest volume, no redistribution.** **High-risk zone = commercial redistribution or resale of scraped data.** *(I could not extract verbatim text from the public-site usage/copyright pages — they are JS-rendered — so those should be confirmed in a browser before relying on them.)*

### Third-party sources (fallbacks / for odds movement)

- **Renavon** (commercial): race results + **historical odds combinations with market movement** — fills the odds-archive gap (paid).
- **Apify "HKJC Comprehensive Racing Data"** (commercial, ~$0.015/record): results, sectional analytics, barrier trials, vet records as JSON/CSV.
- **GitHub (free):** `eprochasson/horserace_data` (HK records since 1979 + unique 2016–2018 live-odds snapshots), `Bobosky2005/hkjc-api` (GraphQL wrapper), `rkwyu/sport-betting-data` (MIT), several scrapers. Licenses vary / often unstated.
- **Kaggle:** `gdaley/hkracing` dataset exists for prototyping.

**Design implication:** build a **modular, polite, cached** data layer (plain `requests` + parser for `racing.hkjc.com`; direct GraphQL calls for live odds), **log provenance per record**, throttle aggressively with a real User-Agent, collect for **personal research only**, and **do not redistribute raw HKJC data**. For historical odds movement, either self-poll going forward or license a vendor.

---

## 5. What a competitive model needs — public vs proprietary

| Feature group | Example features | Availability |
|---|---|---|
| **A. Form / past performance** | finishing positions, margins, class of past races, career win%, winnings/race, **number of past races** | **Public** (raw) → **Semi-public** (normalized speed ratings must be self-computed; these were the *most important* variable in Bolton & Chapman) |
| **B. Recency / condition** | days since last run, age, barrier-trial results | **Public** (gallop *quality* is not) |
| **C. Race conditions** | distance, going, course, class, field size | **Public** (fully priced by market) |
| **D. Draw / weight** | barrier position, weight carried, handicap rating | **Public** (heavily priced) |
| **E. Connections** | jockey/trainer stats, **jockey–trainer combo**, owner stats | **Public** stats → **Semi-public** (combos via aggregation) |
| **F. Physical / gear** | declared body weight & change, gear changes, vet/soundness | **Public** (stable's private read is proprietary) |
| **G. Suitability** | distance preference (Benter's DPGA residual), going/course preference, pace fit | **Semi-public** (must be engineered) |
| **H. Market** | **public win odds & odds movement** | **Public** — the single strongest feature, and free |
| **I. Sectional / pace ratings** | self-built pace/sectional ratings | **Semi-public** (HKJC publishes sectionals) → **Proprietary** for GPS biometrics |
| **— Proprietary-only** | GPS tracking (~18 pts/sec), stride data, live in-running position, stable "work"/gallop intelligence, heart-rate/biometric, trainer intentions, CAW late-money order flow, multi-decade clean datasets | **Proprietary / hard** — what the top syndicates have and retail does not |

### The central, load-bearing finding

**The public odds are the strongest single predictor, and your model's value is purely *incremental* over the market.** Benter measured this directly:

- Public odds alone: R² ≈ **0.122**
- Best fundamental model alone: R² ≈ **0.125** (barely above the market; in some runs *below* it)
- Combined (fundamental + public): R² ≈ **0.140** — the fundamental model added only **ΔR² ≈ 0.009–0.018** on top of the crowd.

His "tipster" control is the killer demonstration: ~48 newspaper handicappers had similar standalone power to his model, but added **essentially nothing** when combined with the odds — because their information was *already priced in*. **The entire game is finding signal the market hasn't already absorbed.** That means your edge can only come from (a) information the market underweights, or (b) a better *combination* of public signals than the crowd — and historically that became profitable only when blended with the public odds, bet at scale on near-final odds, and given rebates.

**Realistic ceiling with public-only data:** a couple of points of explanatory power over the market — enough to be profitable *only* with the two-stage (model + odds) architecture, scale, near-final-odds betting, and favourable economics. Absent the late-data, scale, and rebate advantages, the same model will most likely show an in-sample edge **smaller than the 17.5–25% takeout** and lose money net out-of-sample. Be deeply skeptical of ML projects reporting high raw "accuracy" — raw top-1 accuracy is **not** the same as beating the closing line after takeout, which is the only metric that matters.

---

## 6. Blunt feasibility assessment & recommendation

### The four walls you are up against

1. **The efficiency wall.** HK is one of the most efficient racing markets in the world (no FLB; public odds ≈ optimal forecaster). The price you'd bet into is already corrected by sharps.
2. **The takeout wall.** Every Win/Place/Quinella/QPL bet starts at **−17.5%**; exotics at −23–25%. Your model must add more than that, net, out-of-sample.
3. **The incremental-information wall.** Per Benter's own numbers, the realistic edge a public-data model adds over the market is **small (ΔR² ~0.01)** — and is *below the market standalone*. It helps only in combination with the odds.
4. **The economics/infrastructure wall.** Profitable syndicates rely on **rebates** (10–12% on qualifying pools) and **automated late-betting on near-final odds** at scale — neither realistically available to a retail user. CAW syndicates can post *negative raw returns and still profit on rebates alone*; you can't.

### Probability this tool finds a persistent, retail-exploitable edge

**Very low — low single-digit percent.** The honest base rate, given an efficient market, a ~17.5%+ takeout, a tiny incremental signal, and no rebates/scale, is that **the model will not beat the closing line out-of-sample.** That is the *expected* result, and the validation phase is designed to detect it rather than paper over it.

### Why build it anyway (the legitimate value)

- **A rigorous, honest learning project** in quantitative modelling, market-efficiency testing, calibration, and adversarial backtesting — skills that transfer well beyond racing.
- **A genuine, falsifiable test** of market efficiency: *can* a public-data model beat the HKJC closing line? Answering that honestly (almost certainly "no") is itself a worthwhile, well-scoped result.
- **Decision support / entertainment**, with disciplined fractional-Kelly staking and hard caps, *if* you choose to bet small amounts recreationally — but framed as paying for entertainment, not investing.

### Recommendation: **Conditional GO — research project only**

Proceed to **Phase 1** with these non-negotiable guardrails baked in from the start:

1. **"NO BET" is the default and the most common output.** The tool must be a skeptic, not a confidence machine.
2. **The primary success metric is closing-line value (CLV) out-of-sample.** If the model cannot beat the closing line OOS — and it probably can't — the tool reports that plainly and recommends nothing. No CLV edge ⇒ no live recommendations, full stop.
3. **Real takeout (17.5–25%) and realistic bet timing are applied to every backtest**, with bootstrap confidence intervals so "profit" is tested against variance.
4. **No "arbitrage" is ever claimed** beyond honest cross-pool consistency *signals*, clearly labelled as value (not risk-free).
5. **Data collection stays personal/research-scale, polite, cached, provenance-logged, and never redistributed** (per HKJC T&C).
6. **Every recommendation shows its estimated edge AND its uncertainty**, and live CLV/P&L is logged so the tool grades *itself* over time.

**Do not proceed if the goal is reliable income.** The honest, evidence-based expectation is that no such edge exists for a retail bettor with public data and no rebates. If that conclusion is acceptable as a *finding*, the project is worth building as a research instrument. If it isn't, the project should stop here.

---

## Appendix: consolidated sources

**Market efficiency & syndicates:** Busche & Hall (1988) / Busche (1994), via Snowberg & Wolfers NBER WP 15923 (2010) and Kajii & Watanabe (2017); Walls & Busche (1996), *Applied Economics Letters*; Benter (1994), *Computer Based Horse Race Handicapping and Wagering Systems* (gwern.net mirror) + Acta Machina annotation; Bloomberg (Chellel, 2018, paywalled — corroborated via casino.org, Champion Bets, Guinness World Records 2025, Wikipedia); Idol Horse (Shane Dye, 2024–25); CDC Gaming commentary. HKJC turnover: iGB (2023), Gaming Intelligence / ASGam (2025).

**Takeout & rebates:** HKJC betting guides (`is.hkjc.com/AOSBS/help/en/HR_Guide.html`; `special.hkjc.com/e-win/.../local-pools/`, `.../rebate/`); HK Govt LCQ6 on betting duty (info.gov.hk, 2023); SCMP (2020, Quinella rebate 10%→12%); HKJC formal Betting Rules (`HorseRace_Rule_3_Eng.pdf`); HK Budget 2025-26; IFHA/Chang (2007).

**Arbitrage:** HKJC pool guides; Harville (1973) & Ziemba–Hausch on exotics; Covers.com (provisional-odds mechanics); Tanner De Witt & ICLG (Hong Kong Gambling Ordinance Cap. 148); IT Law Wiki (2002 offshore-betting amendment).

**Data sources & ToS:** live robots.txt (`racing.hkjc.com` 404, `bet.hkjc.com` rules), HKJC racing pages (racecard, localresults, displaysectionaltime, veterinaryrecord, formline, jkcstat, btresult, localtrackwork), eWin/Members T&C (`member.hkjc.com/.../terms-and-conditions.html`); third parties: Renavon, Apify (`alaricus/hkjc-comprehensive-racing-data`), GitHub (`eprochasson/horserace_data`, `Bobosky2005/hkjc-api`, `rkwyu/sport-betting-data`), Kaggle (`gdaley/hkracing`).

**Model features:** Benter (1994); Bolton & Chapman (1986), *Management Science*; Chapman (1994, 2,000 HK races); Stanford CS230 "Ga Yau" (Torné 2021); IEEE SVM committee-machine work; CAW/rebate economics (EquinEdge, Thoroughbred Daily News).

*Full URLs for every source above are recorded in the Phase-0 research agent transcripts and can be expanded into a formal bibliography on request.*
