// Signing client: wraps the official x402 v2 client (x402Client and
// x402HTTPClient from @x402/core, the EIP-3009 typed data of @x402/evm) with
// (a) the profile and disclosure check before paying, (b) the bound nonce,
// (c) the receipt check before the buyer signature, (d) the duty schedule
// (binding completion, swap proof, automatic disputes, decryption
// challenges, closing) and (e) the reserves kept per open purchase.
import { x402Client, x402HTTPClient } from "@x402/core/client";
import type { PaymentPayload, PaymentRequired, PaymentRequirements } from "@x402/core/types";
import { authorizationTypes, findDefaultAsset } from "@x402/evm";
import {
  bytesToHex,
  erc20Abi,
  getAddress,
  hexToBytes,
  keccak256,
  recoverTypedDataAddress,
  toHex,
  type Account,
  type Address,
  type Hex,
  type PublicClient,
  type WalletClient,
} from "viem";
import { ChainView } from "./chain.ts";
import { Duties, type Action, type Task } from "./duties.ts";
import {
  ACK_TYPES,
  ackMessage,
  boundNonce,
  claimsHash as claimsHashOf,
  decrypt,
  domain,
  F_CT,
  keyHash,
  MANDATE_KINDS,
  MANDATE_TYPES,
  decryptHash,
  profileId,
  RECEIPT_TYPES,
  receiptMessage,
  requestHash as requestHashOf,
  responseHash,
  TAGS,
  TOWER_ACK_TYPES,
  type Profile,
  type SignedReceipt,
} from "./hashing.ts";
import { EXTENSION_KEY, profileFromWire, RECEIPT_HEADER, receiptFromWire, unb64, type OfferExtension, type ReceiptEnvelope } from "./wire.ts";

/** Gas budgets per open purchase. The dispute pair is
 * the rule's figure (122,222 + 186,500); the swap and binding figures are
 * upper bounds of this reference contract's calls. */
export const GAS = { open: 122_222n, decrypt: 186_500n, swap: 200_000n, bind: 60_000n };

export interface ClientOptions {
  wallet: WalletClient;
  publicClient: PublicClient;
  /** Settlement contracts the client agrees to pay into. */
  trustedContracts: Address[];
  /** Highest dispute deposit the client accepts (C_nd bound it agrees to). */
  maxDeposit: bigint;
  allowedTiers: number[];
  /** Observation and inclusion delays the client budgets, in blocks. */
  dObs: bigint;
  dTx: bigint;
  /** Price caps for the swap proof and binding completion (wei per gas). */
  pSwap: bigint;
  pBind: bigint;
  /** Share rho of T_x x block gas target the client's own challenges may use. */
  rho: number;
  blockGasTarget: bigint;
  watchtowers?: TowerLink[];
  /** Accept profiles with a response deadline r_dl (an extension outside
   * the claim scope); off by default. */
  responseDeadlineExtension?: boolean;
  fetchImpl?: typeof fetch;
  onAction?: (a: Action) => void;
}

/** In-process link to a watchtower (a real deployment would use RPC). */
export interface TowerLink {
  /** The watchtower's sending address, named as delegate in sigma_W. */
  readonly address: Address;
  /** Takes the purchase; for a signed one returns the watchtower's signed
   * receipt acknowledgement of sigma_B (if it holds the non-delivery kind). */
  submit(task: Task): Promise<Hex | undefined>;
}

/** Kinds the client delegates to a watchtower: non-delivery, key and
 * decryption disputes (not the response dispute). */
export const TOWER_KINDS = MANDATE_KINDS.nonDelivery | MANDATE_KINDS.key | MANDATE_KINDS.decryption;

export type PurchaseState = "refused" | "unpaid" | "paid" | "signed" | "unsigned" | "done";

export interface Purchase {
  url: string;
  state: PurchaseState;
  reason?: string;
  contract?: Address;
  pid?: Hex;
  nonce?: Hex;
  amount?: bigint;
  task?: Task;
  response?: Uint8Array;
  receipt?: SignedReceipt;
  checks: string[];
  reserve?: { eth: bigint; token: bigint; settledOut: boolean };
  mandates?: Map<TowerLink, Hex>;
  ackUrl?: string;
  /** sigma_B made but held back until every acknowledgement arrives. */
  ackPending?: boolean;
}

export class PaymentRefused extends Error {}

export class SigningClient {
  readonly view: Map<Address, ChainView> = new Map();
  readonly duties: Map<Address, Duties> = new Map();
  readonly purchases: Purchase[] = [];
  private pending?: { nonce: Hex; validAfter: bigint; validBefore: bigint; binding: { requestHash: Hex; claimsHash: Hex; salt: Hex } };
  private queue: Promise<unknown> = Promise.resolve();
  private readonly http: x402HTTPClient;

  readonly opts: ClientOptions;

  constructor(opts: ClientOptions) {
    this.opts = opts;
    const core = new x402Client();
    core.register("eip155:*", {
      scheme: "exact",
      findDefaultAsset, // keeps the official spend controls (default USD assets)
      createPaymentPayload: async (x402Version: number, req: PaymentRequirements) => this.boundPayload(x402Version, req),
    });
    this.http = new x402HTTPClient(core);
  }

  get account(): Account {
    return this.opts.wallet.account as Account;
  }

  private viewFor(contract: Address): ChainView {
    let v = this.view.get(contract);
    if (!v) {
      v = new ChainView(this.opts.publicClient, contract);
      this.view.set(contract, v);
      this.duties.set(contract, new Duties(v, this.opts.wallet, { name: "client", dObs: this.opts.dObs, onAction: this.opts.onAction }));
    }
    return v;
  }

  /** The exact-scheme EIP-3009 payload with the bound nonce instead of a
   * random one; the binding triple travels in the payload's extension. */
  private async boundPayload(x402Version: number, req: PaymentRequirements) {
    const p = this.pending;
    if (!p) throw new PaymentRefused("no pending bound payment");
    const chainId = Number(req.network.split(":")[1]);
    const authorization = {
      from: this.account.address,
      to: getAddress(req.payTo),
      value: req.amount,
      validAfter: p.validAfter.toString(),
      validBefore: p.validBefore.toString(),
      nonce: p.nonce,
    };
    const extra = req.extra as { name?: string; version?: string };
    if (!extra?.name || !extra?.version) throw new PaymentRefused("token domain missing");
    const signature = await this.opts.wallet.signTypedData({
      account: this.account,
      domain: { name: extra.name, version: extra.version, chainId, verifyingContract: getAddress(req.asset) },
      types: authorizationTypes,
      primaryType: "TransferWithAuthorization",
      message: {
        from: authorization.from,
        to: authorization.to,
        value: BigInt(authorization.value),
        validAfter: p.validAfter,
        validBefore: p.validBefore,
        nonce: p.nonce,
      },
    });
    return { x402Version, payload: { authorization, signature }, extensions: { [EXTENSION_KEY]: { binding: p.binding } } };
  }

  /** (a) Profile and disclosure check; throws
   * PaymentRefused with the failed checks. */
  async checkOffer(pr: PaymentRequired): Promise<{ req: PaymentRequirements; ext: OfferExtension; profile: Profile; view: ChainView }> {
    const ext = pr.extensions?.[EXTENSION_KEY] as OfferExtension | undefined;
    if (!ext) throw new PaymentRefused("no sampled-settlement extension: not a covered sale");
    const fail: string[] = [];
    const contract = getAddress(ext.contract);
    if (!this.opts.trustedContracts.map((a) => a.toLowerCase()).includes(contract.toLowerCase())) fail.push("settlement contract not trusted");
    const view = this.viewFor(contract);
    const c = await view.constants();
    const disclosed = profileFromWire(ext.profile as Record<string, string | number>);
    if (profileId(disclosed) !== ext.profileId) fail.push("disclosed profile fields do not hash to the profile id");
    const onchain = await view.profile(ext.profileId);
    if (onchain.account === "0x0000000000000000000000000000000000000000") fail.push("profile not registered");
    else if (profileId(onchain) !== ext.profileId) fail.push("registered profile does not hash to the id");
    else if (JSON.stringify(profileFromWireish(onchain)) !== JSON.stringify(profileFromWireish(disclosed))) fail.push("disclosed profile differs from the registered one");
    const req = pr.accepts.find((a) => a.scheme === "exact");
    if (!req) fail.push("no exact-scheme requirement");
    const chainId = await this.opts.publicClient.getChainId();
    if (req) {
      if (req.network !== `eip155:${chainId}`) fail.push("network differs from the chain observed");
      const vault = await view.vaultOf(ext.profileId);
      if (getAddress(req.payTo) !== getAddress(vault)) fail.push("payTo is not the profile's receiving address");
      if (getAddress(req.asset) !== getAddress(await view.token())) fail.push("asset is not the contract's token");
      if (BigInt(req.amount) > onchain.cap) fail.push("amount above the profile cap");
      if (BigInt(req.amount) < onchain.minAmount) fail.push("amount below the profile's smallest sale amount");
    }
    if ((await view.codeHashAt(onchain.verifier)) !== onchain.codeHash) fail.push("verification contract code hash differs");
    if (!this.opts.allowedTiers.includes(onchain.tier)) fail.push("trust tier not accepted");
    if (onchain.deposit > this.opts.maxDeposit || onchain.deposit > c.C_ND) fail.push("dispute deposit above the accepted bound");
    if (onchain.responseDeadline !== 0 && !this.opts.responseDeadlineExtension) fail.push("response-deadline profile (an extension) not enabled");
    if (c.T_X < c.D_INC) fail.push("T_x < d_inc");
    if (c.D_INC < this.opts.dObs + this.opts.dTx) fail.push("d_inc < d_obs + d_tx");
    if (fail.length) throw new PaymentRefused(fail.join("; "));
    return { req: req!, ext, profile: onchain, view };
  }

  /** p_max used for the dispute reserve: the disclosed cap, at least p_floor. */
  static effectivePriceCap(profile: Profile, pFloor: bigint): bigint {
    return profile.maxFeePerGas > pFloor ? profile.maxFeePerGas : pFloor;
  }

  /** (e) Reserve for one new purchase, against every open purchase. */
  private async reserve(profile: Profile, amount: bigint, view: ChainView): Promise<{ eth: bigint; token: bigint; settledOut: boolean }> {
    const c = await view.constants();
    const pMax = SigningClient.effectivePriceCap(profile, c.P_FLOOR);
    const eth = pMax * (GAS.open + GAS.decrypt) + this.opts.pSwap * GAS.swap + this.opts.pBind * GAS.bind;
    const token = profile.deposit;
    const open = this.purchases.filter((p) => p.reserve && p.state !== "done" && p.state !== "refused");
    const needEth = open.reduce((s, p) => s + p.reserve!.eth, 0n) + eth;
    const needToken = open.reduce((s, p) => s + p.reserve!.token + (p.reserve!.settledOut ? 0n : p.amount ?? 0n), 0n) + token + amount;
    const haveEth = await this.opts.publicClient.getBalance({ address: this.account.address });
    const haveToken = (await this.opts.publicClient.readContract({ address: await view.token(), abi: erc20Abi, functionName: "balanceOf", args: [this.account.address] })) as bigint;
    if (haveEth < needEth) throw new PaymentRefused(`gas reserve short: need ${needEth} wei, have ${haveEth}`);
    if (haveToken < needToken) throw new PaymentRefused(`token reserve short: need ${needToken}, have ${haveToken}`);
    const nOpen = BigInt(open.length + 1);
    const limit = BigInt(Math.floor(this.opts.rho * 1e6)) * c.T_X * this.opts.blockGasTarget / 1_000_000n;
    if (nOpen * GAS.decrypt > limit) throw new PaymentRefused("open purchases above the challenge gas share");
    return { eth, token, settledOut: false };
  }

  /** One purchase: request, 402, checks, bound payment, receipt check,
   * buyer signature or none. Purchases are processed one at a time. */
  buy(url: string, init: RequestInit = {}): Promise<Purchase> {
    const run = this.queue.then(() => this.buyOne(url, init));
    this.queue = run.catch(() => undefined);
    return run;
  }

  private async buyOne(url: string, init: RequestInit): Promise<Purchase> {
    const f = this.opts.fetchImpl ?? fetch;
    const p: Purchase = { url, state: "unpaid", checks: [] };
    this.purchases.push(p);
    const method = (init.method ?? "GET").toUpperCase();
    const body = init.body ? new TextEncoder().encode(String(init.body)) : new Uint8Array();
    const u = new URL(url);
    const pathAndQuery = u.pathname + u.search;

    const first = await f(url, init);
    if (first.status !== 402) {
      p.state = "refused";
      p.reason = `expected 402, got ${first.status}`;
      return p;
    }
    const pr = this.http.getPaymentRequiredResponse((n) => first.headers.get(n), await first.json().catch(() => undefined));
    let offer;
    try {
      offer = await this.checkOffer(pr);
    } catch (e) {
      p.state = "refused";
      p.reason = (e as Error).message;
      return p;
    }
    const { req, ext, profile, view } = offer;
    const amount = BigInt(req.amount);
    try {
      p.reserve = await this.reserve(profile, amount, view);
    } catch (e) {
      p.state = "refused";
      p.reason = (e as Error).message;
      return p;
    }
    const chainId = await this.opts.publicClient.getChainId();
    const salt = toHex(crypto.getRandomValues(new Uint8Array(32)));
    const rq = requestHashOf(method, pathAndQuery, body, salt);
    const cl = claimsHashOf(profile.inputRule, method, pathAndQuery);
    const nonce = boundNonce(chainId, ext.contract, ext.profileId, rq, cl, salt);
    const now = await view.chainTime();
    const validAfter = now - 5n;
    const validBefore = now + BigInt(req.maxTimeoutSeconds);
    p.contract = view.contract;
    p.pid = ext.profileId;
    p.nonce = nonce;
    p.amount = amount;
    const binding = { requestHash: rq, claimsHash: cl, salt };
    // sigma_W for each watchtower, made with the authorization
    const mandates = new Map<TowerLink, Hex>();
    for (const t of this.opts.watchtowers ?? []) {
      mandates.set(
        t,
        await this.opts.wallet.signTypedData({
          account: this.account,
          domain: domain(chainId, ext.contract),
          types: MANDATE_TYPES,
          primaryType: "DisputeMandate",
          message: { profileId: ext.profileId, nonce, delegate: t.address, kinds: TOWER_KINDS },
        }),
      );
    }
    p.mandates = mandates;
    const task: Task = { pid: ext.profileId, nonce, payer: this.account.address, validBefore, signed: false, binding };
    p.task = task;

    this.pending = { nonce, validAfter, validBefore, binding };
    let payload: PaymentPayload;
    try {
      payload = await this.http.createPaymentPayload(pr);
    } finally {
      this.pending = undefined;
    }
    p.state = "paid";
    await this.handOver(p);

    const headers = new Headers(init.headers);
    for (const [k, v] of Object.entries(this.http.encodePaymentSignatureHeader(payload))) headers.set(k, v);
    let resp: Response | undefined;
    try {
      resp = await f(url, { ...init, headers });
    } catch (e) {
      p.checks.push(`no response: ${(e as Error).message}`);
    }
    const bytes = resp && resp.ok ? new Uint8Array(await resp.arrayBuffer()) : new Uint8Array();
    const envHeader = resp?.headers.get(RECEIPT_HEADER);
    const receivedAt = await view.head();

    // the settlement as observed on chain (eta)
    const sale = await view.sale(ext.profileId, nonce);
    if (sale.payer === "0x0000000000000000000000000000000000000000") {
      p.checks.push("settlement not observed");
      p.state = "unsigned";
      return p;
    }
    p.reserve.settledOut = true;
    const eta = BigInt(sale.settledBlock);
    const duties = this.duties.get(view.contract)!;
    await duties.step(task); // binding completion when the facilitator dropped the triple

    if (!resp || !resp.ok || !envHeader) {
      p.checks.push(`no receipt (status ${resp?.status ?? "none"})`);
      p.state = "unsigned";
      return p;
    }
    const env = unb64<ReceiptEnvelope>(envHeader);
    const rs = receiptFromWire(env.receipt as Record<string, string>);
    p.receipt = rs;
    p.response = bytes;
    const tSig = await view.signDeadline(eta, sale.epoch);
    const failures = await this.checkReceipt({ rs, env, bytes, profile, pid: ext.profileId, nonce, amount, requestHash: rq, claimsHash: cl, chainId, contract: ext.contract, head: receivedAt, tSig, eta, view });
    p.checks.push(...failures);
    if (failures.length) {
      p.state = "unsigned";
      return p;
    }
    // (c) sign sigma_B, once per nonce
    const sigB = await this.opts.wallet.signTypedData({
      account: this.account,
      domain: domain(chainId, ext.contract),
      types: ACK_TYPES,
      primaryType: "BuyerAck",
      message: ackMessage(rs, ext.profileId, profile.codeHash, false),
    });
    task.signed = true;
    task.receipt = rs;
    const ctProfile = (profile.flags & F_CT) !== 0;
    if (ctProfile) {
      task.ct = bytesToHex(bytes);
      task.keyStatus = "missing";
    }
    p.state = "signed";
    task.sigB = sigB;
    // sigma_B goes to the watchtowers first; it goes to the seller only
    // after every watchtower holding the non-delivery kind returned a signed
    // receipt acknowledgement (checked here), so no watchtower opens a
    // non-delivery dispute on a signed sale
    p.ackUrl = ext.ackUrl;
    await this.deliverAck(p);
    return p;
  }

  /** Sends sigma_B to the seller once all acknowledgements are in (also
   * after t_sig, as soon as the last one arrives). */
  private async deliverAck(p: Purchase): Promise<boolean> {
    if (!(await this.handOver(p))) {
      p.ackPending = true;
      if (!p.checks.includes("watchtower acknowledgement missing")) p.checks.push("watchtower acknowledgement missing");
      return false;
    }
    p.ackPending = false;
    const f = this.opts.fetchImpl ?? fetch;
    const ackResp = await f(p.ackUrl!, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ nonce: p.nonce, signature: p.task!.sigB }) }).catch(() => undefined);
    const profile = await this.viewFor(p.contract!).profile(p.pid!);
    if ((profile.flags & F_CT) !== 0 && ackResp?.ok) {
      const j = (await ackResp.json().catch(() => ({}))) as { key?: Hex };
      if (j.key) this.acceptKey(p, j.key);
    }
    await this.handOver(p); // key status update
    return true;
  }

  /** Hands a purchase to every watchtower with that watchtower's mandate.
   * For a signed purchase, returns whether every watchtower whose mandate
   * holds the non-delivery kind acknowledged sigma_B with a valid
   * signature of its delegate address. */
  async handOver(p: Purchase): Promise<boolean> {
    let all = true;
    const chainId = await this.opts.publicClient.getChainId();
    for (const t of this.opts.watchtowers ?? []) {
      const ack = await t.submit({ ...structuredClone(p.task!), mandate: p.mandates?.get(t), mandateKinds: TOWER_KINDS });
      if (!p.task!.signed || (TOWER_KINDS & MANDATE_KINDS.nonDelivery) === 0) continue;
      let ok = false;
      if (ack) {
        try {
          const who = await recoverTypedDataAddress({
            domain: domain(chainId, p.contract!),
            types: TOWER_ACK_TYPES,
            primaryType: "TowerReceipt",
            message: { profileId: p.pid!, nonce: p.nonce!, sigBHash: keccak256(p.task!.sigB!) },
            signature: ack,
          });
          ok = who.toLowerCase() === t.address.toLowerCase();
        } catch {
          ok = false;
        }
      }
      if (!ok) all = false;
    }
    return all;
  }

  /** Key check: H(k) = h_k and Dec_k(ct) against h_r. */
  acceptKey(p: Purchase, k: Hex) {
    const task = p.task!;
    const rs = p.receipt!;
    if (keyHash(k) !== rs.keyHash) {
      task.keyStatus = "missing"; // an invalid k counts as no key
      return;
    }
    const pt = decrypt(k, rs.nonce, hexToBytes(task.ct!));
    const ok = keccak256(bytesToHex(new Uint8Array([...hexToBytes(TAGS.response), ...pt]))) === rs.responseHash;
    task.keyStatus = ok ? "ok" : "bad";
    if (!ok) task.offchainKey = k;
    if (ok) p.response = pt.slice(32);
  }

  /** (b) The receipt check before sigma_B. Returns
   * the failed checks; an empty list means the client may sign. */
  async checkReceipt(a: {
    rs: SignedReceipt;
    env: ReceiptEnvelope;
    bytes: Uint8Array;
    profile: Profile;
    pid: Hex;
    nonce: Hex;
    amount: bigint;
    requestHash: Hex;
    claimsHash: Hex;
    chainId: number;
    contract: Address;
    head: bigint;
    tSig: bigint;
    eta: bigint;
    view: ChainView;
  }): Promise<string[]> {
    const f: string[] = [];
    const { rs, profile } = a;
    if (rs.nonce.toLowerCase() !== a.nonce.toLowerCase()) f.push("receipt nonce differs from the authorization");
    if (rs.amount !== a.amount) f.push("receipt amount differs from the authorization");
    if (rs.profileId.toLowerCase() !== a.pid.toLowerCase()) f.push("receipt profile id differs from the payment's profile");
    if (rs.codeHash.toLowerCase() !== profile.codeHash.toLowerCase()) f.push("receipt code hash differs from the profile");
    if (rs.requestHash !== a.requestHash) f.push("receipt request hash differs from the client's");
    if (rs.claimsHash !== a.claimsHash) f.push("receipt claims differ from those the request and profile determine");
    try {
      const signer = await recoverTypedDataAddress({
        domain: domain(a.chainId, a.contract),
        types: RECEIPT_TYPES,
        primaryType: "SellerReceipt",
        message: receiptMessage(rs, rs.profileId, rs.codeHash),
        signature: rs.signature,
      });
      if (signer.toLowerCase() !== profile.receiptKey.toLowerCase()) f.push("receipt not signed by the profile's receipt key");
    } catch {
      f.push("receipt signature invalid");
    }
    if (this.purchases.some((p) => p.task?.signed && p.nonce?.toLowerCase() === a.nonce.toLowerCase())) f.push("nonce already signed");
    if (a.head >= a.tSig) f.push("receipt after the signing deadline t_sig");
    if (profile.responseDeadline !== 0 && a.head > a.eta + BigInt(profile.responseDeadline)) f.push("response after the response deadline r_dl");
    if ((profile.flags & F_CT) !== 0) {
      if (keccak256(bytesToHex(a.bytes)) !== rs.ctHash) f.push("ciphertext does not match h_ct");
      // a key already public on chain (an answer to someone's dispute): sign
      // only if ct decrypts to h_r under it
      const ans = await a.view.answers(a.pid, a.nonce);
      if ((ans.ctkBlock !== 0n || ans.kBlock !== 0n) && decryptHash(ans.key, a.nonce, a.bytes) !== rs.responseHash) f.push("public key does not decrypt ct to h_r");
    } else {
      try {
        if (responseHash(a.env.psi, a.bytes) !== rs.responseHash) f.push("response does not match h_r");
      } catch (e) {
        f.push((e as Error).message);
      }
      if (a.env.material && keccak256(a.env.material) !== rs.materialCommit) f.push("proof material does not match its commitment");
    }
    return f;
  }

  /** (d) One pass of every open purchase's duties. */
  async tick(): Promise<void> {
    for (const p of this.purchases) {
      if (!p.task || p.task.done || !p.contract) continue;
      if (p.ackPending) await this.deliverAck(p);
      await this.duties.get(p.contract)!.step(p.task);
      if (p.task.done) {
        p.state = "done";
        p.reason = p.task.note;
      }
    }
  }

  /** Reserves held for open purchases. */
  reserved(): { eth: bigint; token: bigint } {
    const open = this.purchases.filter((p) => p.reserve && p.state !== "done" && p.state !== "refused");
    return { eth: open.reduce((s, p) => s + p.reserve!.eth, 0n), token: open.reduce((s, p) => s + p.reserve!.token, 0n) };
  }
}

function profileFromWireish(p: Profile) {
  return Object.fromEntries(Object.entries(p).map(([k, v]) => [k, typeof v === "string" ? v.toLowerCase() : String(v)]));
}
