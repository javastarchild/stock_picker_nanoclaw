"""
ts_graph.py — Phase 1: Temporal Semantic Graph Engine
TS-IRL-CN Project

TemporalSemanticGraph: core data structure for the TS-IRL-CN framework.

Schema (CaTeRS-inspired):
    Node(id, type, semantic_embedding, first_seen, last_seen, attributes)
    Edge(source, target, edge_type, weight, timestamp, valid_from, valid_to)

Edge types:
    Temporal:  before | after | overlaps | during
    Causal:    causes | enables | prevents
    Semantic:  isa | relatedTo | partOf | spatial:near

Features:
    - Node/edge CRUD with full temporal validity windows
    - Continuous-Time Dynamic Graph (CTDG) formulation
    - Temporal snapshot queries: graph state at arbitrary time T
    - Temporal neighborhood retrieval (k-hop within time window)
    - Semantic similarity search (cosine over stored embeddings)
    - Causal subgraph extraction (causes/enables/prevents chains)
    - Synthetic IoT sensor demo (zero external dependencies)

Dependencies: networkx, numpy (optional for embeddings)
"""

from __future__ import annotations

import math
import time
import random
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from enum import Enum


# ---------------------------------------------------------------------------
# Edge type taxonomy (CaTeRS-inspired)
# ---------------------------------------------------------------------------

class EdgeType(str, Enum):
    # Temporal
    BEFORE        = "before"
    AFTER         = "after"
    OVERLAPS      = "overlaps"
    DURING        = "during"
    # Causal
    CAUSES        = "causes"
    ENABLES       = "enables"
    PREVENTS      = "prevents"
    # Semantic
    ISA           = "isa"
    RELATED_TO    = "relatedTo"
    PART_OF       = "partOf"
    SPATIAL_NEAR  = "spatial:near"
    # Catch-all
    UNKNOWN       = "unknown"

    @classmethod
    def is_causal(cls, et: "EdgeType") -> bool:
        return et in (cls.CAUSES, cls.ENABLES, cls.PREVENTS)

    @classmethod
    def is_temporal(cls, et: "EdgeType") -> bool:
        return et in (cls.BEFORE, cls.AFTER, cls.OVERLAPS, cls.DURING)

    @classmethod
    def is_semantic(cls, et: "EdgeType") -> bool:
        return et in (cls.ISA, cls.RELATED_TO, cls.PART_OF, cls.SPATIAL_NEAR)


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """
    A node in the Temporal Semantic Graph.

    Parameters
    ----------
    id : str
        Unique identifier (e.g. "sensor_42", "event_open_door_001")
    node_type : str
        Ontological category: "sensor", "event", "agent", "state", "concept"
    semantic_embedding : list[float] | None
        Dense vector representation (any dimensionality).
        None → embedding not yet computed.
    first_seen : float
        Unix timestamp of first observation.
    last_seen : float
        Unix timestamp of most recent observation.
    attributes : dict
        Arbitrary key-value metadata (location, unit, sensor_id, …)
    """
    id: str
    node_type: str
    semantic_embedding: Optional[List[float]] = None
    first_seen: float = 0.0
    last_seen: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)

    def update_seen(self, timestamp: float) -> None:
        if self.first_seen == 0.0 or timestamp < self.first_seen:
            self.first_seen = timestamp
        if timestamp > self.last_seen:
            self.last_seen = timestamp

    def is_active_at(self, t: float) -> bool:
        """True if this node existed at time t."""
        return self.first_seen <= t <= self.last_seen

    def __repr__(self) -> str:
        emb_str = f"emb[{len(self.semantic_embedding)}]" if self.semantic_embedding else "no-emb"
        return (f"Node(id={self.id!r}, type={self.node_type!r}, {emb_str}, "
                f"t=[{self.first_seen:.1f}, {self.last_seen:.1f}])")


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    """
    A directed, time-stamped, typed edge.

    Parameters
    ----------
    source : str        Source node id
    target : str        Target node id
    edge_type : EdgeType
    weight : float      Relationship strength / confidence (0–1)
    timestamp : float   When this relationship was observed / created
    valid_from : float  Start of validity window
    valid_to : float    End of validity window (math.inf = open-ended)
    attributes : dict   Extra metadata
    """
    source: str
    target: str
    edge_type: EdgeType
    weight: float = 1.0
    timestamp: float = 0.0
    valid_from: float = 0.0
    valid_to: float = math.inf
    attributes: Dict[str, Any] = field(default_factory=dict)

    @property
    def edge_id(self) -> str:
        """Stable string key for this edge."""
        return f"{self.source}→{self.edge_type.value}→{self.target}@{self.timestamp:.3f}"

    def is_valid_at(self, t: float) -> bool:
        """True if this edge is temporally valid at time t."""
        return self.valid_from <= t <= self.valid_to

    def __repr__(self) -> str:
        return (f"Edge({self.source!r} --[{self.edge_type.value}, w={self.weight:.2f}]--> "
                f"{self.target!r}, valid=[{self.valid_from:.1f}, "
                f"{'∞' if self.valid_to == math.inf else f'{self.valid_to:.1f}'}])")


# ---------------------------------------------------------------------------
# GraphSnapshot — read-only view of the graph at a point in time
# ---------------------------------------------------------------------------

@dataclass
class GraphSnapshot:
    """Immutable view of the graph at a specific timestamp."""
    timestamp: float
    nodes: Dict[str, Node]
    edges: List[Edge]

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def __repr__(self) -> str:
        return (f"GraphSnapshot(t={self.timestamp:.1f}, "
                f"nodes={self.node_count}, edges={self.edge_count})")


# ---------------------------------------------------------------------------
# TemporalSemanticGraph — main class
# ---------------------------------------------------------------------------

class TemporalSemanticGraph:
    """
    Continuous-Time Dynamic Graph (CTDG) with semantic and causal edge types.

    Core operations
    ---------------
    add_node(...)          — insert or update a node
    add_edge(...)          — insert a typed temporal edge
    snapshot(t)            — read-only graph view at time t
    temporal_neighbors(id, t, radius, k_hops) — nodes reachable within Δt
    semantic_search(query_embedding, top_k, t) — cosine-nearest nodes
    causal_chain(start_id, direction, t)        — causes/enables/prevents paths
    trajectory(node_ids, timestamps)           — semantic trajectory object
    stats()                                    — graph summary statistics
    """

    def __init__(self, name: str = "TSGraph") -> None:
        self.name = name
        self._nodes: Dict[str, Node] = {}
        self._edges: List[Edge] = []
        # Secondary index: source_id → list of edge indices
        self._out_edges: Dict[str, List[int]] = {}
        # Secondary index: target_id → list of edge indices
        self._in_edges: Dict[str, List[int]] = {}

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def add_node(
        self,
        node_id: str,
        node_type: str,
        timestamp: float,
        semantic_embedding: Optional[List[float]] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Node:
        """
        Insert a new node or update an existing one.

        If the node already exists, merges attributes, updates last_seen,
        and replaces the embedding if a new one is provided.
        """
        if node_id in self._nodes:
            node = self._nodes[node_id]
            node.update_seen(timestamp)
            if semantic_embedding is not None:
                node.semantic_embedding = semantic_embedding
            if attributes:
                node.attributes.update(attributes)
        else:
            node = Node(
                id=node_id,
                node_type=node_type,
                semantic_embedding=semantic_embedding,
                first_seen=timestamp,
                last_seen=timestamp,
                attributes=attributes or {},
            )
            self._nodes[node_id] = node
        return node

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        """Remove node and all incident edges."""
        if node_id not in self._nodes:
            return False
        del self._nodes[node_id]
        # Remove edges
        self._edges = [e for e in self._edges
                       if e.source != node_id and e.target != node_id]
        self._rebuild_edge_indices()
        return True

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: EdgeType,
        timestamp: float,
        weight: float = 1.0,
        valid_from: Optional[float] = None,
        valid_to: float = math.inf,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Edge:
        """
        Insert a directed typed edge.

        Auto-creates stub nodes if they don't exist (type='unknown').
        valid_from defaults to timestamp if not supplied.
        """
        if source not in self._nodes:
            self.add_node(source, "unknown", timestamp)
        if target not in self._nodes:
            self.add_node(target, "unknown", timestamp)

        # Update node last_seen
        self._nodes[source].update_seen(timestamp)
        self._nodes[target].update_seen(timestamp)

        edge = Edge(
            source=source,
            target=target,
            edge_type=edge_type,
            weight=weight,
            timestamp=timestamp,
            valid_from=valid_from if valid_from is not None else timestamp,
            valid_to=valid_to,
            attributes=attributes or {},
        )
        idx = len(self._edges)
        self._edges.append(edge)

        self._out_edges.setdefault(source, []).append(idx)
        self._in_edges.setdefault(target, []).append(idx)
        return edge

    def get_edges(
        self,
        source: Optional[str] = None,
        target: Optional[str] = None,
        edge_type: Optional[EdgeType] = None,
        at_time: Optional[float] = None,
    ) -> List[Edge]:
        """Filter edges by any combination of source, target, type, time."""
        result = []
        indices: Optional[List[int]] = None

        if source is not None:
            indices = self._out_edges.get(source, [])
        elif target is not None:
            indices = self._in_edges.get(target, [])

        candidates = ([self._edges[i] for i in indices]
                      if indices is not None else self._edges)

        for e in candidates:
            if source is not None and e.source != source:
                continue
            if target is not None and e.target != target:
                continue
            if edge_type is not None and e.edge_type != edge_type:
                continue
            if at_time is not None and not e.is_valid_at(at_time):
                continue
            result.append(e)
        return result

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self, t: float) -> GraphSnapshot:
        """Return a read-only view of the graph as it existed at time t."""
        active_nodes = {nid: n for nid, n in self._nodes.items()
                        if n.is_active_at(t)}
        active_edges = [e for e in self._edges
                        if e.is_valid_at(t)
                        and e.source in active_nodes
                        and e.target in active_nodes]
        return GraphSnapshot(timestamp=t, nodes=active_nodes, edges=active_edges)

    # ------------------------------------------------------------------
    # Temporal neighborhood
    # ------------------------------------------------------------------

    def temporal_neighbors(
        self,
        node_id: str,
        t: float,
        time_radius: float = math.inf,
        k_hops: int = 1,
        edge_types: Optional[Sequence[EdgeType]] = None,
    ) -> Dict[str, Node]:
        """
        BFS from node_id following edges valid within [t - time_radius, t + time_radius].

        Parameters
        ----------
        node_id     : starting node
        t           : reference timestamp
        time_radius : only traverse edges with |timestamp - t| ≤ time_radius
        k_hops      : maximum BFS depth
        edge_types  : restrict to these edge types (None = all)

        Returns
        -------
        Dict[node_id, Node] of reachable neighbors (excluding start node)
        """
        if node_id not in self._nodes:
            return {}

        visited: Dict[str, Node] = {}
        frontier = {node_id}
        t_lo, t_hi = t - time_radius, t + time_radius

        for _ in range(k_hops):
            next_frontier: set[str] = set()
            for nid in frontier:
                for e in self._edges:
                    if e.source != nid:
                        continue
                    if t_lo > e.timestamp or e.timestamp > t_hi:
                        continue
                    if edge_types and e.edge_type not in edge_types:
                        continue
                    if e.target not in visited and e.target != node_id:
                        if e.target in self._nodes:
                            visited[e.target] = self._nodes[e.target]
                            next_frontier.add(e.target)
            frontier = next_frontier - set(visited.keys())
            if not frontier:
                break

        return visited

    # ------------------------------------------------------------------
    # Semantic similarity search
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def semantic_search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        at_time: Optional[float] = None,
        node_type_filter: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """
        Find nodes whose semantic_embedding is closest to query_embedding.

        Returns list of (node_id, cosine_similarity) sorted descending.
        Nodes without embeddings are skipped.
        """
        scores: List[Tuple[str, float]] = []
        for nid, node in self._nodes.items():
            if at_time is not None and not node.is_active_at(at_time):
                continue
            if node_type_filter and node.node_type != node_type_filter:
                continue
            if node.semantic_embedding is None:
                continue
            sim = self._cosine(query_embedding, node.semantic_embedding)
            scores.append((nid, sim))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]

    # ------------------------------------------------------------------
    # Causal chain extraction
    # ------------------------------------------------------------------

    def causal_chain(
        self,
        start_id: str,
        direction: str = "forward",
        t: Optional[float] = None,
        max_depth: int = 6,
    ) -> List[List[str]]:
        """
        Extract causal paths (causes / enables / prevents) from start_id.

        Parameters
        ----------
        start_id  : origin node
        direction : "forward" (start causes others) | "backward" (others cause start)
        t         : if given, restrict to edges valid at t
        max_depth : maximum chain length

        Returns
        -------
        List of paths; each path is a list of node_ids from start to leaf.
        """
        causal_types = {EdgeType.CAUSES, EdgeType.ENABLES, EdgeType.PREVENTS}
        paths: List[List[str]] = []

        def dfs(current: str, path: List[str], depth: int) -> None:
            if depth >= max_depth:
                if len(path) > 1:
                    paths.append(list(path))
                return

            if direction == "forward":
                candidates = self.get_edges(source=current, edge_type=None, at_time=t)
            else:
                candidates = self.get_edges(target=current, edge_type=None, at_time=t)

            causal = [e for e in candidates if e.edge_type in causal_types]
            if not causal:
                if len(path) > 1:
                    paths.append(list(path))
                return

            for e in causal:
                nxt = e.target if direction == "forward" else e.source
                if nxt not in path:  # avoid cycles
                    path.append(nxt)
                    dfs(nxt, path, depth + 1)
                    path.pop()

        dfs(start_id, [start_id], 0)
        return paths

    # ------------------------------------------------------------------
    # Semantic trajectory
    # ------------------------------------------------------------------

    def trajectory(
        self,
        node_ids: List[str],
        timestamps: List[float],
    ) -> "SemanticTrajectory":
        """
        Construct a SemanticTrajectory from an ordered sequence of node visits.
        """
        if len(node_ids) != len(timestamps):
            raise ValueError("node_ids and timestamps must have equal length")
        steps = []
        for nid, t in zip(node_ids, timestamps):
            node = self._nodes.get(nid)
            if node is None:
                raise KeyError(f"Node {nid!r} not found in graph")
            # Collect outgoing edges at this time step
            edges_at_t = self.get_edges(source=nid, at_time=t)
            steps.append(TrajectoryStep(node=node, timestamp=t, edges=edges_at_t))
        return SemanticTrajectory(steps=steps, graph_name=self.name)

    # ------------------------------------------------------------------
    # Utility / stats
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Return summary statistics about the graph."""
        node_types: Dict[str, int] = {}
        edge_types: Dict[str, int] = {}
        nodes_with_emb = 0

        for n in self._nodes.values():
            node_types[n.node_type] = node_types.get(n.node_type, 0) + 1
            if n.semantic_embedding:
                nodes_with_emb += 1

        for e in self._edges:
            et = e.edge_type.value
            edge_types[et] = edge_types.get(et, 0) + 1

        timestamps = [e.timestamp for e in self._edges]

        return {
            "graph_name": self.name,
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "nodes_with_embedding": nodes_with_emb,
            "node_types": node_types,
            "edge_type_counts": edge_types,
            "time_range": (min(timestamps), max(timestamps)) if timestamps else (0, 0),
        }

    def _rebuild_edge_indices(self) -> None:
        """Rebuild out_edges / in_edges secondary indices."""
        self._out_edges.clear()
        self._in_edges.clear()
        for i, e in enumerate(self._edges):
            self._out_edges.setdefault(e.source, []).append(i)
            self._in_edges.setdefault(e.target, []).append(i)

    def __repr__(self) -> str:
        return (f"TemporalSemanticGraph(name={self.name!r}, "
                f"nodes={len(self._nodes)}, edges={len(self._edges)})")


# ---------------------------------------------------------------------------
# SemanticTrajectory — ordered node-visit sequence with context
# ---------------------------------------------------------------------------

@dataclass
class TrajectoryStep:
    """One step in a semantic trajectory."""
    node: Node
    timestamp: float
    edges: List[Edge]           # outgoing edges active at this step

    @property
    def embedding(self) -> Optional[List[float]]:
        return self.node.semantic_embedding

    def __repr__(self) -> str:
        return (f"Step(node={self.node.id!r}, t={self.timestamp:.1f}, "
                f"edges={len(self.edges)})")


@dataclass
class SemanticTrajectory:
    """
    An ordered sequence of TrajectorySteps through the temporal semantic graph.

    This is the input to Phase 2 (TrajectoryEncoder) and Phase 3 (IRL).
    """
    steps: List[TrajectoryStep]
    graph_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return len(self.steps)

    @property
    def duration(self) -> float:
        if len(self.steps) < 2:
            return 0.0
        return self.steps[-1].timestamp - self.steps[0].timestamp

    @property
    def node_sequence(self) -> List[str]:
        return [s.node.id for s in self.steps]

    @property
    def timestamp_sequence(self) -> List[float]:
        return [s.timestamp for s in self.steps]

    def has_embeddings(self) -> bool:
        return all(s.embedding is not None for s in self.steps)

    def __repr__(self) -> str:
        return (f"SemanticTrajectory(len={self.length}, "
                f"duration={self.duration:.1f}s, "
                f"nodes={self.node_sequence})")


# ---------------------------------------------------------------------------
# Synthetic IoT demo — zero external dependencies
# ---------------------------------------------------------------------------

def _make_embedding(seed: str, dim: int = 16) -> List[float]:
    """
    Deterministic pseudo-random embedding from a seed string.
    Uses SHA-256 → float normalisation. Good enough for structural tests.
    """
    h = hashlib.sha256(seed.encode()).digest()
    vals: List[float] = []
    for i in range(0, min(len(h), dim * 2), 2):
        v = ((h[i] << 8) | h[i + 1]) / 65535.0 * 2 - 1  # in [-1, 1]
        vals.append(v)
    # Pad if needed
    while len(vals) < dim:
        vals.append(0.0)
    return vals[:dim]


class SyntheticIoTSimulator:
    """
    Generates a synthetic IoT sensor event stream and populates a
    TemporalSemanticGraph for local dev / testing.

    Scenario: smart-building with motion sensors, door contacts, and
    HVAC state. Agent (person) moves through rooms; doors open/close;
    HVAC responds to occupancy.

    Graph populated:
        Nodes: rooms, sensors, HVAC zones, a person agent
        Edges:
            spatial:near   — sensors near rooms
            causes         — motion event causes door open
            enables        — door open enables zone entry
            before/after   — temporal ordering of events
            isa            — sensor isa physical_device
    """

    ROOMS = ["lobby", "corridor_A", "office_101", "kitchen", "server_room"]
    SENSORS = {
        "motion_lobby":    ("motion",  "lobby"),
        "motion_corr_A":   ("motion",  "corridor_A"),
        "motion_office":   ("motion",  "office_101"),
        "door_lobby":      ("contact", "lobby"),
        "door_office":     ("contact", "office_101"),
        "hvac_zone_A":     ("hvac",    "corridor_A"),
        "hvac_zone_B":     ("hvac",    "office_101"),
    }

    def __init__(self, seed: int = 42) -> None:
        random.seed(seed)
        self.graph = TemporalSemanticGraph(name="SmartBuilding_IoT_Demo")

    def build(self, n_events: int = 40, t_start: float = 1_000_000.0) -> TemporalSemanticGraph:
        """Populate the graph with synthetic IoT events."""
        g = self.graph
        t = t_start

        # -- Static nodes: rooms --
        for room in self.ROOMS:
            g.add_node(room, "room", t,
                       semantic_embedding=_make_embedding(f"room:{room}"),
                       attributes={"building": "HQ", "floor": 1})

        # -- Static nodes: sensors --
        for sid, (stype, room) in self.SENSORS.items():
            g.add_node(sid, "sensor", t,
                       semantic_embedding=_make_embedding(f"sensor:{sid}:{stype}"),
                       attributes={"sensor_type": stype, "room": room})
            # sensor isa physical_device
            g.add_node("physical_device", "concept", t,
                       semantic_embedding=_make_embedding("concept:physical_device"))
            g.add_edge(sid, "physical_device", EdgeType.ISA, t, weight=1.0)
            # sensor spatial:near its room
            g.add_edge(sid, room, EdgeType.SPATIAL_NEAR, t, weight=0.9)

        # -- Agent node: person --
        g.add_node("person_001", "agent", t,
                   semantic_embedding=_make_embedding("agent:person_001"),
                   attributes={"role": "employee", "badge": "P001"})

        # -- Dynamic events: person moves through building --
        route = ["lobby", "corridor_A", "office_101", "kitchen",
                 "office_101", "corridor_A", "lobby"]
        prev_room: Optional[str] = None
        prev_event: Optional[str] = None

        for step_i, room in enumerate(route * (n_events // len(route) + 1)):
            if step_i >= n_events:
                break
            t += random.uniform(30, 180)  # 30s–3min between events

            # Motion event
            motion_sensor = next(
                (sid for sid, (stype, r) in self.SENSORS.items()
                 if stype == "motion" and r == room), None
            )
            if motion_sensor is None:
                motion_sensor = f"motion_{room}"

            event_id = f"evt_motion_{room}_{step_i}"
            g.add_node(event_id, "event", t,
                       semantic_embedding=_make_embedding(f"event:motion:{room}:{step_i}"),
                       attributes={"room": room, "sensor": motion_sensor,
                                   "value": 1, "unit": "bool"})

            # sensor causes event
            g.add_edge(motion_sensor, event_id, EdgeType.CAUSES, t, weight=0.95)

            # person → event (agent observed)
            g.add_edge("person_001", event_id, EdgeType.ENABLES, t, weight=0.8,
                       attributes={"role": "subject"})

            # temporal ordering: prev_event before this event
            if prev_event:
                g.add_edge(prev_event, event_id, EdgeType.BEFORE, t, weight=1.0)

            # Room transition: door open event
            if prev_room and prev_room != room:
                door_id = f"evt_door_open_{prev_room}_to_{room}_{step_i}"
                g.add_node(door_id, "event", t,
                           semantic_embedding=_make_embedding(f"event:door:{prev_room}→{room}"),
                           attributes={"from": prev_room, "to": room, "action": "open"})
                # motion enables door open
                g.add_edge(event_id, door_id, EdgeType.ENABLES, t, weight=0.85)
                # door open enables room entry
                g.add_edge(door_id, room, EdgeType.ENABLES, t + 1, weight=0.9)

            # HVAC: occupancy causes hvac state change
            hvac_sensor = next(
                (sid for sid, (stype, r) in self.SENSORS.items()
                 if stype == "hvac" and r == room), None
            )
            if hvac_sensor and random.random() > 0.6:
                hvac_evt = f"evt_hvac_{room}_{step_i}"
                g.add_node(hvac_evt, "event", t + 5,
                           semantic_embedding=_make_embedding(f"event:hvac:{room}:{step_i}"),
                           attributes={"room": room, "action": "activate",
                                       "trigger": "occupancy"})
                g.add_edge(event_id, hvac_evt, EdgeType.CAUSES, t + 5, weight=0.7)
                g.add_edge(hvac_sensor, hvac_evt, EdgeType.CAUSES, t + 5, weight=0.9)

            prev_room = room
            prev_event = event_id

        return g


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _fmt_sep(title: str) -> str:
    return f"\n{'─'*60}\n  {title}\n{'─'*60}"


def demo() -> None:
    print("=" * 60)
    print("  TS-IRL-CN  Phase 1 — TemporalSemanticGraph Demo")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Build synthetic smart-building graph
    # ------------------------------------------------------------------
    print(_fmt_sep("1. Building Synthetic IoT Graph"))
    sim = SyntheticIoTSimulator(seed=42)
    g = sim.build(n_events=35)
    print(g)

    s = g.stats()
    print(f"\nNode types:      {s['node_types']}")
    print(f"Edge type counts:{s['edge_type_counts']}")
    print(f"Time range:      [{s['time_range'][0]:.0f}, {s['time_range'][1]:.0f}] "
          f"(span {s['time_range'][1]-s['time_range'][0]:.0f}s)")
    print(f"Nodes with emb:  {s['nodes_with_embedding']} / {s['node_count']}")

    # ------------------------------------------------------------------
    # 2. Temporal snapshot
    # ------------------------------------------------------------------
    print(_fmt_sep("2. Temporal Snapshot"))
    t_mid = (s['time_range'][0] + s['time_range'][1]) / 2
    snap = g.snapshot(t_mid)
    print(f"Snapshot at t={t_mid:.0f}: {snap}")

    # ------------------------------------------------------------------
    # 3. Temporal neighborhood from person_001
    # ------------------------------------------------------------------
    print(_fmt_sep("3. Temporal Neighborhood  (person_001, k=2, radius=300s)"))
    t_query = s['time_range'][0] + 600
    neighbors = g.temporal_neighbors("person_001", t=t_query, time_radius=300, k_hops=2)
    print(f"Query t={t_query:.0f}")
    for nid, node in list(neighbors.items())[:8]:
        print(f"  {nid:45s}  type={node.node_type}")
    if len(neighbors) > 8:
        print(f"  … and {len(neighbors)-8} more")

    # ------------------------------------------------------------------
    # 4. Semantic similarity search
    # ------------------------------------------------------------------
    print(_fmt_sep("4. Semantic Search  (query: 'motion event in lobby')"))
    query_emb = _make_embedding("event:motion:lobby:0", dim=16)
    hits = g.semantic_search(query_emb, top_k=6)
    for nid, score in hits:
        node = g.get_node(nid)
        print(f"  {nid:45s}  cos={score:.4f}  type={node.node_type}")

    # ------------------------------------------------------------------
    # 5. Causal chain from first motion event
    # ------------------------------------------------------------------
    print(_fmt_sep("5. Causal Chain  (forward from motion_lobby)"))
    chains = g.causal_chain("motion_lobby", direction="forward", max_depth=4)
    if chains:
        for chain in chains[:5]:
            print("  " + " → ".join(chain))
    else:
        # Try from first event node
        first_evt = next((nid for nid in g._nodes if nid.startswith("evt_motion_lobby")), None)
        if first_evt:
            chains = g.causal_chain(first_evt, direction="forward", max_depth=4)
            for chain in chains[:5]:
                print("  " + " → ".join(chain))
        else:
            print("  (no causal chains found from lobby sensor)")

    # ------------------------------------------------------------------
    # 6. Build a semantic trajectory for person_001
    # ------------------------------------------------------------------
    print(_fmt_sep("6. Semantic Trajectory  (person_001 path)"))
    # Find motion events in order
    motion_events = sorted(
        [(nid, n.first_seen) for nid, n in g._nodes.items()
         if n.node_type == "event" and "motion" in nid],
        key=lambda x: x[1]
    )[:6]

    if motion_events:
        node_ids = [m[0] for m in motion_events]
        timestamps = [m[1] for m in motion_events]
        traj = g.trajectory(node_ids, timestamps)
        print(traj)
        print(f"  Steps:     {traj.length}")
        print(f"  Duration:  {traj.duration:.1f}s")
        print(f"  Has embs:  {traj.has_embeddings()}")
        print("\n  Step sequence:")
        for step in traj.steps:
            print(f"    t={step.timestamp:.0f}  {step.node.id:40s}  "
                  f"outgoing_edges={len(step.edges)}")

    # ------------------------------------------------------------------
    # 7. Manual graph construction — small causal example
    # ------------------------------------------------------------------
    print(_fmt_sep("7. Manual Graph  (CaTeRS-style causal example)"))
    mg = TemporalSemanticGraph(name="CaTeRS_Example")
    t0 = 0.0

    # Events
    for eid, etype in [("rain_starts", "weather_event"),
                       ("road_wet",    "state"),
                       ("car_skids",   "accident_event"),
                       ("traffic_jam", "state"),
                       ("driver_brakes", "action")]:
        mg.add_node(eid, etype, t0,
                    semantic_embedding=_make_embedding(f"ex:{eid}"))

    mg.add_edge("rain_starts",   "road_wet",     EdgeType.CAUSES,  1.0, weight=0.95)
    mg.add_edge("road_wet",      "car_skids",    EdgeType.ENABLES, 2.0, weight=0.80)
    mg.add_edge("driver_brakes", "car_skids",    EdgeType.PREVENTS,2.0, weight=0.70)
    mg.add_edge("car_skids",     "traffic_jam",  EdgeType.CAUSES,  3.0, weight=0.90)
    mg.add_edge("rain_starts",   "road_wet",     EdgeType.BEFORE,  1.0, weight=1.0)
    mg.add_edge("road_wet",      "car_skids",    EdgeType.BEFORE,  2.0, weight=1.0)
    mg.add_edge("car_skids",     "traffic_jam",  EdgeType.BEFORE,  3.0, weight=1.0)

    print(mg)
    print("\n  Causal chains from rain_starts (forward):")
    for chain in mg.causal_chain("rain_starts", direction="forward"):
        print("   ", " → ".join(chain))

    print("\n  Causal chains to traffic_jam (backward):")
    for chain in mg.causal_chain("traffic_jam", direction="backward"):
        print("   ", " → ".join(chain))

    print("\n  Edges at t=2.0:")
    for e in mg.get_edges(at_time=2.0):
        print(f"    {e}")

    print("\n✓ Phase 1 demo complete.")
    print("  Next: Phase 2 — ts_trajectory.py (ST-LSTM TrajectoryEncoder)\n")


if __name__ == "__main__":
    demo()
