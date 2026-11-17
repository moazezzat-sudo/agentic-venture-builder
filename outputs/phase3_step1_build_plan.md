> **STUBBED**: this output comes from a stubbed step, not a working feature.

# Phase 3, step 1: architect, UI/UX and MVP plan

Draft for the founder to review and approve. Every claim shows its support: a source URL with its tier, our own evidence, or ASSUMPTION.

Every item below is a proposal for the founder to approve, change or reject. Stack and design choices are design choices, not market claims.

## Architect

| Component | Choice | Why |
|---|---|---|
| backend | FastAPI (Python) | Founder knows Python, fast to develop REST APIs, open‑source and can run locally. |
| frontend | HTMX with Tailwind CSS | Minimal JavaScript, integrates easily with FastAPI templates, reduces development time. |
| database | SQLite | Zero‑config, fits the budget, and sufficient for early SaaS with limited data. |
| email | SMTP via founder's existing email provider | No extra cost, simple to configure, handles candidate notifications. |
| hosting | VPS (founder creates the account) | Low monthly cost, full control, runs Linux, can host FastAPI + SQLite. |

Database: **SQLite**. Matches brief requirement, no external service fees, easy backup.

Any hosted service above (hosting, email, analytics) needs an account the founder creates; its prices and limits must be checked on the provider's own site. The system never creates accounts or handles keys.

## UI/UX

### User flows

- HR logs in → creates interview slot template → publishes candidate booking link
- Candidate opens link → selects preferred slot → receives confirmation email
- HR receives notification → confirms or adjusts slot → final schedule stored
- HR views calendar → exports schedule as CSV for reporting

### Screens

- **Login**: Authenticate HR users and restrict access to their team's data
- **Dashboard**: Overview of upcoming interviews, quick actions to create slots
- **Create Interview Template**: Define interview type, duration, participants, and available time windows
- **Candidate Booking Page**: Public link where candidates pick a slot and submit contact info
- **Calendar View**: Visual schedule of all confirmed interviews for the HR team
- **Settings**: Manage team members, email SMTP settings, and export options

## MVP plan

Weakest Phase 1 criteria (what the evidence left most uncertain):

- problem_evidence: 1 of 4. Only one low‑tier source shows manual scheduling; no strong data on frequency or cost.
- market: 1 of 4. Population and internet use are given, but no data on number of target SME HR teams.

Riskiest assumption:

- HR teams consider manual interview scheduling painful enough to pay for a SaaS solution. (ASSUMPTION)

Features:

- User authentication for HR team members
- Interview slot creation with configurable duration
- Public candidate booking link with email confirmation
- Automatic calendar sync (iCal) for HR
- Basic CSV export of scheduled interviews

Out of scope for the MVP:

- SMS or WhatsApp reminders
- AI‑driven candidate matching or ranking
- Multi‑language UI beyond Arabic/English
- Integrated payment gateway (subscription billing)
- Advanced analytics dashboard

How the MVP tests the assumption: Run a 4‑week pilot with 2‑3 local SMEs, measure reduction in scheduling errors and time spent versus spreadsheet/email process.

## Feasibility for this founder

- 20 h/week × 8 weeks ≈ 160 h of development fits within founder's available time. (ASSUMPTION)
- Budget $800 covers VPS hosting and domain; all other tools are free/open‑source. (ASSUMPTION)
- Founder’s Python and HR operations experience aligns with FastAPI backend and understanding of scheduling pain points. (ASSUMPTION)

These are estimates, not promises.

## Not built yet

- Coder and tester agents (generate the MVP and run its tests): **STUBBED**
- Docs writer (user documentation): **STUBBED**
- Team builder (roles, form, blind scoring, interview guide): **STUBBED**


## Claims

0. HR teams consider manual interview scheduling painful enough to pay for a SaaS solution. (riskiest_assumption; ASSUMPTION)
1. 20 h/week × 8 weeks ≈ 160 h of development fits within founder's available time. (feasibility; ASSUMPTION)
2. Budget $800 covers VPS hosting and domain; all other tools are free/open‑source. (feasibility; ASSUMPTION)
3. Founder’s Python and HR operations experience aligns with FastAPI backend and understanding of scheduling pain points. (feasibility; ASSUMPTION)

## Guardrail check

None: every text in this draft passed `guardrails.check_text`.
