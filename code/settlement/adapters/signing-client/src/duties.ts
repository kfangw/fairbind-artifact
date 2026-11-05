// The obligation engine shared by the signing client and the watchtower.
// Each step reads the chain, decides which duty is due for one purchase, and
// sends at most the transactions that duty needs. Every call is simulated
// first, so a duty another sender already performed (a dispute opened, a
// challenge recorded, a dispute closed) is skipped without a transaction.
import {
  bytesToHex,
  erc20Abi,
  hexToBytes,
  maxUint256,
  type Account,
  type Address,
  type Hex,
  type WalletClient,
} from "viem";
import { ChainView, SIDE_PAYER, SIDE_THIRD } from "./chain.ts";
import { decryptHash, F_CT, rsHash, type SignedReceipt } from "./hashing.ts";

export const K_NONDELIVERY = 1;
export const K_KEY = 2;
export const D_OPEN = 1;
export const D_ANSWERED = 2;
export const D_CLOSED = 3;
export const ST_HELD = 0;
export const ST_REFUNDED = 1;
export const ST_FROZEN = 4;
const SF_FAILED = 4;

/** What a sender knows about one purchase. The payer's client knows all of
 * it; a watchtower knows what the client handed over. */
export interface Task {
  pid: Hex;
  nonce: Hex;
  payer: Address;
  validBefore: bigint;
  /** sigma_B was made (the client signed the receipt). */
  signed: boolean;
  /** The payer's dispute mandate sigma_W naming this sender as delegate,
   * and the kinds it delegates (for senders other than the payer). */
  mandate?: Hex;
  mandateKinds?: number;
  /** The receipt the client signed (for the swap proof). */
  receipt?: SignedReceipt;
  /** sigma_B, handed to watchtowers before (or with) the seller. */
  sigB?: Hex;
  /** The ciphertext the client checked against h_ct before signing. */
  ct?: Hex;
  /** Ciphertext profiles: whether the off-chain key k arrived and decrypted
   * to h_r ("ok"), arrived and did not ("bad"), or has not arrived. */
  keyStatus?: "ok" | "bad" | "missing";
  offchainKey?: Hex;
  /** The binding triple, for the completion call (client only). */
  binding?: { requestHash: Hex; claimsHash: Hex; salt: Hex };
  /** Chain blocks of observation and inclusion delays the client budgets. */
  done?: boolean;
  /** A claim of this frozen sale was sent by this sender. */
  claimed?: boolean;
  note?: string;
}

export interface Action {
  by: string;
  pid: Hex;
  nonce: Hex;
  call: string;
  tx?: Hex;
  gasUsed?: bigint;
  status: "sent" | "skipped" | "reverted";
  reason?: string;
}

export interface DutyOptions {
  name: string;
  /** Observation delay d_obs in blocks (anchor visibility budget). */
  dObs: bigint;
  /** Send without simulating first and without checking whether the
   * dispute is already open (a blind sender, used to test duplicates). */
  noSimulation?: boolean;
  onAction?: (a: Action) => void;
}

export class Duties {
  private approved = false;
  private blindSent = new Set<string>();
  readonly actions: Action[] = [];

  readonly view: ChainView;
  readonly wallet: WalletClient;
  readonly opts: DutyOptions;

  constructor(view: ChainView, wallet: WalletClient, opts: DutyOptions) {
    this.view = view;
    this.wallet = wallet;
    this.opts = opts;
  }

  get sender(): Address {
    return (this.wallet.account as Account).address;
  }

  private record(a: Action) {
    this.actions.push(a);
    this.opts.onAction?.(a);
  }

  /** Simulate, then send one call; returns true when the call was mined
   * successfully. A failed simulation is a skip, not an error. */
  async send(task: Task, functionName: string, args: unknown[]): Promise<boolean> {
    const base = { address: this.view.contract, abi: this.view.abi, functionName, args, account: this.wallet.account as Account, chain: this.wallet.chain };
    if (!this.opts.noSimulation) {
      try {
        await this.view.client.simulateContract(base);
      } catch (e) {
        this.record({ by: this.opts.name, pid: task.pid, nonce: task.nonce, call: functionName, status: "skipped", reason: shortError(e) });
        return false;
      }
    }
    let hash: Hex;
    try {
      hash = await this.wallet.writeContract({ ...base, gas: 3_000_000n });
    } catch (e) {
      this.record({ by: this.opts.name, pid: task.pid, nonce: task.nonce, call: functionName, status: "reverted", reason: shortError(e) });
      return false;
    }
    const rc = await this.view.client.waitForTransactionReceipt({ hash, timeout: 300_000 });
    const ok = rc.status === "success";
    this.record({ by: this.opts.name, pid: task.pid, nonce: task.nonce, call: functionName, tx: hash, gasUsed: rc.gasUsed, status: ok ? "sent" : "reverted" });
    return ok;
  }

  private async ensureAllowance() {
    if (this.approved) return;
    const token = await this.view.token();
    const allowance = (await this.view.client.readContract({ address: token, abi: erc20Abi, functionName: "allowance", args: [this.sender, this.view.contract] })) as bigint;
    if (allowance < maxUint256 / 2n) {
      const hash = await this.wallet.writeContract({ address: token, abi: erc20Abi, functionName: "approve", args: [this.view.contract, maxUint256], account: this.wallet.account as Account, chain: this.wallet.chain });
      await this.view.client.waitForTransactionReceipt({ hash, timeout: 300_000 });
    }
    this.approved = true;
  }

  private mandateFor(task: Task): [Hex, number] {
    if (this.sender.toLowerCase() === task.payer.toLowerCase()) return ["0x", 0];
    return [task.mandate ?? "0x", task.mandateKinds ?? 0];
  }

  /** A blind sender (noSimulation) sends each opening once regardless of
   * the state it reads. */
  private blindOnce(task: Task, kind: number): boolean {
    if (!this.opts.noSimulation) return false;
    const k = `${task.pid}:${task.nonce}:${kind}`;
    if (this.blindSent.has(k)) return false;
    this.blindSent.add(k);
    return true;
  }

  /** Whether this sender is on the payer's side for a kind. */
  private payerSide(task: Task, kind: number): boolean {
    if (this.sender.toLowerCase() === task.payer.toLowerCase()) return true;
    return !!task.mandate && ((task.mandateKinds ?? 0) & (1 << (kind - 1))) !== 0;
  }

  /** One pass over a purchase's duties at the current head. */
  async step(task: Task): Promise<void> {
    if (task.done) return;
    const v = this.view;
    const c = await v.constants();
    const head = await v.head();
    const sale = await v.sale(task.pid, task.nonce);
    if (sale.payer === "0x0000000000000000000000000000000000000000") {
      if ((await v.chainTime()) >= task.validBefore) {
        task.done = true;
        task.note = "not settled before validBefore";
      }
      return;
    }
    const eta = BigInt(sale.settledBlock);
    const epoch = sale.epoch;

    // binding completion: within eta + d_inc
    if (task.binding && sale.binding === "0x0000000000000000000000000000000000000000000000000000000000000000" && head <= eta + c.D_INC) {
      const b = task.binding;
      await this.send(task, "completeBinding", [task.pid, task.nonce, b.requestHash, b.claimsHash, b.salt]);
    }

    const aE = await v.anchorDeadline(epoch);
    if (!(await v.epochComplete(task.pid, epoch))) {
      // missed anchor: once the head is past A_e, the failure processing
      // call records it (a confirmed failure that freezes this sale), then
      // the frozen sale is claimed
      if (head > aE) {
        if (!(await v.missed(task.pid, epoch))) await this.send(task, "declareAnchorMissed", [task.pid, BigInt(epoch)]);
        task.note = "anchor missing";
        await this.claimIfFrozen(task, head);
        await this.finish(task, false);
      }
      return;
    }
    const al = await v.anchoredLeaf(task.pid, task.nonce, epoch);
    if (!al) {
      task.note = "nonce not in the anchor";
      return;
    }
    if (al.leaf.unanswered !== 0) {
      // the refund is owed from the anchor's completion; its transfer may
      // still wait for a pull call, which anyone may send
      if (!(await this.pullIfPending(task))) return;
      task.note = "unanswered mark, refunded at the anchor";
      task.done = true;
      return;
    }
    const profile = await v.profile(task.pid);
    const ctProfile = (profile.flags & F_CT) !== 0;
    const tSig = await v.signDeadline(eta, epoch);
    const windowEnd = aE + c.T_C;

    // swap proof
    if (task.signed && !al.beta && task.receipt && sale.status === ST_HELD) {
      const mine = rsHash(task.receipt, task.pid, profile.codeHash);
      if (mine !== al.hRS) {
        const r = task.receipt;
        const rs = { nonce: r.nonce, amount: r.amount, requestHash: r.requestHash, responseHash: r.responseHash, ctHash: r.ctHash, keyHash: r.keyHash, claimsHash: r.claimsHash, materialCommit: r.materialCommit };
        await this.send(task, "proveSwap", [al.opening, rs, r.signature]);
      }
    }

    // sample case without a pass by M_e + T_p: the failure processing call
    // (anyone; the payer's client sends it for its own sale), which freezes
    // this sale and the seller's later unpaid ones
    if ((sale.flags & SF_FAILED) === 0 && head > (await v.valueDeadline(epoch)) + c.T_P) {
      if ((await v.isSampled(task.pid, task.nonce)) && !(await v.passed(task.pid, task.nonce))) {
        await this.send(task, "declareSampleFailure", [task.pid, task.nonce]);
      }
    }

    // a frozen sale is claimed (refund to the payer) within T_claim
    if (await this.claimIfFrozen(task, head)) {
      await this.finish(task, false);
      return;
    }

    // this sender's slot: payer-side for the payer and its delegates,
    // third-party otherwise; the other slot neither blocks nor helps it
    const sideND = this.payerSide(task, K_NONDELIVERY) ? SIDE_PAYER : SIDE_THIRD;
    const sideK = this.payerSide(task, K_KEY) ? SIDE_PAYER : SIDE_THIRD;
    const nd = await v.dispute(task.pid, task.nonce, K_NONDELIVERY, sideND);
    const kd = await v.dispute(task.pid, task.nonce, K_KEY, sideK);

    // automatic non-delivery dispute: no sigma_B, after t_sig
    // (only the payer and delegates holding the non-delivery kind open it)
    if (!task.signed && !al.beta && this.payerSide(task, K_NONDELIVERY) && (nd.state === 0 || this.blindOnce(task, K_NONDELIVERY)) && head >= tSig && head <= windowEnd && sale.status === ST_HELD) {
      await this.ensureAllowance();
      await this.send(task, "openDispute", [al.opening, K_NONDELIVERY, ...this.mandateFor(task)]);
    }

    // a key public on chain (any dispute's answer) is checked like one
    // received off-chain
    if (ctProfile && task.signed && task.ct && task.keyStatus !== "ok") {
      const pub = await v.answers(task.pid, task.nonce);
      if (pub.ctkBlock !== 0n || pub.kBlock !== 0n) {
        task.keyStatus = decryptHash(pub.key, task.nonce, hexToBytes(task.ct)) === al.leaf.rs.responseHash ? "ok" : "bad";
      }
    }

    // key dispute: signed ciphertext sale, bad key, or no key by
    // A_e + T_c - d_inc
    if (ctProfile && task.signed && al.beta && this.payerSide(task, K_KEY) && kd.state === 0 && sale.status === ST_HELD && head <= windowEnd) {
      const late = head >= windowEnd - c.D_INC && task.keyStatus !== "ok";
      if (task.keyStatus === "bad" || late) {
        await this.ensureAllowance();
        const opened = await this.send(task, "openDispute", [al.opening, K_KEY, ...this.mandateFor(task)]);
        const now = await v.dispute(task.pid, task.nonce, K_KEY, sideK);
        if (opened && task.offchainKey && task.ct && now.state === D_OPEN) {
          await this.send(task, "challengeDecrypt", [task.pid, task.nonce, K_KEY, sideK, task.ct, task.offchainKey]);
        }
      }
    }

    // decryption challenges on answered slots (either side; anyone may)
    const ans = await v.answers(task.pid, task.nonce);
    for (const kind of [K_NONDELIVERY, K_KEY]) {
      for (const side of [SIDE_PAYER, SIDE_THIRD]) {
        const d = await v.dispute(task.pid, task.nonce, kind, side);
        if (d.state !== D_ANSWERED || d.bad || head > d.deadline) continue;
        const ct = task.ct ?? (await this.deliveredCt(task));
        if (!ct) continue;
        const mismatch = decryptHash(ans.key, task.nonce, hexToBytes(ct)) !== al.leaf.rs.responseHash;
        if (mismatch) await this.send(task, "challengeDecrypt", [task.pid, task.nonce, kind, side, ct, "0x" + "00".repeat(32)]);
      }
    }

    // closing (anyone, both slots)
    let openLeft = false;
    for (const kind of [K_NONDELIVERY, K_KEY]) {
      for (const side of [SIDE_PAYER, SIDE_THIRD]) {
        const d = await v.dispute(task.pid, task.nonce, kind, side);
        if ((d.state === D_OPEN || d.state === D_ANSWERED) && head > d.deadline) {
          await this.send(task, "closeDispute", [task.pid, task.nonce, kind, side]);
        }
        const d2 = await v.dispute(task.pid, task.nonce, kind, side);
        if (d2.state === D_OPEN || d2.state === D_ANSWERED) openLeft = true;
      }
    }

    await this.finish(task, openLeft);
  }

  /** Sends the pull of the sale's completion transfer (a refund owed to
   * the payer) if the anchor's completion fixed it and it is not yet made;
   * returns whether nothing is left to pull. */
  private async pullIfPending(task: Task): Promise<boolean> {
    if (!(await this.view.pullPending(task.pid, task.nonce))) return true;
    await this.send(task, "pullSale", [task.pid, task.nonce]);
    return !(await this.view.pullPending(task.pid, task.nonce));
  }

  /** Claims the sale if it is frozen and its claim period is running;
   * returns whether it is frozen. */
  private async claimIfFrozen(task: Task, head: bigint): Promise<boolean> {
    const end = await this.view.claimDeadline(task.pid, task.nonce);
    if (end === 0n) return false;
    if (head <= end) {
      if (await this.send(task, "claimFrozen", [task.pid, task.nonce])) task.claimed = true;
    }
    return true;
  }

  /** Marks the task done at a final state: refunded, paid (cursor, after a
   * dispute, or acceptance), or frozen past its claim period. */
  private async finish(task: Task, openLeft: boolean): Promise<void> {
    const after = await this.view.sale(task.pid, task.nonce);
    if (openLeft) return;
    if (after.status === ST_REFUNDED && !(await this.pullIfPending(task))) return;
    if (after.status === ST_REFUNDED) {
      task.done = true;
      task.note = task.claimed ? "frozen, claimed and refunded" : "refunded";
    } else if (after.status === 2 || after.status === 3) {
      task.done = true;
      task.note = "paid to seller";
    } else if ((await this.view.claimDeadline(task.pid, task.nonce)) !== 0n || after.status === ST_FROZEN) {
      const end = await this.view.claimDeadline(task.pid, task.nonce);
      if (end !== 0n && (await this.view.head()) > end) {
        task.done = true;
        task.note = "frozen, claim period over";
      }
    }
  }

  private async deliveredCt(task: Task): Promise<Hex | undefined> {
    const logs = await this.view.client.getContractEvents({
      address: this.view.contract,
      abi: this.view.abi,
      eventName: "Delivered",
      args: { pid: task.pid, nonce: task.nonce },
      fromBlock: (await this.view.constants()).genesis,
      toBlock: "latest",
    });
    const a = (logs[0] as unknown as { args?: { ct: Hex } } | undefined)?.args;
    return a?.ct;
  }
}

export function shortError(e: unknown): string {
  const m = (e as { shortMessage?: string; message?: string }).shortMessage ?? (e as Error).message ?? String(e);
  const s = m.split("\n");
  const reason = s.find((l) => /reverted|Error|error:/.test(l)) ?? s[0];
  return reason.slice(0, 160);
}

export { bytesToHex };
