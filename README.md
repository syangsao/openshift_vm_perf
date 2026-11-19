# Linux VM migration benchmarks

Run `vmperf.py` inside the guest before and after migration. Run `report` anywhere with Python 3 and both result directories. No Python packages required. The guest needs `fio` with the libaio engine, `iperf3`, `findmnt`, and `ip`.

On a fixed peer outside both virtualization platforms, start `iperf3 -s -B PEER_IP -p 5201`. Allow the guest to reach that TCP port and stop the server when finished. Use the same peer, port, server version, and guest tool versions for both phases.

```sh
python3 vmperf.py run --vm linux-vm --phase vmware \
  --scratch /mnt/benchmark --peer PEER_IP --out results/vmware
# After migration: same VM ID and settings; change phase and output directory.
python3 vmperf.py run --vm linux-vm --phase openshift \
  --scratch /mnt/benchmark --peer PEER_IP --out results/openshift
python3 vmperf.py report --baseline results/vmware --candidate results/openshift --verbose
```

Use a scratch volume with the policy you want to measure. The runner creates, fills, tests, and removes a temporary file; it never writes directly to a block device. Running on the root volume requires `--allow-root-volume`. Run during a quiet window: the workloads are intentionally uncapped. Defaults: 4 GiB, three repetitions, 60 s storage plus 15 s warm-up, and 30 s TCP plus 5 s warm-up per profile. Copy the raw results off the VM before migrating.

The report prints medians, optional individual runs, and `(candidate / baseline) - 1`. Latency is the median of per-run fio completion-latency percentiles. Higher throughput/IOPS and lower latency are better. Incomplete runs or mismatched settings cause a nonzero exit. No performance thresholds are assumed.

See the [VMware pilot results](docs/vmware-pilot.md) for a real run using shorter profiles. The runner does not depend on that lab or its results.
