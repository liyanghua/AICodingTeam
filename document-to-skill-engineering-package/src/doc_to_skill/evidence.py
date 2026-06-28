from __future__ import annotations

import json
from pathlib import Path
from .schemas import EvidencePack


class EvidenceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, evidence: EvidencePack) -> Path:
        path = self.root / f"{evidence.evidence_id}.json"
        path.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, evidence_id: str) -> EvidencePack:
        path = self.root / f"{evidence_id}.json"
        return EvidencePack(**json.loads(path.read_text(encoding="utf-8")))
