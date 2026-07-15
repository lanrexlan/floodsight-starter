# Prompt: Independent Critique of FloodSight Health for NEXA Grant

Copy the entire block below and paste it to another AI (GPT-4o, Gemini, Claude, etc.).

---

## PROMPT START

You are a senior grants evaluator with deep expertise in global health innovation, climate-health research, and innovation financing for sub-Saharan Africa. You have previously reviewed applications for Grand Challenges Canada (GCC), the Science for Africa Foundation (SAF), Wellcome Trust, and BMGF. You know what separates funded proposals from rejected ones.

I am going to describe a proof-of-concept innovation and ask you to critique it rigorously against the NEXA grant requirements. Be brutally honest. Do not hedge. If something is weak, say so specifically and explain why a reviewer would penalise it. If something is strong, explain exactly what makes it compelling to a GCC/SAF panel.

---

### About the NEXA Grant

NEXA is a joint programme of Grand Challenges Canada and the Science for Africa Foundation. It funds **proof-of-concept (PoC)** innovations at the climate-health nexus in sub-Saharan Africa. Key criteria:

1. **Clear climate-health causal pathway** — a demonstrable mechanistic link between a climate event and a health outcome. Reviewers want peer-reviewed evidence for every step of the causal chain.
2. **Proof-of-concept stage** — a working technical prototype, not just a concept. The system must demonstrate technical feasibility. Reviewers look for live data, deployed code, and real outputs.
3. **Last-mile delivery** — the intervention must reach underserved populations, ideally through community health workers or existing government systems (not smartphone apps that assume connectivity or literacy).
4. **Rigorous MEL (Monitoring, Evaluation & Learning)** — GCC requires quasi-experimental or RCT design where possible. A vague "we'll track impact" will fail. Reviewers want: comparison group, primary outcome metric, statistical analysis plan, data source, and analysis timeline.
5. **Local ownership and system integration** — the applicant must be legally incorporated in sub-Saharan Africa (Nigeria in this case). The intervention must integrate with existing government health infrastructure (e.g. DHIS2, community health worker networks, ministry of health data systems), not bypass them.
6. **Scalability pathway** — the PoC must have a credible route to scale beyond the pilot: other cities, other diseases, national replication.
7. **Budget justification** — up to CAD $200,000 over 18–24 months. Reviewers scrutinise whether the scope is achievable in the timeline and budget, and whether the team has the capacity to execute.
8. **Team credibility** — who is building this, and can they actually do it? Academic or industry affiliations, relevant expertise, local partnerships.

---

### The Innovation: FloodSight Health

**One-line pitch:** FloodSight Health converts flood predictions into malaria outbreak warnings, alerting Community Health Extension Workers (CHEWs) via SMS 17–24 days before case spikes so they can pre-position bed nets and rapid diagnostic tests.

**The causal chain:**

```
Heavy rainfall (climate event)
    → Flood inundation (stagnant water, 5–14 days standing)
    → Anopheles gambiae larval habitat (200 m² grid cells at Watch/Warning level)
    → Larval development at 26–32 °C Lagos temperatures: 8–14 days [Bayoh & Lindsay 2003, Malaria Journal]
    → Adult mosquito emergence → biting begins
    → Malaria case spike in high-density residential LGAs
    → 17–24 day confirmed flood-to-case lag [Oduola et al. 2012, Acta Tropica; Edeghere et al. 2018, Malaria Journal]
    → FloodSight Health alert → CHEW pre-positions nets + RDTs before the spike
```

**Technical stack (all live and deployed):**

- **Flood model:** NASA IMERG satellite rainfall → 24,933-cell 200 m grid → hazard_score + alert_levels (No Alert / Watch / Warning) per cell. Covers 15 Lagos LGAs. Running live at https://floodsight-starter.onrender.com
- **Outbreak engine:** Logistic model — z = −2.1 + 0.45×inundation_km² + 2.80×peak_susceptibility + 1.20×temp_factor; outbreak probability = 1/(1+exp(−z)). Risk tiers: Low (<30%), Moderate (30–55%), High (55–75%), Critical (>75%).
- **Temperature adjustment:** Open-Meteo free API for same-day 2 m temperature. Breeding lag from Bayoh & Lindsay (2003) lookup table (8–14 days at 26–32 °C).
- **CHEW SMS alerts:** Africa's Talking API. ≤160 char messages in English. CHEWs reply: CONFIRM / REPORT N (case count) / HELP. SHA-256 idempotency prevents double-sends.
- **MEL logging:** All CHEW actions logged to Supabase (NETS_DISTRIBUTED, RDT_KITS_PREPOSITIONED, IRS_CONDUCTED, etc.). DHIS2 monthly case data pull for outcome comparison.
- **GitHub Actions cron:** Runs daily at 07:30 WAT. If pilot LGAs reach Watch or Warning, scores outbreak probability, stores results, dispatches CHEW alerts.
- **Dashboard:** Live ops dashboard at /dashboard/health/ (Supabase + Chart.js). Public showcase at https://www.rankineinnovationlab.com/health.html

**MEL Design:**

Quasi-experimental difference-in-differences (DiD) across 10 Lagos LGAs:

- **Treatment arm (5 LGAs):** Alimosho, Ajeromi-Ifelodun, Kosofe, Oshodi-Isolo, Ikorodu — receive CHEW health alerts at Moderate/High/Critical risk
- **Control arm (5 LGAs):** Agege, Mushin, Surulere, Lagos Mainland, Ikeja — receive standard flood alerts only
- **Primary outcome:** Reduction in confirmed malaria cases per 100,000 population in treatment vs. control LGAs in the 12 weeks following each flood event
- **Data source:** DHIS2 (Nigeria District Health Information System 2) via API pull
- **Analysis:** DiD regression at Month 18, controlling for rainfall severity, season, LGA fixed effects
- **CHEW response KPI:** ≥60% CONFIRM rate within 48 hours of alert

**Team and partnerships:**
- Principal: Habeeb Adegoke, Rankine Innovation Lab (ASU affiliation)
- Target partnership: Lagos State Primary Healthcare Development Authority (LSPHCDA) for CHEW roster and DHIS2 access
- Incorporation: Nigeria (required for NEXA eligibility — status pending confirmation)

**Current gaps / honest limitations:**
- DHIS2 org unit UIDs are placeholders — real UIDs require LSPHCDA formal onboarding (targeted Month 2)
- No CHEWs enrolled yet — the subscriber list (`chew_subscribers` table) is empty
- Logistic model coefficients are based on 8 historical Lagos flood-malaria event pairs, not a formal regression dataset
- LSPHCDA MOU not yet signed
- Nigerian incorporation not confirmed (requirement for GCC eligibility)
- OTP/two-way SMS not tested beyond sandbox
- Rainfall-to-flood calibration relies on ERA5 reanalysis (known 30–60% underestimation of convective rainfall)

---

### Your Critique Task

Please evaluate this innovation against the NEXA criteria above and answer the following questions. Be specific. Quote weaknesses as a real reviewer would frame them on a scorecard. Suggest concrete fixes where applicable.

**A. Causal chain credibility (1–10)**
Does the climate → flood → mosquito → malaria → CHEW → prevention chain hold up to scientific scrutiny? Are the cited papers (Bayoh 2003, Oduola 2012, Edeghere 2018) sufficient? What would a malaria epidemiologist challenge?

**B. Proof-of-concept maturity (1–10)**
Is this genuinely PoC-stage or is it still a concept? What evidence of working technical system would a GCC reviewer accept? What is missing that would block a pass here?

**C. Last-mile delivery design (1–10)**
Is SMS-based CHEW alerting the right mechanism? What would a health systems reviewer say about the CONFIRM/REPORT N/HELP protocol? Is there evidence this works in Lagos-level CHEW programs?

**D. MEL rigor (1–10)**
Is the DiD design credible for a PoC grant? Is 18 months sufficient to see a malaria reduction signal? What are the power/sample size issues? What would a biostatistician say about using DHIS2 data as the outcome measure?

**E. Local ownership and system integration (1–10)**
Does the absence of a signed LSPHCDA MOU and real DHIS2 UIDs constitute a fatal flaw for NEXA? What does GCC's track record suggest about how strictly they enforce government partnership requirements at PoC stage?

**F. Scalability pathway (1–10)**
How credible is the scale story beyond Lagos? Can the 200 m grid be redeployed for Kano, Ibadan, or Nairobi? What would make reviewers believe this is a platform, not a one-city project?

**G. Team credibility gap**
Is an ASU-affiliated researcher with a Nigerian address credible for a GCC Nigeria-incorporation requirement? What signals of execution capacity are missing?

**H. Budget fit**
Is this realistic for CAD $200,000 over 18–24 months? What cost items are likely to blow the budget (CHEW training, DHIS2 integration, travel, Africa's Talking SMS volume)?

**I. Competitive differentiation**
What other flood-health early warning systems are GCC/SAF likely to have seen? How does this differentiate from WHO/UNICEF malaria early warning tools, from INFORM risk index, from the Malaria Consortium's existing seasonal malaria chemoprevention programs?

**J. Killer risks**
List the top 3 risks that could cause this project to fail within 12 months, and assess whether the current mitigation (if any) is adequate.

**K. Overall fundability verdict**
Would you fund this at PoC stage under NEXA? Give a clear YES / YES WITH CONDITIONS / NO and explain what the single most important thing is that the team must fix or clarify before submission on July 22, 2026.

---

## PROMPT END

*After pasting this prompt to the AI, ask it to also produce a revised one-paragraph project summary you can use in the NEXA application form's "Project Overview" field, incorporating its own critique.*
