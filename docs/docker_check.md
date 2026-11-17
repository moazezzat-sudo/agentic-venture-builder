# Docker check (18:00)

Two checks from a fresh clone on the demo laptop (Windows, Docker Desktop, native Ollama for Windows):

- **A. Native Ollama:** Docker uses the Ollama already running on the laptop (GPU). This is how the demo runs.
- **B. Bundled fallback:** no `.env` at all, so `docker compose up` starts its own Ollama and downloads the model. This is what someone with nothing installed gets.

Files a check run writes (`decision_log.json`, `outputs/phase1_*`) are test output: delete them, never commit them. Only the final demo runs are committed.

## A. Native Ollama (the demo setup)

1. **Ollama is running with the model.** In PowerShell:

   ```powershell
   ollama list
   ```

   `qwen3:8b` must be listed. If it is not: `ollama pull qwen3:8b`.

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
   OLLAMA_MODEL=qwen3:8b
   OLLAMA_BASE_URL=http://host.docker.internal:11434
   "@ | Set-Content -Encoding ascii .env
   ```

4. **Start only the app** (`--no-deps` skips the bundled Ollama, so nothing extra is downloaded):

   ```powershell
   docker compose up --build --no-deps app
   ```

   Plain `docker compose up` also works, but it first downloads the bundled model (several GB) even though the app will use your native Ollama.

5. **Open** `http://localhost:8000`. The sidebar must say provider `ollama`, model `qwen3:8b`.

6. **Run one brief.** Idea: `A library of printable lesson-plan templates in Arabic for private English tutors in Egypt`, location `Egypt`. Leave the rest blank.
   - The intake questions appear: answer them, click **Send answers and start the research**.
   - A progress box shows each step ("Searching the web and rating every source…") with a seconds counter.
   - The gate card appears: "Gate 1 recommends …", the reasons under it, and the evidence tabs below.
   - Choose **Approve**, click **Record my decision**. The page shows the result.

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

9. **Clean up** the check output and stop:

   ```powershell
   docker compose down
   Remove-Item decision_log.json
   Remove-Item outputs\phase1_*
   git status
   ```

   `git status` must show only the untracked `.env` (it is gitignored, so usually nothing at all).

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

   First start: `model-pull` downloads `qwen3:8b` (several GB) into the `ollama_data` volume and exits with code 0; then the app starts. Later starts reuse the volume.

3. **Open** `http://localhost:8000`. The sidebar must say provider `ollama`, model `qwen3:8b`.

4. **Run the same brief** as in A.6. The bundled Ollama runs on the CPU (no GPU is passed to Docker), so each step is slower than in A; that is expected.

5. **Check and clean up** as in A.7 and A.9 (`docker compose down` keeps the downloaded model; `docker compose down -v` deletes it).

## Report back

| Check | A (native) | B (bundled) |
|---|---|---|
| App opens on `localhost:8000`, sidebar shows `ollama` / `qwen3:8b` | | |
| Brief → intake questions → progress box → gate card | | |
| Approve/Reject recorded, result shown | | |
| `decision_log.json` in the clone root after the run | | |
| Tests pass in the container (A.8) | | — |
| Time for one run (brief to gate) | | |

If a step fails, copy the last lines of the `docker compose` output into the team chat.
