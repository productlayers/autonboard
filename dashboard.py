"""
BFF Dashboard — Streamlit UI for the Best Foot Forward UX Auditor.
Launch: uv run streamlit run dashboard.py
"""
import asyncio
import base64
import json
import os
import re

import httpx
import streamlit as st
from dotenv import load_dotenv

from src.agent.orchestrator import AgentOrchestrator
from src.agent.reflector import AuditReflector
from src.evals.metrics import EvalMetrics
from src.insights.analyzer import UXAnalyzer
from src.insights.logger import RunLogger
import streamlit.components.v1 as st_components
from src.insights.narrator import Narrator, voice_for_persona
from src.personas.generator import PersonaGenerator

load_dotenv()

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Best Foot Forward — AI UX Auditor",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Hero section */
.hero-title { font-size: 2.4rem; font-weight: 700; background: linear-gradient(135deg, #a78bfa 0%, #6366f1 50%, #818cf8 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.2rem; }
.hero-subtitle { color: #9ca3af; font-size: 1.05rem; margin-bottom: 1.5rem; }

/* Goal comparison cards */
.goal-card {
    background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
    border: 1px solid #3a3a5c;
    border-radius: 12px;
    padding: 1.2rem;
    margin-bottom: 0.5rem;
}
.goal-card h4 { margin: 0 0 0.5rem 0; color: #a78bfa; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; }
.goal-card p { margin: 0; color: #e2e8f0; font-size: 1rem; }

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

/* ── Animations ── */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes slideInLeft {
    from { opacity: 0; transform: translateX(-12px); }
    to { opacity: 1; transform: translateX(0); }
}
@keyframes scaleIn {
    from { opacity: 0; transform: scale(0.95); }
    to { opacity: 1; transform: scale(1); }
}

/* ── Report Container ── */
.report-header {
    animation: scaleIn 0.4s ease-out;
    background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
    border: 1px solid #2a2a4a;
    border-radius: 16px;
    padding: 2rem;
    margin: 1rem 0;
    position: relative;
    overflow: hidden;
}
.report-header::before {
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(circle at 30% 50%, rgba(167, 139, 250, 0.06) 0%, transparent 50%);
    pointer-events: none;
}
.report-title {
    font-size: 1.6rem;
    font-weight: 700;
    background: linear-gradient(135deg, #a78bfa, #818cf8, #6366f1);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0.5rem;
}
.report-tldr {
    color: #d1d5db;
    font-size: 1rem;
    line-height: 1.6;
    margin-top: 0.8rem;
}

/* Verdict badges — pill with glow */
.verdict-strong {
    background: linear-gradient(135deg, #065f46, #10b981);
    color: white;
    padding: 0.5rem 1.4rem;
    border-radius: 24px;
    font-weight: 700;
    font-size: 0.85rem;
    display: inline-block;
    box-shadow: 0 0 20px rgba(16, 185, 129, 0.3);
    letter-spacing: 0.03em;
}
.verdict-needs-work {
    background: linear-gradient(135deg, #92400e, #f59e0b);
    color: black;
    padding: 0.5rem 1.4rem;
    border-radius: 24px;
    font-weight: 700;
    font-size: 0.85rem;
    display: inline-block;
    box-shadow: 0 0 20px rgba(245, 158, 11, 0.3);
    letter-spacing: 0.03em;
}
.verdict-broken {
    background: linear-gradient(135deg, #991b1b, #ef4444);
    color: white;
    padding: 0.5rem 1.4rem;
    border-radius: 24px;
    font-weight: 700;
    font-size: 0.85rem;
    display: inline-block;
    box-shadow: 0 0 20px rgba(239, 68, 68, 0.3);
    letter-spacing: 0.03em;
}

/* Section headers */
.section-header {
    font-size: 1.1rem;
    font-weight: 700;
    color: #e2e8f0;
    margin: 1.5rem 0 0.8rem 0;
    padding-bottom: 0.4rem;
    border-bottom: 2px solid #2a2a4a;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.section-count {
    background: #2a2a4a;
    color: #a78bfa;
    font-size: 0.7rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 10px;
}

/* Pull quote / callout */
.pull-quote {
    animation: slideInLeft 0.4s ease-out;
    background: linear-gradient(135deg, #1e1e3a 0%, #16213e 100%);
    border-left: 4px solid #a78bfa;
    border-radius: 0 12px 12px 0;
    padding: 1.2rem 1.5rem;
    margin: 1rem 0;
    font-size: 1.05rem;
    color: #e2e8f0;
    line-height: 1.6;
    font-style: italic;
}
.pull-quote .pq-label {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #a78bfa;
    font-weight: 700;
    font-style: normal;
    margin-bottom: 0.4rem;
}

/* Observation card */
.obs-card {
    animation: fadeInUp 0.3s ease-out both;
    background: #1a1a2e;
    border-left: 4px solid #3b82f6;
    border-radius: 0 12px 12px 0;
    padding: 1rem 1.2rem;
    margin-bottom: 0.8rem;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.obs-card:hover { transform: translateX(4px); box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
.obs-card.obs-critical { border-left-color: #ef4444; }
.obs-card.obs-major { border-left-color: #f59e0b; }
.obs-card.obs-minor { border-left-color: #6b7280; }
.obs-card .obs-meta { color: #9ca3af; font-size: 0.75rem; margin-bottom: 0.4rem; display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.obs-card .obs-tag { padding: 1px 8px; border-radius: 8px; font-size: 0.7rem; font-weight: 600; }
.obs-tag-critical { background: rgba(239,68,68,0.2); color: #fca5a5; }
.obs-tag-major { background: rgba(245,158,11,0.2); color: #fcd34d; }
.obs-tag-minor { background: rgba(107,114,128,0.2); color: #d1d5db; }
.obs-card .obs-text { color: #e2e8f0; font-size: 0.9rem; line-height: 1.6; }

/* Category tags — distinct colors */
.cat-tag {
    padding: 1px 8px;
    border-radius: 8px;
    font-size: 0.7rem;
    font-weight: 600;
}
.cat-dead-end { background: #3b0f0f; color: #fca5a5; }
.cat-confusing-ui { background: #2d1b00; color: #fcd34d; }
.cat-loop { background: #1e0a3e; color: #c4b5fd; }
.cat-auth-wall { background: #1c1917; color: #fbbf24; }
.cat-good { background: #052e16; color: #6ee7b7; }
.cat-broken { background: #2a0a0a; color: #fca5a5; }
.cat-friction { background: #1a1000; color: #fde68a; }
.cat-missing { background: #172554; color: #93c5fd; }
.cat-default { background: #1e1e2e; color: #9ca3af; }

/* Recommendation card */
.rec-card {
    animation: fadeInUp 0.3s ease-out both;
    background: linear-gradient(135deg, #1e1e2e 0%, #1a2332 100%);
    border: 1px solid #2a3a5c;
    border-radius: 12px;
    padding: 1.2rem;
    margin-bottom: 0.8rem;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    position: relative;
}
.rec-card:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.3); }
.rec-card .rec-header { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; flex-wrap: wrap; }
.rec-card .rec-priority { font-weight: 700; font-size: 0.75rem; padding: 3px 10px; border-radius: 8px; display: inline-block; text-transform: uppercase; letter-spacing: 0.05em; }
.rec-p0 { background: linear-gradient(135deg, #dc2626, #ef4444); color: white; box-shadow: 0 0 12px rgba(239,68,68,0.3); }
.rec-p1 { background: linear-gradient(135deg, #d97706, #f59e0b); color: black; }
.rec-p2 { background: #4b5563; color: #d1d5db; }
.rec-card .rec-area { color: #a78bfa; font-size: 0.8rem; font-weight: 600; }
.rec-card .rec-text { color: #e2e8f0; font-size: 0.9rem; line-height: 1.6; }
.rec-card .rec-evidence { color: #9ca3af; font-size: 0.8rem; font-style: italic; margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid #2a2a4a; }

/* Bright spot */
.bright-spot {
    animation: slideInLeft 0.3s ease-out both;
    background: #0d2818;
    border: 1px solid #166534;
    border-radius: 10px;
    padding: 0.6rem 1rem;
    color: #6ee7b7;
    font-size: 0.9rem;
    margin-bottom: 0.5rem;
    line-height: 1.5;
    transition: transform 0.15s ease;
}
.bright-spot:hover { transform: translateX(3px); }

/* Next step — timeline style */
.next-step-timeline {
    animation: fadeInUp 0.3s ease-out both;
    display: flex;
    gap: 1rem;
    margin-bottom: 1rem;
    align-items: flex-start;
}
.step-circle {
    width: 32px;
    height: 32px;
    min-width: 32px;
    border-radius: 50%;
    background: linear-gradient(135deg, #6366f1, #818cf8);
    color: white;
    font-weight: 700;
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 0 12px rgba(99, 102, 241, 0.3);
}
.step-content {
    background: #131330;
    border: 1px solid #312e81;
    border-radius: 10px;
    padding: 0.8rem 1rem;
    color: #c7d2fe;
    font-size: 0.9rem;
    line-height: 1.5;
    flex: 1;
}

/* Persona impact card */
.persona-impact-card {
    background: linear-gradient(135deg, #1a1a2e 0%, #1e1e3a 100%);
    border: 1px solid #3a3a5c;
    border-radius: 12px;
    padding: 1.2rem;
    color: #d1d5db;
    font-size: 0.9rem;
    line-height: 1.6;
    font-style: italic;
}

/* Narrative block */
.narrative-block {
    animation: fadeInUp 0.4s ease-out;
    background: #0f0f1a;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 1.5rem;
    color: #d1d5db;
    font-size: 0.95rem;
    line-height: 1.8;
    margin-bottom: 1rem;
}

/* Goal Framing block (insights → Story tab) */
.framing-wrap {
    background: linear-gradient(135deg, #161628 0%, #1a1a30 100%);
    border: 1px solid #2e2e54;
    border-radius: 14px;
    padding: 1.1rem 1.3rem 1.2rem 1.3rem;
    margin-bottom: 1.2rem;
}
.framing-label {
    font-size: 0.72rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #a78bfa;
    font-weight: 600;
    margin-bottom: 0.75rem;
}
.framing-row { display: flex; gap: 0.9rem; margin-bottom: 0.9rem; }
.framing-cell {
    flex: 1;
    background: #0f0f1c;
    border: 1px solid #2a2a4a;
    border-radius: 10px;
    padding: 0.8rem 0.95rem;
}
.framing-cell-label {
    font-size: 0.68rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #9ca3af;
    font-weight: 600;
    margin-bottom: 0.35rem;
}
.framing-cell-value {
    color: #e2e8f0;
    font-size: 0.95rem;
    line-height: 1.45;
}
.framing-cell.researched .framing-cell-label { color: #c7d2fe; }
.framing-cell.researched { border-color: #4338ca; }
.framing-alignment {
    background: #11192e;
    border-left: 3px solid #6366f1;
    border-radius: 0 8px 8px 0;
    padding: 0.7rem 0.95rem;
    color: #cbd5e1;
    font-size: 0.88rem;
    line-height: 1.55;
}
.framing-alignment-label {
    color: #818cf8;
    font-weight: 600;
    font-size: 0.72rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 0.3rem;
    display: block;
}
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
    with open(log_file) as f:
        for line in f:
            if line.strip():
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return runs


def _get_step_screenshot_bytes(step_data: dict) -> bytes | None:
    """Load step screenshot from inline base64 or disk path (logged runs strip base64)."""
    screenshot_b64 = step_data.get("screenshot_base64")
    if screenshot_b64:
        try:
            return base64.b64decode(screenshot_b64)
        except Exception:
            pass
    screenshot_path = step_data.get("screenshot_path")
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            with open(screenshot_path, "rb") as f:
                return f.read()
        except Exception:
            pass
    return None


def _find_step_in_history(history: list[dict], step_ref: int) -> dict | None:
    for step_data in history:
        if step_data.get("step") == step_ref:
            return step_data
    if 1 <= step_ref <= len(history):
        return history[step_ref - 1]
    return None


def render_insights(insights_data: dict, run_data: dict | None = None):
    """Renders the full narrative UX audit report."""
    
    # Detect old-schema files (they have completion_summary instead of tldr)
    if "completion_summary" in insights_data and "tldr" not in insights_data:
        st.warning("⚠️ This report was generated with an older format. Click **Generate UX Audit Report** to regenerate with the new narrative format.")
        st.info(f"**Old Summary:** {insights_data.get('completion_summary', '')}")
        return
    
    st.markdown("---")
    
    # ── Report Header: verdict + TL;DR (always visible) ──
    verdict = insights_data.get("verdict", "")
    verdict_class = {
        "Strong Onboarding": "verdict-strong",
        "Needs Work": "verdict-needs-work",
        "Critically Broken": "verdict-broken"
    }.get(verdict, "verdict-needs-work")
    tldr = insights_data.get("tldr", "")
    
    st.markdown(f"""<div class="report-header">
        <div class="report-title">🧠 UX Audit Report</div>
        {f'<span class="{verdict_class}">{verdict}</span>' if verdict else ''}
        {f'<div class="report-tldr">{tldr}</div>' if tldr else ''}
    </div>""", unsafe_allow_html=True)
    
    # ── At-a-Glance Stats Row ──
    observations = insights_data.get("observations", [])
    recommendations = insights_data.get("recommendations", [])
    bright_spots = insights_data.get("bright_spots", [])
    next_steps = insights_data.get("next_steps", [])
    
    n_critical = sum(1 for o in observations if o.get("severity") == "critical")
    n_major = sum(1 for o in observations if o.get("severity") == "major")
    n_minor = sum(1 for o in observations if o.get("severity") == "minor")
    n_p0 = sum(1 for r in recommendations if r.get("priority") == "P0")
    
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("🔴 Critical", n_critical)
    s2.metric("🟡 Major", n_major)
    s3.metric("⚪ Minor", n_minor)
    s4.metric("🚨 P0 Fixes", n_p0)
    s5.metric("✅ Bright Spots", len(bright_spots))
    
    # ── Tabbed Report Sections ──
    tab_story, tab_findings, tab_actions = st.tabs(["📖 Story", f"🔍 Findings ({len(observations)})", f"💡 Actions ({len(recommendations)})"])
    
    # ── Helper: map UX category to CSS class ──
    def cat_class(category: str) -> str:
        mapping = {
            "Dead End": "cat-dead-end", "Confusing UI": "cat-confusing-ui",
            "Loop": "cat-loop", "Auth Wall": "cat-auth-wall",
            "Good Experience": "cat-good", "Broken Interaction": "cat-broken",
            "Excessive Friction": "cat-friction", "Missing Affordance": "cat-missing",
        }
        return mapping.get(category, "cat-default")
    
    # ── TAB: Story ──
    with tab_story:
        # Goal Framing — interpret everything below against the right success criterion.
        # Reads from run_data (live runs plumb HVA in; historical runs have it in runs.jsonl).
        pm_goal = (run_data or {}).get("target_action", "")
        research_hva = (run_data or {}).get("llm_inferred_hva", "")
        alignment = (run_data or {}).get("hva_audit_alignment", "")
        if pm_goal or research_hva:
            st.markdown(f"""<div class="framing-wrap">
                <div class="framing-label">🎯 Goal Framing</div>
                <div class="framing-row">
                    <div class="framing-cell">
                        <div class="framing-cell-label">Your Hypothesis</div>
                        <div class="framing-cell-value">{pm_goal or "—"}</div>
                    </div>
                    <div class="framing-cell researched">
                        <div class="framing-cell-label">Research-Backed HVA</div>
                        <div class="framing-cell-value">{research_hva or "—"}</div>
                    </div>
                </div>
                {f'''<div class="framing-alignment">
                    <span class="framing-alignment-label">Alignment</span>
                    {alignment}
                </div>''' if alignment else ''}
            </div>""", unsafe_allow_html=True)

        narrative = insights_data.get("narrative", "")
        if narrative:
            # Extract first sentence as a pull-quote
            first_sentence = narrative.split(". ")[0] + "." if ". " in narrative else ""
            if first_sentence and len(first_sentence) < 200:
                st.markdown(f"""<div class="pull-quote">
                    <div class="pq-label">Key Takeaway</div>
                    {first_sentence}
                </div>""", unsafe_allow_html=True)
            
            st.markdown(f'<div class="narrative-block">{narrative}</div>', unsafe_allow_html=True)
        
        # Bright spots + Persona impact side by side
        col_left, col_right = st.columns(2)
        with col_left:
            if bright_spots:
                st.markdown(f'<div class="section-header">✅ What Worked <span class="section-count">{len(bright_spots)}</span></div>', unsafe_allow_html=True)
                for spot in bright_spots:
                    st.markdown(f'<div class="bright-spot">✅ {spot}</div>', unsafe_allow_html=True)
        with col_right:
            persona_impact = insights_data.get("persona_impact", "")
            if persona_impact:
                st.markdown('<div class="section-header">🎭 Persona Impact</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="persona-impact-card">{persona_impact}</div>', unsafe_allow_html=True)
    
    # ── TAB: Findings ──
    with tab_findings:
        if observations:
            critical_obs = [o for o in observations if o.get("severity") == "critical"]
            major_obs = [o for o in observations if o.get("severity") == "major"]
            other_obs = [o for o in observations if o.get("severity") not in ("critical", "major")]
            
            for group_label, group, _sev in [("🔴 Critical Issues", critical_obs, "critical"), ("🟡 Major Issues", major_obs, "major"), ("⚪ Other Observations", other_obs, "minor")]:
                if group:
                    st.markdown(f'<div class="section-header">{group_label} <span class="section-count">{len(group)}</span></div>', unsafe_allow_html=True)
                    for obs in group:
                        severity = obs.get("severity", "minor")
                        category = obs.get("ux_category", "")
                        cc = cat_class(category)
                        st.markdown(f"""<div class="obs-card obs-{severity}">
                            <div class="obs-meta">
                                <span class="obs-tag obs-tag-{severity}">{severity.upper()}</span>
                                <span class="cat-tag {cc}">{category}</span>
                                <span>{obs.get('step_range', '')}</span>
                                <span>·</span>
                                <span>{obs.get('funnel_stage', '').replace('_', ' ')}</span>
                            </div>
                            <div class="obs-text">{obs.get('observation', '')}</div>
                        </div>""", unsafe_allow_html=True)
        else:
            st.info("No observations recorded.")
    
    # ── TAB: Actions ──
    with tab_actions:
        col_recs, col_next = st.columns([3, 2])
        
        with col_recs:
            if recommendations:
                st.markdown(f'<div class="section-header">💡 Recommendations <span class="section-count">{len(recommendations)}</span></div>', unsafe_allow_html=True)
                for rec in recommendations:
                    priority = rec.get("priority", "P2")
                    priority_class = {"P0": "rec-p0", "P1": "rec-p1", "P2": "rec-p2"}.get(priority, "rec-p2")
                    
                    st.markdown(f"""<div class="rec-card">
                        <div class="rec-header" style="margin-bottom: 0.5rem;">
                            <div style="display: flex; gap: 0.5rem; align-items: center;">
                                <span class="rec-priority {priority_class}">{priority}</span>
                                {f'<span class="rec-priority" style="background:#f3f4f6;color:#374151;border:1px solid #d1d5db;">{rec.get("effort", "Medium")} Effort</span>' if "effort" in rec else ""}
                            </div>
                            <span class="rec-area">{rec.get('area', '')}</span>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    if "recommendation" in rec and "proposed_state" not in rec:
                        st.markdown(f'<div class="rec-text">{rec.get("recommendation", "")}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="rec-text" style="font-weight: 600; font-size: 1.05rem; margin-bottom: 0.5rem; color: #111827;">{rec.get("title", "Recommendation")}</div>', unsafe_allow_html=True)
                        st.markdown(f'<div class="rec-text" style="margin-bottom: 0.25rem;"><span style="color: #ef4444; font-weight: 600;">Current:</span> {rec.get("current_state", "")}</div>', unsafe_allow_html=True)
                        st.markdown(f'<div class="rec-text" style="margin-bottom: 0.5rem;"><span style="color: #10b981; font-weight: 600;">Proposed:</span> {rec.get("proposed_state", "")}</div>', unsafe_allow_html=True)

                    step_ref = rec.get("step_reference")
                    rec_screenshot: bytes | None = None
                    if step_ref is not None and run_data:
                        step_data = _find_step_in_history(run_data.get("history", []), int(step_ref))
                        if step_data:
                            rec_screenshot = _get_step_screenshot_bytes(step_data)

                    st.markdown(
                        f'<div class="rec-evidence" style="margin-top: 0.5rem; border-top: 1px dashed #e5e7eb; padding-top: 0.5rem;">📎 {rec.get("evidence", "")}</div>',
                        unsafe_allow_html=True,
                    )
                    if rec_screenshot:
                        st.image(
                            rec_screenshot,
                            caption=f"Step {step_ref} — where this issue appears",
                            use_container_width=True,
                        )

                    st.markdown("</div>", unsafe_allow_html=True)
        
        with col_next:
            if next_steps:
                st.markdown(f'<div class="section-header">🚀 Next Steps <span class="section-count">{len(next_steps)}</span></div>', unsafe_allow_html=True)
                for i, step in enumerate(next_steps, 1):
                    st.markdown(f"""<div class="next-step-timeline">
                        <div class="step-circle">{i}</div>
                        <div class="step-content">{step}</div>
                    </div>""", unsafe_allow_html=True)


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ✨ Best Foot Forward")
    st.caption("AI-Powered UX Auditor")
    st.divider()

    with st.expander("💡 How It Works", expanded=False):
        st.markdown("""
        1. **Paste a URL** and define what success looks like
        2. **AI generates personas** — real user archetypes for your product
        3. **An autonomous agent** navigates your product as that persona
        4. **You get a UX audit report** with findings, recommendations, and next steps
        """)

    # Live stats (updated during runs)
    if "run_active" in st.session_state and st.session_state.run_active:
        st.markdown("### 📊 Live Stats")
        stats_placeholder = st.empty()
    
    # Global metrics
    metrics = EvalMetrics().get_metrics()
    st.markdown("### 📊 All-Time Stats")
    col1, col2 = st.columns(2)
    col1.metric("Audits Run", metrics["total_runs"])
    col2.metric("Success Rate", f"{metrics['completion_rate']:.0%}")
    col1.metric("Avg Friction", f"{metrics['avg_friction_events']:.1f}")
    col2.metric("Avg Steps", f"{metrics['avg_steps']:.1f}")

    st.divider()

    with st.expander("📖 Glossary"):
        st.markdown("""
        **Success Goal** — The first meaningful action you want new users to complete (e.g., "create a project").
        
        **Friction Event** — Any moment the user got stuck: CAPTCHAs, auth walls, confusing UI, broken buttons.
        
        **Funnel Stage** — Where in the journey the user is:
        `Landing` → `Signup` → `Auth` → `Onboarding` → `Tour` → `First Action` → `Goal Achieved`
        
        **Steps** — Total actions taken before completing or timing out (max 30).
        
        **Success Rate** — % of audits where the persona successfully reached the goal.
        """)


# ── Main Content ─────────────────────────────────────────────────────────────

tab_new, tab_past = st.tabs(["🚀 Run New Audit", "📊 Audit History"])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: New Audit
# ═══════════════════════════════════════════════════════════════════════════════
with tab_new:
    st.markdown('<div class="hero-title">Best Foot Forward</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">Paste any product URL. Our AI adopts a real user persona, navigates your onboarding, and delivers a full UX audit — in minutes, not weeks.</div>', unsafe_allow_html=True)

    # Input form
    with st.form("audit_form"):
        product_url = st.text_input("🔗 Product URL", placeholder="https://www.notion.so", help="The landing page or signup page of the product you want to audit.")
        pm_hva = st.text_input("🎯 Success Goal", placeholder="Create a new page and add a heading", help="What's the first meaningful thing you want a new user to accomplish? This is the goal your AI persona will try to reach.")
        # 🔊 Live Narration hidden — Web Speech API has two blockers:
        # (1) robotic OS voices, no neural TTS quality
        # (2) each st_components.html() call is a separate iframe so
        #     speechSynthesis.cancel() can't stop the previous utterance → overlap
        # Revisit when ElevenLabs free tier or OpenAI TTS is wired up.
        narration_on = False  # st.toggle("🔊 Live Narration", value=False, ...)

        prompt_version = st.radio(
            "🧪 A/B Test",
            options=["v1", "v2"],
            index=0,
            horizontal=True,
            captions=[
                "v1 — Original system prompt (verbose, 16 rules, ~2,200 tokens)",
                "v2 — Refactored system prompt (persona-first, 4 rules, ~700 tokens)",
            ],
            help="Active test: system prompt version. Pick a variant per run to compare voice quality, cost, and success rate side-by-side. This control will host future A/B tests (DOM trimming, model swaps, retrieval modes) as they ship.",
        )

        submitted = st.form_submit_button("🚀 Start UX Audit", use_container_width=True, type="primary")

    if submitted and product_url and pm_hva:
        # Ensure URL has scheme
        if not product_url.startswith("http"):
            product_url = "https://" + product_url

        st.session_state.run_active = True

        # ── Phase 0: Product Discovery ────────────────────────────────────
        with st.status("🔍 Discovering product...", expanded=True) as phase0:
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
            phase0.update(label=f"✅ Discovered **{product_name}**", state="complete")

        # ── Phase 1: Persona Generation & HVA Audit ───────────────────────
        with st.status("🧠 Generating AI personas...", expanded=True) as phase1:
            async def generate_personas():
                gen = PersonaGenerator()
                return await gen.analyze_product(product_name, product_desc, pm_hva)
            
            analysis = asyncio.run(generate_personas())
            phase1.update(label="✅ AI personas generated", state="complete")

        # NOTE: HVA comparison moved to insights section (Story tab) — it's a finding
        # to interpret findings against, not a setup parameter to show before the run.

        # Persona Cards
        st.markdown("### 👥 AI-Generated Personas")
        st.caption("These are the user archetypes our AI generated for your product. The first persona will be used for this audit.")
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
        target_persona = analysis.target_personas[0]
        st.markdown("### 🤖 Live Audit")
        st.caption(f"Watching **{target_persona.name}** navigate your product in real-time...")
        
        steps_container = st.container()
        progress_bar = st.progress(0, text="Starting agent...")
        
        # Sidebar live stats
        sidebar_stats = st.sidebar.empty()
        
        # Mutable counters (can't use nonlocal at module scope in Streamlit)
        counters = {"step": 0, "friction": 0, "tokens": 0}
        max_steps = 30
        
        # Initialize narrator if toggle is on — voice params matched to persona's tech literacy
        narrator = Narrator(voice=voice_for_persona(target_persona)) if narration_on else None

        def on_step(step_dict):
            counters["step"] = step_dict.get("step", counters["step"] + 1)
            if step_dict.get("action_type") == "pause_for_human":
                if step_dict.get("funnel_stage") not in ["signup_wall", "authentication"]:
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
            
            # Live narration — Web Speech API, runs entirely in browser (no API cost)
            if narrator:
                reasoning = step_dict.get("reasoning", "")
                if reasoning:
                    js_snippet = narrator.narrate(reasoning)
                    if js_snippet:
                        st_components.html(js_snippet, height=0)
            
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
            orchestrator = AgentOrchestrator(headless=False, on_pause=on_pause, prompt_version=prompt_version)
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
                        logged_run_id = logger.log_run(
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

                # Phase 3.5: Reflection — extract L1 atoms + insights. Best effort.
                if 'logged_run_id' in locals() and run_results and run_results.get("steps", 0) > 0:
                    with st.status("🪞 Reflecting on the audit...", expanded=False) as reflect_status:
                        try:
                            async def do_reflect():
                                reflector = AuditReflector()
                                return await reflector.run_full_reflection(
                                    persona=target_persona,
                                    target_action=pm_hva,
                                    product_name=product_name,
                                    run_results=run_results,
                                    run_id=logged_run_id,
                                )

                            atoms_written, insights_path = asyncio.run(do_reflect())
                            if atoms_written:
                                st.success(f"Wrote {atoms_written} L1 atoms to memory")
                            if insights_path:
                                st.caption(f"Reflector Insights report: `{insights_path}`")
                            reflect_status.update(label="✅ Reflection complete", state="complete")
                        except Exception as ref_err:
                            reflect_status.update(
                                label=f"⚠️ Reflection failed (run still logged): {ref_err}", state="error"
                            )

        # ── Phase 4: Results ──────────────────────────────────────────────
        st.divider()
        st.markdown("### 📊 Audit Results")
        
        if run_results:
            # Auto-analyze run
            with st.status("🧠 Writing UX Audit Report...", expanded=True) as insight_status:
                try:
                    analyzer = UXAnalyzer()
                    full_run_data = {
                        "run_id": logged_run_id if 'logged_run_id' in locals() else "latest",
                        "product": product_name,
                        "persona": target_persona.name,
                        "target_action": pm_hva,
                        "status": run_results.get("status"),
                        "failure_reason": run_results.get("failure_reason"),
                        "generated_personas": [p.model_dump() for p in analysis.target_personas],
                        "history": run_results.get("history", [])
                    }
                    async def run_analyzer():
                        return await analyzer.analyze_run(full_run_data)
                    findings = asyncio.run(run_analyzer())
                    
                    if 'logged_run_id' in locals() and logged_run_id:
                        analyzer.save_insights(logged_run_id, findings)
                    
                    insight_status.update(label="✅ UX Audit Report Generated", state="complete")
                except Exception as e:
                    findings = None
                    insight_status.update(label=f"❌ Insight extraction failed: {e}", state="error")
            
            if findings:
                # Plumb HVA fields into run_data so the Goal Framing block in render_insights
                # works the same for live runs as for historical runs from runs.jsonl.
                run_results_with_hva = {
                    **run_results,
                    "target_action": pm_hva,
                    "llm_inferred_hva": analysis.inferred_high_value_action,
                    "hva_audit_alignment": analysis.pm_hypothesis_alignment,
                }
                render_insights(findings.model_dump(), run_results_with_hva)

            is_success = run_results.get("run_success", False)
            status_class = "status-success" if is_success else "status-failed"
            status_text = "✅ Success Goal Achieved!" if is_success else "❌ Did not reach Success Goal"
            
            st.markdown(f'<h3 class="{status_class}">{status_text}</h3>', unsafe_allow_html=True)
            
            if run_results.get("failure_reason"):
                st.warning(f"**Failure reason:** {run_results['failure_reason']}")

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Steps Taken", run_results.get("steps", 0))
            r2.metric("Friction Events", run_results.get("friction_events", 0))
            r3.metric("Total Tokens", f"{run_results.get('total_tokens', 0):,}")
            r4.metric("Status", run_results.get("status", "unknown"))
            st.success("✅ Audit saved successfully.")

        st.session_state.run_active = False

    elif submitted:
        st.warning("Please fill in both the URL and HVA fields.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: Past Runs
# ═══════════════════════════════════════════════════════════════════════════════
with tab_past:
    st.markdown("# 📊 Audit History")
    st.caption("Browse past audits and generate UX insight reports for any run.")
    
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
                    c1.markdown(f"**Your Goal:** {run.get('target_action', 'N/A')}")
                    c2.markdown(f"**AI Goal:** {run.get('llm_inferred_hva', 'N/A')}")
                    if run.get("hva_audit_alignment"):
                        st.info(run["hva_audit_alignment"])

                # Personas
                if run.get("generated_personas"):
                    persona_names = [p.get("name", "Unknown") if isinstance(p, dict) else str(p) for p in run["generated_personas"]]
                    st.markdown(f"**Personas:** {', '.join(persona_names)}")

                # Metrics row
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Steps", steps)
                m2.metric("Friction", friction)
                m3.metric("Tokens", f"{tokens:,}")
                m4.metric("Status", status)

                if run.get("failure_reason"):
                    st.warning(f"**Failure:** {run['failure_reason']}")

                # UX Insights
                analyzer = UXAnalyzer()
                insights_data = analyzer.load_insights(run_id)
                is_old_schema = insights_data and "completion_summary" in insights_data and "tldr" not in insights_data
                
                if insights_data and not is_old_schema:
                    render_insights(insights_data, run)
                
                # Show generate/regenerate button
                btn_label = "🔄 Regenerate with New Format" if is_old_schema else "🧠 Generate UX Audit Report"
                if (is_old_schema or not insights_data) and st.button(btn_label, key=f"btn_{run_id}"):
                        with st.spinner("Analyzing run transcript — this takes ~15 seconds..."):
                            try:
                                async def analyze(a=analyzer, r=run):
                                    return await a.analyze_run(r)
                                findings = asyncio.run(analyze())
                                analyzer.save_insights(run_id, findings)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed to generate insights: {e}")

                # Step history
                history = run.get("history", [])
                if history:
                    with st.expander("Show Step Timeline"):
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
