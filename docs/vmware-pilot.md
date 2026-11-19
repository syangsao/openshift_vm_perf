# VMware Linux pilot results

Single Linux guest on VMware; three completed repetitions per profile. Storage used a 1 GiB temporary file on the guest's XFS root volume, not a dedicated data disk. TCP used one stream and a fixed external peer. No OpenShift measurements yet.

| Profile | Metric | Run 1 | Run 2 | Run 3 | Median |
|---|---|---:|---:|---:|---:|
| Sequential read | MiB/s | 861.32 | 1,559.04 | 1,514.49 | 1,514.49 |
| Sequential write | MiB/s | 594.89 | 502.62 | 466.35 | 502.62 |
| Random read | IOPS | 1,242.09 | 6,336.57 | 5,389.06 | 5,389.06 |
| Random read | p95 completion latency (ms) | 0.19 | 0.18 | 0.18 | 0.18 |
| Random read | p99 completion latency (ms) | 0.36 | 0.33 | 0.43 | 0.36 |
| TCP guest → peer | Mbps | 914.57 | 932.48 | 939.48 | 932.48 |
| TCP peer → guest | Mbps | 936.91 | 937.56 | 941.46 | 937.56 |

Random-read IOPS varied over 5× across repetitions. Treat this as a suite pilot, not a storage acceptance threshold. Rebaseline on a representative scratch volume during a quiet window if storage performance is a migration gate.

## Reproducing the profile

Use fio 3.35, iperf3 3.9 in the guest, and iperf3 3.16 on the peer to repeat this exact profile. Substitute your own peer address and scratch mount. Use `--allow-root-volume` only if intentionally measuring a root-volume file as in this pilot.

```sh
python3 vmperf.py run --vm linux-vm --phase vmware \
  --scratch /mnt/benchmark --peer PEER_IP --port 55201 \
  --out results/vmware --size-mib 1024 --reps 3 \
  --storage-seconds 10 --storage-warmup 2 --network-seconds 5 --network-warmup 2
```

Exact lab addresses, paths, and raw logs are not included on this public page. See the [README](../README.md) for setup and post-migration comparison.
