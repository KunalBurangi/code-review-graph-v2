from __future__ import annotations

import json
import logging
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

from .models import ImpactPrediction


@dataclass(slots=True)
class ImpactFeatures:
    call_count: int = 0
    test_count: int = 0
    change_frequency: float = 0.0
    recent_changes: int = 0
    has_tests: bool = False
    graph_depth: int = 0
    import_count: int = 0
    export_count: int = 0


class ImpactPredictor:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or Path(".code-review-graph-v2")
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.model_path = self.data_dir / "impact_model.json"
        self.feedback_path = self.data_dir / "feedback.json"
        self._load_model()

    def _load_model(self) -> None:
        if self.model_path.exists():
            with open(self.model_path) as f:
                data = json.load(f)
                self._weights = data.get("weights", DEFAULT_WEIGHTS)
                self._feedback = data.get("feedback", {})
        else:
            self._weights = DEFAULT_WEIGHTS.copy()
            self._feedback = {}

    def _save_model(self) -> None:
        with open(self.model_path, "w") as f:
            json.dump({
                "weights": self._weights,
                "feedback": self._feedback,
            }, f)

    def compute_features(
        self,
        node_id: str,
        graph: "GraphV2",
    ) -> ImpactFeatures:
        features = ImpactFeatures()

        node = graph.get_node(node_id)
        if not node:
            return features

        in_edges = graph.get_incoming_edges(node_id)
        out_edges = graph.get_outgoing_edges(node_id)

        features.call_count = len(out_edges)
        features.import_count = len([e for e in in_edges if e.edge_type == "imports"])
        features.export_count = len([e for e in out_edges if e.edge_type == "imports"])
        features.graph_depth = self._compute_depth(graph, node_id)

        changes = graph.get_change_history(node.file_path)
        features.recent_changes = len(changes)
        features.change_frequency = self._calculate_frequency(changes)

        features.has_tests = self._has_test_file(graph, node.file_path)

        return features

    def _compute_depth(self, graph: "GraphV2", node_id: str) -> int:
        visited: set[str] = set()
        max_depth = 0

        def dfs(nid: str, depth: int) -> None:
            nonlocal max_depth
            if nid in visited or depth > 10:
                return
            visited.add(nid)
            max_depth = max(max_depth, depth)
            for edge in graph.get_outgoing_edges(nid):
                dfs(edge.target_id, depth + 1)

        dfs(node_id, 0)
        return max_depth

    def _calculate_frequency(self, changes: list) -> float:
        if not changes:
            return 0.0
        return len(changes) / 30.0

    def _has_test_file(self, graph: "GraphV2", file_path: str) -> bool:
        file_stem = Path(file_path).stem
        file_dir = str(Path(file_path).parent)
        # Generate expected test filenames for this source file
        test_names = [
            f"test_{file_stem}",
            f"{file_stem}_test",
            f"{file_stem}.test",
            f"{file_stem}.spec",
        ]
        # Check if any node in the graph matches a test file pattern
        for node in graph.nodes.values():
            node_stem = Path(node.file_path).stem
            if node_stem in test_names:
                return True
        return False

    def predict(self, node_id: str, graph: "GraphV2") -> ImpactPrediction:
        features = self.compute_features(node_id, graph)

        score = 0.0
        reasons = []

        if features.call_count > 5:
            score += self._weights["high_call_count"] * features.call_count
            reasons.append(f"High call count ({features.call_count})")

        if features.export_count > 3:
            score += self._weights["high_exports"] * features.export_count
            reasons.append(f"Exported by {features.export_count} consumers")

        if features.change_frequency > 0.5:
            score += self._weights["high_volatility"] * features.change_frequency
            reasons.append("Frequently changed")

        if features.has_tests:
            score += self._weights["has_tests"]
            reasons.append("Has test coverage")

        if features.graph_depth < 3:
            score += self._weights["shallow_depth"]
            reasons.append("Core/low-level component")

        if node_id in self._feedback:
            score += self._feedback[node_id]
            reasons.append("User confirmed important")

        score = max(0.0, min(1.0, score / 10.0))

        return ImpactPrediction(
            file_path=graph.get_node(node_id).file_path if graph.get_node(node_id) else "",
            score=score,
            reasons=reasons,
            is_likely_impacted=score > 0.4,
        )

    def record_feedback(self, node_id: str, useful: bool) -> None:
        delta = 0.2 if useful else -0.1
        self._feedback[node_id] = self._feedback.get(node_id, 0.0) + delta
        self._save_model()


DEFAULT_WEIGHTS = {
    "high_call_count": 0.15,
    "high_exports": 0.12,
    "high_volatility": 0.1,
    "has_tests": 0.08,
    "shallow_depth": 0.1,
}


class GraphV2:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or Path(".code-review-graph-v2")
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.nodes: dict[str, "CodeNode"] = {}
        self.edges: list["CodeEdge"] = []
        self.change_history: dict[str, list] = defaultdict(list)
        self._edges_by_source: dict[str, list["CodeEdge"]] = defaultdict(list)
        self._edges_by_target: dict[str, list["CodeEdge"]] = defaultdict(list)
        self._node_hashes: dict[str, str] = {}  # file_path → code_hash
        self._load_graph()

    def _load_graph(self) -> None:
        """Load previously saved graph data from disk."""
        graph_file = self.data_dir / "graph.json"
        if not graph_file.exists():
            return
        try:
            with open(graph_file) as f:
                data = json.load(f)
            from .models import CodeNode, CodeEdge
            for n in data.get("nodes", []):
                node = CodeNode(
                    id=n["id"],
                    name=n["name"],
                    node_type=n["node_type"],
                    file_path=n["file_path"],
                    start_line=n.get("start_line", 0),
                    end_line=n.get("end_line", 0),
                    code_hash=n.get("code_hash"),
                )
                self.nodes[node.id] = node
            for e in data.get("edges", []):
                edge = CodeEdge(
                    source_id=e["source"],
                    target_id=e["target"],
                    edge_type=e["type"],
                    call_site=e.get("call_site"),
                )
                self.edges.append(edge)
                self._edges_by_source[edge.source_id].append(edge)
                self._edges_by_target[edge.target_id].append(edge)

            # Restore change history
            for fp, events in data.get("change_history", {}).items():
                self.change_history[fp] = events

            # Rebuild hash index for incremental builds
            for node in self.nodes.values():
                if node.code_hash:
                    self._node_hashes[node.file_path] = node.code_hash

        except Exception as exc:
            logger.warning("Failed to load graph: %s", exc)

    # ── Git history integration ──────────────────────────────────────────

    def load_git_history(self, root: Path, days: int = 90) -> dict[str, int]:
        """Populate change_history from real ``git log`` data.

        Returns a dict of file_path → number of commits in the given window.
        """
        stats: dict[str, int] = {}
        try:
            result = subprocess.run(
                [
                    "git", "log",
                    f"--since={days} days ago",
                    "--format=%H %at",
                    "--name-only",
                ],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.debug("git log failed: %s", result.stderr.strip())
                return stats

            current_commit: str | None = None
            current_ts: float = 0.0

            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(" ", 2)
                if len(parts) == 2 and len(parts[0]) == 40:
                    # This is a "<commit_hash> <unix_timestamp>" line
                    current_commit = parts[0]
                    try:
                        current_ts = float(parts[1])
                    except ValueError:
                        current_ts = 0.0
                else:
                    # This is a file path
                    file_path = str(root / line)
                    self.change_history[file_path].append({
                        "commit": current_commit,
                        "timestamp": current_ts,
                    })
                    stats[file_path] = stats.get(file_path, 0) + 1

        except FileNotFoundError:
            logger.debug("git not found on PATH — skipping history")
        except subprocess.TimeoutExpired:
            logger.debug("git log timed out")
        except Exception as exc:
            logger.debug("Failed to load git history: %s", exc)

        return stats

    # ── File hash check for incremental builds ───────────────────────────

    def file_changed(self, file_path: str, new_hash: str) -> bool:
        """Return True if the file's content hash differs from the stored one."""
        old_hash = self._node_hashes.get(file_path)
        return old_hash != new_hash

    def remove_file_nodes(self, file_path: str) -> None:
        """Remove all nodes and edges related to a file (for incremental rebuild)."""
        ids_to_remove = {
            nid for nid, n in self.nodes.items() if n.file_path == file_path
        }
        for nid in ids_to_remove:
            del self.nodes[nid]
            self._edges_by_source.pop(nid, None)
            self._edges_by_target.pop(nid, None)

        self.edges = [
            e for e in self.edges
            if e.source_id not in ids_to_remove
            and e.target_id not in ids_to_remove
        ]
        self._node_hashes.pop(file_path, None)

    # ── Core graph operations ────────────────────────────────────────────

    def add_node(self, node: "CodeNode") -> None:
        self.nodes[node.id] = node
        if node.code_hash:
            self._node_hashes[node.file_path] = node.code_hash

    def add_edge(self, edge: "CodeEdge") -> None:
        self.edges.append(edge)
        self._edges_by_source[edge.source_id].append(edge)
        self._edges_by_target[edge.target_id].append(edge)

    def get_node(self, node_id: str) -> "CodeNode | None":
        return self.nodes.get(node_id)

    def get_outgoing_edges(self, node_id: str) -> list["CodeEdge"]:
        return self._edges_by_source.get(node_id, [])

    def get_incoming_edges(self, node_id: str) -> list["CodeEdge"]:
        return self._edges_by_target.get(node_id, [])

    def record_change(self, file_path: str, change: dict) -> None:
        self.change_history[file_path].append(change)

    def get_change_history(self, file_path: str) -> list[dict]:
        return self.change_history.get(file_path, [])

    def get_impact_radius(
        self,
        changed_files: list[str],
        predictor: ImpactPredictor,
    ) -> list[ImpactPrediction]:
        affected: list[ImpactPrediction] = []
        visited: set[str] = set()

        for file_path in changed_files:
            for node_id, node in self.nodes.items():
                if node.file_path == file_path and node_id not in visited:
                    visited.add(node_id)
                    pred = predictor.predict(node_id, self)
                    if pred.is_likely_impacted:
                        affected.append(pred)

        return sorted(affected, key=lambda x: -x.score)