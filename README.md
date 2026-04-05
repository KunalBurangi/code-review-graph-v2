# Code Review Graph v2

A code intelligence MCP server that builds a structural dependency graph of your codebase. It maps functions, classes, imports, and **function calls** — then uses that graph to predict which files are impacted by changes.

> **Status**: Working prototype. Actively tested. Not yet production-hardened.

## What It Does

| Feature | Description |
|---------|-------------|
| **Build Graph** | Scans your project and maps every function, class, import, and function call |
| **Impact Prediction** | *"If I change file X, what else might break?"* — ranks affected files by risk |
| **Code Search** | BM25 keyword search across your project with graph-proximity boosting |
| **Review Context** | Get a focused review scope for a set of changed files |
| **Git History** | Loads real `git log` data — knows which files change frequently |
| **Call Graph** | Detects `function_a()` → `function_b()` calls, not just imports |
| **Multi-Repo** | Link multiple projects together for cross-repo search and impact analysis |
| **Incremental Builds** | Only re-parses files that actually changed (content hash comparison) |
| **Visualization** | Interactive HTML graph you can open in any browser |

## Supported Languages

Python, JavaScript, TypeScript, Go, Rust, Java, Ruby, PHP, Swift, Kotlin, C#, C, C++, Solidity, Dart, Lua

## Quick Start

### 1. Install

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/code-review-graph-v2.git
cd code-review-graph-v2

# Create virtual environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure as MCP Server

Add to your MCP config (e.g., `~/.gemini/antigravity/mcp_config.json`):

```json
{
  "mcpServers": {
    "code-review-graph-v2": {
      "command": "/path/to/code-review-graph-v2/.venv/bin/python",
      "args": ["-m", "code_review_graph_v2"],
      "env": {}
    }
  }
}
```

### 3. Build Your First Graph

Once the MCP server is running, use the `build_graph` tool:

```
build_graph(root_path="/path/to/your/project")
```

That's it. All tools are now active for that project.

## MCP Tools Reference

### Core Tools

#### `build_graph(root_path)`
Scans all source files under `root_path`. Detects functions, classes, imports, and function calls. Loads git history (last 90 days). **Incremental** — skips unchanged files on subsequent builds.

**Returns:**
```json
{
  "files_parsed": 42,
  "files_skipped": 0,
  "nodes_created": 156,
  "edges_created": 89,
  "call_edges": 34,
  "import_edges": 55,
  "flows_detected": 12,
  "git_files_with_history": 38
}
```

#### `get_impact_radius(changed_files)`
Predicts which files are impacted by changes. Uses call-graph depth, import fan-out, git change frequency, and test coverage as signals.

```
get_impact_radius(changed_files=["src/auth/validator.py", "src/api/routes.py"])
```

#### `get_review_context(changed_files)`
Combined view of impact predictions + related nodes. **Use this as your first call** when reviewing a PR.

#### `search_code(query, limit=10)`
Searches across the local graph and any linked external graphs. Results are ranked with BM25 scoring boosted by graph proximity.

### Multi-Repo Tools

#### `register_repository(name, path, kind, tags)`
Register a repo in the federation for cross-repo analysis.

```
register_repository(
    name="shared-lib",
    path="/path/to/shared-lib",
    kind="library",
    tags=["python", "utilities"]
)
```

#### `get_cross_repo_impact(repo_name, changed_files)`
Trace how changes in one repo affect others. Critical for shared libraries.

#### `import_external_graph(source_path, name)`
Import a built graph from another project into your local searchable index.

#### `auto_detect_related_repos(base_path)`
Scan a directory for sibling projects that have built graphs.

### Utility Tools

#### `generate_visualization(changed_files, output_path)`
Creates an interactive HTML visualization of the dependency graph.

#### `record_search_feedback(query, node_id, useful)`
Record whether a search result was helpful — adjusts future rankings.

#### `list_repositories()`
List all registered repos in the federation.

#### `configure_auto_scan(scan_paths)`
Set directories to auto-discover external graphs.

## How It Works

```
Your Code                    Graph                         AI Assistant
─────────                    ─────                         ────────────
 auth.py ──────┐          ┌─ validate() ─calls──▶ check_db()
 routes.py ────┼─ parse ──┤─ handle_login() ─calls──▶ validate()
 models.py ────┘          └─ User (class) ─imports──▶ sqlalchemy
                               │
                          git history:
                          auth.py: 12 changes/90d
                          models.py: 3 changes/90d
                               │
                          ▼ impact query ▼
                          "What breaks if I change validate()?"
                          → handle_login (calls it)
                          → routes.py (imports auth)
                          → auth.py is high-volatility ⚠️
```

## Data Storage

Graph data is stored at `~/.code-review-graph-v2/` by default. Override with:

```bash
export CRG_V2_DATA_DIR=/custom/path
```

Contents:
- `graph.json` — nodes, edges, call sites, change history
- `impact_model.json` — scoring weights and user feedback
- `search_feedback.json` — search ranking adjustments
- `external/` — imported graphs from other projects
- `visualization.html` — last generated visualization

## Known Limitations

- **Parsing is regex-based** — handles common patterns well, but may miss edge cases like multi-line function signatures, decorators-as-wrappers, or dynamic dispatch
- **Impact scoring uses static heuristic weights** — not actual machine learning (yet)
- **Search is keyword-only** — no semantic/embedding-based search
- **No automatic rebuild** — you must re-run `build_graph` after code changes
- **Cross-repo impact is pattern-based** — traces module names in imports, not full dependency resolution
- **No automated test suite** — tested manually, `pytest` suite is planned

## Roadmap

- [ ] `pytest` test suite with 80%+ coverage
- [ ] Semantic search (embedding-based)
- [ ] Auto-rebuild via file watcher or git hooks
- [ ] Real ML training from feedback data
- [ ] Multi-line signature parsing
- [ ] Performance benchmarks on large repos (500+ files)
- [ ] CI/CD pipeline

## License

MIT