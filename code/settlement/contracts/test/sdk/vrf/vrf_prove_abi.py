#!/usr/bin/env python3
"""ABI-encoded output of the G10d ECVRF prover (g10/g10d/vrf_prove.py) for
forge's vm.ffi in VrfFork.t.sol. Fork only, with a throwaway key registered
on the fork by impersonating the coordinator owner.

  vrf_prove_abi.py pubkey KEYFILE                  -> abi.encode(uint256[2] pk)
  vrf_prove_abi.py prove KEYFILE PRESEED BLOCKHASH -> abi.encode(Proof, uint256 h2cTries)

Proof is the coordinator's VRF.Proof (pk, gamma, c, s, seed, uWitness,
cGammaWitness, sHashWitness, zInv); every field is static, so the encoding
is the 32-byte words in order. The secret key is never printed.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "vrf_prove", os.path.join(HERE, "..", "..", "g10", "g10d", "vrf_prove.py"))
vp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vp)


def words(*xs):
    return "0x" + "".join("%064x" % x for x in xs)


def main():
    cmd, keyfile = sys.argv[1], sys.argv[2]
    sk = vp.read_key(keyfile)
    if cmd == "pubkey":
        pk = vp.mul(sk, vp.G)
        print(words(pk[0], pk[1]), end="")
    elif cmd == "prove":
        p = vp.prove(sk, int(sys.argv[3], 0), int(sys.argv[4], 16))
        print(words(p["pk"][0], p["pk"][1], p["gamma"][0], p["gamma"][1], p["c"], p["s"], p["seed"],
                    int(p["uWitness"], 16), p["cGammaWitness"][0], p["cGammaWitness"][1],
                    p["sHashWitness"][0], p["sHashWitness"][1], p["zInv"], p["h2c_tries"]), end="")
    else:
        raise SystemExit("usage: vrf_prove_abi.py pubkey KEYFILE | prove KEYFILE PRESEED BLOCKHASH")


if __name__ == "__main__":
    main()
