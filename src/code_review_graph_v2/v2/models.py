from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class CodeNode:
    id: str
    name: str
    node_type: str
    file_path: str
    start_line: int
    end_line: int
    parent_id: str | None = None
    code_hash: str | None = None

    @classmethod
    def compute_hash(cls, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass(slots=True)
class CodeEdge:
    source_id: str
    target_id: str
    edge_type: str
    call_site: str | None = None


@dataclass(slots=True)
class ChangeEvent:
    file_path: str
    change_type: str
    timestamp: float
    node_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImpactPrediction:
    file_path: str
    score: float
    reasons: list[str]
    is_likely_impacted: bool


class Parser(Protocol):
    def parse_file(self, path: Path) -> tuple[list[CodeNode], list[CodeEdge]]:
        ...


@dataclass(slots=True)
class FlowEntry:
    id: str
    name: str
    entry_type: str
    file_path: str
    line: int
    framework: str | None = None
    criticality: float = 0.5


@dataclass(slots=True)
class SearchResult:
    node_id: str
    name: str
    file_path: str
    score: float
    match_type: str