import json
import os


class EvalMetrics:
    """Computes baseline metrics across all runs in the JSONL log."""

    def __init__(self, log_file: str = "data/runs/runs.jsonl"):
        self.log_file = log_file

    def get_metrics(self) -> dict[str, float]:
        if not os.path.exists(self.log_file):
            return {"total_runs": 0, "completion_rate": 0.0, "avg_friction_events": 0.0, "avg_steps": 0.0}

        runs = []
        with open(self.log_file) as f:
            for line in f:
                if line.strip():
                    runs.append(json.loads(line))

        total_runs = len(runs)
        if total_runs == 0:
            return {"total_runs": 0, "completion_rate": 0.0, "avg_friction_events": 0.0, "avg_steps": 0.0}

        successful_runs = sum(1 for r in runs if r["status"] == "success")
        total_friction = sum(r["friction_events"] for r in runs)
        total_steps = sum(r["steps"] for r in runs)

        return {
            "total_runs": total_runs,
            "completion_rate": successful_runs / total_runs,
            "avg_friction_events": total_friction / total_runs,
            "avg_steps": total_steps / total_runs,
        }
