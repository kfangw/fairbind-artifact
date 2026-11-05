// usage: node compile.js <root> <out.json> <file>... ; standard-json, via_ir, optimizer 200, cancun
const solc = require('solc'); const fs = require('fs'); const path = require('path');
const [root, out, ...files] = process.argv.slice(2);
const sources = {}; for (const f of files) sources[f] = { content: fs.readFileSync(path.join(root, f), 'utf8') };
const input = { language: 'Solidity', sources, settings: { viaIR: true, optimizer: { enabled: true, runs: 200 }, evmVersion: 'cancun',
  outputSelection: { '*': { '*': ['abi', 'evm.bytecode.object', 'evm.deployedBytecode.object', 'evm.methodIdentifiers', 'metadata', 'storageLayout', 'evm.deployedBytecode.immutableReferences'], '': ['ast'] } } } };
function imp(p) { try { return { contents: fs.readFileSync(path.join(root, p), 'utf8') }; } catch (e) { return { error: 'not found ' + p }; } }
const r = JSON.parse(solc.compile(JSON.stringify(input), { import: imp }));
const errs = (r.errors || []).filter(e => e.severity === 'error');
for (const e of (r.errors || [])) if (e.severity==='error') console.error(e.formattedMessage);
fs.writeFileSync(out, JSON.stringify(r)); console.log('errors', errs.length, 'warnings', (r.errors||[]).length - errs.length);
