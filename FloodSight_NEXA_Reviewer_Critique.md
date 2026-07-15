# FloodSight Health — NEXA PoC: Adversarial Reviewer Critique

*Prepared as a mock GCC/SAF peer-review scorecard. Grounded in the actual
Nexa RFP (EN-Nexa-RFP-Jun-18-2026), the PoC application form, and Appendix C
scoring criteria. Deadline: 22 July 2026, 14:00 ET.*

---

## First, three RFP facts that change the framing

Your critique prompt imported a generic "GCC bar" that is stricter than what
Nexa PoC actually asks. Three corrections matter:

1. **PoC does NOT need a pre-existing evidence base.** RFP verbatim: *"Proof
   of Concept proposals are not required to have a pre-existing evidence base
   for their innovation idea. Nexa is looking for new, untested, and bold
   ideas."* The PoC bar is **operational feasibility, acceptability, buy-in,
   plus *early signals* of health impact** — not proven effect.
2. **80% are killed at the Innovation Screen**, which reviews only the seven
   Innovation Overview questions on two axes: **Relevance** and
   **Innovation**. This is where you win or die first. FloodSight is *highly*
   relevant here — malaria via "changing mosquito ecology" and
   "climate-informed early warning and monitoring systems" are both named
   priorities. That is a genuine strength, not a stretch.
3. **The health outcome — not the alert — is what's scored.** RFP verbatim:
   *"Technical or operational outcomes related to the performance of the early
   warning system on generating alerts would not alone suffice. The ultimate
   impact of the technology on health access and/or outcomes needs to be
   understood."* This is the sentence that most threatens FloodSight, because
   the project's centre of gravity is a beautiful alerting pipeline.

Net: your **eligibility and community-connection gaps** are the real danger,
not your technical maturity. Read every section below through that lens.

---

## A. Causal chain credibility — **5 / 10**

The chain is *plausible and on-theme* but **not yet defensible to a malaria
epidemiologist**, and it has one link that a specialist will attack hard.

**What holds up.** The macro-association (heavy rain → standing water →
*Anopheles* breeding → lagged malaria rise) is real and has literature. The
17–24 day lag is a reasonable central estimate. Bayoh & Lindsay (2003) is a
correct citation for temperature-dependent larval development.

**What a malaria epidemiologist will challenge — specifically:**

- **Urban Lagos vector ecology is the killer objection.** *An. gambiae s.s.*
  breeds preferentially in **clean, sunlit, temporary** water. The floodwater
  in dense, informal Lagos LGAs (Ajeromi-Ifelodun, Oshodi-Isolo) is typically
  **organically polluted drain overflow**, which favours *Culex
  quinquefasciatus* (a nuisance/filariasis vector, **not** a malaria vector)
  and, at best, *An. arabiensis*. A reviewer will ask: *"Have you shown that
  the standing water your grid flags actually produces malaria-competent
  Anopheles, rather than Culex?"* You currently cannot answer this. This is
  the single biggest scientific vulnerability.
- **Lagos is a low-transmission setting.** Coastal, urban, high bed-net
  coverage, some of the lowest malaria prevalence in Nigeria (single-digit %
  by microscopy in several surveys). A low base rate means the post-flood
  "spike" you need to detect may be small and noisy — which cripples the MEL
  (see D).
- **Bayoh 2003 is a lab study.** It establishes thermal development kinetics,
  not that Lagos floods create productive habitat. Oduola 2012 and Edeghere
  2018 are Nigerian and relevant but are **association studies**, not
  mechanistic proof that *your* 200 m flooded cells map to case increases.
- **Confounding by rainfall itself.** The same rain that floods cell X also
  raises breeding city-wide, in unflooded cells too. Attributing an LGA case
  rise to specific flooded cells (vs. general wet-season seasonality) is very
  hard and reviewers know it.

**Concrete fixes before submission:** (i) Reframe the chain as a *hypothesis
the PoC will test*, not settled fact — this is exactly what PoC funding is
for, and it converts a weakness into your learning agenda. (ii) Add one
entomology sentence acknowledging the *Culex*-vs-*Anopheles* question and
propose a cheap larval-dip validation (even n=20 flagged sites, one field
tech) as a PoC objective — this single addition would move a skeptical
reviewer from "naïve" to "rigorous." (iii) Cite a Lagos-specific
entomological source, not just thermal biology.

---

## B. Proof-of-concept maturity — **7 / 10**

This is your **strongest card** and you are under-selling it relative to the
field. A live, deployed, tested pipeline puts you in the top decile of PoC
applicants for *technical* feasibility. Deployed FastAPI, 40 unit tests, a
running cron, a real SMS integration, a live dashboard, IaC-style Supabase
migrations — most PoC applicants have a slide deck and a Streamlit demo.

**But NEXA's definition of PoC is field-testing in a real-world pilot, and on
that axis you are pre-PoC:**

- **Zero CHEWs enrolled** (`chew_subscribers` empty). The intervention has
  never touched a human. A reviewer reads this as *"working software, unproven
  intervention."*
- **The health engine's coefficients are hand-set, not fitted.** `z = −2.1 +
  0.45·inundation + 2.80·susceptibility + 1.20·temp`, calibrated to "8
  historical event pairs," is an **expert-judgement heuristic dressed as a
  logistic regression.** A quantitative reviewer will spot instantly that
  these are not estimated from data (no n, no CI, no fit statistic). Present
  it honestly as a **rule-based prior to be calibrated during the pilot**, not
  as a trained model — or a biostatistician will penalise the overreach.
- **DHIS2 UIDs are placeholders**; the outcome data spine is notional.
- **Two-way SMS untested outside sandbox.**

**What a GCC reviewer would accept as "PoC-stage":** you don't need enrolled
CHEWs *at submission* — but you need a **credible, dated path to first
real-world alert cycle inside the grant** and evidence the humans will show
up. That means a signed/likely LSPHCDA engagement (see E) far more than more
code. Do not add features. The marginal code has diminishing returns; the
marginal *partnership* is worth 10×.

---

## C. Last-mile delivery design — **7 / 10**

Genuinely strong and well-argued. SMS-to-CHEW on feature phones is exactly
what Nexa means by last-mile ("enable local health actors to turn
climate-driven health risk signals into timely health service delivery
action" — almost your one-liner). The CONFIRM / REPORT N / HELP protocol is
appropriately minimal.

**What a health-systems reviewer will press:**

- **CHEWs don't own the decision to move commodities.** Bed nets and RDTs sit
  in an LMCU/LSPHCDA supply chain with its own stock, approvals and cold-chain
  realities. An SMS telling a CHEW to "pre-position nets" assumes the CHEW has
  nets to pre-position and the authority to move them. **Where does the
  pre-positioned stock come from, and who authorises release?** If the answer
  is "the grant buys a buffer stock," say so and budget it. If it's "the
  existing LSPHCDA pipeline," you need LSPHCDA to confirm it. This is the most
  common reason health-EWS pilots stall.
- **Alert fatigue and false positives.** Your own flood model has known ERA5
  under-estimation and unvalidated flood→*Anopheles* mapping. Early alerts
  *will* be wrong. A CHEW who mobilises twice for nothing stops responding.
  Your ≥60% CONFIRM KPI measures acknowledgement, not action, and doesn't
  protect against this.
- **CHEW incentive/workload.** Nigerian CHEWs are overstretched. Is there a
  stipend, an airtime reimbursement, integration into existing reporting?
  Reviewers with LMIC field experience will ask.

**Fix:** add one paragraph on the **commodity pathway** and a
**human-in-the-loop supervisor** (a facility focal person who triages alerts
before CHEW mobilisation). That converts "app-thinking" into "health-systems
thinking."

---

## D. MEL rigour — **4 / 10** (your weakest scored section)

The DiD is the right *instinct* and Nexa explicitly welcomes quasi-
experimental and observational designs. But as specified it will **not
survive a biostatistician**, for reasons that are structural, not cosmetic:

- **n = 10 units (5 vs 5). This is severely underpowered.** DiD inference is
  driven by the number of *clusters*, not people. With 5 treatment LGAs you
  have almost no ability to detect anything but a huge effect, and LGA fixed
  effects eat most of your degrees of freedom. A reviewer will write:
  *"Underpowered by design; a null result will be uninterpretable."*
- **The outcome is mechanistically mis-timed against the intervention.** Bed
  nets prevent transmission over *months*; RDTs improve *detection*, not
  prevention. Yet your primary outcome is *"reduction in confirmed cases in
  the 12 weeks after each flood."* Nets can't plausibly move that window, and
  **better RDT availability will *increase* confirmed cases** (more testing →
  more diagnoses) — biasing your DiD toward showing the treatment arm doing
  *worse*. This internal contradiction is disqualifying if a reviewer catches
  it, and they will.
- **DHIS2 as the primary outcome is fragile.** Passive, facility-reported,
  incomplete, subject to RDT stockouts and care-seeking shifts. Using it as
  the attribution spine — when your own intervention changes testing
  behaviour — confounds the measurement with the treatment.
- **18 months spans ~1.5 rainy seasons.** You get one, maybe two, clean
  flood-malaria cycles. Not enough repeated events for event-study DiD.

**How a strong PoC MEL would look instead** (and Nexa's own text points here —
they want *operational feasibility, acceptability, and early signals*, with
health impact as *early signals*, not proven effect):

- **Reframe the primary outcome around the intermediary, operational chain**
  Nexa explicitly lists: *time from alert → CHEW action*, *proportion of
  alerts acted on*, *commodities pre-positioned before vs. after case onset*,
  *proportion of flagged cells with entomologically-confirmed Anopheles*.
  These you *can* measure and power in 18 months.
- Keep DHIS2 case data as a **secondary, exploratory "early signal,"** framed
  honestly as underpowered — not the primary endpoint.
- Add a **stepped-wedge or matched-pair** framing if you keep LGA units, and
  pre-register the analysis. Bring in a named biostatistician (see G).

This section, as written, is where a peer reviewer would dock you the most
points. It is also the most fixable before 22 July.

---

## E. Local ownership & system integration — **3 / 10** (the real fatal-flaw candidate)

Not the DHIS2 UIDs — those are a Month-2 engineering task and reviewers
understand placeholder integration at PoC. The problem is **structural and
partly an eligibility gate:**

- **Incorporation.** RFP is unambiguous: *"For Proof of Concept funding,
  applicant organizations MUST be incorporated or equivalent in Africa or
  Brazil."* "Nigerian incorporation not confirmed" is not a soft gap — it is a
  **hard eligibility question**. The org of record in Fluxx must be an
  incorporated African entity. Rankine Innovation Lab presenting with an ASU
  affiliation and unconfirmed Nigerian incorporation risks failing
  eligibility *before* review. Documentation is only requested if you're
  successful, but you must be able to truthfully select "incorporated in
  Nigeria" at submission. **Resolve this first or do not submit.**
- **Connection to Communities is explicitly scored** (Innovation Screen 1d,
  Peer Review Project Team 4b/4c). The form makes you self-select: Community
  owned / led / partnered / linked / not connected. With no signed LSPHCDA
  relationship and a US-based academic lead, an honest selection is
  **"Community linked"** at best — the second-weakest tier. That caps your
  Project-Team and Relevance scores.
- **No signed LSPHCDA MOU.** GCC does *not* require a fully executed
  government MOU at PoC — but it strongly rewards a **letter of support /
  intent** demonstrating the government partner will grant CHEW roster and
  DHIS2 access. Absence of even a letter, when your entire outcome pipeline
  depends on LSPHCDA, reads as *"the critical dependency is unsecured."*

**GCC's track record:** GCC is relatively founder-friendly and funds early,
scrappy teams — but it is strict on the **incorporation eligibility gate** and
on **community connectedness** because both are core to its "locally led"
thesis. It will forgive an unbuilt integration; it will not forgive an
ineligible applicant or a project with no local anchor.

**Fix, in priority order:** (1) confirm Nigerian incorporation of the
applying entity; (2) secure a one-page LSPHCDA (or LASEMA/State Malaria
Elimination Programme) letter of support; (3) add a Nigeria-based co-lead
with malaria/health-systems standing (see G). Item (1) is binary
pass/fail.

---

## F. Scalability pathway — **6 / 10**

Credible *platform* logic, thin *articulation*. The "one config file →
another city" story is real (the flood grid is genuinely retargetable), and
Nexa likes replicable early-warning platforms. But reviewers have seen many
"it scales to N cities" claims and discount them.

- **Strength:** the underlying flood engine already generalises (open
  satellite inputs, parametric grid). Kano, Ibadan, Kumasi, Nairobi all have
  IMERG coverage. This is a real differentiator vs. bespoke single-site tools.
- **What's missing to be believed:** the *health* layer's scalability depends
  on things that do **not** travel with a config file — CHEW networks, DHIS2
  instances, malaria endemicity, and (critically) the vector-ecology question
  from (A), which is **city-specific**. Northern Nigeria (Kano) is high-
  transmission rural-fringe; the flood→*Anopheles* link is *stronger* there
  than in coastal Lagos. A sharp reviewer might ask why you're piloting in
  low-transmission Lagos at all rather than a higher-burden state.
- **Fix:** frame scale as "flood-EWS core is portable; health-response module
  is a documented adaptation kit (vector calibration + CHEW onboarding + DHIS2
  mapping)." Name 1–2 concrete next geographies *and why* (ideally a
  higher-burden state, to pre-empt the Lagos question).

---

## G. Team credibility gap — **serious**

This is, with (E), the pair most likely to sink you.

- **A single ASU-affiliated researcher with a Nigerian address is not a
  credible delivery team** for a government-integrated malaria intervention.
  Reviewers score "appropriately trained, experienced, positioned to carry out
  design, implementation *and assessment*." As presented, the team has
  demonstrated **software** capacity and **zero demonstrated**
  epidemiology, health-systems, MEL/biostatistics, or Lagos-government-
  relations capacity.
- **Missing signals reviewers look for:** a Nigerian public-health co-
  investigator; a named MEL/biostatistics partner (a Nigerian university —
  UNILAG College of Medicine, or a malaria research group); a
  letter/collaborator from LSPHCDA or the Lagos State Malaria Elimination
  Programme; any prior track record of fielding an intervention (not just
  shipping code).
- **Lived experience / community connection** (scored 4b) is currently weak:
  a US-based lead. If the lead is Nigerian by origin, *say so explicitly and
  prominently* — GCC weights this.

**Fix:** add 2–3 named collaborators before submission, even informally
confirmed: (1) a Lagos malaria epidemiologist / entomologist, (2) a
biostatistician for the MEL, (3) an LSPHCDA or LASEMA focal point. Each can be
a fractional collaborator; their *presence and letters* are worth more to the
score than any code you could write in the remaining days.

---

## H. Budget fit — **feasible but currently un-scoped**

CAD/USD 200k over 18–24 months is realistic for this scope **if** it's spent
on people and fieldwork, not engineering (the software is largely built —
which is actually a fundable strength: you're asking for pilot money, not
build money). Likely cost structure and the items that blow budgets:

| Category | Realistic call | Risk |
|---|---|---|
| Remuneration (Nigerian PI, field coord, part-time epi/biostat) | 45–55% | Under-costing local salaries |
| Subcontract: MEL/biostatistics + entomology validation | 12–18% | Often forgotten |
| CHEW stipends / airtime / training | 10–15% | **Most-underestimated line** — training dozens of CHEWs across 5 LGAs is real money and time |
| Goods: buffer stock of nets/RDTs for pre-positioning | 8–12% | If commodities aren't from LSPHCDA pipeline, you must buy them |
| SMS (Africa's Talking) | <2% | Genuinely cheap — a real strength |
| DHIS2 integration / data access | 2–4% | Mostly staff time |
| Travel (LGA field visits, LSPHCDA) | 5–8% | Underestimated |
| Indirect (max 10%) | ≤10% | Fine |

**The line most likely to be criticised:** CHEW **training and stipends** —
reviewers with field experience know onboarding and sustaining a CHEW cohort
is the expensive, slow part, and applicants routinely under-budget it. Africa's
Talking SMS volume is *not* a budget risk (it's your cheapest input — lean into
that as value-for-money). Show the panel you understand where the real money
goes: humans and commodities, not servers.

---

## I. Competitive differentiation — **moderate; needs sharpening**

Reviewers *will* have seen: the **WHO/WMO Malaria Early Warning System (MEWS)**
concept, **EWARS** (Early Warning and Response System, dengue/climate, WHO-
TDR), the **INFORM** risk index, IRI/Columbia malaria-climate models, and the
**Malaria Consortium's SMC** programmes. You must differentiate crisply:

- **vs. INFORM / MEWS / IRI models:** those are **coarse (district/national,
  monthly) risk indices for planners.** FloodSight is **200 m, daily,
  event-triggered, and dispatches an individual actionable SMS to a named
  CHEW.** Your differentiator is **spatial-temporal resolution + last-mile
  actuation**, not the risk model per se. Say exactly this.
- **vs. EWARS:** EWARS is dengue-led, alarm-signal focused, and largely a
  surveillance dashboard. You add the **flood-inundation mechanism** and the
  **pre-positioning action loop.**
- **vs. Malaria Consortium SMC:** SMC is *seasonal, scheduled chemoprevention*
  — calendar-driven. You are **event-driven** (a specific flood), which is
  genuinely novel and climate-adaptive in exactly the way Nexa's framework
  rewards ("newer vector management strategies that are more climate-
  resilient" is a *named example* in the RFP).

**The honest risk:** your flood→malaria *specificity* (A) is what makes you
different **and** what's least proven. Differentiation and scientific
vulnerability are the same axis. Lead with the resolution/actuation
differentiator, treat the mechanism as the PoC hypothesis.

---

## J. Top 3 killer risks (12-month horizon)

1. **Eligibility failure / no local anchor (highest).** If the applying entity
   isn't truly incorporated in Nigeria, or LSPHCDA never engages, the project
   has no legal standing and no outcome data. *Mitigation as written:
   inadequate* — both are "pending." **Must be resolved before submission for
   #1; within Month 2 for the partnership, with a letter now.**
2. **The intervention never reaches a human in time to matter.** CHEW
   enrolment + commodity pathway + first real flood cycle is a long chain with
   no piece yet proven, and the Lagos rainy season is time-boxed. Miss the
   2026 season and you lose ~half your evidence window. *Mitigation as written:
   none.* Needs a dated enrolment plan and a commodity source.
3. **The health signal is undetectable (scientific + MEL).** Low Lagos
   transmission + underpowered n=10 DiD + mistimed outcome + *Culex* confounder
   means a null or perverse result is the *likely* outcome even if the system
   works operationally. *Mitigation as written: none.* Needs the D-section MEL
   pivot to operational/intermediary outcomes so the PoC can "succeed" on
   feasibility even if the case-count signal is noisy.

---

## K. Overall fundability verdict — **YES, WITH CONDITIONS**

At the **Innovation Screen** (the 80%-cull), FloodSight is genuinely
competitive: it's squarely on a named area of focus (climate-informed EWS),
targets a named priority outcome (malaria via changing mosquito ecology), and
— rare among applicants — has a **live, deployed, tested system.** That
combination gets you past the screen that kills most.

At **Peer Review**, as currently written, it would land **mid-pack and
probably below the funding line**, dragged down by three things in order:
**(1) eligibility/local-ownership (E+G), (2) MEL rigour (D), (3) the
unvalidated vector-ecology link (A).**

**The single most important thing to fix before 22 July:**

> **Convert this from a solo US-based software project into an eligible,
> Nigerian-anchored, health-partnered team — starting with confirmed Nigerian
> incorporation of the applicant entity and at least a letter of support from
> LSPHCDA (or the Lagos State Malaria Elimination Programme) plus one named
> Nigerian malaria/health-systems co-investigator and one MEL/biostatistician.**

Incorporation is binary pass/fail; the rest lifts you from "interesting demo
by an outsider" to "fundable, locally-led PoC." The code is already ahead of
the field — that is not what's holding you back. **People and legitimacy
are.** Everything else in this critique is a refinement you can make in the
proposal text; this one is existential.

If you can only do three things this week: (1) incorporation, (2) LSPHCDA
letter + Nigerian co-PI, (3) rewrite the MEL primary outcome around
operational/intermediary indicators with DHIS2 case data demoted to an
exploratory early signal.

---

## Revised "Project Overview" paragraph (for the Fluxx form)

> FloodSight Health is a climate-informed early-warning and monitoring system
> that converts satellite flood forecasts into anticipatory malaria action for
> Lagos's most flood-exposed communities. Heavy rainfall and flood inundation
> create standing water and, in the weeks that follow, elevated malaria
> transmission risk — a climate-to-health pathway that is intensifying as
> extreme rainfall increases. FloodSight already runs a live, tested pipeline
> that scores flood hazard across 15 Lagos LGAs at 200 m resolution from
> free NASA satellite data; this project extends it into a health-response
> layer that, when flooded cells cross a risk threshold, sends a plain-language
> SMS to Community Health Extension Workers so they can pre-position bed nets
> and rapid diagnostic tests ahead of the anticipated case rise, and report
> back by return SMS. Working in partnership with the Lagos State Primary
> Healthcare Development Authority and local malaria expertise, the 18-month
> proof of concept will test whether the system is operationally feasible,
> trusted, and acted upon by frontline workers, and will generate early signals
> of health impact — measuring alert-to-action time, the share of alerts that
> trigger timely commodity pre-positioning, and, as an exploratory outcome,
> malaria trends in DHIS2 for served versus comparison LGAs. As a bold, still-
> unproven idea built on open data and existing government health infrastructure,
> FloodSight Health offers an event-driven, climate-adaptive alternative to
> calendar-based malaria programmes, with a portable core that can be
> re-targeted to other flood- and malaria-exposed African cities.

*(Trim to the form's character limit — this runs ~1,750 characters; the PoC
"Project Overview"/Q1–Q2 fields are 1,500–2,000 each, so it fits Q2 with
light editing.)*
