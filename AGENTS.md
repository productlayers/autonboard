# Project Rules: Best Foot Forward (BFF)
**Lead PM:** Technical Product Manager (Platform & AI)

## 1. Product Mission
To build a production-grade autonomous browser agent that adopts dynamic user personas to audit software onboarding flows. The engine must evaluate the usability and time-to-value of consumer and B2B products from the perspective of specific user segments.

## 2. Technical Bar (Definition of Done)
* **Agentic Traceability:** Every action the agent takes must be logged with timestamp, UI state, persona context, LLM reasoning, and exact Playwright action.
* **Evaluation-Driven:** Behavioral changes to the agent or persona logic require "Before vs. After" metric comparisons (completion rate, persona fidelity, friction events).
* **Deterministic Guardrails:** The LLM does not get unlimited retries. If it is stuck, the system forces a pause or structured decline.
* **Production Hygiene:** Use `uv` for dependency management, maintain a modular `src/` directory structure, and write strictly typed Python.

## 3. Agent Instructions
* **No "Magic" Wrappers:** We do not use black-box browser agent frameworks. We build our own state-machine loop orchestrating raw Playwright to retain full control over reasoning and evaluation.
* **No-Credential-Inputs:** Test account credentials must not be hardcoded or managed in `.env`. We use persistent browser profiles (e.g., Google SSO) to handle authentication natively.
* **Human-in-the-Loop:** If the agent encounters CAPTCHAs or non-deterministic security blockers, it must pause, alert the human to solve it, log a friction event, and resume.
* **Proactive Git Commits:** Automatically commit logical groupings of changes (features or fixes) at meaningful stages using `git commit` without waiting for the user to ask. Do not wait until the end of a session to dump massive changes; maintain clean traceability as you work.
