# Best Foot Forward (BFF)

**An autonomous browser agent that adopts AI-generated user personas to audit any product's onboarding flow — then tells you exactly where users get stuck.**

BFF opens a real browser, generates realistic user personas (varying tech-literacy, goals, and behaviors), and drives them through your product's signup and onboarding funnel step-by-step. Every click, every moment of confusion, every friction point is logged with screenshots, first-person reasoning, and funnel stage classification. Product teams get structured UX findings without scheduling a single user test.

---

## How It Works

1. **Paste a URL** — Point BFF at any product (e.g. `notion.so`, `figma.com`, `airbnb.com`)
2. **Define the goal** — Tell it what a new user should accomplish (e.g. *"Create a project and invite a teammate"*)
3. **Personas are generated** — An LLM creates 3 distinct user personas tuned to the product, each with different tech literacy and motivations
4. **Agent runs the flow** — A real Chromium browser opens. The agent navigates as the persona, reasoning aloud at every step (*"I'm confused — is this button for sharing or exporting?"*)
5. **Friction is flagged** — CAPTCHAs, login walls, and dead-ends pause the agent for human intervention (logged as friction events)
6. **Results are logged** — Every step is saved to `runs.jsonl` with screenshots, funnel stage, action, reasoning, and latency

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        dashboard.py (Streamlit)                  │
│            Real-time UI: run audits, view traces, browse results │
└─────────────────────────────┬────────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│  src/app/main.py — Entry point & phase orchestrator              │
│  Phase 0: Scrape URL metadata → Phase 1: Generate personas →    │
│  Phase 2: Run agent → Phase 3: Log results & metrics             │
└───────┬──────────────┬──────────────┬────────────────────────────┘
        │              │              │
   ┌────▼────┐   ┌─────▼─────┐  ┌────▼──────────┐
   │ Persona │   │   Agent    │  │   Telemetry   │
   │Generator│   │   Loop     │  │   Pipeline    │
   │         │   │            │  │               │
   │ LLM →   │   │ Observe →  │  │ RunLogger →   │
   │ 3 typed │   │ Plan →     │  │ runs.jsonl    │
   │ personas│   │ Act →      │  │ screenshots/  │
   │ + HVA   │   │ Repeat     │  │ EvalMetrics   │
   │ audit   │   │            │  │               │
   └─────────┘   └─────┬──────┘  └───────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
   ┌────▼────┐    ┌─────▼─────┐   ┌─────▼─────┐
   │Observer │    │  Planner  │   │   Actor    │
   │         │    │           │   │            │
   │ Injects │    │ LLM with  │   │ Playwright │
   │ bff-ids │    │ persona   │   │ executor   │
   │ into DOM│    │ system    │   │ with 3-tier│
   │ + annot.│    │ prompt →  │   │ retry:     │
   │ screen- │    │ structured│   │ click →    │
   │ shots   │    │ action    │   │ hover+click│
   │         │    │ output    │   │ → coord    │
   └─────────┘    └───────────┘   └─────┬──────┘
                                        │
                                  ┌─────▼──────┐
                                  │  Browser   │
                                  │  Manager   │
                                  │            │
                                  │ Persistent │
                                  │ Chromium   │
                                  │ context    │
                                  │ (SSO-ready)│
                                  │ + in-page  │
                                  │ pause      │
                                  │ overlay    │
                                  └────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.12+ (strictly typed) |
| **Browser Automation** | Playwright (raw — no wrapper frameworks) |
| **LLM** | OpenAI-compatible API via OpenRouter (GPT-4o default) |
| **Structured Output** | Pydantic models with OpenAI JSON Schema mode |
| **Dashboard** | Streamlit (live traces, past runs, screenshots) |
| **HTTP** | httpx (async metadata scraping) |
| **Package Manager** | uv (fast, deterministic installs) |
| **Data Format** | JSONL (append-only run logs) + PNG screenshots |

---

## Current Status

### Core Engine
- Done — **Observe, Plan, Act loop** — Full state machine with DOM injection, LLM planning, and Playwright execution
- Done — **Persona generation** — LLM generates 3 personas per product with tech literacy, goals, and behavioral traits
- Done — **HVA audit** — Compares PM's hypothesis vs. LLM-inferred high-value action
- Done — **First-person reasoning** — Agent thinks aloud as the persona (*"I'm looking for a sign-up button..."*)
- Done — **Funnel stage classification** — Each step tagged: `landing_page → signup_wall → authentication → onboarding → first_action → hva_achieved`
- Done — **Step-level telemetry** — Screenshots, latency, element coordinates, reasoning, success/failure per step

### Reliability and Edge Cases
- Done — **3-tier click strategy** — Direct click, hover+click, coordinate-based fallback (handles Spotify-style hover-reveal UIs)
- Done — **Contenteditable support** — `dblclick` + `SelectAll` + keyboard fallback for rich text editors
- Done — **Loop detection** — Ping-pong detector, sibling cycling detector, builder awareness (element growth tracking)
- Done — **Crash-safe logging** — Partial run data always persisted, even on `Ctrl+C` or LLM rate limit errors
- Done — **Auto-discovery** — Product name and description scraped from URL (no manual input needed)

### Human-in-the-Loop
- Done — **In-browser pause overlay** — CAPTCHAs and auth walls inject a modal directly into the page; user clicks "Resume Agent" in the browser
- Done — **No hardcoded credentials** — Uses persistent browser profiles for Google SSO
- Done — **Friction event logging** — Every human intervention is timestamped and categorized

### Dashboard and Visualization
- Done — **Streamlit dashboard** — Run new audits, view real-time step traces, browse past runs
- In Progress — **UI labels** — Currently uses PM jargon (`HVA`); needs user-friendly rewording
- To Build — **Friction heatmap** — Visual grid showing where users consistently get stuck
- To Build — **Cross-run comparison** — Side-by-side view of multiple audit runs
- To Build — **Funnel drop-off chart** — Bar chart of where users abandon the flow

### Intelligence Layer
- To Build — **Post-run UX Analyzer** — LLM pass over completed runs to generate structured UX findings
- To Build — **Agent memory** — Per-product friction log + global heuristics so the agent learns across runs
- To Build — **Exploratory mode** — Agent explores without knowing the target HVA (tests discoverability, not just usability)

---

## Proposed Improvements

These are areas I'm thinking about taking the project next. Some are scoped enough to build in a day, others are longer-term bets.

### Near-term

| Area | What I'm Thinking |
|------|--------------------|
| **Loop resilience** | Audit all 48 past runs, cluster the remaining stuck-loop patterns by root cause, and add targeted guardrails for each |
| **User-friendly labels** | Replace PM-language in the dashboard (`HVA`, `audit_mode`) with plain English so anyone can run an audit without context |
| **UX Insight Analyzer** | A second LLM pass that reads a completed run log and outputs structured findings — friction points, mislabeled buttons, funnel drop-offs — without re-running the browser |
| **Funnel visualization** | Add a Plotly bar chart to the dashboard showing exactly where in the onboarding funnel users drop off |

### Longer-term

| Area | What I'm Thinking |
|------|--------------------|
| **Agent memory** | Persist per-product learnings (tricky elements, required interaction strategies) so the agent stops repeating the same mistakes across runs |
| **Exploratory mode** | Let the agent navigate without knowing the PM's target goal — tests whether the product *guides* users to the right action vs. whether users *can* complete it if told |
| **Multi-persona runs** | Run all 3 generated personas in parallel for richer comparison data in a single session |
| **Friction heatmap** | A visual grid of steps × personas where color intensity maps to friction — immediately shows where every user type gets stuck |

---

## How to Run It

```bash
# 1. Clone the repo
git clone https://github.com/productlayers/autonboard.git
cd autonboard

# 2. Install dependencies (requires uv — install via: curl -LsSf https://astral.sh/uv/install.sh | sh)
uv sync

# 3. Install browser
uv run playwright install chromium

# 4. Set up your API key
cp .env.example .env
# Edit .env and add your OpenRouter API key (get one at https://openrouter.ai)

# 5. Run an audit
uv run python -m src.app.main \
  --url "https://www.notion.so" \
  --hva "Create a new page and add a table"

# 6. Or use the dashboard (recommended)
uv run streamlit run dashboard.py
```

Time to first run: about 3 minutes (mostly the Playwright browser download).

### Environment Variables (`.env`)

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenRouter or OpenAI-compatible key | `sk-or-v1-...` |
| `OPENAI_BASE_URL` | API endpoint | `https://openrouter.ai/api/v1` |
| `OPENAI_MODEL` | Model to use | `openai/gpt-4o` |
| `HEADLESS` | Run browser without a window | `false` |

---

## Areas Open for Contribution

The project touches several distinct areas, and there's room to go deep on any of them:

- **LLM and prompt engineering** — The agent's behavior is shaped by a single system prompt in `src/agent/planner.py`. There's a lot of room to improve persona fidelity, reduce brute-force navigation, and handle edge cases more gracefully.
- **Browser automation and reliability** — The actor (`src/agent/actor.py`) and orchestrator (`src/agent/orchestrator.py`) handle the low-level Playwright interactions and loop detection. New failure modes show up with every new product tested.
- **Data visualization and dashboarding** — The Streamlit dashboard (`dashboard.py`) is functional but basic. The run data is rich (screenshots, per-step reasoning, funnel stages) and deserves better visual treatment.
- **Post-run analysis** — There's no automated insight generation yet. A second LLM pass over completed runs could surface structured UX findings without re-running the browser. The spec is in `docs/BACKLOG.md`.
- **Evaluation and benchmarking** — Comparing audit results across products and personas. Building metrics that actually capture onboarding quality.

See [`docs/BACKLOG.md`](docs/BACKLOG.md) for detailed specs on each of these, and [`docs/LEARNINGS.md`](docs/LEARNINGS.md) for the edge cases and fixes discovered so far.

---

## Stats So Far

- **48 audit runs** logged across multiple products
- **480+ screenshots** captured at step-level granularity
- **7 documented edge cases** with fixes (see [LEARNINGS.md](docs/LEARNINGS.md))
- Products tested: Notion, Figma, Spotify, Typeform, Partiful, Airbnb, Airtable, and more
