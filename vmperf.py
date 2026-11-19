#!/usr/bin/env python3
"""Run Linux guest benchmarks or compare two saved runs."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from statistics import median
import subprocess
import tempfile

STORAGE = {'seq-read': ('read', '1m', 8), 'seq-write': ('write', '1m', 8),
           'rand-read': ('randread', '4k', 1)}
NETWORK = ('tcp-send', 'tcp-receive')
METRICS = {'seq-read': ('MiB/s',), 'seq-write': ('MiB/s',),
           'rand-read': ('IOPS', 'p95 ms', 'p99 ms'),
           **{name: ('Mbps',) for name in NETWORK}}


def capture(command):
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def measure(command, directory, name, timeout):
    print(name, flush=True)
    with (directory / (name + '.json')).open('w') as out, (directory / (name + '.stderr')).open('w') as err:
        try:
            return subprocess.run(command, stdout=out, stderr=err, timeout=timeout).returncode == 0
        except subprocess.TimeoutExpired:
            print('Timed out', file=err)
            return False


def run(args):
    scratch = args.scratch.resolve(strict=True)
    mount = json.loads(capture(['findmnt', '-J', '-T', str(scratch), '-o', 'TARGET,SOURCE,FSTYPE']))['filesystems'][0]
    if mount['fstype'] in ('tmpfs', 'ramfs'):
        raise ValueError('Scratch must be disk-backed')
    if mount['target'] == '/' and not args.allow_root_volume:
        raise ValueError('Use a dedicated scratch mount, or explicitly select the root volume with --allow-root-volume')
    if shutil.disk_usage(scratch).free < (args.size_mib + 1024) * 2**20:
        raise ValueError('Scratch needs the test file size plus 1 GiB free')
    versions = {tool: capture([tool, '--version']).splitlines()[0] for tool in ('fio', 'iperf3')}
    if not versions['fio'].startswith('fio-'):
        raise ValueError('fio must be the Flexible I/O Tester')
    settings = {key: getattr(args, key) for key in ('peer', 'port', 'size_mib', 'reps', 'storage_seconds', 'storage_warmup', 'network_seconds', 'network_warmup')}
    settings.update(profile=1, versions=versions)
    args.out.mkdir(parents=True)
    manifest = dict(vm=args.vm, phase=args.phase, settings=settings, mount=mount,
                    timestamp=datetime.now(timezone.utc).isoformat(), host=capture(['hostname']),
                    route=capture(['ip', 'route', 'get', args.peer]), commands={}, success={})

    def save():
        (args.out / 'run.json').write_text(json.dumps(manifest, indent=2) + '\n')

    def execute(command, name, timeout):
        manifest['commands'][name] = command
        ok = measure(command, args.out, name, timeout)
        manifest['success'][name] = ok
        save()
        return ok

    save()
    with tempfile.TemporaryDirectory(prefix='vmperf-', dir=scratch) as directory:
        # cwd-independent fio filename; escape fio's colon-separated filename syntax.
        filename = str(Path(directory) / 'scratch').replace(':', r'\:')
        fio = ['fio', '--output-format=json', '--ioengine=libaio', '--direct=1',
               '--numjobs=1', '--refill_buffers=1', f'--filename={filename}', f'--size={args.size_mib}m']
        initialized = execute(fio + ['--name=prepare', '--rw=write', '--bs=1m', '--iodepth=8', '--end_fsync=1'], 'prepare', 300)
        if initialized:
            for rep in range(1, args.reps + 1):
                for name, (rw, bs, depth) in STORAGE.items():
                    execute(fio + [f'--name={name}', f'--rw={rw}', f'--bs={bs}', f'--iodepth={depth}',
                                   '--allow_file_create=0', '--time_based', f'--runtime={args.storage_seconds}',
                                   f'--ramp_time={args.storage_warmup}'], f'{name}-{rep}',
                            args.storage_seconds + args.storage_warmup + 60)
    for rep in range(1, args.reps + 1):
        for name in NETWORK:
            cmd = ['iperf3', '-c', args.peer, '-p', str(args.port), '-J', '-P', '1',
                   '-t', str(args.network_seconds), '-O', str(args.network_warmup)]
            if name == 'tcp-receive':
                cmd.append('-R')
            execute(cmd, f'{name}-{rep}', args.network_seconds + args.network_warmup + 30)
    return report(args.out)


def samples(directory, manifest, name):
    values = []
    for rep in range(1, manifest['settings']['reps'] + 1):
        key = f'{name}-{rep}'
        if not manifest['success'].get(key):
            continue
        try:
            raw = json.loads((directory / (key + '.json')).read_text())
            if name in NETWORK:
                if not raw.get('error'):
                    values.append((raw['end']['sum_received']['bits_per_second'] / 1e6,))
            else:
                job = raw['jobs'][0]
                if job['error']:
                    continue
                io = job['write' if name == 'seq-write' else 'read']
                if name == 'rand-read':
                    percentiles = io['clat_ns']['percentile']
                    values.append((io['iops'], percentiles['95.000000'] / 1e6,
                                   percentiles['99.000000'] / 1e6))
                else:
                    values.append((io['bw_bytes'] / 2**20,))
        except (ValueError, OSError, LookupError, TypeError):
            continue
    return values


def report(baseline, candidate=None, verbose=False):
    paths = [baseline] if candidate is None else [baseline, candidate]
    manifests = [json.loads((path / 'run.json').read_text()) for path in paths]
    comparable = len(paths) == 1 or (manifests[0]['vm'] == manifests[1]['vm'] and
                                    manifests[0]['settings'] == manifests[1]['settings'])
    headers = ['Profile', 'Metric', *(m['phase'] for m in manifests)]
    if candidate is not None:
        headers.append('Delta')
    rows = [headers + ['Status']]
    failed = not comparable
    for name, units in METRICS.items():
        groups = [samples(path, manifest, name) for path, manifest in zip(paths, manifests)]
        complete = all(len(group) == m['settings']['reps'] for group, m in zip(groups, manifests))
        failed |= not complete
        for index, unit in enumerate(units):
            series = [[sample[index] for sample in group] for group in groups]
            medians = [median(s) if len(s) == m['settings']['reps'] else None for s, m in zip(series, manifests)]
            row = [name, unit, *('—' if x is None else f'{x:,.2f}' for x in medians)]
            if candidate is not None:
                row.append(f'{(medians[1] / medians[0] - 1):+.1%}' if comparable and complete and medians[0] else '—')
            rows.append(row + ['Not comparable' if not comparable else 'Measured' if complete else 'Incomplete'])
            if verbose:
                rows.append(['', 'Runs', *(', '.join(f'{x:,.2f}' for x in s) or '—' for s in series),
                             *([''] if candidate is not None else []), ''])
    print(f"VM: {manifests[0]['vm']}  |  Values: median of complete runs; latency: fio completion latency")
    for m in manifests:
        mount = m['mount']
        print(f"{m['phase']}: {m['timestamp']} | {mount['source']} at {mount['target']} ({mount['fstype']}) | peer {m['settings']['peer']}")
    widths = [max(map(len, col)) for col in zip(*rows)]
    for index, row in enumerate(rows):
        print('  '.join(value.ljust(width) for value, width in zip(row, widths)).rstrip())
        if index == 0:
            print('  '.join('-' * width for width in widths))
    return int(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    runner = sub.add_parser('run')
    runner.add_argument('--vm', required=True)
    runner.add_argument('--phase', choices=('vmware', 'openshift'), required=True)
    runner.add_argument('--scratch', type=Path, required=True)
    runner.add_argument('--allow-root-volume', action='store_true')
    runner.add_argument('--peer', required=True, help='Fixed peer IP address')
    runner.add_argument('--out', type=Path, required=True, help='New results directory')
    for key, default in [('port', 5201), ('size-mib', 4096), ('reps', 3), ('storage-seconds', 60),
                         ('storage-warmup', 15), ('network-seconds', 30), ('network-warmup', 5)]:
        runner.add_argument('--' + key, type=int, default=default)
    reporter = sub.add_parser('report')
    reporter.add_argument('--baseline', type=Path, required=True)
    reporter.add_argument('--candidate', type=Path)
    reporter.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'report':
            return report(args.baseline, args.candidate, args.verbose)
        if min(args.size_mib, args.reps, args.storage_seconds, args.network_seconds) < 1 or min(args.storage_warmup, args.network_warmup) < 0 or not 1 <= args.port <= 65535:
            raise ValueError('Invalid size, repetitions, duration, warm-up, or port')
        return run(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f'vmperf: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
