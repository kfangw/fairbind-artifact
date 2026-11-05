"""Execution binding for the open-weights inference class (predicate class 2).

Seller side: run the committed model and configuration, build TOPLOC proofs from
the final hidden states, and bind them into the receipt's class-specific
`predicateCommitment` through the open-weights preimage
(toplocCommitment, modelHash, configHash).

Verifier side: check the preimage against the authenticated claims, open the
configuration and trace commitments, re-execute the committed model locally and
compare the reproduced activations with the seller's proofs.

The object layouts below (configuration manifest, TOPLOC trace, weight manifest,
comparison record) are experimental. The normative specification fixes only the
preimage words and the predicateCommitment encoding. Hashes of these objects are
keccak256(UTF8(JCS(object))).
"""
from dataclasses import dataclass
from fractions import Fraction
import functools
import hashlib
import json
import math
import re
import sys
from pathlib import Path

from encoding import (canonical, hex32, keccak256, object_hash, open_weights_commitment,
                      parse_canonical, parse_hex32)
import model as runner

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runtime' / 'predicates'))
from toploc_compare import Limits, compare  # noqa: E402

PREDICATE_ID = '0xdc77e562812ea60a876f258021aea1da480f6035092b70aa11ca0f5ae1dae9ad'
CONFIG_FORMAT = 'fairbind/experimental/open-weights-config/v1'
TRACE_FORMAT = 'fairbind/experimental/toploc-trace/v1'
RECORD_FORMAT = 'fairbind/experimental/toploc-comparison/v1'
ZERO32 = '0x' + '00' * 32
MAX_TRACE_BYTES = 1 << 20
DECIMAL = re.compile(r'(0|[1-9][0-9]{0,8})(\.[0-9]{1,6})?')

def toploc_revision():
    lock = json.loads((ROOT / 'UPSTREAMS.lock.json').read_text())
    return next(u['revision'] for u in lock['upstreams'] if u['name'] == 'toploc')

def local_runtime():
    import torch
    import transformers
    return {'torch': torch.__version__.split('+')[0], 'transformers': transformers.__version__,
            'toploc': toploc_revision()}

def config_manifest(*, tokenizer='token-ids', precision='float32', quantization='none',
                    max_new_tokens=8, accelerator='cpu', threads=1, topk=16, decode_batching_size=8,
                    tolerance=(0, '0', '0'), runtime=None):
    """Configuration object committed by configHash. Defaults match the CPU pilot."""
    return {
        'format': CONFIG_FORMAT, 'version': 1,
        'tokenizer': tokenizer, 'promptTemplate': 'none',
        'precision': precision, 'quantization': quantization, 'batchSize': 1,
        'decoding': {'strategy': 'greedy', 'maxNewTokens': max_new_tokens},
        'kernel': {'attention': 'eager', 'threads': threads, 'deterministicAlgorithms': True, 'kvCache': False},
        'runtime': runtime or local_runtime(),
        'accelerator': accelerator,
        'toploc': {'layer': 'final-hidden-state', 'activationDtype': 'bfloat16', 'topk': topk,
                   'decodeBatchingSize': decode_batching_size, 'skipPrefill': False,
                   'tolerance': {'maxExpMismatches': tolerance[0], 'maxMantissaMean': tolerance[1],
                                 'maxMantissaMedian': tolerance[2]}},
    }

def _exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('unexpected members')

def _small_int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('integer out of range')
    return value

def _decimal(value):
    if type(value) is not str or not DECIMAL.fullmatch(value):
        raise ValueError('unsupported decimal')
    return float(Fraction(value))

def check_config(config):
    """Return (limits, reason). reason is None when this verifier supports the configuration."""
    try:
        _exact(config, ['format', 'version', 'tokenizer', 'promptTemplate', 'precision', 'quantization',
                        'batchSize', 'decoding', 'kernel', 'runtime', 'accelerator', 'toploc'])
        _exact(config['decoding'], ['strategy', 'maxNewTokens'])
        _exact(config['kernel'], ['attention', 'threads', 'deterministicAlgorithms', 'kvCache'])
        _exact(config['runtime'], ['torch', 'transformers', 'toploc'])
        t = config['toploc']
        _exact(t, ['layer', 'activationDtype', 'topk', 'decodeBatchingSize', 'skipPrefill', 'tolerance'])
        _exact(t['tolerance'], ['maxExpMismatches', 'maxMantissaMean', 'maxMantissaMedian'])
        topk = _small_int(t['topk'], 1, 1024)
        limits = Limits(_small_int(t['tolerance']['maxExpMismatches'], 0, topk),
                        _decimal(t['tolerance']['maxMantissaMean']), _decimal(t['tolerance']['maxMantissaMedian']))
        _small_int(t['decodeBatchingSize'], 1, 1024)
        _small_int(config['decoding']['maxNewTokens'], 1, 4096)
        _small_int(config['kernel']['threads'], 1, 1024)
    except (ValueError, TypeError, KeyError):
        return None, 'invalid configuration manifest'
    supported = (config['format'] == CONFIG_FORMAT and config['version'] == 1
                 and config['tokenizer'] in ('token-ids', 'model-directory') and config['promptTemplate'] == 'none'
                 and config['precision'] in runner.PRECISIONS and config['quantization'] in runner.QUANTIZATIONS
                 and config['batchSize'] == 1 and config['decoding']['strategy'] == 'greedy'
                 and config['kernel']['attention'] == 'eager' and config['kernel']['deterministicAlgorithms'] is True
                 and config['kernel']['kvCache'] is False and t['layer'] == 'final-hidden-state'
                 and t['activationDtype'] == 'bfloat16' and t['skipPrefill'] is False)
    if not supported:
        return None, 'unsupported configuration'
    if config['runtime'] != local_runtime():
        return None, 'runtime versions differ from the verifier environment'
    if config['accelerator'] != accelerator_name():
        return None, 'accelerator class differs from the verifier environment'
    return limits, None

def accelerator_name():
    import torch
    return 'cuda:' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu'

def _device(config):
    return 'cuda' if config['accelerator'].startswith('cuda:') else 'cpu'

@functools.lru_cache(maxsize=4)
def _load(model_dir, precision, quantization, attention, device):
    return runner.load_model(model_dir, precision, quantization, attention, device)

def load_for(model_dir, config):
    runner.configure_runtime(config['kernel']['threads'])
    return _load(str(Path(model_dir).resolve()), config['precision'], config['quantization'],
                 config['kernel']['attention'], _device(config))

def trace_object(proofs, config):
    t = config['toploc']
    return {'format': TRACE_FORMAT, 'version': 1, 'topk': t['topk'],
            'decodeBatchingSize': t['decodeBatchingSize'], 'skipPrefill': t['skipPrefill'],
            'proofs': ['0x' + p.hex() for p in proofs]}

def build_proofs(activations, config):
    import toploc
    t = config['toploc']
    return toploc.build_proofs_bytes(activations, decode_batching_size=t['decodeBatchingSize'],
                                     topk=t['topk'], skip_prefill=t['skipPrefill'])

def activation_digest(activations):
    import torch
    digest = hashlib.sha256()
    for a in activations:
        digest.update(a.view(torch.uint16).numpy().astype('<u2').tobytes())
    return digest.hexdigest()

@dataclass(frozen=True)
class Served:
    output_ids: list
    config_bytes: bytes
    trace_bytes: bytes
    preimage: dict
    predicate_commitment: str
    activations: list

def commit(model, model_hash, config, prompt_ids):
    """Run `model` and bind its TOPLOC trace to the declared model and configuration.

    The caller declares model_hash and config; this function does not check that
    `model` matches them. An honest seller uses `serve`.
    """
    output_ids, activations = runner.generate(model, prompt_ids, config['decoding']['maxNewTokens'])
    trace_bytes = canonical(trace_object(build_proofs(activations, config), config))
    config_bytes = canonical(config)
    preimage = {'toplocCommitment': hex32(keccak256(trace_bytes)), 'modelHash': model_hash,
                'configHash': hex32(keccak256(config_bytes))}
    commitment = open_weights_commitment(*(parse_hex32(preimage[k]) for k in ('toplocCommitment', 'modelHash', 'configHash')))
    return Served(output_ids, config_bytes, trace_bytes, preimage, hex32(commitment), activations)

def serve(model_dir, config, prompt_ids):
    """Honest seller path: the model hash is computed from the executed checkpoint."""
    return commit(load_for(model_dir, config), hex32(object_hash(runner.weight_manifest(model_dir))), config, prompt_ids)

def claims_object(model_hash, config_hash):
    return {'version': 1, 'classId': 2, 'predicateId': PREDICATE_ID, 'modelHash': model_hash, 'configHash': config_hash}

def _result(verdict, reason, **extra):
    return dict({'verdict': verdict, 'reason': reason, 'metrics': [], 'details': None, 'record': None,
                 'reexecuted_output_ids': None}, **extra)

def verify(*, claims, preimage, config_bytes, trace_bytes, model_dir, prompt_ids, output_ids,
           predicate_commitment=None):
    """Three-way comparison after the authenticated input gate.

    `claims` are the seller's authenticated claims. `preimage` is the opened
    class-2 preimage. `config_bytes` is retrieved by configHash and `model_dir`
    is the verifier's own copy of the public weights. `trace_bytes` is the TOPLOC
    trace from the response bundle and may be None. `prompt_ids`/`output_ids`
    come from the authenticated request and response.
    """
    if preimage is None:
        return _result('INCONCLUSIVE', 'commitment preimage missing')
    try:
        words = {k: parse_hex32(preimage[k]) for k in ('toplocCommitment', 'modelHash', 'configHash')}
        claimed = {k: parse_hex32(claims[k]) for k in ('modelHash', 'configHash')}
    except (ValueError, TypeError, KeyError):
        return _result('INCONCLUSIVE', 'invalid preimage or claims encoding')
    if predicate_commitment is not None:
        if predicate_commitment == ZERO32:
            return _result('FAIL', 'empty predicate commitment')
        if predicate_commitment != hex32(open_weights_commitment(words['toplocCommitment'], words['modelHash'], words['configHash'])):
            return _result('INCONCLUSIVE', 'preimage does not open the receipt commitment')
    if claims.get('predicateId') != PREDICATE_ID or claims.get('classId') != 2:
        return _result('INCONCLUSIVE', 'unsupported claims')
    if words['modelHash'] != claimed['modelHash'] or words['configHash'] != claimed['configHash']:
        return _result('FAIL', 'preimage contradicts authenticated claims')
    if config_bytes is None or keccak256(config_bytes) != words['configHash']:
        return _result('INCONCLUSIVE', 'configuration manifest unavailable')
    try:
        config = parse_canonical(config_bytes)
    except (ValueError, UnicodeError):
        return _result('INCONCLUSIVE', 'configuration manifest is not canonical')
    limits, reason = check_config(config)
    if reason:
        return _result('INCONCLUSIVE', reason)
    if trace_bytes is None:
        return _result('INCONCLUSIVE', 'commitment preimage missing: no TOPLOC trace')
    if len(trace_bytes) > MAX_TRACE_BYTES or keccak256(trace_bytes) != words['toplocCommitment']:
        return _result('INCONCLUSIVE', 'trace does not open toplocCommitment')
    try:
        trace = parse_canonical(trace_bytes)
        _exact(trace, ['format', 'version', 'topk', 'decodeBatchingSize', 'skipPrefill', 'proofs'])
        if trace != trace_object([], config) | {'proofs': trace['proofs']} or type(trace['proofs']) is not list:
            raise ValueError('trace parameters differ from configuration')
        proofs = [bytes.fromhex(p[2:]) for p in trace['proofs'] if type(p) is str and p.startswith('0x')]
        if len(proofs) != len(trace['proofs']):
            raise ValueError('proof encoding')
    except (ValueError, TypeError, UnicodeError):
        return _result('INCONCLUSIVE', 'unsupported trace encoding')
    if (not prompt_ids or not output_ids or len(output_ids) > config['decoding']['maxNewTokens']
            or any(type(v) is not int or v < 0 for v in list(prompt_ids) + list(output_ids))):
        return _result('INCONCLUSIVE', 'request or response outside configuration')
    try:
        if model_dir is None or object_hash(runner.weight_manifest(model_dir)) != words['modelHash']:
            return _result('INCONCLUSIVE', 'committed weights unavailable to verifier')
        model = load_for(model_dir, config)
        if max(list(prompt_ids) + list(output_ids)) >= model.config.vocab_size:
            return _result('INCONCLUSIVE', 'token outside model vocabulary')
        activations, greedy = runner.reproduce(model, prompt_ids, output_ids, with_tokens=True)
        reproduced = canonical(trace_object(build_proofs(activations, config), config))
    except (OSError, ValueError, RuntimeError) as e:
        return _result('INCONCLUSIVE', 're-execution failed: ' + type(e).__name__)
    t = config['toploc']
    comparison = compare(activations, proofs, topk=t['topk'], batch_size=t['decodeBatchingSize'], limits=limits)
    metrics = [{'expMismatches': m['exp_mismatches'], 'mantissaMean': _metric(m['mantissa_mean']),
                'mantissaMedian': _metric(m['mantissa_median'])} for m in comparison['metrics']]
    record = canonical({'format': RECORD_FORMAT, 'version': 1, 'verdict': comparison['verdict'],
                        'reason': comparison['reason'], 'sellerTrace': preimage['toplocCommitment'],
                        'reproducedTrace': hex32(keccak256(reproduced)),
                        'reproducedActivationsSha256': activation_digest(activations), 'metrics': metrics})
    details = {'kind': 'open-weights-inference', 'toplocCommitment': preimage['toplocCommitment'],
               'reproducedCommitment': hex32(keccak256(reproduced)), 'modelHash': preimage['modelHash'],
               'configHash': preimage['configHash'], 'traceHash': hex32(keccak256(record))}
    return _result(comparison['verdict'], comparison['reason'], metrics=metrics, details=details, record=record,
                   reexecuted_output_ids=greedy)

def _metric(value):
    if not math.isfinite(value):
        raise ValueError('invalid metric')
    return repr(float(value))
