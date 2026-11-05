"""Baseline arm configs (experiments/baselines/*.json), resolved against the operating point."""
import hashlib
import json
from pathlib import Path

from . import operating_point as opt

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / 'experiments' / 'baselines'
# Values of the earlier shared constants that must not reappear as literals in a config.
RETIRED_LITERALS = {5400, 2700, 10800, 107.541667, 0.0731, 348}


class BaselineError(ValueError):
    pass


def load_all(directory=DEFAULT_DIR):
    out = {}
    for path in sorted(Path(directory).glob('*.json')):
        raw = path.read_bytes()
        doc = json.loads(raw.decode('ascii'))
        if doc.get('schema') != 'fairbind-baseline-policy/v1' or doc.get('id') != path.stem:
            raise BaselineError(f'{path.name}: schema or id mismatch')
        doc['_sha256'] = hashlib.sha256(raw).hexdigest()
        out[doc['id']] = doc
    return out


def references(doc):
    """Every 'op:' and 'rate:' string in a config."""
    if isinstance(doc, dict):
        for k, v in doc.items():
            if not k.startswith('_'):
                yield from references(v)
    elif isinstance(doc, list):
        for v in doc:
            yield from references(v)
    elif isinstance(doc, str) and (doc.startswith('op:') or doc.startswith('rate:')):
        yield doc


def retired_literals(doc, path=''):
    """Numeric fields that still carry a value of the retired shared constants."""
    if isinstance(doc, dict):
        for k, v in doc.items():
            if not k.startswith('_'):
                yield from retired_literals(v, f'{path}.{k}')
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            yield from retired_literals(v, f'{path}[{i}]')
    elif isinstance(doc, (int, float)) and not isinstance(doc, bool) and doc in RETIRED_LITERALS:
        yield path
    elif isinstance(doc, str) and doc.isdigit() and int(doc) in RETIRED_LITERALS:
        yield path


def resolve(doc, op, profile_name):
    table = opt.symbols(op, profile_name)
    params = opt.resolve_tree(doc['fairbind_parameters'], op, table)
    return dict(id=doc['id'], name=doc['name'], sha256=doc['_sha256'], fairbind_parameters=params)
