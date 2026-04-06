"""
First-Order Logic (FOL) Engine
===============================
Supports:
  - Terms:    Variable (?X), Constant (socrates), FunctionTerm (father(?X))
  - Atoms:    Predicate application — human(?X), mortal(socrates)
  - Formulas: Atom, Not, And, Or, Implies, ForAll, Exists
  - Rules:    Horn clauses stored as head :- body1, body2, ...
  - Inference: Backward chaining (SLD resolution) + forward chaining
  - Substitution and unification (Robinson's algorithm, with occurs check)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
import itertools


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------

class Term:
    """Base class for all terms."""
    def apply(self, subst: "Substitution") -> "Term":
        raise NotImplementedError
    def variables(self) -> frozenset:
        raise NotImplementedError


@dataclass(frozen=True)
class Variable(Term):
    """A logical variable, e.g. Variable('X') displayed as ?X."""
    name: str

    def apply(self, subst: "Substitution") -> Term:
        val = subst.get(self)
        if val is None:
            return self
        return val.apply(subst) if val != self else self

    def variables(self) -> frozenset:
        return frozenset([self])

    def __str__(self) -> str:
        return f"?{self.name}"

    def __repr__(self) -> str:
        return f"Var({self.name!r})"


@dataclass(frozen=True)
class Constant(Term):
    """A ground constant, e.g. Constant('socrates') or Constant(42)."""
    value: Any

    def apply(self, subst: "Substitution") -> Term:
        return self

    def variables(self) -> frozenset:
        return frozenset()

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"Const({self.value!r})"


@dataclass(frozen=True)
class FunctionTerm(Term):
    """A structured term: functor(arg1, arg2, ...) e.g. father(?X)"""
    functor: str
    args: Tuple[Term, ...]

    def apply(self, subst: "Substitution") -> Term:
        return FunctionTerm(self.functor, tuple(a.apply(subst) for a in self.args))

    def variables(self) -> frozenset:
        return frozenset().union(*(a.variables() for a in self.args))

    def __str__(self) -> str:
        args_str = ", ".join(str(a) for a in self.args)
        return f"{self.functor}({args_str})"


# ---------------------------------------------------------------------------
# Substitution
# ---------------------------------------------------------------------------

class Substitution:
    """A mapping from Variables to Terms, used during unification."""

    def __init__(self, bindings: Optional[Dict[Variable, Term]] = None):
        self._bindings: Dict[Variable, Term] = dict(bindings) if bindings else {}

    def get(self, var: Variable) -> Optional[Term]:
        return self._bindings.get(var)

    def extend(self, var: Variable, term: Term) -> "Substitution":
        new = Substitution(self._bindings)
        new._bindings[var] = term
        return new

    def __contains__(self, var: Variable) -> bool:
        return var in self._bindings

    def apply(self, term: Term) -> Term:
        return term.apply(self)

    def as_dict(self) -> dict:
        """Return human-readable {var_name: term_str} dict."""
        return {str(k): str(v) for k, v in self._bindings.items()}

    def __repr__(self) -> str:
        items = ", ".join(f"{k}={v}" for k, v in self._bindings.items())
        return f"Subst({{{items}}})"


EMPTY_SUBST = Substitution()
FAILURE = None  # unification failure sentinel


# ---------------------------------------------------------------------------
# Unification  (Robinson's algorithm with occurs check)
# ---------------------------------------------------------------------------

def occurs_in(var: Variable, term: Term, subst: Substitution) -> bool:
    """True if var appears in term after applying subst (occurs check prevents circularity)."""
    term = subst.apply(term)
    if isinstance(term, Variable):
        return term == var
    if isinstance(term, Constant):
        return False
    if isinstance(term, FunctionTerm):
        return any(occurs_in(var, a, subst) for a in term.args)
    return False


def unify(t1: Term, t2: Term, subst: Substitution,
          occurs_check: bool = True) -> Optional[Substitution]:
    """
    Unify two Terms under subst.
    Returns extended substitution on success, None on failure.
    """
    t1 = subst.apply(t1)
    t2 = subst.apply(t2)

    if t1 == t2:
        return subst

    if isinstance(t1, Variable):
        if occurs_check and occurs_in(t1, t2, subst):
            return FAILURE
        return subst.extend(t1, t2)

    if isinstance(t2, Variable):
        if occurs_check and occurs_in(t2, t1, subst):
            return FAILURE
        return subst.extend(t2, t1)

    if isinstance(t1, FunctionTerm) and isinstance(t2, FunctionTerm):
        if t1.functor != t2.functor or len(t1.args) != len(t2.args):
            return FAILURE
        s = subst
        for a1, a2 in zip(t1.args, t2.args):
            s = unify(a1, a2, s, occurs_check)
            if s is FAILURE:
                return FAILURE
        return s

    return FAILURE


def unify_atoms(a1: "Atom", a2: "Atom", subst: Substitution,
                occurs_check: bool = True) -> Optional[Substitution]:
    """
    Unify two Atom objects (predicate + args) under subst.
    Atoms are Formulas not Terms, so handled separately from unify().
    """
    if a1.predicate != a2.predicate or len(a1.args) != len(a2.args):
        return FAILURE
    s = subst
    for t1, t2 in zip(a1.args, a2.args):
        s = unify(t1, t2, s, occurs_check)
        if s is FAILURE:
            return FAILURE
    return s


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------

class Formula:
    """Base class for FOL formulas."""
    def apply(self, subst: Substitution) -> "Formula":
        raise NotImplementedError
    def variables(self) -> frozenset:
        raise NotImplementedError
    def is_ground(self) -> bool:
        return len(self.variables()) == 0


@dataclass(frozen=True)
class Atom(Formula):
    """Atomic formula: predicate(term1, ..., termN)."""
    predicate: str
    args: Tuple[Term, ...]

    def apply(self, subst: Substitution) -> "Atom":
        return Atom(self.predicate, tuple(a.apply(subst) for a in self.args))

    def variables(self) -> frozenset:
        return frozenset().union(*(a.variables() for a in self.args))

    def __str__(self) -> str:
        if not self.args:
            return self.predicate
        return f"{self.predicate}({', '.join(str(a) for a in self.args)})"


@dataclass(frozen=True)
class Not(Formula):
    formula: Formula

    def apply(self, subst: Substitution) -> "Not":
        return Not(self.formula.apply(subst))

    def variables(self) -> frozenset:
        return self.formula.variables()

    def __str__(self) -> str:
        return f"not({self.formula})"


@dataclass(frozen=True)
class And(Formula):
    conjuncts: Tuple[Formula, ...]

    def apply(self, subst: Substitution) -> "And":
        return And(tuple(c.apply(subst) for c in self.conjuncts))

    def variables(self) -> frozenset:
        return frozenset().union(*(c.variables() for c in self.conjuncts))

    def __str__(self) -> str:
        return " & ".join(f"({c})" for c in self.conjuncts)

    @classmethod
    def of(cls, *conjuncts: Formula) -> Formula:
        flat = []
        for c in conjuncts:
            if isinstance(c, And):
                flat.extend(c.conjuncts)
            else:
                flat.append(c)
        return flat[0] if len(flat) == 1 else cls(tuple(flat))


@dataclass(frozen=True)
class Or(Formula):
    disjuncts: Tuple[Formula, ...]

    def apply(self, subst: Substitution) -> "Or":
        return Or(tuple(d.apply(subst) for d in self.disjuncts))

    def variables(self) -> frozenset:
        return frozenset().union(*(d.variables() for d in self.disjuncts))

    def __str__(self) -> str:
        return " | ".join(f"({d})" for d in self.disjuncts)


@dataclass(frozen=True)
class Implies(Formula):
    antecedent: Formula
    consequent: Formula

    def apply(self, subst: Substitution) -> "Implies":
        return Implies(self.antecedent.apply(subst), self.consequent.apply(subst))

    def variables(self) -> frozenset:
        return self.antecedent.variables() | self.consequent.variables()

    def __str__(self) -> str:
        return f"({self.antecedent}) => ({self.consequent})"


@dataclass(frozen=True)
class ForAll(Formula):
    variable: Variable
    body: Formula

    def apply(self, subst: Substitution) -> "ForAll":
        restricted = Substitution({k: v for k, v in subst._bindings.items()
                                   if k != self.variable})
        return ForAll(self.variable, self.body.apply(restricted))

    def variables(self) -> frozenset:
        return self.body.variables() - {self.variable}

    def __str__(self) -> str:
        return f"forall {self.variable}: ({self.body})"


@dataclass(frozen=True)
class Exists(Formula):
    variable: Variable
    body: Formula

    def apply(self, subst: Substitution) -> "Exists":
        restricted = Substitution({k: v for k, v in subst._bindings.items()
                                   if k != self.variable})
        return Exists(self.variable, self.body.apply(restricted))

    def variables(self) -> frozenset:
        return self.body.variables() - {self.variable}

    def __str__(self) -> str:
        return f"exists {self.variable}: ({self.body})"


# ---------------------------------------------------------------------------
# Horn Clause
# ---------------------------------------------------------------------------

@dataclass
class HornClause:
    """
    A Horn clause: head :- body1, body2, ..., bodyN
    A fact has an empty body list.
    """
    head: Atom
    body: List[Atom] = field(default_factory=list)
    label: str = ""

    def rename_vars(self, suffix: str) -> "HornClause":
        """Return fresh copy with all variables renamed to avoid clash during resolution."""
        all_vars = self.head.variables()
        for b in self.body:
            all_vars |= b.variables()
        rename_map = Substitution({v: Variable(f"{v.name}__{suffix}") for v in all_vars})
        return HornClause(
            self.head.apply(rename_map),
            [b.apply(rename_map) for b in self.body],
            self.label,
        )

    def __str__(self) -> str:
        if not self.body:
            return str(self.head)
        return f"{self.head} :- {', '.join(str(b) for b in self.body)}"


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class FOLKnowledgeBase:
    """
    A knowledge base with:
      - Asserted Horn clauses (facts and rules)
      - Backward chaining (SLD resolution, Prolog-style)
      - Forward chaining (ground fact propagation)
      - Optional Cyc ontology backing
    """

    def __init__(self):
        self.clauses: List[HornClause] = []
        self._index: Dict[str, List[HornClause]] = {}  # predicate → clauses
        self._counter = itertools.count()
        self.cyc_ontology = None  # injected externally

    # ------------------------------------------------------------------
    # Insertion
    # ------------------------------------------------------------------

    def tell(self, clause: HornClause) -> None:
        self.clauses.append(clause)
        self._index.setdefault(clause.head.predicate, []).append(clause)

    def tell_fact(self, predicate: str, *args: Term, label: str = "") -> HornClause:
        terms = tuple(_coerce_term(a) for a in args)
        clause = HornClause(Atom(predicate, terms), [], label)
        self.tell(clause)
        return clause

    def tell_rule(self, head: Atom, body: List[Atom], label: str = "") -> HornClause:
        clause = HornClause(head, body, label)
        self.tell(clause)
        return clause

    def tell_implies(self, formula: Implies) -> HornClause:
        """Convert Implies(antecedent, consequent) to a Horn clause."""
        head = formula.consequent
        body = formula.antecedent
        if not isinstance(head, Atom):
            raise ValueError(f"Consequent must be Atom, got {type(head).__name__}")
        body_atoms: List[Atom] = []
        if isinstance(body, Atom):
            body_atoms = [body]
        elif isinstance(body, And):
            for c in body.conjuncts:
                if not isinstance(c, Atom):
                    raise ValueError(f"Conjunct must be Atom, got {type(c).__name__}")
                body_atoms.append(c)
        else:
            raise ValueError(f"Antecedent must be Atom or And, got {type(body).__name__}")
        clause = HornClause(head, body_atoms)
        self.tell(clause)
        return clause

    # ------------------------------------------------------------------
    # Backward Chaining (SLD resolution)
    # ------------------------------------------------------------------

    def _fresh(self) -> str:
        return str(next(self._counter))

    def _bc_solve(
        self,
        goals: List[Atom],
        subst: Substitution,
        depth: int,
        max_depth: int,
    ) -> Iterator[Substitution]:
        if depth > max_depth:
            return
        if not goals:
            yield subst
            return

        goal, rest = goals[0].apply(subst), goals[1:]

        # Cyc ontology built-ins first
        if self.cyc_ontology is not None:
            yield from self.cyc_ontology.bc_solve_atom(
                goal, subst, rest, self, depth, max_depth)

        # KB clauses
        for clause in self._index.get(goal.predicate, []):
            renamed = clause.rename_vars(self._fresh())
            s2 = unify_atoms(goal, renamed.head, subst)
            if s2 is not None:
                yield from self._bc_solve(list(renamed.body) + list(rest), s2,
                                          depth + 1, max_depth)

    def ask(self, query: Atom, max_depth: int = 50,
            max_solutions: int = 100) -> List[Dict[str, str]]:
        """Return list of answer substitutions for query."""
        results = []
        for subst in self._bc_solve([query], EMPTY_SUBST, 0, max_depth):
            binding = {str(v): str(subst.apply(v)) for v in query.variables()}
            results.append(binding)
            if len(results) >= max_solutions:
                break
        return results

    def ask_yes_no(self, query: Atom, max_depth: int = 50) -> bool:
        for _ in self._bc_solve([query], EMPTY_SUBST, 0, max_depth):
            return True
        return False

    # ------------------------------------------------------------------
    # Forward Chaining
    # ------------------------------------------------------------------

    def forward_chain(self, max_steps: int = 500) -> int:
        """Saturate KB by applying all rules to current ground facts."""
        new_count = 0
        changed = True
        steps = 0
        while changed and steps < max_steps:
            changed = False
            steps += 1
            for clause in list(self.clauses):
                if not clause.body:
                    continue
                for subst in self._bc_solve(clause.body, EMPTY_SUBST, 0, 15):
                    new_head = clause.head.apply(subst)
                    if new_head.is_ground():
                        existing = self._index.get(new_head.predicate, [])
                        if not any(c.head == new_head for c in existing):
                            self.tell(HornClause(new_head, [], "derived"))
                            new_count += 1
                            changed = True
        return new_count

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def list_facts(self, predicate: Optional[str] = None) -> List[str]:
        src = self._index.get(predicate, []) if predicate else self.clauses
        return [str(c) for c in src if not c.body]

    def list_rules(self, predicate: Optional[str] = None) -> List[str]:
        src = self._index.get(predicate, []) if predicate else self.clauses
        return [str(c) for c in src if c.body]

    def stats(self) -> dict:
        facts = sum(1 for c in self.clauses if not c.body)
        rules = sum(1 for c in self.clauses if c.body)
        return {
            "total_clauses": len(self.clauses),
            "facts": facts,
            "rules": rules,
            "predicates": list(self._index.keys()),
        }


def _coerce_term(v) -> Term:
    if isinstance(v, Term):
        return v
    if isinstance(v, str) and v.startswith("?"):
        return Variable(v[1:])
    return Constant(v)


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------

def var(name: str) -> Variable:
    return Variable(name)

def const(value) -> Constant:
    return Constant(value)

def atom(predicate: str, *args) -> Atom:
    return Atom(predicate, tuple(_coerce_term(a) for a in args))

def rule(head: Atom, *body: Atom, label: str = "") -> HornClause:
    return HornClause(head, list(body), label)

def fact(predicate: str, *args, label: str = "") -> HornClause:
    return HornClause(atom(predicate, *args), [], label)


# ---------------------------------------------------------------------------
# Parser — clause and formula strings
# ---------------------------------------------------------------------------

class FOLParser:
    """
    Parse FOL expressions from strings.

    Clause syntax:
      mortal(socrates)                  — fact
      mortal(?X) :- human(?X)           — rule with one body atom
      mortal(?X) :- human(?X), greek(?X) — rule with two body atoms

    Formula syntax (for /formula endpoint):
      Implies(Atom('human', Var('X')), Atom('mortal', Var('X')))
    """

    @staticmethod
    def parse_term(s: str) -> Term:
        s = s.strip()
        if s.startswith("?"):
            return Variable(s[1:])
        try:
            return Constant(int(s))
        except ValueError:
            pass
        try:
            return Constant(float(s))
        except ValueError:
            pass
        if (s.startswith("'") and s.endswith("'")) or \
           (s.startswith('"') and s.endswith('"')):
            return Constant(s[1:-1])
        if "(" in s and s.endswith(")"):
            fname = s[:s.index("(")]
            inner = s[s.index("(") + 1:-1]
            args = tuple(FOLParser.parse_term(a) for a in _split_args(inner))
            return FunctionTerm(fname, args)
        return Constant(s)

    @staticmethod
    def parse_atom(s: str) -> Atom:
        s = s.strip()
        if "(" not in s:
            return Atom(s, ())
        pred = s[:s.index("(")]
        inner = s[s.index("(") + 1:-1]
        args = tuple(FOLParser.parse_term(a) for a in _split_args(inner))
        return Atom(pred, args)

    @staticmethod
    def parse_clause(s: str) -> HornClause:
        s = s.strip()
        if ":-" in s:
            head_str, body_str = s.split(":-", 1)
            head = FOLParser.parse_atom(head_str.strip())
            body = [FOLParser.parse_atom(a.strip()) for a in _split_args(body_str)]
            return HornClause(head, body)
        return HornClause(FOLParser.parse_atom(s), [])

    @staticmethod
    def parse_formula(expr_str: str) -> Formula:
        """Parse a formula using restricted eval with FOL constructors."""
        import re
        s = expr_str.strip()
        # ?X → Var('X')
        s = re.sub(r'\?([A-Za-z_]\w*)', r"Var('\1')", s)

        ctx: Dict[str, Any] = {
            "Var": lambda n: Variable(n),
            "Const": lambda v: Constant(v),
            "Atom": lambda p, *args: Atom(p, tuple(_coerce_term(a) for a in args)),
            "And": lambda *fs: And.of(*fs),
            "Or": lambda *fs: Or.of(*fs),
            "Not": lambda f: Not(f),
            "Implies": lambda a, c: Implies(a, c),
            "ForAll": lambda v, f: ForAll(v, f),
            "Exists": lambda v, f: Exists(v, f),
        }
        try:
            return eval(s, {"__builtins__": {}}, ctx)
        except Exception as e:
            raise ValueError(f"Cannot parse formula {expr_str!r}: {e}")


def _split_args(s: str) -> List[str]:
    """Split comma-separated args respecting nested parentheses."""
    parts, depth, current = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== FOL Engine Self-Test ===\n")

    kb = FOLKnowledgeBase()

    X = var("X")
    kb.tell(fact("human", "socrates"))
    kb.tell(fact("human", "plato"))
    kb.tell(fact("greek", "socrates"))
    kb.tell(rule(atom("mortal", X), atom("human", X)))
    kb.tell(rule(atom("greek_philosopher", X), atom("human", X), atom("greek", X)))

    print("Facts:", kb.list_facts())
    print("Rules:", kb.list_rules())

    q = atom("mortal", X)
    print(f"\nQuery: {q}")
    print(f"Answers: {kb.ask(q)}")

    print(f"\nmortal(socrates)? {kb.ask_yes_no(atom('mortal', 'socrates'))}")
    print(f"mortal(zeus)?     {kb.ask_yes_no(atom('mortal', 'zeus'))}")

    q2 = atom("greek_philosopher", X)
    print(f"\ngreek_philosopher(?X)? {kb.ask(q2)}")

    # Parser test
    c = FOLParser.parse_clause("ancestor(?X, ?Z) :- parent(?X, ?Y), ancestor(?Y, ?Z)")
    print(f"\nParsed clause: {c}")

    # Forward chaining test
    kb2 = FOLKnowledgeBase()
    kb2.tell(fact("parent", "tom", "bob"))
    kb2.tell(fact("parent", "bob", "ann"))
    Y, Z = var("Y"), var("Z")
    kb2.tell(rule(atom("ancestor", X, Z), atom("parent", X, Z)))
    kb2.tell(rule(atom("ancestor", X, Z), atom("parent", X, Y), atom("ancestor", Y, Z)))
    derived = kb2.forward_chain()
    print(f"\nForward chaining derived {derived} new facts")
    print("All ancestor facts:", kb2.list_facts("ancestor"))

    print("\nAll tests passed.")
