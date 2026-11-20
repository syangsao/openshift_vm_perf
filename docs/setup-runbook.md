# Linux VM benchmark setup runbook

Run the tests inside the same Linux guest before and after migration. Use a separate, fixed network peer. Collect both result directories on a workstation for the terminal comparison. This procedure does not require Kubernetes access from the guest or a Python virtual environment.

## 1. Prepare the VMware guest

Install the benchmark and transfer tools from your distribution's trusted repositories. Choose one command set:

```sh
# RHEL 9: enable your organization's approved BaseOS/AppStream repositories first.
sudo dnf install python3 git fio fio-engine-libaio iperf3 util-linux iproute openssh-clients

# Debian / Ubuntu:
sudo apt-get update
sudo apt-get install python3 git fio iperf3 util-linux iproute2 openssh-client
```

If you lack sudo or a package is unavailable, have an administrator install the tools or supply a trusted, compatible user-local build. A user-local `fio` package may need its separately packaged `libaio` plugin and shared libraries; simply placing `fio` in `PATH` is not enough. Verify from the same shell and as the same user that will run the suite:

```sh
command -v python3 fio iperf3 findmnt ip
python3 --version
fio --version
fio --enghelp=libaio
iperf3 --version
```

`fio --version` should identify Flexible I/O Tester (`fio-…`), and `--enghelp=libaio` should list engine options. Record the client versions and keep them unchanged after migration. Clone the repository on the guest and on your workstation:

```sh
cd "$HOME"
git clone https://github.com/syangsao/openshift_vm_perf.git
cd openshift_vm_perf
git rev-parse HEAD
```

Record the revision. Use the same checkout after migration; if you must clone again, run `git checkout --detach <recorded-commit>` in the new clone.

### EL9 without sudo: the pilot workaround

Grogu's sudo requires a password. For the pilot, we unpacked compatible x86_64 EL9 RPMs into a user-owned directory without installing them system-wide. Prefer the package-manager setup above when available. Otherwise, obtain and verify trusted RPMs for `fio` and its matching `fio-engine-libaio`, `iperf3`, and any missing shared libraries. The pilot staged `libaio` and `liburing` too. You need `rpm2cpio` and `cpio` already present. Put the verified RPMs in a new `~/vmperf-rpms` directory, then run the following in Bash:

```bash
tools=$(mktemp -d "$HOME/vmperf-tools.XXXXXX")
(
  set -euo pipefail
  cd "$tools"
  for rpm in "$HOME"/vmperf-rpms/*.rpm; do
    rpm2cpio "$rpm" | cpio -idm --quiet
  done
  mkdir bin
  cat > bin/fio <<'EOF'
#!/bin/bash
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
args=()
for arg; do
  case "$arg" in
    --ioengine=libaio) arg="--ioengine=$root/usr/lib64/fio/fio-libaio.so" ;;
    --enghelp=libaio) arg="--enghelp=$root/usr/lib64/fio/fio-libaio.so" ;;
  esac
  args+=("$arg")
done
exec "$root/usr/bin/fio" "${args[@]}"
EOF
  chmod +x bin/fio
)
```

Keep this path for the next session and export it in the shell that will run the benchmarks:

```bash
export PATH="$tools/bin:$tools/usr/bin:$PATH"
export LD_LIBRARY_PATH="$tools/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
ldd "$tools/usr/bin/fio" "$tools/usr/bin/iperf3" "$tools/usr/lib64/fio/fio-libaio.so"
fio --version
fio --enghelp=libaio
iperf3 --version
```

If `ldd` reports `not found`, stop and obtain the matching library through the same approved source. The wrapper points fio at the extracted plugin rather than the system plugin directory. Preserve the staged tools across migration so the same versions can be used.

## 2. Select the storage target

Provision and mount a scratch volume using your normal platform process. Choose a storage policy representative of the disk you want to measure. Do not format or reuse an existing data volume just to follow this guide. In the guest:

```sh
mountpoint /mnt/benchmark &&
  sudo install -d -o "$(id -u)" -g "$(id -g)" /mnt/benchmark/vmperf
findmnt -T /mnt/benchmark/vmperf
df -h /mnt/benchmark/vmperf
test -w /mnt/benchmark/vmperf
```

Stop if the mount or permission check fails, or if `findmnt` shows a different volume than expected. The default run needs at least 5 GiB free (a 4 GiB file plus 1 GiB headroom). The runner creates and removes its own file; never pass a block device as `--scratch`. To intentionally benchmark an existing root volume, use `--scratch "$HOME" --allow-root-volume`; run only in a quiet window because the test can saturate that disk. The Grogu pilot used this root-volume approach, not a dedicated data disk.

## 3. Set up the network peer

Use a stable, wired host outside both virtualization platforms that both guests can reach. Install `iperf3` there and record the version. Replace `192.0.2.10` (a documentation-only IP) with the peer's actual address. In a dedicated terminal **on the peer**:

```sh
PEER_IP=192.0.2.10
PORT=5201
iperf3 --version
iperf3 -s -B "$PEER_IP" -p "$PORT"
```

Allow TCP to that port from the test guest through the peer firewall and any intervening firewall. No inbound benchmark listener is required on the guest: `-R` reverses data flow over a connection initiated by the guest. Do not expose the peer publicly. In the **guest shell**, set the same IP and port:

```sh
PEER_IP=192.0.2.10
PORT=5201
ip route get "$PEER_IP"
iperf3 -c "$PEER_IP" -p "$PORT" -t 3
iperf3 -c "$PEER_IP" -p "$PORT" -t 3 -R
```

For the pilot's port, use `PORT=55201` on both hosts. Confirm the route uses the intended guest NIC. If the connection is refused, check the server bind address and port; if it times out, check routing and firewall rules. Do not run any other iperf3 clients against this peer during the benchmarks. Stop the server with Ctrl+C when finished, and restart it with the same IP, port, and version for the second phase.

## 4. Run and preserve the VMware baseline

Pick a quiet window without backups, migrations, or other benchmarks. Record vCPU, RAM, storage policy, filesystem, NIC/driver, and MTU. From the repo directory in the **VMware guest**, using the peer settings above:

```sh
python3 vmperf.py run --vm linux-vm --phase vmware \
  --scratch /mnt/benchmark/vmperf --peer "$PEER_IP" --port "$PORT" \
  --out results/vmware
```

The runner uses a 4 GiB file and three repetitions per profile by default. It prints a table when complete. To reproduce the **short pilot profile** instead, use peer port `55201` and append these arguments to the baseline and later candidate commands:

```text
--size-mib 1024 --reps 3 --storage-seconds 10 --storage-warmup 2
--network-seconds 5 --network-warmup 2
```

That file size needs at least 2 GiB free. The pilot used fio 3.35, guest iperf3 3.9, and peer iperf3 3.16. Keep pilot and default results separate. If the run fails, check `run.json`, `prepare.stderr`, and the affected profile's `.stderr` and `.json`; rerun to a new, unused output directory rather than overwriting evidence.

From the repo directory on your **workstation**, replace `vm-user@vmware-guest` with your SSH login and copy the entire result directory before migration:

```sh
mkdir -p results
scp -r vm-user@vmware-guest:openshift_vm_perf/results/vmware results/
python3 vmperf.py report --baseline results/vmware --verbose
```

Raw files contain guest and peer identifiers. Keep them local unless publication is explicitly authorized. The repository ignores the `results/` directory.

## 5. Repeat on OpenShift Virtualization

After migration completes, verify that the intended volume is mounted, that the peer is reachable in both directions, and that the same revision and tool versions are still in use. Record the OpenShift StorageClass and any NIC, MTU, or routing differences. Use the same `--vm` label and identical workload flags, even if the guest hostname changes. In the **migrated guest**:

```sh
PEER_IP=192.0.2.10  # Replace with the same actual address used for the baseline.
PORT=5201          # Use the actual baseline port.
python3 vmperf.py run --vm linux-vm --phase openshift \
  --scratch /mnt/benchmark/vmperf --peer "$PEER_IP" --port "$PORT" \
  --out results/openshift
```

If you used custom timings or sizes on VMware, repeat them here. If you benchmarked the root volume before migration, benchmark that same logical volume after migration. On the **workstation**:

```sh
scp -r vm-user@openshift-guest:openshift_vm_perf/results/openshift results/
python3 vmperf.py report --baseline results/vmware \
  --candidate results/openshift --verbose
```

The report prints medians and percent change to stdout, with the individual repetitions under `--verbose`. A negative delta is good for latency but bad for throughput. Investigate high variability before drawing conclusions. Missing results show as `Incomplete`; mismatched guest tool versions or test settings show as `Not comparable`. No pass/fail thresholds are assumed.

See the separate [VMware pilot results](vmware-pilot.md) for measured data.
