MPC KEY-VALUE DATABASE COST MODEL
===============================

Run from the repository root with Python 3.10+ (no third-party packages):

  python -m mpc_cost.run --full
  python -m unittest mpc_cost.test_model -v

Online/offline attribution and scan comparison (13 October update):

  python -m mpc_cost.compare_scans
  python -m unittest mpc_cost.test_scan_comparison -v

This rebuilds the saved central ORAM design without changing its total cost,
classifies query-independent preparation separately, and compares an exact
parallel full-key scan and a stronger indexed 2D private-dot scan. Results are
in results/bottleneck_scan_comparison.json. Phase boundaries are a potential
scheduling classification, not a measured profile. The comparison's resource
equivalent dollar figures do not establish feasible giant AWS deployments.

Outputs: results/summary.json, circuits.json, frontier.csv, topology.json.
The report gives interpretation, assumptions and limitations. This is a circuit
accounting/capacity/queue simulator, NOT an MPC implementation or an AWS benchmark.

Inputs
------
Pass --config file.json with optional design, backend, deployment objects, for
example:

{"deployment": {"round_ms": 0.5,
                "local_products_per_sec_64vcpu": 500000000,
                "mean_latency_limit": 5.0,
                "az_fraction": 0.7333333333333333}}

The sweep overrides batch, fanout, base_cutoff, metadata and sort_method. Other
design fields remain configurable. See dataclasses in model.py for the complete
schema. Direct Python use of circuit(Design(...)) and provision(...) evaluates an
exact chosen design without the sweep. Rates other than 10,000 are supported;
source backend coefficients are specific to n=10,t=4,p=2^127-1 and are guarded.
The initial tree must have at least twice its dense batch in leaves. Dynamic
insertions, database writes, adaptive queries and WAN topologies are out of scope.

Price refresh
-------------
The checked-in snapshot contains official AWS rows with SKU, effective date,
region, Linux/shared-tenancy conditions and feed publication version. Read:

  python mpc_cost/refresh_aws_prices.py --help

Use --output to write a new snapshot and --prices to point the simulator at it.
No AWS instances are launched, and no credentials are required for this feed.

Interpretation
--------------
* The reference is a derived Circuit-OPRAM-inspired compilation template. Its
  complete pool/recursive-update/eviction circuits are not implemented or proved.
* No quoted result is a best-known algorithm bound or production cost forecast.
* The reference counts three separate pool operations, conflict routing, private
  payload moves, exact metadata conversion, dot-product outputs, random bits,
  authentication, lifetime field-size headroom, two cuckoo probes and stash scan.
* A 40% cuckoo load ceiling rounds to two 2^29-cell tables at N=2^28: actual
  occupancy25%. The ORAM uses one leaf per dense cell, Z=3. These are conservative
  layout choices, not optimized stash parameters. Pool slack128/stash8 are design
  placeholders awaiting failure analysis, not asserted security guarantees.
* Stored arithmetic bit metadata is fully charged in record movements and memory;
  compact mode charges a full canonical mask and a modular-subtraction circuit
  proxy for conversion. Compact-field addressing does not give free bit access.
* Arithmetic-bit gates use the same Shamir nonlinear primitive as field products;
  they are counted at their ACTUAL widths, not as constant-cost word comparisons.
  Native Boolean MPC would require new measured conversion/AND coefficients.
* Private dot products are charged per reduced output in communication and per
  vector entry in CPU. They do not magically eliminate one-hot generation.
* Whole-batch checks, private-switch-input costs and A2B circuitry have explicit
  proxy constants. Stock SY-Shamir source was inspected; this is not a trace of
  that program. No ATLAS online coefficient is mixed into SY-Shamir dot products.
* CPU rates (0.5/2/8 billion weighted field operations per64-vCPU node/s), exchange
  delays (0.05/0.2/0.5ms), network65%, distributed70%, operating70% and RAM75%
  are unmeasured sensitivity assumptions. They are not AWS guarantees. The local
  operation rate must be measured INCLUDING checks, PRG, interpolation, marshaling,
  bit generation, and inversions. Output traffic is a source-derived leading proxy.
* The service schedule serializes recursive work, and folds steady-state offline
  resource demand into service time. This is conservative for latency with ready
  preprocessing, but avoids treating preprocessing production as free capacity.
  Parallel maintenance and correctly scheduled offline factories can improve it.
* Intra-party routing is charged on the NIC as a configurable multiple of share
  RAM traffic, in addition to inter-party bytes. Only inter-party traffic enters
  cross-AZ billing; within-party sharding is assumed in the party's AZ.
* K machines per party jointly execute one state; separate replica groups have
  complete independent ORAM states. All copies, parties, and idle headroom are
  charged. A central batcher prevents the incorrect B/(R/replicas) fill delay.
* Queue simulation uses Poisson arrivals and service CV0.05. Its p95 is a scenario,
  not an SLA. Every batch waits for state maintenance before its replica reuses it.
* Cross-AZ billing counts network sends once then charges BOTH billed endpoints.
  The4/3/3 AZ fraction is an all-to-all graph proxy, not a universal protocol fact.
* EC2 figures exclude initialization, EBS/backups, client ingress/egress, NAT,
  orchestration, failover replicas, taxes, support, and engineering. Deployment of
  tens of thousands of instances additionally requires quotas/capacity validation.

Where to calibrate first
------------------------
Pin the supplied MP-SPDZ revision and measure one complete checked scalar batch,
dot products at lengths16..32768, exact bit conversion and mask production, then
one full pool phase and a recursive read. Record online AND steady-state resource
usage. Next implement duplicate map-block updates and prove stash lifetime bounds.
Replace circuit proxies with measured trace counters before using a USD figure
as a proposal deliverable or promising target throughput.
