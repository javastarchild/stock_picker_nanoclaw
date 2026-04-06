"""
Cyc Ontology Interface
======================
Loads the compact cyc_index.json (produced by build_cyc_index.py) and
provides:

  1. Predicate lookup: arity, arg type constraints, human name
  2. Concept hierarchy: genls (subclass), isa (instance-of)
  3. Transitive closure of genls for inheritance reasoning
  4. Backward chaining hook: handles genls/isa/subclass queries against
     the Cyc knowledge base, integrated into FOLKnowledgeBase._bc_solve

The index JSON has this shape:
  {
    "predicates": {
        "isa": {"arity": 2, "label": "Is a"},
        "genls": {"arity": 2, "label": "Generalizations"},
        ...
    },
    "genls": {
        "Dog": ["Animal", "DomesticatedAnimal"],
        ...
    },
    "types": {
        "Socrates": ["Person", "Human"],
        ...
    }
  }
"""

from __future__ import annotations
import json
import os
from typing import Dict, Iterator, List, Optional, Set

from fol_engine import (
    Atom, Constant, Variable, Substitution, EMPTY_SUBST,
    unify, unify_atoms, FAILURE,
)


class CycOntology:
    """
    In-memory Cyc ontology index.

    After calling load(), provides:
      - predicate_info(name): arity + label
      - genls_parents(concept): immediate superclasses
      - all_genls(concept): transitive superclasses
      - isa_types(individual): direct types asserted in index
    """

    def __init__(self):
        self.predicates: Dict[str, dict] = {}    # name → {arity, label, ...}
        self.genls: Dict[str, List[str]] = {}     # concept → [parent, ...]
        self.types: Dict[str, List[str]] = {}     # individual → [type, ...]
        self._genls_cache: Dict[str, Set[str]] = {}
        self._loaded = False

    def load(self, index_path: str) -> None:
        if not os.path.exists(index_path):
            raise FileNotFoundError(
                f"Cyc index not found at {index_path}. "
                "Run build_cyc_index.py to generate it first."
            )
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.predicates = data.get("predicates", {})
        self.genls = data.get("genls", {})
        self.types = data.get("types", {})
        self._genls_cache.clear()
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # Hierarchy queries
    # ------------------------------------------------------------------

    def genls_parents(self, concept: str) -> List[str]:
        """Immediate superclasses of concept in Cyc."""
        return self.genls.get(concept, [])

    def all_genls(self, concept: str, visited: Optional[Set[str]] = None) -> Set[str]:
        """Transitive superclasses of concept (not including concept itself)."""
        if concept in self._genls_cache:
            return self._genls_cache[concept]
        if visited is None:
            visited = set()
        if concept in visited:
            return set()
        visited.add(concept)
        result: Set[str] = set()
        for parent in self.genls.get(concept, []):
            result.add(parent)
            result |= self.all_genls(parent, visited)
        self._genls_cache[concept] = result
        return result

    def isa_types(self, individual: str) -> List[str]:
        """Types directly asserted for individual in the index."""
        return self.types.get(individual, [])

    def is_isa(self, individual: str, collection: str) -> bool:
        """
        True if individual is an instance of collection (or any subcollection).
        Uses: direct types + transitive genls.
        """
        direct = self.isa_types(individual)
        for t in direct:
            if t == collection:
                return True
            if collection in self.all_genls(t):
                return True
        return False

    def is_genls(self, sub: str, sup: str) -> bool:
        """True if sub is a (transitive) subclass of sup."""
        if sub == sup:
            return True
        return sup in self.all_genls(sub)

    # ------------------------------------------------------------------
    # Predicate info
    # ------------------------------------------------------------------

    def predicate_info(self, name: str) -> Optional[dict]:
        return self.predicates.get(name)

    def validate_arity(self, predicate: str, n_args: int) -> Optional[str]:
        """Return error string if arity wrong, None if ok or unknown."""
        info = self.predicates.get(predicate)
        if info is None:
            return None  # unknown predicate — don't block
        expected = info.get("arity")
        if expected is not None and expected != n_args:
            return (f"Predicate '{predicate}' expects {expected} arg(s), "
                    f"got {n_args}")
        return None

    def search_predicates(self, query: str, limit: int = 20) -> List[dict]:
        """Search predicates by name substring."""
        q = query.lower()
        results = []
        for name, info in self.predicates.items():
            if q in name.lower():
                results.append({"name": name, **info})
                if len(results) >= limit:
                    break
        return results

    # ------------------------------------------------------------------
    # Backward chaining hook (called from FOLKnowledgeBase._bc_solve)
    # ------------------------------------------------------------------

    def bc_solve_atom(
        self,
        goal: Atom,
        subst: Substitution,
        rest_goals: List[Atom],
        kb,
        depth: int,
        max_depth: int,
    ) -> Iterator[Substitution]:
        """
        Handle built-in Cyc predicates:
          genls(?Sub, ?Sup)   — subclass query
          isa(?Ind, ?Coll)    — instance-of query
        Yields substitutions from the Cyc ontology.
        """
        if not self._loaded:
            return

        pred = goal.predicate

        if pred == "genls" and len(goal.args) == 2:
            yield from self._solve_genls(goal, subst, rest_goals, kb, depth, max_depth)
        elif pred == "isa" and len(goal.args) == 2:
            yield from self._solve_isa(goal, subst, rest_goals, kb, depth, max_depth)

    def _solve_genls(self, goal, subst, rest_goals, kb, depth, max_depth):
        arg0 = subst.apply(goal.args[0])
        arg1 = subst.apply(goal.args[1])

        if isinstance(arg0, Constant) and isinstance(arg1, Constant):
            # Both bound — direct check
            if self.is_genls(str(arg0), str(arg1)):
                yield from kb._bc_solve(list(rest_goals), subst, depth + 1, max_depth)

        elif isinstance(arg0, Constant) and isinstance(arg1, Variable):
            # Sub bound, Super free — enumerate all superclasses
            sub = str(arg0)
            for sup in self.all_genls(sub):
                s2 = subst.extend(arg1, Constant(sup))
                yield from kb._bc_solve(list(rest_goals), s2, depth + 1, max_depth)

        elif isinstance(arg0, Variable) and isinstance(arg1, Constant):
            # Super bound, Sub free — enumerate all subclasses
            sup = str(arg1)
            for sub, parents in self.genls.items():
                if self.is_genls(sub, sup):
                    s2 = subst.extend(arg0, Constant(sub))
                    yield from kb._bc_solve(list(rest_goals), s2, depth + 1, max_depth)

        elif isinstance(arg0, Variable) and isinstance(arg1, Variable):
            # Both free — enumerate all genls pairs (limited)
            count = 0
            for sub, parents in self.genls.items():
                for sup in parents:
                    s2 = subst.extend(arg0, Constant(sub))
                    if arg1 not in s2:
                        s3 = s2.extend(arg1, Constant(sup))
                    else:
                        s3 = s2
                    yield from kb._bc_solve(list(rest_goals), s3, depth + 1, max_depth)
                    count += 1
                    if count >= 500:  # safety limit
                        return

    def _solve_isa(self, goal, subst, rest_goals, kb, depth, max_depth):
        arg0 = subst.apply(goal.args[0])
        arg1 = subst.apply(goal.args[1])

        if isinstance(arg0, Constant) and isinstance(arg1, Constant):
            if self.is_isa(str(arg0), str(arg1)):
                yield from kb._bc_solve(list(rest_goals), subst, depth + 1, max_depth)

        elif isinstance(arg0, Constant) and isinstance(arg1, Variable):
            ind = str(arg0)
            seen: Set[str] = set()
            for t in self.isa_types(ind):
                for collection in [t] + list(self.all_genls(t)):
                    if collection not in seen:
                        seen.add(collection)
                        s2 = subst.extend(arg1, Constant(collection))
                        yield from kb._bc_solve(list(rest_goals), s2, depth + 1, max_depth)

        elif isinstance(arg0, Variable) and isinstance(arg1, Constant):
            coll = str(arg1)
            for ind, types in self.types.items():
                if self.is_isa(ind, coll):
                    s2 = subst.extend(arg0, Constant(ind))
                    yield from kb._bc_solve(list(rest_goals), s2, depth + 1, max_depth)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        return {
            "loaded": self._loaded,
            "predicates": len(self.predicates),
            "genls_concepts": len(self.genls),
            "typed_individuals": len(self.types),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_ontology: Optional[CycOntology] = None


def get_ontology() -> CycOntology:
    global _ontology
    if _ontology is None:
        _ontology = CycOntology()
    return _ontology


def load_ontology(index_path: str) -> CycOntology:
    ont = get_ontology()
    try:
        ont.load(index_path)
        print(f"Cyc ontology loaded: {ont.stats()}")
    except FileNotFoundError as e:
        print(f"[WARNING] {e}")
        print("[WARNING] Running without Cyc ontology — isa/genls queries will use KB only.")
    return ont
