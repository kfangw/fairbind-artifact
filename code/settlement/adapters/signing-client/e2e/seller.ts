// Reference seller and facilitator for the end-to-end runs. The seller
// serves x402 v2 payment requirements with the sampled-settlement extension,
// has the facilitator settle the EIP-3009 authorization through the
// settlement contract, returns the response with a signed receipt, anchors
// its epochs, answers disputes, proves sampled sales and releases. Its
// behaviour per route is set by a mode, including the misbehaviours the runs
// exercise.
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import {
  decodePaymentSignatureHeader,
  encodePaymentRequiredHeader,
  encodePaymentResponseHeader,
} from "@x402/core/http";
import type { PaymentPayload, PaymentRequired } from "@x402/core/types";
import {
  bytesToHex,
  concatHex,
  encodeAbiParameters,
  encodePacked,
  erc20Abi,
  hexToBytes,
  keccak256,
  toHex,
  type Address,
  type Hex,
  type LocalAccount,
  type PublicClient,
  type WalletClient,
} from "viem";
import { ChainView, type Leaf } from "../src/chain.ts";
import {
  claimsHash,
  domain,
  encrypt,
  keyHash,
  levels,
  leaf0Of,
  leafOf,
  plaintext,
  receiptMessage,
  RECEIPT_TYPES,
  requestHash,
  responseHash,
  rsHash,
  UNIT_TYPES,
  ZERO32,
  type Profile,
  type Receipt,
} from "../src/hashing.ts";
import { b64, EXTENSION_KEY, profileToWire, RECEIPT_HEADER, receiptToWire, type BindingExtension, type OfferExtension } from "../src/wire.ts";

export const USDC: Address = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
export const FEED = 1;

export type Mode =
  | "honest" // plaintext profile, response and receipt
  | "honest-ct" // ciphertext profile, key on the buyer signature
  | "withhold" // takes the payment, gives nothing, does not answer disputes
  | "withhold-badct" // takes the payment, gives nothing, answers with a ct that does not decrypt to h_r
  | "withhold-key-badct" // ciphertext profile: gives ct and receipt, no key; reveals a key under which ct does not decrypt to h_r
  | "wrong-payto" // 402 names one profile and the receiving address of another
  | "wrong-receipt-profile" // receipt signed with another profile id in its profile field
  | "fraud"; // plaintext profile: delivers a false price under a receipt that commits to it; no material verifies

export interface Route {
  path: string;
  pid: Hex;
  profile: Profile;
  mode: Mode;
  /** for wrong-payto and wrong-receipt-profile: the other profile */
  otherPid?: Hex;
}

interface SaleRec {
  route: Route;
  pid: Hex;
  nonce: Hex;
  rs: Receipt;
  psi: Hex;
  r: Uint8Array;
  k: Hex;
  ct: Uint8Array;
  material: Hex;
  sigB?: Hex;
}

export interface SellerOptions {
  publicClient: PublicClient;
  seller: WalletClient; // account, receipt key and unit key
  facilitator: WalletClient;
  feedKey: LocalAccount;
  contract: Address;
  port: number;
}

export class RefSeller {
  readonly view: ChainView;
  readonly routes = new Map<string, Route>();
  readonly sales = new Map<string, SaleRec>();
  readonly log: string[] = [];
  private server?: Server;
  readonly opts: SellerOptions;

  constructor(opts: SellerOptions) {
    this.opts = opts;
    this.view = new ChainView(opts.publicClient, opts.contract);
  }

  get base(): string {
    return `http://127.0.0.1:${this.opts.port}`;
  }

  addRoute(r: Route) {
    this.routes.set(r.path, r);
  }

  start(): Promise<void> {
    this.server = createServer((req, res) => {
      this.handle(req, res).catch((e) => {
        this.log.push(`handler error: ${(e as Error).message}`);
        res.statusCode = 500;
        res.end();
      });
    });
    return new Promise((ok) => this.server!.listen(this.opts.port, "127.0.0.1", () => ok()));
  }

  stop(): Promise<void> {
    return new Promise((ok) => this.server?.close(() => ok()) ?? ok());
  }

  private async send(w: WalletClient, functionName: string, args: unknown[]): Promise<{ ok: boolean; gas: bigint; hash: Hex }> {
    const hash = await w.writeContract({ address: this.opts.contract, abi: this.view.abi, functionName, args, account: w.account!, chain: w.chain, gas: 8_000_000n });
    const rc = await this.opts.publicClient.waitForTransactionReceipt({ hash, timeout: 300_000 });
    return { ok: rc.status === "success", gas: rc.gasUsed, hash };
  }

  private async handle(req: IncomingMessage, res: ServerResponse) {
    const u = new URL(req.url ?? "/", this.base);
    if (req.method === "POST" && u.pathname === "/ack") return this.ack(req, res);
    const route = this.routes.get(u.pathname);
    if (!route) {
      res.statusCode = 404;
      return res.end();
    }
    const pay = req.headers["payment-signature"] as string | undefined;
    if (!pay) return this.offer(route, u, res);
    return this.serve(route, req, u, pay, res);
  }

  private async offer(route: Route, u: URL, res: ServerResponse) {
    const chainId = await this.opts.publicClient.getChainId();
    const payToPid = route.mode === "wrong-payto" ? route.otherPid! : route.pid;
    const ext: OfferExtension = { contract: this.opts.contract, profileId: route.pid, profile: profileToWire(route.profile), ackUrl: `${this.base}/ack` };
    const pr: PaymentRequired = {
      x402Version: 2,
      resource: { url: u.toString(), description: "price feed", mimeType: "application/octet-stream" },
      accepts: [
        {
          scheme: "exact",
          network: `eip155:${chainId}`,
          asset: USDC,
          amount: "10000",
          payTo: await this.view.vaultOf(payToPid),
          maxTimeoutSeconds: 600,
          extra: { name: "USD Coin", version: "2" },
        },
      ],
      extensions: { [EXTENSION_KEY]: ext },
    };
    res.statusCode = 402;
    res.setHeader("PAYMENT-REQUIRED", encodePaymentRequiredHeader(pr));
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify({}));
  }

  /** Facilitator: settle the authorization through the contract. */
  private async settle(payload: PaymentPayload): Promise<{ ok: boolean; hash: Hex; auth: Record<string, string> }> {
    const p = payload.payload as { authorization: Record<string, string>; signature: Hex };
    const a = p.authorization;
    const b = (payload.extensions?.[EXTENSION_KEY] as Partial<BindingExtension> | undefined)?.binding;
    const auth = { from: a.from, to: a.to, value: BigInt(a.value), validAfter: BigInt(a.validAfter), validBefore: BigInt(a.validBefore), nonce: a.nonce };
    const r = await this.send(this.opts.facilitator, "settle", [auth, p.signature, b?.requestHash ?? ZERO32, b?.claimsHash ?? ZERO32, b?.salt ?? ZERO32]);
    return { ok: r.ok, hash: r.hash, auth: a };
  }

  private async lazerMaterial(psi: Hex, validAfter: bigint, price: bigint): Promise<{ r: Uint8Array; material: Hex }> {
    // the fixed-rate channel (3, 200 ms) update at validAfter, the grid time
    // the tier 1a verifier requires
    const ts = validAfter * 1_000_000n;
    const payload = encodePacked(
      ["uint32", "uint64", "uint8", "uint8", "uint32", "uint8", "uint8", "int64"],
      [2479346549, ts, 3, 1, FEED, 1, 0, price],
    );
    const sig = await this.opts.feedKey.sign!({ hash: keccak256(payload) });
    const rr = sig.slice(0, 66) as Hex;
    const ss = ("0x" + sig.slice(66, 130)) as Hex;
    const v = parseInt(sig.slice(130, 132), 16) - 27;
    const update = encodePacked(["uint32", "bytes32", "bytes32", "uint8", "uint16", "bytes"], [706910618, rr, ss, v, (payload.length - 2) / 2, payload]);
    const r = hexToBytes(encodeAbiParameters([{ type: "uint32" }, { type: "int64" }, { type: "uint64" }], [FEED, price, ts]));
    return { r, material: concatHex([psi, update]) };
  }

  private async serve(route: Route, req: IncomingMessage, u: URL, pay: string, res: ServerResponse) {
    const payload = decodePaymentSignatureHeader(pay) as PaymentPayload;
    const s = await this.settle(payload);
    if (!s.ok) {
      res.statusCode = 402;
      return res.end();
    }
    const chainId = await this.opts.publicClient.getChainId();
    const b = (payload.extensions?.[EXTENSION_KEY] as Partial<BindingExtension> | undefined)?.binding;
    const nonce = s.auth.nonce as Hex;
    const pathAndQuery = u.pathname + u.search;
    const salt = b?.salt ?? ZERO32;
    const rq = requestHash(req.method ?? "GET", pathAndQuery, new Uint8Array(), salt);
    const cl = claimsHash(route.profile.inputRule, req.method ?? "GET", pathAndQuery);
    const psi = toHex(crypto.getRandomValues(new Uint8Array(32)));
    const { material } = await this.lazerMaterial(psi, BigInt(s.auth.validAfter), 189_000_000_000n);
    // the fraud mode answers with another price than the feed signed
    const sold = route.mode === "fraud" ? 201_000_000_000n : 189_000_000_000n;
    const { r } = await this.lazerMaterial(psi, BigInt(s.auth.validAfter), sold);
    const k = toHex(crypto.getRandomValues(new Uint8Array(32)));
    const pt = plaintext(psi, r);
    // the misbehaving modes commit h_r to the real response and h_ct to a
    // ciphertext of something else
    const bad = route.mode === "withhold-badct" || route.mode === "withhold-key-badct";
    const ctPlain = bad ? new Uint8Array(pt.length).fill(0x41) : pt;
    const ct = encrypt(k, nonce, ctPlain);
    const rs: Receipt = {
      nonce,
      amount: BigInt(s.auth.value),
      requestHash: rq,
      responseHash: responseHash(psi, r),
      ctHash: keccak256(ct),
      keyHash: keyHash(k),
      claimsHash: cl,
      materialCommit: keccak256(material),
    };
    const rec: SaleRec = { route, pid: route.pid, nonce, rs, psi, r, k, ct, material };
    this.sales.set(nonce.toLowerCase(), rec);
    res.setHeader("PAYMENT-RESPONSE", encodePaymentResponseHeader({ success: true, transaction: s.hash, network: payload.accepted.network, payer: s.auth.from } as never));
    if (route.mode === "withhold" || route.mode === "withhold-badct") {
      res.statusCode = 503; // payment taken, nothing delivered
      return res.end();
    }
    const signPid = route.mode === "wrong-receipt-profile" ? route.otherPid! : route.pid;
    const signature = await this.opts.seller.signTypedData({
      account: this.opts.seller.account!,
      domain: domain(chainId, this.opts.contract),
      types: RECEIPT_TYPES,
      primaryType: "SellerReceipt",
      message: receiptMessage(rs, signPid, route.profile.codeHash),
    });
    const env = { receipt: receiptToWire({ ...rs, profileId: signPid, codeHash: route.profile.codeHash, signature }), psi, material };
    res.setHeader(RECEIPT_HEADER, b64(env));
    res.statusCode = 200;
    const ctProfile = route.mode === "honest-ct" || route.mode === "withhold-key-badct";
    res.end(Buffer.from(ctProfile ? ct : r));
  }

  private async ack(req: IncomingMessage, res: ServerResponse) {
    const chunks: Buffer[] = [];
    for await (const c of req) chunks.push(c as Buffer);
    const j = JSON.parse(Buffer.concat(chunks).toString("utf8")) as { nonce: Hex; signature: Hex };
    const rec = this.sales.get(j.nonce.toLowerCase());
    if (!rec) {
      res.statusCode = 404;
      return res.end();
    }
    rec.sigB = j.signature;
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify(rec.route.mode === "honest-ct" ? { key: rec.k } : {}));
  }

  // ------------------------------------------------------------ chain duties

  /** Anchor every settled sale of (pid, epoch) in one unit. */
  async anchor(pid: Hex, epoch: number): Promise<{ ok: boolean; gas: bigint; leaves: number }> {
    const chainId = await this.opts.publicClient.getChainId();
    const nonces = (await this.view.read<Hex[]>("epochNonces", [pid, BigInt(epoch)])).slice();
    nonces.sort((a, b) => (BigInt(a) < BigInt(b) ? -1 : 1));
    const codeHash = (await this.view.profile(pid)).codeHash;
    const leaves: Leaf[] = nonces.map((n) => {
      const rec = this.sales.get(n.toLowerCase());
      if (!rec) return { rs: { ...emptyRs(), nonce: n }, unanswered: 1, accept: false, sigB: "0x" };
      return { rs: rec.rs, unanswered: 0, accept: false, sigB: rec.sigB ?? "0x" };
    });
    const lv: Hex[] = [];
    const lv0: Hex[] = [];
    for (const l of leaves) {
      const hRS = l.unanswered === 0 ? rsHash(l.rs, pid, codeHash) : ZERO32;
      const l0 = leaf0Of(l.rs.nonce, hRS, l.unanswered);
      const beta = l.unanswered === 0 && l.sigB !== "0x"; // the seller relays only valid signatures it received
      lv0.push(l0);
      lv.push(leafOf(l0, beta ? keccak256(l.sigB) : ZERO32, beta, false));
    }
    const root = levels(lv).at(-1)![0];
    const root0 = levels(lv0).at(-1)![0];
    const snapshot: Address[] = [];
    const snapshotHash = keccak256(encodeAbiParameters([{ type: "address[]" }], [snapshot]));
    const unit = { pid, epoch, count: leaves.length, unitNo: 1, first: leaves[0].rs.nonce, last: leaves.at(-1)!.rs.nonce, root, root0, snapshot, leaves, sellerSig: "0x" as Hex };
    unit.sellerSig = await this.opts.seller.signTypedData({
      account: this.opts.seller.account!,
      domain: domain(chainId, this.opts.contract),
      types: UNIT_TYPES,
      primaryType: "AnchorUnit",
      message: { profileId: pid, epoch, count: unit.count, unitNo: 1, firstNonce: unit.first, lastNonce: unit.last, root, root0, snapshotHash },
    });
    const r = await this.send(this.opts.seller, "anchorUnit", [unit]);
    const complete = await this.view.epochComplete(pid, epoch);
    return { ok: r.ok && complete, gas: r.gas, leaves: leaves.length };
  }

  /** Answer open disputes on this seller's sales according to the mode. */
  async answerDisputes(): Promise<void> {
    for (const rec of this.sales.values()) {
      for (const kind of [1, 2]) {
        const d0 = await this.view.dispute(rec.pid, rec.nonce, kind, 0);
        const d1 = await this.view.dispute(rec.pid, rec.nonce, kind, 1);
        if (d0.state !== 1 && d1.state !== 1) continue;
        const a = await this.view.answers(rec.pid, rec.nonce);
        if (kind === 1 ? a.ctkBlock !== 0n || a.ackBlock !== 0n : a.ctkBlock !== 0n || a.kBlock !== 0n) continue; // already on chain
        const m = rec.route.mode;
        if (kind === 1) {
          if (m === "withhold" || m === "wrong-receipt-profile") continue; // no answer
          if (rec.sigB && m === "honest") {
            const r = await this.send(this.opts.seller, "answerWithAck", [rec.pid, rec.nonce, false, rec.sigB]);
            this.log.push(`answerWithAck ${r.ok} gas ${r.gas}`);
          } else {
            const r = await this.send(this.opts.seller, "answerDeliver", [rec.pid, rec.nonce, bytesToHex(rec.ct), rec.k]);
            this.log.push(`answerDeliver ${rec.route.path} ${r.ok} gas ${r.gas}`);
          }
        } else {
          const r = await this.send(this.opts.seller, "answerKey", [rec.pid, rec.nonce, rec.k]);
          this.log.push(`answerKey ${rec.route.path} ${r.ok} gas ${r.gas}`);
        }
      }
    }
  }

  /** Prove every sampled sale of (pid, epoch) that has no pass yet,
   * whatever its status (a refunded sale stays in the sample). A proof that
   * does not verify, or comes after M_e + T_p, is sent and reverts. */
  async prove(pid: Hex, epoch: number): Promise<{ proven: number; reverted: number; gas: bigint[] }> {
    const out = { proven: 0, reverted: 0, gas: [] as bigint[] };
    for (const rec of this.sales.values()) {
      if (rec.pid !== pid) continue;
      const s = await this.view.sale(pid, rec.nonce);
      if (s.epoch !== epoch) continue;
      if (!(await this.view.isSampled(pid, rec.nonce)) || (await this.view.passed(pid, rec.nonce))) continue;
      const al = await this.view.anchoredLeaf(pid, rec.nonce, epoch);
      if (!al) continue;
      const r = await this.send(this.opts.seller, "prove", [al.opening, rec.material]);
      if (r.ok) out.proven++;
      else out.reverted++;
      out.gas.push(r.gas);
      this.log.push(`prove ${rec.route.path} ${r.ok} gas ${r.gas}`);
    }
    return out;
  }

  /** Cursor steps of this seller's account until it has passed `epoch`
   * (empty epochs pass at once); sent by `by` (anyone). */
  async release(epoch: number, by?: WalletClient): Promise<{ ok: boolean; steps: { epoch: number; ok: boolean; gas: bigint; paid?: bigint }[] }> {
    const acct = this.opts.seller.account!.address;
    const steps: { epoch: number; ok: boolean; gas: bigint }[] = [];
    for (;;) {
      const cur = Number(await this.view.read<bigint>("accountCursor", [acct]));
      if (cur > epoch) return { ok: steps.every((x) => x.ok), steps };
      try {
        const r = await this.send(by ?? this.opts.seller, "release", [acct]);
        steps.push({ epoch: cur, ok: r.ok, gas: r.gas });
        this.log.push(`release epoch ${cur} ${r.ok} gas ${r.gas}`);
        if (!r.ok) return { ok: false, steps };
      } catch (e) {
        this.log.push(`release ${acct}: ${(e as Error).message.split("\n")[0]}`);
        return { ok: false, steps };
      }
    }
  }

  /** The seller's bond: approve and deposit. */
  async depositBond(amount: bigint): Promise<{ ok: boolean; gas: bigint }> {
    await this.approveToken();
    const r = await this.send(this.opts.seller, "depositBond", [this.opts.seller.account!.address, amount]);
    this.log.push(`depositBond ${amount} ${r.ok} gas ${r.gas}`);
    return { ok: r.ok, gas: r.gas };
  }

  /** Re-entry of the suspended account, topping the bond up by `topUp`. */
  async reenter(topUp: bigint): Promise<{ ok: boolean; gas: bigint }> {
    await this.approveToken();
    const r = await this.send(this.opts.seller, "reenter", [topUp]);
    this.log.push(`reenter ${topUp} ${r.ok} gas ${r.gas}`);
    return { ok: r.ok, gas: r.gas };
  }

  private async approveToken() {
    const hash = await this.opts.seller.writeContract({ address: USDC, abi: erc20Abi, functionName: "approve", args: [this.opts.contract, 2n ** 255n], account: this.opts.seller.account!, chain: this.opts.seller.chain });
    await this.opts.publicClient.waitForTransactionReceipt({ hash, timeout: 300_000 });
  }

  /** A second seller signature for the stored unit 1 of (pid, epoch) with
   * another root0: evidence of a double-signed anchor (for the run's
   * misbehaving seller). */
  async doubleSign(pid: Hex, epoch: number): Promise<{ header: Record<string, unknown>; sig: Hex }> {
    const chainId = await this.opts.publicClient.getChainId();
    const u = (await this.view.units(pid, epoch))[0];
    const snapshotHash = keccak256(encodeAbiParameters([{ type: "address[]" }], [u.snapshot]));
    const header = { pid, epoch, count: u.count, unitNo: u.unitNo, first: u.first, last: u.last, root: u.root, root0: keccak256(toHex("another root0")), snapshotHash };
    const sig = await this.opts.seller.signTypedData({
      account: this.opts.seller.account!,
      domain: domain(chainId, this.opts.contract),
      types: UNIT_TYPES,
      primaryType: "AnchorUnit",
      message: { profileId: pid, epoch, count: u.count, unitNo: u.unitNo, firstNonce: u.first, lastNonce: u.last, root: u.root, root0: header.root0, snapshotHash },
    });
    return { header, sig };
  }
}

function emptyRs(): Receipt {
  return { nonce: ZERO32, amount: 0n, requestHash: ZERO32, responseHash: ZERO32, ctHash: ZERO32, keyHash: ZERO32, claimsHash: ZERO32, materialCommit: ZERO32 };
}
