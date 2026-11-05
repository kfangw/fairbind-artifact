# usage: toforge.py <standard-json output> <out dir> : writes forge-shaped artifacts <out>/<File.sol>/<Contract>.json
import json, os, sys
r = json.load(open(sys.argv[1])); out = sys.argv[2]
for src, cs in r.get('contracts', {}).items():
    base = os.path.basename(src)
    for name, c in cs.items():
        d = os.path.join(out, base); os.makedirs(d, exist_ok=True)
        e = c['evm']
        art = {'abi': c['abi'], 'bytecode': {'object': '0x' + e['bytecode']['object'], 'linkReferences': {}},
               'deployedBytecode': {'object': '0x' + e['deployedBytecode']['object'], 'linkReferences': {},
                                    'immutableReferences': e['deployedBytecode'].get('immutableReferences', {})},
               'methodIdentifiers': e['methodIdentifiers'], 'storageLayout': c.get('storageLayout', {}),
               'metadata': json.loads(c['metadata']) if c.get('metadata') else {},
               'ast': r['sources'][src]['ast'], 'id': r['sources'][src]['id']}
        json.dump(art, open(os.path.join(d, name + '.json'), 'w'))
