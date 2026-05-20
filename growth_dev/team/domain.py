from __future__ import annotations

from pathlib import Path

from .models import DomainSpec, TeamSpec
from .yaml_io import load_yaml_subset


def load_team_spec(path: Path) -> TeamSpec:
    payload = load_yaml_subset(path)
    return TeamSpec.from_dict(payload)


def load_domain_spec(domain_id: str, domains_dir: Path = Path("domains")) -> DomainSpec:
    domain_path = domains_dir / domain_id / "domain.yaml"
    if not domain_path.exists():
        raise FileNotFoundError(f"Domain pack not found: {domain_path}")
    payload = load_yaml_subset(domain_path)
    domain = DomainSpec.from_dict(payload)
    if domain.domain_id != domain_id:
        raise ValueError(f"Domain id mismatch: expected {domain_id}, got {domain.domain_id}")
    return domain
