"""Configure a local FairBind deployment and write the run directory.

Runs after scripts/local_deploy.py --rpc-url on a loopback Anvil whose accounts
are the default test mnemonic. It creates the deadline configurations and
service profiles of a profile document, registers verifiers, a bond account and
one seller, funds the buyers, and writes deployment.json, a deployment manifest
and one JSON configuration per service into the run directory. Every key it
writes is an Anvil default test key; nothing here is fit for a public network.

Role accounts (Anvil default mnemonic indexes):
  0 governance and deployer   1 guardian            2 penalty treasury
  3 verifier reward pool      4 facilitator         5 keeper
  6 seller owner and signer   7 buyer               8 verifier owner and relay
  9 second buyer              10.. verifier signing keys

Data predicate (offline). The seller's claims commit to a source set and a
tolerance policy whose canonical hashes are those of the objects written to
services/verifier/data/: the two ticker sources of the synthetic replay
fixtures in runtime/dataworker/testdata/refsource/replay, a quorum of both, the
fixtures' reference time and a price tolerance. Every verifier configuration
registers the data pipeline with the replay provider over that directory, so no
network is used. The seller serves a fixed quote chosen inside the tolerance of
the fixtures' median: Coinbase 64231.57 and Kraken 64229.8 give the median
64230.685, the bound is 5 + 0.001 * 64230.685 = 69.23..., and the quote price
64230.68 is judged PASS. The pipeline runs only for the experimental predicate
identifier (EXPERIMENTAL_DATA_PREDICATE); a profile with the normative
DATA_API_REFERENCE_V1 identifier gets an INCONCLUSIVE envelope. Changing the
quote, the policy or the fixtures changes the verdict.

Inference predicate. Off unless --inference-model-dir names a local checkpoint
directory; then each verifier configuration also registers the re-execution
pipeline (runtime/inference/evaluate.py) with that directory and
--inference-config-dir (configuration manifests keyed by the Keccak-256 of their
bytes; default: the model directory).

Harness block. A profile document with a top-level `harness` object (written by
experiments/controller for the hold-period grid; keys in HARNESS_KEYS) changes
the setup; without one the setup is as described above.
  - The bond account holds sellerBondScale * sellerPenalty.
  - registeredVerifiers verifiers register: the first assignableVerifiers with
    verifierBondAtomic, the rest with the largest minVerifierBond (below the
    assignment floor, so they count toward minVerifiers but are never assigned).
    deployment.json records `assignable` per verifier. The verifier tree is
    checkpointed after the registrations.
  - spareVerifiers identities (mnemonic indexes right after the registered
    verifiers' keys) get a keystore and a verifier configuration with
    verifierId 0 under services/verifier/spare-<k>/, but are not registered;
    deployment.json lists them under `spares`. A spare signing key sends no
    transaction and needs no ether: the verifier owner registers it (mint,
    approve, registerVerifier with the spare's bond), anyone checkpoints the
    tree, and the replacer writes the returned id into the configuration.
  - With cheatBody the seller's route gets cheatBodyFile (cheat-quote.json: the
    same preimage, a price the data pipeline judges FAIL).
  - pollMs sets the keeper's pollIntervalMs, the seller's tickMs, the buyers'
    tickSeconds (rounded up to whole seconds) and the verifiers' pollIntervalMs
    when services/verifier/config.go has that field, else pollIntervalSeconds
    rounded up (the verifier decoder rejects unknown fields).
  - The buyer is funded for buyerPurchases purchases when that exceeds the default
    1,000 (the controller's expected purchase count of the run, with margin).
  - The seller owner and the buyer receive APPEAL_DEPOSITS appeal deposits, or
    buyerPurchases deposits when that is more; the
    seller owner approves the contract without limit (appeals and top-ups).
"""
import argparse, json, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PPM = 1_000_000
MNEMONIC = 'test test test test test test test test test test test junk'
ROLES = {'governance': 0, 'guardian': 1, 'penaltyTreasury': 2, 'verifierRewardPool': 3, 'facilitator': 4,
         'keeper': 5, 'seller': 6, 'buyer': 7, 'verifier': 8, 'buyer2': 9}
VERIFIER_KEY_BASE = 10
DEADLINE_FIELDS = ['anchorBlocks', 'sealBlocks', 'openBlocks', 'responseBlocks', 'claimBlocks', 'serveBlocks',
                   'judgeBlocks', 'evidenceBlocks', 'appealBlocks']
# ServiceProfileInput field order (contracts/src/FairBindCore.sol).
PROFILE_FIELDS = ['classId', 'predicateId', 'canonId', 'epochOrigin', 'epochBlocks', 'samplePpm', 'effectivePpm',
                  'recheckPpm', 'bucketCapacity', 'refillPpmPerBlock', 'maxRatePpmPerBlock', 'enforcementBlocks',
                  'deferBlocks', 'retentionBlocks', 'marginBlocks', 'maxRequestBytes', 'maxResponseBytes',
                  'maxEvidenceBytes', 'maxPublicationCost', 'maxReviewCost', 'maxPurchaseValue', 'maxBadGain',
                  'sellerPenalty', 'minVerifierBond', 'verifierBondCap', 'verifierLatePenalty', 'verifierWrongPenalty',
                  'disputeDeposit', 'appealDeposit', 'verifierExposurePpm', 'maxAssignments', 'minVerifiers',
                  'strikeLimit', 'deadlineConfigId', 'beaconDelayBlocks', 'beaconSlackL1Blocks', 'claimWindowBlocks',
                  'failureLimit', 'failureWindowBlocks', 'maxInconclusivePpm', 'inconclusiveWindowBlocks',
                  'forfeitVerifierPpm', 'freezeOnInitialFail', 'minJudgedCount', 'parameterHash']
PROFILE_TUPLE = ('(uint16,bytes32,bytes32,uint64,uint32,uint32,uint32,uint32,uint32,uint32,uint32,uint32,uint32,'
                 'uint32,uint32,uint32,uint32,uint32,uint96,uint96,uint96,uint96,uint96,uint96,uint96,uint96,uint96,'
                 'uint96,uint96,uint32,uint16,uint16,uint16,uint32,uint32,uint32,uint32,uint32,uint32,uint32,uint32,'
                 'uint32,bool,uint32,bytes32)')
SERVICE_CLASS = {1: 'data-api', 2: 'open-weights-inference'}
# SHA-256 of "fairbind/experimental/data-decimal-median/v1" (docs/decisions/0010).
EXPERIMENTAL_DATA_PREDICATE = '0x1a320b649fe0216a2d3ed2e6692f214cc0784cd6ec04bf3ef6cd230418f3ddd7'
REPLAY_DIR = ROOT / 'runtime' / 'dataworker' / 'testdata' / 'refsource' / 'replay'
DATA_SOURCES = ['coinbase-exchange:ticker:BTC-USD', 'kraken:ticker:XBTUSD']
DATA_REFERENCE_TIME = 1790000000
# runtime/dataworker Policy and SourceSet layouts.
DATA_POLICY = {'source_ids': DATA_SOURCES, 'quorum': 2, 'reference_time': DATA_REFERENCE_TIME, 'max_skew': 30,
               'fields': {'price': {'unit': 'USD', 'absolute': '5', 'relative': '0.001', 'reference_spread': '50'}}}
DATA_SOURCE_SET = {'sources': DATA_SOURCES}
SELLER_QUOTE = {'price': '64230.68', 'symbol': 'BTC-USD'}
TOKEN_NAME, TOKEN_VERSION = 'MockUSDC', '2'
# Top-level `harness` block of a profile document (experiments/controller/profile.py harness).
HARNESS_KEYS = ('sellerBondScale', 'registeredVerifiers', 'assignableVerifiers', 'verifierBondAtomic',
                'spareVerifiers', 'cheatBody', 'pollMs', 'buyerPurchases')
# Wrong body of the cheated sales: the route's preimage with a price far outside the tolerance.
CHEAT_QUOTE = {'price': '1.00', 'symbol': 'BTC-USD'}
# Appeal deposits minted to the seller owner and to the buyer under a harness block.
APPEAL_DEPOSITS = 10_000
# Purchases every buyer is funded for; a harness block's buyerPurchases raises it for the buyer.
BUYER_PURCHASES = 1_000


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


class Chain:
    def __init__(self, url, cast):
        self.url, self.cast_path = url, cast

    def rpc(self, method, params):
        req = urllib.request.Request(self.url, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method,
                                                           'params': params}).encode(),
                                     {'Content-Type': 'application/json'})
        out = json.load(urllib.request.urlopen(req, timeout=30))
        if 'error' in out:
            raise RuntimeError(f'{method}: {out["error"]}')
        return out['result']

    def cast(self, *args):
        res = subprocess.run([self.cast_path, *args], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f'cast {args[0]} {args[1] if len(args) > 1 else ""}: {res.stderr.strip()}')
        return res.stdout.strip()

    def cast_location(self):
        return subprocess.run(['sh', '-c', f'command -v {self.cast_path}'], capture_output=True,
                              text=True).stdout.strip()

    def keccak(self, data):
        return self.cast('keccak', '0x' + data.hex())

    def head(self):
        return int(self.rpc('eth_blockNumber', []), 16)

    def call(self, sender, to, sig, *args):
        return self.cast('call', '--rpc-url', self.url, '--from', sender, to, sig, *map(str, args))

    def send(self, sender, to, sig, *args):
        out = self.cast('send', '--json', '--rpc-url', self.url, '--unlocked', '--from', sender, to, sig,
                        *map(str, args))
        rec = json.loads(out)
        if int(rec['status'], 16) != 1:
            raise RuntimeError(f'{sig} reverted: {rec["transactionHash"]}')
        return rec['transactionHash']


def key_at(chain, index):
    return chain.cast('wallet', 'private-key', '--mnemonic', MNEMONIC, '--mnemonic-index', str(index))


def addr_of(chain, key):
    return chain.cast('wallet', 'address', '--private-key', key)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


class HarnessError(ValueError):
    pass


def parse_harness(doc, profile_params, verifiers_flag=0):
    """The validated `harness` block at the top level of the profile document, or None.

    Every key of HARNESS_KEYS is required and no other key is accepted. verifierBondAtomic is
    returned as an int (the document may carry it as a decimal string)."""
    block = doc.get('harness')
    if block is None:
        return None
    if not isinstance(block, dict):
        raise HarnessError('harness must be an object')
    unknown, missing = sorted(set(block) - set(HARNESS_KEYS)), sorted(set(HARNESS_KEYS) - set(block))
    if unknown or missing:
        raise HarnessError(f'harness keys: unknown {unknown}, missing {missing}')

    def integer(name, least):
        v = block[name]
        if isinstance(v, bool) or not isinstance(v, int) or v < least:
            raise HarnessError(f'harness {name} must be an integer >= {least}')
        return v

    h = {'sellerBondScale': integer('sellerBondScale', 1), 'registeredVerifiers': integer('registeredVerifiers', 1),
         'assignableVerifiers': integer('assignableVerifiers', 1), 'spareVerifiers': integer('spareVerifiers', 0),
         'pollMs': integer('pollMs', 1), 'buyerPurchases': integer('buyerPurchases', 1)}
    bond = block['verifierBondAtomic']
    if isinstance(bond, str) and bond.isdigit():
        bond = int(bond)
    if isinstance(bond, bool) or not isinstance(bond, int) or bond < 1:
        raise HarnessError('harness verifierBondAtomic must be a positive integer or decimal string')
    h['verifierBondAtomic'] = bond
    if not isinstance(block['cheatBody'], bool):
        raise HarnessError('harness cheatBody must be a boolean')
    h['cheatBody'] = block['cheatBody']
    if h['assignableVerifiers'] > h['registeredVerifiers']:
        raise HarnessError('harness assignableVerifiers exceeds registeredVerifiers')
    least = max(int(p['minVerifiers']) for p in profile_params)
    if h['registeredVerifiers'] < least:
        raise HarnessError(f'harness registeredVerifiers {h["registeredVerifiers"]} is below the largest '
                           f'minVerifiers {least}')
    min_bond = max(int(p['minVerifierBond']) for p in profile_params)
    if bond < min_bond:
        raise HarnessError(f'harness verifierBondAtomic {bond} is below the largest minVerifierBond {min_bond}')
    if verifiers_flag and verifiers_flag != h['registeredVerifiers']:
        raise HarnessError(f'--verifiers {verifiers_flag} disagrees with harness registeredVerifiers '
                           f'{h["registeredVerifiers"]}')
    return h


def verifier_bonds(profile_params, harness, verifiers_flag=0):
    """(bond, assignable) of every verifier to register, in registration order.

    Without a harness block every verifier gets the largest minVerifierBond or, when larger, the
    smallest verifierBondCap, and assignable is None (not recorded). With one, the first
    assignableVerifiers verifiers get verifierBondAtomic and the rest the largest minVerifierBond."""
    min_bond = max(int(p['minVerifierBond']) for p in profile_params)
    if harness is None:
        least = max(int(p['minVerifiers']) for p in profile_params)
        count = verifiers_flag or least
        if count < least:
            raise HarnessError(f'--verifiers {count} is below the largest minVerifiers {least} of the profile document')
        # Assignment needs (bond - reserved penalties) * verifierExposurePpm to cover
        # value + maxReviewCost of every open assignment, so a bond at the minimum is
        # never assigned. Bond at the smallest verifierBondCap (the most that counts).
        bond = max(min_bond, min(int(p['verifierBondCap']) for p in profile_params))
        return [(bond, None)] * count
    n, r = harness['assignableVerifiers'], harness['registeredVerifiers']
    return [(harness['verifierBondAtomic'], True)] * n + [(min_bond, False)] * (r - n)


def spare_key_indexes(harness):
    """Mnemonic indexes of the spare verifier signing keys: the indexes right after the registered
    verifiers' keys, so they never collide with them and do not depend on the run."""
    if harness is None:
        return []
    first = VERIFIER_KEY_BASE + harness['registeredVerifiers']
    return list(range(first, first + harness['spareVerifiers']))


def seller_bond_amount(params, harness):
    return int(params['sellerPenalty']) * (harness['sellerBondScale'] if harness else 1)


def buyer_funding(params, harness):
    """Tokens minted to a buyer: BUYER_PURCHASES purchases of maxPurchaseValue, or the harness
    block's buyerPurchases when larger, and four dispute deposits."""
    purchases = max(BUYER_PURCHASES, harness['buyerPurchases'] if harness else 0)
    return purchases * int(params['maxPurchaseValue']) + 4 * int(params['disputeDeposit'])


def appeal_funding(params, harness):
    """Tokens minted to the seller owner and to the buyer for appeal deposits (0 without a harness):
    APPEAL_DEPOSITS deposits, or one per purchase the buyer is funded for when that is more (every
    sale can be appealed once, and a lost appeal keeps its deposit)."""
    if not harness:
        return 0
    return max(APPEAL_DEPOSITS, harness['buyerPurchases']) * int(params['appealDeposit'])


def poll_fields(harness, verifier_poll_ms):
    """Poll settings per service. The keeper takes milliseconds; the seller takes milliseconds
    (tickMs) under a harness block and whole seconds otherwise; the buyers take whole seconds
    (tickSeconds, rounded up); the verifier takes pollIntervalMs only when its parser accepts it
    (verifier_poll_ms), otherwise pollIntervalSeconds rounded up."""
    if harness is None:
        return {'keeper': {'pollIntervalMs': 500}, 'tick': {'tickSeconds': 1}, 'seller': {'tickSeconds': 1},
                'verifier': {'pollIntervalSeconds': 1}}
    ms = harness['pollMs']
    seconds = max(1, -(-ms // 1000))
    return {'keeper': {'pollIntervalMs': ms}, 'tick': {'tickSeconds': seconds}, 'seller': {'tickMs': ms},
            'verifier': {'pollIntervalMs': ms} if verifier_poll_ms else {'pollIntervalSeconds': seconds}}


def verifier_accepts_poll_ms(root=ROOT):
    """Whether the verifier configuration parser (services/verifier/config.go) has a pollIntervalMs
    field. Its decoder rejects unknown fields, so the field is written only when it exists."""
    try:
        return 'json:"pollIntervalMs' in (root / 'services' / 'verifier' / 'config.go').read_text()
    except OSError:
        return False


def service_files(s):
    """Every file of the run directory's services/ tree except the verifier keystores, as
    {path: content}: a dict or list is written as indented JSON, bytes and str as they are.

    `s` holds the setup state: run, common, router, token, addrs, keys, network, ports, urls,
    cast_path, sp (the seller's profile entry), created, seller_id, source_set, tolerance, claims,
    verifiers, spares, harness, verifier_poll_ms, inference_predicate."""
    svc = s['run'] / 'services'
    common, router, addrs, urls, ports = s['common'], s['router'], s['addrs'], s['urls'], s['ports']
    sp, params, harness = s['sp'], s['sp']['parameters'], s['harness']
    poll = poll_fields(harness, s['verifier_poll_ms'])
    files = {}
    files[svc / 'keeper' / 'keeper.json'] = dict(common, contract=router, **{
        'from': addrs['keeper'], 'gas': 5_000_000, 'stateFile': str(svc / 'keeper' / 'state.json'),
        'startBlock': 0, **poll['keeper'], 'rpcTimeoutMs': 10000, 'maxLogRange': 5000,
        'resendAfterBlocks': 20})
    files[svc / 'facilitator' / 'facilitator.json'] = dict(common, **{
        'listen': f'127.0.0.1:{ports["facilitator"]}', 'dataDir': str(svc / 'facilitator' / 'data'),
        'network': s['network'], 'contract': router, 'from': addrs['facilitator'], 'token': s['token'],
        'tokenName': TOKEN_NAME, 'tokenVersion': TOKEN_VERSION,
        'settlementSchema': str(ROOT / 'schemas' / 'fairbind-settlement-v1.schema.json')})
    files[svc / 'seller' / 'claims.json'] = s['claims']
    files[svc / 'seller' / 'quote.json'] = json.dumps(SELLER_QUOTE, separators=(',', ':')) + '\n'
    files[svc / 'seller' / 'seller.key'] = s['keys']['seller'] + '\n'
    headers = sorted(params.get('canonicalHeaders', ['accept']))
    route = {'path': '/v1/quote', 'description': 'Signed market quote', 'mimeType': 'application/json',
             'bodyFile': str(svc / 'seller' / 'quote.json'),
             'preimage': {'kind': 'data-api', 'referenceTime': str(DATA_REFERENCE_TIME),
                          'sourceSetHash': s['source_set'], 'tolerancePolicyHash': s['tolerance']}}
    if harness and harness['cheatBody']:
        # Served with the route's preimage on the sales the seller cheats on; the data pipeline
        # judges it FAIL (tolerance exceeded).
        files[svc / 'seller' / 'cheat-quote.json'] = json.dumps(CHEAT_QUOTE, separators=(',', ':')) + '\n'
        route['cheatBodyFile'] = str(svc / 'seller' / 'cheat-quote.json')
    seller_cfg = dict(common, **{
        'listen': f'127.0.0.1:{ports["seller"]}', 'dataDir': str(svc / 'seller' / 'data'),
        'publicUrl': urls['seller'], 'network': s['network'], 'contract': router, 'owner': addrs['seller'],
        'sellerId': s['seller_id'], 'signingKeyFile': str(svc / 'seller' / 'seller.key'),
        'facilitatorUrl': urls['facilitator'], 'serviceName': 'Local evaluation API',
        'serviceClass': SERVICE_CLASS[sp['classId']], 'profileHash': sp['parameterHash'],
        'canonicalHeaders': headers, 'price': int(params['maxPurchaseValue']), 'maxTimeoutSeconds': 300,
        'tokenName': TOKEN_NAME, 'tokenVersion': TOKEN_VERSION,
        'extensionSchema': str(ROOT / 'schemas' / 'fairbind-extension-v1.schema.json'),
        'settlementSchema': str(ROOT / 'schemas' / 'fairbind-settlement-v1.schema.json'),
        'claimsFile': str(svc / 'seller' / 'claims.json'), **poll['seller'],
        'routes': [route] if sp['classId'] == 1 else []})
    files[svc / 'seller' / 'seller.json'] = seller_cfg
    for role in ('buyer', 'buyer2'):
        files[svc / role / 'buyer.key'] = s['keys'][role] + '\n'
        files[svc / role / 'buyer.json'] = dict(common, **{
            'listen': f'127.0.0.1:{ports[role]}', 'dataDir': str(svc / role / 'data'), 'network': s['network'],
            'contract': router, 'keyFile': str(svc / role / 'buyer.key'),
            'maxPrice': int(params['maxPurchaseValue']), **poll['tick']})
    password = svc / 'verifier' / 'password'
    files[password] = 'local-evaluation\n'
    # Predicate pipelines shared by every verifier.
    data_dir = svc / 'verifier' / 'data'
    files[data_dir / 'policy.json'] = canonical_json(DATA_POLICY) + b'\n'
    files[data_dir / 'sources.json'] = canonical_json(DATA_SOURCE_SET) + b'\n'
    data_profiles = [p for p in s['created'] if p['classId'] == 1]
    data_predicate = {'timeoutSeconds': 15,
                      'references': {'mode': 'replay', 'replayDir': str(REPLAY_DIR), 'allowSynthetic': True},
                      'profiles': {str(p['profileId']): {'policyFile': str(data_dir / 'policy.json'),
                                                         'sourceSetFile': str(data_dir / 'sources.json')}
                                   for p in data_profiles}}

    def verifier_cfg(verifier_id, vdir, keystore):
        return dict(s['common'], **{
            'contract': router, 'verifierId': verifier_id, 'keystore': str(keystore),
            'passwordFile': str(password), 'castPath': s['cast_path'], 'stateDir': str(vdir / 'state'),
            **poll['verifier'], 'startBlock': 0, 'maxLogRange': 5000, 'submitMarginBlocks': 4,
            'relay': {'from': addrs['verifier'], 'gas': 5_000_000},
            'sellers': {str(s['seller_id']): urls['seller']},
            'profiles': {str(p['profileId']): ({'sourceSetHash': s['source_set'], 'tolerancePolicyHash': s['tolerance']}
                                               if p['profileId'] == sp['profileId'] else {}) for p in s['created']}},
            **({'dataPredicate': data_predicate} if data_profiles else {}),
            **({'inferencePredicate': s['inference_predicate']} if s['inference_predicate'] else {}))

    for v in s['verifiers']:
        files[Path(v['config'])] = verifier_cfg(v['verifierId'], Path(v['config']).parent, v['keystore'])
    for sv in s['spares']:
        # verifierId 0 is a placeholder the verifier parser rejects: the replacer writes the id
        # that registerVerifier returns before starting a worker on this file.
        files[Path(sv['config'])] = verifier_cfg(0, Path(sv['config']).parent, sv['keystore'])
    return files


def verifier_entries(run, registered, spare_keys, owner, bitmap, spare_bond):
    """deployment.json entries of the registered verifiers and the spare identities, with their
    keystore and configuration paths. `registered` is [(verifierId, signingKey, privateKey, bond,
    assignable)], `spare_keys` [(mnemonicIndex, signingKey, privateKey)]."""
    vroot = run / 'services' / 'verifier'
    verifiers = []
    for vid, vaddr, vkey, bond, assignable in registered:
        vdir = vroot / str(vid)
        v = {'verifierId': vid, 'signingKey': vaddr, 'privateKey': vkey, 'owner': owner, 'bond': str(bond),
             'classBitmap': bitmap}
        if assignable is not None:
            v['assignable'] = assignable
        v['keystore'] = str(vdir / 'keystore' / f'verifier-{vid}')
        v['config'] = str(vdir / 'verifier.json')
        verifiers.append(v)
    spares = []
    for k, (index, vaddr, vkey) in enumerate(spare_keys, start=1):
        vdir = vroot / f'spare-{k}'
        spares.append({'spare': k, 'mnemonicIndex': index, 'signingKey': vaddr, 'privateKey': vkey, 'owner': owner,
                       'bond': str(spare_bond), 'classBitmap': bitmap, 'registered': False,
                       'keystore': str(vdir / 'keystore' / f'spare-{k}'), 'config': str(vdir / 'verifier.json')})
    return verifiers, spares


def deployment_document(s):
    """deployment.json. Without a harness block it has exactly the fields of earlier runs."""
    report, run, svc = s['report'], s['run'], s['run'] / 'services'
    deploy = report['deployments']
    created, sp, addrs = s['created'], s['sp'], s['addrs']
    # The keystore path is internal to the setup; deployment.json keeps its earlier verifier fields.
    verifiers = [{k: v for k, v in e.items() if k != 'keystore'} for e in s['verifiers']]
    deployment = {
        'formatVersion': 1, 'note': 'Local evaluation only. Every key is an Anvil default test key.',
        'createdAt': s['created_at'], 'commit': report['commit'],
        'dirty': report.get('dirty', False), 'build': report['build'], 'anvil': report['anvil'], 'admissionOverride': report['admission_override'],
        'network': s['network'], 'chainId': s['chain_id'], 'rpcUrl': s['common']['rpcUrl'], 'contract': s['router'],
        'token': s['token'], 'tokenName': TOKEN_NAME, 'tokenVersion': TOKEN_VERSION,
        'profileDocument': s['profile_document'],
        'modules': {k: v['address'] for k, v in deploy.items() if k not in ('FairBind', 'MockEIP3009Token')},
        'profiles': [{k: v for k, v in p.items() if k != 'parameters'} for p in created],
        'bond': {'bondId': s['bond_id'], 'profileId': sp['profileId'], 'owner': addrs['seller'],
                 'amount': str(s['seller_bond'])},
        'seller': {'sellerId': s['seller_id'], 'bondId': s['bond_id'], 'profileId': sp['profileId'],
                   'owner': addrs['seller'], 'signingKey': addrs['seller'], 'claimsHash': s['claims_hash'],
                   'url': s['urls']['seller']},
        'verifiers': verifiers,
        'roles': {role: {'address': addrs[role], 'privateKey': s['keys'][role], 'mnemonicIndex': ROLES[role]}
                  for role in ROLES},
        'services': {'keeper': str(svc / 'keeper' / 'keeper.json'),
                     'facilitator': str(svc / 'facilitator' / 'facilitator.json'),
                     'seller': str(svc / 'seller' / 'seller.json'), 'buyer': str(svc / 'buyer' / 'buyer.json'),
                     'buyer2': str(svc / 'buyer2' / 'buyer.json'),
                     'verifiers': [v['config'] for v in verifiers]},
        'urls': s['urls'], 'setupBlock': s['setup_block'], 'deployReport': s['deploy_report']}
    h = s['harness']
    if h is not None:
        deployment['harness'] = dict(h, verifierBondAtomic=str(h['verifierBondAtomic']),
                                     appealFunding=str(s['appeal_funding']),
                                     verifierPollMs=bool(s['verifier_poll_ms']))
        deployment['spares'] = s['spares']
    return deployment


def write_files(files):
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        elif isinstance(content, str):
            path.write_text(content)
        else:
            write_json(path, content)


def import_keystore(chain, path, private_key):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        chain.cast('wallet', 'import', path.name, '--private-key', private_key, '--keystore-dir', str(path.parent),
                   '--unsafe-password', 'local-evaluation')


def setup(a, chain, now=None):
    run = Path(a.run_dir).resolve()
    run.mkdir(parents=True, exist_ok=True)
    report = json.loads(Path(a.report).read_text())
    doc = json.loads(Path(a.profile).read_text())
    router, token = report['router'], report['token']
    accounts = chain.rpc('eth_accounts', [])
    keys = {role: key_at(chain, i) for role, i in ROLES.items()}
    addrs = {role: addr_of(chain, k) for role, k in keys.items()}
    for role, i in ROLES.items():
        if accounts[i].lower() != addrs[role].lower():
            raise SystemExit(f'Anvil account {i} is not the default test mnemonic account')
    gov, seller_owner, verifier_owner = addrs['governance'], addrs['seller'], addrs['verifier']
    if report['roles']['governance'].lower() != gov.lower():
        raise SystemExit('deployment governance is not account 0')

    profiles = doc['profiles']
    if not profiles:
        raise SystemExit('profile document has no profiles')
    try:
        harness = parse_harness(doc, [p['parameters'] for p in profiles], a.verifiers)
        bonds = verifier_bonds([p['parameters'] for p in profiles], harness, a.verifiers)
    except HarnessError as e:
        raise SystemExit(str(e))
    origin = max(int(p['parameters']['epochOrigin']) for p in profiles)
    head = chain.head()
    if head < origin:
        chain.rpc('anvil_mine', [hex(origin - head)])

    created = []
    for prof in profiles:
        pid, params = int(prof['profileId']), prof['parameters']
        doc_hash = prof.get('parameterHash')
        param_hash = chain.keccak(canonical_json(params))
        deadlines = params['deadlineConfig']
        chain.send(gov, router, 'createDeadlineConfig(uint32,(uint32,uint32,uint32,uint32,uint32,uint32,uint32,'
                   'uint32,uint32))', pid, '(' + ','.join(str(deadlines[f]) for f in DEADLINE_FIELDS) + ')')
        values = dict(params, deadlineConfigId=pid, parameterHash=param_hash)
        # cast encodes a bool from the literal true/false.
        values['freezeOnInitialFail'] = 'true' if params['freezeOnInitialFail'] else 'false'
        tup = '(' + ','.join(str(values[f]) for f in PROFILE_FIELDS) + ')'
        chain.send(gov, router, f'createServiceProfile(uint32,{PROFILE_TUPLE})', pid, tup)
        created.append({'profileId': pid, 'name': prof.get('name', ''), 'classId': int(params['classId']),
                        'parameterHash': param_hash, 'documentParameterHash': doc_hash,
                        'parameterHashRecomputed': doc_hash != param_hash, 'deadlineConfigId': pid,
                        'parameters': params})

    # Verifiers: one registration per signing key, all owned by the verifier role account.
    # Below the largest minVerifiers no profile of the document is available (ADR 0023).
    bitmap = 0
    for p in created:
        bitmap |= 1 << p['classId']
    total = sum(b for b, _ in bonds)
    chain.send(verifier_owner, token, 'mint(address,uint256)', verifier_owner, total)
    chain.send(verifier_owner, token, 'approve(address,uint256)', router, total)
    registered = []
    for i, (bond, assignable) in enumerate(bonds):
        vkey = key_at(chain, VERIFIER_KEY_BASE + i)
        vaddr = addr_of(chain, vkey)
        vid = int(chain.call(verifier_owner, router, 'registerVerifier(uint256,address,uint128)(uint32)',
                             bitmap, vaddr, bond).split()[0])
        chain.send(verifier_owner, router, 'registerVerifier(uint256,address,uint128)', bitmap, vaddr, bond)
        registered.append((vid, vaddr, vkey, bond, assignable))
    for p in created:
        chain.send(gov, router, 'checkpointVerifierTree(uint32)', p['profileId'])
        chain.send(gov, router, 'setServiceProfileActive(uint32,bool)', p['profileId'], 'true')
    spare_keys = []
    for index in spare_key_indexes(harness):
        vkey = key_at(chain, index)
        spare_keys.append((index, addr_of(chain, vkey), vkey))
    verifiers, spares = verifier_entries(run, registered, spare_keys, verifier_owner, bitmap,
                                         harness['verifierBondAtomic'] if harness else 0)

    # Bond account and seller.
    sp = next((p for p in created if (a.seller_profile and p['profileId'] == a.seller_profile)
               or (not a.seller_profile and p['classId'] == 1)), None)
    if sp is None:
        raise SystemExit('no profile for the seller')
    params = sp['parameters']
    if sp['classId'] == 1:
        # Canonical hashes of the manifests the verifiers load (dataworker.ObjectHash).
        source_set, tolerance = chain.keccak(canonical_json(DATA_SOURCE_SET)), chain.keccak(canonical_json(DATA_POLICY))
    else:
        source_set = chain.keccak(b'fairbind/local-evaluation/source-set')
        tolerance = chain.keccak(b'fairbind/local-evaluation/tolerance-policy')
    a_name, b_name = ('sourceSetHash', 'tolerancePolicyHash') if sp['classId'] == 1 else ('modelHash', 'configHash')
    claims = canonical_json({'version': 1, 'classId': sp['classId'], 'predicateId': params['predicateId'].lower(),
                             a_name: source_set, b_name: tolerance})
    claims_hash = chain.keccak(claims)
    seller_bond = seller_bond_amount(params, harness)
    chain.send(seller_owner, token, 'mint(address,uint256)', seller_owner, seller_bond)
    chain.send(seller_owner, token, 'approve(address,uint256)', router, seller_bond)
    bond_id = int(chain.call(seller_owner, router, 'registerBond(uint32,uint128)(uint32)', sp['profileId'],
                             seller_bond).split()[0])
    chain.send(seller_owner, router, 'registerBond(uint32,uint128)', sp['profileId'], seller_bond)
    seller_id = int(chain.call(seller_owner, router, 'registerSeller(uint32,uint32,address,bytes32)(uint32)',
                               bond_id, sp['profileId'], seller_owner, claims_hash).split()[0])
    chain.send(seller_owner, router, 'registerSeller(uint32,uint32,address,bytes32)', bond_id, sp['profileId'],
               seller_owner, claims_hash)

    # Buyers: funds for purchases and the dispute deposit, approved to the contract.
    for role in ('buyer', 'buyer2'):
        buyer_funds = buyer_funding(params, harness if role == 'buyer' else None)
        chain.send(addrs[role], token, 'mint(address,uint256)', addrs[role], buyer_funds)
        chain.send(addrs[role], token, 'approve(address,uint256)', router, 2**256 - 1)
    # Harness: appeal deposits for the seller owner (every initial FAIL) and the buyer (every
    # initial PASS in the honest arm); the seller owner's allowance also covers bond top-ups.
    funding = appeal_funding(params, harness)
    if funding:
        chain.send(seller_owner, token, 'mint(address,uint256)', seller_owner, funding)
        chain.send(seller_owner, token, 'approve(address,uint256)', router, 2**256 - 1)
        chain.send(addrs['buyer'], token, 'mint(address,uint256)', addrs['buyer'], funding)

    # Service files.
    inference_predicate = None
    if a.inference_model_dir:
        model_dir = Path(a.inference_model_dir).resolve()
        config_dir = Path(a.inference_config_dir).resolve() if a.inference_config_dir else model_dir
        inference_predicate = {'python': a.python, 'script': str(ROOT / 'runtime' / 'inference' / 'evaluate.py'),
                               'modelDir': str(model_dir), 'configDir': str(config_dir), 'timeoutSeconds': 600}
    port = a.base_port
    ports = {'facilitator': port, 'seller': port + 1, 'buyer': port + 2, 'buyer2': port + 3}
    chain_id = int(chain.rpc('eth_chainId', []), 16)
    state = dict(run=run, report=report, router=router, token=token, addrs=addrs, keys=keys,
                 network=f'eip155:{chain_id}', chain_id=chain_id, common={'rpcUrl': chain.url, 'chainId': chain_id},
                 ports=ports, urls={k: f'http://127.0.0.1:{v}' for k, v in ports.items()},
                 cast_path=chain.cast_location(), sp=sp, created=created, seller_id=seller_id, bond_id=bond_id,
                 seller_bond=seller_bond, source_set=source_set, tolerance=tolerance, claims=claims,
                 claims_hash=claims_hash, verifiers=verifiers, spares=spares, harness=harness,
                 verifier_poll_ms=bool(harness) and verifier_accepts_poll_ms(), appeal_funding=funding,
                 inference_predicate=inference_predicate)
    for d in ('keeper', 'facilitator', 'seller', 'buyer', 'buyer2', 'verifier'):
        (run / 'services' / d).mkdir(parents=True, exist_ok=True)
    write_files(service_files(state))
    for v, (_, _, vkey, _, _) in zip(verifiers, registered):
        import_keystore(chain, Path(v['keystore']), vkey)
    for sv in spares:
        import_keystore(chain, Path(sv['keystore']), sv['privateKey'])

    state.update(created_at=now or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), setup_block=chain.head(),
                 profile_document=str(Path(a.profile).resolve()), deploy_report=str(Path(a.report).resolve()))
    deployment = deployment_document(state)
    write_json(run / 'deployment.json', deployment)
    # The fields of schemas/deployment-manifest-v1.schema.json.
    deploy = report['deployments']
    write_json(run / 'manifest.json', {
        'formatVersion': 1, 'network': state['network'], 'chainId': str(chain_id), 'contractAddress': router,
        'deploymentToken': token, 'sourceRevision': report['commit'],
        'compilerVersion': 'solc 0.8.24 (via_ir, optimizer 200 runs)',
        'constructorArguments': {'deploymentToken': token, 'governanceTimelock': gov,
                                 'emergencyGuardian': report['roles']['guardian'],
                                 'penaltyTreasury': report['roles']['penalty_treasury']},
        'governanceDelaySeconds': '0',
        'profiles': [{'profileId': p['profileId'], 'parameterHash': p['parameterHash']} for p in created],
        'creationTransaction': deploy['FairBind']['transaction'], 'roleGrantTransactions': []})
    return {'deployment': str(run / 'deployment.json'), 'contract': router, 'sellerId': seller_id,
            'bondId': bond_id, 'verifiers': [v['verifierId'] for v in verifiers]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', required=True, help='report written by local_deploy.py')
    ap.add_argument('--profile', required=True, help='profile document (profiles/*.json or a derived document)')
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--rpc-url', required=True)
    ap.add_argument('--cast', default='cast')
    ap.add_argument('--verifiers', type=int, default=0, help='verifiers to register (default and minimum: max minVerifiers)')
    ap.add_argument('--seller-profile', type=int, default=0, help='profile of the seller (default: first data-api)')
    ap.add_argument('--base-port', type=int, default=18400, help='first loopback port of the service listeners')
    ap.add_argument('--inference-model-dir', default='', help='local checkpoint; enables the inference predicate')
    ap.add_argument('--inference-config-dir', default='', help='configuration manifests for the inference predicate')
    ap.add_argument('--python', default=sys.executable, help='Python interpreter of the inference predicate')
    a = ap.parse_args()
    print(json.dumps(setup(a, Chain(a.rpc_url.rstrip('/'), a.cast))))


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        sys.exit(f'local_setup: {e}')
