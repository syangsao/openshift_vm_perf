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

## VMware rerun — 2026-11-20 UTC

All five profiles completed three repetitions on the same guest with the same settings and external peer. Both runs were on VMware; these deltas show repeatability, not migration impact.

| Profile | Metric | Run 1 | Run 2 | Run 3 | Rerun median | vs. original |
|---|---|---:|---:|---:|---:|---:|
| Sequential read | MiB/s | 1,248.70 | 1,625.12 | 1,640.82 | 1,625.12 | +7.3% |
| Sequential write | MiB/s | 866.14 | 567.92 | 389.34 | 567.92 | +13.0% |
| Random read | IOPS | 5,066.19 | 7,365.46 | 4,952.32 | 5,066.19 | −6.0% |
| Random read | p95 completion latency (ms) | 0.21 | 0.17 | 0.20 | 0.20 | +11.4% |
| Random read | p99 completion latency (ms) | 0.55 | 0.26 | 0.54 | 0.54 | +49.7% |
| TCP guest → peer | Mbps | 910.98 | 931.24 | 931.15 | 931.15 | −0.1% |
| TCP peer → guest | Mbps | 939.44 | 940.95 | 939.51 | 939.51 | +0.2% |

Deltas use unrounded medians. TCP medians stayed within 0.2%; storage varied substantially even without a platform change. Use a representative scratch volume and repeat the baseline before setting storage acceptance thresholds.

## Reproducing the profile

Use fio 3.35, iperf3 3.9 in the guest, and iperf3 3.16 on the peer to repeat this exact profile. Substitute your own peer address and scratch mount. Use `--allow-root-volume` only if intentionally measuring a root-volume file as in this pilot.

```sh
python3 vmperf.py run --vm linux-vm --phase vmware \
  --scratch /mnt/benchmark --peer PEER_IP --port 55201 \
  --out results/vmware --size-mib 1024 --reps 3 \
  --storage-seconds 10 --storage-warmup 2 --network-seconds 5 --network-warmup 2
```

Exact lab addresses, paths, and raw logs are not included on this public page. See the [README](../README.md) for setup and post-migration comparison.
