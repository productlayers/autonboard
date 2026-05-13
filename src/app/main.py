import asyncio
import argparse
import httpx
from rich.console import Console
from dotenv import load_dotenv

from src.personas.generator import PersonaGenerator
from src.agent.orchestrator import AgentOrchestrator
from src.insights.logger import RunLogger
from src.evals.metrics import EvalMetrics

console = Console()

async def run_agent(product_url: str, product_name: str = None, pm_hva: str = "", headless: bool = False):
    # 0. Auto-Discover Product Description (lightweight httpx scrape, no browser)
    console.print("\n[bold blue]=== Phase 0: Auto-Discovering Product ===[/bold blue]")
    console.print(f"Scraping metadata from {product_url}...")
    product_desc = "No description found."
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            resp = await client.get(product_url, headers={"User-Agent": "Mozilla/5.0"})
            text = resp.text
            # Extract meta description
            import re
            match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', text, re.IGNORECASE)
            if not match:
                match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', text, re.IGNORECASE)
            if match:
                product_desc = match.group(1).strip()
            # Extract product name from og:site_name or <title> if not provided
            if not product_name:
                name_match = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', text, re.IGNORECASE)
                if not name_match:
                    name_match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:site_name["\']', text, re.IGNORECASE)
                if name_match:
                    product_name = name_match.group(1).strip()
                else:
                    # Fallback: extract from <title> (take first segment before common separators)
                    title_match = re.search(r'<title[^>]*>([^<]+)</title>', text, re.IGNORECASE)
                    if title_match:
                        raw_title = title_match.group(1).strip()
                        # Split on common separators: " - ", " | ", " — ", " · "
                        product_name = re.split(r'\s*[\-\|\—\·]\s*', raw_title)[0].strip()
    except Exception as e:
        console.print(f"[yellow]Could not scrape metadata: {e}[/yellow]")
    
    # Final fallback: derive from URL hostname
    if not product_name:
        from urllib.parse import urlparse
        hostname = urlparse(product_url).hostname or ""
        # Remove www. and .com/.io/etc
        product_name = hostname.replace("www.", "").split(".")[0].capitalize()
    
    console.print(f"Product Name: {product_name}")
    console.print(f"Scraped Description: {product_desc}")

    # 1. Generate Personas & HVA Audit
    console.print("\n[bold blue]=== Phase 1: Persona Generation & Audit ===[/bold blue]")
    generator = PersonaGenerator()
    analysis = await generator.analyze_product(product_name, product_desc, pm_hva)
    
    console.print(f"[bold]PM's Hypothesized HVA:[/bold] {pm_hva}")
    console.print(f"[bold]LLM's Inferred HVA:[/bold] {analysis.inferred_high_value_action}")
    console.print(f"[bold]Audit Alignment:[/bold] {analysis.pm_hypothesis_alignment}\n")
    
    console.print(f"[bold]Generated Personas:[/bold]")
    for p in analysis.target_personas:
        console.print(f"- {p.name} (Tech Literacy: {p.technical_literacy})")
        
    # Pick the first persona for this run
    target_persona = analysis.target_personas[0]
    
    # 2. Run Agent
    console.print("\n[bold blue]=== Phase 2: Agent Execution ===[/bold blue]")
    orchestrator = AgentOrchestrator(headless=headless)
    
    run_results = None
    try:
        run_results = await orchestrator.run(
            persona=target_persona,
            product_name=product_name,
            product_url=product_url,
            target_action=pm_hva, # We hold the agent to the PM's ground truth hypothesis
            max_steps=30
        )
    except KeyboardInterrupt:
        console.print(f"\n[bold red]Run interrupted by user (Ctrl+C).[/bold red]")
        run_results = getattr(orchestrator, 'partial_results', None) or {
            "status": "failed",
            "run_success": False,
            "failure_reason": "user_interrupted_ctrl_c",
            "steps": 0,
            "friction_events": 0,
            "total_tokens": 0,
            "history": []
        }
    except Exception as e:
        console.print(f"\n[bold red]Fatal error in orchestrator: {e}[/bold red]")
        run_results = getattr(orchestrator, 'partial_results', None) or {
            "status": "failed",
            "run_success": False,
            "failure_reason": f"orchestrator_crash: {type(e).__name__}: {e}",
            "steps": 0,
            "friction_events": 0,
            "total_tokens": 0,
            "history": []
        }
    finally:
        # Safety fallback if something truly unexpected happened
        if run_results is None:
            run_results = {
                "status": "failed",
                "run_success": False,
                "failure_reason": "unknown_crash_before_results",
                "steps": 0,
                "friction_events": 0,
                "total_tokens": 0,
                "history": []
            }
        # 3. Log Results — ALWAYS, even for crashes
        console.print("\n[bold blue]=== Phase 3: Logging & Metrics ===[/bold blue]")
        logger = RunLogger()
        all_persona_names = [p.name for p in analysis.target_personas]
        logger.log_run(
            persona_name=target_persona.name,
            product_name=product_name,
            target_action=pm_hva,
            run_results=run_results,
            generated_personas=all_persona_names,
            inferred_hva=analysis.inferred_high_value_action,
            pm_hypothesis_alignment=analysis.pm_hypothesis_alignment
        )
    
    # 4. Print Current Metrics
    metrics = EvalMetrics().get_metrics()
    console.print("\n[bold]Current Global Metrics:[/bold]")
    console.print(f"Total Runs: {metrics['total_runs']}")
    console.print(f"Completion Rate: {metrics['completion_rate']:.0%}")
    console.print(f"Avg Friction Events (Human Interventions): {metrics['avg_friction_events']:.1f}")

    # 5. Keep browser open for inspection if NOT headless
    if not headless:
        console.print("\n[bold yellow]Audit complete. Keeping browser open for inspection...[/bold yellow]")
        console.print("[yellow]Press Ctrl+C again to close the browser and exit.[/yellow]")
        try:
            while True:
                await asyncio.sleep(3600) # Wait for an hour (or until Ctrl+C)
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
    

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Best Foot Forward - Autonomous UX Auditor")
    parser.add_argument("--url", required=True, help="Target product URL")
    parser.add_argument("--name", required=False, default=None, help="Target product name (auto-detected from URL if omitted)")
    parser.add_argument("--hva", required=True, help="The PM's hypothesis for the First High-Value Action")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    
    args = parser.parse_args()
    
    asyncio.run(run_agent(args.url, args.name, args.hva, headless=args.headless))

if __name__ == "__main__":
    main()
