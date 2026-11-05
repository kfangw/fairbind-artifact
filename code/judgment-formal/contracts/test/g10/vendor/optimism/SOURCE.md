# Vendored source

Files copied without change from the Optimism monorepo,
`packages/contracts-bedrock/src/libraries/` at tag `op-contracts/v1.8.0`
(https://github.com/ethereum-optimism/optimism), MIT License (see LICENSE):

- `Bytes.sol`
- `rlp/RLPReader.sol`, `rlp/RLPErrors.sol`
- `trie/MerkleTrie.sol`, `trie/SecureMerkleTrie.sol`

They are used only by the gas measurement `StorageProofGas.t.sol`.
