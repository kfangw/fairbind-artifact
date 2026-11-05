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
    chain = Chain(a.rpc_url.rstrip('/'), a.cast)
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
    least = max(int(p['parameters']['minVerifiers']) for p in profiles)
    count = a.verifiers or least
    if count < least:
        raise SystemExit(f'--verifiers {count} is below the largest minVerifiers {least} of the profile document')
    bitmap = 0
    for p in created:
        bitmap |= 1 << p['classId']
    # Assignment needs (bond - reserved penalties) * verifierExposurePpm to cover
    # value + maxReviewCost of every open assignment, so a bond at the minimum is
    # never assigned. Bond at the smallest verifierBondCap (the most that counts).
    bond = max(max(int(p['parameters']['minVerifierBond']) for p in created),
               min(int(p['parameters']['verifierBondCap']) for p in created))
    chain.send(verifier_owner, token, 'mint(address,uint256)', verifier_owner, bond * count)
    chain.send(verifier_owner, token, 'approve(address,uint256)', router, bond * count)
    verifiers = []
    for i in range(count):
        vkey = key_at(chain, VERIFIER_KEY_BASE + i)
        vaddr = addr_of(chain, vkey)
        vid = int(chain.call(verifier_owner, router, 'registerVerifier(uint256,address,uint128)(uint32)',
                             bitmap, vaddr, bond).split()[0])
        chain.send(verifier_owner, router, 'registerVerifier(uint256,address,uint128)', bitmap, vaddr, bond)
        verifiers.append({'verifierId': vid, 'signingKey': vaddr, 'privateKey': vkey, 'owner': verifier_owner,
                          'bond': str(bond), 'classBitmap': bitmap})
    for p in created:
        chain.send(gov, router, 'checkpointVerifierTree(uint32)', p['profileId'])
        chain.send(gov, router, 'setServiceProfileActive(uint32,bool)', p['profileId'], 'true')

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
    seller_bond = int(params['sellerPenalty'])
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
    buyer_funds = 1_000 * int(params['maxPurchaseValue']) + 4 * int(params['disputeDeposit'])
    for role in ('buyer', 'buyer2'):
        chain.send(addrs[role], token, 'mint(address,uint256)', addrs[role], buyer_funds)
        chain.send(addrs[role], token, 'approve(address,uint256)', router, 2**256 - 1)

    # Service files.
    cast_path = subprocess.run(['sh', '-c', f'command -v {a.cast}'], capture_output=True, text=True).stdout.strip()
    port = a.base_port
    ports = {'facilitator': port, 'seller': port + 1, 'buyer': port + 2, 'buyer2': port + 3}
    urls = {k: f'http://127.0.0.1:{v}' for k, v in ports.items()}
    svc = run / 'services'
    for d in ('keeper', 'facilitator', 'seller', 'buyer', 'buyer2', 'verifier'):
        (svc / d).mkdir(parents=True, exist_ok=True)
    chain_id = int(chain.rpc('eth_chainId', []), 16)
    network = f'eip155:{chain_id}'
    common = {'rpcUrl': chain.url, 'chainId': chain_id}
    write_json(svc / 'keeper' / 'keeper.json', dict(common, contract=router, **{
        'from': addrs['keeper'], 'gas': 5_000_000, 'stateFile': str(svc / 'keeper' / 'state.json'),
        'startBlock': 0, 'pollIntervalMs': 500, 'rpcTimeoutMs': 10000, 'maxLogRange': 5000,
        'resendAfterBlocks': 20}))
    write_json(svc / 'facilitator' / 'facilitator.json', dict(common, **{
        'listen': f'127.0.0.1:{ports["facilitator"]}', 'dataDir': str(svc / 'facilitator' / 'data'),
        'network': network, 'contract': router, 'from': addrs['facilitator'], 'token': token,
        'tokenName': TOKEN_NAME, 'tokenVersion': TOKEN_VERSION,
        'settlementSchema': str(ROOT / 'schemas' / 'fairbind-settlement-v1.schema.json')}))
    (svc / 'seller' / 'claims.json').write_bytes(claims)
    (svc / 'seller' / 'quote.json').write_text(json.dumps(SELLER_QUOTE, separators=(',', ':')) + '\n')
    (svc / 'seller' / 'seller.key').write_text(keys['seller'] + '\n')
    headers = sorted(params.get('canonicalHeaders', ['accept']))
    seller_cfg = dict(common, **{
        'listen': f'127.0.0.1:{ports["seller"]}', 'dataDir': str(svc / 'seller' / 'data'),
        'publicUrl': urls['seller'], 'network': network, 'contract': router, 'owner': seller_owner,
        'sellerId': seller_id, 'signingKeyFile': str(svc / 'seller' / 'seller.key'),
        'facilitatorUrl': urls['facilitator'], 'serviceName': 'Local evaluation API',
        'serviceClass': SERVICE_CLASS[sp['classId']], 'profileHash': sp['parameterHash'],
        'canonicalHeaders': headers, 'price': int(params['maxPurchaseValue']), 'maxTimeoutSeconds': 300,
        'tokenName': TOKEN_NAME, 'tokenVersion': TOKEN_VERSION,
        'extensionSchema': str(ROOT / 'schemas' / 'fairbind-extension-v1.schema.json'),
        'settlementSchema': str(ROOT / 'schemas' / 'fairbind-settlement-v1.schema.json'),
        'claimsFile': str(svc / 'seller' / 'claims.json'), 'tickSeconds': 1,
        'routes': [{'path': '/v1/quote', 'description': 'Signed market quote', 'mimeType': 'application/json',
                    'bodyFile': str(svc / 'seller' / 'quote.json'),
                    'preimage': {'kind': 'data-api', 'referenceTime': str(DATA_REFERENCE_TIME), 'sourceSetHash': source_set,
                                 'tolerancePolicyHash': tolerance}}]})
    if sp['classId'] != 1:
        seller_cfg['routes'] = []
    write_json(svc / 'seller' / 'seller.json', seller_cfg)
    for role in ('buyer', 'buyer2'):
        (svc / role / 'buyer.key').write_text(keys[role] + '\n')
        write_json(svc / role / 'buyer.json', dict(common, **{
            'listen': f'127.0.0.1:{ports[role]}', 'dataDir': str(svc / role / 'data'), 'network': network,
            'contract': router, 'keyFile': str(svc / role / 'buyer.key'),
            'maxPrice': int(params['maxPurchaseValue']), 'tickSeconds': 1}))
    password = svc / 'verifier' / 'password'
    password.write_text('local-evaluation\n')
    # Predicate pipelines shared by every verifier.
    data_dir = svc / 'verifier' / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / 'policy.json').write_bytes(canonical_json(DATA_POLICY) + b'\n')
    (data_dir / 'sources.json').write_bytes(canonical_json(DATA_SOURCE_SET) + b'\n')
    data_profiles = [p for p in created if p['classId'] == 1]
    data_predicate = {'timeoutSeconds': 15,
                      'references': {'mode': 'replay', 'replayDir': str(REPLAY_DIR), 'allowSynthetic': True},
                      'profiles': {str(p['profileId']): {'policyFile': str(data_dir / 'policy.json'),
                                                         'sourceSetFile': str(data_dir / 'sources.json')}
                                   for p in data_profiles}}
    inference_predicate = None
    if a.inference_model_dir:
        model_dir = Path(a.inference_model_dir).resolve()
        config_dir = Path(a.inference_config_dir).resolve() if a.inference_config_dir else model_dir
        inference_predicate = {'python': a.python, 'script': str(ROOT / 'runtime' / 'inference' / 'evaluate.py'),
                               'modelDir': str(model_dir), 'configDir': str(config_dir), 'timeoutSeconds': 600}
    for v in verifiers:
        vdir = svc / 'verifier' / str(v['verifierId'])
        (vdir / 'keystore').mkdir(parents=True, exist_ok=True)
        name = f'verifier-{v["verifierId"]}'
        if not (vdir / 'keystore' / name).exists():
            chain.cast('wallet', 'import', name, '--private-key', v['privateKey'], '--keystore-dir',
                       str(vdir / 'keystore'), '--unsafe-password', 'local-evaluation')
        write_json(vdir / 'verifier.json', dict(common, **{
            'contract': router, 'verifierId': v['verifierId'], 'keystore': str(vdir / 'keystore' / name),
            'passwordFile': str(password), 'castPath': cast_path, 'stateDir': str(vdir / 'state'),
            'pollIntervalSeconds': 1, 'startBlock': 0, 'maxLogRange': 5000, 'submitMarginBlocks': 4,
            'relay': {'from': verifier_owner, 'gas': 5_000_000},
            'sellers': {str(seller_id): urls['seller']},
            'profiles': {str(p['profileId']): ({'sourceSetHash': source_set, 'tolerancePolicyHash': tolerance}
                                               if p['profileId'] == sp['profileId'] else {}) for p in created}},
            **({'dataPredicate': data_predicate} if data_profiles else {}),
            **({'inferencePredicate': inference_predicate} if inference_predicate else {})))
        v['config'] = str(vdir / 'verifier.json')

    deploy = report['deployments']
    deployment = {
        'formatVersion': 1, 'note': 'Local evaluation only. Every key is an Anvil default test key.',
        'createdAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'commit': report['commit'],
        'dirty': report.get('dirty', False), 'build': report['build'], 'anvil': report['anvil'], 'admissionOverride': report['admission_override'],
        'network': network, 'chainId': chain_id, 'rpcUrl': chain.url, 'contract': router, 'token': token,
        'tokenName': TOKEN_NAME, 'tokenVersion': TOKEN_VERSION, 'profileDocument': str(Path(a.profile).resolve()),
        'modules': {k: v['address'] for k, v in deploy.items() if k not in ('FairBind', 'MockEIP3009Token')},
        'profiles': [{k: v for k, v in p.items() if k != 'parameters'} for p in created],
        'bond': {'bondId': bond_id, 'profileId': sp['profileId'], 'owner': seller_owner, 'amount': str(seller_bond)},
        'seller': {'sellerId': seller_id, 'bondId': bond_id, 'profileId': sp['profileId'], 'owner': seller_owner,
                   'signingKey': seller_owner, 'claimsHash': claims_hash, 'url': urls['seller']},
        'verifiers': verifiers,
        'roles': {role: {'address': addrs[role], 'privateKey': keys[role], 'mnemonicIndex': ROLES[role]}
                  for role in ROLES},
        'services': {'keeper': str(svc / 'keeper' / 'keeper.json'),
                     'facilitator': str(svc / 'facilitator' / 'facilitator.json'),
                     'seller': str(svc / 'seller' / 'seller.json'), 'buyer': str(svc / 'buyer' / 'buyer.json'),
                     'buyer2': str(svc / 'buyer2' / 'buyer.json'),
                     'verifiers': [v['config'] for v in verifiers]},
        'urls': urls, 'setupBlock': chain.head(), 'deployReport': str(Path(a.report).resolve())}
    write_json(run / 'deployment.json', deployment)
    # The fields of schemas/deployment-manifest-v1.schema.json.
    write_json(run / 'manifest.json', {
        'formatVersion': 1, 'network': network, 'chainId': str(chain_id), 'contractAddress': router,
        'deploymentToken': token, 'sourceRevision': report['commit'],
        'compilerVersion': 'solc 0.8.24 (via_ir, optimizer 200 runs)',
        'constructorArguments': {'deploymentToken': token, 'governanceTimelock': gov,
                                 'emergencyGuardian': report['roles']['guardian'],
                                 'penaltyTreasury': report['roles']['penalty_treasury']},
        'governanceDelaySeconds': '0',
        'profiles': [{'profileId': p['profileId'], 'parameterHash': p['parameterHash']} for p in created],
        'creationTransaction': deploy['FairBind']['transaction'], 'roleGrantTransactions': []})
    print(json.dumps({'deployment': str(run / 'deployment.json'), 'contract': router, 'sellerId': seller_id,
                      'bondId': bond_id, 'verifiers': [v['verifierId'] for v in verifiers]}))


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        sys.exit(f'local_setup: {e}')
