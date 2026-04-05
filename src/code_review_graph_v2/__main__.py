from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        prog="code-review-graph-v2",
        description="ML-powered code review context with multi-repo support",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    build_parser = subparsers.add_parser("build", help="Build code graph")
    build_parser.add_argument("--path", "-p", default=".", help="Path to parse")
    
    subparsers.add_parser("status", help="Show graph statistics")
    
    vis_parser = subparsers.add_parser("visualize", help="Generate HTML visualization")
    vis_parser.add_argument("--output", "-o", help="Output HTML path")
    
    config_parser = subparsers.add_parser("config", help="Configure auto-scan paths")
    config_parser.add_argument("paths", nargs="*", help="Paths to scan")
    
    detect_parser = subparsers.add_parser("detect", help="Auto-detect repos")
    detect_parser.add_argument("path", help="Base path to scan")
    
    args = parser.parse_args()
    
    if args.command == "build":
        from code_review_graph_v2 import build_graph
        result = build_graph(args.path)
        print(f"Built: {result['files_parsed']} files, {result['nodes_created']} nodes")
        
    elif args.command == "status":
        from code_review_graph_v2 import get_graph
        graph = get_graph()
        print(f"Nodes: {len(graph.graph.nodes)}")
        print(f"Edges: {len(graph.graph.edges)}")
        print(f"External repos: {len(graph.federation._external_graphs)}")
        
    elif args.command == "visualize":
        from code_review_graph_v2 import generate_visualization
        result = generate_visualization(output_path=args.output)
        print(f"Generated: {result['output_path']}")
        
    elif args.command == "config":
        from code_review_graph_v2 import configure_auto_scan
        result = configure_auto_scan(args.paths or [])
        print(f"Auto-scan paths: {result['scan_paths']}")
        print(f"Discovered repos: {result['discovered_repos']}")
        
    elif args.command == "detect":
        from code_review_graph_v2 import auto_detect_related_repos
        result = auto_detect_related_repos(args.path)
        print(f"Found: {len(result['repos'])} repos")
        for repo in result["repos"]:
            print(f"  - {repo['name']}: {repo['path']}")
        
    else:
        parser.print_help()


if __name__ == "__main__":
    main()