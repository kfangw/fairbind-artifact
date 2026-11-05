// Read side of the settlement contract: ABI, constants, profile, sales,
// anchor units (decoded from the anchor transactions' calldata) and leaf
// openings with Merkle paths. Used by the signing client and the watchtower.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import {
  decodeFunctionData,
  encodeAbiParameters,
  keccak256,
  type Abi,
  type Address,
  type Hex,
  type PublicClient,
} from "viem";
import { recoverTypedDataAddress } from "viem";
import { ACK_TYPES, ackMessage, domain, leaf0Of, leafOf, levels, merklePath, rsHash, ZERO32, type Profile, type Receipt } from "./hashing.ts";

const HALF_N = 0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0n;

/** The anchor's acceptance of a buyer signature: 65 bytes, low s, v in
 * {27, 28}, and the BuyerAck digest recovers to the payer. */
export async function ackSignedBy(l: Leaf, pid: Hex, codeHash: Hex, chainId: number, contract: Address, payer: Address): Promise<boolean> {
  const sig = l.sigB;
  if (!sig || sig.length !== 2 + 130) return false;
  const s = BigInt("0x" + sig.slice(66, 130));
  const v = parseInt(sig.slice(130, 132), 16);
  if (s > HALF_N || (v !== 27 && v !== 28)) return false;
  try {
    const who = await recoverTypedDataAddress({
      domain: domain(chainId, contract),
      types: ACK_TYPES,
      primaryType: "BuyerAck",
      message: ackMessage(l.rs, pid, codeHash, l.accept),
      signature: sig,
    });
    return who.toLowerCase() === payer.toLowerCase();
  } catch {
    return false;
  }
}

const here = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = resolve(here, "../../..");

/** Loads a compiled artifact of the sdk Foundry profile (forge build first). */
export function artifact(file: string, name: string): { abi: Abi; bytecode: Hex } {
  const j = JSON.parse(readFileSync(resolve(REPO_ROOT, "out/sdk", file, `${name}.json`), "utf8"));
  return { abi: j.abi as Abi, bytecode: j.bytecode.object as Hex };
}

/** The settlement contract's ABI with its module's: the module's calls are
 * made on the settlement contract's address, which delegates them. Events and
 * errors the two share appear once. */
export const settlementAbi = (): Abi => {
  const main = artifact("SampledSettlement.sol", "SampledSettlement").abi as readonly { type: string; name?: string; inputs?: { type: string }[] }[];
  const mod = artifact("SampledSettlement.sol", "SettlementModule").abi as readonly { type: string; name?: string; inputs?: { type: string }[] }[];
  const sig = (x: { type: string; name?: string; inputs?: { type: string }[] }) => `${x.type}:${x.name}(${(x.inputs ?? []).map((i) => i.type).join(",")})`;
  const seen = new Set(main.map(sig));
  return [...main, ...mod.filter((x) => x.type !== "constructor" && !seen.has(sig(x)))] as unknown as Abi;
};

export interface Constants {
  genesis: bigint;
  EPOCH_BLOCKS: bigint;
  A_A: bigint;
  D_INC: bigint;
  TAU_V: bigint;
  T_V: bigint;
  W_B: bigint;
  T_RS: bigint;
  T_C: bigint;
  T_P: bigint;
  T_D: bigint;
  T_X: bigint;
  C_ND: bigint;
  P_FLOOR: bigint;
  T_CLAIM: bigint;
}

export interface Sale {
  payer: Address;
  amount: bigint;
  settledBlock: number;
  epoch: number;
  validAfter: bigint;
  status: number;
  bindingCompleted: boolean;
  flags: number;
  episode: number;
  ordinal: number;
  binding: Hex;
}

export const ST_HELD = 0;
export const ST_REFUNDED = 1;
export const ST_PAID = 2;
export const ST_ACCEPT_PAID = 3;
export const ST_FROZEN = 4;

/** Seller account: bond, locked deductions, cap high-water mark, episode,
 * failures, suspension. */
export interface AccountState {
  bond: bigint;
  locked: bigint;
  capHigh: bigint;
  episode: number;
  failures: number;
  suspended: boolean;
  settlements: number;
}

export interface Leaf {
  rs: Receipt;
  unanswered: number;
  accept: boolean;
  sigB: Hex;
}

export interface Unit {
  pid: Hex;
  epoch: number;
  count: number;
  unitNo: number;
  first: Hex;
  last: Hex;
  root: Hex;
  root0: Hex;
  snapshot: Address[];
  leaves: Leaf[];
  sellerSig: Hex;
}

export interface Opening {
  pid: Hex;
  epoch: number;
  unitNo: number;
  index: bigint;
  rs: Receipt;
  unanswered: number;
  sigHash: Hex;
  beta: boolean;
  accept: boolean;
  path: Hex[];
}

export interface DisputeState {
  opener: Address;
  authorized: boolean;
  state: number;
  bad: boolean;
  deadline: bigint;
  deposit: bigint;
  answerBlock: bigint;
}

/** Seller answers kept on chain per purchase. */
export interface AnswerState {
  key: Hex;
  ctkBlock: bigint;
  kBlock: bigint;
  ackBlock: bigint;
}

export const SIDE_THIRD = 0;
export const SIDE_PAYER = 1;

/** The contract's view of one anchored leaf, with the opening to use. */
export interface AnchoredLeaf {
  leaf: Leaf;
  beta: boolean;
  hRS: Hex;
  opening: Opening;
}

export class ChainView {
  readonly abi: Abi;
  private constantsCache?: Constants;
  private unitCache = new Map<Hex, Unit[]>();
  private codeHashCache = new Map<Hex, Hex>();

  readonly client: PublicClient;
  readonly contract: Address;

  constructor(client: PublicClient, contract: Address) {
    this.client = client;
    this.contract = contract;
    this.abi = settlementAbi();
  }

  read<T>(functionName: string, args: unknown[] = []): Promise<T> {
    return this.client.readContract({ address: this.contract, abi: this.abi, functionName, args }) as Promise<T>;
  }

  async constants(): Promise<Constants> {
    if (this.constantsCache) return this.constantsCache;
    const names = ["genesis", "EPOCH_BLOCKS", "A_A", "D_INC", "TAU_V", "T_V", "W_B", "T_RS", "T_C", "T_P", "T_D", "T_X", "C_ND", "P_FLOOR", "T_CLAIM"] as const;
    const vals = await Promise.all(names.map((n) => this.read<bigint>(n)));
    const c = Object.fromEntries(names.map((n, i) => [n, vals[i]])) as unknown as Constants;
    this.constantsCache = c;
    return c;
  }

  async head(): Promise<bigint> {
    return this.client.getBlockNumber({ cacheTime: 0 });
  }

  async chainTime(): Promise<bigint> {
    return (await this.client.getBlock({ blockTag: "latest" })).timestamp;
  }

  // ------------------------------------------------------------ timing
  async lastBlock(epoch: number): Promise<bigint> {
    const c = await this.constants();
    return c.genesis + (BigInt(epoch) + 1n) * c.EPOCH_BLOCKS - 1n;
  }
  async anchorDeadline(epoch: number): Promise<bigint> {
    return (await this.lastBlock(epoch)) + (await this.constants()).A_A;
  }
  async valueDeadline(epoch: number): Promise<bigint> {
    const c = await this.constants();
    return (await this.anchorDeadline(epoch)) + c.TAU_V + 1n + c.T_V;
  }
  /** W_e = M_e + w_b. */
  async signWindowEnd(epoch: number): Promise<bigint> {
    return (await this.valueDeadline(epoch)) + (await this.constants()).W_B;
  }
  /** t_sig = min(eta + T_rs, W_e - d_inc). */
  async signDeadline(eta: bigint, epoch: number): Promise<bigint> {
    const c = await this.constants();
    const a = eta + c.T_RS;
    const b = (await this.signWindowEnd(epoch)) - c.D_INC;
    return a < b ? a : b;
  }

  // ------------------------------------------------------------ state
  async profile(pid: Hex): Promise<Profile> {
    return this.read<Profile>("profile", [pid]);
  }
  async vaultOf(pid: Hex): Promise<Address> {
    return this.read<Address>("vaultOf", [pid]);
  }
  async token(): Promise<Address> {
    return this.read<Address>("token");
  }
  async sale(pid: Hex, nonce: Hex): Promise<Sale> {
    return this.read<Sale>("sale", [pid, nonce]);
  }
  /** One slot: side 1 payer-side, side 0 third-party. */
  async dispute(pid: Hex, nonce: Hex, kind: number, side: number): Promise<DisputeState> {
    return this.read<DisputeState>("dispute", [pid, nonce, kind, side]);
  }
  async answers(pid: Hex, nonce: Hex): Promise<AnswerState> {
    return this.read<AnswerState>("answers", [pid, nonce]);
  }
  async account(acct: Address): Promise<AccountState> {
    return this.read<AccountState>("account", [acct]);
  }
  /** End of the claim period of a frozen sale, 0 if it is not frozen. */
  async claimDeadline(pid: Hex, nonce: Hex): Promise<bigint> {
    return this.read<bigint>("claimDeadline", [pid, nonce]);
  }
  async passed(pid: Hex, nonce: Hex): Promise<boolean> {
    return this.read<boolean>("passed", [keccak256(encodeAbiParameters([{ type: "bytes32" }, { type: "bytes32" }], [pid, nonce]))]);
  }
  async isSampled(pid: Hex, nonce: Hex): Promise<boolean> {
    return this.read<boolean>("isSampled", [pid, nonce]);
  }
  async missed(pid: Hex, epoch: number): Promise<boolean> {
    const k = keccak256(encodeAbiParameters([{ type: "bytes32" }, { type: "bytes32" }], [pid, `0x${BigInt(epoch).toString(16).padStart(64, "0")}`]));
    return (await this.read<bigint>("missedAt", [k])) !== 0n;
  }
  /** Whether the anchor's completion fixed a transfer for the sale (a
   * refund or an acceptance payment) that no pull call has made yet. */
  async pullPending(pid: Hex, nonce: Hex): Promise<boolean> {
    return (await this.read<readonly [boolean, bigint]>("pullPending", [pid, nonce]))[0];
  }
  async epochComplete(pid: Hex, epoch: number): Promise<boolean> {
    return this.read<boolean>("epochComplete", [pid, BigInt(epoch)]);
  }
  async codeHashAt(addr: Address): Promise<Hex> {
    const code = await this.client.getCode({ address: addr });
    return code ? keccak256(code) : ZERO32;
  }

  /** Units stored for (pid, epoch), decoded from the anchor transactions. */
  async units(pid: Hex, epoch: number): Promise<Unit[]> {
    const key = `${pid}:${epoch}` as Hex;
    const cached = this.unitCache.get(key);
    if (cached && cached.length > 0) return cached;
    const logs = await this.client.getContractEvents({
      address: this.contract,
      abi: this.abi,
      eventName: "UnitStored",
      args: { pid, epoch },
      fromBlock: (await this.constants()).genesis,
      toBlock: "latest",
    });
    const out: Unit[] = [];
    for (const lg of logs) {
      const tx = await this.client.getTransaction({ hash: lg.transactionHash! });
      const d = decodeFunctionData({ abi: this.abi, data: tx.input });
      if (d.functionName !== "anchorUnit") continue; // direct calls only in this reference
      const u = (d.args as unknown[])[0] as Unit;
      const ev = (lg as unknown as { args: { unitNo: number } }).args;
      if (u.pid === pid && u.epoch === epoch && u.unitNo === ev.unitNo) out.push(u);
    }
    this.unitCache.set(key, out);
    return out;
  }

  async verifierCodeHash(pid: Hex): Promise<Hex> {
    const c = this.codeHashCache.get(pid);
    if (c) return c;
    const p = await this.profile(pid);
    this.codeHashCache.set(pid, p.codeHash);
    return p.codeHash;
  }

  /** The anchored leaf of (pid, nonce) and its opening, or undefined. The
   * buyer-signature flag beta is recomputed as the anchor did (ecrecover of
   * the BuyerAck digest against the payer). */
  async anchoredLeaf(pid: Hex, nonce: Hex, epoch: number): Promise<AnchoredLeaf | undefined> {
    const chainId = await this.client.getChainId();
    const codeHash = await this.verifierCodeHash(pid);
    for (const u of await this.units(pid, epoch)) {
      const idx = u.leaves.findIndex((l) => l.rs.nonce.toLowerCase() === nonce.toLowerCase());
      if (idx < 0) continue;
      const hashes: Hex[] = [];
      let mine: AnchoredLeaf | undefined;
      for (let i = 0; i < u.leaves.length; i++) {
        const l = u.leaves[i];
        const hRS = l.unanswered === 0 ? rsHash(l.rs, pid, codeHash) : ZERO32;
        const sigHash = l.sigB && l.sigB !== "0x" ? keccak256(l.sigB) : ZERO32;
        let beta = false;
        if (l.unanswered === 0 && sigHash !== ZERO32) {
          const s = await this.sale(pid, l.rs.nonce);
          beta = await ackSignedBy(l, pid, codeHash, chainId, this.contract, s.payer);
        }
        const acc = beta && l.accept;
        hashes.push(leafOf(leaf0Of(l.rs.nonce, hRS, l.unanswered), sigHash, beta, acc));
        if (i === idx) {
          mine = {
            leaf: l,
            beta,
            hRS,
            opening: {
              pid,
              epoch,
              unitNo: u.unitNo,
              index: BigInt(i),
              rs: l.rs,
              unanswered: l.unanswered,
              sigHash,
              beta,
              accept: acc,
              path: [],
            },
          };
        }
      }
      if (!mine) continue;
      mine.opening.path = merklePath(levels(hashes), idx);
      return mine;
    }
    return undefined;
  }
}
