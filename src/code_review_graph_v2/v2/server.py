from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from .federation import MultiRepoFederation
from .impact import GraphV2, ImpactPredictor
from .models import CodeEdge, CodeNode
from .parser import detect_flows_v2, parse_file_v2
from .search import LearnedSearcher
from .visualization import Visualizer

logger = logging.getLogger(__name__)


mcp = FastMCP(
    "code-review-graph-v2",
    instructions=(
        "Intelligent code review context with structural graph analysis. "
        "Builds a dependency graph of your codebase (functions, classes, imports, "
        "and call edges) and predicts which files are impacted by changes using "
        "git history, graph depth, and learned scoring. Supports multi-repo "
        "federation for cross-project impact analysis."
    ),
)


class CodeReviewGraphV2:
    def __init__(self, data_dir: Path | None = None):
        import os
        env_dir = os.environ.get("CRG_V2_DATA_DIR")
        self.data_dir = data_dir or (Path(env_dir) if env_dir else Path.home() / ".code-review-graph-v2")
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.graph = GraphV2(self.data_dir)
        self.predictor = ImpactPredictor(self.data_dir)
        self.searcher = LearnedSearcher(self.data_dir)
        self.federation = MultiRepoFederation(self.data_dir)
        self.visualizer = Visualizer(self.data_dir)

    def build_from_path(self, root: Path) -> dict[str, Any]:
        from .parser import LANGUAGE_EXTENSIONS

        stats = {
            "files_parsed": 0,
            "files_skipped": 0,
            "nodes_created": 0,
            "edges_created": 0,
            "call_edges": 0,
            "import_edges": 0,
            "flows_detected": 0,
            "git_files_with_history": 0,
        }

        for ext in LANGUAGE_EXTENSIONS:
            for file_path in root.rglob(f"*{ext}"):
                if self._should_skip(file_path):
                    continue
                try:
                    # ── Incremental: skip unchanged files ──
                    content = file_path.read_text(encoding="utf-8")
                    file_hash = CodeNode.compute_hash(content)
                    fp_str = str(file_path)

                    if not self.graph.file_changed(fp_str, file_hash):
                        stats["files_skipped"] += 1
                        continue

                    # Remove old nodes for this file before re-parsing
                    self.graph.remove_file_nodes(fp_str)

                    nodes, edges = parse_file_v2(file_path, content)
                    for node in nodes:
                        self.graph.add_node(node)
                    for edge in edges:
                        self.graph.add_edge(edge)

                    stats["files_parsed"] += 1
                    stats["nodes_created"] += len(nodes)
                    stats["edges_created"] += len(edges)
                    stats["call_edges"] += sum(1 for e in edges if e.edge_type == "calls")
                    stats["import_edges"] += sum(1 for e in edges if e.edge_type == "imports")

                    flows = detect_flows_v2(file_path, content)
                    stats["flows_detected"] += len(flows)
                except Exception as exc:
                    logger.debug("Failed to parse %s: %s", file_path, exc)

        # ── Load git history ──
        git_stats = self.graph.load_git_history(root)
        stats["git_files_with_history"] = len(git_stats)

        self._save_graph()
        return stats

    def _should_skip(self, path: Path) -> bool:
        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
        return any(part in skip_dirs for part in path.parts)

    def _save_graph(self) -> None:
        graph_file = self.data_dir / "graph.json"
        data = {
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "node_type": n.node_type,
                    "file_path": n.file_path,
                    "start_line": n.start_line,
                    "end_line": n.end_line,
                    "code_hash": n.code_hash,
                }
                for n in self.graph.nodes.values()
            ],
            "edges": [
                {
                    "source": e.source_id,
                    "target": e.target_id,
                    "type": e.edge_type,
                    "call_site": e.call_site,
                }
                for e in self.graph.edges
            ],
            "change_history": dict(self.graph.change_history),
        }
        with open(graph_file, "w") as f:
            json.dump(data, f)

    def get_review_context(self, changed_files: list[str]) -> dict[str, Any]:
        impact_radius = self.graph.get_impact_radius(changed_files, self.predictor)

        all_nodes = {n.id: n for n in self.graph.nodes.values()}
        search_results = self.searcher.search(
            query=" ".join(Path(f).stem for f in changed_files),
            nodes=all_nodes,
            graph=self.graph,
            context_nodes=[n.id for n in self.graph.nodes.values() if n.file_path in changed_files],
            limit=20,
        )

        return {
            "changed_files": changed_files,
            "impact_predictions": [
                {"file": p.file_path, "score": p.score, "reasons": p.reasons}
                for p in impact_radius
            ],
            "related_nodes": [
                {"id": r.node_id, "name": r.name, "file": r.file_path, "score": r.score, "type": r.match_type}
                for r in search_results
            ],
            "stats": {
                "total_nodes": len(self.graph.nodes),
                "total_edges": len(self.graph.edges),
                "impacted_count": len(impact_radius),
            },
        }


_graph_cache: dict[str, CodeReviewGraphV2] = {}
_current_data_dir: Path | None = None


def get_graph(data_dir: Path | None = None) -> CodeReviewGraphV2:
    """Get or create a graph instance for the given data directory.

    Uses a per-project cache so each project keeps its own graph.
    Falls back to the most recently built project, or ``~/.code-review-graph-v2``.
    """
    global _current_data_dir

    if data_dir is None:
        import os
        env_dir = os.environ.get("CRG_V2_DATA_DIR")
        data_dir = _current_data_dir or (Path(env_dir) if env_dir else Path.home() / ".code-review-graph-v2")

    key = str(data_dir.resolve())
    if key not in _graph_cache:
        _graph_cache[key] = CodeReviewGraphV2(data_dir)
    return _graph_cache[key]


# ---------------------------------------------------------------------------
# MCP Tools — with improved descriptions for AI discoverability
# ---------------------------------------------------------------------------


@mcp.tool()
def build_graph(root_path: str | None = None) -> dict[str, Any]:
    """Build or rebuild the code review graph.

    Parses all supported source files under ``root_path``, detecting functions,
    classes, imports, and function calls.  Uses **incremental builds**: files
    whose content hash has not changed since the last build are skipped.  Also
    loads **git history** (last 90 days) to populate change-frequency data.

    Returns parse statistics including files parsed, nodes/edges created,
    and how many files were skipped as unchanged.
    """
    global _current_data_dir

    root = Path(root_path) if root_path else Path.cwd()
    data_dir = root / ".code-review-graph-v2"
    _current_data_dir = data_dir
    graph = get_graph(data_dir)
    return graph.build_from_path(root)


@mcp.tool()
def get_impact_radius(changed_files: list[str]) -> dict[str, Any]:
    """Get predicted impact radius for changed files using ML scoring.

    Analyzes the dependency graph to find all functions and classes that could
    be affected by modifications to ``changed_files``.  Scoring uses call-graph
    depth, import fan-out, git change frequency, and test coverage signals.

    Use this **before** reading impacted files to narrow your review scope.
    Most useful for projects with 50+ files where manual exploration is slow.
    """
    graph = get_graph()
    return {
        "predictions": graph.get_review_context(changed_files)["impact_predictions"],
    }


@mcp.tool()
def search_code(query: str, limit: int = 10) -> dict[str, Any]:
    """Search code across all registered repos + auto-discovered external graphs.

    Uses BM25 text scoring combined with graph-proximity boosting: results that
    are close to recently-changed nodes in the dependency graph rank higher.
    Searches both the local graph and any external graphs imported via
    ``import_external_graph`` or auto-discovered via ``auto_detect_related_repos``.

    Returns results ranked by relevance, each tagged with its source
    (``local`` or external repo name).
    """
    graph = get_graph()
    
    local_nodes = {n.id: n for n in graph.graph.nodes.values()}
    local_results = graph.searcher.search(query, local_nodes, graph.graph, limit=limit)
    
    external_results = graph.federation.search_all_graphs(query, limit=limit)
    
    combined = [
        *[
            {"source": "local", "id": r.node_id, "name": r.name, "file": r.file_path, "score": r.score, "type": r.match_type}
            for r in local_results
        ],
        *[
            {"source": e["source"], "id": e["id"], "name": e["name"], "file": e["file"], "score": 0.8, "type": "external"}
            for e in external_results
        ]
    ]
    
    return {
        "results": combined[:limit],
        "sources": {
            "local": len(local_results),
            "external": len(external_results),
            "external_repos": list(graph.federation._external_graphs.keys()),
        }
    }


@mcp.tool()
def record_search_feedback(query: str, node_id: str, useful: bool) -> dict[str, str]:
    """Record user feedback to improve search ranking.

    When a search result is useful (or not), recording feedback adjusts future
    ranking weights so that similar queries return better results over time.
    """
    graph = get_graph()
    graph.searcher.record_click(query, node_id)
    return {"status": "recorded"}


@mcp.tool()
def register_repository(name: str, path: str, kind: str = "unknown", tags: list[str] | None = None) -> dict[str, str]:
    """Register a repository in the multi-repo federation.

    Once registered, the repository's graph can be searched via ``search_code``
    and its impact analyzed via ``get_cross_repo_impact``.  Use ``kind`` to tag
    the repo type (e.g., ``backend``, ``frontend``, ``shared-lib``).
    """
    graph = get_graph()
    graph.federation.register_repo(name, Path(path), kind, tags)
    return {"status": "registered", "name": name}


@mcp.tool()
def configure_auto_scan(scan_paths: list[str]) -> dict[str, Any]:
    """Configure paths to auto-scan for external graphs (e.g., ['~/projects', '/work']).

    The MCP server will look for ``.code-review-graph-v2/graph.json`` inside
    each subdirectory of the given paths and automatically make them available
    for cross-repo search and impact analysis.
    """
    graph = get_graph()
    for path in scan_paths:
        graph.federation.add_auto_scan_path(path)
    
    return {
        "status": "configured",
        "scan_paths": graph.federation._auto_scan_paths,
        "discovered_repos": list(graph.federation._external_graphs.keys()),
    }


@mcp.tool()
def auto_detect_related_repos(base_path: str) -> dict[str, Any]:
    """Auto-detect and link related repositories in a base directory.

    Scans ``base_path`` for sibling project directories that already have a
    built code graph.  Detected repos are automatically linked for cross-repo
    search and impact queries.
    """
    graph = get_graph()
    base = Path(base_path).expanduser()
    
    if not base.exists():
        return {"status": "error", "message": f"Path not found: {base}"}
    
    detected = []
    for repo_path in base.iterdir():
        if not repo_path.is_dir() or repo_path.name.startswith("."):
            continue
        
        for graph_dir_name in [".code-review-graph-v2", ".code-review-graph"]:
            graph_dir = repo_path / graph_dir_name
            if (graph_dir / "graph.json").exists():
                detected.append({
                    "name": repo_path.name,
                    "path": str(repo_path),
                    "graph_dir": graph_dir_name,
                })
                graph.federation.add_auto_scan_path(base_path)
                break
    
    return {
        "status": "detected",
        "repos": detected,
        "auto_scan_paths": graph.federation._auto_scan_paths,
    }


@mcp.tool()
def list_repositories() -> dict[str, Any]:
    """List all registered repositories.

    Returns metadata for each repo in the federation including name, path,
    kind, tags, and workspace.
    """
    graph = get_graph()
    repos = graph.federation.list_repos()
    return {
        "repos": [
            {"name": r.name, "path": str(r.path), "kind": r.kind, "tags": r.tags, "workspace": r.workspace}
            for r in repos
        ]
    }


@mcp.tool()
def get_cross_repo_impact(repo_name: str, changed_files: list[str]) -> dict[str, Any]:
    """Get impact across repository boundaries.

    Analyzes how changes in ``repo_name`` affect other registered repositories.
    Traces exported symbols (modules, functions) from ``changed_files`` and
    checks if any other repo imports or references them.

    Critical for monorepo and multi-service architectures where a shared-lib
    change can break downstream consumers.
    """
    graph = get_graph()
    impact = graph.federation.get_federated_impact(repo_name, changed_files)
    cross_deps = graph.federation.detect_cross_repo_deps(repo_name)
    return {"impact": impact, "cross_deps": cross_deps}


@mcp.tool()
def import_external_graph(
    source_path: str,
    name: str | None = None,
) -> dict[str, Any]:
    """Import graph from another repository into local federation.

    Copies the ``graph.json`` from ``source_path`` into the local data
    directory so it can be searched alongside the current project's graph.
    Use this to link a related project without registering it as a full repo.
    """
    graph = get_graph()
    source = Path(source_path)
    
    if not source.exists():
        return {"status": "error", "message": f"Path not found: {source}"}
    
    source_graph_dir = source / ".code-review-graph-v2"
    if not source_graph_dir.exists():
        source_graph_dir = source / ".code-review-graph"
    
    if not source_graph_dir.exists():
        return {"status": "error", "message": "No graph data found in source path"}
    
    target_dir = graph.data_dir / "external"
    target_dir.mkdir(exist_ok=True, parents=True)
    
    import_name = name or source.name
    target_path = target_dir / f"{import_name}.json"
    
    source_graph_file = source_graph_dir / "graph.json"
    if source_graph_file.exists():
        shutil.copy(source_graph_file, target_path)
        
        return {
            "status": "imported",
            "name": import_name,
            "source": str(source),
            "local_path": str(target_path),
            "message": f"Graph '{import_name}' imported. Use search_code to query it.",
        }
    
    return {"status": "error", "message": "No graph.json found in source"}


@mcp.tool()
def get_review_context(changed_files: list[str]) -> dict[str, Any]:
    """Get token-optimized review context with impact predictions.

    Returns a combined view of:
    - **impact_predictions**: files likely affected by your changes, ranked
    - **related_nodes**: functions/classes semantically related to changed files
    - **stats**: total graph size and impacted count

    Use this as your **first call** when reviewing a PR or planning a change.
    It gives you the review scope without reading every file manually.
    """
    graph = get_graph()
    return graph.get_review_context(changed_files)


@mcp.tool()
def generate_visualization(
    changed_files: list[str] | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate interactive HTML visualization of the code graph.

    Creates a force-directed graph visualization showing nodes (functions,
    classes), edges (imports, calls), and highlights impacted files if
    ``changed_files`` is provided.  Opens in any browser.
    """
    graph = get_graph()
    
    from .models import FlowEntry
    from .parser import detect_flows_v2
    import os
    
    all_flows: list[FlowEntry] = []
    for node in graph.graph.nodes.values():
        try:
            flows = detect_flows_v2(Path(node.file_path))
            all_flows.extend(flows)
        except Exception:
            pass
    
    impact = graph.get_review_context(changed_files or [])
    predictions = [
        graph.predictor.predict(nid, graph.graph)
        for nid in graph.graph.nodes
        if any(n.file_path == cf for cf in (changed_files or []))
        for n in [graph.graph.nodes[nid]]
    ]
    
    from .models import ImpactPrediction
    pred_objects = []
    for p in impact.get("impact_predictions", []):
        pred_objects.append(ImpactPrediction(
            file_path=p["file"],
            score=p["score"],
            reasons=p["reasons"],
            is_likely_impacted=p.get("is_likely_impacted", p["score"] > 0.4),
        ))
    
    output = Path(output_path) if output_path else graph.data_dir / "visualization.html"
    graph.visualizer.export_html(
        graph.graph,
        all_flows[:20],
        pred_objects,
        output,
    )
    
    return {
        "status": "generated",
        "output_path": str(output),
        "stats": {
            "nodes": len(graph.graph.nodes),
            "edges": len(graph.graph.edges),
            "flows": len(all_flows),
            "impacted": len(pred_objects),
        },
    }


def cli() -> None:
    mcp.run()


if __name__ == "__main__":
    cli()