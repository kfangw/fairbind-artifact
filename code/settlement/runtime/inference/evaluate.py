"""Open-weights (class 2) predicate pipeline after the authenticated input gate.

`evaluate(bundle, profile)` takes a bundle that the Go gate (`runtime/verifier.Check`)
reported READY or FAIL, opens the class-2 commitment, re-executes the committed
model on the verifier's own copy of the weights with the committed configuration,
applies the committed TOPLOC comparison rule (`binding.verify`) and returns
PASS / FAIL / INCONCLUSIVE with a canonical evidence object.

Any other gate status raises NotJudged: a receipt that does not authenticate is
neither PASS, FAIL nor INCONCLUSIVE. This module cannot run the gate itself; the
Go glue (`pipeline.go`) runs it and is the supported caller.

Request and response bodies use the experimental layouts below. The TOPLOC trace
travels inside the seller-signed response, so a signed response without a trace,
or with a trace that does not open toplocCommitment, is a seller violation (FAIL).

Command line: one JSON document on stdin, one JSON line on stdout. Byte fields
are standard base64. See `pipeline.go` for the exact shape.
"""
import base64
import binascii
import json
import sys

from encoding import canonical, hex32, keccak256, parse_canonical, parse_hex32

PREDICATE_ID = '0xdc77e562812ea60a876f258021aea1da480f6035092b70aa11ca0f5ae1dae9ad'
EVIDENCE_FORMAT = 'fairbind/experimental/inference-evidence/v1'
REQUEST_FORMAT = 'fairbind/experimental/inference-request/v1'
RESPONSE_FORMAT = 'fairbind/experimental/inference-response/v1'
ZERO32 = '0x' + '00' * 32
MAX_TOKENS = 1 << 16
MAX_INPUT = 8 << 20
GATE_ADMITTED = ('READY', 'FAIL')


class NotJudged(Exception):
    """The bundle did not pass the input gate; no verdict is produced."""


def request_body(prompt_ids):
    return canonical({'format': REQUEST_FORMAT, 'version': 1, 'promptIds': list(prompt_ids)})


def response_body(output_ids, trace_bytes):
    return canonical({'format': RESPONSE_FORMAT, 'version': 1, 'outputIds': list(output_ids),
                      'trace': trace_bytes.decode('ascii')})


def _token_ids(value):
    if type(value) is not list or not 1 <= len(value) <= MAX_TOKENS:
        raise ValueError('token list')
    if any(type(v) is not int or not 0 <= v < 2**31 for v in value):
        raise ValueError('token id')
    return value


def _exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('unexpected members')


def parse_request(raw):
    doc = parse_canonical(raw)
    _exact(doc, ['format', 'version', 'promptIds'])
    if doc['format'] != REQUEST_FORMAT or doc['version'] != 1:
        raise ValueError('request format')
    return _token_ids(doc['promptIds'])


def parse_response(raw):
    doc = parse_canonical(raw)
    _exact(doc, ['format', 'version', 'outputIds', 'trace'])
    if doc['format'] != RESPONSE_FORMAT or doc['version'] != 1 or type(doc['trace']) is not str or not doc['trace']:
        raise ValueError('response format')
    return _token_ids(doc['outputIds']), doc['trace'].encode('ascii')


def token_hash(ids):
    return hex32(keccak256(canonical({'tokenIds': list(ids)})))


def evaluate(bundle, profile):
    """Return (verdict, evidence, evidence_bytes).

    bundle: gate {'status', 'reason'} from the Go gate; claims (bytes); preimage
    {toplocCommitment, modelHash, configHash} as 0x hex; predicateCommitment (0x
    hex, from the signed receipt); request and response (bytes, the authenticated
    request body and response body); nonce (0x hex).
    profile: configs {configHash: bytes} and models {modelHash: directory}, the
    manifests and weights available to this verifier.
    """
    gate = bundle.get('gate') or {}
    status, gate_reason = gate.get('status'), str(gate.get('reason') or '')
    if status not in GATE_ADMITTED:
        raise NotJudged(gate_reason or 'no gate result')
    pre = bundle['preimage']
    for key in ('toplocCommitment', 'modelHash', 'configHash'):
        parse_hex32(pre[key])
    evidence = {
        'format': EVIDENCE_FORMAT, 'version': 1, 'predicateId': PREDICATE_ID,
        'nonce': bundle.get('nonce') or ZERO32, 'gate': gate_reason,
        'predicateCommitment': bundle['predicateCommitment'],
        'inputHash': hex32(keccak256(bundle['request'])),
        'responseBodyHash': hex32(keccak256(bundle['response'])),
        'modelHash': pre['modelHash'], 'configHash': pre['configHash'], 'toplocCommitment': pre['toplocCommitment'],
        'sellerOutputHash': ZERO32, 'reexecutedOutputHash': ZERO32, 'reproducedCommitment': ZERO32,
        'comparison': {'verdict': '', 'reason': '', 'recordHash': ZERO32, 'metrics': []},
        'record': '', 'verdict': '', 'reason': '',
    }

    def done(verdict, reason):
        if not evidence['comparison']['verdict']:
            evidence['comparison'].update(verdict=verdict, reason=reason)
        evidence['verdict'], evidence['reason'] = verdict, reason
        raw = canonical(evidence)
        return verdict, evidence, raw

    # A seller-signed receipt with an empty commitment, or an opened commitment
    # contradicting the registered claims, is FAIL without re-execution.
    if status == 'FAIL':
        return done('FAIL', gate_reason)
    if bundle['predicateCommitment'] == ZERO32:
        return done('FAIL', 'empty predicate commitment')
    try:
        prompt_ids = parse_request(bundle['request'])
    except (ValueError, UnicodeError):
        return done('INCONCLUSIVE', 'request outside the inference request format')
    try:
        output_ids, trace_bytes = parse_response(bundle['response'])
    except (ValueError, UnicodeError):
        return done('FAIL', 'signed response does not carry output tokens and the committed trace')
    evidence['sellerOutputHash'] = token_hash(output_ids)
    if keccak256(trace_bytes) != parse_hex32(pre['toplocCommitment']):
        return done('FAIL', 'signed trace does not open toplocCommitment')
    try:
        claims = parse_canonical(bundle['claims'])
    except (ValueError, UnicodeError):
        return done('INCONCLUSIVE', 'claims encoding')
    configs, models = profile.get('configs') or {}, profile.get('models') or {}
    try:
        import binding
        r = binding.verify(claims=claims, preimage=dict(pre), config_bytes=configs.get(pre['configHash']),
                           trace_bytes=trace_bytes, model_dir=models.get(pre['modelHash']),
                           prompt_ids=prompt_ids, output_ids=output_ids,
                           predicate_commitment=bundle['predicateCommitment'])
    except ImportError:
        return done('INCONCLUSIVE', 're-execution runtime unavailable')
    details = r['details'] or {}
    evidence['comparison'] = {'verdict': r['verdict'], 'reason': r['reason'], 'metrics': r['metrics'],
                              'recordHash': details.get('traceHash', ZERO32)}
    evidence['reproducedCommitment'] = details.get('reproducedCommitment', ZERO32)
    if r['record'] is not None:
        evidence['record'] = r['record'].decode('ascii')
    if r.get('reexecuted_output_ids') is not None:
        evidence['reexecutedOutputHash'] = token_hash(r['reexecuted_output_ids'])
    return done(r['verdict'], r['reason'])


def _b64(value):
    if type(value) is not str:
        raise ValueError('base64 string expected')
    return base64.b64decode(value, validate=True)


def decode_input(doc):
    """Decode the command-line document into (bundle, profile)."""
    _exact(doc, ['bundle', 'profile'])
    b, p = doc['bundle'], doc['profile']
    _exact(b, ['gate', 'claims', 'preimage', 'predicateCommitment', 'request', 'response', 'nonce'])
    _exact(p, ['configs', 'models'])
    bundle = dict(gate=b['gate'], preimage=b['preimage'], predicateCommitment=b['predicateCommitment'],
                  nonce=b['nonce'], claims=_b64(b['claims']), request=_b64(b['request']), response=_b64(b['response']))
    profile = {'configs': {k: _b64(v) for k, v in p['configs'].items()},
               'models': {k: v for k, v in p['models'].items() if type(v) is str}}
    return bundle, profile


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    try:
        if len(raw) > MAX_INPUT:
            raise ValueError('input size')
        bundle, profile = decode_input(json.loads(raw))
        verdict, _, evidence = evaluate(bundle, profile)
        out = {'verdict': verdict, 'evidence': evidence.decode('ascii'), 'evidenceHash': hex32(keccak256(evidence))}
    except NotJudged as e:
        out = {'notJudged': str(e)}
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as e:
        print('invalid input: ' + type(e).__name__, file=sys.stderr)
        sys.exit(2)
    print(json.dumps(out, sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
