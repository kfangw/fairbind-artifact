"""Design-2 rule switches of the settlement replay (design2_rules D2-1 .. D2-9).

Everything here is inert unless replay.py is run with `--design 2`. Values (v_max choices, hold
choices, detection floor, bond margin, k table, sales cap grid, chain block times) are read from
design2.json. The first edition of the rules is selectable (`edition=1`); the second edition is the
default.

- D2-1  amount cap v_max (the first edition called it tau): a settlement with value above it is
        rejected by the cap, before the bucket;
- D2-2/3  per-row sampling probability s_ppm(v) = min(PPM, ceil(v * PPM / v_max)) and its threshold;
- D2-5  unit deduction b = ceil((40/27) * v_max / p0) and unit bond B = k * b (second edition), the
        first edition's floor((40/27) * k * v_max / p0) stays selectable;
- D2-7  sales cap S on a grid (small buckets (q_S, r_S) and 3245 * n), chosen per address as the least
        cap that rejects nothing in a record (`CapPlan`); the burst multiplier of the first edition
        (`MultiplierPlan`) stays selectable;
- D2-8/9  holding period and the failure / inconclusive window lengths as one overlay of the profile,
        fixed windows aligned to absolute block 0, block times per chain.
"""
import json
from fractions import Fraction
from pathlib import Path

import numpy as np

from bucket import PPM, Bucket

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / 'design2.json'
SOURCES = ('prior14', 'cross', 'insample')
CAP_MODES = ('auto-zero-reject', 'prior14', 'cross', 'none')
EDITIONS = (1, 2)
# Option names of the first edition that the second edition renamed (the old name is still accepted).
LEGACY_OPTION_NAMES = {'--tau': '--vmax'}


def load_config(path=None):
    config = json.loads(Path(path or CONFIG_PATH).read_text(encoding='ascii'))
    if 'vmax_choices_usdc' not in config and 'tau_choices_usdc' in config:   # a first-edition file
        config['vmax_choices_usdc'] = config['tau_choices_usdc']
    return config


def vmax_atomic(text, decimals):
    """v_max as an exact integer in atomic units from a decimal USDC string; refuses a fraction of an atom."""
    value = Fraction(str(text)) * 10 ** decimals
    if value.denominator != 1 or value <= 0:
        raise ValueError(f'v_max {text} is not a positive whole number of atomic units')
    return int(value)


tau_atomic = vmax_atomic        # the first edition's name


def ceil_fraction(x):
    x = Fraction(x)
    return -((-x.numerator) // x.denominator)


def block_seconds_of(text):
    """A block (or slot) time in seconds as an exact fraction; refuses zero and negative values."""
    value = Fraction(str(text))
    if value <= 0:
        raise ValueError(f'block time {text} must be positive')
    return value


def decimal_text(x):
    """A fraction as a decimal string when it terminates (2, 0.4, 1.5), otherwise as a fraction."""
    from decimal import Decimal
    x = Fraction(x)
    if x.denominator == 1:
        return str(x.numerator)
    rest = x.denominator
    for p in (2, 5):
        while rest % p == 0:
            rest //= p
    return format(Decimal(x.numerator) / Decimal(x.denominator), 'f') if rest == 1 else str(x)


def seconds_to_blocks(seconds, block_seconds):
    """A duration in seconds as whole blocks, rounded up (a deadline is never shortened)."""
    return ceil_fraction(Fraction(seconds) / block_seconds)


def window_edges(lo, end, length, align):
    """Edges of the complete fixed windows of `length` blocks inside [lo, end]. 'absolute' puts the edges on
    multiples of `length` (windows aligned to block 0, D2-9); 'first-block' starts the first window at lo."""
    if align == 'absolute':
        first = -((-lo) // length) * length
    elif align == 'first-block':
        first = lo
    else:
        raise ValueError(f'unknown window alignment {align}')
    n = (end - first + 1) // length if end >= first else 0
    return first + length * np.arange(n + 1, dtype=np.int64)


def parse_margin(text):
    m = Fraction(str(text))
    if m < 1:
        raise ValueError('the multiplier margin must be at least 1')
    return m


# ---------------------------------------------------------------- D2-2 / D2-3

def s_ppm(values, tau):
    """min(PPM, ceil(v * PPM / tau)) in integer arithmetic (a value array or one integer)."""
    v = np.asarray(values, dtype=np.int64)
    out = np.minimum(PPM, -((-v * PPM) // tau))
    return out if isinstance(values, np.ndarray) else int(out)


def threshold_contract(ppm, top=2**256 - 1):
    """FairBindCore._probabilityThreshold (the function engine.probability_threshold mirrors):
    floor(2^256 * ppm / PPM); 2^256 - 1 at PPM."""
    if ppm == 0:
        return 0
    if ppm == PPM:
        return top
    return (top // PPM) * ppm + ((top % PPM + 1) * ppm) // PPM


def threshold_ceil(ppm):
    """ceil(ppm * 2^256 / PPM), the rounding design2_rules D2-3 writes."""
    return -((-ppm * 2**256) // PPM)


def threshold_of(ppm, rounding):
    if rounding == 'contract':
        return threshold_contract(ppm)
    if rounding == 'ceil':
        return threshold_ceil(ppm)
    raise ValueError(f'unknown threshold rounding {rounding}')


# ---------------------------------------------------------------- D2-5

def unit_bond(k, tau, p0_ppm, margin):
    """B2 = margin * k * tau / p0 as an integer (floor), with margin a Fraction."""
    return int(Fraction(margin) * k * tau * PPM / p0_ppm)


def unit_b(vmax, p0_ppm, margin):
    """b = ceil(margin * v_max * PPM / p0) in atomic units (D2-5 (b), margin 40/27): the deduction of one
    confirmed failure. Rounded up so that b >= v_max / p0 and the deduction floor(B / k) of a bond B = k * b
    is exactly b."""
    return ceil_fraction(Fraction(margin) * vmax * PPM / p0_ppm)


def unit_bond_b(k, vmax, p0_ppm, margin):
    """B = k * b (second edition of D2-5 (b))."""
    return k * unit_b(vmax, p0_ppm, margin)


def exposure_limit_atomic(tau, p0_ppm):
    """tau / p0 (the episode exposure limit), as a Fraction of atomic units."""
    return Fraction(tau * PPM, p0_ppm)


def penalty_floor2(tau, p0_ppm, rule):
    """expectedPenaltyFloor2. 'product': ceil(tau * PPM / p0_ppm) (2.5 tau, U7 first option);
    'ratio': tau * ceil(PPM / p0_ppm) (3 tau, the form the contract has today)."""
    if rule == 'product':
        return -((-tau * PPM) // p0_ppm)
    if rule == 'ratio':
        return tau * -((-PPM) // p0_ppm)
    raise ValueError(f'unknown floor rule {rule}')


# ---------------------------------------------------------------- D2-7 envelope multiplier

def all_admitted(local_blocks, capacity, refill_ppm, scale):
    """True when a bucket (capacity * scale, refill refill_ppm * scale per block) that starts full
    at the first block admits every settlement of `local_blocks` (sorted)."""
    if len(local_blocks) == 0:
        return True
    b = Bucket(capacity, refill_ppm, scale, int(local_blocks[0]))
    cap, rate = b.cap_ppm, refill_ppm * scale
    balance, updated = b.balance_ppm, b.updated_block
    for blk in local_blocks.tolist():
        level = balance + (blk - updated) * rate
        if level > cap:
            level = cap
        if level < PPM:
            return False
        balance, updated = level - PPM, blk
    return True


def fit_scale(blocks, capacity, refill_ppm):
    """n*(a) = max(1, least n for which the full bucket admits every settlement of `blocks`).
    The bucket condition is monotone in n, so the least n is found by bisection; n = ceil(m / q)
    always admits m settlements, which bounds the search."""
    blocks = np.sort(np.asarray(blocks, dtype=np.int64))
    m = len(blocks)
    if m == 0:
        return 1
    lo, hi = 1, max(1, -(-m // capacity))
    while lo < hi:
        mid = (lo + hi) // 2
        if all_admitted(blocks, capacity, refill_ppm, mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def envelope_scale_bruteforce(blocks, capacity, refill_ppm):
    """max over i <= j of ceil((j - i + 1) * PPM / (q * PPM + refill * (b_j - b_i))), at least 1: the
    closed form of the envelope condition (D2-7 (b)), O(m^2); used by the tests."""
    blocks = sorted(int(b) for b in blocks)
    best = 1
    for i in range(len(blocks)):
        for j in range(i, len(blocks)):
            num = (j - i + 1) * PPM
            den = capacity * PPM + refill_ppm * (blocks[j] - blocks[i])
            best = max(best, -(-num // den))
    return best


def margin_scale(n, margin):
    """n times the margin factor, rounded up."""
    return max(1, -((-n * margin.numerator) // margin.denominator))


class MultiplierPlan:
    """Per-address bond multiplier of the nE rule for one run.

    source 'prior14'   fit on the same address's records of the 14 days before the window
    source 'cross'     two-fold split of the window: the first half runs with the multiplier fitted on
                       the second half and the other way round (a bucket per half, each starts full)
    source 'insample'  fit on the replayed window itself (zero rejection by construction; a control)
    The records used are those with value at most tau (the others never reach the bucket). An address
    without a fitting record keeps n = 1; the margin factor applies to a fitted multiplier."""

    def __init__(self, source, margin, tau, prior=None, mid_block=None, first_block=None):
        if source not in SOURCES:
            raise ValueError(f'unknown multiplier source {source}')
        if source == 'prior14' and prior is None:
            raise ValueError('the prior-14-days source needs the prior settlement list')
        self.source, self.margin, self.tau = source, margin, tau
        self.prior, self.mid_block, self.first_block = prior, mid_block, first_block
        self.cache = {}

    @property
    def name(self):
        m = self.margin
        tag = f'-m{m.numerator}' if m.denominator == 1 else f'-m{float(m):g}'
        return f'nE-{self.source}{tag}'

    def _fit(self, blocks, values, q, refill_ppm):
        ok = values <= self.tau
        if not ok.any():
            return 1
        return margin_scale(fit_scale(blocks[ok], q, refill_ppm), self.margin)

    def scale(self, address, arrays, q, refill_ppm):
        """(scale for the bond, segments or None). segments: [(first block of the part, multiplier)]."""
        key = (address, q)
        if key in self.cache:
            return self.cache[key]
        blocks, values = arrays[0], arrays[1]
        if self.source == 'prior14':
            pb, pv = self.prior.per[address][0], self.prior.per[address][1]
            res = (self._fit(pb, pv, q, refill_ppm), None)
        elif self.source == 'insample':
            res = (self._fit(blocks, values, q, refill_ppm), None)
        else:
            first = blocks < self.mid_block
            n_first = self._fit(blocks[~first], values[~first], q, refill_ppm)  # first half uses the second half's fit
            n_second = self._fit(blocks[first], values[first], q, refill_ppm)
            res = (max(n_first, n_second), [(self.first_block, n_first), (self.mid_block, n_second)])
        self.cache[key] = res
        return res


# ---------------------------------------------------------------- D2-7 sales cap grid (second edition)

def small_bucket(S, main_S, main_capacity, lam):
    """(q_S, r_S ppm per block) of a sales cap S below the main cap (D2-7 (b)):
    q_S = max(1, round(S * q / S_main)) rounded half up, r_S = floor((S - q_S) * PPM / Lambda)."""
    q_s = max(1, (2 * S * main_capacity + main_S) // (2 * main_S))
    return q_s, ((S - q_s) * PPM) // lam


def cap_admits(S, q_s, r_s, lam):
    """The most settlements the bucket (q_s, r_s) admits in `lam` blocks: ceil(q_s + r_s * lam / PPM)."""
    return -((-(q_s * PPM + r_s * lam)) // PPM)


# ---------------------------------------------------------------- chains: time-denominated profile fields

PROFILE_BLOCK_FIELDS = ('epochBlocks', 'enforcementBlocks', 'deferBlocks', 'retentionBlocks', 'claimWindowBlocks',
                        'marginBlocks', 'beaconDelayBlocks', 'beaconSlackL1Blocks', 'failureWindowBlocks',
                        'inconclusiveWindowBlocks')
PROFILE_RATE_FIELDS = ('refillPpmPerBlock', 'maxRatePpmPerBlock')


def scale_profile_time(profile, reference_seconds, block_seconds):
    """A copy of the profile with every duration kept in seconds: blocks become
    ceil(blocks * reference / block time) and rates per block become floor(rate * block time / reference).
    Counts (bucketCapacity, minJudgedCount, maxAssignments) do not change. Identity for the reference chain."""
    out = json.loads(json.dumps(profile))
    reference_seconds, block_seconds = Fraction(reference_seconds), Fraction(block_seconds)
    if reference_seconds == block_seconds:
        return out

    def to_blocks(x):
        return seconds_to_blocks(Fraction(x) * reference_seconds, block_seconds)

    p = out['parameters']
    for key in PROFILE_BLOCK_FIELDS:
        if key in p:
            p[key] = to_blocks(p[key])
    for key in PROFILE_RATE_FIELDS:
        if key in p:
            p[key] = int(Fraction(p[key]) * block_seconds / reference_seconds)
    for key, value in p['deadlineConfig'].items():
        p['deadlineConfig'][key] = to_blocks(value)
    return out


# ---------------------------------------------------------------- D2-8 / D2-9 overlay

class Design2:
    """The resolved switches of one run.

    edition 2 (default): hold period = failure window = inconclusive window = L_F + 500 reference blocks
    (converted to the chain's block time), fixed windows aligned to block 0, b = ceil((40/27) v_max / p0),
    B = k(S) * b with k from the table of design2.json, threshold rounding ceil, and a sales cap
    (`sales_cap`: a grid value S or a mode of `CAP_MODES`) or, as a first-edition rule, a multiplier source.
    edition 1: the switches of the first edition (the hold periods listed in design2.json, one k, floor bond,
    windows from the first block, multiplier sources only)."""

    def __init__(self, config, op, *, vmax_usdc=None, tau_usdc=None, k=None, hold=None, failure_window=None,
                 source=None, margin='1', rounding=None, floor_rule='product', edition=2, bond_rule=None,
                 align=None, sales_cap=None, k_w=None, k_table=None, chain='base', block_seconds=None,
                 confirm_delay='case'):
        if edition not in EDITIONS:
            raise ValueError(f'unknown rule edition {edition}')
        self.config = config
        self.edition = edition
        if confirm_delay not in ('case', 'settlement'):
            raise ValueError(f'unknown confirmation delay {confirm_delay}')
        if edition == 1 and confirm_delay != 'case':
            raise ValueError('the confirmation delay sensitivity needs rule edition 2')
        self.confirm_delay = confirm_delay
        cfg2 = config['edition2']
        self.decimals = op['chain']['token_decimals']
        choices = config['vmax_choices_usdc']
        v = vmax_usdc if vmax_usdc is not None else tau_usdc
        if v is None or v not in choices:
            raise ValueError(f'v_max {v} is not one of {choices}')
        if chain not in config['chains']:
            raise ValueError(f'unknown chain {chain}; choose from {sorted(config["chains"])}')
        chain_cfg = config['chains'][chain]
        self.chain = chain
        self.block_seconds = block_seconds_of(block_seconds if block_seconds is not None else chain_cfg['block_seconds'])
        self.reference_seconds = Fraction(config['reference_block_seconds'])
        if edition == 1 and (chain != 'base' or self.block_seconds != self.reference_seconds):
            raise ValueError('edition 1 is defined for the reference chain only')
        self.f = self.reference_seconds / self.block_seconds           # blocks per reference block
        self.address_case = chain_cfg['address_case']
        # Hold period and windows.
        if edition == 2:
            ref_hold = seconds_to_blocks(Fraction(cfg2['hold_reference_blocks']) * self.reference_seconds,
                                         self.block_seconds)
            allowed_hold, default_hold = [ref_hold], ref_hold
        else:
            allowed_hold, default_hold = config['hold_choices_blocks'], config['hold_default_blocks']
        hold = default_hold if hold is None else hold
        if hold not in allowed_hold:
            raise ValueError(f'hold {hold} is not one of {allowed_hold}')
        failure_window = hold if failure_window is None else failure_window
        self.window_choices = [hold] if edition == 2 else list(config['failure_window_choices_blocks'])
        if failure_window not in self.window_choices:
            raise ValueError(f'failure window {failure_window} is not one of {self.window_choices}')
        # Rounding, floor rule, bond rule, alignment.
        rounding = rounding or (cfg2['threshold_rounding'] if edition == 2 else config['threshold_rounding']['default'])
        if rounding not in config['threshold_rounding']['choices']:
            raise ValueError(f'unknown threshold rounding {rounding}')
        if floor_rule not in config['floor_rule']['choices']:
            raise ValueError(f'unknown floor rule {floor_rule}')
        bond_rule = bond_rule or (cfg2['bond_rule'] if edition == 2 else config['bond_rule']['default'])
        if bond_rule not in config['bond_rule']['choices']:
            raise ValueError(f'unknown bond rule {bond_rule}')
        align = align or (cfg2['window_alignment'] if edition == 2 else config['window_alignment']['default'])
        if align not in config['window_alignment']['choices']:
            raise ValueError(f'unknown window alignment {align}')
        self.vmax_usdc = self.tau_usdc = v
        self.vmax = self.tau = vmax_atomic(v, self.decimals)
        self.hold, self.failure_window = hold, failure_window
        self.rounding, self.floor_rule, self.bond_rule, self.align = rounding, floor_rule, bond_rule, align
        self.p0_ppm = config['detect_floor_ppm']
        self.bond_margin = Fraction(*config['bond_margin'])
        self.lam = self.hold + self.failure_window       # Lambda of D2-7 (a)
        self.hour_blocks = int(round(Fraction(3600) / self.block_seconds))
        l_ref = cfg2['L_actual_blocks'] if edition == 2 else config['L_actual_blocks']
        self.l_actual = ceil_fraction(Fraction(l_ref) * self.f)
        # k per cap.
        sc = cfg2['sales_cap']
        self.main_S, self.main_capacity = sc['main_S'], sc['main_capacity']
        self.small_grid = list(sc['small_grid'])
        self.no_record_cap = sc['no_record_cap']
        self.refill_main = int(Fraction(sc['main_refill_ppm_per_block']) * self.block_seconds / self.reference_seconds)
        grid = self.small_grid + [self.main_S]
        self.k_w = None
        if k_table is not None:
            self.k_table = {int(s): int(x) for s, x in k_table.items()}
        elif k is not None:
            self.k_table = {s: int(k) for s in grid}
        elif edition == 2:
            kt = cfg2['k_table']
            self.k_w = k_w if k_w is not None else kt['default_w']
            if self.k_w not in kt['by_w']:
                raise ValueError(f'no k table for w = {self.k_w}; choose from {sorted(kt["by_w"])}')
            self.k_table = dict(zip(kt['S'], kt['by_w'][self.k_w]))
        else:
            self.k_table = {s: config['k_placeholder'] for s in grid}
        if sorted(self.k_table) != sorted(grid):
            raise ValueError(f'the k table must list exactly the caps {grid}')
        self.k = self.k_table[self.main_S]
        # Unit deduction b and the bond of the main cap.
        if bond_rule == 'integer-b':
            self.b = unit_b(self.vmax, self.p0_ppm, self.bond_margin)
            self.bond = unit_bond_b(self.k, self.vmax, self.p0_ppm, self.bond_margin)
        else:
            self.bond = unit_bond(self.k, self.vmax, self.p0_ppm, self.bond_margin)
            self.b = self.bond // self.k
        # Sales cap or multiplier source.
        self.sales_cap = self.source = None
        if sales_cap is not None:
            if edition == 1:
                raise ValueError('a sales cap needs rule edition 2')
            if source is not None:
                raise ValueError('a sales cap and a multiplier source exclude each other')
            if isinstance(sales_cap, str) and sales_cap.isdigit():
                sales_cap = int(sales_cap)
            if isinstance(sales_cap, int):
                self.cap_spec(sales_cap, 'fixed')            # validates the value
            elif sales_cap not in CAP_MODES:
                raise ValueError(f'sales cap {sales_cap} is neither a grid value nor one of {CAP_MODES}')
            self.sales_cap = sales_cap
            self.margin = parse_margin(margin)
            if self.margin != 1:
                raise ValueError('the multiplier margin applies to a multiplier source, not to a sales cap')
        else:
            src = source if source is not None else (config['multiplier']['default_source'] if edition == 1 else None)
            if src is None:
                raise ValueError('rule edition 2 needs a sales cap or a multiplier source')
            if src not in SOURCES:
                raise ValueError(f'unknown multiplier source {src}')
            self.source = src
            self.margin = parse_margin(margin)

    # ---- caps

    def cap_spec(self, S, method):
        """The bucket, k and bond of sales cap S: a grid value below the main cap, or n * main cap (n >= 1)."""
        if S in self.small_grid:
            n = 1
            capacity, refill = small_bucket(S, self.main_S, self.main_capacity, self.lam)
            k = self.k_table[S]
        elif S >= self.main_S and S % self.main_S == 0:
            n, capacity, refill = S // self.main_S, self.main_capacity, self.refill_main
            k = self.k_table[self.main_S]
        else:
            raise ValueError(f'sales cap {S} is not on the grid {self.small_grid} + {self.main_S} * n')
        if self.bond_rule == 'integer-b':
            unit, b = k * self.b, self.b
        else:
            unit = unit_bond(k, self.vmax, self.p0_ppm, self.bond_margin)
            b = unit // k
        return dict(S=S, n=n, capacity=capacity, refill_ppm=refill, scale=n, k=k, b=b, bond_unit=unit,
                    bond=n * unit, method=method)

    def multiplier_spec(self, n, method='multiplier'):
        """The cap record of a first-edition multiplier n (the main bucket scaled n times)."""
        return self.cap_spec(self.main_S * n, method)

    def allowed_window_lengths(self):
        return self.window_choices

    def describe(self):
        out = dict(rule_edition=self.edition, vmax_usdc=self.vmax_usdc, vmax_atomic=self.vmax,
                   tau_usdc=self.tau_usdc, tau_atomic=self.tau, k=self.k, unit_bond_atomic=self.bond,
                   unit_deduction_atomic=self.b, bond_rule=self.bond_rule,
                   k_table=self.k_table, k_w=self.k_w,
                   detect_floor_ppm=self.p0_ppm, bond_margin=list(self.config['bond_margin']),
                   hold_blocks=self.hold, failure_window_blocks=self.failure_window,
                   window_alignment=self.align,
                   multiplier_source=self.source, multiplier_margin=str(self.margin),
                   sales_cap=self.sales_cap, lambda_blocks=self.lam, confirm_delay=self.confirm_delay,
                   threshold_rounding=self.rounding, floor_rule=self.floor_rule,
                   chain=dict(name=self.chain, block_seconds=decimal_text(self.block_seconds),
                              reference_block_seconds=decimal_text(self.reference_seconds),
                              source=self.config['chains'][self.chain]['source'],
                              address_case=self.address_case, hour_blocks=self.hour_blocks),
                   L_actual_blocks=self.l_actual,
                   status='design value, not an admitted contract profile (retention below caseHorizon)')
        if self.sales_cap is not None:
            out['small_buckets'] = {str(S): dict(zip(('capacity', 'refill_ppm_per_block'),
                                                     small_bucket(S, self.main_S, self.main_capacity, self.lam)))
                                    for S in self.small_grid}
        return out

    def apply_profile(self, profile):
        """A copy of the profile with the design-2 parameters (the shared profile is untouched). For a chain
        other than the reference chain every duration is first converted from seconds to blocks."""
        out = scale_profile_time(profile, self.reference_seconds, self.block_seconds)
        p = out['parameters']
        p['maxPurchaseValue'] = str(self.vmax)
        p['maxBadGain'] = str(self.vmax)
        p['sampleScaleValue'] = str(self.vmax)
        p['samplePpm'] = PPM          # the rate at v = v_max; the per-row rate is s_ppm(v)
        p['effectivePpm'] = self.p0_ppm
        p['sellerPenalty'] = str(self.bond)
        p['failureLimit'] = self.k
        for key in ('deferBlocks', 'retentionBlocks', 'claimWindowBlocks'):
            p[key] = self.hold
        for key in ('failureWindowBlocks', 'inconclusiveWindowBlocks'):
            p[key] = self.failure_window
        return out

    def apply_op(self, op, name, profile2, case_horizon):
        """The operating point with the values the overlay changes (profile2 = apply_profile result)."""
        from controller import operating_point as opt
        from controller import profile as prof
        out = json.loads(json.dumps({k: v for k, v in op.items() if not k.startswith('_')}))
        for key in ('_sha256', '_path'):
            if key in op:
                out[key] = op[key]
        e = out['profiles'][name]
        p = profile2['parameters']
        ppm = op['chain']['ppm']
        e['g_atomic']['value'] = self.vmax
        e['v_atomic']['value'] = self.vmax
        e['pi']['value'] = p['samplePpm'] / ppm
        e['p_ceiling']['value'] = p['effectivePpm'] / ppm
        h, beta = e['h']['value'], e['beta']['value']
        e['p_ceiling']['bound'] = round(e['pi']['value'] * (h * (1 - beta)) ** 2, 4)
        e['hold_period_blocks']['value'] = max(p['deferBlocks'], p['retentionBlocks'])
        e['keeper_margin_blocks']['value'] = e['hold_period_blocks']['value'] - case_horizon
        e['failureLimit']['value'] = self.k
        e['g_over_p_atomic']['value'] = penalty_floor2(self.vmax, self.p0_ppm, self.floor_rule)
        # Values derived from the (possibly time-converted) profile and the longest measured path.
        e['L_blocks']['value'] = prof.judgment_delay(profile2)
        e['delta_F_blocks']['value'] = opt.freeze_delay(profile2)
        e['L_min_blocks']['value'] = opt.min_detection_delay(profile2)
        e['caseHorizon_blocks']['value'] = case_horizon
        e['lambda_max_per_block']['value'] = p['maxRatePpmPerBlock'] / ppm
        e['refill_per_block']['value'] = p['refillPpmPerBlock'] / ppm
        e['L_actual_blocks']['value'] = self.l_actual
        e['L_actual_blocks']['min'] = self.l_actual
        bt = self.block_seconds
        out['chain']['block_seconds'] = int(bt) if bt.denominator == 1 else float(bt)
        return out


# ---------------------------------------------------------------- D2-7 (second edition): the sales cap per address

class CapPlan:
    """Sales cap of every address for one run (D2-7 (b), decision 93).

    mode 'auto-zero-reject' (main result): per address the least grid cap that rejects nothing in the replayed
                            window itself; "the seller knows its demand"
    mode 'prior14'          (contrast): the same rule fitted on the same address's records of the 14 days before the
                            window; an address without a fitting record gets the least cap (10)
    mode 'cross'            two-fold split of the window; each half runs with the cap fitted on the other half
                            (a stand-in for the contrast when no earlier record exists); the account's cap is the
                            larger of the two
    an integer S            the same cap for every address (a fixed cap, no fitting)
    mode 'none'             (registration R11, rule edition 10 candidate v0.6: no count limit on settlements) no bucket:
                            every settlement that reaches admission is admitted; the record carries the main cap's
                            k and b for the bond columns and `unlimited=True`. auto-zero-reject is then the labelled
                            legacy variant (the bucket of edition 7). Needs the edition-10 release.

    The records used are those with value at most v_max (the others never reach the bucket). The grid is the
    small caps of design2.json followed by 3245 * n; the bucket condition is monotone in the cap, so the least
    cap is found in increasing order, and n by bisection (`fit_scale`)."""

    kind = 'cap'

    def __init__(self, d2, mode, prior=None, mid_block=None, first_block=None):
        if mode not in CAP_MODES and not isinstance(mode, int):
            raise ValueError(f'unknown sales cap mode {mode}')
        if mode == 'prior14' and prior is None:
            raise ValueError('the prior-14-days sales cap needs the prior settlement list')
        self.d2, self.mode = d2, mode
        self.prior, self.mid_block, self.first_block = prior, mid_block, first_block
        self.cache = {}

    @property
    def name(self):
        return f'cap-{self.mode}'

    def fit_S(self, blocks, values):
        """(S, method): the least grid cap that admits every record of `blocks` with value at most v_max."""
        d = self.d2
        ok = np.asarray(values) <= d.vmax
        if not ok.any():
            return d.no_record_cap, 'no-record'
        b = np.sort(np.asarray(blocks, dtype=np.int64)[ok])
        for S in d.small_grid:
            spec = d.cap_spec(S, 'fit')
            if all_admitted(b, spec['capacity'], spec['refill_ppm'], 1):
                return S, 'fit'
        return d.main_S * fit_scale(b, d.main_capacity, d.refill_main), 'fit'

    def scale(self, address, arrays, q, refill_ppm):
        """(cap record, segments or None). segments: [(first block of the part, scale, capacity, refill)]."""
        key = (address, q)
        if key in self.cache:
            return self.cache[key]
        d = self.d2
        if q != d.main_capacity:
            raise ValueError(f'the sales cap grid is defined for q = {d.main_capacity}, not {q}')
        blocks, values = arrays[0], arrays[1]
        segments = None
        if isinstance(self.mode, int):
            spec = d.cap_spec(self.mode, 'fixed')
        elif self.mode == 'none':
            spec = dict(d.cap_spec(d.main_S, 'none-unlimited'), unlimited=True)
        elif self.mode == 'auto-zero-reject':
            S, how = self.fit_S(blocks, values)
            spec = d.cap_spec(S, 'min-zero-insample' if how == 'fit' else 'no-record')
        elif self.mode == 'prior14':
            pb, pv = self.prior.per[address][0], self.prior.per[address][1]
            S, how = self.fit_S(pb, pv)
            spec = d.cap_spec(S, 'prior14' if how == 'fit' else 'prior14-no-record')
        else:
            first = blocks < self.mid_block
            S_first, _ = self.fit_S(blocks[~first], values[~first])    # the first half runs with the second half's cap
            S_second, _ = self.fit_S(blocks[first], values[first])
            parts = [d.cap_spec(S_first, 'cross'), d.cap_spec(S_second, 'cross')]
            spec = dict(max(parts, key=lambda s: s['S']), method='cross', S_parts=[S_first, S_second])
            segments = [(self.first_block, parts[0]['scale'], parts[0]['capacity'], parts[0]['refill_ppm']),
                        (self.mid_block, parts[1]['scale'], parts[1]['capacity'], parts[1]['refill_ppm'])]
        res = (spec, segments)
        self.cache[key] = res
        return res


def check(op, profile, design2):
    """Consistency of the operating point and the overlaid profile in the named design-2 mode of
    operating_point.check (negative keeper margin accepted, hold period against L_actual, window
    lengths from the config), plus D2-1 (maxPurchaseValue = maxBadGain = v_max) and D2-5 (e) (the unit
    bond is at least k times the exposure floor)."""
    from controller import operating_point as opt
    p = profile['parameters']
    errors = opt.check(op, profile, mode='design-2',
                       g_over_p=penalty_floor2(design2.vmax, design2.p0_ppm, design2.floor_rule),
                       window_lengths=design2.allowed_window_lengths())
    name = profile['name']
    if int(p['sellerPenalty']) < design2.k * penalty_floor2(design2.vmax, design2.p0_ppm, design2.floor_rule):
        errors.append(f'{name}: sellerPenalty is below k times the exposure floor')
    if int(p['maxPurchaseValue']) != design2.vmax or int(p['maxBadGain']) != design2.vmax:
        errors.append(f'{name}: maxPurchaseValue and maxBadGain must equal v_max')
    return errors


def keeper_notes(op, profile):
    """The keeper margin the design-2 mode accepts: negative against caseHorizon, and the slack over L_actual."""
    e = op['profiles'][profile['name']]
    return dict(keeper_margin_blocks=e['keeper_margin_blocks']['value'],
                keeper_slack_over_L_actual_blocks=e['hold_period_blocks']['value'] - e['L_actual_blocks']['value'],
                note='design-2 mode: a hold period below caseHorizon is intended; the margin to the longest measured path is the slack')


def parse_k(text):
    """--d2-k: None, one integer (the same k for every cap), or 'S:k,S:k,...' (a table). Returns (k, k_table)."""
    if text is None:
        return None, None
    text = str(text).strip()
    if text.isdigit():
        return int(text), None
    table = {}
    for part in text.split(','):
        s, _, k = part.partition(':')
        if not (s.strip().isdigit() and k.strip().isdigit()):
            raise ValueError(f'--d2-k {text!r}: expected an integer or S:k pairs')
        table[int(s)] = int(k)
    return None, table
