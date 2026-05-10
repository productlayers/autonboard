# Best Foot Forward — Specification

## Problem Statement

Onboarding is where products win or lose their users. Product teams typically engineer these flows backwards from business and technical constraints — not from the user's perspective. The result: flows optimized for the *average* user that inadvertently churn the *target* user.

Losing low-quality users during onboarding is healthy. Losing the users the product was built for is a product failure. There is no scalable way today to audit an onboarding flow from the perspective of specific user segments without expensive, slow, manual UX research.

## Product Vision

**Best Foot Forward** is an autonomous browser agent that adopts dynamic user personas to audit software onboarding flows. It evaluates the usability and time-to-value of any web product — consumer apps, productivity tools, creator platforms, and more — from the perspective of specific user segments, surfacing friction, confusion, and drop-off risk that traditional analytics miss.

### What Makes This Different

- **Persona-driven, not script-driven.** The agent dynamically generates user personas based on the product's target audience and navigates the flow *as that persona would* — a non-technical small business owner behaves differently than a senior developer.
- **Evaluative, not just functional.** This is not a QA tool checking if buttons work. It is a UX research tool evaluating whether the *experience* works for the *right* users.
- **Cumulative intelligence.** Every run adds to a structured knowledge base, enabling longitudinal analysis across products, personas, and flow changes over time.

---

## Scope

### In Scope (MVP)

| Capability | Detail |
|---|---|
| **Web-only** | The agent audits web applications via Playwright. |
| **Dynamic persona generation** | Given a product URL and description, the LLM identifies the top 3 user segments and generates structured Persona objects with a fixed schema (tech literacy, goals, pain points, behavioral traits). |
| **Authenticated sessions** | The agent uses a persistent browser profile with a pre-authenticated Google account, clicking "Continue with Google" where available to avoid managing per-product passwords. |
| **Autonomous onboarding navigation** | The agent navigates the onboarding flow making decisions consistent with the active persona's traits and technical literacy. |
| **First High-Value Action (HVA)** | The agent's goal is to reach and complete the product's first high-value action. This is defined **hybrid**: the operator provides their hypothesis, and the LLM independently infers its own — creating an audit on PM intuition. |
| **Human-in-the-Loop** | If the agent encounters CAPTCHAs, payment walls, or non-deterministic security blockers, it pauses, alerts the operator, logs the intervention as a friction event, and resumes after resolution. |
| **Structured logging** | Every action is logged with timestamp, page URL, funnel stage, persona context, LLM reasoning, and the exact Playwright action. Runs are appended to an immutable JSONL log. |

### Out of Scope (Future Roadmap)

- Mobile/native app testing
- Payment flow completion
- Direct integration with product analytics platforms (Mixpanel, Amplitude)
- Multi-persona testing loop (run all 3 generated personas and compare paths)
- Enterprise state management (persistent DAG state graph via LangGraph)
- Episodic memory indexing (vector DB for cross-run experience retrieval)
- Cloud browser persistence (Browserbase/Steel.dev)
- W&B (Weave) telemetry instrumentation
- Two-tier model cascade (fast vision model for element extraction + deeper reasoning model for persona alignment)
- Exploratory audit mode (`--mode directed|exploratory`)

---

## Architecture

```
Observe → Plan → Act  (State-Machine Loop)
```

The agent operates as a custom-built state machine orchestrating raw Playwright. Black-box browser agent frameworks (e.g., `browser-use`, `LaVague`) are explicitly rejected to retain full control over reasoning, traceability, and evaluation.

| Layer | Component | Responsibility |
|---|---|---|
| **Browser** | `src/core/browser.py` | Persistent Chromium context (SSO sessions), viewport management, `pause_for_human()` |
| **Observe** | `src/agent/observer.py` | Injects JS to tag interactive elements with `bff-id`, captures annotated JPEG screenshots, produces a token-efficient DOM representation |
| **Plan** | `src/agent/planner.py` | Feeds persona context + DOM state + screenshot to LLM; outputs a structured `AgentAction` with mandatory reasoning |
| **Act** | `src/agent/actor.py` | Maps `AgentAction` to Playwright locators; executes with timeouts and coordinate-based fallback |
| **Orchestrate** | `src/agent/orchestrator.py` | Runs the loop with hard `max_steps` ceiling, loop detection, sibling-cycling detection, and crash recovery |
| **Persona** | `src/personas/` | Pydantic schema + LLM-powered generator producing 3 personas and an HVA audit |
| **Insights** | `src/insights/logger.py` | Append-only JSONL run logs |
| **Evals** | `src/evals/metrics.py` | Completion rate, friction count, token usage |

### Key Design Principles

1. **LLM decides, Python executes.** The LLM chooses what to click and why. Python executes via Playwright and enforces non-negotiable limits.
2. **Deterministic guardrails.** If the agent is stuck for N steps, the system forces a structured decline rather than letting the LLM spin.
3. **No credentials in code.** Authentication is handled exclusively through persistent browser profiles. No passwords in `.env`, no credential inputs in any UI.
4. **Persona fidelity over task completion.** The agent must not brute-force its way to the HVA. Actions must be consistent with how the active persona would naturally behave.

---

## Architecture Decision Record (ADR)

| Date | Decision | Rationale |
|---|---|---|
| Phase 0 | **Custom State Machine over Black-Box Agents** | Rejected `browser-use` and similar wrappers to maintain strict, deterministic control over the `Observe-Plan-Act` loop, token tracking, and human-in-the-loop pausing. |
| Phase 1 | **Multimodal Set-of-Mark (SoM) Observation** | Upgraded from text-only DOM parsing to visual screenshot parsing with injected bounding boxes. The DOM was too fragile against SPAs, React portals, and z-index overlays (cookie banners), causing repeated false-positive failures. |
| Phase 1 | **Physical Clicks over JS Evaluation** | Rejected raw `element.click()` to bypass React UI layers because it violated the core constraint of simulating real human behavior. Use Playwright's strict physical `locator.click()`. |
| Phase 1 | **6s API Throttle** | Introduced a 6-second `asyncio.sleep` in the orchestrator loop. Full base64 JPEG screenshots on every step rapidly trigger 429 rate limits on cloud providers without pacing. |
| Phase 1 | **gpt-4o via OpenRouter** | Switched from Llama-4-Scout to GPT-4o for superior vision-language understanding, stronger persona adherence, and more reliable structured output parsing. |

---

## Credential & Authentication Strategy

| Approach | How It Works |
|---|---|
| **Persistent Browser Context** | Playwright saves cookies, local storage, and session data to `data/browser_profile/`. A Google account is authenticated once manually; all subsequent runs reuse the session. |
| **"Continue with Google"** | The agent preferentially selects Google SSO when available during signup/login flows. |
| **Human escalation** | If Google SSO is unavailable or manual login is required, the agent triggers `pause_for_human()` and logs it as a friction event. |

---

## Evaluation Framework

| Metric | What It Measures | Status |
|---|---|---|
| **Completion Rate** | Did the agent reach the HVA? | ✅ Live |
| **Friction Events** | How many human interventions were required? | ✅ Live |
| **Persona Fidelity** | Did the agent's actions align with the persona's traits? | 🔲 Future (LLM-as-judge) |
| **Insight Quality** | Are the generated insights actionable? | 🔲 Future |
| **Behavioral Consistency** | Does the same persona take similar paths across reruns? | 🔲 Future |

### Evaluation-Driven Development Rule

No changes to persona generation, the planner prompt, or the agent loop are accepted without a before/after comparison on completion rate and friction events.

---

## Why Web-Only

| Dimension | Web | Mobile |
|---|---|---|
| **UI Representation** | Clean DOM — semantic, hierarchical, token-efficient | Accessibility trees — messy, often unlabeled, deeply nested |
| **Execution Infra** | Headless Chrome — cheap, parallelizable | Android emulators / iOS simulators — heavy VMs, macOS-only for iOS |
| **Action Reliability** | Deterministic selectors | Coordinate-based tapping — flaky |
| **Engineering Focus** | 80% on the AI layer (personas, planning, eval) | 80% fighting infrastructure |

Mobile is a future expansion once the core AI layer is proven on web.

---

## Future Vision

A future version of BFF will expose an API or integration layer allowing product teams to correlate BFF's persona-driven friction findings with their internal analytics (Mixpanel, Amplitude) to answer: *"Do real users from this segment actually churn at the same points our agent flagged?"*
