# BFF Product Backlog

> Living document tracking prioritized enhancements. Items marked ✅ have been implemented.
> PRD reference: `bff_prd_draft.md` § Out of Scope (Future)

---

## Tier 1 — Telemetry & Observability (Completed)

### ✅ Rich step-level telemetry
Added per-step fields: `element_x`, `element_y`, `reasoning`, `state_summary`, `screenshot_base64` (persisted as PNG to `data/runs/screenshots/`), `latency_ms`, `success`, `error_msg`.

### ✅ HVA audit metadata
Top-level JSONL fields: `llm_inferred_hva`, `hva_audit_alignment`, `generated_personas`.

### ✅ Crash-safe logging
`orchestrator.py` catches all exceptions (including `KeyboardInterrupt` and `RateLimitError`). `main.py` uses `try/except/finally` to guarantee `logger.log_run()` always fires. New fields: `run_success` (bool), `failure_reason` (string).

### ✅ Fatal Authentication Rule
Prompt hardened with a dominant Rule 1 that overrides organic roleplay — agent must `pause_for_human` on any login/signup screen.

### ✅ `funnel_stage` classification
Planner now outputs one of: `landing_page`, `signup_wall`, `authentication`, `onboarding_questionnaire`, `product_tour`, `first_action`, `hva_achieved`. Logged per-step.

### ✅ `element_text`
The visible label of the clicked element (e.g., "Get Started", "Continue") extracted from the DOM. Logged per-step.

### ✅ `step_timestamp`
Wall-clock epoch seconds for each step. Enables total elapsed time calculations.

### ✅ `page_title`
Extracted via `document.title` at each step. Helps identify funnel stage in SPAs where the URL doesn't change.

### ✅ First-person persona reasoning
Prompt rewritten so `reasoning` and `state_summary` are expressed in first person ("I want to...", "I'm confused by...") rather than third person ("The persona wants to...").

### ✅ Human-readable screenshot filenames
Format: `{product}_{YYYYMMDD_HHMMSS}_step{N}_{funnel_stage}.png`
Example: `airtable_20260508_2305_step3_onboarding_questionnaire.png`

### ✅ Human-readable run IDs
`run_id` format changed from epoch int (`1778306687`) to `YYYYMMDD_HHMMSS`. ISO timestamp stored separately.

---

## Tier 1 — Post-Run UX Insight Analyzer

### `src/insights/analyzer.py` — LLM-powered post-hoc run analysis

**Problem:** The agent loop currently generates rich structured data per step (element_text, reasoning, error_msg, funnel_stage, screenshots) but produces no human-readable UX findings. Analysis currently requires manual inspection of `runs.jsonl`.

**Proposed Solution:** A second, lightweight LLM pass over a completed run record that generates structured UX findings without touching the agent loop.

**What it can detect from existing JSONL fields alone:**

| Signal | Raw evidence in JSONL | Example finding |
|---|---|---|
| Mislabeled affordances | `element_text` + repeated clicks + `success: true` but no state change | *"The 'Edit' button opened a background image picker — not a title editor. 3 interactions wasted."* |
| Auth wall friction | `funnel_stage: signup_wall` + `pause_for_human` | *"Users must log in before saving any progress — no trial of core features."* |
| Typing failures | `action_type: type` + `success: false` + `error_msg` | *"Event title field is a contenteditable div — standard form-fill tools fail here."* |
| Loop detection | Repeated element IDs in history | *"Agent cycled between 2 elements for 8 steps before breaking out."* |
| Funnel drop-off point | Last `funnel_stage` before `failure_reason` | *"100% of personas dropped at 'first_action' stage — HVA unreachable without login."* |

**Architecture:**
- Input: a single run record from `runs.jsonl`
- Output: structured `UXFindings` object (Pydantic) with: `friction_points[]`, `mislabeled_affordances[]`, `completion_summary`, `persona_specific_notes[]`
- Can be run post-hoc: `uv run python -m src.insights.analyzer --run-id 20260509_190040`
- No agent changes required — purely a read pass over existing data

**Why post-hoc is better than runtime logging:**
- Agent loop stays lean
- Analyzer can be re-run with different prompts/models without re-running the browser
- Multiple runs can be batch-analyzed for cross-product comparisons

---


### Problem Statement
The current agent operates in **Directed Mode** only: the persona is told the PM's HVA upfront and actively tries to reach it. This answers:

> *"If a user already knows they want to do X, how much friction does the product put in their way?"* (Usability test)

But it does NOT answer:

> *"Does the onboarding funnel naturally guide a user toward X, even if they didn't arrive with that specific intent?"* (Product design test)

By giving the persona the HVA, we create a goal-biased agent that makes beeline decisions. A real first-time user doesn't know the product team's intended HVA — they arrive with their own vague motivation ("I heard about this from a friend", "I need a tool for my team").

### Proposed Solution
Add a `--mode directed|exploratory` CLI flag:

| Mode | Persona knows HVA? | Prompt goal | HVA used for | Answers |
|------|--------------------|----|-----|---------|
| **Directed** (current) | Yes | PM's HVA as explicit target | Task completion metric | "How hard is it to do X, if the user wants to do X?" |
| **Exploratory** (new) | No | Persona's own `primary_goal` only | Post-hoc evaluation metric | "Does the funnel naturally lead users toward X?" |

### Implementation Notes
- In exploratory mode, the planner prompt replaces the HVA line with the persona's `primary_goal` (e.g., "You just heard about Steam and want to check it out")
- The PM's HVA is still passed to `runs.jsonl` for post-hoc analysis
- New JSONL field: `hva_reached_organically: true/false` — did the persona naturally perform the HVA without being told to?
- New JSONL field: `audit_mode: "directed" | "exploratory"`
- The `done` action type in exploratory mode triggers when the persona feels they've accomplished their own goal, NOT the PM's HVA

### Success Metrics
- Compare directed vs. exploratory completion rates for the same product
- If exploratory completion rate is low but directed is high → the funnel has a **discoverability** problem
- If both are low → the product has a **fundamental usability** problem

---

## Tier 1 — Scroll Action Support

**Problem:** The agent currently has no `scroll` action type. The observer only captures interactive elements visible in the viewport, and the planner can only click, type, navigate, or pause. On pages with below-the-fold content (long onboarding questionnaires, cookie banners pushing content down, infinite-scroll listings), the agent cannot discover or interact with elements it can't see — likely contributing to loops where it repeatedly clicks the same visible elements.

**Proposed Changes:**

| Component | Change |
|---|---|
| `planner.py` | Add `"scroll"` to the `action_type` Literal. Add a `scroll_direction` field (`"up"` \| `"down"`) to `AgentAction`. Add a planner rule: *"If you cannot see the element you need, or suspect there is more content below, use scroll."* |
| `actor.py` | Handle `scroll` action by calling `page.mouse.wheel(0, delta_y)` or `page.evaluate('window.scrollBy(0, 500)')`. |
| `observer.py` | After scrolling, re-inject SoM labels so the new viewport elements get `bff-id` tags and bounding boxes. |
| `orchestrator.py` | No special loop-detection changes needed — existing anti-repeat rules apply. |

**Why Tier 1:** The ApartmentList run showed the agent stuck on quiz screens where the "Next" button may have been below the fold or obscured. Scroll support directly addresses a class of loops that no amount of prompt engineering can fix.

**Files:** `src/agent/planner.py`, `src/agent/actor.py`, `src/agent/observer.py`

---

## Tier 2 — Enhanced Telemetry Fields

### `question_asked`
When the agent fills out onboarding questionnaires, capture what question was being asked alongside `text_to_type`. Enables persona-comparison dashboards ("How did each persona answer the same question?").

### `estimated_completion_pct`
Per-step estimate (0-100) from the planner of how close the persona is to the HVA. Enables funnel drop-off visualization.

### `funnel_stage_duration_ms`
Computed at log time by aggregating steps within the same `funnel_stage`. Shows time-in-stage for each funnel phase.

---

## Tier 1 — UX-Friendly Dashboard UI Labels

**Problem:** The current UI surfaces internal PM-language (`HVA`, `audit_mode`, etc.) that is confusing to non-PM users running the tool. Users shouldn't need to know what an HVA is to run an audit.

**Proposed Changes:**
- Rename `HVA` input field → *"What's the #1 thing you want a new user to do?" (e.g. 'create their first project')*
- Rename `audit_mode` toggle → *"Audit Style: Goal-Directed vs. Free Exploration"* with a tooltip explaining each
- Rename `product_name` (optional) → *"Product name (auto-detected if blank)"*
- All field labels should use plain English with a one-line helper text below
- Add a `?` tooltip icon next to every advanced field

**Files:** `dashboard.py`

---

## Tier 1 — Stuck-in-a-Loop Synthesis & Fixes

**Problem:** Despite existing loop detectors (ping-pong, sibling cycling, builder awareness), several classes of loops persist across runs. No systematic review has been done of actual run logs to catalogue and prioritize the remaining failure modes.

**Proposed Work:**
1. **Audit Phase:** Review all run logs in `data/runs/` and `docs/LEARNINGS.md`. For each stuck-loop event, document: product, step count before detection, action sequence, and root cause category.
2. **Synthesis:** Cluster into root cause types (e.g., hidden state changes, modal hijacking, SPA lazy-loading, dropdown blur events, multi-step form navigation).
3. **Fix Phase:** For each root cause cluster, implement a targeted guardrail in `orchestrator.py` or `actor.py` and add a corresponding rule to `planner.py`.
4. **Regression Gate:** Add a `tests/test_loop_detector.py` with synthetic action histories that reproduce each known loop pattern, so future changes can't silently regress them.

**Files:** `src/agent/orchestrator.py`, `src/agent/planner.py`, `src/agent/actor.py`, `docs/LEARNINGS.md`, `tests/test_loop_detector.py`

---

## Tier 2 — Agent Run Memory

**Problem:** Every audit run starts from a blank slate. The agent cannot learn from its own past mistakes (e.g., it tries `fill()` on a known contenteditable site again, or misidentifies a recurring UI pattern). Institutional knowledge is lost between runs.

**Proposed Architecture:**

| Layer | What is stored | Storage |
|---|---|---|
| **Friction Log** | Per-product: known tricky elements, loop triggers, required interaction strategies | `data/memory/{product_slug}.json` |
| **Global Heuristics** | Cross-product patterns surfaced by the UX Analyzer (e.g., "contenteditable divs on event builders always need dblclick") | `data/memory/global_heuristics.json` |
| **Retrieval** | At run start, orchestrator loads product-specific + global memory and injects into the planner prompt as a `past_learnings` context block | `src/agent/memory.py` |

**Key Design Constraints:**
- Memory is **append-only** (no deletes) and timestamped — preserves auditability
- Each memory entry links back to the `run_id` that generated it
- The UX Analyzer (`src/insights/analyzer.py`) is the write path — it extracts learnings post-run and persists them
- Agent loop reads memory; it never writes directly (separation of concerns)

**Files:** `src/agent/memory.py` [NEW], `src/insights/analyzer.py`, `src/agent/orchestrator.py`

---

## Tier 2 — Enhanced Run Visualization Dashboard

**Problem:** The current `dashboard.py` is a functional but basic Streamlit UI. Run data is rich (screenshots, step-by-step reasoning, funnel stages, friction events) but poorly surfaced. There is no cross-run comparison or trend view.

**Proposed Features:**

| Feature | Description |
|---|---|
| **Run Timeline** | Horizontal step-by-step timeline with funnel stage color-coding and screenshot thumbnails on hover |
| **Friction Heatmap** | Visual grid of steps × personas with color intensity = friction events. Highlights where users consistently get stuck |
| **Funnel Drop-off Chart** | Bar chart of `funnel_stage` distribution across all steps — shows exactly where users abandon |
| **Cross-Run Comparison** | Select 2+ runs side-by-side. Compare completion rates, step counts, loop events per persona |
| **Persona Trace Viewer** | Per-persona expandable trace: reasoning → screenshot → action → outcome per step |
| **Memory Inspector** | Read-only view of what the agent has learned about each product from past runs |

**Tech:** Streamlit with `plotly` for charts, `streamlit-image-select` for screenshot browsing.

**Files:** `dashboard.py`, `src/viz/` [NEW dir]

---

## Tier 2 — Browser Cleanup on Crash

### Problem
`orchestrator.py` calls `browser.stop()` only on the happy path (line ~368, headless only) and the call is *not* inside a `try/finally`. If anything above it throws — observation failure, planner exception, network blip — the Playwright Chrome process leaks. These are silent: they pile up in the Dock / process table and only surface when the machine slows down. Headless crashes are especially hard to notice because there's no visible window.

### Fix
Wrap the orchestrator run loop in `try/finally` and call `await self.browser.stop()` in the `finally`, gated only by "did we start the browser." Non-headless inspection-hold should still happen in `main.py` after the orchestrator returns (already done — `main.py` waits on the context `close` event, then calls `browser.stop()`).

### Acceptance
- Force a crash mid-run in headless mode → no `Google Chrome for Testing` process left behind (`ps aux | grep -i chrom`).
- Force a crash mid-run in headed mode → window stays open for inspection; closing it triggers cleanup.

---

## Tier 3 — Future Ideas

### `persona_frustration_score`
Per-step emotional state from the persona's perspective (1-5 scale). Would require prompt engineering to get calibrated scores.

### `accessibility_issues`
Flag elements that lack aria-labels, have low contrast, or violate WCAG guidelines. Could be extracted from the DOM during observation.

### `competitive_benchmark`
Compare the same HVA across similar products (e.g., "Create a project" on Asana vs. Monday.com vs. ClickUp). Requires multi-run orchestration.

### Rate-limit resilience
Add automatic retry with exponential backoff for 429 errors, or implement model fallback (Groq → Together AI → OpenAI) when quota is exhausted.
