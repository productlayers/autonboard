"""
L1 atoms — atomic agent-behavior observations.

Each atom captures one durable observation about how the agent navigated UI, 
handled friction, or escaped loops, generalized enough to apply to future runs 
across all products. This is the agent's global functional memory.

Backing store: JSONL at data/memory/atoms.jsonl.

Public API:
    write_atoms(atoms)                                     # append
    load_atoms()                                           # full scan
    find_atoms(funnel_stage=, atom_type=)                  # filtered scan
    new_atom_id()                                          # short uuid
    now_iso()                                              # utc timestamp
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ATOMS_PATH = Path("data/memory/atoms.jsonl")


# ── Schema ───────────────────────────────────────────────────────────────────

AtomType = Literal[
    "ui_navigation_tactic",  # e.g. how to handle dropdowns
    "friction_resolution",   # e.g. how the agent recovered from an error
    "anti_loop_tactic",      # e.g. what to do when clicking fails repeatedly
]


class AppliesTo(BaseModel):
    """Retrieval filters. Empty list = no filter on that dimension."""
    funnel_stage: list[str] = Field(default_factory=list)
    product_category: list[str] = Field(default_factory=list)


class ResultRef(BaseModel):
    """Drill-down pointer back to the L0 trace step that produced this atom."""
    run_id: str
    step: int
    screenshot_path: str | None = None


class Atom(BaseModel):
    id: str
    atom_type: AtomType
    funnel_stage: str
    observation: str = Field(
        description="One sentence in plain text: what the agent learned tactically at this stage, generalized to apply to future similar moments."
    )
    result_ref: ResultRef
    applies_to: AppliesTo
    confidence: Literal["provisional", "confirmed"] = "provisional"
    created_at: str
    last_used_at: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def new_atom_id() -> str:
    """Short, sortable-ish id with an 'atm_' prefix for easy grepping in logs."""
    return f"atm_{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ── I/O ──────────────────────────────────────────────────────────────────────


def write_atoms(atoms: list[Atom], path: Path = ATOMS_PATH) -> int:
    """Append atoms to the JSONL store. Returns the number written."""
    if not atoms:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for atom in atoms:
            f.write(atom.model_dump_json() + "\n")
    return len(atoms)


def load_atoms(path: Path = ATOMS_PATH) -> list[Atom]:
    """Load all atoms from the JSONL store. Returns empty list if no file yet."""
    if not path.exists():
        return []
    out: list[Atom] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(Atom(**json.loads(line)))
    return out


def find_atoms(
    funnel_stage: str | None = None,
    atom_type: AtomType | None = None,
    limit: int | None = None,
    most_recent_first: bool = True,
    path: Path = ATOMS_PATH,
) -> list[Atom]:
    """
    Simple linear-scan retrieval.
    Ordering: by created_at, most recent first by default.
    """
    atoms = load_atoms(path)
    if funnel_stage is not None:
        atoms = [a for a in atoms if a.funnel_stage == funnel_stage]
    if atom_type is not None:
        atoms = [a for a in atoms if a.atom_type == atom_type]
    if most_recent_first:
        atoms.sort(key=lambda a: a.created_at, reverse=True)
    if limit is not None:
        atoms = atoms[:limit]
    return atoms
