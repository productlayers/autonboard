# Best Foot Forward (BFF)

**Autonomous browser agent for auditing software onboarding flows.**

BFF adopts dynamic user personas to evaluate the usability and time-to-value of any web product — consumer apps, productivity tools, creator platforms, and more. It navigates real product UIs, simulates how specific user segments experience onboarding, and produces structured telemetry: friction events, funnel stage classification, and first-person think-aloud reasoning for product and UX teams.

---

## How It Works

1. **Product Discovery** — Scrapes landing page metadata to understand the product context.
2. **Persona Generation** — Uses an LLM to generate 3 distinct user personas with varying technical literacy and behavioral traits, tuned to the specific product.
3. **HVA Audit** — Compares the PM's hypothesized High-Value Action against the LLM's independent inference to surface alignment gaps.
4. **Agent Execution** — Drives a real Chromium browser via Playwright, with the agent reasoning in the persona's voice at every step.
5. **Telemetry Logging** — Every step is logged with timestamp, URL, funnel stage, action, persona reasoning, and screenshot path to `data/runs/runs.jsonl`.

---

## Architecture

```
src/
├── app/
│   └── main.py              # Entry point: orchestrates phases 0–5
├── agent/
│   ├── orchestrator.py      # State machine loop: observe → plan → act
│   ├── planner.py           # LLM-powered action planner (v1/v2 prompt versions)
│   ├── observer.py          # DOM injection + viewport-priority element extraction
│   ├── actor.py             # Playwright action executor
│   ├── auth_hold.py         # Human-in-the-loop auth pause + resume flow
│   └── reflector.py         # Post-run reflection and atom generation
├── personas/
│   ├── generator.py         # LLM persona generation + research-based HVA inference
│   └── schema.py            # Pydantic schemas for personas and product analysis
├── memory/
│   └── atoms.py             # Durable tactical memory (JSONL atom store)
├── core/
│   └── browser.py           # Ephemeral browser session manager (Playwright)
├── insights/
│   ├── logger.py            # Run logger → data/runs/runs.jsonl
│   ├── analyzer.py          # LLM-powered post-run UX analysis
│   └── narrator.py          # Live step narration (Web Speech API)
├── evals/
│   └── metrics.py           # Completion rate, friction events, token usage
└── scripts/
    ├── analyze_runs.py       # Aggregate run analysis CLI
    └── compare_prompt_versions.py  # A/B prompt version comparison
```

See [`docs/SPEC.md`](docs/SPEC.md) for the full architecture decision record and design rationale.

---

## Quickstart

### Prerequisites
- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv) for dependency management
- An OpenRouter API key (or compatible OpenAI endpoint)

### Setup

```bash
# Install dependencies
uv sync

# Install Playwright browsers
uv run playwright install chromium

# Copy env template and fill in your API key
cp .env.example .env
```

### Run an audit

```bash
uv run python -m src.app.main \
  --url "https://www.notion.so" \
  --hva "Create a new page and add a table"
```
*(Note: The product name and description are now auto-discovered from the URL. You can still explicitly pass `--name "Product"` if needed.)*

The browser will open, the agent will navigate the onboarding flow, and screenshots will be saved to `data/runs/screenshots/` at each step.

### Visualize Results

To view real-time traces, screenshots, and UX findings, run the Streamlit dashboard:

```bash
# Kill any previous instance and start fresh
kill $(lsof -ti :8501) 2>/dev/null; uv run streamlit run dashboard.py
```

---

## Configuration (`.env`)

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Your OpenRouter (or OpenAI-compatible) API key |
| `OPENAI_BASE_URL` | API base URL (e.g. `https://openrouter.ai/api/v1`) |
| `OPENAI_MODEL` | Model to use (e.g. `openai/gpt-4o`) |
| `HEADLESS` | Set to `true` to run without a visible browser window |
| `PROMPT_VERSION` | `v1` (default, verbose) or `v2` (persona-first, ~70% fewer tokens) |

---

## Design Principles

- **No black-box wrappers.** Raw Playwright, full control over the reasoning loop.
- **No hardcoded credentials.** Uses persistent browser profiles for authenticated sessions — no passwords in code or `.env`.
- **Human-in-the-loop.** CAPTCHAs and auth walls pause the agent and prompt for human resolution, logged as friction events.
- **Persona fidelity over task completion.** The agent must not brute-force its way to the HVA. Actions must be consistent with how the active persona would naturally behave.
- **Evaluation-driven.** Every behavioral change to the agent is measured against before/after completion rate and friction metrics.

---

## Output

Each run appends a JSON record to `data/runs/runs.jsonl`:

```json
{
  "run_id": "20260509_180000",
  "product": "Notion",
  "persona": "Non-technical Entrepreneur",
  "target_action": "Create a new page and add a table",
  "llm_inferred_hva": "Create and share a collaborative document with a teammate",
  "hva_audit_alignment": "PM hypothesis is a setup step, not an activation moment — the real HVA is collaboration.",
  "status": "success",
  "steps": 12,
  "friction_events": 1,
  "total_tokens": 42800,
  "history": [
    {
      "step": 1,
      "action_type": "click",
      "funnel_stage": "landing_page",
      "reasoning": "That 'Get started for free' button is hard to miss...",
      "tokens": 6200,
      "cached_tokens": 2816,
      "prompt_version": "v2",
      "screenshot_path": "data/runs/screenshots/notion_20260509_step1_landing_page.png"
    }
  ]
}
```
