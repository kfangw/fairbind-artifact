import { test } from "node:test";
import assert from "node:assert/strict";
import { keccak256, toHex, type Hex, type WalletClient } from "viem";
import { Duties, ST_REFUNDED, type Task } from "../src/duties.ts";
import type { ChainView } from "../src/chain.ts";

const h = (s: string): Hex => keccak256(toHex(s));

/** A chain view with one marked (unanswered) sale of a complete anchor whose
 * refund is owed from the completion and moved by a pull call. */
function fakeView(state: { pending: boolean }) {
  return {
    constants: async () => ({ D_INC: 30n, T_C: 600n }),
    head: async () => 1_000n,
    sale: async () => ({ payer: "0x0000000000000000000000000000000000000b0b", settledBlock: 10, epoch: 1, binding: h("b"), status: ST_REFUNDED }),
    anchorDeadline: async () => 900n,
    epochComplete: async () => true,
    anchoredLeaf: async () => ({ leaf: { unanswered: 1 }, beta: false }),
    pullPending: async () => state.pending,
  } as unknown as ChainView;
}

class Recorder extends Duties {
  sent: string[] = [];
  result = true;
  onSend?: () => void;
  override async send(_task: Task, functionName: string): Promise<boolean> {
    this.sent.push(functionName);
    if (this.result) this.onSend?.();
    return this.result;
  }
}

const task = (): Task => ({ pid: h("pid"), nonce: h("nonce"), payer: "0x0000000000000000000000000000000000000b0b", validBefore: 0n, signed: false });

test("a marked sale's owed refund is pulled, then the purchase is done", async () => {
  const state = { pending: true };
  const d = new Recorder(fakeView(state), {} as WalletClient, { name: "buyer", dObs: 2n });
  d.onSend = () => (state.pending = false);
  const t = task();
  await d.step(t);
  assert.deepEqual(d.sent, ["pullSale"]);
  assert.equal(t.done, true);
});

test("an owed refund still unpulled keeps the purchase open; nothing to pull sends nothing", async () => {
  const state = { pending: true };
  const d = new Recorder(fakeView(state), {} as WalletClient, { name: "buyer", dObs: 2n });
  d.result = false; // the pull did not go through
  const t = task();
  await d.step(t);
  assert.deepEqual(d.sent, ["pullSale"]);
  assert.notEqual(t.done, true);
  state.pending = false; // someone else pulled it (a chunk call)
  d.sent = [];
  await d.step(t);
  assert.deepEqual(d.sent, []);
  assert.equal(t.done, true);
});
