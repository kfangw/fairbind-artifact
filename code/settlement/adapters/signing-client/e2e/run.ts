// End-to-end runs on a local anvil fork of Base mainnet (the deployed USDC,
// fork-only keys, no real funds). Starts anvil, deploys the settlement and
// tier 1a verification contracts, registers seller profiles, runs the
// scenarios on one shared timeline, checks each scenario's outcome against
// the expectation fixed before the run, and writes e2e-out/result.json.
// Sample values come over Chainlink VRF v2.5: the settlement contract owns a
// subscription on Chainlink's VRFCoordinatorV2_5Mock deployed on the fork;
// after A_e each seller sends the profile epoch's request and the mock
// fulfills it (see "sample values" below for the words).
//   FORK_RPC    upstream RPC (default: the public Base RPC, read only)
//   FORK_BLOCK  fork block (default 52977000)
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  createPublicClient,
  createWalletClient,
  encodeAbiParameters,
  erc20Abi,
  http,
  keccak256,
  numberToHex,
  stringToHex,
  hexToBytes,
  bytesToHex,
  type Address,
  type Hex,
  type PublicClient,
  type WalletClient,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { decodeEventLog } from "viem";
import { base } from "viem/chains";
import { artifact, ChainView } from "../src/chain.ts";
import { SigningClient, type Purchase } from "../src/client.ts";
import type { Action } from "../src/duties.ts";
import { boundNonce, decryptHash, encrypt, F_CT, node, profileId, rsHash, type Profile } from "../src/hashing.ts";
import { Watchtower } from "../src/watchtower.ts";
import { RefSeller, USDC, FEED, type Mode } from "./seller.ts";

const FORK_RPC = process.env.FORK_RPC ?? "https://mainnet.base.org";
const FORK_BLOCK = process.env.FORK_BLOCK ?? "52977000";
const EPOCH_MULTIPLE = Number(process.env.E2E_K ?? "1"); // seller-epoch multiple k of every profile
const PORT = 8547;
const RPC = `http://127.0.0.1:${PORT}`;
const BALANCE_SLOT = 9n; // FiatTokenV2_2 balanceAndBlacklistStates

const key = (s: string): Hex => keccak256(stringToHex(`${s}, fork only`));

async function startAnvil(): Promise<ChildProcess> {
  const p = spawn("anvil", ["--fork-url", FORK_RPC, "--fork-block-number", FORK_BLOCK, "--port", String(PORT), "--silent", "--compute-units-per-second", process.env.FORK_CUPS ?? "100", "--retries", "20", "--fork-retry-backoff", "2000", "--timeout", "60000"], { stdio: "inherit" });
  for (let i = 0; i < 120; i++) {
    try {
      const r = await fetch(RPC, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_chainId", params: [] }) });
      if (r.ok) return p;
    } catch {
      /* not up yet */
    }
    await new Promise((ok) => setTimeout(ok, 500));
  }
  throw new Error("anvil did not start");
}

async function rpc(method: string, params: unknown[]) {
  const r = await fetch(RPC, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
  const j = (await r.json()) as { result?: unknown; error?: { message: string } };
  if (j.error) throw new Error(`${method}: ${j.error.message}`);
  return j.result;
}

const mine = (n: bigint) => rpc("anvil_mine", [numberToHex(n), "0x1"]);

async function setUsdc(who: Address, amount: bigint) {
  const slot = keccak256(encodeAbiParameters([{ type: "address" }, { type: "uint256" }], [who, BALANCE_SLOT]));
  await rpc("anvil_setStorageAt", [USDC, slot, numberToHex(amount, { size: 32 })]);
}

async function main() {
  const anvil = await startAnvil();
  const git = (args: string[]) => execFileSync("git", args, { cwd: import.meta.dirname }).toString().trim();
  const dirty = git(["status", "--porcelain", "--", "../../../contracts", ".", "../../../foundry.toml"]).length > 0;
  const result: Record<string, unknown> = { revision: git(["rev-parse", "HEAD"]), dirty, forkRpc: FORK_RPC, forkBlock: FORK_BLOCK, startedAt: new Date().toISOString() };
  try {
    await run(result);
  } finally {
    anvil.kill();
  }
  const out = resolve(import.meta.dirname, "../e2e-out");
  mkdirSync(out, { recursive: true });
  writeFileSync(resolve(out, "result.json"), JSON.stringify(result, (_k, v) => (typeof v === "bigint" ? v.toString() : v), 2));
  const sc = result.scenarios as { id: string; pass: boolean }[];
  console.log(`\nscenarios: ${sc.filter((s) => s.pass).length}/${sc.length} as expected; parity ${(result.parity as { ok: boolean }).ok}`);
  if (!sc.every((s) => s.pass) || !(result.parity as { ok: boolean }).ok) process.exitCode = 1;
}

async function run(result: Record<string, unknown>) {
  const chain = { ...base, rpcUrls: { default: { http: [RPC] } } };
  const pub = createPublicClient({ chain, transport: http(RPC), pollingInterval: 50 }) as PublicClient;
  const wallet = (name: string): WalletClient => createWalletClient({ chain, transport: http(RPC), account: privateKeyToAccount(key(name)) });
  const sellerNames = ["seller", "seller-fraud", "seller-late", "seller-miss", "seller-dbl"];
  const buyerNames = Array.from({ length: 13 }, (_, i) => `buyer-${i + 1}`);
  const names = ["deployer", ...sellerNames, "facilitator", ...buyerNames, "tower-a", "tower-b", "stranger"];
  const w = Object.fromEntries(names.map((n) => [n, wallet(n)])) as Record<string, WalletClient>;
  for (const n of names) {
    await rpc("anvil_setBalance", [w[n].account!.address, numberToHex(10n ** 19n)]);
    await setUsdc(w[n].account!.address, n.startsWith("buyer") || n.startsWith("tower") || n === "stranger" ? 10_000_000n : n.startsWith("seller") ? 5_000_000n : 0n);
  }
  const feedKey = privateKeyToAccount(key("feed signer"));

  // ------------------------------------------------------------ deploy
  const S = artifact("SampledSettlement.sol", "SampledSettlement");
  const L = artifact("P5Verifiers.sol", "P5LazerVerifier");
  const deploy = async (a: { abi: unknown; bytecode: Hex }, args: unknown[]) => {
    const hash = await w.deployer.deployContract({ abi: a.abi as never, bytecode: a.bytecode, args: args as never, account: w.deployer.account!, chain });
    const rc = await pub.waitForTransactionReceipt({ hash, timeout: 300_000 });
    deployGas.push(rc.gasUsed);
    return rc.contractAddress!;
  };
  const deployGas: bigint[] = [];
  // Chainlink's VRF v2.5 coordinator mock (base fee 1e14 wei, 1 gwei per gas)
  const V = artifact("VRFCoordinatorV2_5Mock.sol", "VRFCoordinatorV2_5Mock");
  const coordinator = await deploy(V, [10n ** 14n, 10n ** 9n, 4n * 10n ** 15n]);
  const vrfKeyHash = keccak256(stringToHex("e2e vrf key hash"));
  const contract = await deploy(S, [USDC, coordinator, vrfKeyHash]);
  result.deployGas = deployGas;
  const lazer = await deploy(L, [feedKey.address, FEED]);
  const view = new ChainView(pub, contract);
  const c = await view.constants();
  const vrfSubId = await view.read<bigint>("vrfSubId", []);
  {
    const hash = await w.deployer.writeContract({ address: coordinator, abi: V.abi, functionName: "fundSubscriptionWithNative", args: [vrfSubId], value: 10n ** 18n, account: w.deployer.account!, chain });
    await pub.waitForTransactionReceipt({ hash, timeout: 300_000 });
  }
  result.vrf = { coordinator, keyHash: vrfKeyHash, subId: vrfSubId, requests: [] as unknown[] };
  result.contract = contract;
  result.verifier = lazer;
  result.chainId = await pub.getChainId();

  // move to an epoch start + 5 so every purchase falls in one epoch
  const startHead = await pub.getBlockNumber();
  const e0 = (startHead - c.genesis) / c.EPOCH_BLOCKS + 1n;
  await mine(c.genesis + e0 * c.EPOCH_BLOCKS + 5n - startHead);

  // ------------------------------------------------------------ profiles
  const codeHash = await view.codeHashAt(lazer);
  const sellerAddr = w.seller.account!.address;
  const mkProfile = (tag: string, flags: number, rdl = 0, who = sellerAddr): Profile => ({
    account: who,
    receiptKey: who,
    unitKey: who,
    verifier: lazer,
    codeHash,
    tier: 1,
    flags,
    cap: 1_000_000n,
    minAmount: 1_000n, // v_min: every sale of the runs is 10,000
    responseDeadline: rdl,
    deposit: 50_000n,
    maxFeePerGas: 0n, // disclosed below the floor: clients reserve at p_floor
    epochMultiple: EPOCH_MULTIPLE,
    inputRule: keccak256(stringToHex(`price feed input rule, ${tag}`)),
  });
  const register = async (p: Profile, sw: WalletClient = w.seller): Promise<Hex> => {
    const hash = await sw.writeContract({ address: contract, abi: view.abi, functionName: "register", args: [p, 200_000], account: sw.account!, chain });
    await pub.waitForTransactionReceipt({ hash, timeout: 300_000 });
    return profileId(p);
  };
  const seller = new RefSeller({ publicClient: pub, seller: w.seller, facilitator: w.facilitator, feedKey, contract, port: PORT + 1 });
  const routes: Record<string, { mode: Mode; flags: number; other?: string }> = {
    "/h": { mode: "honest", flags: 0 },
    "/hc": { mode: "honest-ct", flags: F_CT },
    "/w": { mode: "withhold", flags: 0 },
    "/wb": { mode: "withhold-badct", flags: 0 },
    "/k": { mode: "withhold-key-badct", flags: F_CT },
    "/t": { mode: "withhold-badct", flags: 0 },
    "/x": { mode: "wrong-payto", flags: 0, other: "/h" },
    "/r": { mode: "wrong-receipt-profile", flags: 0, other: "/h" },
    "/c": { mode: "withhold-key-badct", flags: F_CT },
  };
  const pids: Record<string, Hex> = {};
  const profiles: Record<string, Profile> = {};
  for (const [path, r] of Object.entries(routes)) {
    profiles[path] = mkProfile(path, r.flags);
    pids[path] = await register(profiles[path]);
    const onchain = await view.profile(pids[path]);
    if (onchain.account.toLowerCase() !== sellerAddr.toLowerCase()) throw new Error(`profile ${path} not registered`);
  }
  for (const [path, r] of Object.entries(routes)) {
    seller.addRoute({ path, pid: pids[path], profile: profiles[path], mode: r.mode, otherPid: r.other ? pids[r.other] : undefined });
  }
  await seller.start();
  // the sellers of the failure scenarios, one account each (a failure
  // freezes the account's later unpaid sales across its profiles)
  const other: Record<string, { seller: RefSeller; routes: Record<string, Mode> }> = {
    "seller-fraud": { seller: undefined as unknown as RefSeller, routes: { "/f": "fraud", "/fh": "honest" } },
    "seller-late": { seller: undefined as unknown as RefSeller, routes: { "/l": "honest" } },
    "seller-miss": { seller: undefined as unknown as RefSeller, routes: { "/m": "honest" } },
    "seller-dbl": { seller: undefined as unknown as RefSeller, routes: { "/d": "honest" } },
  };
  let port = PORT + 2;
  const sellerOf: Record<string, RefSeller> = {};
  for (const path of Object.keys(routes)) sellerOf[path] = seller;
  for (const [name, o] of Object.entries(other)) {
    o.seller = new RefSeller({ publicClient: pub, seller: w[name], facilitator: w.facilitator, feedKey, contract, port: port++ });
    for (const [path, mode] of Object.entries(o.routes)) {
      profiles[path] = mkProfile(path, 0, 0, w[name].account!.address);
      pids[path] = await register(profiles[path], w[name]);
      o.seller.addRoute({ path, pid: pids[path], profile: profiles[path], mode });
      sellerOf[path] = o.seller;
    }
    await o.seller.start();
  }
  // bonds b(V*_p) = V (tiers 0 and 1, s-hat = 1)
  const bonds: Record<string, unknown> = {};
  bonds.seller = await seller.depositBond(1_000_000n);
  for (const [name, o] of Object.entries(other)) bonds[name] = await o.seller.depositBond(1_000_000n);
  result.bonds = bonds;
  result.profiles = pids;

  // ------------------------------------------------------------ parity
  const chainId = await pub.getChainId();
  const parity: Record<string, boolean> = {};
  {
    const p = profiles["/h"];
    parity.profileId = (await view.read<Hex>("profileId", [p])) === profileId(p);
    const rq = keccak256(stringToHex("rq"));
    const cl = keccak256(stringToHex("cl"));
    const salt = keccak256(stringToHex("salt"));
    parity.boundNonce = (await view.read<Hex>("boundNonce", [pids["/h"], rq, cl, salt])) === boundNonce(chainId, contract, pids["/h"], rq, cl, salt);
    const r = { nonce: salt, amount: 10_000n, requestHash: rq, responseHash: cl, ctHash: rq, keyHash: cl, claimsHash: rq, materialCommit: cl };
    parity.rsHash = (await view.read<Hex>("rsHash", [pids["/h"], codeHash, r])) === rsHash(r, pids["/h"], codeHash);
    parity.node = (await view.read<Hex>("node", [rq, cl])) === node(rq, cl);
    const ct = encrypt(salt, rq, new Uint8Array(96).fill(7));
    parity.decryptHash = (await view.read<Hex>("decryptHash", [salt, rq, bytesToHex(ct)])) === decryptHash(salt, rq, ct);
    parity.vault = (await view.vaultOf(pids["/h"])) === (await view.read<Address>("vaultAddress", [pids["/h"]]));
  }
  result.parity = { ...parity, ok: Object.values(parity).every(Boolean) };

  // ------------------------------------------------------------ actors
  const actions: Action[] = [];
  const onAction = (a: Action) => {
    actions.push(a);
    console.log(`  ${a.by.padEnd(8)} ${a.call.padEnd(16)} ${a.status}${a.gasUsed ? ` gas ${a.gasUsed}` : ""}${a.reason ? ` (${a.reason})` : ""}`);
  };
  const towerA = new Watchtower({ name: "tower-a", publicClient: pub, wallet: w["tower-a"], contract, dObs: 2n, onAction });
  const towerB = new Watchtower({ name: "tower-b", publicClient: pub, wallet: w["tower-b"], contract, dObs: 2n, noSimulation: true, onAction });
  const mkClient = (n: string, towers: Watchtower[] = []) =>
    new SigningClient({
      wallet: w[n],
      publicClient: pub,
      trustedContracts: [contract],
      maxDeposit: 100_000n,
      allowedTiers: [0, 1],
      dObs: 2n,
      dTx: 5n,
      pSwap: 10n ** 9n,
      pBind: 10n ** 9n,
      rho: 0.5,
      blockGasTarget: 25_000_000n,
      watchtowers: towers,
      onAction: (a) => onAction({ ...a, by: n }),
    });
  const clients: Record<string, SigningClient> = {
    "buyer-1": mkClient("buyer-1"),
    "buyer-2": mkClient("buyer-2"),
    "buyer-3": mkClient("buyer-3"),
    "buyer-4": mkClient("buyer-4"),
    "buyer-5": mkClient("buyer-5", [towerA, towerB]),
    "buyer-6": mkClient("buyer-6"),
    "buyer-7": mkClient("buyer-7"),
    "buyer-8": mkClient("buyer-8"),
    "buyer-9": mkClient("buyer-9", [towerA]),
    "buyer-10": mkClient("buyer-10"),
    "buyer-11": mkClient("buyer-11"),
    "buyer-12": mkClient("buyer-12"),
    "buyer-13": mkClient("buyer-13"),
  };
  const online = new Set(Object.keys(clients));
  online.delete("buyer-5"); // E4: offline right after paying
  online.delete("buyer-7"); // E6: offline until the third-party key dispute has ended
  online.delete("buyer-10"); // (c): offline until after the cursor, which processes the late seller's failure

  const usdc = (a: Address) => pub.readContract({ address: USDC, abi: erc20Abi, functionName: "balanceOf", args: [a] }) as Promise<bigint>;
  const addrs = { seller: sellerAddr, ...Object.fromEntries(Object.entries(w).map(([n, x]) => [n, x.account!.address])) } as Record<string, Address>;
  const before: Record<string, bigint> = {};
  for (const n of [...sellerNames, ...buyerNames, "tower-a", "tower-b", "stranger"]) before[n] = await usdc(addrs[n]);

  const tickAll = async (label: string) => {
    console.log(`[${label}] head ${await pub.getBlockNumber()}`);
    for (const n of online) await clients[n].tick();
    await towerA.tick();
    await towerB.tick();
  };

  // ------------------------------------------------------------ purchases
  const url = (p: string) => `${seller.base}${p}?feed=1`;
  const P: Record<string, Purchase> = {};
  console.log("[buy]");
  P.E1 = await clients["buyer-1"].buy(url("/h"));
  P.E1b = await clients["buyer-1"].buy(url("/hc"));
  P.E2 = await clients["buyer-2"].buy(url("/w"));
  P.E2b = await clients["buyer-3"].buy(url("/wb"));
  P.E3 = await clients["buyer-4"].buy(url("/k"));
  P.E4 = await clients["buyer-5"].buy(url("/t"));
  P.E5a = await clients["buyer-6"].buy(url("/x"));
  P.E5b = await clients["buyer-6"].buy(url("/r"));
  P.E6 = await clients["buyer-7"].buy(url("/c"));
  const ourl = (p: string) => `${sellerOf[p].base}${p}?feed=1`;
  P.Fa = await clients["buyer-8"].buy(ourl("/f")); // (a) fraud: false price, no material verifies
  P.Fb = await clients["buyer-9"].buy(ourl("/fh")); // (b) honest sale of the fraud seller, settled after (a)
  P.L = await clients["buyer-10"].buy(ourl("/l")); // (c) honest seller whose proof comes late
  P.M = await clients["buyer-11"].buy(ourl("/m")); // (e) seller that never anchors
  P.D = await clients["buyer-13"].buy(ourl("/d")); // seller that double-signs its anchor unit
  for (const [id, p] of Object.entries(P)) console.log(`  ${id} ${p.state}${p.reason ? `: ${p.reason}` : ""}${p.checks.length ? ` [${p.checks.join("; ")}]` : ""}`);
  const reservedAfterBuy = Object.fromEntries(Object.entries(clients).map(([n, cl]) => [n, cl.reserved()]));
  const sale0 = await view.sale(pids["/h"], P.E1.nonce!);
  const epoch = sale0.epoch;
  for (const [id, p] of Object.entries(P)) {
    if (!p.nonce || !p.pid) continue;
    const s = await view.sale(p.pid, p.nonce);
    if (s.payer !== "0x0000000000000000000000000000000000000000" && s.epoch !== epoch) throw new Error(`${id} settled in another epoch`);
  }
  await tickAll("after buy");

  // ------------------------------------------------------------ anchor
  const aE = await view.anchorDeadline(epoch);
  await mine((await view.lastBlock(epoch)) + c.D_INC + 1n - (await pub.getBlockNumber()));
  const anchors: Record<string, unknown> = {};
  for (const path of [...Object.keys(routes), "/f", "/fh", "/l", "/d"]) {
    const n = await view.read<Hex[]>("epochNonces", [pids[path], BigInt(epoch)]);
    if (n.length === 0) continue;
    anchors[path] = await sellerOf[path].anchor(pids[path], epoch);
  }
  console.log("[anchor]", JSON.stringify(anchors, (_k, v) => (typeof v === "bigint" ? v.toString() : v)));
  await mine(3n);
  // E6: a third party (colluding with the seller) opens a key dispute on
  // buyer-7's signed sale while buyer-7 is offline, without a mandate
  const sendAs = async (wc: WalletClient, fn: string, args: unknown[], by = "stranger") => {
    const hash = await wc.writeContract({ address: contract, abi: view.abi, functionName: fn, args, account: wc.account!, chain, gas: 3_000_000n });
    const rc = await pub.waitForTransactionReceipt({ hash, timeout: 300_000 });
    onAction({ by, pid: (typeof args[0] === "string" ? args[0] : "0x") as Hex, nonce: "0x", call: fn, tx: hash, gasUsed: rc.gasUsed, status: rc.status === "success" ? "sent" : "reverted" });
    return rc.status === "success";
  };
  const walletOf: Record<string, string> = {};
  for (const path of Object.keys(routes)) walletOf[path] = "seller";
  for (const [name, o] of Object.entries(other)) for (const path of Object.keys(o.routes)) walletOf[path] = name;
  const sampled = (R: bigint, nonce: Hex, v: bigint, cap: bigint) => {
    if (v >= cap) return true;
    const h = BigInt(keccak256(encodeAbiParameters([{ type: "uint256" }, { type: "bytes32" }], [R, nonce])));
    return (h * cap) >> 256n < v;
  };
  const sampleValues = async (ep: number, targets: Record<string, Hex[]>, paths = [...Object.keys(routes), "/f", "/fh", "/l", "/m", "/d"]) => {
    const head = await pub.getBlockNumber();
    const aEp = await view.anchorDeadline(ep);
    if (head <= aEp) await mine(aEp + 1n - head);
    if ((await pub.getBlockNumber()) > (await view.valueDeadline(ep))) throw new Error("past M_e before the sample request");
    for (const path of paths) {
      const n = await view.read<Hex[]>("epochNonces", [pids[path], BigInt(ep)]);
      if (n.length === 0) continue;
      const wn = walletOf[path];
      const hash = await w[wn].writeContract({ address: contract, abi: view.abi, functionName: "requestSample", args: [pids[path], BigInt(ep)], account: w[wn].account!, chain, gas: 1_000_000n });
      const rc = await pub.waitForTransactionReceipt({ hash, timeout: 300_000 });
      onAction({ by: wn, pid: pids[path], nonce: "0x", call: "requestSample", tx: hash, gasUsed: rc.gasUsed, status: rc.status === "success" ? "sent" : "reverted" });
      if (rc.status !== "success") {
        (result.vrf as { requests: unknown[] }).requests.push({ path, epoch: ep, reverted: true });
        continue;
      }
      let id = 0n;
      let input: Hex = "0x";
      for (const lg of rc.logs) {
        try {
          const ev = decodeEventLog({ abi: view.abi, data: lg.data, topics: lg.topics });
          if (ev.eventName === "SampleRequested") {
            id = (ev.args as unknown as { requestId: bigint }).requestId;
            input = (ev.args as unknown as { input: Hex }).input;
          }
        } catch {
          /* coordinator events */
        }
      }
      const want = targets[path] ?? [];
      let word: bigint | undefined;
      let tries = 0;
      if (want.length) {
        const amounts = await Promise.all(want.map(async (nn) => (await view.sale(pids[path], nn)).amount as bigint));
        for (let j = 0n; ; j++) {
          tries++;
          const cand = BigInt(keccak256(encodeAbiParameters([{ type: "string" }, { type: "uint256" }, { type: "uint256" }], ["e2e vrf word", id, j])));
          let R = BigInt(keccak256(encodeAbiParameters([{ type: "bytes32" }, { type: "uint256" }, { type: "uint256" }], [input, id, cand])));
          if (R === 0n) R = 1n;
          if (want.every((nn, i) => sampled(R, nn, amounts[i], profiles[path].cap))) {
            word = cand;
            break;
          }
        }
      }
      const fh = word === undefined
        ? await w.deployer.writeContract({ address: coordinator, abi: V.abi, functionName: "fulfillRandomWords", args: [id, contract], account: w.deployer.account!, chain, gas: 2_000_000n })
        : await w.deployer.writeContract({ address: coordinator, abi: V.abi, functionName: "fulfillRandomWordsWithOverride", args: [id, contract, [word]], account: w.deployer.account!, chain, gas: 2_000_000n });
      const frc = await pub.waitForTransactionReceipt({ hash: fh, timeout: 300_000 });
      onAction({ by: "vrf", pid: pids[path], nonce: "0x", call: "fulfill (mock)", tx: fh, gasUsed: frc.gasUsed, status: frc.status === "success" ? "sent" : "reverted" });
      const value = await view.read<bigint>("sampleValue", [keccak256(encodeAbiParameters([{ type: "bytes32" }, { type: "bytes32" }], [pids[path], numberToHex(BigInt(ep), { size: 32 })]))]);
      const inSample: Record<string, boolean> = {};
      for (const nn of n) inSample[nn] = await view.isSampled(pids[path], nn);
      (result.vrf as { requests: unknown[] }).requests.push({ path, epoch: ep, requestId: id, input, chosenWord: word !== undefined, word: word ?? null, tries, value, requestGas: rc.gasUsed, fulfillGas: frc.gasUsed, inSample });
      console.log(`  vrf ${path} epoch ${ep} request ${id} ${word !== undefined ? `chosen word after ${tries}` : "mock word"}: ${Object.values(inSample).filter(Boolean).length}/${n.length} sampled`);
    }
  };
  // double-signed anchor: the seller signs a second unit 1 with another
  // root0; anyone submits the evidence
  {
    const ev = await sellerOf["/d"].doubleSign(pids["/d"], epoch);
    await sendAs(w.stranger, "proveDoubleSign", [ev.header, ev.sig]);
  }
  {
    const hash = await w.stranger.writeContract({ address: USDC, abi: erc20Abi, functionName: "approve", args: [contract, 2n ** 255n], account: w.stranger.account!, chain });
    await pub.waitForTransactionReceipt({ hash, timeout: 300_000 });
    const al = await view.anchoredLeaf(pids["/c"], P.E6.nonce!, epoch);
    await sendAs(w.stranger, "openDispute", [al!.opening, 2, "0x", 0]);
  }
  await tickAll("after anchor: automatic disputes");
  await seller.answerDisputes();
  await tickAll("after answers: decryption challenges");
  await mine(c.T_D + 2n);
  await sendAs(w.stranger, "closeDispute", [pids["/c"], P.E6.nonce!, 2, 0]); // ends on the seller's side
  const e6AfterThirdParty = await view.dispute(pids["/c"], P.E6.nonce!, 2, 0);
  online.add("buyer-7");
  await tickAll("after T_d, T_x: closing");

  // ------------------------------------------------------------ sample values
  // After A_e each seller requests the sample value of each of its profile
  // epochs with a complete anchor (the never-anchored /m has none: its
  // request reverts, and the missed anchor is a failure either way). The
  // expectations fixed before the run need four sales in the sample: (a)
  // the fraud sale, (b) the fraud seller's honest sale whose proof passes,
  // (c) the late seller's sale, and (d) the re-entry sale. For those
  // profile epochs the mock is fulfilled with the first word of the
  // sequence keccak256("e2e vrf word", request id, j), j = 0, 1, ..., under
  // which the scenario's sales are sampled (the mock lets the test choose
  // the word; a real coordinator does not). Every other request is
  // fulfilled with the mock's own word keccak256(request id, 0).
  await sampleValues(epoch, { "/f": [P.Fa.nonce!], "/fh": [P.Fb.nonce!], "/l": [P.L.nonce!] });

  // ------------------------------------------------------------ proofs
  await mine((await view.valueDeadline(epoch)) + 1n - (await pub.getBlockNumber()));
  const proofs: Record<string, unknown> = {};
  // the main seller proves every sampled sale, refunded ones included; the
  // fraud seller tries (a) and proves (b); the late seller waits
  for (const path of [...Object.keys(routes), "/f", "/fh", "/d"]) proofs[path] = await sellerOf[path].prove(pids[path], epoch);
  console.log("[prove]", JSON.stringify(proofs, (_k, v) => (typeof v === "bigint" ? v.toString() : v)));
  await tickAll("after proofs");

  // ------------------------------------------------------------ proof deadline M_e + T_p
  await mine((await view.valueDeadline(epoch)) + c.T_P + 1n - (await pub.getBlockNumber()));
  proofs["/l"] = await sellerOf["/l"].prove(pids["/l"], epoch); // too late: reverts
  const lateAccountBefore = await view.account(addrs["seller-late"]);
  await tickAll("M_e + T_p + 1: failure processing and claims");
  const fraudAfterFailure = await view.account(addrs["seller-fraud"]);

  // ------------------------------------------------------------ key dispute deadline
  await mine(aE + c.T_C - c.D_INC - (await pub.getBlockNumber()));
  await tickAll("A_e + T_c - d_inc: key disputes");
  await seller.answerDisputes();
  await tickAll("after key answers: decryption challenges");
  await mine(c.T_X + 2n);
  await tickAll("after T_x: closing");

  // ------------------------------------------------------------ release
  const target = [aE + c.T_C, await view.signWindowEnd(epoch)].reduce((a, b) => (a > b ? a : b)) + 1n;
  const head = await pub.getBlockNumber();
  if (target > head) await mine(target - head);
  const releases: Record<string, unknown> = {};
  releases.seller = await seller.release(epoch);
  releases["seller-fraud"] = await other["seller-fraud"].seller.release(epoch);
  releases["seller-late"] = await other["seller-late"].seller.release(epoch, w.stranger); // the cursor processes the late seller's failure
  releases["seller-miss"] = await other["seller-miss"].seller.release(epoch);
  releases["seller-dbl"] = await other["seller-dbl"].seller.release(epoch);
  console.log("[release]", JSON.stringify(releases, (_k, v) => (typeof v === "bigint" ? v.toString() : v)));
  const lateAccountAfter = await view.account(addrs["seller-late"]);
  const lateStatusAfterCursor = (await view.sale(pids["/l"], P.L.nonce!)).status;
  await tickAll("after release");
  online.add("buyer-10");
  await tickAll("buyer-10 back: claims");

  // ------------------------------------------------------------ (d) re-entry
  const fraudSeller = other["seller-fraud"].seller;
  P.R0 = await clients["buyer-12"].buy(ourl("/fh")); // suspended: no settlement
  const r0State = P.R0.state; // read now: the task ends later once validBefore passes
  const reentry = await fraudSeller.reenter(1_000_000n);
  const fraudAfterReentry = await view.account(addrs["seller-fraud"]);
  P.R1 = await clients["buyer-12"].buy(ourl("/fh"));
  const s1 = await view.sale(pids["/fh"], P.R1.nonce!);
  const e1 = s1.epoch;
  await mine((await view.lastBlock(e1)) + c.D_INC + 1n - (await pub.getBlockNumber()));
  const anchorR1 = await fraudSeller.anchor(pids["/fh"], e1);
  await tickAll("re-entry epoch: after anchor");
  await sampleValues(e1, { "/fh": [P.R1.nonce!] }, ["/fh"]);
  await mine((await view.valueDeadline(e1)) + 1n - (await pub.getBlockNumber()));
  const proofR1 = await fraudSeller.prove(pids["/fh"], e1);
  const t1 = [(await view.anchorDeadline(e1)) + c.T_C, await view.signWindowEnd(e1)].reduce((a, b) => (a > b ? a : b)) + 1n;
  await mine(t1 - (await pub.getBlockNumber()));
  const releaseR1 = await fraudSeller.release(e1);
  await tickAll("re-entry epoch: after release");

  const after: Record<string, bigint> = {};
  for (const n of Object.keys(before)) after[n] = await usdc(addrs[n]);
  const delta = (n: string) => after[n] - before[n];
  const status = async (p: Purchase) => (p.pid && p.nonce ? (await view.sale(p.pid, p.nonce)).status : -1);
  const disp = async (p: Purchase, k: number, side = 1) => (p.pid && p.nonce ? await view.dispute(p.pid, p.nonce, k, side) : undefined);
  const count = (pred: (a: Action) => boolean) => actions.filter(pred).length;
  const by = (n: string, call: string, st = "sent") => count((a) => a.by === n && a.call === call && a.status === st);
  const price = 10_000n;
  const dep = 50_000n;

  // ------------------------------------------------------------ verdicts
  const sc: { id: string; pass: boolean; checks: Record<string, unknown> }[] = [];
  const add = (id: string, checks: Record<string, unknown>, expect: Record<string, unknown>) => {
    const pass = Object.entries(expect).every(([k, v]) => JSON.stringify(checks[k], big) === JSON.stringify(v, big));
    sc.push({ id, pass, checks: { ...checks, expected: expect } });
  };
  const big = (_k: string, v: unknown) => (typeof v === "bigint" ? v.toString() : v);

  add(
    "E1 honest sale (plaintext) and E1b (ciphertext, key on signature)",
    {
      e1State: P.E1.state,
      e1bState: P.E1b.state,
      e1Status: await status(P.E1),
      e1bStatus: await status(P.E1b),
      e1bKey: P.E1b.task?.keyStatus,
      disputesOpenedByBuyer1: by("buyer-1", "openDispute"),
      buyerDelta: delta("buyer-1"),
      reservedAtBuy: reservedAfterBuy["buyer-1"],
      reservedAtEnd: clients["buyer-1"].reserved(),
      proofs: [proofs["/h"], proofs["/hc"]],
    },
    { e1State: "done", e1bState: "done", e1Status: 2, e1bStatus: 2, e1bKey: "ok", disputesOpenedByBuyer1: 0, buyerDelta: -2n * price, reservedAtEnd: { eth: 0n, token: 0n } },
  );
  add(
    "E2 non-delivery dispute, no answer, refund",
    { state: P.E2.state, signed: P.E2.task?.signed, status: await status(P.E2), opened: by("buyer-2", "openDispute"), closed: by("buyer-2", "closeDispute"), buyerDelta: delta("buyer-2"), checks: P.E2.checks },
    { signed: false, status: 1, opened: 1, closed: 1, buyerDelta: 0n },
  );
  add(
    "E2b non-delivery dispute, ct not decrypting to h_r, decryption challenge, refund",
    { state: P.E2b.state, status: await status(P.E2b), opened: by("buyer-3", "openDispute"), challenged: by("buyer-3", "challengeDecrypt"), bad: (await disp(P.E2b, 1))?.bad, buyerDelta: delta("buyer-3") },
    { status: 1, opened: 1, challenged: 1, bad: true, buyerDelta: 0n },
  );
  add(
    "E3 key dispute (key withheld, then a key under which ct does not decrypt to h_r)",
    { state: P.E3.state, signed: P.E3.task?.signed, keyStatusBeforeDispute: P.E3.task?.keyStatus, status: await status(P.E3), opened: by("buyer-4", "openDispute"), challenged: by("buyer-4", "challengeDecrypt"), bad: (await disp(P.E3, 2))?.bad, buyerDelta: delta("buyer-4") },
    { signed: true, status: 1, opened: 1, challenged: 1, bad: true, buyerDelta: 0n },
  );
  const d4 = await disp(P.E4, 1);
  add(
    "E4 two watchtowers dispute for an offline buyer",
    {
      buyerActions: count((a) => a.by === "buyer-5"),
      openA: by("tower-a", "openDispute"),
      openBreverted: by("tower-b", "openDispute", "reverted"),
      openBsent: by("tower-b", "openDispute"),
      opener: d4?.opener,
      authorized: d4?.authorized,
      challenges: by("tower-a", "challengeDecrypt") + by("tower-b", "challengeDecrypt"),
      status: await status(P.E4),
      buyerDelta: delta("buyer-5"),
      towerAdelta: delta("tower-a"),
      towerBdelta: delta("tower-b"),
    },
    { buyerActions: 0, openA: 1, openBreverted: 1, openBsent: 0, opener: addrs["tower-a"], authorized: true, status: 1, buyerDelta: 0n, towerAdelta: 0n, towerBdelta: 0n },
  );
  add(
    "E5a 402 names a profile whose receiving address is not payTo: no payment",
    { state: P.E5a.state, reason: P.E5a.reason, settled: P.E5a.nonce ? (await view.sale(P.E5a.pid!, P.E5a.nonce)).payer : "none" },
    { state: "refused", settled: "none" },
  );
  add(
    "E5b receipt carries another profile id: no signature, non-delivery dispute, refund",
    { state: P.E5b.state, signed: P.E5b.task?.signed, checks: P.E5b.checks, status: await status(P.E5b), opened: by("buyer-6", "openDispute") },
    { signed: false, status: 1, opened: 1 },
  );
  const d6 = await disp(P.E6, 2);
  add(
    "E6 third-party key dispute ends on the seller's side; the payer-side slot opens on its own and the stored key answers it",
    {
      signed: P.E6.task?.signed,
      thirdPartyClosedBad: e6AfterThirdParty.bad,
      thirdPartyClosedState: e6AfterThirdParty.state,
      payerSlotOpener: d6?.opener,
      payerSide: d6?.authorized,
      buyerOpened: by("buyer-7", "openDispute"),
      buyerChallenged: by("buyer-7", "challengeDecrypt"),
      sellerAnswers: seller.log.filter((l) => l.startsWith("answerKey /c")).length,
      status: await status(P.E6),
      buyerDelta: delta("buyer-7"),
      strangerDelta: delta("stranger"),
    },
    { signed: true, thirdPartyClosedBad: false, thirdPartyClosedState: 3, payerSlotOpener: addrs["buyer-7"], payerSide: true, buyerOpened: 1, buyerChallenged: 1, sellerAnswers: 1, status: 1, buyerDelta: 0n, strangerDelta: -dep },
  );
  add(
    "seller account",
    { sellerDelta: delta("seller"), failures: (await view.account(sellerAddr)).failures, suspended: (await view.account(sellerAddr)).suspended, releases: releases.seller },
    { sellerDelta: 2n * price + dep, failures: 0, suspended: false },
  );
  const cap = 1_000_000n;
  const fa = await view.sale(pids["/f"], P.Fa.nonce!);
  add(
    "(a) fraud seller: sampled sale without a pass by T_p, confirmed failure, freeze, deduction, suspension",
    {
      signed: P.Fa.task?.signed,
      sellerProofsReverted: (proofs["/f"] as { reverted: number }).reverted,
      declaredBy: by("buyer-8", "declareSampleFailure"),
      failuresAfter: fraudAfterFailure.failures,
      bondAfter: fraudAfterFailure.bond,
      lockedAfter: fraudAfterFailure.locked,
      suspendedAfter: fraudAfterFailure.suspended,
      saleStatus: fa.status,
      claimedBy: by("buyer-8", "claimFrozen"),
      buyerDelta: delta("buyer-8"),
      noSettlementWhileSuspended: P.R0.nonce ? (await view.sale(pids["/fh"], P.R0.nonce)).payer : "none",
    },
    { signed: true, sellerProofsReverted: 1, declaredBy: 1, failuresAfter: 1, bondAfter: 0n, lockedAfter: cap, suspendedAfter: true, saleStatus: 1, claimedBy: 1, buyerDelta: 0n, noSettlementWhileSuspended: "0x0000000000000000000000000000000000000000" },
  );
  const fb = await view.sale(pids["/fh"], P.Fb.nonce!);
  add(
    "(b) frozen sale of the same seller (settled after s_f, its own proof passed): the buyer's claim",
    {
      signed: P.Fb.task?.signed,
      passed: await view.passed(pids["/fh"], P.Fb.nonce!),
      towerAcks: P.Fb.checks.includes("watchtower acknowledgement missing") ? 0 : 1,
      claims: by("buyer-9", "claimFrozen") + by("tower-a", "claimFrozen"),
      saleStatus: fb.status,
      buyerDelta: delta("buyer-9"),
    },
    { signed: true, passed: true, towerAcks: 1, claims: 1, saleStatus: 1, buyerDelta: 0n },
  );
  add(
    "(c) honest seller whose proof comes after T_p: failure in the cursor, its cost",
    {
      signed: P.L.task?.signed,
      lateProofReverted: (proofs["/l"] as { reverted: number }).reverted,
      failuresBeforeCursor: lateAccountBefore.failures,
      failuresAfterCursor: lateAccountAfter.failures,
      deducted: lateAccountAfter.locked,
      bondLeft: lateAccountAfter.bond,
      suspended: lateAccountAfter.suspended,
      statusAfterCursor: lateStatusAfterCursor,
      claimedBy: by("buyer-10", "claimFrozen"),
      buyerDelta: delta("buyer-10"),
      sellerDelta: delta("seller-late"),
      sellerGas: actions.filter((a) => a.by === "seller-late").length,
    },
    { signed: true, lateProofReverted: 1, failuresBeforeCursor: 0, failuresAfterCursor: 1, deducted: cap, bondLeft: 0n, suspended: true, statusAfterCursor: 4, claimedBy: 1, buyerDelta: 0n, sellerDelta: 0n },
  );
  add(
    "(d) re-entry: bond restored, new episode, a new sale paid by the cursor",
    {
      refusedWhileSuspended: r0State,
      reentryOk: reentry.ok,
      bond: fraudAfterReentry.bond,
      episode: fraudAfterReentry.episode,
      suspended: fraudAfterReentry.suspended,
      newSaleEpisode: s1.episode,
      newSaleSigned: P.R1.task?.signed,
      anchored: anchorR1.ok,
      proven: proofR1.proven,
      newSaleStatus: (await view.sale(pids["/fh"], P.R1.nonce!)).status,
      sellerDelta: delta("seller-fraud"),
      buyerDelta: delta("buyer-12"),
    },
    { refusedWhileSuspended: "unsigned", reentryOk: true, bond: cap, episode: 2, suspended: false, newSaleEpisode: 2, newSaleSigned: true, anchored: true, proven: 1, newSaleStatus: 2, sellerDelta: price - cap, buyerDelta: -price },
  );
  const ms = await view.sale(pids["/m"], P.M.nonce!);
  const missAcct = await view.account(addrs["seller-miss"]);
  add(
    "(e) missed anchor: declared after A_e, freeze from the epoch's first sale, deduction, claim",
    {
      signed: P.M.task?.signed,
      declaredBy: by("buyer-11", "declareAnchorMissed"),
      missed: await view.missed(pids["/m"], epoch),
      failures: missAcct.failures,
      locked: missAcct.locked,
      suspended: missAcct.suspended,
      saleStatus: ms.status,
      claimedBy: by("buyer-11", "claimFrozen"),
      buyerDelta: delta("buyer-11"),
      sellerDelta: delta("seller-miss"),
    },
    { signed: true, declaredBy: 1, missed: true, failures: 1, locked: cap, suspended: true, saleStatus: 1, claimedBy: 1, buyerDelta: 0n, sellerDelta: 0n },
  );
  const dblAcct = await view.account(addrs["seller-dbl"]);
  add(
    "double-signed anchor: evidence by anyone, failure, the buyer's claim",
    {
      evidence: by("stranger", "proveDoubleSign"),
      failures: dblAcct.failures,
      locked: dblAcct.locked,
      claimedBy: by("buyer-13", "claimFrozen"),
      saleStatus: (await view.sale(pids["/d"], P.D.nonce!)).status,
      buyerDelta: delta("buyer-13"),
    },
    { evidence: 1, failures: 1, locked: cap, claimedBy: 1, saleStatus: 1, buyerDelta: 0n },
  );
  result.gas = gasSummary(actions, [seller, ...Object.values(other).map((o) => o.seller)], { deployGas, bonds, reentry, releases, releaseR1, anchors });
  void dep;
  void hexToBytes;
  result.scenarios = sc;
  result.actions = actions;
  result.sellerLog = seller.log;
  result.usdcDelta = Object.fromEntries(Object.keys(before).map((n) => [n, delta(n)]));
  result.purchases = Object.fromEntries(Object.entries(P).map(([k, p]) => [k, { state: p.state, reason: p.reason, checks: p.checks, note: p.task?.note }]));
  for (const s of sc) console.log(`${s.pass ? "PASS" : "FAIL"} ${s.id}\n  ${JSON.stringify(s.checks, big)}`);
  await seller.stop();
  for (const o of Object.values(other)) await o.seller.stop();
}

/** Gas of the calls the runs made, grouped by call (fork receipts). */
function gasSummary(actions: Action[], sellers: RefSeller[], extra: Record<string, unknown>) {
  const byCall: Record<string, string[]> = {};
  for (const a of actions) {
    if (!a.gasUsed) continue;
    const k = `${a.call}${a.status === "reverted" ? " (reverted)" : ""}`;
    (byCall[k] ??= []).push(`${a.by}:${a.gasUsed}`);
  }
  return { byCall, sellerLogs: sellers.map((x) => x.log.filter((l) => l.includes("gas"))), ...extra };
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
