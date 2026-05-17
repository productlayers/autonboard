import base64
import json
import os
from datetime import datetime
from typing import Any


class RunLogger:
    """Logs agent runs to an append-only JSONL file."""

    def __init__(self, log_dir: str = "data/runs"):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.screenshots_dir = os.path.join(self.log_dir, "screenshots")
        os.makedirs(self.screenshots_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, "runs.jsonl")
    def log_run(
        self,
        persona_name: str,
        product_name: str,
        target_action: str,
        run_results: dict[str, Any],
        generated_personas: list | None = None,
        inferred_hva: str | None = None,
        pm_hypothesis_alignment: str | None = None,
        persona_archetype_id: str | None = None,
    ) -> str:
        """Appends the run summary to the JSONL log. Returns the run_id."""
        now = datetime.now()
        run_id = now.strftime("%Y%m%d_%H%M%S")

        # Save base64 screenshots to disk to keep JSONL lightweight
        # Sanitize product name for safe filenames
        safe_product = product_name.lower().replace(" ", "_").replace("/", "_")

        for i, step_data in enumerate(run_results.get("history", [])):
            if "screenshot_base64" in step_data and step_data["screenshot_base64"]:
                try:
                    img_data = base64.b64decode(step_data["screenshot_base64"])
                    funnel_stage = step_data.get("funnel_stage", "unknown")
                    filename = f"{safe_product}_{run_id}_step{i + 1}_{funnel_stage}.png"
                    filepath = os.path.join(self.screenshots_dir, filename)
                    with open(filepath, "wb") as f:
                        f.write(img_data)
                    step_data["screenshot_path"] = filepath
                except Exception as e:
                    print(f"Failed to save screenshot for step {i + 1}: {e}")
                # Remove the massive base64 string from the JSON
                if "screenshot_base64" in step_data:
                    del step_data["screenshot_base64"]

        record = {
            "run_id": run_id,
            "timestamp": now.isoformat(),
            "product": product_name,
            "persona": persona_name,
            "persona_archetype_id": persona_archetype_id,
            "generated_personas": generated_personas or [],
            "target_action": target_action,
            "llm_inferred_hva": inferred_hva,
            "hva_audit_alignment": pm_hypothesis_alignment,
            "status": run_results["status"],
            "run_success": run_results.get("run_success", False),
            "failure_reason": run_results.get("failure_reason"),
            "steps": run_results["steps"],
            "friction_events": run_results["friction_events"],
            "total_tokens": run_results.get("total_tokens", 0),
            "history": run_results.get("history", []),
        }

        with open(self.log_file, "a") as f:
            f.write(json.dumps(record) + "\n")

        print(f"Run logged successfully to {self.log_file}")
        return run_id
