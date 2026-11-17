# Keeping the model list current

Providers add, rename and retire models all the time. BoneChilling handles that in
three layers, so a retired model never silently breaks an ingest.

## 1. What the app does on its own

| Situation | What the user sees |
|---|---|
| Cloud provider, key saved | The model list comes **live from the provider**, so retired models disappear by themselves. |
| Saved model no longer offered | Settings shows *"Your saved model needs attention"* with a one-click replacement. |
| Ingest started with a retired model | The pre-flight check stops before any film is sent, with the same message. |
| Provider retires it mid-run (HTTP 404/410 "model not found / deprecated") | Each film fails with *"Model 'x' isn't available from this provider any more… pick another model, then use Retry failed films"*. Nothing is lost: failed films retry. |
| Ollama model removed from the online library | Already-downloaded models keep working forever; only new downloads fail, with a clear message. |
| Model marked `deprecated` in our list | Shown as "· retiring" in the dropdown with a warning and a **Switch to …** button. |

## 2. The curated list: `src/bonechiling/engines/models.json`

Plain JSON, no code change needed. Each entry:

```json
{ "id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash", "note": "Older",
  "status": "deprecated", "replacement": "gemini-2.5-flash" }
```

* `status: "current"` – normal.
* `status: "deprecated"` – still works; users get a warning and the `replacement`.
* `status: "retired"` – hidden from the dropdown (still shown if a user already has it saved, with a warning).
* Bump `"updated"` when you edit it.

## 3. The monthly check

`.github/workflows/check-models.yml` runs `scripts/check_models.py` on the 1st of
every month (and whenever the list changes):

* every Ollama tag is checked against the Ollama registry,
* OpenRouter IDs against its public list,
* Anthropic / OpenAI / Gemini IDs **if** you add `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY` as repository secrets (Settings → Secrets and variables → Actions).

If a `current` model has vanished the workflow fails and GitHub emails you; the run
summary has a table of what to change. Edit `models.json`, push, ship a new build.
