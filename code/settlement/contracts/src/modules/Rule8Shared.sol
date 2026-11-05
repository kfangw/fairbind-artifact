// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { ExchangeStore } from "./ExchangeStore.sol";
import { ExchangeShared } from "./ExchangeShared.sol";
import { Rule8Store } from "./Rule8Store.sol";

/// Code shared by the two rule edition 8 modules: the fee payment from the
/// profile fee pool, the copy of a profile seal into a seller's anchor
/// record, the held count, and the seller's anchor signature.
abstract contract Rule8Shared is ExchangeShared {
    /// Domain of a binding leaf b_n = H(position || beta_n) beside the nonce (rule D2-41 (c′)).
    bytes32 internal constant BIND_DOMAIN = keccak256("fairbind/rule8-bind/v1");
    bytes32 internal constant ANCHOR_TYPEHASH = keccak256(
        "FairBindAnchor(uint32 sellerId,uint32 profileId,uint24 epoch,uint32 count,bytes32 root,bytes32 root0,bytes32 publicationHash,uint32 units,bytes32 unitsHash)"
    );

    event R8FeePaid(uint32 indexed profileId, address indexed to, uint256 amount);
    event R8FeeOwed(uint32 indexed profileId, address indexed to, uint256 amount);
    event SignedAnchor(uint32 indexed sellerId, uint24 indexed epoch, address submitter, bytes32 contentHash);

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        ExchangeShared(token, gov, guard, treasury, rewardPool)
    { }

    /// Pays a fee from the pool in this transaction, or writes it to the
    /// queue of owed fees when the pool is short or owes earlier fees (rule
    /// D2-38 (b), (d)).
    function _r8PayFee(uint32 profileId, address to, uint256 amount) internal {
        if (amount == 0) return;
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (r8.pool[profileId] >= amount && r8.owedHead[profileId] == r8.owed[profileId].length) {
            r8.pool[profileId] -= amount;
            _transfer(to, amount);
            emit R8FeePaid(profileId, to, amount);
        } else {
            r8.owed[profileId].push(Rule8Store.Owed(to, uint96(amount)));
            emit R8FeeOwed(profileId, to, amount);
        }
    }

    /// The fee of a required call of kind `kind` to its caller (rule D2-38 (a)).
    function _fee(uint32 profileId, uint8 kind) internal {
        _r8PayFee(profileId, msg.sender, Rule8Store.layout().callFees[profileId][kind]);
    }

    /// Whether a purchase of a rule 8 profile is a sale (rule D2-39 (b″)):
    /// every purchase of an unsigned account; under receipt signatures a
    /// purchase bound by A_e. An epoch anchored with the bulk signature
    /// check (rule D2-41) marked its unbound purchases for refund in the
    /// anchor transaction, so there a sale is a purchase not so marked.
    function _r8Sale(bytes32 nonce, uint32 profileId, uint32 sellerId, uint24 epoch) internal view returns (bool) {
        if (_exchangeMode(profileId) == ExchangeStore.MODE_NONE) return true;
        if (Rule8Store.layout().sellerEpochs[sellerId][epoch].bindRoot != bytes32(0)) {
            return refundSources[nonce] != uint8(RefundSource.UNBOUND);
        }
        return _bound(nonce);
    }

    /// A seller epoch of a rule 8 profile is sealed when it is anchored and
    /// its profile epoch is sealed (rule D2-35 (b)); there is no seal of its
    /// own. The modules that read the sampling value from the anchor record
    /// take it from there, so this copies the profile epoch's value and
    /// checkpoint into the record once, and ends the record as EPOCH_FAILED
    /// when the profile epoch ended for a checkpoint shortage (rule D2-35
    /// (c)). The copy is a cache: it can only take the profile's values.
    /// Returns the record's state afterwards.
    function _r8Materialize(uint32 sellerId, uint24 epoch) internal returns (uint8) {
        AnchorView storage record = anchors[sellerId][epoch];
        if (record.state != uint8(EpochState.ANCHORED)) return record.state;
        Rule8Store.ProfileEpoch storage pe = Rule8Store.layout().profileEpochs[record.profileId][epoch];
        if (pe.state == Rule8Store.PE_FAILED) {
            record.state = uint8(EpochState.EPOCH_FAILED);
            emit EpochFailed(sellerId, epoch, uint8(EpochFailureReason.VERIFIER_SET_UNAVAILABLE));
            _epochResolved(sellerId, epoch);
            return record.state;
        }
        if (pe.state != Rule8Store.PE_SEALED) return record.state;
        record.randomness = pe.randomness;
        record.verifierSetHash = pe.setHash;
        record.totalEffectiveWeight = pe.weight;
        record.sortitionVersion = pe.version;
        record.state = uint8(EpochState.SEALED);
        emit EpochSealed(sellerId, epoch, pe.randomness, pe.setHash, pe.version, pe.weight);
        _epochResolved(sellerId, epoch);
        return record.state;
    }

    function _anchorStructHash(Rule8Store.AnchorContent calldata c) internal pure returns (bytes32) {
        return keccak256(abi.encode(ANCHOR_TYPEHASH, c));
    }

    /// Whether `sig` is the seller's signature of the content: its registered
    /// signing key, ecrecover first and ERC-1271 within g_1271 (rule D2-36 (a)).
    function _sellerSigned(uint32 sellerId, uint32 profileId, bytes32 structHash, bytes calldata sig)
        internal
        view
        returns (bool ok)
    {
        ExchangeStore.Terms storage t = _terms(profileId);
        (ok,) = _signedBy(sellers[sellerId].viewData.signingKey, _typed(profileId, structHash), sig, t.g1271, t.sigLimit);
    }
}
