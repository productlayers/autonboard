"""
A/B compare prompt versions in runs.jsonl.

Filters runs by prompt_version (read from each step's record — set by
ActionPlanner via the PROMPT_VERSION env var), aggregates quantitative
metrics, and surfaces qualitative reasoning samples for side-by-side reads.

Usage:
    uv run python scripts/compare_prompt_versions.py
    uv run python scripts/compare_prompt_versions.py --runs data/runs/runs.jsonl
"""
import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def run_prompt_version(run: dict) -> str:
    """Read the prompt_version from the first step that has it; older runs default to 'v1'."""
    for step in run.get("history", []):
        if step.get("prompt_version"):
            return step["prompt_version"]
    return "v1-legacy"


def run_metrics(run: dict) -> dict:
    steps = run.get("history", [])
    step_count = len(steps)
    tokens = run.get("total_tokens", 0)
    cached = sum(s.get("cached_tokens", 0) or 0 for s in steps)
    return {
        "status": run.get("status", ""),
        "steps": step_count,
        "friction": run.get("friction_events", 0),
        "tokens": tokens,
        "cached_tokens": cached,
        "tokens_per_step": tokens / step_count if step_count else 0,
        "cache_hit_rate": cached / tokens if tokens else 0,
        "reached_hva": any(s.get("funnel_stage") == "hva_achieved" for s in steps),
    }


def summarize_bucket(label: str, runs: list[dict]) -> None:
    if not runs:
        print(f"\n{label}: no runs")
        return
    print(f"\n{label} — {len(runs)} runs")
    print("-" * 72)
    metrics = [run_metrics(r) for r in runs]
    n = len(metrics)
    successes = sum(1 for m in metrics if m["status"] == "success")
    hva = sum(1 for m in metrics if m["reached_hva"])
    avg_steps = sum(m["steps"] for m in metrics) / n
    avg_friction = sum(m["friction"] for m in metrics) / n
    runs_with_tokens = [m for m in metrics if m["tokens"]]
    avg_tps = (sum(m["tokens_per_step"] for m in runs_with_tokens) / len(runs_with_tokens)) if runs_with_tokens else 0
    cache_rates = [m["cache_hit_rate"] for m in runs_with_tokens if m["cache_hit_rate"]]
    avg_cache_rate = (sum(cache_rates) / len(cache_rates) * 100) if cache_rates else 0

    print(f"  Success rate:        {successes}/{n} ({successes/n*100:.0f}%)")
    print(f"  HVA reached:         {hva}/{n} ({hva/n*100:.0f}%)")
    print(f"  Avg steps:           {avg_steps:.1f}")
    print(f"  Avg friction events: {avg_friction:.1f}")
    print(f"  Avg tokens/step:     {avg_tps:,.0f}")
    print(f"  Cache hit rate:      {avg_cache_rate:.1f}%  ({len(cache_rates)}/{len(runs_with_tokens)} runs with cache data)")


def reasoning_samples(runs: list[dict], n_samples: int = 3) -> list[tuple[str, str, str]]:
    """Pull (product, persona, reasoning) tuples from runs for qualitative read."""
    pool = []
    for r in runs:
        product = r.get("product", "")
        persona = r.get("persona", "")
        for s in r.get("history", []):
            reasoning = (s.get("reasoning") or "").strip()
            stage = s.get("funnel_stage", "")
            if reasoning and stage not in ("authentication", "signup_wall"):
                pool.append((product, persona, reasoning, stage))
    if not pool:
        return []
    random.seed(42)
    return random.sample(pool, min(n_samples, len(pool)))


def matched_pairs(by_version: dict[str, list[dict]]) -> list[tuple[dict, dict]]:
    """Find (product, persona_name) combos that appear in BOTH v1 and v2 — strongest signal."""
    v1_runs = by_version.get("v1", []) + by_version.get("v1-legacy", [])
    v2_runs = by_version.get("v2", [])
    v1_index = {(r.get("product"), r.get("persona")): r for r in v1_runs}
    v2_index = {(r.get("product"), r.get("persona")): r for r in v2_runs}
    common = set(v1_index) & set(v2_index)
    return [(v1_index[k], v2_index[k]) for k in common]


def main() -> None:
    parser = argparse.ArgumentParser(description="A/B compare prompt versions")
    parser.add_argument("--runs", default="data/runs/runs.jsonl", help="Path to runs.jsonl")
    parser.add_argument("--samples", type=int, default=3, help="Reasoning samples per version")
    args = parser.parse_args()

    path = Path(args.runs)
    if not path.exists():
        print(f"Error: {path} not found")
        return

    runs = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                runs.append(json.loads(line))

    by_version: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by_version[run_prompt_version(r)].append(r)

    print("=" * 72)
    print(f"  PROMPT VERSION A/B  —  {len(runs)} total runs")
    print("=" * 72)
    print("\nDistribution by prompt_version:")
    for ver, ver_runs in sorted(by_version.items()):
        print(f"  {ver:<12} {len(ver_runs):>3} runs")

    for ver in sorted(by_version.keys()):
        summarize_bucket(f"\n▌ {ver.upper()}", by_version[ver])

    # Matched pairs — same product+persona run with both versions
    pairs = matched_pairs(by_version)
    if pairs:
        print(f"\n\nMATCHED PAIRS  ({len(pairs)} product/persona combos run on both versions)")
        print("=" * 72)
        for v1_r, v2_r in pairs[:5]:
            print(f"\n  {v1_r.get('product','?')} / {v1_r.get('persona','?')}")
            m1, m2 = run_metrics(v1_r), run_metrics(v2_r)
            print(f"    v1: steps={m1['steps']:>2}  friction={m1['friction']}  tokens/step={m1['tokens_per_step']:,.0f}  hva={'✓' if m1['reached_hva'] else '✗'}")
            print(f"    v2: steps={m2['steps']:>2}  friction={m2['friction']}  tokens/step={m2['tokens_per_step']:,.0f}  hva={'✓' if m2['reached_hva'] else '✗'}")

    # Qualitative samples
    print("\n\nREASONING SAMPLES (qualitative read — does v2 feel more distinct?)")
    print("=" * 72)
    for ver in ("v1", "v1-legacy", "v2"):
        if ver not in by_version:
            continue
        samples = reasoning_samples(by_version[ver], args.samples)
        if samples:
            print(f"\n  ── {ver} ──")
            for product, persona, reasoning, stage in samples:
                print(f"\n  [{product} / {persona} @ {stage}]")
                print(f"    \"{reasoning[:280]}{'...' if len(reasoning) > 280 else ''}\"")

    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
