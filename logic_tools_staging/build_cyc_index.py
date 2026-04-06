"""
build_cyc_index.py
==================
One-time script: streams the open-cyc.rdf ZIP file and extracts a compact
JSON index suitable for loading into CycOntology at startup.

Extracts:
  - predicates: name → {arity, label}
  - genls: concept → [parent, ...]   (subcollection/subclass hierarchy)
  - types: individual → [type, ...]   (isa assertions, limited)

Output: resources/cyc_index.json  (~several MB, fast to load)

Usage:
    python build_cyc_index.py [--rdf PATH] [--out PATH] [--limit N]

Defaults:
    --rdf   resources/open-cyc.rdf.ZIP
    --out   resources/cyc_index.json
    --limit 200000   (max RDF descriptions to parse — full file has ~300k)
"""

import argparse
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from xml.etree import ElementTree as ET

# Namespace URIs (plain, without curly braces)
CYC_NS = "http://sw.cyc.com/2006/07/27/cyc/"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
OWL_NS = "http://www.w3.org/2002/07/owl#"

# Clark notation for ElementTree tag matching: {namespace}localname
def _t(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"

CYC  = CYC_NS   # kept for URI construction (rdf:about comparisons)

# ElementTree tags (Clark notation)
T_DESCRIPTION   = _t(RDF_NS,  "Description")
T_TYPE          = _t(RDF_NS,  "type")
T_ARITY         = _t(CYC_NS,  "arity")
T_PRETTY        = _t(CYC_NS,  "prettyString-Canonical")
T_LABEL         = _t(RDFS_NS, "label")
T_GENLS         = _t(CYC_NS,  "genls")
T_SUBCLASSOF    = _t(RDFS_NS, "subClassOf")
T_RESOURCE      = _t(RDF_NS,  "resource")  # not a tag but an attribute name
ATTR_ABOUT      = _t(RDF_NS,  "about")
ATTR_RESOURCE   = _t(RDF_NS,  "resource")

# Cyc type URIs that indicate something is a Predicate (using plain URIs for rdf:resource)
PREDICATE_TYPES = {
    f"{CYC_NS}Predicate",
    f"{CYC_NS}BinaryPredicate",
    f"{CYC_NS}UnaryPredicate",
    f"{CYC_NS}TernaryPredicate",
    f"{CYC_NS}QuaternaryPredicate",
    f"{CYC_NS}QuintaryPredicate",
    f"{CYC_NS}HLPredicate",
    f"{CYC_NS}BaseKBPredicate",
    f"{CYC_NS}RuleMacroPredicate",
}

# Collection types indicating a concept is a Collection (class)
COLLECTION_TYPES = {
    f"{CYC_NS}Collection",
    f"{CYC_NS}FirstOrderCollection",
    f"{CYC_NS}SecondOrderCollection",
    f"{CYC_NS}ObjectType",
    f"{CYC_NS}ExistingObjectType",
}

INDIVIDUAL_TYPES = {
    f"{CYC_NS}Individual",
    f"{CYC_NS}PartiallyTangible",
    f"{CYC_NS}SomethingExisting",
}


def cyc_name(uri: str) -> str:
    if uri.startswith(CYC_NS):
        return uri[len(CYC_NS):]
    return uri


class _SanitizingStream:
    """
    Wraps a file-like object and strips invalid XML characters on the fly.
    The open-cyc.rdf file contains control characters (e.g. 0x1A) that
    are not valid in XML 1.0, causing ElementTree to fail mid-parse.
    We strip any byte outside the valid XML 1.0 character ranges.
    """
    # Valid XML 1.0 chars: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD]
    _INVALID = re.compile(
        b'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]'
    )

    def __init__(self, stream):
        self._stream = stream

    def read(self, n: int = -1) -> bytes:
        data = self._stream.read(n)
        return self._INVALID.sub(b' ', data)


def parse_rdf_streaming(rdf_file, limit: int):
    """
    Parse the RDF/XML file using iterparse, yielding per-Description records.
    Each record is a dict:
      {
        'about': str,
        'types': [str],
        'arity': int or None,
        'label': str or None,
        'genls': [str],
        'isa_types': [str],   # rdf:type targets that are not predicates/collections
        'is_predicate': bool,
        'is_collection': bool,
        'is_individual': bool,
      }
    """
    count = 0
    current: dict = {}
    depth = 0

    sanitized = _SanitizingStream(rdf_file)
    # iterparse over the Description elements
    context = ET.iterparse(sanitized, events=("start", "end"))

    for event, elem in context:
        tag = elem.tag

        if event == "start":
            if tag == T_DESCRIPTION:
                depth += 1
                if depth == 1:
                    about = elem.get(ATTR_ABOUT, "")
                    current = {
                        "about": about,
                        "types": [],
                        "arity": None,
                        "label": None,
                        "genls": [],
                        "isa_types": [],
                        "is_predicate": False,
                        "is_collection": False,
                        "is_individual": False,
                    }

        elif event == "end":
            if tag == T_DESCRIPTION:
                depth -= 1
                if depth == 0 and current:
                    yield current
                    current = {}
                    count += 1
                    if count >= limit:
                        break
                    if count % 10000 == 0:
                        print(f"  Parsed {count:,} descriptions...", file=sys.stderr)
                    elem.clear()

            elif depth == 1 and current:
                # Child element of Description
                if tag == T_TYPE:
                    resource = elem.get(ATTR_RESOURCE, "")
                    current["types"].append(resource)
                    if resource in PREDICATE_TYPES:
                        current["is_predicate"] = True
                    elif resource in COLLECTION_TYPES:
                        current["is_collection"] = True
                    elif resource in INDIVIDUAL_TYPES:
                        current["is_individual"] = True

                elif tag == T_ARITY:
                    try:
                        current["arity"] = int(elem.text or "")
                    except (ValueError, TypeError):
                        pass

                elif tag == T_PRETTY:
                    current["label"] = (elem.text or "").strip()

                elif tag == T_LABEL:
                    if current["label"] is None:
                        current["label"] = (elem.text or "").strip()

                elif tag == T_GENLS:
                    resource = elem.get(ATTR_RESOURCE, "")
                    if resource.startswith(CYC_NS):
                        current["genls"].append(cyc_name(resource))

                elif tag == T_SUBCLASSOF:
                    resource = elem.get(ATTR_RESOURCE, "")
                    if resource.startswith(CYC_NS):
                        current["genls"].append(cyc_name(resource))


def build_index(rdf_zip_path: str, limit: int) -> dict:
    print(f"Reading: {rdf_zip_path}", file=sys.stderr)

    predicates: dict = {}
    genls: dict = defaultdict(list)
    types: dict = defaultdict(list)

    with zipfile.ZipFile(rdf_zip_path, "r") as z:
        rdf_name = next(n for n in z.namelist() if n.endswith(".rdf"))
        with z.open(rdf_name) as f:
            for rec in parse_rdf_streaming(f, limit):
                about = rec["about"]
                if not about.startswith(CYC_NS):
                    continue
                name = cyc_name(about)

                # Predicates
                if rec["is_predicate"] and rec["arity"] is not None:
                    entry = {"arity": rec["arity"]}
                    if rec["label"]:
                        entry["label"] = rec["label"]
                    predicates[name] = entry

                # Genls hierarchy
                if rec["genls"]:
                    existing = genls[name]
                    for parent in rec["genls"]:
                        if parent not in existing and parent != name:
                            existing.append(parent)

                # Types (isa assertions via rdf:type, limited to collection types)
                if rec["is_individual"] and rec["types"]:
                    coll_types = [
                        cyc_name(t) for t in rec["types"]
                        if t.startswith(CYC)
                        and t not in PREDICATE_TYPES
                        and t not in COLLECTION_TYPES
                        and t not in INDIVIDUAL_TYPES
                    ]
                    if coll_types:
                        types[name] = coll_types

    # Remove empty genls
    genls = {k: v for k, v in genls.items() if v}
    types = {k: v for k, v in types.items() if v}

    return {
        "predicates": predicates,
        "genls": dict(genls),
        "types": dict(types),
    }


def main():
    parser = argparse.ArgumentParser(description="Build Cyc ontology index")
    parser.add_argument("--rdf", default="resources/open-cyc.rdf.ZIP",
                        help="Path to open-cyc.rdf.ZIP")
    parser.add_argument("--out", default="resources/cyc_index.json",
                        help="Output JSON path")
    parser.add_argument("--limit", type=int, default=200000,
                        help="Max RDF descriptions to parse")
    args = parser.parse_args()

    if not os.path.exists(args.rdf):
        print(f"ERROR: RDF file not found: {args.rdf}", file=sys.stderr)
        sys.exit(1)

    print(f"Building Cyc index (limit={args.limit:,})...", file=sys.stderr)
    index = build_index(args.rdf, args.limit)

    print(f"\nIndex summary:", file=sys.stderr)
    print(f"  predicates: {len(index['predicates']):,}", file=sys.stderr)
    print(f"  genls pairs: {sum(len(v) for v in index['genls'].values()):,}", file=sys.stderr)
    print(f"  typed individuals: {len(index['types']):,}", file=sys.stderr)

    os.makedirs(os.path.dirname(args.out) if os.path.dirname(args.out) else ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=None, separators=(",", ":"))

    size_mb = os.path.getsize(args.out) / (1024 * 1024)
    print(f"\nWrote: {args.out} ({size_mb:.1f} MB)", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
