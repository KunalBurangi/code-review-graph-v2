from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .parser import LANGUAGE_EXTENSIONS


@dataclass(slots=True)
class RepoReference:
    name: str
    path: Path
    kind: str = "unknown"
    tags: list[str] = field(default_factory=list)
    workspace: str | None = None


class MultiRepoFederation:
    def __init__(self, data_dir: Path | None = None, auto_scan_paths: list[str] | None = None):
        import os
        env_dir = os.environ.get("CRG_V2_DATA_DIR")
        self.data_dir = data_dir or (Path(env_dir) if env_dir else Path.home() / ".code-review-graph-v2")
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self._repos: dict[str, RepoReference] = {}
        self._external_graphs: dict[str, dict] = {}
        self._auto_scan_paths = auto_scan_paths or self._load_auto_scan_paths()
        self._load_registry()
        self._auto_discover_external_graphs()

    def _load_auto_scan_paths(self) -> list[str]:
        config_path = self.data_dir / "config.json"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    data = json.load(f)
                    return data.get("auto_scan_paths", [])
            except Exception:
                pass
        return []

    def _save_auto_scan_paths(self) -> None:
        config_path = self.data_dir / "config.json"
        data = {"auto_scan_paths": self._auto_scan_paths}
        with open(config_path, "w") as f:
            json.dump(data, f)

    def add_auto_scan_path(self, path: str) -> None:
        if path not in self._auto_scan_paths:
            self._auto_scan_paths.append(path)
            self._save_auto_scan_paths()
            self._auto_discover_external_graphs()

    def _auto_discover_external_graphs(self) -> None:
        for scan_path in self._auto_scan_paths:
            base = Path(scan_path).expanduser()
            if not base.exists():
                continue
            
            for repo_path in base.iterdir():
                if not repo_path.is_dir():
                    continue
                
                for graph_dir_name in [".code-review-graph-v2", ".code-review-graph"]:
                    graph_dir = repo_path / graph_dir_name
                    graph_file = graph_dir / "graph.json"
                    
                    if graph_file.exists():
                        try:
                            with open(graph_file) as f:
                                data = json.load(f)
                                self._external_graphs[repo_path.name] = {
                                    "path": str(repo_path),
                                    "graph": data,
                                }
                        except Exception:
                            pass

    def search_all_graphs(self, query: str, limit: int = 20) -> list[dict]:
        results = []
        query_lower = query.lower()

        # Search ALL external graphs, not just one hardcoded name
        for repo_name, repo_data in self._external_graphs.items():
            for node in repo_data.get("graph", {}).get("nodes", []):
                node_name = node.get("name", "").lower()
                node_file = node.get("file_path", "").lower()
                if query_lower in node_name or query_lower in node_file:
                    results.append({
                        "source": repo_name,
                        "id": node.get("id"),
                        "name": node.get("name"),
                        "type": node.get("node_type"),
                        "file": node.get("file_path"),
                    })

        return results[:limit]

    def get_external_schema(self, endpoint_name: str) -> dict | None:
        backend = self._external_graphs.get("backend", {})
        if not backend:
            return None
        
        nodes = backend.get("graph", {}).get("nodes", [])
        for node in nodes:
            if endpoint_name.lower() in node.get("name", "").lower():
                return {
                    "name": node.get("name"),
                    "type": node.get("node_type"),
                    "file": node.get("file_path"),
                    "line": node.get("start_line"),
                }
        
        return None

    def _load_registry(self) -> None:
        registry_path = self.data_dir / "repo_registry.json"
        if registry_path.exists():
            import json
            with open(registry_path) as f:
                data = json.load(f)
                for name, info in data.get("repos", {}).items():
                    self._repos[name] = RepoReference(
                        name=name,
                        path=Path(info["path"]),
                        kind=info.get("kind", "unknown"),
                        tags=info.get("tags", []),
                        workspace=info.get("workspace"),
                    )

    def _save_registry(self) -> None:
        import json
        registry_path = self.data_dir / "repo_registry.json"
        data = {
            "repos": {
                name: {
                    "path": str(ref.path),
                    "kind": ref.kind,
                    "tags": ref.tags,
                    "workspace": ref.workspace,
                }
                for name, ref in self._repos.items()
            }
        }
        with open(registry_path, "w") as f:
            json.dump(data, f)

    def register_repo(
        self,
        name: str,
        path: Path,
        kind: str = "unknown",
        tags: list[str] | None = None,
    ) -> None:
        self._repos[name] = RepoReference(
            name=name,
            path=path,
            kind=kind,
            tags=tags or [],
            workspace=self._detect_workspace(path),
        )
        self._save_registry()

    def unregister(self, name: str) -> None:
        if name in self._repos:
            del self._repos[name]
            self._save_registry()

    def list_repos(self) -> list[RepoReference]:
        return list(self._repos.values())

    def _detect_workspace(self, path: Path) -> str | None:
        if (path / "package.json").exists():
            try:
                content = (path / "package.json").read_text()
                if '"workspaces"' in content:
                    return "npm"
            except Exception:
                pass
        if (path / "pnpm-workspace.yaml").exists():
            return "pnpm"
        if (path / "lerna.json").exists():
            return "lerna"
        if (path / "go.mod").exists():
            return "go"
        if (path / "Cargo.toml").exists():
            return "rust"
        if any((path / p).exists() for p in ["pnpm-workspace.yaml", "lerna.json"]):
            return "monorepo"
        return None

    def detect_cross_repo_deps(
        self,
        repo_name: str,
    ) -> list[tuple[str, str]]:
        if repo_name not in self._repos:
            return []

        repo = self._repos[repo_name]
        deps: list[tuple[str, str]] = []

        try:
            if repo.workspace in ("npm", "pnpm"):
                pkg_json = repo.path / "package.json"
                if pkg_json.exists():
                    import json
                    data = json.loads(pkg_json.read_text())
                    deps.extend(
                        (d, "npm")
                        for d in data.get("dependencies", {}).keys()
                    )
                    deps.extend(
                        (d, "npm")
                        for d in data.get("devDependencies", {}).keys()
                    )
        except Exception:
            pass

        for other_name, other_repo in self._repos.items():
            if other_name == repo_name:
                continue
            for dep_name, dep_type in deps:
                if dep_name in other_repo.path.name:
                    deps.append((other_name, "local"))

        return deps

    def get_federated_impact(
        self,
        repo_name: str,
        changed_files: list[str],
    ) -> dict[str, list[str]]:
        cross_deps = self.detect_cross_repo_deps(repo_name)
        impact: dict[str, list[str]] = {repo_name: changed_files}

        # Extract identifiers from changed files to search in dependent repos
        changed_names = set()
        for f in changed_files:
            stem = Path(f).stem
            changed_names.add(stem)
            # Also add common derivative names (e.g. UserService -> user_service)
            changed_names.add(stem.lower())

        for dep_repo_name, _ in cross_deps:
            affected_files: list[str] = []
            # Check external graphs for files that reference changed modules
            if dep_repo_name in self._external_graphs:
                ext_data = self._external_graphs[dep_repo_name]
                for node in ext_data.get("graph", {}).get("nodes", []):
                    node_name = node.get("name", "").lower()
                    node_file = node.get("file_path", "")
                    # If an external node imports or references a changed module
                    if any(cn in node_name for cn in changed_names):
                        if node_file not in affected_files:
                            affected_files.append(node_file)
            # Also check registered repo file system for import references
            elif dep_repo_name in self._repos:
                dep_path = self._repos[dep_repo_name].path
                for ext in LANGUAGE_EXTENSIONS:
                    for source_file in dep_path.rglob(f"*{ext}"):
                        try:
                            content = source_file.read_text(encoding="utf-8", errors="ignore")
                            if any(cn in content.lower() for cn in changed_names):
                                affected_files.append(str(source_file))
                        except Exception:
                            continue
            impact[dep_repo_name] = affected_files

        return impact