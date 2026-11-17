# Demo scripts

Two scripts for the founder web app at `http://localhost:8000`: **A**, the 3-minute live demo, and **B**, the weak-idea run that ends in STOP. We follow them at 21:00 (the recorded demo runs) and for the video at 22:30.

The briefs come from `evals/briefs/briefs.json`. Their Gate 1 results on Groq are in `evals/briefs/results.md`. On the local model the scores can differ, so **say what the screen shows, never what this script expects.** If a gate recommends something other than what is written here, read out the real recommendation and its reasons. That honesty is part of the demo.

## Before you start (10 minutes earlier)

1. Start the app the way it will be demoed: native Ollama with `docker compose up --no-deps app`, or with Groq (see `docs/docker_check.md`). The sidebar shows the provider and model; check them.
2. **Warm up:** run brief **A** once and stop at the gate. This loads the model into memory (kept 30 minutes) and fills the search cache, so the live run is faster.
3. Before the recorded runs, clear the test output so that only demo runs are committed:

   ```powershell
   Remove-Item decision_log.json -ErrorAction SilentlyContinue
   Get-ChildItem outputs -Filter "phase*" | Remove-Item
   ```

   Keep `outputs/payment_test_log.md` (it is committed), and run the warm-up before this step, not after.
4. Have a second browser tab ready, with the warm-up run open through **Open an earlier run**. If the live model is slow, switch to that tab and say so.
5. Use a window at least 1280 px wide, so the gate card and its reasons fit on one screen.

## A. Live demo, 3 minutes: a promising idea (S3)

| Time | Do | Say (short) | Point at |
|---|---|---|---|
| 0:00 | The empty page. | "A founder brings an idea. Agents check it against rated sources and score it on a fixed rubric. The founder decides at every gate." | The phase line: **Discover LIVE**, the others **STUBBED**, Sell **MOCKED**, with the legend under it. "We label what is real." |
| 0:15 | Type the brief (below), click **Start Phase 1**. | "Only the idea is required. The intake agent asks for what is missing." | |
| 0:30 | Intake questions appear. Type `no` for teammates (and anything else asked), click **Send answers and start the research**. | "The answers feed the founder-fit and feasibility scores." | |
| 0:40 | The progress box runs. | "One researcher per business area searches free sources. Every source gets a rating, A for official, D for forums." | The live status line and the seconds counter. |
| 1:00 | The gate card appears. | "The gate recommends; plain Python decides the outcome from the rubric, not the model." | **Gate 1 recommends …**, the score with the go/stop cut-offs, the reasons. |
| 1:20 | Open the **Evidence** tab. | "Every claim has its link and tier, or says ASSUMPTION." | A **Tier A** World Bank figure, a **Tier D** community signal, an **ASSUMPTION**. Click one **source** link. |
| 1:40 | Open **Scorecard**. | "Seven criteria, fixed weights, written down before the run." | The weights and the reasons. |
| 1:55 | In the gate card: **Reject and choose another outcome**, choose REPEAT (or the outcome you want to show), type a note, click **Record my decision**. | "Nothing moves on without the founder. The button stays grey until I choose, and my decision is logged as approved_by: founder." | The greyed button, then the decision. |
| 2:20 | The coach's questions appear. | "On repeat, a coach asks what would close the evidence gap." | The line "the system recommended … and you chose …". |
| 2:35 | Sidebar. | "This run cost $0.00, about 6,000 tokens, all in decision_log.json." | **Tokens** and **Cost**. |
| 2:45 | Scroll to **Phases 2–6**, open **5. Sell/deliver/get paid**, click **Run the mocked sale to cash**. | "Selling is MOCKED: fake events, no payment provider, no money. Payment triggers delivery, a duplicate is ignored, a refund revokes access, and it all reconciles." | **MOCKED** badge, "12/12 steps passed". |
| 3:00 | End. | | |

**Brief A (S3):**
- Idea: `A CV and portfolio builder for fresh graduates`
- Your skills: `react, technical recruiting`
- Budget: `300 USD`
- Location: `Egypt`
- Time available: `15 hours a week`
- Target market: `final-year university students`
- Do you have a team?: `No`

On Groq this brief got **REPEAT** (score 2.05). If it gets **STOP** live, approve the stop instead and use script B's ending; the point is the same.

## B. Weak idea, ends in STOP (W1), about 1.5 minutes

| Time | Do | Say (short) | Point at |
|---|---|---|---|
| 0:00 | Sidebar: **Start a new brief**. Type brief B, click **Start Phase 1**; answer `no` if asked about teammates. | "Now an idea that sounds fine but shouldn't be built." | |
| 0:20 | The progress box runs. | | |
| 0:40 | The gate card appears. | "The system recommends STOP and says why." | **Gate 1 recommends STOP** and the reasons, for example "competition scored 0, which stops the idea whatever the total". |
| 0:55 | **Evidence** tab. | "It found that free tools already do this." | The competitor claims (on Groq: iLovePDF's free converter, **Tier B**). |
| 1:05 | **Approve: STOP**, **Record my decision**. | "The founder agrees; the run ends here, and nothing was built or spent." | |
| 1:15 | The finished screen. | "Every gate decision, the tokens and cost, and every file this run wrote." | **Run stopped**, the **Every gate decision** table, **Model tokens**, **Output files of this run**. Open `outputs/phase1_gate_decision.md`. |
| 1:30 | End. | | |

**Brief B (W1):**
- Idea: `A website that converts PDF files to Word documents`
- Your skills: `python`
- Budget: `100 USD`
- Location: `Egypt`
- Time available: `10 hours a week`
- Target market: `university students`
- Do you have a team?: `No`

On Groq this brief got **STOP** (score 1.75 in the eval, 1.15 in a later app run), with problem evidence and competition both at 0.

**Optional, 10 seconds:** brief `A mobile app that lets people buy fractions of Bitcoin with their phone credit` stops at once, before any research: crypto products are banned.

## Words to use and to avoid

- Say "scored against our rubric", never "validated".
- Say "we rate every source and show the rating", never "we only use credible sources".
- Never promise income or success, and never call a STUBBED or MOCKED part real.
- Phases 2–6 are drafts that are not wired into the run yet: say so if asked.

## After the recorded runs (21:00)

1. Keep the browser open on the finished screen until the files are checked.
2. Commit only the demo runs:

   ```powershell
   git add decision_log.json outputs/
   git status
   git commit -m "Demo runs: promising idea (repeat) and weak idea (stop)"
   ```

   `git status` must show only `decision_log.json` and `outputs/phase1_*` files from these two runs (plus `payment_test_log.md` if the sale to cash was run).
