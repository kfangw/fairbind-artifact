# Predicates

Predicates return `PASS`, `FAIL`, or `INCONCLUSIVE` with versioned evidence. The first implementation covers one data API predicate and one open-weights inference predicate.

Each predicate profile records its false rejection and false acceptance measurements. The contract stores only the predicate identifier, verdict, and evidence hash.

The normative commitment codecs and evidence envelope are defined in
[`../docs/spec/predicate-interface-v1.md`](../docs/spec/predicate-interface-v1.md).
