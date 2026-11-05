#!/usr/bin/env python3
"""Chainlink VRF v2.5 request and fulfillment on a local Base fork for the settlement contract's sample-value consumer (a copy of the G10d script that deploys SettlementVrfConsumer).

Against the deployed Base coordinator (VRFCoordinatorV2_5_Optimism at
0xd5D517aBE5cF79B7e95eC98dB0f0277788aFF634) on an anvil fork:
  1. impersonates the coordinator owner and registers a throwaway proving key
     (its secret stays in --key; the real oracle keys are not used),
  2. creates a subscription from an impersonated EOA, deploys the minimal
     consumer, adds it, funds the subscription with native ETH and with LINK
     (LINK moved from the coordinator's own balance by impersonation),
  3. for each payment option sends consumer.request() and then
     coordinator.fulfillRandomWords(proof, rc, false) with a VRF.sol-compatible
     proof from vrf_prove.py, and records gas used, the billed payment, the
     L1GasFee event and the callback result.
Every transaction is real on the fork (receipts from anvil). Only the local
RPC is used once anvil has the fork state. Writes a TSV of measured rows and a
receipts TSV (label, 0, gas, to, calldata) for l1big.py.

Usage: run_vrf.py --rpc http://127.0.0.1:8604 --key KEYFILE --out OUT.tsv --l1rows ROWS.tsv
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
G10D = os.path.join(HERE, "..", "..", "g10", "g10d")
COORD = "0xd5D517aBE5cF79B7e95eC98dB0f0277788aFF634"
OWNER = "0xcEf2893e396d530bdECB1F1467e69F7B994eC5Ad"
LINK = "0x88Fb150BDc53A65fe94Dea0c9BA0a6dAf8C6e196"
USER = "0x1000000000000000000000000000000000000d01"     # subscription owner and requester (impersonated)
ORACLE = "0x1000000000000000000000000000000000000d02"   # sends fulfillments (impersonated)
BASE_FEE = 5_000_000  # 0.005 gwei, the fork block base fee (Base minimum); pinned before every transaction
PROOF_T = "(uint256[2],uint256[2],uint256,uint256,uint256,address,uint256[2],uint256[2],uint256)"
RC_T = "(uint64,uint256,uint32,uint32,address,bytes)"

T_REQ = None  # topic of RandomWordsRequested
T_FUL = None
T_L1 = None


def cast(*args):
    r = subprocess.run(["cast", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cast {' '.join(args[:3])}: {r.stderr.strip()[:400]}")
    return r.stdout.strip()


def rpc(url, method, *params):
    return cast("rpc", "--rpc-url", url, method, *params)


def send(url, frm, to, sig, *args, value=None, gas_price=BASE_FEE):
    # anvil lowers the base fee over empty blocks; pin it to the fork block's value
    rpc(url, "anvil_setNextBlockBaseFeePerGas", str(BASE_FEE))
    cmd = ["send", "--rpc-url", url, "--unlocked", "--from", frm, "--json"]
    if value is not None:
        cmd += ["--value", str(value)]
    if gas_price is not None:
        cmd += ["--gas-price", str(gas_price), "--priority-gas-price", "0"]
    if to == "--create":
        cmd += ["--create", sig, *args]
    else:
        cmd += [to, sig, *args]
    rc = json.loads(cast(*cmd))
    if rc["status"] not in ("0x1", 1):
        raise RuntimeError(f"reverted {sig} {rc['transactionHash']}")
    return rc


def topic(sig):
    return cast("keccak", sig)


def words(data):
    d = data[2:]
    return [int(d[i:i + 64], 16) for i in range(0, len(d), 64)]


def main():
    global T_REQ, T_FUL, T_L1
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--l1rows", required=True)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--cb-gas", type=int, default=100_000)
    a = ap.parse_args()
    url = a.rpc
    T_REQ = topic("RandomWordsRequested(bytes32,uint256,uint256,uint256,uint16,uint32,uint32,bytes,address)")
    T_FUL = topic("RandomWordsFulfilled(uint256,uint256,uint256,uint96,bool,bool,bool)")
    T_L1 = topic("L1GasFee(uint256)")
    t_sub = topic("SubscriptionCreated(uint256,address)")
    t_word = topic("WordStored(uint256,uint256)")
    t_stale = topic("FallbackWeiPerUnitLinkUsed(uint256,int256)")

    for who in (USER, ORACLE, OWNER, COORD):
        rpc(url, "anvil_impersonateAccount", who)
    for who in (USER, ORACLE, OWNER):
        rpc(url, "anvil_setBalance", who, hex(100 * 10**18))

    pk = subprocess.run([sys.executable, "-I", os.path.join(G10D, "vrf_prove.py"), "pubkey", "--key", a.key],
                        capture_output=True, text=True, check=True).stdout.split()
    send(url, OWNER, COORD, "registerProvingKey(uint256[2],uint64)", f"[{pk[0]},{pk[1]}]", "2000000000")
    key_hash = cast("keccak", cast("abi-encode", "f(uint256[2])", f"[{pk[0]},{pk[1]}]"))
    print("registered proving key, keyHash", key_hash)

    rc = send(url, USER, COORD, "createSubscription()")
    sub_id = int([lg for lg in rc["logs"] if lg["topics"][0] == t_sub][0]["topics"][1], 16)
    art = json.load(open(os.path.join(HERE, "..", "..", "..", "..", "out", "sdk", "SettlementVrfConsumer.sol",
                                      "SettlementVrfConsumer.json")))
    ctor = cast("abi-encode", "c(address,bytes32,uint256)", COORD, key_hash, str(sub_id))
    rc = send(url, USER, "--create", art["bytecode"]["object"] + ctor[2:])
    consumer = rc["contractAddress"]
    print("subId", sub_id, "consumer", consumer, "deploy gas", int(rc["gasUsed"], 16))
    send(url, USER, COORD, "addConsumer(uint256,address)", str(sub_id), consumer)
    send(url, USER, COORD, "fundSubscriptionWithNative(uint256)", str(sub_id), value=10**18)
    link_bal = int(cast("call", "--rpc-url", url, LINK, "balanceOf(address)(uint256)", COORD).split()[0])
    print("coordinator LINK balance", link_bal)
    send(url, COORD, LINK, "transfer(address,uint256)", USER, str(100 * 10**18))
    send(url, USER, LINK, "transferAndCall(address,uint256,bytes)", COORD, str(100 * 10**18),
         cast("abi-encode", "f(uint256)", str(sub_id)))

    rows = []
    l1rows = []
    for native in (True, False):
        mode = "native" if native else "link"
        for rep in range(1, a.reps + 1):
            rq = send(url, USER, consumer, "request(bool,uint32)", "true" if native else "false", str(a.cb_gas))
            lg = [x for x in rq["logs"] if x["topics"][0] == T_REQ][0]
            w = words(lg["data"])
            req_id, preseed = w[0], w[1]
            req_block = int(rq["blockNumber"], 16)
            bh = json.loads(cast("block", "--rpc-url", url, str(req_block), "--json"))["hash"]
            proof = json.loads(subprocess.run(
                [sys.executable, "-I", os.path.join(G10D, "vrf_prove.py"), "prove", "--key", a.key,
                 "--preseed", hex(preseed), "--blockhash", bh[2:]], capture_output=True, text=True,
                check=True).stdout)
            p = proof
            proof_arg = (f"([{p['pk'][0]},{p['pk'][1]}],[{p['gamma'][0]},{p['gamma'][1]}],{p['c']},{p['s']},"
                         f"{p['seed']},{p['uWitness']},[{p['cGammaWitness'][0]},{p['cGammaWitness'][1]}],"
                         f"[{p['sHashWitness'][0]},{p['sHashWitness'][1]}],{p['zInv']})")
            extra = "0x92fd1338" + ("%064x" % (1 if native else 0))
            rc_arg = f"({req_block},{sub_id},{a.cb_gas},1,{consumer},{extra})"
            fu = send(url, ORACLE, COORD, f"fulfillRandomWords({PROOF_T},{RC_T},bool)", proof_arg, rc_arg, "false",
                      gas_price=BASE_FEE)
            fl = [x for x in fu["logs"] if x["topics"][0] == T_FUL][0]
            fw = words(fl["data"])  # randomness, payment, nativePayment, success, onlyPremium
            l1 = [words(x["data"])[0] for x in fu["logs"] if x["topics"][0] == T_L1]
            stored = [x for x in fu["logs"] if x["topics"][0] == t_word]
            word = int(cast("call", "--rpc-url", url, consumer, "lastWord()(uint256)").split()[0])
            assert fw[3] == 1 and stored and word == int(stored[0]["data"][2:66], 16), "callback failed"
            gp = int(fu["effectiveGasPrice"], 16)
            prem = 60 if native else 50
            if native:
                billed = (fw[1] * 100 / (100 + prem) - (l1[0] if l1 else 0)) / gp
            else:
                wpl = int(cast("call", "--rpc-url", url, "0xc5E65227fe3385B88468F9A01600017cDC9F3A12",
                               "latestRoundData()(uint80,int256,uint256,uint256,uint80)").split()[2])
                billed = ((fw[1] * 100 / (100 + prem)) * wpl / 1e18 - (l1[0] if l1 else 0)) / gp
            row = dict(mode=mode, rep=rep, request_id=hex(req_id), request_block=req_block,
                       request_gas=int(rq["gasUsed"], 16), fulfill_gas=int(fu["gasUsed"], 16),
                       fulfill_gas_price=gp, payment=fw[1], l1_cost_wei=(l1[0] if l1 else 0),
                       callback_success=fw[3], word_stored=1, h2c_tries=p["h2c_tries"],
                       billed_gas=round(billed), fulfill_calldata_bytes=None,
                       feed_stale=int(any(x["topics"][0] == t_stale for x in fu["logs"])))
            rows.append(row)
            for lab, r in (("request", rq), ("fulfill", fu)):
                tx = json.loads(cast("tx", "--rpc-url", url, r["transactionHash"], "--json"))
                if lab == "fulfill":
                    row["fulfill_calldata_bytes"] = (len(tx["input"]) - 2) // 2
                l1rows.append(f"vrf_{mode}_{lab}_{rep}\t0\t{int(r['gasUsed'], 16)}\t{tx['to']}\t{tx['input']}")
            print(json.dumps(row), flush=True)
    with open(a.out, "w") as f:
        f.write("# subId %d consumer %s keyHash %s callbackGasLimit %d\n" % (sub_id, consumer, key_hash, a.cb_gas))
        hdr = list(rows[0])
        f.write("\t".join(hdr) + "\n")
        for r in rows:
            f.write("\t".join(str(r[k]) for k in hdr) + "\n")
    with open(a.l1rows, "w") as f:
        f.write("\n".join(l1rows) + "\n")


if __name__ == "__main__":
    main()
