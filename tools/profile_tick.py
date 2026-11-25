#!/usr/bin/env python3
"""Profile chosen ticks of the Python strategy without touching main.py or my_strategy.py.

Run it instead of main.py, against a runner waiting on a TCP seat:

    python3 tools/profile_tick.py --ticks 500             # one tick
    python3 tools/profile_tick.py --ticks 100 800         # two ticks, to compare
    python3 tools/profile_tick.py --ticks 400-409         # ten ticks summed into one profile
    python3 tools/profile_tick.py --ticks 500 -- 127.0.0.1 31002   # host port [token], as main.py takes

For every group in --ticks it saves <out>/tick_<group>.prof (pstats / snakeviz / tuna) and prints
its top functions to stderr. Every tick's answer time goes to <out>/ticks.csv (profiled ticks
are marked: cProfile itself slows them down).
"""
import argparse
import cProfile
import csv
import os
import pstats
import sys
import time

PYTHON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python')
sys.path.insert(0, os.path.abspath(PYTHON_DIR))

import main  # noqa: E402  the client's Runner
from my_strategy import MyStrategy  # noqa: E402


def parse_groups(specs):
    groups = []
    for spec in specs:
        if '-' in spec:
            lo, hi = (int(x) for x in spec.split('-', 1))
            groups.append((spec, set(range(lo, hi + 1))))
        else:
            groups.append((spec, {int(spec)}))
    return groups


def main_():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ticks', nargs='+', required=True, help='ticks to profile: N or A-B (inclusive)')
    ap.add_argument('--sort', default='tottime', help='pstats sort key for the printout (tottime, cumulative, ncalls)')
    ap.add_argument('--top', type=int, default=20, help='how many functions to print per group')
    ap.add_argument('--out', default='profiles', help='directory for the .prof files and ticks.csv')
    ap.add_argument('runner_args', nargs='*', help='host port [token], passed on as main.py takes them')
    args = ap.parse_args()

    groups = parse_groups(args.ticks)
    profiles = {name: cProfile.Profile() for name, _ in groups}
    tick_to_group = {}
    for name, ticks in groups:
        for t in ticks:
            tick_to_group[t] = name
    times = []  # (tick, ms, profiled)
    reached = set()  # groups that profiled at least one tick

    original = MyStrategy.get_action

    def get_action(self, player_view, debug_interface):
        tick = player_view.current_tick
        group = tick_to_group.get(tick)
        prof = profiles[group] if group else None
        start = time.perf_counter()
        if prof:
            reached.add(group)
            prof.enable()
        try:
            return original(self, player_view, debug_interface)
        finally:
            if prof:
                prof.disable()
            times.append((tick, (time.perf_counter() - start) * 1000, bool(prof)))

    MyStrategy.get_action = get_action

    r = args.runner_args
    host = r[0] if len(r) > 0 else '127.0.0.1'
    port = int(r[1]) if len(r) > 1 else 31001
    token = r[2] if len(r) > 2 else '0000000000000000'

    try:
        main.Runner(host, port, token).run()
    finally:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, 'ticks.csv'), 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['tick', 'ms', 'profiled'])
            w.writerows((t, f'{ms:.3f}', int(p)) for t, ms, p in times)
        for name, _ in groups:
            if name not in reached:
                print(f'\n=== tick {name}: not reached ===', file=sys.stderr)
                continue
            prof = profiles[name]
            path = os.path.join(args.out, f'tick_{name}.prof')
            prof.dump_stats(path)
            stats = pstats.Stats(path, stream=sys.stderr)
            print(f'\n=== tick {name} -> {path} ===', file=sys.stderr)
            stats.strip_dirs().sort_stats(args.sort).print_stats(args.top)
        if times:
            worst = max(times, key=lambda x: x[1])
            print(f'{len(times)} ticks answered; slowest: tick {worst[0]}, {worst[1]:.1f} ms'
                  f'{" (profiled)" if worst[2] else ""}; per-tick times in {args.out}/ticks.csv', file=sys.stderr)


if __name__ == '__main__':
    main_()
