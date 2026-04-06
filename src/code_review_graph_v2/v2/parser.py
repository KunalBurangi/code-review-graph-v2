from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from .models import CodeEdge, CodeNode, FlowEntry


LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".vue": "vue",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "cpp",
    ".sol": "solidity",
    ".dart": "dart",
    ".r": "r",
    ".lua": "lua",
}

# Languages that use indentation to delimit blocks.
_INDENT_LANGUAGES = {"python", "ruby"}

# Languages that use braces to delimit blocks.
_BRACE_LANGUAGES = {
    "javascript", "typescript", "go", "rust", "java",
    "php", "swift", "kotlin", "csharp", "c", "cpp",
    "solidity", "dart", "lua",
}


FUNCTION_PATTERNS = {
    "python": [
        r"^(\s*)def\s+(\w+)\s*\(",
        r"^(\s*)async\s+def\s+(\w+)\s*\(",
        r"^(\s*)class\s+(\w+)",
    ],
    "javascript": [
        r"^\s*(?:export\s+)?class\s+(\w+)",
        r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)",
        r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>",
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)",
        r"^\s*(?:public|private|protected)?\s*(?:static)?\s*(?:async\s+)?(\w+)\s*\(",
        r"^\s*constructor\s*\(",
    ],
    "typescript": [
        r"^\s*(?:export\s+)?class\s+(\w+)",
        r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)",
        r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>",
        r"^\s*(?:public|private|protected)?\s*(?:readonly)?\s*(?:static)?\s*(?:async\s+)?(\w+)\s*\(",
        r"^\s*constructor\s*\(",
    ],
    "go": [
        r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(",
        r"^func\s+\(\w+\s+\*?\w+\)\s+(\w+)\s*\(",
    ],
    "rust": [
        r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)",
        r"^\s*(?:pub\s+)?struct\s+(\w+)",
    ],
    "java": [
        r"^\s*(?:public|private|protected)?\s*(?:static)?\s*(?:\w+\s+)+(\w+)\s*\(",
        r"^\s*(?:public|private|protected)?\s*class\s+(\w+)",
    ],
    "ruby": [
        r"^\s*def\s+(\w+)",
        r"^\s*class\s+(\w+)",
    ],
    "php": [
        r"^\s*(?:public|private|protected)?\s*function\s+(\w+)",
        r"^\s*(?:abstract\s+)?class\s+(\w+)",
    ],
}


IMPORT_PATTERNS = {
    "python": [
        r"^(?:from\s+(\S+)\s+)?import\s+(.+)",
    ],
    "javascript": [
        r"^\s*import\s+(?:(?:\{[^}]+\})|(?:\*\s+as\s+\w+)|(?:\w+))\s+from\s+['\"]([^'\"]+)['\"]",
        r"^\s*require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ],
    "typescript": [
        r"^\s*import\s+(?:(?:\{[^}]+\})|(?:\*\s+as\s+\w+)|(?:\w+))\s+from\s+['\"]([^'\"]+)['\"]",
        r"^\s*import\s+['\"]([^'\"]+)['\"]",
    ],
    "go": [
        r"^\s*import\s+(?:\(\s*)?['\"](\S+)['\"]",
    ],
}


FRAMEWORK_PATTERNS = {
    "python": {
        "fastapi": [
            r"@app\.(get|post|put|delete|patch)\s*\(",
            r"@router\.(get|post|put|delete|patch)\s*\(",
            r"FastAPI\s*\(",
        ],
        "flask": [
            r"@app\.(route|get|post|put|delete)\s*\(",
            r"@blueprint\.(route|get|post)\s*\(",
        ],
        "django": [
            r"path\s*\(",
            r"re_path\s*\(",
            r"urlpatterns",
        ],
        "httpx": [
            r"Client\s*\(",
            r"AsyncClient\s*\(",
        ],
    },
    "javascript": {
        "express": [
            r"express\s*\(\)",
            r"app\.(get|post|put|delete|patch|use)\s*\(",
            r"router\.(get|post|put|delete|patch|use)\s*\(",
        ],
        "nextjs": [
            r"(?:getStaticProps|getServerSideProps|getStaticPaths)",
            r"(?:useRouter|usePathname)",
            r"export\s+(?:default\s+)?(?:function|const)\s+\w+",
        ],
        "react": [
            r"createElement\s*\(",
            r"useState\s*\(",
            r"useEffect\s*\(",
            r"React\.(?:createElement|Component)",
        ],
        "vue": [
            r"export\s+default\s+{",
            r"defineComponent\s*\(",
        ],
    },
    "go": {
        "gin": [
            r"gin\.Default\s*\(",
            r"gin\.New\s*\(",
            r"router\.(GET|POST|PUT|DELETE|PATCH)\s*\(",
        ],
        "echo": [
            r"echo\.New\s*\(",
            r"e\.(GET|POST|PUT|DELETE|PATCH)\s*\(",
        ],
        "standard": [
            r"http\.(Handle|HandleFunc|ListenAndServe)",
        ],
    },
}


# ---------------------------------------------------------------------------
# end_line detection helpers
# ---------------------------------------------------------------------------


def _find_block_end_indent(lines: list[str], start_idx: int) -> int:
    """Find end of an indentation-based block (Python, Ruby).

    Scans forward from the definition line until we hit a non-empty line
    at the same or lower indentation level.
    """
    if start_idx >= len(lines):
        return start_idx

    def_line = lines[start_idx]
    # measure leading whitespace of the definition line itself
    def_indent = len(def_line) - len(def_line.lstrip())

    last_body_idx = start_idx  # fallback: at least the definition line

    for idx in range(start_idx + 1, len(lines)):
        line = lines[idx]
        stripped = line.strip()

        # skip blank lines and comments – they don't end blocks
        if not stripped or stripped.startswith("#"):
            continue

        line_indent = len(line) - len(line.lstrip())
        if line_indent <= def_indent:
            # This line is at the same or lower indentation → block ended
            break
        last_body_idx = idx

    return last_body_idx


def _find_block_end_brace(lines: list[str], start_idx: int) -> int:
    """Find end of a brace-delimited block (JS, TS, Go, Java, …).

    Starts scanning from the definition line, looks for the first ``{`` and
    then tracks brace depth until it drops to zero.
    """
    depth = 0
    started = False

    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        for ch in line:
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
                if started and depth <= 0:
                    return idx

    # If no matching brace found, fall back to reasonable heuristic:
    # next 20 lines or EOF, whichever is smaller.
    return min(start_idx + 20, len(lines) - 1)


def _find_block_end(lines: list[str], start_idx: int, lang: str) -> int:
    """Return the 0-indexed line number of the last line in the block."""
    if lang in _INDENT_LANGUAGES:
        return _find_block_end_indent(lines, start_idx)
    if lang in _BRACE_LANGUAGES:
        return _find_block_end_brace(lines, start_idx)
    # Unknown language – default to single line
    return start_idx


# ---------------------------------------------------------------------------
# Intra-file call detection
# ---------------------------------------------------------------------------

# Pattern to find function-call-like tokens: ``name(``
_CALL_RE = re.compile(r"\b(\w+)\s*\(")


def _detect_calls(
    lines: list[str],
    nodes: list[CodeNode],
    path: Path,
) -> list[CodeEdge]:
    """Detect function calls within each function body.

    For every function node, scan its body lines for calls to other known
    function names in the same file.  Creates ``calls`` edges.
    """
    # Build a lookup: function_name → node (only functions, not classes/imports)
    func_names: dict[str, CodeNode] = {}
    for node in nodes:
        if node.node_type == "function" and node.name != "anonymous":
            func_names[node.name] = node

    if not func_names:
        return []

    call_edges: list[CodeEdge] = []
    seen: set[tuple[str, str]] = set()

    for caller in nodes:
        if caller.node_type not in ("function", "class"):
            continue

        # Scan the caller's body lines for calls to known functions
        body_start = caller.start_line - 1  # 0-indexed
        body_end = caller.end_line  # exclusive upper bound

        for line_idx in range(body_start + 1, min(body_end, len(lines))):
            line = lines[line_idx]
            for m in _CALL_RE.finditer(line):
                callee_name = m.group(1)
                if callee_name == caller.name:
                    continue  # skip self-recursion noise
                if callee_name in func_names:
                    callee = func_names[callee_name]
                    key = (caller.id, callee.id)
                    if key not in seen:
                        seen.add(key)
                        call_edges.append(
                            CodeEdge(
                                source_id=caller.id,
                                target_id=callee.id,
                                edge_type="calls",
                                call_site=f"{path}:{line_idx + 1}",
                            )
                        )

    return call_edges


# ---------------------------------------------------------------------------
# Main parse entry point
# ---------------------------------------------------------------------------


def parse_file_v2(
    path: Path, content: str | None = None
) -> tuple[list[CodeNode], list[CodeEdge]]:
    if content is None:
        content = path.read_text(encoding="utf-8")

    ext = path.suffix
    lang = LANGUAGE_EXTENSIONS.get(ext, "unknown")
    nodes: list[CodeNode] = []
    edges: list[CodeEdge] = []

    if lang not in FUNCTION_PATTERNS:
        return nodes, edges

    func_patterns = FUNCTION_PATTERNS.get(lang, [])
    lines = content.split("\n")
    file_hash = CodeNode.compute_hash(content)

    node_by_line: dict[int, CodeNode] = {}
    current_class: CodeNode | None = None
    class_stack: list[CodeNode] = []  # Track nested classes

    for i, line in enumerate(lines, start=1):
        # Determine current indentation level (for class scope tracking)
        indent_level = len(line) - len(line.lstrip())
        
        # Pop class stack if we dedented out of current class
        while class_stack and class_stack[-1].end_line == 0:
            # Don't pop yet; end_line isn't set
            break
        
        for pattern in func_patterns:
            match = re.match(pattern, line)
            if match:
                # Use last captured group — always the name across all patterns
                name = match.group(match.lastindex) if match.lastindex else "anonymous"
                
                # Special handling for constructor
                if "constructor" in pattern and match.group(0):
                    name = "constructor"
                
                is_class = "class" in pattern
                node_type = "class" if is_class else "function"

                # ── Compute real end_line ──
                end_line_idx = _find_block_end(lines, i - 1, lang)  # 0-indexed
                end_line = end_line_idx + 1  # convert to 1-indexed

                # Determine if this is a method (inside a class)
                parent_class = None
                if not is_class and current_class:
                    # Check if we're inside the current class's scope
                    if i > current_class.start_line and i <= current_class.end_line:
                        parent_class = current_class
                        node_type = "method"

                node = CodeNode(
                    id=f"{path}:{i}",
                    name=name,
                    node_type=node_type,
                    file_path=str(path),
                    start_line=i,
                    end_line=end_line,
                    code_hash=file_hash,
                    parent_class=parent_class.name if parent_class else None,
                )
                
                nodes.append(node)
                node_by_line[i] = node
                
                # Update current_class if this is a class definition
                if is_class:
                    current_class = node
                    class_stack.append(node)
                
                break

    import_patterns = IMPORT_PATTERNS.get(lang, [])
    import_nodes: dict[str, CodeNode] = {}
    import_statements: list[tuple[int, str, str]] = []  # (line_number, import_path, full_line)

    for i, line in enumerate(lines, start=1):
        for pattern in import_patterns:
            for match in re.finditer(pattern, line):
                if match.lastindex:
                    module = match.group(match.lastindex).split(",")[0].strip()
                    if module:
                        import_statements.append((i, module, line))
                        if module not in import_nodes:
                            imp_node = CodeNode(
                                id=f"import:{module}",
                                name=module,
                                node_type="import",
                                file_path=str(path),
                                start_line=i,
                                end_line=i,
                            )
                            import_nodes[module] = imp_node
                            nodes.append(imp_node)

    # ── Import edges: which functions use which imports ──
    for node in nodes:
        if node.node_type in ("function", "class", "method"):
            # Use the real start/end range for checking import usage
            body_text = "\n".join(lines[node.start_line - 1 : node.end_line])
            for imp_module, imp_node in import_nodes.items():
                if imp_module in body_text:
                    edges.append(CodeEdge(
                        source_id=node.id,
                        target_id=imp_node.id,
                        edge_type="imports",
                    ))

    # ── Call edges: which functions call which functions ──
    call_edges = _detect_calls(lines, nodes, path)
    edges.extend(call_edges)
    
    # Store import statements for cross-file resolution
    return nodes, edges


def resolve_cross_file_imports(
    all_nodes: dict[str, CodeNode],
    all_import_statements: dict[str, list[tuple[int, str, str]]],
    root_path: Path,
    lang: str,
) -> list[CodeEdge]:
    """Resolve import paths to actual files and create cross-file edges.
    
    Args:
        all_nodes: Dict of all nodes by ID
        all_import_statements: Dict of import statements per file
        root_path: Root directory for relative path resolution
        lang: Programming language
    
    Returns:
        List of cross-file import edges
    """
    cross_file_edges: list[CodeEdge] = []
    seen: set[tuple[str, str]] = set()
    
    for source_file, import_list in all_import_statements.items():
        source_path = Path(source_file)
        
        for line_num, import_path, full_line in import_list:
            # Skip external package imports (assume they contain /, are absolute, or don't resolve)
            if not import_path.startswith(".") and not import_path.startswith("/"):
                continue
            
            # Resolve relative import path
            if import_path.startswith("."):
                # Relative import: resolve from source file directory
                resolved_path = (source_path.parent / import_path).resolve()
            else:
                # Absolute import
                resolved_path = Path(import_path).resolve()
            
            # Try different extensions to find the actual file
            extensions = [".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".java"]
            target_file = None
            
            # Check if it's a directory import (index file)
            for ext in extensions:
                if resolved_path.is_dir():
                    candidate = resolved_path / f"index{ext}"
                    if candidate.exists():
                        target_file = candidate
                        break
                else:
                    # Try the path as-is and with extensions
                    if resolved_path.exists():
                        target_file = resolved_path
                        break
                    candidate = resolved_path.with_suffix(ext)
                    if candidate.exists():
                        target_file = candidate
                        break
            
            if not target_file:
                continue
            
            # Find exported functions/classes in target file
            target_file_str = str(target_file)
            for node_id, node in all_nodes.items():
                if node.file_path == target_file_str:
                    if node.node_type in ("class", "function", "method"):
                        # Find the importing node (function/class that uses this import)
                        for import_node_id, import_node in all_nodes.items():
                            if import_node.file_path == source_file:
                                if import_node.node_type in ("class", "function", "method"):
                                    # Check if this node uses the import
                                    if import_node.start_line <= line_num <= import_node.end_line:
                                        key = (import_node_id, node_id)
                                        if key not in seen:
                                            seen.add(key)
                                            cross_file_edges.append(CodeEdge(
                                                source_id=import_node_id,
                                                target_id=node_id,
                                                edge_type="imports",
                                            ))
    
    return cross_file_edges


def detect_flows_v2(
    path: Path, content: str | None = None
) -> list[FlowEntry]:
    if content is None:
        content = path.read_text(encoding="utf-8")

    ext = path.suffix
    lang = LANGUAGE_EXTENSIONS.get(ext, "unknown")
    flows: list[FlowEntry] = []

    if lang not in FRAMEWORK_PATTERNS:
        return flows

    frameworks = FRAMEWORK_PATTERNS.get(lang, {})
    lines = content.split("\n")

    for framework, patterns in frameworks.items():
        for i, line in enumerate(lines, start=1):
            for pattern in patterns:
                if re.search(pattern, line):
                    flow = FlowEntry(
                        id=f"{path}:flow:{i}",
                        name=f"{framework}_entry_{i}",
                        entry_type="http_handler",
                        file_path=str(path),
                        line=i,
                        framework=framework,
                        criticality=0.8,
                    )
                    flows.append(flow)
                    break

    return flows