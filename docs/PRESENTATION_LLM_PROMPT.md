# Copy-Paste Prompt for Another LLM

I need you to create a technically defensible presentation for a Python hybrid renewable energy simulation and optimization project.

Use the attached `PRESENTATION_MASTER_BLUEPRINT.md` and the project source code as the factual basis. Do not invent features, equations, validation results, or HOMER Pro parity.

## Required output

Create a 30–35 slide presentation with:

1. Slide title.
2. Concise slide content.
3. Equations in readable mathematical notation.
4. Speaker notes explaining the slide in detail.
5. Suggested diagram/chart/table for each slide where useful.
6. Likely viva/panel questions and short answers after every major module.

## Required sequence

1. Problem statement and motivation.
2. Objectives and scope.
3. End-to-end software architecture.
4. Project setup and economics inputs.
5. Load import/generation, variability, scaling, and resampling.
6. NASA POWER resource acquisition and validation.
7. Solar geometry and clearness index.
8. Erbs decomposition and HDKR plane-of-array irradiance.
9. PV cell temperature and PV output.
10. Wind hub-height correction, power curve, density, and losses.
11. Converter AC/DC equations and shared-capacity logic.
12. Battery SOC, efficiencies, limits, self-discharge, degradation, and SOH.
13. Grid import/export and current tariff model.
14. Renewable-first dispatch sequence.
15. Time-step energy-balance equation.
16. Annual KPI calculations.
17. Fisher equation, CRF, replacement, salvage, NPC, and LCOE.
18. Candidate generation and parallel simulation.
19. Capacity shortage, renewable fraction, and operating-reserve constraints.
20. Candidate ranking and selected results.
21. Validation methodology and exact current test results.
22. Problems encountered and fixes.
23. Known mismatches and limitations.
24. Prioritized future roadmap.
25. Final conclusion.

## Accuracy rules

For every formula or claim, mark it as one of:

- HOMER-aligned.
- HOMER-inspired simplification.
- Project-specific.
- Planned/not yet implemented.

Explicitly preserve these current validation facts:

- Automated suite: 188 passed, 4 failed, 192 total.
- HOMER-style comparison: 79 passed, 2 failed, 81 total.
- NPC ranking scenario: 9 passed, 1 failed, 10 checks total.
- Direct HOMER hourly-export validation is not complete.

Explicitly explain the known issues:

- Two project tests use outdated economics constructor field names.
- Two optimization tests use one-year load data with two-year resource data.
- The full-year `test_3` PV reference is inconsistent with current solar geometry, likely because of resource timestamp semantics and a stale reference.
- The current capacity-shortage KPI is unmet-load energy divided by load energy, while HOMER’s documented capacity shortage also includes reserve shortfall.
- The current battery throughput convention differs from HOMER’s published stored-energy-change definition.
- The code’s LCOE denominator includes grid exports, while current HOMER Pro documentation describes served electrical load; this requires a controlled export-case benchmark.
- PV tracking modes, MPPT efficiency tables, real-time tariffs, demand charges, grid outages, and emissions reporting are not yet operational.

## Tone

Write as if the presenter built the project and understands the engineering decisions. Keep it honest, confident, and suitable for a technical viva. Do not hide failed tests; explain what they reveal and how they guide the next validation work.

## Visual requirements

Include:

- One complete architecture diagram.
- One AC/DC bus diagram.
- One PV calculation flowchart.
- One battery SOC/degradation flowchart.
- One dispatch sequence diagram.
- One optimization flowchart.
- One validation matrix.
- One “problem → cause → fix → evidence” table.
- One limitations and roadmap table.

End with:

- A one-minute conclusion script.
- A five-minute project summary script.
- A list of 25 likely viva questions with model answers.
