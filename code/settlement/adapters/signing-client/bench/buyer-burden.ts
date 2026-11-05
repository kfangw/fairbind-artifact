// Buyer-side extra work per purchase under sampled settlement, against a
// plain x402 v2 exact (EIP-3009) purchase. Measures, with the client's own
// functions (src/hashing.ts, src/wire.ts, src/client.ts), on this machine:
//   binding      salt, request hash, claims hash, binding hash, bound nonce
//   receiptCheck seller receipt signature recovery, h_r of the response and
//                the material commitment (the cryptographic part of check (b))
//   sigmaB       h_RS and the EIP-712 BuyerAck signature sigma_B
//   perPurchase  binding + sigmaB (+ receiptCheck in perPurchaseWithCheck)
//   mandate      one watchtower's sigma_W, and the check of its receipt ack
//   eip3009      the payment signature plain x402 already makes (reference)
// each as median and p95 over RUNS runs after WARMUP runs; and the bytes the
// extension adds to the x402 payment message (PAYMENT-SIGNATURE header),
// to the 402 offer (PAYMENT-REQUIRED header) and the sigma_B delivery.
// Keys are generated in memory for the run (no funds, nothing on chain).
//
// usage: node bench/buyer-burden.ts [runs]      (default 2000)
import { x402Client, x402HTTPClient } from "@x402/core/client";
import { encodePaymentSignatureHeader, encodePaymentRequiredHeader } from "@x402/core/http";
import type { PaymentRequired } from "@x402/core/types";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { authorizationTypes } from "@x402/evm";
import { createWalletClient, custom, keccak256, recoverTypedDataAddress, toHex, type Hex, type Address } from "viem";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import os from "node:os";
import { performance } from "node:perf_hooks";
import {
  ACK_TYPES,
  ackMessage,
  boundNonce,
  claimsHash,
  domain,
  MANDATE_TYPES,
  profileId,
  RECEIPT_TYPES,
  receiptMessage,
  requestHash,
  responseHash,
  TOWER_ACK_TYPES,
  type Profile,
  type SignedReceipt,
} from "../src/hashing.ts";
import { SigningClient, TOWER_KINDS } from "../src/client.ts";
import { EXTENSION_KEY, profileToWire, receiptToWire, b64, type OfferExtension } from "../src/wire.ts";

const RUNS = Number(process.argv[2] ?? 2000);
const WARMUP = 200;
const CHAIN_ID = 8453;
const USDC: Address = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const CONTRACT: Address = "0x5FbDB2315678afecb367f032d93F642f64180aa3";
const VAULT: Address = "0xa16E02E87b7454126E5E10d957A927A7F5B5d2be";

const buyer = privateKeyToAccount(generatePrivateKey());
const sellerAcct = privateKeyToAccount(generatePrivateKey());
const towerAcct = privateKeyToAccount(generatePrivateKey());
const noRpc = custom({ request: async () => { throw new Error("no rpc in the benchmark"); } });
const wallet = createWalletClient({ account: buyer, transport: noRpc });

const h = (s: string): Hex => keccak256(toHex(s));
const profile: Profile = {
  account: sellerAcct.address,
  receiptKey: sellerAcct.address,
  unitKey: sellerAcct.address,
  verifier: "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0",
  codeHash: h("verifier code"),
  tier: 1,
  flags: 0,
  cap: 1_000_000n,
  minAmount: 100n,
  responseDeadline: 0,
  deposit: 50_000n,
  maxFeePerGas: 1_000_000_000n,
  epochMultiple: 1,
  inputRule: h("input rule"),
};
const pid = profileId(profile);
// the e2e seller's sizes: a 96-byte response (three words) and 129 bytes of
// tier 1a material (psi and a Lazer update)
const response = new Uint8Array(96).fill(7);
const material = toHex(new Uint8Array(129).fill(9));
const method = "GET";
const pathAndQuery = "/price?feed=1";
const body = new Uint8Array();

function stats(xs: number[]) {
  const s = [...xs].sort((a, b) => a - b);
  const q = (p: number) => s[Math.min(s.length - 1, Math.ceil(p * s.length) - 1)];
  return { n: s.length, median_ms: +q(0.5).toFixed(4), p95_ms: +q(0.95).toFixed(4), mean_ms: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(4), max_ms: +s[s.length - 1].toFixed(4) };
}

async function time(name: string, fn: (i: number) => Promise<unknown> | unknown) {
  for (let i = 0; i < WARMUP; i++) await fn(-1 - i);
  const xs: number[] = [];
  for (let i = 0; i < RUNS; i++) {
    const t0 = performance.now();
    await fn(i);
    xs.push(performance.now() - t0);
  }
  return [name, stats(xs)] as const;
}

// --- steps, as SigningClient.buyOne makes them ---------------------------
function binding() {
  const salt = toHex(crypto.getRandomValues(new Uint8Array(32)));
  const rq = requestHash(method, pathAndQuery, body, salt);
  const cl = claimsHash(profile.inputRule, method, pathAndQuery);
  const nonce = boundNonce(CHAIN_ID, CONTRACT, pid, rq, cl, salt);
  return { salt, rq, cl, nonce };
}

async function sellerReceipt(b: { rq: Hex; cl: Hex; nonce: Hex }): Promise<SignedReceipt> {
  const r = {
    nonce: b.nonce,
    amount: 10_000n,
    requestHash: b.rq,
    responseHash: responseHash(h("psi"), response),
    ctHash: h("ct"),
    keyHash: h("k"),
    claimsHash: b.cl,
    materialCommit: keccak256(material),
  };
  const signature = await sellerAcct.signTypedData({ domain: domain(CHAIN_ID, CONTRACT), types: RECEIPT_TYPES, primaryType: "SellerReceipt", message: receiptMessage(r, pid, profile.codeHash) });
  return { ...r, profileId: pid, codeHash: profile.codeHash, signature };
}

async function receiptCheck(rs: SignedReceipt) {
  const signer = await recoverTypedDataAddress({ domain: domain(CHAIN_ID, CONTRACT), types: RECEIPT_TYPES, primaryType: "SellerReceipt", message: receiptMessage(rs, rs.profileId, rs.codeHash), signature: rs.signature });
  if (signer !== sellerAcct.address) throw new Error("receipt signer");
  if (responseHash(h("psi"), response) !== rs.responseHash) throw new Error("h_r");
  if (keccak256(material) !== rs.materialCommit) throw new Error("material");
}

function sigmaB(rs: SignedReceipt) {
  return wallet.signTypedData({ account: buyer, domain: domain(CHAIN_ID, CONTRACT), types: ACK_TYPES, primaryType: "BuyerAck", message: ackMessage(rs, pid, profile.codeHash, false) });
}

function mandate(nonce: Hex) {
  return wallet.signTypedData({ account: buyer, domain: domain(CHAIN_ID, CONTRACT), types: MANDATE_TYPES, primaryType: "DisputeMandate", message: { profileId: pid, nonce, delegate: towerAcct.address, kinds: TOWER_KINDS } });
}

function eip3009(nonce: Hex) {
  return wallet.signTypedData({
    account: buyer,
    domain: { name: "USD Coin", version: "2", chainId: CHAIN_ID, verifyingContract: USDC },
    types: authorizationTypes,
    primaryType: "TransferWithAuthorization",
    message: { from: buyer.address, to: VAULT, value: 10_000n, validAfter: 1_792_743_000n, validBefore: 1_792_743_600n, nonce },
  });
}

async function main() {
  // fixed inputs for the steps that take a receipt
  const b0 = binding();
  const rs0 = await sellerReceipt(b0);
  const sigB0 = await sigmaB(rs0);
  const towerAck = await towerAcct.signTypedData({ domain: domain(CHAIN_ID, CONTRACT), types: TOWER_ACK_TYPES, primaryType: "TowerReceipt", message: { profileId: pid, nonce: b0.nonce, sigBHash: keccak256(sigB0) } });

  const rows = [
    await time("binding", () => binding()),
    await time("receiptCheck", () => receiptCheck(rs0)),
    await time("sigmaB", () => sigmaB(rs0)),
    // one fixed receipt stands in for each run's own (the work of h_RS and
    // the signature does not depend on the field values)
    await time("perPurchase", () => {
      binding();
      return sigmaB(rs0);
    }),
    await time("perPurchaseWithCheck", async () => {
      binding();
      await receiptCheck(rs0);
      return sigmaB(rs0);
    }),
    await time("mandateSign", () => mandate(b0.nonce)),
    await time("towerAckCheck", () =>
      recoverTypedDataAddress({ domain: domain(CHAIN_ID, CONTRACT), types: TOWER_ACK_TYPES, primaryType: "TowerReceipt", message: { profileId: pid, nonce: b0.nonce, sigBHash: keccak256(sigB0) }, signature: towerAck })),
    await time("eip3009 (plain x402, reference)", () => eip3009(b0.nonce)),
  ];

  // --- bytes on the wire ---------------------------------------------------
  const accepts = [{ scheme: "exact", network: `eip155:${CHAIN_ID}`, asset: USDC, amount: "10000", payTo: VAULT, maxTimeoutSeconds: 600, extra: { name: "USD Coin", version: "2" } }];
  const resource = { url: "http://127.0.0.1:4021/price?feed=1", description: "price feed", mimeType: "application/octet-stream" };
  const offer: OfferExtension = { contract: CONTRACT, profileId: pid, profile: profileToWire(profile), ackUrl: "http://127.0.0.1:4021/ack" };
  const prPlain = { x402Version: 2, resource, accepts } as unknown as PaymentRequired;
  const prFair = { ...prPlain, extensions: { [EXTENSION_KEY]: offer } } as unknown as PaymentRequired;

  // plain x402: the official exact client, random nonce
  const plainCore = new x402Client();
  plainCore.register("eip155:*", new ExactEvmScheme(buyer));
  const plainPayload = await new x402HTTPClient(plainCore).createPaymentPayload(prPlain);
  // sampled settlement: the signing client's own x402 client and bound payload
  const sc = new SigningClient({ wallet, publicClient: {} as never, trustedContracts: [CONTRACT], maxDeposit: 50_000n, allowedTiers: [1], dObs: 2n, dTx: 2n, pSwap: 0n, pBind: 0n, rho: 0.1, blockGasTarget: 30_000_000n });
  const scAny = sc as unknown as { pending: unknown; http: x402HTTPClient };
  scAny.pending = { nonce: b0.nonce, validAfter: 1_792_743_000n, validBefore: 1_792_743_600n, binding: { requestHash: b0.rq, claimsHash: b0.cl, salt: b0.salt } };
  const fairPayload = await scAny.http.createPaymentPayload(prFair);
  scAny.pending = undefined;

  const len = (s: string) => Buffer.byteLength(s, "utf8");
  const plainJson = JSON.stringify(plainPayload);
  const fairJson = JSON.stringify(fairPayload);
  const plainHdr = encodePaymentSignatureHeader(plainPayload);
  const fairHdr = encodePaymentSignatureHeader(fairPayload);
  const fairExt = (fairPayload.extensions ?? {})[EXTENSION_KEY] as Record<string, unknown>;
  const bindingOnly = JSON.stringify({ [EXTENSION_KEY]: { binding: fairExt.binding } });
  const ackBody = JSON.stringify({ nonce: b0.nonce, signature: sigB0 });
  const bytes = {
    paymentSignatureHeader: {
      plain_json: len(plainJson),
      fairbind_json: len(fairJson),
      added_json: len(fairJson) - len(plainJson),
      plain_base64: len(plainHdr),
      fairbind_base64: len(fairHdr),
      added_base64: len(fairHdr) - len(plainHdr),
      echoed_offer_keys: Object.keys(fairExt).filter((k) => k !== "binding"),
      binding_only_extension_json: len(bindingOnly),
      note: "x402Client merges the 402 offer's extensions into the payload, so the payment message carries the echoed offer (contract, profileId, profile, ackUrl) and the binding triple; the bound nonce replaces the random nonce at the same length",
    },
    paymentRequiredHeader: {
      plain_base64: len(encodePaymentRequiredHeader(prPlain)),
      fairbind_base64: len(encodePaymentRequiredHeader(prFair)),
      added_base64: len(encodePaymentRequiredHeader(prFair)) - len(encodePaymentRequiredHeader(prPlain)),
      offer_extension_json: len(JSON.stringify({ [EXTENSION_KEY]: offer })),
    },
    sigmaBDelivery: { post_body_json: len(ackBody), note: "POST to ackUrl, a separate buyer-to-seller message after the response" },
    receiptHeader: { base64: len(b64({ receipt: receiptToWire(rs0), psi: h("psi"), material })), note: "x-settlement-receipt, seller to buyer, tier 1a material inline" },
  };

  const cpus = os.cpus();
  const out = {
    runs: RUNS,
    warmup: WARMUP,
    machine: { cpu: cpus[0]?.model, logical_cpus: cpus.length, mem_gb: +(os.totalmem() / 2 ** 30).toFixed(1), os: `${os.type()} ${os.release()} ${os.arch()}`, node: process.version, viem: "2.48.11", x402: "2.28.0", note: "cloud container (shared VM), single-threaded loop, nothing else running" },
    timing: Object.fromEntries(rows),
    bytes,
  };
  console.log(JSON.stringify(out, null, 2));
}

await main();
