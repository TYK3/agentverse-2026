"""Sweep the real B1 Scout descent offline: python tools/seed_sweep_b1.py --seeds 0-2.

Each isolated child runs sim.demo_descent to c1, checks no teleport and the
Responder's route over the measured map. This is not a Responder delivery test.
Reports and per-seed results go under runs/; exit non-zero on any failure/timeout.
"""

import argparse
import functools
import json
import os
import pathlib
import random
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.seed_sweep import seeds_from


def child(seed, max_t, out_dir):
    import numpy as np

    from sim import demo_descent
    from sim.levels import LevelWorld

    random.seed(seed)
    np.random.seed(seed)
    # run() has no seed argument. Bind the real world's seed in this child only;
    # seeding numpy alone would leave every LevelWorld's private generator at 0.
    demo_descent.LevelWorld = functools.partial(LevelWorld, seed=seed)
    result = demo_descent.run(max_t=max_t, floor='B1')
    checks = {
        'reached B1': bool(result['reached']),
        'descended L1 > ground > B1': result['levels'] == ['L1', 'ground', 'B1'],
        'no teleport': result['max_jump'] < 0.035,
        'Responder route spans L1 > B1': result['responder_route'] == 'ok'
        and tuple(result['route_k'] or ()) == (12, -12),
    }
    summary = {k: v for k, v in result.items() if k not in ('map', 'log', 'trail', 'trace')}
    summary.update(seed=seed, checks=checks)
    (out_dir / f'b1-{seed}.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(f"reached={result['reached']} sim={result['t']}s levels={'>'.join(result['levels'])} "
          f"max_jump={result['max_jump']} route={result['responder_route']}", flush=True)
    return 0 if all(checks.values()) else 1


def run_seed(seed, timeout, max_t, out_dir):
    command = [sys.executable, str(pathlib.Path(__file__).resolve()), '--child', '--seed', str(seed),
               '--max-t', str(max_t), '--out-dir', str(out_dir)]
    start = time.monotonic()
    result_path = out_dir / f'b1-{seed}.json'
    # A previous successful result must not survive a failed attempt.
    result_path.unlink(missing_ok=True)
    try:
        proc = subprocess.run(command, cwd=ROOT, env=dict(os.environ, GEMINI_MODE='off'),
                              capture_output=True, text=True, timeout=timeout, check=False)
        status, output = ('pass' if proc.returncode == 0 else 'fail'), proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        status = 'timeout'
        output = (exc.stdout or b'') + (exc.stderr or b'')
        output = output.decode(errors='replace') if isinstance(output, bytes) else output
    seconds = round(time.monotonic() - start, 2)
    (out_dir / f'b1-{seed}.log').write_text(output, encoding='utf-8')
    detail = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
    # An exit code alone is not evidence of a completed rescue.
    if status == 'pass' and (len(detail.get('checks', {})) != 4 or not all(detail['checks'].values())):
        status = 'fail'
    reason = (output.strip().splitlines() or ['no result'])[-1]
    return {'seed': seed, 'status': status, 'seconds': seconds, 'sim_seconds': detail.get('t'),
            'reason': reason, 'checks': detail.get('checks', {})}


def positive(value):
    number = float(value)
    if not 0 < number < float('inf'):
        raise argparse.ArgumentTypeError('must be a finite positive number')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--seeds', default='0,1,2,3,4', help='comma list or inclusive a-b range')
    parser.add_argument('--timeout', type=positive, default=600, help='wall seconds per seed')
    parser.add_argument('--max-t', type=positive, default=600, help='sim seconds per seed')
    parser.add_argument('--out-dir', type=pathlib.Path, default=ROOT / 'runs')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--seed', type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.out_dir = args.out_dir.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    os.environ['GEMINI_MODE'] = 'off'
    if args.child:
        return child(args.seed, args.max_t, args.out_dir)
    try:
        seeds = seeds_from(args.seeds)
        if not seeds or any(seed < 0 for seed in seeds) or len(set(seeds)) != len(seeds):
            raise ValueError('use distinct non-negative seeds')
    except ValueError as exc:
        parser.error(f'invalid --seeds: {exc}')
    results = []
    for seed in seeds:
        row = run_seed(seed, args.timeout, args.max_t, args.out_dir)
        results.append(row)
        sim_time = f"{row['sim_seconds']}s" if row['sim_seconds'] is not None else 'n/a'
        print(f"seed {seed}: {row['status'].upper()} wall={row['seconds']:.2f}s "
              f"sim={sim_time} {row['reason']}", flush=True)
    passed = sum(row['status'] == 'pass' for row in results)
    summary = f'B1: {passed}/{len(results)} passed ({passed / len(results):.0%}), GEMINI_MODE=off'
    print(summary)
    rows = ['# B1 seed sweep', '', summary, '',
            '| Seed | Result | Wall seconds | Sim seconds |', '|---|---|---|---|']
    rows.extend(f"| {r['seed']} | {r['status'].upper()} | {r['seconds']} | {r['sim_seconds']} |"
                for r in results)
    (args.out_dir / 'seed_sweep_b1.md').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    (args.out_dir / 'seed_sweep_b1.json').write_text(
        json.dumps({'passed': passed, 'total': len(results), 'results': results}, indent=2) + '\n',
        encoding='utf-8')
    print(f'reports: {args.out_dir / "seed_sweep_b1.md"} and seed_sweep_b1.json')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
