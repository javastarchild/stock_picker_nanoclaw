"""
FOL Knowledge Base Tool — REST API
====================================
Extended from propositional logic to full First-Order Logic with
Cyc ontology backing.

Endpoints:
  POST /fact           — assert a Horn clause fact (propositional or FOL)
  POST /rule           — assert a Horn clause rule
  POST /clause         — assert a raw Horn clause  (head :- body syntax)
  POST /query          — backward-chain to answer a query
  POST /forward        — run forward chaining and return derived count
  GET  /facts          — list all asserted facts
  GET  /rules          — list all asserted rules
  GET  /stats          — KB statistics

  GET  /ontology/stats            — Cyc ontology statistics
  GET  /ontology/predicate/<name> — look up a Cyc predicate
  GET  /ontology/search?q=<term>  — search Cyc predicates by name
  POST /ontology/genls            — query subclass hierarchy
  POST /ontology/isa              — query instance-of (with inheritance)

Request/response examples:
  POST /clause  {"clause": "mortal(?X) :- human(?X)"}
  POST /fact    {"fact": "human(socrates)"}
  POST /query   {"query": "mortal(?X)"}
    → {"answers": [{"?X": "socrates"}], "proved": true}
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os

from fol_engine import (
    FOLKnowledgeBase, FOLParser, HornClause,
    atom, fact, rule, var, const,
    Variable, Constant, Atom,
)
from cyc_index import load_ontology, get_ontology

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Global KB and ontology
# ---------------------------------------------------------------------------

kb = FOLKnowledgeBase()
CYC_INDEX_PATH = os.environ.get(
    "CYC_INDEX_PATH",
    os.path.join(os.path.dirname(__file__), "resources", "cyc_index.json")
)
ontology = load_ontology(CYC_INDEX_PATH)
kb.cyc_ontology = ontology


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_clause_str(s: str) -> HornClause:
    return FOLParser.parse_clause(s)

def _parse_atom_str(s: str) -> Atom:
    return FOLParser.parse_atom(s)

def _error(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


# ---------------------------------------------------------------------------
# KB endpoints
# ---------------------------------------------------------------------------

@app.route("/fact", methods=["POST"])
def add_fact():
    """
    Assert a fact.
    Body: {"fact": "human(socrates)"}
         or legacy propositional: {"fact": "A"}
    """
    data = request.json or {}
    raw = data.get("fact", "").strip()
    if not raw:
        return _error("'fact' field required")
    try:
        clause = _parse_clause_str(raw)
        if clause.body:
            return _error("Use /rule for clauses with a body")
        kb.tell(clause)
        return jsonify({"status": "fact added", "fact": str(clause.head)})
    except Exception as e:
        return _error(f"Parse error: {e}")


@app.route("/rule", methods=["POST"])
def add_rule():
    """
    Assert a rule.
    Body: {"rule": "mortal(?X) :- human(?X)"}
    """
    data = request.json or {}
    raw = data.get("rule", "").strip()
    if not raw:
        return _error("'rule' field required")
    try:
        clause = _parse_clause_str(raw)
        if not clause.body:
            return _error("Rule must have a body. Use /fact for ground assertions.")
        kb.tell(clause)
        return jsonify({"status": "rule added", "rule": str(clause)})
    except Exception as e:
        return _error(f"Parse error: {e}")


@app.route("/clause", methods=["POST"])
def add_clause():
    """
    Assert any Horn clause (fact or rule, using :- syntax).
    Body: {"clause": "ancestor(?X,?Z) :- parent(?X,?Y), ancestor(?Y,?Z)"}
    """
    data = request.json or {}
    raw = data.get("clause", "").strip()
    if not raw:
        return _error("'clause' field required")
    try:
        clause = _parse_clause_str(raw)
        kb.tell(clause)
        kind = "fact" if not clause.body else "rule"
        return jsonify({"status": f"{kind} added", "clause": str(clause)})
    except Exception as e:
        return _error(f"Parse error: {e}")


@app.route("/query", methods=["POST"])
def query():
    """
    Backward-chain to answer a query.
    Body: {"query": "mortal(?X)", "max_depth": 50, "max_solutions": 10}
    Response: {"answers": [...], "proved": bool, "query": str}
    """
    data = request.json or {}
    raw = data.get("query", "").strip()
    if not raw:
        return _error("'query' field required")
    max_depth = int(data.get("max_depth", 50))
    max_solutions = int(data.get("max_solutions", 100))
    try:
        query_atom = _parse_atom_str(raw)
    except Exception as e:
        return _error(f"Parse error: {e}")

    # Validate arity against Cyc if ontology is loaded
    arity_error = ontology.validate_arity(query_atom.predicate, len(query_atom.args))
    warnings = []
    if arity_error:
        warnings.append(arity_error)

    answers = kb.ask(query_atom, max_depth=max_depth, max_solutions=max_solutions)
    proved = len(answers) > 0 or kb.ask_yes_no(query_atom, max_depth=max_depth)

    resp = {
        "query": str(query_atom),
        "proved": proved,
        "answers": answers,
        "answer_count": len(answers),
    }
    if warnings:
        resp["warnings"] = warnings
    return jsonify(resp)


@app.route("/forward", methods=["POST"])
def forward_chain():
    """Run forward chaining. Returns number of new facts derived."""
    data = request.json or {}
    max_steps = int(data.get("max_steps", 500))
    derived = kb.forward_chain(max_steps=max_steps)
    return jsonify({
        "status": "forward chaining complete",
        "new_facts_derived": derived,
        "kb_stats": kb.stats(),
    })


@app.route("/facts", methods=["GET"])
def list_facts():
    predicate = request.args.get("predicate")
    facts = kb.list_facts(predicate)
    return jsonify({"facts": facts, "count": len(facts)})


@app.route("/rules", methods=["GET"])
def list_rules():
    predicate = request.args.get("predicate")
    rules = kb.list_rules(predicate)
    return jsonify({"rules": rules, "count": len(rules)})


@app.route("/stats", methods=["GET"])
def kb_stats():
    return jsonify(kb.stats())


@app.route("/reset", methods=["POST"])
def reset_kb():
    """Clear the KB (for testing). Keeps ontology loaded."""
    global kb
    kb = FOLKnowledgeBase()
    kb.cyc_ontology = ontology
    return jsonify({"status": "kb reset"})


# ---------------------------------------------------------------------------
# Ontology endpoints
# ---------------------------------------------------------------------------

@app.route("/ontology/stats", methods=["GET"])
def ontology_stats():
    return jsonify(ontology.stats())


@app.route("/ontology/predicate/<name>", methods=["GET"])
def ontology_predicate(name: str):
    info = ontology.predicate_info(name)
    if info is None:
        return _error(f"Predicate '{name}' not found in Cyc ontology", 404)
    return jsonify({"name": name, **info})


@app.route("/ontology/search", methods=["GET"])
def ontology_search():
    q = request.args.get("q", "").strip()
    if not q:
        return _error("'q' query parameter required")
    limit = int(request.args.get("limit", 20))
    results = ontology.search_predicates(q, limit=limit)
    return jsonify({"query": q, "results": results, "count": len(results)})


@app.route("/ontology/genls", methods=["POST"])
def ontology_genls():
    """
    Query the genls (subclass) hierarchy.
    Body:
      {"concept": "Dog"}               → all superclasses of Dog
      {"concept": "Dog", "depth": 1}   → immediate parents only
      {"superclass": "Animal"}         → all subclasses of Animal
    """
    data = request.json or {}
    if "concept" in data:
        concept = data["concept"]
        depth = data.get("depth")
        if depth == 1:
            parents = ontology.genls_parents(concept)
        else:
            parents = sorted(ontology.all_genls(concept))
        return jsonify({
            "concept": concept,
            "superclasses": parents,
            "count": len(parents),
        })
    elif "superclass" in data:
        sup = data["superclass"]
        subs = [k for k in ontology.genls if ontology.is_genls(k, sup)]
        return jsonify({"superclass": sup, "subclasses": sorted(subs), "count": len(subs)})
    else:
        return _error("Provide 'concept' or 'superclass'")


@app.route("/ontology/isa", methods=["POST"])
def ontology_isa():
    """
    Query the isa (instance-of) relationship.
    Body:
      {"individual": "Socrates"}           → all types of Socrates
      {"collection": "Person"}             → all individuals of type Person
      {"individual": "x", "collection": "y"} → boolean check
    """
    data = request.json or {}
    ind = data.get("individual")
    coll = data.get("collection")

    if ind and coll:
        result = ontology.is_isa(ind, coll)
        return jsonify({"individual": ind, "collection": coll, "result": result})
    elif ind:
        direct_types = ontology.isa_types(ind)
        all_types = set(direct_types)
        for t in direct_types:
            all_types |= ontology.all_genls(t)
        return jsonify({
            "individual": ind,
            "direct_types": direct_types,
            "all_types": sorted(all_types),
        })
    elif coll:
        instances = [i for i in ontology.types if ontology.is_isa(i, coll)]
        return jsonify({"collection": coll, "instances": instances, "count": len(instances)})
    else:
        return _error("Provide 'individual' and/or 'collection'")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "kb": kb.stats(),
        "ontology": ontology.stats(),
    })


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
