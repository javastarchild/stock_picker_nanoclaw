# Logic Tools — Development Plan

## What Was Built (Session 1, Apr 6 2026)

### Core FOL Engine (`fol_engine.py`)
- **Terms**: `Variable(?X)`, `Constant`, `FunctionTerm(f, args)`
- **Formulas**: `Atom`, `Not`, `And`, `Or`, `Implies`, `ForAll`, `Exists`
- **Substitution**: full variable binding with chained lookup
- **Unification**: Robinson's algorithm with occurs check (`unify` for terms, `unify_atoms` for atoms)
- **Horn Clauses**: `head :- body1, body2, ...` with variable renaming for fresh copies
- **FOLKnowledgeBase**: `tell()`, `ask()`, `ask_yes_no()`, `forward_chain()`
- **SLD Backward Chaining**: Prolog-style resolution with depth limit
- **Forward Chaining**: saturation of ground facts from rules
- **Parser** (`FOLParser`): parses `predicate(?X, const) :- ...` clause strings

### Cyc Ontology Interface (`cyc_index.py`)
- Loads `cyc_index.json` (built by `build_cyc_index.py`)
- `all_genls(concept)`: transitive superclass closure
- `is_isa(individual, collection)`: inheritance-aware instance check
- `search_predicates(query)`: name search across Cyc predicates
- **BC hook**: `bc_solve_atom()` handles `genls/2` and `isa/2` queries against Cyc

### Cyc Index Builder (`build_cyc_index.py`)
- Streams `open-cyc.rdf.ZIP` using ElementTree iterparse
- Handles invalid XML chars (`\x1a` control bytes in source)
- Extracts: predicates+arities, `genls` hierarchy, `rdf:type` assignments
- Outputs compact `cyc_index.json`

**Test run (20k limit)**: 334 predicates, 8,156 genls concepts, 4,460 typed individuals

### REST API (`app.py`)
- `POST /fact`, `POST /rule`, `POST /clause` — assert to KB
- `POST /query` — backward chain, returns `{answers, proved}`
- `POST /forward` — run forward chaining
- `GET /facts`, `GET /rules`, `GET /stats`
- `GET /ontology/stats`, `GET /ontology/predicate/<name>`, `GET /ontology/search`
- `POST /ontology/genls`, `POST /ontology/isa`

---

## Next Steps (Session 2+)

### Priority 1: Fix Mount & Deploy Files
1. Fix `logic_tools` mount to be writable (add `"readonly": false` to container_config)
2. Copy staging files from `stock_picker/logic_tools_staging/` → `logic_tools/`
3. Run full Cyc index build:
   ```bash
   cd /home/javastarchild/logic_tools
   python build_cyc_index.py --rdf resources/open-cyc.rdf.ZIP \
     --out resources/cyc_index.json --limit 200000
   ```
   Expected: ~11,700 predicates, 50k+ genls pairs, ~10 minutes

### Priority 2: Engine Improvements
- **Tabling / Memoization**: Cache `(goal, subst)` results to prevent infinite loops
  in recursive rules (e.g., transitive Cyc hierarchies). This is the #1 issue.
- **Negation-as-Failure (NAF)**: `not(atom)` in rule bodies — succeed if atom
  has no proof. Required for many agent routing rules.
- **Arithmetic builtins**: `is(?X, +(?A, ?B))`, comparison `<, >, =:=`

### Priority 3: Agent Orchestration Vocabulary
Use Cyc concepts to define the agent routing knowledge base:

```prolog
% Agent capabilities (Cyc-backed)
can_handle(andy, task_type(?T)) :- isa(?T, ProgrammingTask).
can_handle(andy, task_type(?T)) :- isa(?T, LogicReasoning).

% Routing rules
route_to(andy, ?Task) :- can_handle(andy, task_type(?Task)), not(requires_web(?Task)).
route_to(search_agent, ?Task) :- requires_web(?Task).

% Task classification using Cyc hierarchy
requires_web(?Task) :- isa(?Task, InternetSearchTask).
```

Cyc predicates to leverage:
- `IntelligentAgent` — all agents are instances of this
- `performedBy` — who performs an action
- `agentHired` — delegation
- `Action`, `Event` — task types
- `capableOf` — capability predicate

### Priority 4: UI Enhancements
- Update `frontend/index.html` to show Cyc predicate autocomplete
- Add query explanation view (show proof trace)
- Add genls/isa browser panel

### Priority 5: Create GitHub Repo
User to create `javastarchild/logic_tools` and push from `~/logic_tools`

---

## Architecture Notes

### Why Bespoke (not SWI-Prolog or pyDatalog)
- Agent orchestration needs custom predicates + Python-native integration
- No Java dependency (owlready2/Pellet), no separate server (SWI-Prolog)
- pyDatalog is unmaintained since 2019
- We have full control to extend for agent-specific features

### Cyc Integration Strategy
- OpenCyc is used as a **vocabulary source** and **background ontology**
- We don't try to load all of Cyc's axioms (too many, many are context-specific)
- Instead: use Cyc's `genls` hierarchy for type inheritance in our rules
- Custom rules (agent routing, task classification) are written in our Horn clause format
- Cyc term names used directly as constants (e.g., `IntelligentAgent`, `ComputerProgram`)

### Staging Area
Files are in `stock_picker/logic_tools_staging/` pending writable mount:
- `fol_engine.py`   — FOL engine (tested ✓)
- `cyc_index.py`    — Cyc ontology interface (tested ✓)
- `build_cyc_index.py` — index builder (tested ✓)
- `app.py`          — REST API (new endpoints)
- `requirements.txt` — flask, flask-cors, sympy
- `docker-compose.yml` — ports: backend 5050, frontend 8091
