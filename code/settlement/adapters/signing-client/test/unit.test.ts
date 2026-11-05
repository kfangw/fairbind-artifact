import { test } from "node:test";
import assert from "node:assert/strict";
import { keccak256, toHex, type Hex } from "viem";
import { decryptHash, encrypt, decrypt, keyHash, levels, merklePath, node, pad, plaintext, responseHash, sampledBy, profileId, type Profile } from "../src/hashing.ts";
import { SigningClient } from "../src/client.ts";

const h = (s: string): Hex => keccak256(toHex(s));

test("pad refuses unaligned responses and keeps aligned ones", () => {
  assert.throws(() => pad(new Uint8Array(33)));
  assert.equal(pad(new Uint8Array(64)).length, 64);
});

test("encryption round trip and decryptHash against h_r", () => {
  const psi = h("psi");
  const r = new Uint8Array(96).fill(3);
  const pt = plaintext(psi, r);
  const k = h("k");
  const n = h("n");
  const ct = encrypt(k, n, pt);
  assert.deepEqual(decrypt(k, n, ct), pt);
  assert.equal(decryptHash(k, n, ct), responseHash(psi, r));
  assert.notEqual(decryptHash(h("other"), n, ct), responseHash(psi, r));
  assert.notEqual(keyHash(k), keyHash(h("other")));
});

test("Merkle paths rebuild the root, odd widths included", () => {
  for (const w of [1, 2, 3, 5, 8]) {
    const leaves = Array.from({ length: w }, (_, i) => h(`leaf ${i}`));
    const lv = levels(leaves);
    const root = lv.at(-1)![0];
    for (let i = 0; i < w; i++) {
      let x = leaves[i];
      let idx = i;
      for (const sib of merklePath(lv, i)) {
        x = idx % 2 === 0 ? node(x, sib) : node(sib, x);
        idx >>= 1;
      }
      assert.equal(x, root, `width ${w} index ${i}`);
    }
  }
});

test("sampling: v >= V or no value means sampled", () => {
  assert.equal(sampledBy(0n, h("n"), 1n, 10n), true);
  assert.equal(sampledBy(5n, h("n"), 10n, 10n), true);
  let hits = 0;
  for (let i = 0; i < 400; i++) if (sampledBy(BigInt(i + 1), h("n"), 1n, 4n)) hits++;
  assert.ok(hits > 50 && hits < 150, `about a quarter sampled, got ${hits}`);
});

test("price cap for the reserve never goes below p_floor", () => {
  const p = { maxFeePerGas: 0n } as Profile;
  assert.equal(SigningClient.effectivePriceCap(p, 10n ** 9n), 10n ** 9n);
  assert.equal(SigningClient.effectivePriceCap({ ...p, maxFeePerGas: 5n * 10n ** 9n }, 10n ** 9n), 5n * 10n ** 9n);
});

test("profile id changes with every field", () => {
  const base: Profile = { account: "0x0000000000000000000000000000000000000001", receiptKey: "0x0000000000000000000000000000000000000002", unitKey: "0x0000000000000000000000000000000000000003", verifier: "0x0000000000000000000000000000000000000004", codeHash: h("c"), tier: 1, flags: 0, cap: 1n, minAmount: 1n, responseDeadline: 0, deposit: 1n, maxFeePerGas: 1n, epochMultiple: 1, inputRule: h("r") };
  const id = profileId(base);
  assert.notEqual(profileId({ ...base, account: "0x0000000000000000000000000000000000000009" }), id);
  assert.notEqual(profileId({ ...base, responseDeadline: 1 }), id);
  assert.notEqual(profileId({ ...base, maxFeePerGas: 2n }), id);
  assert.notEqual(profileId({ ...base, epochMultiple: 2 }), id);
  assert.notEqual(profileId({ ...base, minAmount: 2n }), id);
});
