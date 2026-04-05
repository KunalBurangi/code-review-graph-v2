from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class GraphVisualization:
    nodes: list[dict]
    edges: list[dict]
    metadata: dict


@dataclass
class FlowDiagram:
    flows: list[dict]
    criticality_colors: dict


class Visualizer:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or Path(".code-review-graph-v2")
        self.data_dir.mkdir(exist_ok=True, parents=True)

    def generate_interactive_graph(
        self,
        graph: "GraphV2",
        highlight_files: list[str] | None = None,
    ) -> GraphVisualization:
        nodes = []
        edges = []
        highlight_set = set(highlight_files or [])

        for node in graph.nodes.values():
            nodes.append({
                "id": node.id,
                "label": node.name,
                "type": node.node_type,
                "file": node.file_path,
                "line": node.start_line,
                "highlighted": node.file_path in highlight_set,
            })

        for edge in graph.edges:
            edges.append({
                "source": edge.source_id,
                "target": edge.target_id,
                "type": edge.edge_type,
            })

        return GraphVisualization(
            nodes=nodes,
            edges=edges,
            metadata={
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "highlighted_count": len(highlight_set),
            }
        )

    def generate_flow_diagram(
        self,
        flows: list["FlowEntry"],
    ) -> FlowDiagram:
        flow_dicts = []
        criticality_colors = {
            "critical": "#ef4444",
            "high": "#f97316",
            "medium": "#eab308",
            "low": "#22c55e",
        }

        for flow in flows:
            criticality = "low"
            if flow.criticality > 0.8:
                criticality = "critical"
            elif flow.criticality > 0.6:
                criticality = "high"
            elif flow.criticality > 0.4:
                criticality = "medium"

            flow_dicts.append({
                "id": flow.id,
                "name": flow.name,
                "type": flow.entry_type,
                "file": flow.file_path,
                "line": flow.line,
                "framework": flow.framework,
                "criticality": flow.criticality,
                "color": criticality_colors[criticality],
            })

        return FlowDiagram(
            flows=flow_dicts,
            criticality_colors=criticality_colors,
        )

    def generate_impact_timeline(
        self,
        impact_predictions: list["ImpactPrediction"],
    ) -> dict:
        timeline = {
            "events": [],
            "total_impact": len(impact_predictions),
        }

        for pred in sorted(impact_predictions, key=lambda x: -x.score):
            timeline["events"].append({
                "file": Path(pred.file_path).name,
                "path": pred.file_path,
                "score": round(pred.score, 2),
                "reasons": pred.reasons,
                "affected": pred.is_likely_impacted,
            })

        return timeline

    def _select_graph_subset(
        self,
        viz: GraphVisualization,
        max_nodes: int = 200,
    ) -> tuple[list[dict], list[dict]]:
        """Select a connected subset of nodes + matching edges for rendering.

        Prioritises highlighted nodes and those with the most connections so the
        visualisation shows the most informative part of the graph.
        """
        all_nodes = viz.nodes
        all_edges = viz.edges

        if len(all_nodes) <= max_nodes:
            # Small enough to render everything – just filter orphan edges
            node_ids = {n["id"] for n in all_nodes}
            valid_edges = [
                e for e in all_edges
                if e["source"] in node_ids and e["target"] in node_ids
            ]
            return all_nodes, valid_edges

        # Count connections per node
        conn: dict[str, int] = {}
        for e in all_edges:
            conn[e["source"]] = conn.get(e["source"], 0) + 1
            conn[e["target"]] = conn.get(e["target"], 0) + 1

        # Always include highlighted nodes, then most-connected
        highlighted = [n for n in all_nodes if n.get("highlighted")]
        others = sorted(
            [n for n in all_nodes if not n.get("highlighted")],
            key=lambda n: conn.get(n["id"], 0),
            reverse=True,
        )
        selected = highlighted + others[: max_nodes - len(highlighted)]
        selected = selected[:max_nodes]

        node_ids = {n["id"] for n in selected}
        valid_edges = [
            e for e in all_edges
            if e["source"] in node_ids and e["target"] in node_ids
        ]
        return selected, valid_edges

    def export_html(
        self,
        graph: "GraphV2",
        flows: list["FlowEntry"],
        impact_predictions: list["ImpactPrediction"],
        output_path: Path | None = None,
    ) -> str:
        viz = self.generate_interactive_graph(graph, [p.file_path for p in impact_predictions])
        flow_viz = self.generate_flow_diagram(flows)
        timeline = self.generate_impact_timeline(impact_predictions)

        # Select a renderable subset (nodes + only edges that reference them)
        render_nodes, render_edges = self._select_graph_subset(viz, max_nodes=200)

        html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Code Review Graph v2</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #38bdf8; margin-bottom: 20px; font-size: 1.8rem; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
        .card h2 {{ color: #38bdf8; font-size: 1.1rem; margin-bottom: 15px; }}
        #graph-container {{ height: 500px; background: #0f172a; border-radius: 8px; overflow: hidden; position: relative; }}
        .graph-toolbar {{ display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }}
        .graph-toolbar input {{ background: #334155; border: 1px solid #475569; color: #e2e8f0; padding: 6px 12px; border-radius: 6px; font-size: 0.85rem; width: 220px; }}
        .graph-toolbar input::placeholder {{ color: #64748b; }}
        .graph-toolbar button {{ background: #334155; border: 1px solid #475569; color: #e2e8f0; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }}
        .graph-toolbar button:hover {{ background: #475569; }}
        .graph-info {{ position: absolute; bottom: 8px; right: 12px; color: #64748b; font-size: 0.7rem; pointer-events: none; }}
        .tooltip {{ position: absolute; background: #1e293b; border: 1px solid #475569; border-radius: 8px; padding: 10px 14px; font-size: 0.8rem; pointer-events: none; opacity: 0; transition: opacity 0.15s; z-index: 10; max-width: 300px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }}
        .tooltip .tt-name {{ font-weight: 600; color: #38bdf8; margin-bottom: 4px; }}
        .tooltip .tt-file {{ color: #94a3b8; font-size: 0.75rem; word-break: break-all; }}
        .tooltip .tt-type {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; margin-top: 4px; }}
        .flow-item {{ display: flex; align-items: center; padding: 10px; margin: 8px 0; background: #334155; border-radius: 6px; }}
        .flow-badge {{ padding: 4px 10px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; margin-right: 12px; }}
        .flow-name {{ flex: 1; font-weight: 500; }}
        .flow-file {{ color: #94a3b8; font-size: 0.8rem; }}
        .impact-item {{ display: flex; justify-content: space-between; align-items: center; padding: 12px; margin: 8px 0; background: #334155; border-radius: 6px; }}
        .impact-score {{ font-weight: 700; font-size: 1.1rem; }}
        .impact-file {{ font-weight: 500; }}
        .impact-reasons {{ color: #94a3b8; font-size: 0.75rem; }}
        .stats {{ display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }}
        .stat {{ background: #1e293b; padding: 15px 25px; border-radius: 8px; border: 1px solid #334155; }}
        .stat-value {{ font-size: 1.5rem; font-weight: 700; color: #38bdf8; }}
        .stat-label {{ color: #94a3b8; font-size: 0.85rem; }}
        .legend {{ display: flex; gap: 15px; margin-top: 10px; flex-wrap: wrap; }}
        .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 0.8rem; }}
        .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 Code Review Graph v2</h1>

        <div class="stats">
            <div class="stat">
                <div class="stat-value">{viz.metadata["total_nodes"]}</div>
                <div class="stat-label">Nodes</div>
            </div>
            <div class="stat">
                <div class="stat-value">{viz.metadata["total_edges"]}</div>
                <div class="stat-label">Edges</div>
            </div>
            <div class="stat">
                <div class="stat-value">{len(render_nodes)}</div>
                <div class="stat-label">Rendered</div>
            </div>
            <div class="stat">
                <div class="stat-value">{len(flow_viz.flows)}</div>
                <div class="stat-label">Flows</div>
            </div>
            <div class="stat">
                <div class="stat-value">{timeline["total_impact"]}</div>
                <div class="stat-label">Impacted</div>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h2>📊 Interactive Graph</h2>
                <div class="legend">
                    <div class="legend-item"><div class="legend-dot" style="background:#38bdf8"></div>Function</div>
                    <div class="legend-item"><div class="legend-dot" style="background:#a78bfa"></div>Class</div>
                    <div class="legend-item"><div class="legend-dot" style="background:#fb923c"></div>Module</div>
                    <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div>Highlighted</div>
                </div>
                <div class="graph-toolbar">
                    <input type="text" id="search-input" placeholder="Search nodes…" />
                    <button id="btn-reset">Reset zoom</button>
                </div>
                <div id="graph-container">
                    <div class="tooltip" id="tooltip"></div>
                    <div class="graph-info">Showing {len(render_nodes)} of {viz.metadata["total_nodes"]} nodes · Scroll to zoom · Drag to pan</div>
                </div>
            </div>

            <div class="card" style="max-height:620px;overflow-y:auto;">
                <h2>🌊 Execution Flows</h2>
                <div class="legend">
                    <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div>Critical</div>
                    <div class="legend-item"><div class="legend-dot" style="background:#f97316"></div>High</div>
                    <div class="legend-item"><div class="legend-dot" style="background:#eab308"></div>Medium</div>
                    <div class="legend-item"><div class="legend-dot" style="background:#22c55e"></div>Low</div>
                </div>
                <div id="flows-container">
                    {self._render_flows(flow_viz.flows[:20])}
                </div>
            </div>
        </div>

        <div class="card" style="margin-top: 20px;">
            <h2>💥 Impact Analysis</h2>
            <div id="impact-container">
                {self._render_impact(timeline["events"])}
            </div>
        </div>
    </div>

    <script>
        // ── Data ──
        const nodes = {json.dumps(render_nodes)};
        const edges = {json.dumps(render_edges)};

        // ── Dimensions ──
        const container = document.getElementById('graph-container');
        const width  = container.clientWidth  || 600;
        const height = container.clientHeight || 480;

        // ── SVG + zoom ──
        const svg = d3.select('#graph-container')
            .append('svg')
            .attr('width', width)
            .attr('height', height);

        const g = svg.append('g');   // zoomable root group

        const zoom = d3.zoom()
            .scaleExtent([0.15, 5])
            .on('zoom', (event) => g.attr('transform', event.transform));
        svg.call(zoom);

        document.getElementById('btn-reset').addEventListener('click', () => {{
            svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
        }});

        // ── Colour helper ──
        function nodeColor(d) {{
            if (d.highlighted) return '#ef4444';
            if (d.type === 'class')    return '#a78bfa';
            if (d.type === 'function') return '#38bdf8';
            return '#fb923c';
        }}

        // ── Simulation ──
        const simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(edges).id(d => d.id).distance(70))
            .force('charge', d3.forceManyBody().strength(-120))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(14));

        // ── Links ──
        const link = g.append('g')
            .attr('stroke-opacity', 0.35)
            .selectAll('line')
            .data(edges)
            .enter().append('line')
            .attr('stroke', '#475569')
            .attr('stroke-width', 1);

        // ── Nodes ──
        const node = g.append('g')
            .selectAll('circle')
            .data(nodes)
            .enter().append('circle')
            .attr('r', d => d.highlighted ? 9 : 5)
            .attr('fill', nodeColor)
            .attr('stroke', d => d.highlighted ? '#fca5a5' : 'transparent')
            .attr('stroke-width', 2)
            .style('cursor', 'pointer')
            .call(d3.drag()
                .on('start', dragstarted)
                .on('drag', dragged)
                .on('end', dragended));

        // ── Labels (only for larger/highlighted nodes) ──
        const label = g.append('g')
            .selectAll('text')
            .data(nodes)
            .enter().append('text')
            .text(d => d.label.length > 22 ? d.label.slice(0, 20) + '…' : d.label)
            .attr('font-size', 9)
            .attr('fill', '#94a3b8')
            .attr('dx', 10)
            .attr('dy', 3)
            .style('pointer-events', 'none');

        // ── Tooltip ──
        const tooltip = d3.select('#tooltip');

        node.on('mouseover', (event, d) => {{
            const typeColors = {{ function: '#38bdf8', class: '#a78bfa', module: '#fb923c' }};
            const bg = typeColors[d.type] || '#fb923c';
            tooltip.html(
                '<div class="tt-name">' + d.label + '</div>' +
                '<div class="tt-file">' + d.file + ':' + d.line + '</div>' +
                '<span class="tt-type" style="background:' + bg + '22;color:' + bg + '">' + d.type + '</span>'
            )
            .style('left', (event.offsetX + 14) + 'px')
            .style('top',  (event.offsetY - 10) + 'px')
            .style('opacity', 1);
        }})
        .on('mouseout', () => tooltip.style('opacity', 0));

        // ── Tick ──
        simulation.on('tick', () => {{
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);
            node
                .attr('cx', d => d.x)
                .attr('cy', d => d.y);
            label
                .attr('x', d => d.x)
                .attr('y', d => d.y);
        }});

        // ── Search ──
        const searchInput = document.getElementById('search-input');
        searchInput.addEventListener('input', () => {{
            const q = searchInput.value.toLowerCase();
            if (!q) {{
                node.attr('opacity', 1).attr('r', d => d.highlighted ? 9 : 5);
                label.attr('opacity', 1);
                link.attr('stroke-opacity', 0.35);
                return;
            }}
            node.attr('opacity', d => d.label.toLowerCase().includes(q) ? 1 : 0.1)
                .attr('r', d => d.label.toLowerCase().includes(q) ? 12 : 4);
            label.attr('opacity', d => d.label.toLowerCase().includes(q) ? 1 : 0.05);
            link.attr('stroke-opacity', 0.08);
        }});

        // ── Drag helpers ──
        function dragstarted(event) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            event.subject.fx = event.subject.x;
            event.subject.fy = event.subject.y;
        }}
        function dragged(event) {{
            event.subject.fx = event.x;
            event.subject.fy = event.y;
        }}
        function dragended(event) {{
            if (!event.active) simulation.alphaTarget(0);
            event.subject.fx = null;
            event.subject.fy = null;
        }}
    </script>
</body>
</html>'''

        if output_path:
            output_path.write_text(html)
        return html

    def _render_flows(self, flows: list[dict]) -> str:
        if not flows:
            return '<p style="color:#94a3b8">No flows detected</p>'
        html = ''
        for flow in flows:
            html += f'''
            <div class="flow-item">
                <span class="flow-badge" style="background:{flow["color"]}">{flow.get("framework", "unknown")}</span>
                <span class="flow-name">{flow["name"]}</span>
                <span class="flow-file">{Path(flow["file"]).name}:{flow["line"]}</span>
            </div>'''
        return html

    def _render_impact(self, events: list[dict]) -> str:
        if not events:
            return '<p style="color:#94a3b8">No impact predictions</p>'
        html = ''
        for event in events:
            score_color = '#ef4444' if event["score"] > 0.7 else '#f97316' if event["score"] > 0.4 else '#22c55e'
            html += f'''
            <div class="impact-item">
                <div>
                    <div class="impact-file">{event["file"]}</div>
                    <div class="impact-reasons">{", ".join(event["reasons"]) if event["reasons"] else "Direct change"}</div>
                </div>
                <div class="impact-score" style="color:{score_color}">{event["score"]:.0%}</div>
            </div>'''
        return html


from .models import FlowEntry, ImpactPrediction
from .impact import GraphV2
from pathlib import Path