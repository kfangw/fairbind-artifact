// Wire formats between the signing client and a seller that offers sampled
// settlement through x402 v2. The x402 headers themselves are encoded by the
// official @x402/core helpers.
import type { Address, Hex } from "viem";
import type { Profile, SignedReceipt } from "./hashing.ts";

/** Key of the x402 extension carrying the profile and the binding. */
export const EXTENSION_KEY = "sampled-settlement";
export const RECEIPT_HEADER = "x-settlement-receipt";

/** Server side of the extension (in PaymentRequired.extensions). */
export interface OfferExtension {
  contract: Address;
  profileId: Hex;
  profile: Record<keyof Profile, string | number>;
  ackUrl: string;
}

/** Client side of the extension (in PaymentPayload.extensions). */
export interface BindingExtension {
  binding: { requestHash: Hex; claimsHash: Hex; salt: Hex };
}

/** What the seller returns with the response. */
export interface ReceiptEnvelope {
  receipt: Record<keyof SignedReceipt, string>;
  psi: Hex;
  /** Proof material, or where to get it (here: inline). */
  material?: Hex;
}

export function profileToWire(p: Profile): Record<keyof Profile, string | number> {
  return {
    account: p.account,
    receiptKey: p.receiptKey,
    unitKey: p.unitKey,
    verifier: p.verifier,
    codeHash: p.codeHash,
    tier: p.tier,
    flags: p.flags,
    cap: p.cap.toString(),
    minAmount: p.minAmount.toString(),
    responseDeadline: p.responseDeadline,
    deposit: p.deposit.toString(),
    maxFeePerGas: p.maxFeePerGas.toString(),
    epochMultiple: p.epochMultiple,
    inputRule: p.inputRule,
  };
}

export function profileFromWire(w: Record<string, string | number>): Profile {
  return {
    account: w.account as Address,
    receiptKey: w.receiptKey as Address,
    unitKey: w.unitKey as Address,
    verifier: w.verifier as Address,
    codeHash: w.codeHash as Hex,
    tier: Number(w.tier),
    flags: Number(w.flags),
    cap: BigInt(w.cap),
    minAmount: BigInt(w.minAmount),
    responseDeadline: Number(w.responseDeadline),
    deposit: BigInt(w.deposit),
    maxFeePerGas: BigInt(w.maxFeePerGas),
    epochMultiple: Number(w.epochMultiple),
    inputRule: w.inputRule as Hex,
  };
}

export function receiptToWire(r: SignedReceipt): Record<keyof SignedReceipt, string> {
  return {
    nonce: r.nonce,
    amount: r.amount.toString(),
    requestHash: r.requestHash,
    responseHash: r.responseHash,
    ctHash: r.ctHash,
    keyHash: r.keyHash,
    claimsHash: r.claimsHash,
    materialCommit: r.materialCommit,
    profileId: r.profileId,
    codeHash: r.codeHash,
    signature: r.signature,
  };
}

export function receiptFromWire(w: Record<string, string>): SignedReceipt {
  return {
    nonce: w.nonce as Hex,
    amount: BigInt(w.amount),
    requestHash: w.requestHash as Hex,
    responseHash: w.responseHash as Hex,
    ctHash: w.ctHash as Hex,
    keyHash: w.keyHash as Hex,
    claimsHash: w.claimsHash as Hex,
    materialCommit: w.materialCommit as Hex,
    profileId: w.profileId as Hex,
    codeHash: w.codeHash as Hex,
    signature: w.signature as Hex,
  };
}

export const b64 = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64");
export const unb64 = <T>(s: string): T => JSON.parse(Buffer.from(s, "base64").toString("utf8")) as T;
