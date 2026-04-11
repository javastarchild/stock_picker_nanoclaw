# Temporal Semantic Inverse Reinforcement Learning Connected Networks
## TS-IRL-CN — Project Framework & Phased Prototype Plan

**Version:** 0.1 (Framework)
**Status:** Research + Phase 1 in progress

---

## What Is This?

TS-IRL-CN is a framework for representing real-world sensor information and data as
a temporal, semantically-annotated connected network — where **time**, **meaning**,
and **inferred intent** are first-class citizens of the data structure, not
post-hoc annotations on top of raw signals.

The framework addresses three fundamental limitations of current AI systems:

| Limitation | How TS-IRL-CN Addresses It |
|---|---|
| **No physical grounding** — LLMs reason about text about reality, not reality itself | Sensor data → temporal semantic graph → grounded representations |
| **No causal understanding** — models learn correlations, not causes | CaTeRS-style causal edge types (causes/enables/prevents) + IRL attribution |
| **No temporal coherence** — models treat time as metadata, not structure | Time is embedded in the graph topology; semantic meaning evolves with it |

---

## Core Concept

```
Raw sensor stream
        │
        ▼
┌─────────────────────────────────────────────────────┐
│          Temporal Semantic Graph                     │
│                                                      │
│  Nodes: entities, events, agents, states             │
│  Edges: ──temporal──  ──semantic──  ──causal──       │
│  Time:  graph topology evolves continuously          │
│  Meaning: each node/edge carries semantic embedding  │
└─────────────────────────────────────────────────────┘
        │
        ▼
  Semantic Trajectories
  (observed paths through the evolving graph)
        │
        ▼
  Inverse Reinforcement Learning
  (infer: what goal/reward was driving these trajectories?)
        │
        ▼
  Latent Reward Functions
  over the semantic-temporal state space
        │
        ▼
  LLM / MLLM Query Layer
  "What was agent X trying to do between t1 and t2?"
```

---

## Key Components

### 1. Temporal
Time-varying graphs where nodes, edges, and their weights change over time.
Events are ordered, and the semantic meaning of a state depends on *when* it occurs,
not just *what* it is. Uses continuous-time dynamic graph (CTDG) formulations
rather than discrete snapshot sequences.

### 2. Semantic
Meaning-bearing representations: knowledge graphs, event ontologies,
semantic trajectories, and causal/temporal relations between events.
Edge types encode not just structural connection but *why* two nodes are connected
(co-occurrence, causation, enablement, temporal precedence, spatial proximity).

Schema inspired by **CaTeRS** (ACL 2016):
- Temporal edges: `before`, `after`, `overlaps`, `during`
- Causal edges: `causes`, `enables`, `prevents`
- Semantic edges: `isa`, `relatedTo`, `partOf`, `spatial:near`

### 3. Inverse Reinforcement Learning
Given observed trajectories (paths agents took through the semantic-temporal graph),
IRL recovers the latent reward function that explains those choices.
Rather than asking "what will happen next?" (prediction), IRL asks
"what goal was this agent pursuing?" (intent inference).

Key insight: the reward function is defined over the *semantic-temporal graph state*
— not a flat feature vector — making it generalizable across different graph
instances with the same semantic structure.

### 4. Connected Networks
Graph-based structures where nodes (events, concepts, agents, states) are linked
by edges encoding causal, temporal, and semantic relationships.
Supports higher-order connections (hyperedges for multi-agent interactions)
as motivated by PLOS ONE higher-order temporal network prediction.

---

## Research Approach

### Positioning: Three Gaps We Are Targeting

The six-gap analysis from the literature survey identifies the following as the
highest-leverage contribution targets for TS-IRL-CN:

**Gap 1 — No unified temporal+semantic+IRL pipeline** *(primary target)*
No existing library connects temporal GNN → semantic KG embedding → IRL reward recovery.
TS-IRL-CN's core contribution is this integration, with bridging components at each interface.

**Gap 2 — Graph-structured IRL state spaces** *(primary target)*
Standard IRL (MaxEnt, GAIL, AIRL) assumes flat vector state spaces.
TS-IRL-CN formalizes trajectory-over-temporal-graph as the IRL state representation,
with a novel state-aliasing resolution mechanism for semantically similar but
temporally distinct states.

**Gap 5 — Continuous-time semantic reward functions** *(secondary target)*
Reward functions that are time-aware (decay, recurrence, causal attribution)
rather than time-blind averages over discrete episodes.

### Research Strategy

**Stage 1 (Prototype-driven):** Build working prototypes for each component in isolation,
then systematically integrate. This is how the stream_aggregators project was developed:
build and validate each piece before combining.

**Stage 2 (Benchmark-driven):** Evaluate on TGB 2.0 (temporal KG tasks) and
ICEWS/EventKG (semantic event trajectories). Compare against ReaL-TG and MERIT-IRL baselines.

**Stage 3 (Application-driven):** Ground the framework in a concrete real-world domain.
Candidate domains:
- Smart building / IoT sensor networks (natural fit with existing NanoClaw infrastructure)
- Geopolitical event forecasting (ICEWS data, natural semantic-temporal structure)
- Healthcare patient trajectory analysis (PMC 10365613 motivation)

---

## Phased Prototype Development

### Phase 1 — Temporal Semantic Graph Engine
**Goal:** Build the core data structure. No ML yet — pure graph engineering.

**What it does:**
- Ingests a timestamped event stream (sensor readings, text events, etc.)
- Constructs an evolving graph where nodes are entities/events and edges carry
  temporal + semantic + causal type annotations
- Supports: node/edge insertion, temporal snapshots, graph queries,
  semantic similarity search, temporal neighborhood retrieval

**Schema (CaTeRS-inspired):**
```python
Node(id, type, semantic_embedding, first_seen, last_seen, attributes)
Edge(source, target, edge_type, weight, timestamp, valid_from, valid_to)
# edge_type ∈ {before, after, causes, enables, prevents, isa, relatedTo, spatial:near, ...}
```

**Data sources:**
- Synthetic IoT sensor events (local dev, no dependencies)
- EventKG subset (real-world semantic-temporal graph)
- ICEWS coded event data (geopolitical)

**Libraries:** NetworkX + RDFLib (construction), PyG (GNN backbone), PyKEEN (embeddings)

**Deliverable:** `ts_graph.py` — TemporalSemanticGraph class with full CRUD + query API

---

### Phase 2 — Semantic Trajectory Encoder
**Goal:** Represent observed paths through the Phase 1 graph as ML-consumable trajectories.

**What it does:**
- Extracts trajectories (sequences of node-visits with semantic context) from the graph
- Encodes each trajectory step as: (node_embedding, edge_type_vector, temporal_features)
- Handles temporal semantic drift: two semantically similar nodes at different times
  get distinguishable representations (inspired by PNAS 1610686113 finding on
  semantic similarity causing false memory confusion)
- ST-LSTM encoder: combines spatial/semantic + temporal features per step (Paper 7 architecture)

**Key design choice:** Trajectory steps carry both the node's *current* semantic embedding
AND a temporal decay over the node's historical semantic context. This prevents the
"false memory" problem where semantically similar states at different times are aliased.

**Deliverable:** `ts_trajectory.py` — TrajectoryEncoder + TrajectoryDataset

---

### Phase 3 — IRL on Semantic Trajectories *(Core Research)*
**Goal:** Recover latent reward functions from observed trajectory data.

**What it does:**
- Takes a dataset of observed trajectories (Phase 2 output)
- Applies MaxEntropy IRL and AIRL to recover the reward function over
  the semantic-temporal graph state space
- Custom wrapper adapts graph embeddings → flat state vectors for `imitation` library
- Implements MERIT-IRL formulation for online/streaming trajectory setting
  (no waiting for trajectory termination — suitable for real-time sensor streams)

**Novel contribution:** Reward function parameterized over semantic graph structure,
not individual nodes. A reward function learned on EventKG trajectories generalizes
to ICEWS trajectories with the same causal-semantic edge structure.

**Deliverable:** `ts_irl.py` — TemporalSemanticIRL + RewardNet + OnlineIRL

---

### Phase 4 — LLM Integration Layer
**Goal:** Natural language interface over the temporal semantic graph and recovered reward functions.

**What it does:**
- LLM (Claude via Anthropic API) semantically annotates raw sensor events → graph nodes
- LangGraph orchestrates multi-step reasoning over the temporal semantic graph
- Natural language query: "What was agent X trying to do between t1 and t2?"
  → graph traversal + reward attribution + LLM explanation
- Addresses Gap 4: temporal commonsense reasoning improvements via
  structured graph context rather than pure parametric LLM memory

**Architecture:**
```
User query → LLM → graph query plan → temporal graph traversal
           → reward function lookup → causal attribution
           → LLM → natural language answer with temporal reasoning
```

**Deliverable:** `ts_nlq.py` — NaturalLanguageQuery engine over TS-IRL-CN

---

### Phase 5 — MLLM Extension + Real-time Streaming
**Goal:** Live inference of agent goals from multimodal sensor streams.

**What it does:**
- MLLM perception layer: camera + IMU + audio → semantic event → graph node
- Connects to stream_aggregators project (EWMA anomaly detection, sliding window join)
  for real-time sensor preprocessing
- Near-real-time goal inference: as new sensor events arrive, update the
  temporal semantic graph and re-run reward attribution
- Anomaly detection: when observed trajectory diverges from expected reward-optimal path,
  flag as anomaly (unusual agent behavior)

**Integration with existing NanoClaw projects:**
- `stream_aggregators/05_ewma_anomaly/` → real-time sensor preprocessing
- `logic_tools` FOL KB → symbolic causal rules complement the learned IRL reward

**Deliverable:** `ts_realtime.py` — live pipeline from sensor stream to goal inference

---

## Technical Stack

| Component | Library | Version | Notes |
|---|---|---|---|
| Temporal GNN | `torch_geometric` + `torch_geometric_temporal` | Latest | TGB 2.0 for benchmarking |
| Static GNN | `networkx` | 3.x | Graph construction + queries |
| Semantic KG embedding | `pykeen` (TNTComplEx / TimePlex) | Latest | Temporal KG completion |
| IRL core | `imitation` (AIRL/GAIL) | Jan 2025+ | Custom graph wrapper needed |
| Online IRL | MERIT-IRL (arXiv 2410.15612) | Research impl | For streaming setting |
| LLM interface | `anthropic` SDK | Latest | Claude for semantic annotation |
| Agentic reasoning | `langgraph` | Latest | Multi-step graph traversal |
| Graph-LLM retrieval | `llama-index` PropertyGraphIndex | Latest | Structured graph queries |
| RDF/OWL parsing | `rdflib` | 7.x | EventKG + ontology ingestion |
| Trajectory encoding | Custom ST-LSTM (PyTorch) | — | Based on Paper 7 architecture |
| Stream preprocessing | `stream_aggregators/` (local) | — | EWMA + sliding window join |

---

## Prototype Execution Plan

```
Week 1-2:  Phase 1 — TemporalSemanticGraph core data structure + synthetic demo
Week 3-4:  Phase 1 continued — EventKG ingestion, semantic edge types, graph queries
Week 5-6:  Phase 2 — TrajectoryEncoder, ST-LSTM, temporal drift handling
Week 7-8:  Phase 3 — MaxEntIRL + graph wrapper, first reward recovery demo
Week 9-10: Phase 3 continued — MERIT-IRL online version, streaming trajectories
Week 11-12: Phase 4 — LLM annotation layer, NL query interface
Week 13+:  Phase 5 — MLLM integration, real-time demo
```

---

## Gap-to-Contribution Map

| Research Gap | TS-IRL-CN Contribution |
|---|---|
| No unified T+S+IRL pipeline | Core framework: bridging components at each interface |
| Graph-structured IRL state spaces | Novel: trajectory-over-temporal-graph as IRL state; state aliasing resolution |
| Semantic drift in trajectory inference | Temporal decay on semantic similarity scores (Phase 2) |
| LLM temporal reasoning over KGs | Structured graph context injection; LangGraph temporal traversal (Phase 4) |
| Continuous-time semantic reward functions | Time-parameterized reward nets over graph structure (Phase 3) |
| Multimodal IRL over temporal graphs | MLLM perception layer → graph population (Phase 5) |

---

## References

1. [Temporal Semantic Network Analysis (TDS, 2021)](https://towardsdatascience.com/temporal-semantic-network-analysis-bd8869c10f10/)
2. [Higher-Order Temporal Network Prediction (PLOS ONE)](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0323753)
3. [CaTeRS: Causal and Temporal Relation Scheme (ACL 2016)](https://aclanthology.org/W16-1007/)
4. [Social Semantic Knowledge & Hedonic Evaluation (Neuropsychologia)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10365613/)
5. [Temporal Pole Semantic Representations & False Memory (PNAS)](https://www.pnas.org/doi/10.1073/pnas.1610686113)
6. [Occipital-Temporal Semantic + Affective Tuning (Nature Comms 2024)](https://www.nature.com/articles/s41467-024-49073-8)
7. [ST-LSTM: Semantic Trajectory Future Location Prediction (ACM TIST 2022)](https://dl.acm.org/doi/10.1145/3465060)
8. [Thematic Semantic Processing in Language Production (Cortex 2022)](https://www.sciencedirect.com/science/article/abs/pii/S0010945222002416)

### Key SOTA References
- [TGN: Temporal Graph Networks (Twitter Research)](https://github.com/twitter-research/tgn)
- [TGB 2.0 Benchmark (NeurIPS 2024)](https://arxiv.org/html/2406.09639v1)
- [PyKEEN: TNTComplEx / TimePlex (temporal KG)](https://github.com/pykeen/pykeen)
- [imitation: AIRL/GAIL (HumanCompatibleAI)](https://github.com/HumanCompatibleAI/imitation)
- [MERIT-IRL: Online Trajectory IRL (NeurIPS 2024)](https://arxiv.org/abs/2410.15612)
- [ReaL-TG: RL for Temporal Graph Link Forecasting (2025)](https://arxiv.org/abs/2509.00975)
- [GraphRAG (Microsoft)](https://github.com/microsoft/graphrag)
- [GNN-IRL: Graph-structured Intrinsic Reward (Sci Reports 2025)](https://www.nature.com/articles/s41598-025-23769-3)
- [Synergizing Multimodal Temporal KGs (EMNLP 2025)](https://aclanthology.org/2025.emnlp-main.224.pdf)
- [IRL Meets LLM Alignment (AAAI 2025)](https://arxiv.org/html/2507.13158v1)
