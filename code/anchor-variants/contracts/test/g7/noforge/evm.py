"""Minimal concrete EVM runner (py-evm, Cancun rules) for the verification contracts."""
import json
from eth.chains.base import MiningChain
from eth.db.atomic import AtomicDB
from eth.vm.forks.cancun import CancunVM
from eth.vm.message import Message
from eth_abi import encode
from eth_hash.auto import keccak

GENESIS = dict(difficulty=0, gas_limit=30_000_000, timestamp=1_800_000_000, coinbase=b"\0" * 20,
               extra_data=b"", nonce=b"\0" * 8, mix_hash=b"\0" * 32)


def runtime(art_path, name, immutables=None):
    a = json.load(open(f"{art_path}/P5Verifiers.sol/{name}.json"))
    code = bytearray(bytes.fromhex(a["deployedBytecode"]["object"][2:]))
    refs = a["deployedBytecode"].get("immutableReferences", {})
    if refs:
        # immutables in declaration order: map by AST id order
        ids = sorted(refs, key=int)
        for k, val in zip(ids, immutables):
            for r in refs[k]:
                code[r["start"]:r["start"] + r["length"]] = val.to_bytes(32, "big")
    return bytes(code)


class Runner:
    def __init__(self, codes):
        state = {addr: dict(balance=0, nonce=1, code=c, storage={}) for addr, c in codes.items()}
        state[b"\x99" * 20] = dict(balance=10**30, nonce=0, code=b"", storage={})
        chain = MiningChain.configure(vm_configuration=((0, CancunVM),), chain_id=1).from_genesis(
            AtomicDB(), dict(GENESIS), state)
        self.vm = chain.get_vm()

    def call(self, to, data, gas=10_000_000):
        st = self.vm.state
        snap = st.snapshot()
        msg = Message(gas=gas, to=to, sender=b"\x99" * 20, value=0, data=data, code=st.get_code(to))
        ctx = st.get_transaction_context_class()(gas_price=1, origin=b"\x99" * 20)
        comp = st.computation_class.apply_message(st, msg, ctx)
        st.revert(snap)
        ok = comp.is_success
        out = comp.output
        return ok, out, comp.get_gas_used()


SEL = keccak(b"verify((bytes32,uint64,uint64,bytes32,bytes32,bytes32,bytes32,bytes32),bytes)")[:4]


def verify_data(ctx, material):
    t = (ctx.get("nonce", b"\0" * 32), ctx.get("amount", 0), ctx.get("validAfter", 0), ctx.get("requestHash", b"\0" * 32),
         ctx.get("responseHash", b"\0" * 32), ctx.get("claimsHash", b"\0" * 32), ctx["materialCommit"],
         ctx.get("anchoredHash", b"\0" * 32))
    return SEL + encode(["(bytes32,uint64,uint64,bytes32,bytes32,bytes32,bytes32,bytes32)", "bytes"], [t, material])


def passes(r, to, ctx, material, gas=10_000_000):
    ok, out, used = r.call(to, verify_data(ctx, material), gas)
    return (ok and len(out) == 32 and int.from_bytes(out, "big") == 1), used, ok
