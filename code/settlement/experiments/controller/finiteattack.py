"""Finite attacks: a seller that cheats on m sales and then changes course, and the per-episode result columns.

The seller directive block (`directive`) names the number of cheated sales and what the seller
does afterwards:
- `serve_honestly`: it keeps selling and serves every later sale honestly;
- `stop_selling`: it refuses every new purchase; the sales it accepted are still served
  (redelivery, publication, anchors) as the contract requires;
- `request_exit`: it stops selling and, once its last cheated sale is delivered, requests the exit
  of its registration and of its bond account and finalizes each as soon as the contract admits
  it (services/seller/finite.go).

The seller counts sales in the order it accepts their payments. Without a failed settlement that
order is the settlement order, so the ground truth is the first m `Settled` purchases of the seller
(`ground_truth`); the seller's own record (`meta/attack.json`, `cheated`) is the cross-check.

An episode is one seller's attack in one run: its m cheated sales from the first settlement until
each of them has reached the seller or been lost to it (experiments/metrics.md). `episode` reduces
the per-sale outcomes the collector reads from the chain to the result columns:
- `finite_attack_detection`: `with_detection` when the seller's bond account had a confirmed
  failure (a final FAIL or UNSERVED case, or a claim window) caused by a cheated sale before the
  episode ended, otherwise `without_detection`; `open` when the run ended before the episode did;
- `seller_gain_released`: value of the cheated sales that reached the seller (Released, or
  releasable at the end of the run);
- `buyer_refund_amount`: value of the cheated sales repaid to their buyers (Refunded or paid from
  the frozen pool), and `buyer_refund_blocks`, per repaid cheated sale, blocks from its settlement
  to the repayment; `buyer_refund_owed` is what was still claimable when the run ended.
"""

AFTER = ('serve_honestly', 'stop_selling', 'request_exit')
COUNTS = 'sales in the order the seller accepts their payments'

# Financial states of contract-interface-v1 section 2 as the collector names them.
REACHED_SELLER = ('RELEASED', 'RELEASABLE')
REPAID = ('REFUNDED',)
OWED = ('REFUNDABLE', 'FROZEN_CLAIMABLE')
TERMINAL = ('RELEASED', 'REFUNDED', 'FORFEITED')
DETECTION_OUTCOMES = ('FAIL', 'UNSERVED')


def directive(cheat_sales, after):
    """Seller directive block of a finite attack."""
    if isinstance(cheat_sales, bool) or not isinstance(cheat_sales, int) or cheat_sales < 1:
        raise ValueError('cheat_sales must be a positive integer')
    if after not in AFTER:
        raise ValueError(f'after must be one of {AFTER}')
    return dict(cheat_sales=cheat_sales, after=after, counts=COUNTS)


def ground_truth(settled_nonces, cheat_sales):
    """The cheated sales: the first `cheat_sales` settled purchases of the seller, in settlement order."""
    return list(settled_nonces[:cheat_sales])


def episode(sales, cheated, run_end_block, confirmed_failure_block=None):
    """Result columns of one finite-attack episode.

    `sales` maps a nonce to its outcome: settled_block, value, financial_state (final state at the
    end of the run), case_outcome (FAIL, UNSERVED, PASS, INCONCLUSIVE or None), and, when the value
    left the deferred ledger, released_block or repaid_block. `cheated` lists the cheated nonces.
    `confirmed_failure_block` is the first confirmed failure of the seller's bond account, if any.
    """
    missing = [n for n in cheated if n not in sales]
    if missing:
        raise ValueError(f'cheated sales without an outcome: {missing}')
    rows = [dict(sales[n], nonce=n) for n in cheated]
    released = sum(int(r['value']) for r in rows if r['financial_state'] in REACHED_SELLER)
    repaid = [r for r in rows if r['financial_state'] in REPAID]
    owed = sum(int(r['value']) for r in rows if r['financial_state'] in OWED)
    refund_blocks = [int(r['repaid_block']) - int(r['settled_block']) for r in repaid]
    ended = all(r['financial_state'] in TERMINAL for r in rows)
    end_block = None
    if ended:
        end_block = max(int(r.get('released_block') or r.get('repaid_block') or r.get('forfeited_block')
                            or run_end_block) for r in rows)
    detected_by = [r['nonce'] for r in rows if r.get('case_outcome') in DETECTION_OUTCOMES]
    detected = bool(detected_by) and confirmed_failure_block is not None and (
        end_block is None or int(confirmed_failure_block) <= end_block)
    if detected:
        status = 'with_detection'
    elif ended:
        status = 'without_detection'
    else:
        status = 'open'
    return dict(
        finite_attack_detection=status,
        detected=detected,
        detection_block=int(confirmed_failure_block) if detected else None,
        detected_by=detected_by,
        cheated_sales=len(rows),
        episode_end_block=end_block,
        seller_gain_released=released,
        buyer_refund_amount=sum(int(r['value']) for r in repaid),
        buyer_refund_owed=owed,
        buyer_refund_blocks=refund_blocks,
        buyer_refund_blocks_max=max(refund_blocks) if refund_blocks else None,
    )


def rows(run_id, result):
    """Observation rows ({metric, value, observation_id}) of one episode."""
    return [dict(metric=k, value=result[k], observation_id=run_id)
            for k in ('finite_attack_detection', 'seller_gain_released', 'buyer_refund_amount',
                      'buyer_refund_blocks')]
