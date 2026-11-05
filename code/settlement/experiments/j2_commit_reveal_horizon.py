"""L_F and T_hold when the beacon delay is replaced by a commit-reveal window (journal J2).

The longest-path search of case_paths.py reads the blocks between the settlement of an epoch and
the sample opening from beaconDelayBlocks: seal deadline = 2*epochBlocks + anchorBlocks +
beaconDelayBlocks + sealBlocks. A commit-reveal source replaces beaconDelayBlocks by
commit_after + reveal blocks R, where commit_after is the part of the commit window that lies
after the anchor deadline A (0 when commits close at A, the design of FairBindCommitReveal).
The T_hold terms are the ones of rule D2-8: T_hold = L_F + keeper margin + waiting margin.

Run: python3 experiments/j2_commit_reveal_horizon.py [--keeper 500] [--waiting 3600]
"""
import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import case_paths  # noqa: E402
from controller import profile as prof  # noqa: E402


def longest(profile_name, delay):
    profile = prof.load_profile(case_paths.PROFILE_FILE, profile_name)
    profile = copy.deepcopy(profile)
    if delay is not None:
        profile['parameters']['beaconDelayBlocks'] = delay
    r = case_paths.analyse(profile)
    return r['longest'], r['caseHorizon']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', default='data-api-fast-v1')
    ap.add_argument('--keeper', type=int, default=500)
    ap.add_argument('--waiting', type=int, default=3600)
    ap.add_argument('--windows', type=int, nargs='*', default=[100, 300, 600])
    ap.add_argument('--commit-after', type=int, default=0, help='commit blocks after the anchor deadline')
    a = ap.parse_args()
    base_delay = prof._p(prof.load_profile(case_paths.PROFILE_FILE, a.profile))['beaconDelayBlocks']
    print(f'profile {a.profile}, keeper margin {a.keeper}, waiting margin {a.waiting}, '
          f'commit blocks after A = {a.commit_after}')
    print('source                      delay  L_F      T_hold   dL_F   dT_hold')
    rows = [('block hash (prototype)', base_delay)] + [(f'commit-reveal R={r}', r + a.commit_after) for r in a.windows]
    base = None
    for label, delay in rows:
        l_f, horizon = longest(a.profile, delay)
        t_hold = l_f + a.keeper + a.waiting
        if base is None:
            base = (l_f, t_hold)
        print(f'{label:<27} {delay:>5}  {l_f:>6}  {t_hold:>7}  {l_f - base[0]:>+6}  {t_hold - base[1]:>+7}')


if __name__ == '__main__':
    main()
