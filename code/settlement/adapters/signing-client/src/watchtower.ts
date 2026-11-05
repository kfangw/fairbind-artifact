// Watchtower: holds no payer key. It watches the chain for the purchases
// clients hand it (with the payer's dispute mandate sigma_W and, for signed
// ciphertext sales, the checked ciphertext) and sends the duties anyone may
// send: dispute openings, decryption challenges and closings. It pays the
// deposit and gas from its own account. Several watchtowers may watch the
// same purchase: each call is simulated against the current state first, and
// the contract reverts a second opening of the same dispute, so duplicates
// cost at most a reverted transaction and never a second deposit.
import { keccak256, type Account, type Address, type Hex, type PublicClient, type WalletClient } from "viem";
import { ChainView } from "./chain.ts";
import { Duties, type Action, type Task } from "./duties.ts";
import type { TowerLink } from "./client.ts";
import { domain, MANDATE_KINDS, TOWER_ACK_TYPES } from "./hashing.ts";

export interface WatchtowerOptions {
  name: string;
  publicClient: PublicClient;
  /** The watchtower's own gas and deposit account (not a payer key). */
  wallet: WalletClient;
  contract: Address;
  dObs: bigint;
  noSimulation?: boolean;
  onAction?: (a: Action) => void;
}

export class Watchtower implements TowerLink {
  readonly tasks = new Map<string, Task>();
  readonly duties: Duties;
  readonly view: ChainView;

  readonly opts: WatchtowerOptions;

  constructor(opts: WatchtowerOptions) {
    this.opts = opts;
    this.view = new ChainView(opts.publicClient, opts.contract);
    this.duties = new Duties(this.view, opts.wallet, { name: opts.name, dObs: opts.dObs, noSimulation: opts.noSimulation, onAction: opts.onAction });
  }

  get address(): Address {
    return this.opts.wallet.account!.address;
  }

  /** A client hands over or updates a purchase (with the binding triple,
   * so the watchtower can also send the binding completion). */
  async submit(task: Task): Promise<Hex | undefined> {
    const key = `${task.pid}:${task.nonce}`;
    const t: Task = { ...task };
    const old = this.tasks.get(key);
    if (old?.done) return undefined;
    // a nonce on which this watchtower already sent a non-delivery dispute
    // gets no acknowledgement; once it acknowledged sigma_B it never sends
    // one (the duty engine does not open non-delivery disputes on signed
    // sales). The sigma_B is kept either way.
    const sentND = !old?.signed && this.duties.actions.some((a) => a.pid === task.pid && a.nonce === task.nonce && a.call === "openDispute" && a.status === "sent");
    this.tasks.set(key, t);
    if (!task.signed || !task.sigB || sentND) return undefined;
    // only a watchtower holding the non-delivery kind acknowledges
    if (((task.mandateKinds ?? 0) & MANDATE_KINDS.nonDelivery) === 0) return undefined;
    const contract = this.opts.contract;
    const chainId = await this.opts.publicClient.getChainId();
    return this.opts.wallet.signTypedData({
      account: this.opts.wallet.account as Account,
      domain: domain(chainId, contract),
      types: TOWER_ACK_TYPES,
      primaryType: "TowerReceipt",
      message: { profileId: task.pid, nonce: task.nonce, sigBHash: keccak256(task.sigB) },
    });
  }

  async tick(): Promise<void> {
    for (const t of this.tasks.values()) {
      if (!t.done) await this.duties.step(t);
    }
  }
}
