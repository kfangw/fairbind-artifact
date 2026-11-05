// Encodings and hashes shared with the settlement contract. Each function
// mirrors a function of contracts/test/sdk/SampledSettlement.sol; the e2e run
// checks them against the deployed contract.
import {
  concatHex,
  encodeAbiParameters,
  hexToBytes,
  bytesToHex,
  keccak256,
  stringToHex,
  hashTypedData,
  type Address,
  type Hex,
} from "viem";

export const ZERO32: Hex = `0x${"00".repeat(32)}`;

const tag = (s: string): Hex => keccak256(stringToHex(s));
export const TAGS = {
  response: tag("p5/response/v1"),
  leaf0: tag("p5/leaf0/v1"),
  node: tag("settlement/epoch-node/v1"),
  nonce: tag("settlement/bound-nonce/v1"),
  request: tag("settlement/request/v1"),
  claims: tag("settlement/claims/v1"),
};

export interface Profile {
  account: Address;
  receiptKey: Address;
  unitKey: Address;
  verifier: Address;
  codeHash: Hex;
  tier: number;
  flags: number;
  cap: bigint;
  /** v_min: smallest sale amount the profile accepts (0 < v_min <= cap). */
  minAmount: bigint;
  responseDeadline: number;
  deposit: bigint;
  maxFeePerGas: bigint;
  /** k: consecutive profile epochs per seller epoch (1 to K_MAX, one per account). */
  epochMultiple: number;
  inputRule: Hex;
}

export const PROFILE_COMPONENTS = [
  { name: "account", type: "address" },
  { name: "receiptKey", type: "address" },
  { name: "unitKey", type: "address" },
  { name: "verifier", type: "address" },
  { name: "codeHash", type: "bytes32" },
  { name: "tier", type: "uint8" },
  { name: "flags", type: "uint8" },
  { name: "cap", type: "uint64" },
  { name: "minAmount", type: "uint64" },
  { name: "responseDeadline", type: "uint32" },
  { name: "deposit", type: "uint64" },
  { name: "maxFeePerGas", type: "uint64" },
  { name: "epochMultiple", type: "uint16" },
  { name: "inputRule", type: "bytes32" },
] as const;

export const F_BLOCKHASH = 1;
export const F_CT = 2;

/** keccak256(abi.encode(profile)), the profile id. */
export function profileId(p: Profile): Hex {
  return keccak256(encodeAbiParameters([{ type: "tuple", components: PROFILE_COMPONENTS }], [p]));
}

/** Receipt fields carried in a leaf (the contract's Receipt struct). */
export interface Receipt {
  nonce: Hex;
  amount: bigint;
  requestHash: Hex;
  responseHash: Hex;
  ctHash: Hex;
  keyHash: Hex;
  claimsHash: Hex;
  materialCommit: Hex;
}

/** A seller receipt as delivered: the leaf fields plus the profile id and
 * code hash it was signed under, and the seller's EIP-712 signature. */
export interface SignedReceipt extends Receipt {
  profileId: Hex;
  codeHash: Hex;
  signature: Hex;
}

export function domain(chainId: number, contract: Address) {
  return { name: "Settlement", version: "10", chainId, verifyingContract: contract } as const;
}

export const RECEIPT_TYPES = {
  SellerReceipt: [
    { name: "nonce", type: "bytes32" },
    { name: "amount", type: "uint256" },
    { name: "requestHash", type: "bytes32" },
    { name: "responseHash", type: "bytes32" },
    { name: "ctHash", type: "bytes32" },
    { name: "keyHash", type: "bytes32" },
    { name: "profileId", type: "bytes32" },
    { name: "codeHash", type: "bytes32" },
    { name: "claimsHash", type: "bytes32" },
    { name: "materialCommit", type: "bytes32" },
  ],
} as const;

export const ACK_TYPES = {
  BuyerAck: [
    { name: "nonce", type: "bytes32" },
    { name: "amount", type: "uint256" },
    { name: "requestHash", type: "bytes32" },
    { name: "responseHash", type: "bytes32" },
    { name: "ctHash", type: "bytes32" },
    { name: "profileId", type: "bytes32" },
    { name: "codeHash", type: "bytes32" },
    { name: "receiptHash", type: "bytes32" },
    { name: "accepted", type: "bool" },
  ],
} as const;

export const UNIT_TYPES = {
  AnchorUnit: [
    { name: "profileId", type: "bytes32" },
    { name: "epoch", type: "uint32" },
    { name: "count", type: "uint32" },
    { name: "unitNo", type: "uint32" },
    { name: "firstNonce", type: "bytes32" },
    { name: "lastNonce", type: "bytes32" },
    { name: "root", type: "bytes32" },
    { name: "root0", type: "bytes32" },
    { name: "snapshotHash", type: "bytes32" },
  ],
} as const;

export const MANDATE_TYPES = {
  DisputeMandate: [
    { name: "profileId", type: "bytes32" },
    { name: "nonce", type: "bytes32" },
    { name: "delegate", type: "address" },
    { name: "kinds", type: "uint8" },
  ],
} as const;

/** A watchtower's receipt acknowledgement of sigma_B: signed by the
 * delegate address over (profile id, nonce, H(sigma_B)); the contract does
 * not read it. */
export const TOWER_ACK_TYPES = {
  TowerReceipt: [
    { name: "profileId", type: "bytes32" },
    { name: "nonce", type: "bytes32" },
    { name: "sigBHash", type: "bytes32" },
  ],
} as const;

/** Kinds a dispute mandate may delegate (bit mask). */
export const MANDATE_KINDS = { nonDelivery: 1, key: 2, decryption: 4, response: 8 } as const;

export function receiptMessage(r: Receipt, pid: Hex, codeHash: Hex) {
  return {
    nonce: r.nonce,
    amount: r.amount,
    requestHash: r.requestHash,
    responseHash: r.responseHash,
    ctHash: r.ctHash,
    keyHash: r.keyHash,
    profileId: pid,
    codeHash,
    claimsHash: r.claimsHash,
    materialCommit: r.materialCommit,
  };
}

/** EIP-712 struct hash of a seller receipt (h_RS). */
export function rsHash(r: Receipt, pid: Hex, codeHash: Hex): Hex {
  const t = RECEIPT_TYPES.SellerReceipt;
  const typeHash = keccak256(stringToHex(`SellerReceipt(${t.map((f) => `${f.type} ${f.name}`).join(",")})`));
  const m = receiptMessage(r, pid, codeHash);
  return keccak256(
    encodeAbiParameters(
      [{ type: "bytes32" }, ...t.map((f) => ({ type: f.type }))],
      [typeHash, m.nonce, m.amount, m.requestHash, m.responseHash, m.ctHash, m.keyHash, m.profileId, m.codeHash, m.claimsHash, m.materialCommit],
    ),
  );
}

export function receiptDigest(r: Receipt, pid: Hex, codeHash: Hex, chainId: number, contract: Address): Hex {
  return hashTypedData({
    domain: domain(chainId, contract),
    types: RECEIPT_TYPES,
    primaryType: "SellerReceipt",
    message: receiptMessage(r, pid, codeHash),
  });
}

export function ackMessage(r: Receipt, pid: Hex, codeHash: Hex, accepted: boolean) {
  return {
    nonce: r.nonce,
    amount: r.amount,
    requestHash: r.requestHash,
    responseHash: r.responseHash,
    ctHash: r.ctHash,
    profileId: pid,
    codeHash,
    receiptHash: rsHash(r, pid, codeHash),
    accepted,
  };
}

export function leaf0Of(nonce: Hex, hRS: Hex, unanswered: number): Hex {
  return keccak256(
    encodeAbiParameters([{ type: "bytes32" }, { type: "bytes32" }, { type: "bytes32" }, { type: "uint8" }], [TAGS.leaf0, nonce, hRS, unanswered]),
  );
}

export function leafOf(l0: Hex, sigHash: Hex, beta: boolean, accept: boolean): Hex {
  return keccak256(
    encodeAbiParameters([{ type: "bytes32" }, { type: "bytes32" }, { type: "bool" }, { type: "bool" }], [l0, sigHash, beta, accept]),
  );
}

export function node(a: Hex, b: Hex): Hex {
  return keccak256(encodeAbiParameters([{ type: "bytes32" }, { type: "bytes32" }, { type: "bytes32" }], [TAGS.node, a, b]));
}

export function levels(leaves: Hex[]): Hex[][] {
  const out: Hex[][] = [leaves.slice()];
  while (out[out.length - 1].length > 1) {
    const cur = out[out.length - 1];
    const next: Hex[] = [];
    for (let i = 0; i < cur.length; i += 2) next.push(node(cur[i], i + 1 < cur.length ? cur[i + 1] : cur[i]));
    out.push(next);
  }
  return out;
}

export function merklePath(lv: Hex[][], index: number): Hex[] {
  const p: Hex[] = [];
  for (let d = 0; d + 1 < lv.length; d++) {
    const sib = index ^ 1;
    p.push(sib < lv[d].length ? lv[d][sib] : lv[d][index]);
    index >>= 1;
  }
  return p;
}

export function bindingHash(requestHash: Hex, claimsHash: Hex): Hex {
  return keccak256(encodeAbiParameters([{ type: "bytes32" }, { type: "bytes32" }], [requestHash, claimsHash]));
}

/** nonce = H(tag, chain id, contract, profile id, binding hash, salt). */
export function boundNonce(chainId: number, contract: Address, pid: Hex, requestHash: Hex, claimsHash: Hex, salt: Hex): Hex {
  return keccak256(
    encodeAbiParameters(
      [{ type: "bytes32" }, { type: "uint256" }, { type: "address" }, { type: "bytes32" }, { type: "bytes32" }, { type: "bytes32" }],
      [TAGS.nonce, BigInt(chainId), contract, pid, bindingHash(requestHash, claimsHash), salt],
    ),
  );
}

/** Canonical request hash with the buyer's salt: method, path with
 * query, and body hash. Header canonicalization is not covered here. */
export function requestHash(method: string, pathAndQuery: string, body: Uint8Array, salt: Hex): Hex {
  return keccak256(
    encodeAbiParameters(
      [{ type: "bytes32" }, { type: "bytes32" }, { type: "string" }, { type: "string" }, { type: "bytes32" }],
      [TAGS.request, salt, method.toUpperCase(), pathAndQuery, keccak256(body)],
    ),
  );
}

/** Claims the request and the profile determine: the profile's input rule
 * and the requested method and path. */
export function claimsHash(inputRule: Hex, method: string, pathAndQuery: string): Hex {
  return keccak256(
    encodeAbiParameters(
      [{ type: "bytes32" }, { type: "bytes32" }, { type: "string" }, { type: "string" }],
      [TAGS.claims, inputRule, method.toUpperCase(), pathAndQuery],
    ),
  );
}

/** Responses are ABI-encoded words; pad is the identity on 32-byte
 * aligned data and other lengths are refused. */
export function pad(r: Uint8Array): Uint8Array {
  if (r.length % 32 !== 0) throw new Error("response is not 32-byte aligned");
  return r;
}

/** h_r = keccak256(tag || psi || pad(r)). */
export function responseHash(psi: Hex, r: Uint8Array): Hex {
  return keccak256(concatHex([TAGS.response, psi, bytesToHex(pad(r))]));
}

/** The plaintext of ct: psi || pad(r). */
export function plaintext(psi: Hex, r: Uint8Array): Uint8Array {
  return hexToBytes(concatHex([psi, bytesToHex(pad(r))]));
}

/** Keystream cipher: word j of ct is word j of pt xor keccak(k, nonce, j). */
export function encrypt(k: Hex, nonce: Hex, pt: Uint8Array): Uint8Array {
  if (pt.length % 32 !== 0) throw new Error("plaintext length");
  const out = new Uint8Array(pt.length);
  for (let j = 0; j < pt.length / 32; j++) {
    const ks = hexToBytes(keccak256(encodeAbiParameters([{ type: "bytes32" }, { type: "bytes32" }, { type: "uint256" }], [k, nonce, BigInt(j)])));
    for (let i = 0; i < 32; i++) out[32 * j + i] = pt[32 * j + i] ^ ks[i];
  }
  return out;
}

export const decrypt = encrypt;

/** keccak256(tag || Dec_k(ct)), the contract's decryptHash. */
export function decryptHash(k: Hex, nonce: Hex, ct: Uint8Array): Hex {
  if (ct.length % 32 !== 0) return ZERO32;
  return keccak256(concatHex([TAGS.response, bytesToHex(decrypt(k, nonce, ct))]));
}

export function keyHash(k: Hex): Hex {
  return keccak256(encodeAbiParameters([{ type: "bytes32" }], [k]));
}

/** U_n < v / V, as h * V < v * 2^256. */
export function sampledBy(value: bigint, nonce: Hex, v: bigint, cap: bigint): boolean {
  if (value === 0n || v >= cap) return true;
  const h = BigInt(keccak256(encodeAbiParameters([{ type: "uint256" }, { type: "bytes32" }], [value, nonce])));
  return (h * cap) >> 256n < v;
}
