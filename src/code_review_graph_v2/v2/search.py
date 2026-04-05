from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .models import SearchResult


@dataclass
class SearchConfig:
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    semantic_weight: float = 0.3
    graph_weight: float = 0.2
    popularity_weight: float = 0.1


class LearnedSearcher:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or Path(".code-review-graph-v2")
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.clicks_path = self.data_dir / "search_clicks.json"
        self._config = SearchConfig()
        self._load_clicks()

    def _load_clicks(self) -> None:
        if self.clicks_path.exists():
            with open(self.clicks_path) as f:
                data = json.load(f)
                self._query_doc_scores = data.get("scores", {})
        else:
            self._query_doc_scores = defaultdict(lambda: defaultdict(float))

    def _save_clicks(self) -> None:
        with open(self.clicks_path, "w") as f:
            json.dump({"scores": dict(self._query_doc_scores)}, f)

    def _tokenize(self, text: str) -> list[str]:
        return text.lower().split()

    def _bm25_score(
        self,
        query: str,
        doc_text: str,
        doc_len: int,
        avg_doc_len: float,
        total_docs: int = 1,
        doc_frequencies: dict[str, int] | None = None,
    ) -> float:
        query_terms = self._tokenize(query)
        doc_terms = self._tokenize(doc_text)
        term_freq = defaultdict(int)

        for term in doc_terms:
            term_freq[term] += 1

        score = 0.0
        for term in query_terms:
            if term in term_freq:
                tf = term_freq[term]
                # Proper IDF: log((N - df + 0.5) / (df + 0.5) + 1)
                df = (doc_frequencies or {}).get(term, 1)
                idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
                numerator = tf * (self._config.bm25_k1 + 1)
                denominator = tf + self._config.bm25_k1 * (
                    1 - self._config.bm25_b + self._config.bm25_b * (doc_len / avg_doc_len)
                )
                score += idf * (numerator / denominator)

        return score

    def _graph_proximity(
        self,
        node_id: str,
        context_nodes: list[str],
        graph: "GraphV2 | None" = None,
    ) -> float:
        if not context_nodes or not graph:
            return 0.0

        # BFS shortest path from any context node to this node
        min_distance = float("inf")
        for start in context_nodes:
            visited: set[str] = set()
            queue: list[tuple[str, int]] = [(start, 0)]
            while queue:
                current, depth = queue.pop(0)
                if depth > 5:  # max search depth
                    break
                if current == node_id:
                    min_distance = min(min_distance, depth)
                    break
                if current in visited:
                    continue
                visited.add(current)
                # Follow edges in both directions
                for edge in graph.get_outgoing_edges(current):
                    if edge.target_id not in visited:
                        queue.append((edge.target_id, depth + 1))
                for edge in graph.get_incoming_edges(current):
                    if edge.source_id not in visited:
                        queue.append((edge.source_id, depth + 1))

        if min_distance == float("inf"):
            return 0.0
        # Closer nodes get higher scores: 1.0 for distance=1, decreasing
        return max(0.0, 1.0 - (min_distance - 1) * 0.2)

    def search(
        self,
        query: str,
        nodes: dict,
        graph: "GraphV2 | None" = None,
        context_nodes: list[str] | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        node_texts = {nid: f"{node.name} {node.node_type}" for nid, node in nodes.items()}

        avg_doc_len = sum(len(t.split()) for t in node_texts.values()) / max(1, len(node_texts))

        # Pre-compute document frequencies for proper IDF
        all_terms: dict[str, int] = defaultdict(int)  # term -> number of docs containing it
        for text in node_texts.values():
            seen_terms: set[str] = set()
            for term in self._tokenize(text):
                if term not in seen_terms:
                    all_terms[term] += 1
                    seen_terms.add(term)
        total_docs = max(1, len(node_texts))

        query_terms = self._tokenize(query)
        query_doc_score = self._query_doc_scores.get(query, {})

        for node_id, text in node_texts.items():
            bm25 = self._bm25_score(
                query, text, len(text.split()), avg_doc_len,
                total_docs=total_docs, doc_frequencies=all_terms,
            )

            semantic = 0.0
            if query_terms:
                matches = sum(1 for t in query_terms if t in text.lower())
                semantic = matches / len(query_terms)

            graph_score = 0.0
            if graph and context_nodes:
                graph_score = self._graph_proximity(node_id, context_nodes, graph)

            learned_score = query_doc_score.get(node_id, 0.0)

            final_score = (
                bm25 * 0.4
                + semantic * self._config.semantic_weight
                + graph_score * self._config.graph_weight
                + learned_score * self._config.popularity_weight
            )

            match_type = "keyword"
            if semantic > 0.5:
                match_type = "semantic"
            if learned_score > 0:
                match_type = "learned"

            results.append(SearchResult(
                node_id=node_id,
                name=nodes[node_id].name,
                file_path=nodes[node_id].file_path,
                score=final_score,
                match_type=match_type,
            ))

        return sorted(results, key=lambda x: -x.score)[:limit]

    def record_click(self, query: str, node_id: str) -> None:
        self._query_doc_scores[query][node_id] += 0.1
        self._save_clicks()