"""Strict subprocess codec for the separately identified experimental comparison.

This does not authenticate observations or receipts. Only a worker that has
completed binding checks and independently retrieved references may use results.
The policy is not DATA_API_REFERENCE_V1 and is not installed in any chain profile.
"""
import base64
import json
import sys
from data_reference import Policy, FieldPolicy, Observation, compare

POLICY_ID = '0x1a320b649fe0216a2d3ed2e6692f214cc0784cd6ec04bf3ef6cd230418f3ddd7'
MAX_INPUT = 1_048_576

def pairs(rows):
    out = {}
    for k, v in rows:
        if k in out:
            raise ValueError('duplicate JSON member')
        out[k] = v
    return out

def parse(raw):
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))

def exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('unexpected members')

def integer(value):
    if type(value) is not int or not 0 <= value < 2**53:
        raise ValueError('unsupported integer')
    return value

def evaluate(doc):
    exact(doc, ['policyId', 'policy', 'responseBase64', 'observations'])
    if doc['policyId'] != POLICY_ID:
        raise ValueError('unsupported experimental policy')
    p = doc['policy']
    exact(p, ['source_ids','quorum','reference_time','max_skew','fields'])
    if type(p['source_ids']) is not list or not all(type(x) is str for x in p['source_ids']):
        raise ValueError('source identities')
    if type(p['fields']) is not dict or not 1 <= len(p['fields']) <= 64:
        raise ValueError('fields')
    fields = {}
    for name, f in p['fields'].items():
        exact(f, ['unit','absolute','relative','reference_spread'])
        if not all(type(x) is str for x in f.values()):
            raise ValueError('field values')
        fields[name] = FieldPolicy(**f)
    policy = Policy(tuple(p['source_ids']), integer(p['quorum']),
                    integer(p['reference_time']), integer(p['max_skew']), fields)
    body = base64.b64decode(doc['responseBase64'], validate=True)
    if len(body) > 65536:
        raise ValueError('response size')
    response = parse(body)
    if type(response) is not dict:
        raise ValueError('response object')
    obs = doc['observations']
    if type(obs) is not list or len(obs) > 64:
        raise ValueError('observations')
    rows = []
    for row in obs:
        exact(row, ['source','observed_at','values','units'])
        if type(row['source']) is not str or type(row['values']) is not dict or type(row['units']) is not dict:
            raise ValueError('observation shape')
        integer(row['observed_at'])
        rows.append(Observation(**row))
    r = compare(policy, response, rows)
    return {'policyId': POLICY_ID, 'verdict': r.verdict, 'reason': r.reason,
            'sources': list(r.sources), 'medians': r.medians}

def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('input size')
        result = evaluate(parse(raw))
    except (ValueError, TypeError, KeyError, UnicodeError) as e:
        result = {'policyId': POLICY_ID, 'verdict': 'INCONCLUSIVE',
                  'reason': str(e), 'sources': [], 'medians': None}
    print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False))

if __name__ == '__main__':
    main()
