#!/usr/bin/env bash
# Records what the Base fork really runs, at the pinned block, and checks that
# Foundry's vm.lastCallGas under --isolate equals an anvil receipt.
#   UPSTREAM  public Base RPC (read-only calls only)
#   FORK_RPC  local anvil forked from UPSTREAM at FORK_BLOCK (--hardfork osaka)
#   KEY_FILE  a throwaway key made for the fork; it is funded on the fork with
#             anvil_setBalance and never printed
set -euo pipefail
UPSTREAM="${UPSTREAM:-https://mainnet.base.org}"
FORK_RPC="${FORK_RPC:-http://127.0.0.1:8602}"
FORK_BLOCK="${FORK_BLOCK:-52977000}"
KEY_FILE="${KEY_FILE:?throwaway key file}"
GPO=0x420000000000000000000000000000000000000F
L1B=0x4200000000000000000000000000000000000015
H2935=0x0000F90827F1C53a10cb7A02335B175320002935
cd "$(git rev-parse --show-toplevel)"
echo "# commit $(git rev-parse --short HEAD)  $(date -u +%FT%TZ)  fork block $FORK_BLOCK"
echo "## client: $(cast rpc web3_clientVersion --rpc-url "$UPSTREAM")"
cast block "$FORK_BLOCK" --rpc-url "$FORK_RPC" --json | python3 -c "import json,sys;b=json.load(sys.stdin);print('## block', int(b['number'],16), 'hash', b['hash'], 'timestamp', int(b['timestamp'],16), 'baseFeePerGas', int(b['baseFeePerGas'],16), 'extraData', b['extraData'], 'requestsHash', b.get('requestsHash'))"
for f in "version()(string)" "isEcotone()(bool)" "isFjord()(bool)" "isIsthmus()(bool)" "isJovian()(bool)" "baseFeeScalar()(uint32)" "blobBaseFeeScalar()(uint32)" "l1BaseFee()(uint256)" "blobBaseFee()(uint256)"; do
  echo "## GasPriceOracle $f = $(cast call $GPO "$f" --rpc-url "$FORK_RPC" --block "$FORK_BLOCK" 2>&1 | head -1)"
done
for f in "version()(string)" "operatorFeeScalar()(uint32)" "operatorFeeConstant()(uint64)" "daFootprintGasScalar()(uint16)"; do
  echo "## L1Block $f = $(cast call $L1B "$f" --rpc-url "$FORK_RPC" --block "$FORK_BLOCK" 2>&1 | head -1)"
done
# EIP-7939 CLZ (Osaka): initcode PUSH1 1 CLZ PUSH1 0 MSTORE PUSH1 32 PUSH1 0 RETURN, run on the chain itself
echo "## CLZ(1) by eth_call on $UPSTREAM at $FORK_BLOCK (0xff = opcode present): $(cast rpc eth_call '{"data":"0x60011e60005260206000f3"}' "$(cast to-hex $FORK_BLOCK)" --rpc-url "$UPSTREAM")"
# EIP-7623 floor on the chain itself: 1,000 nonzero bytes to an EOA; standard 37,000, floor 61,000
D=0x$(python3 -c "print('11'*1000)")
echo "## eth_estimateGas, 1000 nonzero calldata bytes to an EOA (standard 37000, EIP-7623 floor 61000): $(cast estimate 0x000000000000000000000000000000000000dEaD "$D" --from 0x000000000000000000000000000000000000bEEF --rpc-url "$UPSTREAM" --block "$FORK_BLOCK")"
# EIP-2935 history contract holds recent hashes
s=$(( (FORK_BLOCK - 1) % 8191 ))
echo "## EIP-2935 code bytes: $(( ($(cast code $H2935 --rpc-url "$FORK_RPC" | wc -c) - 3) / 2 ))"
echo "## EIP-2935 slot $s = $(cast storage $H2935 $s --rpc-url "$FORK_RPC" --block "$FORK_BLOCK"); hash of block $((FORK_BLOCK-1)) = $(cast block $((FORK_BLOCK-1)) --rpc-url "$FORK_RPC" -f hash)"
echo "## EIP-2935 get($((FORK_BLOCK-100))) = $(cast call $H2935 "$(cast to-uint256 $((FORK_BLOCK-100)))" --rpc-url "$FORK_RPC" --block "$FORK_BLOCK"); hash = $(cast block $((FORK_BLOCK-100)) --rpc-url "$FORK_RPC" -f hash)"
echo "## Chainlink ETH/USD on Base latestRoundData at fork block: $(cast call 0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70 'latestRoundData()(uint80,int256,uint256,uint256,uint80)' --rpc-url "$FORK_RPC" --block "$FORK_BLOCK" | tr '\n' ' ')"
echo "## eth_feeHistory 20 blocks to the fork block, median of 25/50/75th percentile tips (wei):"
cast rpc eth_feeHistory 0x14 "$(cast to-hex $FORK_BLOCK)" '[25,50,75]' --rpc-url "$UPSTREAM" | python3 -c "
import json,sys,statistics as st;d=json.load(sys.stdin);r=d['reward']
print('##  base fees', sorted(set(int(x,16) for x in d['baseFeePerGas'])), 'tips p25/p50/p75', [st.median(int(x[i],16) for x in r) for i in range(3)])"
# receipt cross-check on the fork
A=$(cast wallet address --private-key "$(cat "$KEY_FILE")")
cast rpc anvil_setBalance "$A" 0xDE0B6B3A7640000 --rpc-url "$FORK_RPC" >/dev/null
BC=$(python3 -c "import json;print(json.load(open('out/g10b/G10Base.sol/G10Probe.json'))['bytecode']['object'])")
P=$(cast send --private-key "$(cat "$KEY_FILE")" --rpc-url "$FORK_RPC" --create "$BC" --json | python3 -c "import json,sys;print(json.load(sys.stdin)['contractAddress'])")
for d in 0x "$D"; do
  g=$(cast send --private-key "$(cat "$KEY_FILE")" --rpc-url "$FORK_RPC" "$P" "take(bytes)" "$d" --json | python3 -c "import json,sys;print(int(json.load(sys.stdin)['gasUsed'],16))")
  echo "## anvil receipt gasUsed, G10Probe.take with $(( (${#d}-2)/2 )) bytes of 0x11: $g"
done
echo "## (forge --isolate vm.lastCallGas for the same two calls: see g10b_calib.log)"
