"""Exact mirror of the bond account's token bucket (FairBindCore._refilledBucket and
_consumeBucket, FairBindBond.registerBond).

All arithmetic is integer and block based, as in the contract:

    cap     = bucketCapacity * scaleFactor * PPM
    refill  = (block - bucketUpdatedBlock) * refillPpmPerBlock * scaleFactor
    level   = min(cap, bucketBalancePpm + refill)
    settle  : level < PPM -> RateLimitExceeded (state unchanged, the call reverts)
              otherwise bucketBalancePpm = level - PPM, bucketUpdatedBlock = block

A new bond starts with a full bucket at its scale; _rescale in registerBond sets
bucketUpdatedBlock to the registration block. maxRatePpmPerBlock is not read by
settle; it only bounds the profile (FairBindCore._validateProfile).
"""

PPM = 1_000_000


class Bucket:
    __slots__ = ('capacity', 'refill_ppm', 'scale', 'balance_ppm', 'updated_block', 'cap_ppm')

    def __init__(self, capacity, refill_ppm, scale, registered_block):
        for name, value in (('capacity', capacity), ('refill_ppm', refill_ppm), ('scale', scale),
                            ('registered_block', registered_block)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f'{name} must be a non-negative integer')
        if capacity == 0 or scale == 0:
            raise ValueError('capacity and scale must be positive')
        self.capacity = capacity
        self.refill_ppm = refill_ppm
        self.scale = scale
        self.cap_ppm = capacity * scale * PPM
        self.balance_ppm = self.cap_ppm
        self.updated_block = registered_block

    def level(self, block):
        """_refilledBucket at `block` (the view the contract computes before consuming)."""
        if block < self.updated_block:
            raise ValueError('block before the last bucket update')
        balance = self.balance_ppm + (block - self.updated_block) * self.refill_ppm * self.scale
        return self.cap_ppm if balance > self.cap_ppm else balance

    def consume(self, block):
        """One settle at `block`. Returns True when admitted, False on RateLimitExceeded."""
        level = self.level(block)
        if level < PPM:
            return False
        self.balance_ppm = level - PPM
        self.updated_block = block
        return True


def profile_admits_capacity(profile_parameters, capacity):
    """The FairBindCore._validateProfile rate check for a profile whose bucketCapacity is
    `capacity`: bucketCapacity * PPM + refill * enforcementBlocks <= maxRate * enforcementBlocks."""
    p = profile_parameters
    return (capacity * PPM + p['refillPpmPerBlock'] * p['enforcementBlocks']
            <= p['maxRatePpmPerBlock'] * p['enforcementBlocks'])
