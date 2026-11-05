#!/usr/bin/env python3
"""The replay profile and the replay operating point, derived from the shared evaluation files.

The R20 design (V6, sections 9.1 and 9.3) runs the replay at a failure limit that the shared
evaluation profile does not derive (the pre-certification default k = 27 / 45, not the
failureLimitBasis value 16 / 27) and at a data-API enforcement window long enough to admit the
burst capacity qX (13,700 blocks, so that (r_max - r_fill) * enforcementBlocks = 137). Neither
value belongs in the shared profile: its failureLimit is recomputed from failureLimitBasis by
scripts/check_spec.py, and its parameterHash is pinned by test vectors and contract tests.

So the replay reads its own pair of files, built here from the shared ones and the overrides in
conditions.json (`replay_profile`):

    replay_profile.py            check that the committed files equal the build
    replay_profile.py --write    rebuild them

Every parameter not listed in the overrides equals the shared profile; parameterHash is
recomputed with the canonical JSON hash of scripts/check_spec.py. The run envelope records the
base files, their hashes and the override list (replay.py, `profile_overrides`).
"""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'scripts'))

import check_spec  # noqa: E402
import inputs  # noqa: E402


def parameter_hash(parameters):
    return check_spec.hash_hex(check_spec.canonical_json(parameters))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(cond=None):
    """(profile document, operating point document) for the replay, from the shared files."""
    cond = cond or inputs.load_conditions()
    spec = cond['replay_profile']
    base_profile_path = ROOT / spec['base_profile_file']
    base_op_path = ROOT / spec['base_operating_point']
    base = json.loads(base_profile_path.read_text(encoding='utf-8'))
    op = json.loads(base_op_path.read_text(encoding='ascii'))
    doc = copy.deepcopy(base)
    doc['status'] = 'replay-only'
    doc['description'] = (
        'Settlement replay profile (experiments/replay). Equal to the shared evaluation profile except the '
        'parameters in replayOverrides; parameterHash is recomputed. failureLimit here is the R20 '
        'pre-certification default k, not the value failureLimitBasis derives, so this file is not checked by '
        'scripts/check_spec.py and is not a deployable evaluation profile. Built by '
        'experiments/replay/replay_profile.py.')
    doc['derivedFrom'] = dict(file=spec['base_profile_file'], sha256=_sha(base_profile_path),
                              source=spec['source'])
    for prof in doc['profiles']:
        over = spec['overrides'].get(prof['name'], {})
        record = {}
        for key, value in sorted(over.items()):
            if key not in prof['parameters']:
                raise ValueError(f'{prof["name"]}: no parameter {key}')
            record[key] = dict(base=prof['parameters'][key], replay=value)
            prof['parameters'][key] = value
        prof['parameterHash'] = parameter_hash(prof['parameters'])
        prof['replayOverrides'] = record
    rop = copy.deepcopy(op)
    rop['profile_file'] = spec['profile_file']
    rop['description'] = (
        'Operating point of the settlement replay: the shared operating point (experiments/operating-point.json) '
        'with profile_file set to the replay profile and failureLimit set to its value there. Built by '
        'experiments/replay/replay_profile.py; used only by experiments/replay.')
    rop['derivedFrom'] = dict(file=spec['base_operating_point'], sha256=_sha(base_op_path), source=spec['source'])
    for name, over in spec['overrides'].items():
        if 'failureLimit' in over:
            entry = rop['profiles'][name]['failureLimit']
            entry['value'] = over['failureLimit']
            entry['source'] = (f"replay profile failureLimit: the R20 pre-certification default k ({spec['source']}); "
                               f"the shared profile derives {op['profiles'][name]['failureLimit']['value']} from "
                               'failureLimitBasis')
    return doc, rop


def dumps(doc):
    return json.dumps(doc, indent=2, ensure_ascii=True) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--write', action='store_true')
    a = p.parse_args(argv)
    cond = inputs.load_conditions()
    spec = cond['replay_profile']
    doc, rop = build(cond)
    targets = [(ROOT / spec['profile_file'], dumps(doc)), (ROOT / spec['operating_point'], dumps(rop))]
    if a.write:
        for path, text in targets:
            path.write_text(text, encoding='ascii')
            print(f'wrote {path.relative_to(ROOT)}')
        return 0
    stale = [str(path.relative_to(ROOT)) for path, text in targets
             if not path.exists() or path.read_text(encoding='ascii') != text]
    if stale:
        print('out of date: ' + ', '.join(stale), file=sys.stderr)
        return 1
    print('replay profile and operating point: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
