"""
Knowledge Graph for the Engineering Knowledge Hub.

Stores relationships between entities:
- Door → located_in → Level
- Door → required_by → Code Clause
- Door → referenced_in → Drawing
- Door → listed_in → Schedule
- etc.
"""
from typing import List, Optional, Dict, Any, Set, Tuple
from dataclasses import dataclass, field

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


@dataclass
class GraphNode:
    """A node in the knowledge graph."""
    node_id: str
    node_type: str  # door, wall, room, requirement, drawing, etc.
    name: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    project_id: str = ""


@dataclass
class GraphEdge:
    """An edge in the knowledge graph."""
    src_id: str
    src_type: str
    relation: str  # located_in, required_by, references, etc.
    dst_id: str
    dst_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


class KnowledgeGraph:
    """
    In-memory knowledge graph with persistence to database.
    Supports entity-relation navigation.
    """

    def __init__(self):
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: List[GraphEdge] = []
        self._adjacency: Dict[str, List[GraphEdge]] = {}  # src_id -> edges
        self._reverse_adjacency: Dict[str, List[GraphEdge]] = {}  # dst_id -> edges

    def add_node(self, node: GraphNode):
        """Add a node to the graph."""
        self._nodes[node.node_id] = node
        if node.node_id not in self._adjacency:
            self._adjacency[node.node_id] = []
        if node.node_id not in self._reverse_adjacency:
            self._reverse_adjacency[node.node_id] = []

    def add_edge(self, edge: GraphEdge):
        """Add an edge to the graph."""
        self._edges.append(edge)
        if edge.src_id not in self._adjacency:
            self._adjacency[edge.src_id] = []
        self._adjacency[edge.src_id].append(edge)
        if edge.dst_id not in self._reverse_adjacency:
            self._reverse_adjacency[edge.dst_id] = []
        self._reverse_adjacency[edge.dst_id].append(edge)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID."""
        return self._nodes.get(node_id)

    def get_nodes_by_type(self, node_type: str, project_id: str = "") -> List[GraphNode]:
        """Get all nodes of a specific type."""
        return [
            n for n in self._nodes.values()
            if n.node_type == node_type and (not project_id or n.project_id == project_id)
        ]

    def get_edges_from(self, node_id: str, relation: str = "") -> List[GraphEdge]:
        """Get all edges from a node."""
        edges = self._adjacency.get(node_id, [])
        if relation:
            edges = [e for e in edges if e.relation == relation]
        return edges

    def get_edges_to(self, node_id: str, relation: str = "") -> List[GraphEdge]:
        """Get all edges to a node."""
        edges = self._reverse_adjacency.get(node_id, [])
        if relation:
            edges = [e for e in edges if e.relation == relation]
        return edges

    def get_related(self, node_id: str, relation: str = "",
                    direction: str = "out") -> List[GraphNode]:
        """Get all related nodes."""
        if direction == "out":
            edges = self.get_edges_from(node_id, relation)
            return [self._nodes.get(e.dst_id) for e in edges if e.dst_id in self._nodes]
        else:
            edges = self.get_edges_to(node_id, relation)
            return [self._nodes.get(e.src_id) for e in edges if e.src_id in self._nodes]

    def find_path(self, src_id: str, dst_id: str,
                  max_depth: int = 5) -> Optional[List[GraphEdge]]:
        """Find a path between two nodes (BFS)."""
        if src_id == dst_id:
            return []
        visited = {src_id}
        queue = [(src_id, [])]
        while queue:
            current, path = queue.pop(0)
            if len(path) >= max_depth:
                continue
            for edge in self._adjacency.get(current, []):
                if edge.dst_id == dst_id:
                    return path + [edge]
                if edge.dst_id not in visited:
                    visited.add(edge.dst_id)
                    queue.append((edge.dst_id, path + [edge]))
        return None

    def query(self, node_type: str = "", relation: str = "",
              project_id: str = "", filters: Dict[str, Any] = None) -> List[GraphNode]:
        """Query the graph with filters."""
        results = []
        for node in self._nodes.values():
            if node_type and node.node_type != node_type:
                continue
            if project_id and node.project_id != project_id:
                continue
            if filters:
                match = True
                for key, value in filters.items():
                    if node.properties.get(key) != value:
                        match = False
                        break
                if not match:
                    continue
            results.append(node)
        return results

    def get_stats(self) -> Dict[str, int]:
        """Get graph statistics."""
        node_types = {}
        for node in self._nodes.values():
            node_types[node.node_type] = node_types.get(node.node_type, 0) + 1
        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "node_types": node_types,
        }

    def clear(self):
        """Clear the graph."""
        self._nodes.clear()
        self._edges.clear()
        self._adjacency.clear()
        self._reverse_adjacency.clear()


# Singleton instance
_graph = KnowledgeGraph()


def get_graph() -> KnowledgeGraph:
    """Get the global knowledge graph instance."""
    return _graph
