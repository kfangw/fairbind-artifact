"""Checks a C1 collection data directory.

Structural checks never parse a judgment record: its bytes are only hashed
against the cell manifest. `--deep` re-derives every judgment from its
evidence with `c1tool rederive` and prints counts only; it is refused while
the collection is still open unless explicitly allowed.
"""
import datetime
import json
import subprocess
from pathlib import Path

from collector import (FORMAT_CELL, FORMAT_CONTROLLER, FORMAT_DISCARD, SELLERS, END_REASONS, build_lists,
                       file_sha, type_strata)

DISCARD_REASONS = ('interrupted', 'machine_sleep', 'network', 'other')


class Replay:
    """Re-runs the list consumption of collector.Collector.assign from the
    controller records, to show that every list position was used once."""

    def __init__(self, cfg, lists):
        self.cfg, self.lists = cfg, lists
        self.grid = cfg['collection']['grid_seconds']
        self.back = {s['type']: s.get('cells_back') for s in type_strata(cfg)}
        self.st = {'role_pos': {s: 0 for s in SELLERS}, 'type_pos': 0, 'deferred': [],
                   'honest': {s: 0 for s in SELLERS}, 'wrong': {s: 0 for s in SELLERS}, 'types_assigned': 0,
                   'successes': {s: set() for s in SELLERS}}

    def eligible(self, typ, src, t, no_adaptive):
        b = self.back.get(typ)
        if b is not None:
            return t - b * self.grid in self.st['successes'][src]
        return not (typ == 'D-adaptive' and no_adaptive)

    def next_type(self, src, t, no_adaptive=False):
        st = self.st
        for k, d in enumerate(st['deferred']):
            if self.eligible(d, src, t, no_adaptive):
                st['deferred'].pop(k)
                return d
        types = self.lists['types']
        while st['type_pos'] < len(types):
            d = types[st['type_pos']]
            st['type_pos'] += 1
            if self.eligible(d, src, t, no_adaptive):
                return d
            st['deferred'].append(d)
        return None

    def cell(self, t, ctl, problems):
        st = self.st
        generator_failed = False
        for e in ctl['captures']:
            src = e['source_id']
            if (e.get('capture') or {}).get('stage') != 'ok':
                if e.get('role') is not None:
                    problems.append(f'{t}: {src}: role given to a failed capture')
                continue
            roles = self.lists['roles'][src]
            if st['role_pos'][src] < len(roles):
                want = roles[st['role_pos'][src]]
                if e.get('role_list_index') != st['role_pos'][src]:
                    problems.append(f'{t}: {src}: role list index {e.get("role_list_index")}, expected {st["role_pos"][src]}')
                st['role_pos'][src] += 1
            else:
                want = 'wrong'
            if e.get('role') != want:
                problems.append(f'{t}: {src}: role {e.get("role")}, expected {want}')
            st['successes'][src].add(t)
            if want == 'honest':
                st['honest'][src] += 1
                continue
            typ = self.next_type(src, t, generator_failed)
            if e.get('adaptive_deferred'):
                if typ != 'D-adaptive':
                    problems.append(f'{t}: {src}: adaptive deferral without an adaptive type')
                st['deferred'].insert(0, typ)
                generator_failed = True
                typ = self.next_type(src, t, True)
            if typ is None:
                if e.get('type') is not None or not e.get('unused'):
                    problems.append(f'{t}: {src}: expected an unused capture')
                continue
            if e.get('type') != typ:
                problems.append(f'{t}: {src}: type {e.get("type")}, expected {typ}')
            st['wrong'][src] += 1
            st['types_assigned'] += 1


def run_tool(tool, args, dirs, batch=200):
    total, problems = 0, []
    for k in range(0, len(dirs), batch):
        p = subprocess.run([tool] + args + [str(d) for d in dirs[k:k + batch]], capture_output=True, text=True)
        try:
            out = json.loads(p.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return total, problems + [f'{args[0]}: no result ({p.stderr.strip()[-200:]})']
        total += out.get('objects', out.get('judgments_rederived', 0))
        problems += out.get('problems') or []
    return total, problems


def verify_data(data, deep=False, allow_open=False, out=print):
    problems = []
    col = json.loads((data / 'collection.json').read_text())
    cfg = col['config']
    grid = cfg['collection']['grid_seconds']
    lists, lsha = build_lists(cfg)
    if lsha != col['lists_sha256']:
        problems.append('seeded lists differ from the collection record')
    if (data / 'plan' / 'lists.json').exists() and json.loads((data / 'plan' / 'lists.json').read_text()) != lists:
        problems.append('plan/lists.json differs from the seeded lists')
    st = json.loads((data / 'state.json').read_text()) if (data / 'state.json').exists() else None
    cells = []
    for day in sorted((data / 'cells').glob('*')) if (data / 'cells').exists() else []:
        for c in sorted(day.iterdir()):
            if not c.name.isdigit():
                problems.append(f'unexpected entry {c}')
                continue
            t = int(c.name)
            d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime('%Y-%m-%d')
            if t % grid or d != day.name:
                problems.append(f'{c}: not on the grid or in the wrong day directory')
            cells.append((t, c))
    cells.sort()
    ts = [t for t, _ in cells]
    if len(ts) != len(set(ts)):
        problems.append('a grid time is complete more than once')
    replay = Replay(cfg, lists)
    object_dirs, judgment_files = [], []
    total_bytes, requests = 0, 0
    for t, c in cells:
        mp = c / 'manifest.json'
        if not mp.exists():
            problems.append(f'{t}: manifest missing')
            continue
        man = json.loads(mp.read_text())
        if man.get('format') != FORMAT_CELL or man.get('reference_time') != t:
            problems.append(f'{t}: manifest format or time')
        files = man.get('files', {})
        present = {p.relative_to(c).as_posix() for p in c.rglob('*') if p.is_file()} - {'manifest.json'}
        if present != set(files):
            problems.append(f'{t}: files differ from the manifest: {sorted(present ^ set(files))[:5]}')
        for rel, meta in files.items():
            p = c / rel
            if p.exists() and (p.stat().st_size != meta['bytes'] or file_sha(p) != meta['sha256']):
                problems.append(f'{t}: {rel}: hash or size mismatch')
            total_bytes += meta['bytes']
        total_bytes += mp.stat().st_size
        for req in ('controller.json', 'requests.log', 'instance-1/judgment.json', 'instance-2/judgment.json',
                    'instance-3/judgment.json'):
            if req not in files:
                problems.append(f'{t}: {req} missing')
        ctl = json.loads((c / 'controller.json').read_text())
        if ctl.get('format') != FORMAT_CONTROLLER or ctl.get('reference_time') != t or \
                [e['source_id'] for e in ctl.get('captures', [])] != SELLERS:
            problems.append(f'{t}: controller record format, time or seller order')
            continue
        for e in ctl['captures']:
            f = (e.get('capture') or {}).get('object_file')
            if f and f'seller/{f}' not in files:
                problems.append(f'{t}: seller object {f} missing')
        requests += ctl.get('http_requests', 0)
        replay.cell(t, ctl, problems)
        for sub in ['seller', 'generator', 'instance-1', 'instance-2', 'instance-3']:
            if (c / sub).is_dir():
                object_dirs.append(c / sub)
        judgment_files += [c / f'instance-{i}' / 'judgment.json' for i in (1, 2, 3)]
    discarded = []
    for p in sorted((data / 'discarded').glob('*.json')) if (data / 'discarded').exists() else []:
        rec = json.loads(p.read_text())
        if rec.get('format') != FORMAT_DISCARD or rec.get('reason') not in DISCARD_REASONS:
            problems.append(f'{p.name}: discard record format or reason')
        discarded.append(rec['reference_time'])
        if rec['reference_time'] in set(ts):
            problems.append(f'{rec["reference_time"]}: both complete and discarded')
    if st is not None:
        r = replay.st
        for key in ('role_pos', 'type_pos', 'honest', 'wrong', 'types_assigned', 'deferred'):
            if r[key] != st[key]:
                problems.append(f'state {key} {st[key]} differs from the replay {r[key]}')
        if st['complete_cells'] != len(cells):
            problems.append(f'state counts {st["complete_cells"]} complete cells, found {len(cells)}')
        if st['discarded_cells'] != len(discarded):
            problems.append(f'state counts {st["discarded_cells"]} discarded cells, found {len(discarded)}')
        if cells and st['last_complete_t'] != cells[-1][0]:
            problems.append('state last complete cell differs from the newest cell')
        sessions = st['sessions'] + ([st['current_session']] if st.get('current_session') else [])
        if sum(s['complete_cells'] for s in sessions) != len(cells):
            problems.append('session complete counts do not add up')
        if sum(s['discarded_cells'] for s in sessions) > len(discarded):
            problems.append('session discarded counts exceed the discarded cells')
        for s in st['sessions']:
            if s.get('end_reason') not in END_REASONS:
                problems.append(f'session {s["id"]}: end reason {s.get("end_reason")}')
    tool = col['tools']['c1tool']
    roots = ['-roots', col['roots']] if col.get('roots') else []
    nobj, p2 = run_tool(tool, ['objects'] + roots, object_dirs)
    problems += p2
    out(f'complete cells: {len(cells)}')
    out(f'discarded cells: {len(discarded)}')
    out(f'raw objects verified: {nobj}')
    out(f'bytes in complete cells: {total_bytes}' + (f' ({total_bytes // len(cells)} per cell)' if cells else ''))
    out(f'HTTP requests in complete cells: {requests}')
    if deep:
        complete = st is not None and (st.get('stopped') or {}).get('reason') == 'collection_complete'
        if not complete and not allow_open:
            problems.append('--deep refused: the collection is open (judgment records stay closed until it ends)')
        else:
            n, p3 = run_tool(tool, ['rederive'] + roots, judgment_files, batch=100)
            problems += p3
            out(f'judgment records well-formed and re-derived: {len(judgment_files) - len(p3)} of '
                f'{len(judgment_files)} ({n} judgments)')
    out(f'problems: {len(problems)}')
    for p in problems[:50]:
        out('  ' + p)
    return 0 if not problems else 1
