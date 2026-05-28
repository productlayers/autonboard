# Best Foot Forward — Project Context for Claude

## What This Is
Autonomous browser agent (Playwright + LLM) that simulates real user personas navigating product onboarding flows. Captures first-person think-aloud reasoning, friction events, funnel stage classifications, and screenshots at every step. Built for PMs and UX teams who want onboarding insights in minutes rather than weeks of user research.

Product name: **Best Foot Forward (BFF)**, also referred to internally as **Autonboard**.
GitHub repo: `https://github.com/productlayers/autonboard`

---

## Architecture at a Glance

| File | Role |
|------|------|
| `src/app/main.py` | Entry point, CLI args: `--url`, `--hva`, `--name` (optional), `--headless` |
| `src/agent/orchestrator.py` | State machine: observe → plan → act. Owns loop detection and post-auth injection |
| `src/agent/planner.py` | LLM action planner. Loads memory atoms at prompt-build time (limit 12). Has v1 (verbose) and v2 (tight, ~70% fewer tokens) system prompts |
| `src/agent/observer.py` | DOM injection + set-of-marks (SOM) annotation. Blue boxes since May 16 2026 |
| `src/agent/actor.py` | Playwright action executor |
| `src/agent/reflector.py` | Post-run reflection + atom generation. **Dashboard-triggered, not automatic** |
| `src/agent/auth_hold.py` | Human-in-the-loop pause/resume for auth walls and CAPTCHAs |
| `src/memory/atoms.py` | Durable JSONL atom store at `data/memory/atoms.jsonl` |
| `src/personas/generator.py` | LLM persona generation + HVA inference from landing page |
| `dashboard.py` | Streamlit dashboard — view runs, trigger reflection, inspect friction |
| `scripts/analyze_runs.py` | Aggregate run analysis CLI |
| `scripts/compare_prompt_versions.py` | A/B prompt version comparison |

---

## Current State (as of May 2026)

### Runs
- **109 total runs** across 15+ products: Spotify, Canva, Pinterest, Airtable, Notion, Typeform, Airbnb, Evite, Apartment List, Duolingo, Partiful, 9GAG, v0, The Ledger, Figma, Noom, and others
- Screenshots at `data/runs/screenshots/` (~789 files)
- Run data at `data/runs/runs.jsonl`

### Memory Atoms
- ~39 atoms in `data/memory/atoms.jsonl`
- Key atom: Airtable Omni AI chat — after AI proposes a plan, TYPE in the chat input (e.g. "Build this") rather than clicking "See details" which only expands the card
- Atoms are injected into every planning step via `find_atoms(limit=12)` in `planner.py`

### Annotation Style
- **Before May 16 2026**: `2px solid red` borders, yellow labels (old runs)
- **After May 16 2026** (PR #6): `1px solid rgba(99,102,241,0.45)` blue borders, indigo badge labels — lighter, more polished
- This matters for demo/slide selection: prefer post-May-16 screenshots for visuals

### Prompt Versions
- **v1**: Verbose, more context, higher token usage
- **v2**: Persona-first framing, ~70% fewer tokens, tighter rules
- Both versions live in `planner.py`. Controlled via `prompt_version` arg to orchestrator (not an env var)
- Token efficiency improved: 186K → 148K → 54K across successive runs

---

## Active Branches

| Branch | Status | Contents |
|--------|--------|----------|
| `docs/readme-update` | Open PR | README: memory system explanation, reflection flow, demo thumbnail, accuracy fixes |
| `feat/lovable-demo-data` | Open PR | Demo run data export for Lovable static dashboard (Spotify, Canva, Pinterest runs + 23 screenshots) |
| `fix/agent-pause-input-type` | Stale | May be superseded by changes already merged to main — verify before touching |

---

## Known Issues / Active Regressions

### Input→Type Rule Regression
- **What**: Added rule "if you identify a text input, action MUST be `type` not `click`"
- **Regression**: Agent now types during "Thinking..." / loading states on Airtable Omni instead of waiting
- **Discussed fix**: Soften the rule with a qualifier — "unless the system is visibly processing or loading"
- **Status**: Discussed, not yet implemented
- **Root cause**: Agent has no `wait` action type, creating pressure to always act. A proper fix is adding `wait` as an action (backlog Tier 2)

### Non-Consecutive Loop Detection
- Agent detects consecutive repeated actions but not patterns like A→B→A→B
- Backlog Tier 1 item, not yet implemented

---

## Key Decisions Made (and Why)

### Phrase Priming Removal
- **Problem**: User prompt contained "Notice what stands out" which primed the agent to use "catching my eye" / "standing out to me" on every step despite a system prompt rule banning repetitive phrases
- **Fix**: Removed the three words from both user prompt and v2 system prompt line 188
- **Location**: `src/agent/planner.py`

### Post-Auth Handoff Note
- After a human resolves a CAPTCHA or payment wall, the agent was disoriented
- Fixed by injecting a `post_auth_note` into the next step's `environmental_feedback`:
  *"A human just intervened... That blocker is now resolved. Do NOT mention it as friction..."*
- **Location**: `src/agent/orchestrator.py` (~line 316)

### Loop Detection (3 Mechanisms)
1. ID-based: detects same element clicked consecutively
2. Reasoning-based (SPA-aware): detects when logic is stuck even if element IDs shift
3. Sibling cycling: catches hover-reveal loops (e.g. Spotify-style)

### Discuss Before Acting
- Always diagnose and discuss proposed changes before editing files
- Especially for agent behavior changes — run analysis, present findings, wait for approval
- Documented in `~/.claude/AGENTS.md` Section 6

---

## Experiment Tracking (Backlog — Not Yet Built)

Two-level design planned:
- **Level 1**: Per-run config auto-captured (prompt version, model, temperature, atom count)
- **Level 2**: Experiment registry (opt-in) — `experiment_id`, JSON with control/treatment group info, change tested, hypothesis
- Schema spec is in `docs/BACKLOG.md` Tier 1

---

## Demo Assets

| Asset | Location |
|-------|----------|
| Demo video (Loom, 4:35) | https://www.loom.com/share/6ddad93ff98f47f59df359f93b77e097 |
| Demo thumbnail | `docs/demo-preview.png` |
| Demo script (voiceover) | `docs/DEMO_SCRIPT.md` |
| Lovable static dashboard | https://lovable.dev (from `feat/lovable-demo-data` branch) |
| Demo run data | `data/demo/runs.json` + `data/demo/screenshots/` |

### Slides for Demo Video Intro (5 slides, all post-May-16 blue style)
Selected screenshots showing genuine UX friction (not agent failures):
1. `spotify_20260520_151245_step2_authentication.png` — login wall frustration
2. `airtable_20260520_135404_step13_authentication.png` — cookie banner blocking
3. `airtable_20260520_171255_step18_authentication.png` — unexpected paywall
4. `figma_20260519_154739_step17_first_action.png` — "Let's get designing!" (success)
5. `spotify_20260520_151245_step7_hva_achieved.png` — playlist created (success, same persona as slide 1)

Slides prompt ready to paste into Claude AI or Cowork — ask Claude to regenerate it if needed.

---

## Backlog Highlights

See `docs/BACKLOG.md` for full list. Top items:

**Tier 1 (build next)**
- Experiment tracking (two-level: per-run config + registry)
- Non-consecutive loop detection (A→B→A→B patterns)

**Tier 2**
- `wait` action type (proper fix for input→type regression pressure)
- DOM trimming edge cases

---

## Working Style Notes
- Owner has senior TPM background; prefers discussing issues before code changes
- No `Co-Authored-By: Claude` in commits
- No portfolio/interview framing in committed text — products stand on their own
- One branch per logical change, branched from `origin/main`
- Always verify repo and branch with `git -C <abs-path>` before any git operation
