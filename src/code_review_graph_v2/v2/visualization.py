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
        #graph-container {{ height: 400px; background: #0f172a; border-radius: 8px; }}
        .flow-item {{ display: flex; align-items: center; padding: 10px; margin: 8px 0; background: #334155; border-radius: 6px; }}
        .flow-badge {{ padding: 4px 10px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; margin-right: 12px; }}
        .flow-name {{ flex: 1; font-weight: 500; }}
        .flow-file {{ color: #94a3b8; font-size: 0.8rem; }}
        .impact-item {{ display: flex; justify-content: space-between; align-items: center; padding: 12px; margin: 8px 0; background: #334155; border-radius: 6px; }}
        .impact-score {{ font-weight: 700; font-size: 1.1rem; }}
        .impact-file {{ font-weight: 500; }}
        .impact-reasons {{ color: #94a3b8; font-size: 0.75rem; }}
        .stats {{ display: flex; gap: 20px; margin-bottom: 20px; }}
        .stat {{ background: #1e293b; padding: 15px 25px; border-radius: 8px; border: 1px solid #334155; }}
        .stat-value {{ font-size: 1.5rem; font-weight: 700; color: #38bdf8; }}
        .stat-label {{ color: #94a3b8; font-size: 0.85rem; }}
        .legend {{ display: flex; gap: 15px; margin-top: 10px; }}
        .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 0.8rem; }}
        .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
        svg line {{ stroke: #475569; stroke-width: 1; }}
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
                    <div class="legend-item"><div class="legend-dot" style="background:#fb923c"></div>Import</div>
                    <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div>Highlighted</div>
                </div>
                <div id="graph-container"></div>
            </div>
            
            <div class="card">
                <h2>🌊 Execution Flows</h2>
                <div class="legend">
                    <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div>Critical</div>
                    <div class="legend-item"><div class="legend-dot" style="background:#f97316"></div>High</div>
                    <div class="legend-item"><div class="legend-dot" style="background:#eab308"></div>Medium</div>
                    <div class="legend-item"><div class="legend-dot" style="background:#22c55e"></div>Low</div>
                </div>
                <div id="flows-container">
                    {self._render_flows(flow_viz.flows[:10])}
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
        const nodes = {json.dumps(viz.nodes[:50])};
        const edges = {json.dumps(viz.edges[:100])};
        
        const width = document.getElementById('graph-container').clientWidth;
        const height = 380;
        
        const svg = d3.select('#graph-container')
            .append('svg')
            .attr('width', width)
            .attr('height', height);
        
        const simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(edges).id(d => d.id).distance(60))
            .force('charge', d3.forceManyBody().strength(-150))
            .force('center', d3.forceCenter(width / 2, height / 2));
        
        const link = svg.append('g')
            .selectAll('line')
            .data(edges)
            .enter().append('line');
        
        const node = svg.append('g')
            .selectAll('circle')
            .data(nodes)
            .enter().append('circle')
            .attr('r', d => d.highlighted ? 10 : 6)
            .attr('fill', d => {{
                if (d.highlighted) return '#ef4444';
                if (d.type === 'function') return '#38bdf8';
                if (d.type === 'class') return '#a78bfa';
                return '#fb923c';
            }})
            .call(d3.drag()
                .on('start', dragstarted)
                .on('drag', dragged)
                .on('end', dragended));
        
        node.append('title').text(d => d.label);
        
        simulation.on('tick', () => {{
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);
            
            node
                .attr('cx', d => d.x = Math.max(10, Math.min(width - 10, d.x)))
                .attr('cy', d => d.y = Math.max(10, Math.min(height - 10, d.y)));
        }});
        
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