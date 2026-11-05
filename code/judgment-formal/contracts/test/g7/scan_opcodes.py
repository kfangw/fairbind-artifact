#!/usr/bin/env python3
"""Lists, for each verification contract's deployed bytecode, the opcodes
that read the environment or state or make calls (GAS, BALANCE, SLOAD,
TIMESTAMP, NUMBER, CALLER, ORIGIN, ... and the CALL family), with the opcode
that follows each GAS. The result of the contract may depend on gas only
through such a GAS; a GAS that is the gas argument of a STATICCALL to a
precompile does not change the result while the call has enough gas.

usage: scan_opcodes.py <out dir> <Contract> [<Contract> ...]
"""
import json, sys, os

NAMES = {0x31: "BALANCE", 0x32: "ORIGIN", 0x33: "CALLER", 0x3a: "GASPRICE", 0x3b: "EXTCODESIZE",
         0x3c: "EXTCODECOPY", 0x3f: "EXTCODEHASH", 0x40: "BLOCKHASH", 0x41: "COINBASE", 0x42: "TIMESTAMP",
         0x43: "NUMBER", 0x44: "PREVRANDAO", 0x45: "GASLIMIT", 0x46: "CHAINID", 0x47: "SELFBALANCE",
         0x48: "BASEFEE", 0x49: "BLOBHASH", 0x4a: "BLOBBASEFEE", 0x54: "SLOAD", 0x55: "SSTORE", 0x5a: "GAS",
         0x5c: "TLOAD", 0x5d: "TSTORE", 0xf0: "CREATE", 0xf1: "CALL", 0xf2: "CALLCODE", 0xf4: "DELEGATECALL",
         0xf5: "CREATE2", 0xfa: "STATICCALL", 0xff: "SELFDESTRUCT", 0x30: "ADDRESS"}


def ops(code):
    i, out = 0, []
    while i < len(code):
        op = code[i]
        n = op - 0x5f if 0x60 <= op <= 0x7f else 0
        out.append((i, op, code[i + 1:i + 1 + n]))
        i += 1 + n
    return out


def main():
    d = sys.argv[1]
    for name in sys.argv[2:]:
        path = None
        for root, _, files in os.walk(d):
            if name + ".json" in files:
                path = os.path.join(root, name + ".json")
        art = json.load(open(path))
        code = bytes.fromhex(art["deployedBytecode"]["object"][2:])
        # stop at the metadata (CBOR) section: the last 2 bytes give its length
        meta = int.from_bytes(code[-2:], "big") + 2
        seq = ops(code[:-meta])
        found = {}
        for k, (pc, op, imm) in enumerate(seq):
            if op in NAMES:
                found.setdefault(NAMES[op], []).append(pc)
        print(name, len(code), "bytes")
        for nm, pcs in sorted(found.items()):
            print(f"  {nm}: {len(pcs)}")
        for k, (pc, op, imm) in enumerate(seq):
            if op == 0x5a:
                nxt = [NAMES.get(o, hex(o)) + (("(" + v.hex() + ")") if v else "") for _, o, v in seq[k + 1:k + 4]]
                prv = [NAMES.get(o, hex(o)) + (("(" + v.hex() + ")") if v else "") for _, o, v in seq[max(0, k - 6):k]]
                print(f"  GAS at {pc}: before {prv} after {nxt}")


main()
