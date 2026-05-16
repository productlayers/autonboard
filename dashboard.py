"""
BFF Dashboard — Streamlit UI for the Best Foot Forward UX Auditor.
Launch: uv run streamlit run dashboard.py
"""
import asyncio
import base64
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import httpx
import streamlit as st
from dotenv import load_dotenv

from src.personas.generator import PersonaGenerator
from src.agent.orchestrator import AgentOrchestrator
from src.insights.logger import RunLogger
from src.evals.metrics import EvalMetrics

load_dotenv()

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Best Foot Forward",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* HVA comparison cards */
.hva-card {
    background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
    border: 1px solid #3a3a5c;
    border-radius: 12px;
    padding: 1.2rem;
    margin-bottom: 0.5rem;
}
.hva-card h4 { margin: 0 0 0.5rem 0; color: #a78bfa; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; }
.hva-card p { margin: 0; color: #e2e8f0; font-size: 1rem; }

/* Persona cards */
.persona-card {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 1rem;
    height: 100%;
}
.persona-card h4 { color: #c4b5fd; margin: 0 0 0.4rem 0; }
.persona-card .tech-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 600;
}
.tech-low { background: #dc2626; color: white; }
.tech-medium { background: #f59e0b; color: black; }
.tech-high { background: #10b981; color: white; }

/* Step chat bubble */
.step-bubble {
    background: #1e1e2e;
    border: 1px solid #3a3a5c;
    border-radius: 16px;
    padding: 1rem 1.2rem;
    margin-bottom: 1rem;
    position: relative;
}
.step-bubble .step-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.6rem;
}
.step-bubble .persona-name { color: #c4b5fd; font-weight: 600; font-size: 0.95rem; }
.step-bubble .reasoning { color: #d1d5db; font-style: italic; line-height: 1.5; margin-bottom: 0.6rem; }
.step-bubble .action-line { color: #9ca3af; font-size: 0.85rem; }

/* Funnel stage badges */
.stage-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 600;
}
.stage-landing_page { background: #3b82f6; color: white; }
.stage-signup_wall { background: #f59e0b; color: black; }
.stage-authentication { background: #ef4444; color: white; }
.stage-onboarding_questionnaire { background: #8b5cf6; color: white; }
.stage-product_tour { background: #06b6d4; color: white; }
.stage-first_action { background: #10b981; color: white; }
.stage-hva_achieved { background: #22c55e; color: white; }

/* Status badges */
.status-success { color: #22c55e; font-weight: 700; }
.status-failed { color: #ef4444; font-weight: 700; }
.status-timeout { color: #f59e0b; font-weight: 700; }

/* Metric card */
.metric-box {
    background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
    border: 1px solid #3a3a5c;
    border-radius: 12px;
    padding: 1rem;
    text-align: center;
}
.metric-box .metric-value { font-size: 1.8rem; font-weight: 700; color: #a78bfa; }
.metric-box .metric-label { font-size: 0.8rem; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.05em; }
</style>
""", unsafe_allow_html=True)


# ── Helper Functions ─────────────────────────────────────────────────────────

def extract_product_name(url: str, html: str = "") -> str:
    """Extract product name from HTML metadata or URL hostname."""
    if html:
        m = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:site_name["\']', html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        t = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if t:
            return re.split(r'\s*[-|—·]\s*', t.group(1).strip())[0].strip()
    from urllib.parse import urlparse
    hostname = urlparse(url).hostname or ""
    return hostname.replace("www.", "").split(".")[0].capitalize()


def extract_description(html: str) -> str:
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', html, re.IGNORECASE)
    return m.group(1).strip() if m else "No description found."


def render_stage_badge(stage: str) -> str:
    return f'<span class="stage-badge stage-{stage}">{stage.replace("_", " ")}</span>'


def render_step_bubble(step_data: dict, persona_name: str) -> str:
    stage = step_data.get("funnel_stage", "unknown")
    reasoning = step_data.get("reasoning", "")
    action = step_data.get("action_type", "")
    element_id = step_data.get("element_id", "")
    step_num = step_data.get("step", "?")
    success = step_data.get("success", True)
    error = step_data.get("error_msg", "")

    action_desc = f"→ {action}"
    if element_id:
        action_desc += f" on [{element_id}]"
    if step_data.get("text_to_type"):
        action_desc += f' — typed "{step_data["text_to_type"]}"'

    icon = "✅" if success else "❌"
    error_line = f'<br><span style="color:#ef4444;font-size:0.8rem;">Error: {error}</span>' if error else ""

    return f"""
    <div class="step-bubble">
        <div class="step-header">
            <span class="persona-name">🧑 {persona_name} — Step {step_num}</span>
            {render_stage_badge(stage)}
        </div>
        <div class="reasoning">"{reasoning}"</div>
        <div class="action-line">{icon} {action_desc}{error_line}</div>
    </div>
    """


def load_past_runs() -> list:
    log_file = "data/runs/runs.jsonl"
    if not os.path.exists(log_file):
        return []
    runs = []
    with open(log_file, "r") as f:
        for line in f:
            if line.strip():
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return runs


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📈 Best Foot Forward")
    st.caption("Autonomous UX Auditor")
    st.divider()

    # Live stats (updated during runs)
    if "run_active" in st.session_state and st.session_state.run_active:
        st.markdown("### 📊 Live Stats")
        stats_placeholder = st.empty()
    
    # Global metrics
    metrics = EvalMetrics().get_metrics()
    st.markdown("### 📈 Global Metrics")
    col1, col2 = st.columns(2)
    col1.metric("Total Runs", metrics["total_runs"])
    col2.metric("Completion Rate", f"{metrics['completion_rate']:.0%}")
    col1.metric("Avg Friction", f"{metrics['avg_friction_events']:.1f}")
    col2.metric("Avg Steps", f"{metrics['avg_steps']:.1f}")

    st.divider()

    # Metric Definitions
    with st.expander("📖 Metric Definitions"):
        st.markdown("""
        **HVA** — High-Value Action. The first meaningful action a product wants new users to complete.
        
        **Friction Event** — Any moment the agent got stuck and needed human help (CAPTCHAs, auth walls, broken UI).
        
        **Funnel Stage** — Where in the onboarding flow the agent is:
        `landing_page` → `signup_wall` → `authentication` → `onboarding_questionnaire` → `product_tour` → `first_action` → `hva_achieved`
        
        **Steps** — Total actions the agent took before completing or timing out (max 30).
        
        **Tokens** — LLM tokens consumed across all planning calls during the run.
        
        **Completion Rate** — % of runs where the agent successfully reached `hva_achieved`.
        """)


# ── Main Content ─────────────────────────────────────────────────────────────

tab_new, tab_past = st.tabs(["🚀 New Audit", "📋 Past Runs"])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: New Audit
# ═══════════════════════════════════════════════════════════════════════════════
with tab_new:
    st.markdown("# 📈 Best Foot Forward")
    st.markdown("##### Autonomous UX auditor powered by AI personas")
    st.markdown("")

    # Input form
    with st.form("audit_form"):
        col_url, col_hva = st.columns([3, 3])
        with col_url:
            product_url = st.text_input("🔗 Product URL", placeholder="https://www.airbnb.com")
        with col_hva:
            pm_hva = st.text_input("🎯 High-Value Action (HVA)", placeholder="Search for a weekend stay and view a listing")
        
        submitted = st.form_submit_button("🚀 Run Audit", use_container_width=True, type="primary")

    if submitted and product_url and pm_hva:
        # Ensure URL has scheme
        if not product_url.startswith("http"):
            product_url = "https://" + product_url

        st.session_state.run_active = True

        # ── Phase 0: Product Discovery ────────────────────────────────────
        with st.status("🔍 Phase 0: Discovering product...", expanded=True) as phase0:
            html_text = ""
            product_desc = "No description found."
            product_name = None
            try:
                async def scrape():
                    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                        resp = await client.get(product_url, headers={"User-Agent": "Mozilla/5.0"})
                        return resp.text
                html_text = asyncio.run(scrape())
                product_desc = extract_description(html_text)
                product_name = extract_product_name(product_url, html_text)
            except Exception as e:
                st.warning(f"Could not scrape metadata: {e}")
                product_name = extract_product_name(product_url)

            st.markdown(f"**Product:** {product_name}")
            st.markdown(f"**Description:** {product_desc}")
            phase0.update(label=f"✅ Phase 0: Discovered **{product_name}**", state="complete")

        # ── Phase 1: Persona Generation & HVA Audit ───────────────────────
        with st.status("🧠 Phase 1: Generating personas & auditing HVA...", expanded=True) as phase1:
            async def generate_personas():
                gen = PersonaGenerator()
                return await gen.analyze_product(product_name, product_desc, pm_hva)
            
            analysis = asyncio.run(generate_personas())
            phase1.update(label="✅ Phase 1: Personas generated", state="complete")

        # HVA Audit Comparison
        st.markdown("### 🎯 HVA Audit")
        col_pm, col_llm = st.columns(2)
        with col_pm:
            st.markdown(f"""<div class="hva-card">
                <h4>PM's Hypothesized HVA</h4>
                <p>{pm_hva}</p>
            </div>""", unsafe_allow_html=True)
        with col_llm:
            st.markdown(f"""<div class="hva-card">
                <h4>LLM-Inferred HVA</h4>
                <p>{analysis.inferred_high_value_action}</p>
            </div>""", unsafe_allow_html=True)
        
        with st.expander("📝 Alignment Analysis", expanded=True):
            st.info(analysis.pm_hypothesis_alignment)

        # Persona Cards
        st.markdown("### 👥 Generated Personas")
        persona_cols = st.columns(3)
        for i, persona in enumerate(analysis.target_personas):
            tech_class = {"Low": "tech-low", "Medium": "tech-medium", "High": "tech-high"}.get(persona.technical_literacy, "tech-medium")
            with persona_cols[i]:
                st.markdown(f"""<div class="persona-card">
                    <h4>{"🟢" if i == 0 else "⚪"} {persona.name}</h4>
                    <span class="tech-badge {tech_class}">{persona.technical_literacy}</span>
                    <p style="color:#9ca3af;font-size:0.85rem;margin-top:0.5rem;">{persona.primary_goal}</p>
                </div>""", unsafe_allow_html=True)
        
        if len(analysis.target_personas) > 0:
            st.caption(f"🟢 Running audit with: **{analysis.target_personas[0].name}**")

        st.divider()

        # ── Phase 2: Agent Execution ──────────────────────────────────────
        st.markdown("### 🤖 UX Audit — Live")
        target_persona = analysis.target_personas[0]
        
        steps_container = st.container()
        progress_bar = st.progress(0, text="Starting agent...")
        
        # Sidebar live stats
        sidebar_stats = st.sidebar.empty()
        
        # Mutable counters (can't use nonlocal at module scope in Streamlit)
        counters = {"step": 0, "friction": 0, "tokens": 0}
        max_steps = 30

        def on_step(step_dict):
            counters["step"] = step_dict.get("step", counters["step"] + 1)
            if step_dict.get("action_type") == "pause_for_human":
                counters["friction"] += 1
            
            # Render chat bubble
            with steps_container:
                st.markdown(
                    render_step_bubble(step_dict, target_persona.name),
                    unsafe_allow_html=True
                )
                # Show screenshot if available
                screenshot_b64 = step_dict.get("screenshot_base64")
                if screenshot_b64:
                    try:
                        img_bytes = base64.b64decode(screenshot_b64)
                        st.image(img_bytes, caption=f"Step {counters['step']} screenshot", use_container_width=True)
                    except Exception:
                        pass

            # Update progress
            progress = min(counters["step"] / max_steps, 1.0)
            progress_bar.progress(progress, text=f"Step {counters['step']}/{max_steps}")
            
            # Update sidebar stats
            sidebar_stats.markdown(f"""
            ### 📊 Live Stats
            - **Steps:** {counters['step']}/{max_steps}
            - **Friction Events:** {counters['friction']}
            """)

        async def on_pause(reason: str):
            """Called when agent pauses — just shows a status message in the UI.
            The actual resume button is injected into the browser window by browser.py."""
            with steps_container:
                st.warning(
                    f"⚠️ **Agent Paused** — {reason}\n\n"
                    f"Solve the issue in the browser window and click **'✅ Done — Resume Agent'** there to continue."
                )

        # Run the orchestrator — always log, even on crash/interrupt
        run_results = None
        async def run_orchestrator():
            orchestrator = AgentOrchestrator(headless=False, on_pause=on_pause)
            return await orchestrator.run(
                persona=target_persona,
                product_name=product_name,
                product_url=product_url,
                target_action=pm_hva,
                max_steps=max_steps,
                on_step=on_step
            )

        with st.status("🏃 Agent running...", expanded=False) as agent_status:
            try:
                run_results = asyncio.run(run_orchestrator())
                agent_status.update(label="✅ Agent finished", state="complete")
            except Exception as e:
                st.error(f"Agent crashed: {e}")
                run_results = {
                    "status": "failed", "run_success": False,
                    "failure_reason": str(e), "steps": counters["step"],
                    "friction_events": counters["friction"], "total_tokens": 0, "history": []
                }
                agent_status.update(label="❌ Agent crashed", state="error")
            finally:
                # Always log — even partial/crashed runs
                if run_results:
                    try:
                        logger = RunLogger()
                        all_personas_data = [p.model_dump() for p in analysis.target_personas]
                        logger.log_run(
                            persona_name=target_persona.name,
                            product_name=product_name,
                            target_action=pm_hva,
                            run_results=run_results,
                            generated_personas=all_personas_data,
                            inferred_hva=analysis.inferred_high_value_action,
                            pm_hypothesis_alignment=analysis.pm_hypothesis_alignment
                        )
                    except Exception as log_err:
                        st.warning(f"Run completed but logging failed: {log_err}")

        # ── Phase 3: Results ──────────────────────────────────────────────
        st.divider()
        st.markdown("### 📊 Audit Results")
        
        if run_results:
            is_success = run_results.get("run_success", False)
            status_class = "status-success" if is_success else "status-failed"
            status_text = "✅ HVA Achieved!" if is_success else "❌ Did not reach HVA"
            
            st.markdown(f'<h3 class="{status_class}">{status_text}</h3>', unsafe_allow_html=True)
            
            if run_results.get("failure_reason"):
                st.warning(f"**Failure reason:** {run_results['failure_reason']}")

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Steps Taken", run_results.get("steps", 0))
            r2.metric("Friction Events", run_results.get("friction_events", 0))
            r3.metric("Total Tokens", f"{run_results.get('total_tokens', 0):,}")
            r4.metric("Status", run_results.get("status", "unknown"))
            st.success("Run saved to `data/runs/runs.jsonl`")

        st.session_state.run_active = False

    elif submitted:
        st.warning("Please fill in both the URL and HVA fields.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: Past Runs
# ═══════════════════════════════════════════════════════════════════════════════
with tab_past:
    st.markdown("# 📋 Past Runs")
    
    runs = load_past_runs()
    
    if not runs:
        st.info("No runs found yet. Run an audit from the **New Audit** tab!")
    else:
        # Filters
        col_f1, col_f2 = st.columns([2, 1])
        with col_f1:
            products = sorted(set(r.get("product", "Unknown") for r in runs))
            selected_product = st.selectbox("Filter by product", ["All"] + products)
        with col_f2:
            selected_status = st.selectbox("Filter by status", ["All", "success", "failed", "timeout"])

        filtered = runs
        if selected_product != "All":
            filtered = [r for r in filtered if r.get("product") == selected_product]
        if selected_status != "All":
            filtered = [r for r in filtered if r.get("status") == selected_status]

        st.caption(f"Showing {len(filtered)} of {len(runs)} runs")

        for run in reversed(filtered):
            run_id = run.get("run_id", run.get("timestamp", "unknown"))
            product = run.get("product", "Unknown")
            persona = run.get("persona", "Unknown")
            status = run.get("status", "unknown")
            steps = run.get("steps", 0)
            friction = run.get("friction_events", 0)
            tokens = run.get("total_tokens", 0)

            status_emoji = {"success": "✅", "failed": "❌", "timeout": "⏱️"}.get(status, "❓")
            
            with st.expander(f"{status_emoji} **{product}** — {persona} ({steps} steps, {friction} friction) — {run_id}"):
                # HVA Audit
                if run.get("llm_inferred_hva"):
                    c1, c2 = st.columns(2)
                    c1.markdown(f"**PM's HVA:** {run.get('target_action', 'N/A')}")
                    c2.markdown(f"**LLM HVA:** {run.get('llm_inferred_hva', 'N/A')}")
                    if run.get("hva_audit_alignment"):
                        st.info(run["hva_audit_alignment"])

                # Personas
                if run.get("generated_personas"):
                    st.markdown(f"**Personas:** {', '.join(run['generated_personas'])}")

                # Metrics row
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Steps", steps)
                m2.metric("Friction", friction)
                m3.metric("Tokens", f"{tokens:,}")
                m4.metric("Status", status)

                if run.get("failure_reason"):
                    st.warning(f"**Failure:** {run['failure_reason']}")

                # Step history
                history = run.get("history", [])
                if history:
                    st.markdown("#### Step Timeline")
                    for step_data in history:
                        st.markdown(
                            render_step_bubble(step_data, persona),
                            unsafe_allow_html=True
                        )
                        # Try to load screenshot from disk
                        screenshot_path = step_data.get("screenshot_path")
                        if screenshot_path and os.path.exists(screenshot_path):
                            st.image(screenshot_path, caption=f"Step {step_data.get('step', '?')}", use_container_width=True)
                else:
                    st.caption("No step history recorded for this run.")
