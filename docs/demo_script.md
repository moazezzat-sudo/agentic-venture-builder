# Demo scripts

Two scripts for the founder web app at `http://localhost:8000`: **A**, the 3-minute live demo with the football idea, and **B**, a weak idea (a messaging app with reactions) that ends in STOP. We follow them at 21:00 (the recorded demo runs) and for the video at 22:30.

**Say what the screen shows, never what this script expects.** Scores depend on the model and on what the web search finds that minute. If a gate recommends something other than what is written here, read out the real recommendation and its reasons. That honesty is part of the demo.

The two briefs below were written for this script: confirm their wording as a team before 21:00. They have not been through `evals/briefs/` yet, so do the warm-up run (below) to see what they get.

## Which gates the demo shows

All six phases are wired into the run, each ending at its own founder gate, but a full run takes
about a minute of machine time on Groq (20,915 tokens; `evals/briefs/RESULTS.md`) and longer on a
local model. So the live demo shows only **Gate 1** (and the niche gate if Gate 1 is GO): the decision
judges care about most and the founder approval step.

Set the sidebar's **Demo setting → Stop the demo after Phase** to **1** (or start the app with
`APP_STOP_AFTER_PHASE=1`). Then GO at the last Phase 1 gate is not sent: the app says so and the run
stays paused, so Phases 2 to 6 cannot start on stage.

The later gates (2: waitlist, 3: build plan and the real build of the landing page, product and docs,
4: commercial, 5: launch and the MOCKED sale to cash, 6: memo) are shown, if at all, from an earlier
run opened by its id (sidebar: **Open an earlier run**), not run live.

## Before you start (10 minutes earlier)

1. Start the app the way it will be demoed: native Ollama with `docker compose up --no-deps app`, or Groq (see `docs/docker_check.md`). Check the model under **Run details** at the bottom of the page.
2. **Warm up:** run brief **A** once up to the gate. This loads the model (kept 30 minutes) and fills the search cache, so the live run is faster.
3. Before the recorded runs, clear the test output so that only demo runs are committed:

   ```powershell
   Remove-Item decision_log.json -ErrorAction SilentlyContinue
   Get-ChildItem outputs -Filter "phase*" | Remove-Item
   ```

   Keep `outputs/payment_test_log.md` (it is committed). Run the warm-up before this step, not after.
4. Keep a second tab with the warm-up run open (**Open an earlier run**; its id is under **Run details**). If the live model is slow, switch to it and say so.
5. Browser at least 1280 px wide, so the verdict, the headline and the "Why" fit on one screen.

## A. Live demo, 3 minutes: the football idea

**Brief A** (type only these two; leave the rest blank so the question cards appear):
- Idea: `An app that lets amateur five-a-side football players in Cairo find a pitch, book it and fill missing players for tonight's game`
- Location: `Cairo, Egypt`

| Time | Do | Say (short) | Point at |
|---|---|---|---|
| 0:00 | The empty page. | "A founder brings an idea. An AI cofounder checks it against rated sources, scores it on a fixed rubric, and the founder decides at every step." | The stepper: **Discover** first, Validate to Learn after it, with small **STUBBED** / **MOCKED** badges. "We label what isn't real." |
| 0:15 | Type brief A, click **Start Phase 1**. | "Only the idea is required." | |
| 0:25 | The question cards. | "It says what it understood and asks only what's missing, and why." | **Here's what I understood** (when shown), a **Why I ask** line. Click a **suggestion chip** to answer one; pick a choice on another. Click **Send and start the research**. |
| 0:45 | The progress box. | "It's searching for people who have this problem in Egypt, and for who already solves it, rating every source as it goes." | The live status line. |
| 1:05 | The evaluation. | "First the verdict, then a one-line headline, then why." | The **verdict badge**, the headline, the **Why** bullets. Click one **[C…]** citation: it opens the source. |
| 1:25 | Criterion cards (or the reasons). | "Every score shows its evidence, what speaks against it, and what would change it." | One card: the score bar, **Against:**, **What would change this score**. |
| 1:40 | **What we don't know yet**, **What to do next**, then the **Evidence** tab. | "It says what it doesn't know. Every claim has a tier, A official to D forum, or says no source found." | A **Tier A** World Bank figure, a lighter **Tier D** forum post, a **No source found**. Expand **What I searched and why**. |
| 2:05 | Decision: choose **Request changes**, type `Check the pitch-booking apps already used in Cairo`, click **Record my decision**. | "Nothing moves on without the founder. I can approve, reject and pick another outcome, or ask for changes with a note." | The button stays grey until a choice (and, for changes, a note). |
| 2:25 | The next questions appear. | "It goes back to work on what I asked." | "At Gate 1 I recommended … and you chose REPEAT (your note: …)". |
| 2:40 | Open **Run details**. | "For reviewers: the run id, the tokens, $0.00, every step in the decision log." | **Model tokens**, **Cost**, the log. |
| 2:55 | End. | "It recommends; the founder decides." | |

If the gate says **STOP** instead, approve it and show the finished screen as in script B; the point is the same.

## B. Weak idea, ends in STOP, about 1.5 minutes

**Brief B:**
- Idea: `A messaging app for friends where you can react to messages with emojis`
- Your skills: `python`
- Budget: `100 USD`
- Location: `Egypt`
- Time available: `10 hours a week`
- Target market: `university students`
- Do you have a team?: `No`

| Time | Do | Say (short) | Point at |
|---|---|---|---|
| 0:00 | Sidebar: **Start a new brief**. Type brief B, click **Start Phase 1**; answer any question card. | "Now an idea that sounds fine but shouldn't be built." | |
| 0:20 | The progress box. | | |
| 0:40 | The evaluation. | "It recommends STOP, and says why." | The **STOP** badge, the headline, the **Why** bullets (expected: big free apps already do exactly this, so competition and willingness to pay are weak). |
| 0:55 | The **Evidence** tab. | "Here is what it found." | The competitor claims with their tiers and links. |
| 1:05 | **Approve: STOP**, **Record my decision**. | "The founder agrees. Nothing was built or spent." | |
| 1:15 | The finished screen. | "A short summary for the founder: where we stopped and every decision." | **We stopped here**, the **Your decisions** table. Open **Run details** → the output files, for example `outputs/phase1_gate_decision.md`. |
| 1:30 | End. | | |

**Optional, 10 seconds:** brief `A mobile app that lets people buy fractions of Bitcoin with their phone credit` stops at once, before any research: crypto products are banned.

## Words to use and to avoid

- Say "scored against our rubric", never "validated".
- Say "we rate every source and show the rating", never "we only use credible sources".
- Never promise income or success, and never call a STUBBED or MOCKED part real.
- Phases 2–6 run after the niche gate, each with its own founder gate, but their outputs are labelled STUBBED drafts and the sale to cash is MOCKED: say so if asked.

## After the recorded runs (21:00)

1. Keep the browser on the finished screen until the files are checked.
2. Commit only the demo runs:

   ```powershell
   git add decision_log.json outputs/
   git status
   git commit -m "Demo runs: football idea and weak idea (stop)"
   ```

   `git status` must show only `decision_log.json` and the `outputs/phase*` files of these runs (plus `payment_test_log.md` if the sale to cash was run).
