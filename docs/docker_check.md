# Fresh-clone Docker check

Procedure for two checks from a fresh clone on the demo laptop (Windows, Docker Desktop, native Ollama for Windows). This document is a checklist, not a completed verification record. Record the commit, time and results below after running it:

- **A. Native Ollama:** Docker uses the Ollama already running on the laptop (GPU). This is how the demo runs.
- **B. Bundled fallback:** no `.env` at all, so `docker compose up` starts its own Ollama and downloads the model. This is what someone with nothing installed gets.

Use a disposable clone for these checks. Test runs may overwrite committed demo artifacts in that clone. Keep its logs for diagnosis and never commit them over the submission demo. Do not delete committed artifacts as cleanup.

## A. Native Ollama (the demo setup)

1. **Ollama is running with the model.** In PowerShell:

   ```powershell
   ollama list
   ```

   `qwen3:4b` must be listed. If it is not: `ollama pull qwen3:4b`.

2. **Fresh clone** into a new folder, so nothing from your working copy leaks in:

   ```powershell
   cd $HOME\Desktop
   git clone https://github.com/moazezzat-sudo/agentic-venture-builder.git avb-check
   cd avb-check
   ```

3. **Create `.env`** pointing Docker at the native Ollama (no Groq key):

   ```powershell
   @"
   LLM_PROVIDER=ollama
   OLLAMA_MODEL=qwen3:4b
   OLLAMA_BASE_URL=http://host.docker.internal:11434
   "@ | Set-Content -Encoding ascii .env
   ```

4. **Start only the app** (`--no-deps` skips the bundled Ollama, so nothing extra is downloaded):

   ```powershell
   docker compose up --build --no-deps app
   ```

   Plain `docker compose up` also starts the bundled model download (about 2.5 GB) in the background, even though this configuration uses native Ollama. The app does not wait for that download.

5. **Open** `http://localhost:8000`. The sidebar must say provider `ollama`, model `qwen3:4b`.

6. **Run one brief.** Idea: `A library of printable lesson-plan templates in Arabic for private English tutors in Egypt`, location `Egypt`. Leave the rest blank.
   - Answer the discovery questions, then confirm the summary with **Yes, that's my idea**. Correct it first if needed.
   - A progress box shows each step ("Searching the web and rating every source…") with a seconds counter.
   - The gate card appears: "Gate 1 recommends …", the reasons under it, and the evidence tabs below.
   - If the recommendation is STOP, approve it. Otherwise choose **Reject and choose another outcome**, select STOP, and record the decision. The page shows the stopped result; approving a go or repeat would continue the graph.

7. **Check what was written** (in a second PowerShell window, in `avb-check`):

   ```powershell
   Get-Item decision_log.json
   Get-ChildItem outputs
   ```

   `decision_log.json` must exist in the clone's root (it survives the container), and `outputs/` must have `phase1_*` files.

8. **Run the tests inside the container** (Python 3.12, as Docker runs it):

   ```powershell
   docker compose run --rm --no-deps app python -m pytest -q tests
   ```

   All tests must pass.

9. **Stop** the disposable check environment and inspect changes:

   ```powershell
   docker compose down
   git status
   ```

   `git status` may show modified demo logs and outputs from the check. This is expected in the disposable clone; do not commit them. `.env` must remain ignored.

## B. Bundled Ollama fallback (nothing configured)

1. **Remove `.env`** so the defaults apply, and make sure no `OLLAMA_BASE_URL` is set in the shell:

   ```powershell
   Remove-Item .env
   $env:OLLAMA_BASE_URL = $null
   ```

   The native Ollama may keep running: the bundled one publishes no host port, so they don't clash.

2. **Start everything:**

   ```powershell
   docker compose up --build
   ```

   The app starts at once; it does not wait for the model. On the first start `model-pull` downloads `qwen3:4b` (about 2.5 GB) into the `ollama_data` volume in the background and exits with code 0 when done. Later starts reuse the volume. Follow the download in a second window:

   ```powershell
   docker compose logs -f model-pull
   ```

3. **Open** `http://localhost:8000` right away. The sidebar must say provider `ollama`, model `qwen3:4b`. While the model downloads, the page must show "Local model still downloading: `qwen3:4b` (about 2.5 GB) … `docker compose logs -f model-pull`", with a **Retry** button, and **Start Phase 1** greyed out. When the download finishes, the message goes away by itself within about 15 seconds (or click **Retry**).

   Also check: `docker compose stop ollama` while the app runs must give "The local model server is not answering yet … `docker compose up -d ollama model-pull`", not an error page. Start it again with `docker compose up -d ollama`.

4. **Run the same brief** as in A.6. The bundled Ollama runs on the CPU (no GPU is passed to Docker), so each step is slower than in A; that is expected.

5. **Inspect outputs and stop** as in A.7 and A.9 (`docker compose down` keeps the downloaded model; `docker compose down -v` deletes it).

## Verification record

Commit: not recorded. Checked at: not recorded. Machine: not recorded. No successful fresh-clone run is claimed by this checklist.

| Check | A (native) | B (bundled) |
|---|---|---|
| App opens on `localhost:8000`, sidebar shows `ollama` / `qwen3:4b` | | |
| B only: app opens during the download, shows the download message, unlocks by itself | — | |
| B only: `docker compose stop ollama` gives the "not answering" message | — | |
| Brief → intake questions → progress box → gate card | | |
| Approve/Reject recorded, result shown | | |
| `decision_log.json` in the clone root after the run | | |
| Tests pass in the container (A.8) | | — |
| Time for one run (brief to gate) | | |

If a step fails, copy the last lines of the `docker compose` output into the team chat.
