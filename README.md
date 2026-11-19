# Linux VM migration benchmarks

Run `vmperf.py` inside the Linux VM before and after migration. Run the report on your workstation. No Python packages required.

## 1. Install and verify the guest tools

Use your distro's package manager on the VMware guest:

```sh
# RHEL 9: requires access to the enabled RHEL repositories.
sudo dnf install python3 git fio fio-engine-libaio iperf3 util-linux iproute

# Ubuntu/Debian: use this instead of dnf.
sudo apt-get update
sudo apt-get install python3 git fio iperf3 util-linux iproute2
```

```sh
python3 --version
fio --version                 # Must identify itself as fio-<version>.
fio --enghelp=libaio           # Must list engine options, not an engine error.
iperf3 --version
git clone https://github.com/syangsao/openshift_vm_perf.git
cd openshift_vm_perf
git rev-parse HEAD             # Record this; use the same revision after migration.
```

The runner does not require root. If `fio --version` identifies a Python GIS tool instead, use the distro's Flexible I/O Tester executable and fix the guest's `PATH`.

## 2. Prepare a writable scratch directory

Attach and mount a scratch volume using your normal provisioning process. Pick a storage policy representative of the disk you want to measure. On the guest, check the mount **before** creating the benchmark directory:

```sh
mountpoint /mnt/benchmark      # Stop if this is not a mount point.
sudo install -d -o "$(id -u)" -g "$(id -g)" /mnt/benchmark/vmperf
findmnt -T /mnt/benchmark/vmperf
df -h /mnt/benchmark/vmperf
test -w /mnt/benchmark/vmperf
```

Confirm `findmnt` shows the intended filesystem and that `df` shows at least 5 GiB available for the default run (4 GiB file plus 1 GiB reserved). The runner fills and removes its own temporary file. Do not point it at a block device. If you intentionally want to measure the root volume, use `--scratch "$HOME" --allow-root-volume` and record that choice.

## 3. Start a fixed network peer

Pick a wired Linux host outside both virtualization platforms that both versions of the guest can reach. Install `iperf3` there and record its version. Run the server in a dedicated terminal; replace the example IP with the peer's actual address:

```sh
PEER_IP=192.0.2.10
iperf3 -s -B "$PEER_IP" -p 5201
```

Allow inbound **TCP 5201 from the test guest** on the peer firewall. Use the same host, address, port, and server version in both phases. From the guest, set `PEER_IP` again (it is a different shell) and check both directions before collecting results:

```sh
PEER_IP=192.0.2.10             # Replace with the same actual peer address.
ip route get "$PEER_IP"         # Confirm the intended guest interface and source IP.
iperf3 -c "$PEER_IP" -p 5201 -t 3
iperf3 -c "$PEER_IP" -p 5201 -t 3 -R
```

If either check fails, verify server binding, firewall rules, and routing before starting the suite. Stop the server with Ctrl+C when finished; restart it with the same settings for the next phase.

## 4. Collect the VMware baseline and copy it off the VM

Run during a quiet window, away from backups and migration activity. The tests are uncapped. Defaults are three repetitions, 60 seconds of measured storage I/O after 15 seconds of warm-up, and 30 seconds of measured TCP throughput after 5 seconds of warm-up.

```sh
# VMware guest, from the repository directory:
python3 vmperf.py run --vm linux-vm --phase vmware \
  --scratch /mnt/benchmark/vmperf --peer "$PEER_IP" --out results/vmware
```

The output directory must not already exist. If the runner reports an incomplete profile, inspect its `.stderr` and `.json` files; use a new output directory for a rerun. Record vCPU, RAM, the VMware datastore policy, guest NIC/MTU, and any unusual background load.

```sh
# Workstation, from its own clone of the repository:
mkdir -p results
scp -r vm-user@vmware-guest:openshift_vm_perf/results/vmware results/
python3 vmperf.py report --baseline results/vmware --verbose
```

Keep the entire result directory, including `run.json`. Replace the example SSH login and adjust the remote path if you cloned somewhere other than the guest home directory.

## 5. Rerun after migration and compare

After the migrated VM is stable, verify the mount, available space, guest tooling, and network path again. Use the same script revision, VM ID, tool versions, peer, repetitions, file size, and timings. Record the OpenShift StorageClass and any changes to the guest NIC or network path. Change only the phase and output directory in the command below; use the new scratch path if its mount point differs.

```sh
# OpenShift guest, from the repository directory:
PEER_IP=192.0.2.10             # Replace with the same actual peer address.
python3 vmperf.py run --vm linux-vm --phase openshift \
  --scratch /mnt/benchmark/vmperf --peer "$PEER_IP" --out results/openshift

# Workstation, from its own clone:
scp -r vm-user@openshift-guest:openshift_vm_perf/results/openshift results/
python3 vmperf.py report --baseline results/vmware --candidate results/openshift --verbose
```

The terminal report shows medians and `(candidate / baseline) - 1`. `--verbose` shows individual runs. Higher throughput and IOPS are better; lower latency is better. Latency is the median of per-run fio completion-latency percentiles. Incomplete runs or mismatched settings cause a nonzero exit; no performance thresholds are assumed.

See the [VMware pilot results](docs/vmware-pilot.md) for a real run using shorter profiles. The runner does not depend on that lab or its results.
