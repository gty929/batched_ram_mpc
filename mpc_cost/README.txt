MPC KEY-VALUE DATABASE COST MODEL
===============================

17 October 2026: current single-PRF AWS fleet and latency report
--------------------------------------------------------------
The current communication construction supersedes the two-PRF reference
below. Dummy addresses are fresh private XOR-shared randomness, charged at
64 bytes per address bit. One real-address AES and the existing output mux
suffice; the dummy epoch key is removed. Independent real table-epoch keys
and the 128-bit canonical fingerprint remain unchanged.

Project AES onto output bytes (0,13,10,7), then take the needed address bits.
All ten rounds remain. Byte-dependency pruning needs 128+4+ceil(t/8) S-boxes
for t<=32, or 4256--4352 ANDs with the existing 32-AND S-box. This is an
upper bound charging full final S-boxes, not a claim of optimal pruning.
Both rebuild and lookup use this projection. Corrected useful traffic:
  B1024: 19.231424 / 25.874732 MB/query for N=2^28 / 2^32.
  B2048: 18.684768 / 25.328076 MB/query for N=2^28 / 2^32.
All AWS tables have now been resized and resimulated with these costs.
The current self-contained report is output/pdf/hierarchical_aws_throughput.pdf.
It removes superseded schemes and old fleet/latency tables. Seven-state
results at 10,000 queries/s, for N=2^28 / 2^32:
  B1024: 42 / 56 workers per party; $6.692M / $9.967M per year, both parties;
         mean 121.0 / 121.8 ms, p99 180.4 / 180.4 ms.
  B2048: 36 / 48 workers per party; $5.746M / $8.706M per year, both parties;
         mean 241.0 / 239.2 ms, p99 362.6 / 358.3 ms.
The headline deployment includes scratch, peak provisioned gp3 I/O, cache
refills, and private dummy-input material in both directions. Independent
states share worker pools. These are finite-trace/model results, not AWS
measurements or annual tail guarantees. The current address protocol is
stamped into each saved trace; pricing and report rendering reject stale
protocol stamps. Historical notes below are retained only as a changelog.

  python -m mpc_cost.hierarchical_prf_optimization
  python -m mpc_cost.hierarchical_throughput
  python -m mpc_cost.hierarchical_communication_audit
  python -m mpc_cost.hierarchical_schedule
  python -m mpc_cost.hierarchical_schedule --suite variants
  python -m mpc_cost.hierarchical_annual
  python -m unittest mpc_cost.test_hierarchical_prf_optimization -v
  python -m mpc_cost.render_hierarchical_throughput_report

Ledger: results/hierarchical_prf_optimization.json. Four tests check retained
AES rounds and outputs against 32 independent native-AES vectors, gate-count
bounds, private randomness, key removal, and both communication directions.

17 October 2026: communication and representation audit
------------------------------------------------------
Historical two-PRF reference, superseded for useful bytes by the correction.
The AWS report now has a complete useful-byte and deployment-byte audit.
The existing baseline already moves each 128-bit fingerprint as Boolean
wires, plus two flags and retained routing bits; only values use packed OTs.
No lookup/rebuild PRF was missing: B1024 PRF datapaths cost 5.243/6.226 MB/query
at N=2^28/2^32, while key-only rebuild movement costs 7.911/10.685 MB/query.
Useful total remains 21.389/28.455 MB/query (B1024) or 20.733/27.799 (B2048).

Direct state-wire composition with one Free-XOR offset is now an explicit
interface requirement. The existing 4096-byte query bridge budget covers
two same-offset 128-wire relabeling ports. Generic unrelated-state-label
bridges would instead add 5.849/8.279 MB/query at B1024. The report separates
this sensitivity from the baseline, and prices extra hash-bit retention.

A separate uncompiled variant packs fingerprints only during rebuild
movement, then pays all key re-input conversions. Its projected useful
totals are 13.848/18.232 MB/query (B1024) and 13.335/17.719 (B2048).
It is not used to revise AWS prices without a new I/O and worker schedule.

  python -m mpc_cost.hierarchical_communication_audit
  python -m unittest mpc_cost.test_hierarchical_communication_audit -v
  python -m mpc_cost.render_hierarchical_throughput_report

Ledger: results/hierarchical_communication_audit.json. Five independent audit
checks supplement the earlier 19 throughput, latency, schedule and price tests.

17 October 2026: hierarchical annual cost and query latency
----------------------------------------------------------
The same hierarchical_aws_throughput.pdf now includes a full annual budget
and a finite rebuild-aware pooled schedule. At 10,000 queries/s, batch 1024,
five independently evolving states, and RAM preloading of small buckets plus
all shared-stash/PRF material, N=2^28/2^32 costs $7.30M/$10.59M annually for
both parties. Modeled mean query latency is 122/119 ms; p99 is 182/177 ms.
Batch 512 lowers mean to 61/61 ms but costs $10.14M/$14.21M. The primary
assumptions are 0.2 ms RTT-equivalents, 0.5 ms cold EBS delay, and charged
intra-party redistribution. Rare trace maxima are 0.582/5.745 s at batch 1024;
these are conditional finite traces, not AWS benchmarks or annual SLAs.

Seven states with the same worker pools reduce the observed maxima below
215 ms and cost $7.323M/$10.912M. With a few-hundred-millisecond tolerance,
batch 2048 with seven states is the cheaper tested candidate: $6.219M/$9.336M,
mean 244/243 ms, p99 366/363 ms, and finite-trace maxima 434/435 ms.
Smaller batches save frontend work but add more read/rebuild work overall.

Annual cost includes EC2, five copies of persistent state and explicit rebuild
scratch, and eight gp3 volumes/worker provisioned for full instance EBS peak
bandwidth with 64 KiB I/O. Both parties use private addresses in the same AZ.
Prices come from official AWS rows published 2026-10-15, checked 2026-10-17.
CPU is excluded. The original Q=2^32 probability budget needs recalibration
before claiming the same failure guarantee for 315.36 billion queries/year.

  python -m mpc_cost.hierarchical_schedule
  python -m mpc_cost.hierarchical_schedule --suite variants
  python -m mpc_cost.hierarchical_annual
  python -m unittest mpc_cost.test_hierarchical_throughput mpc_cost.test_hierarchical_latency mpc_cost.test_hierarchical_schedule mpc_cost.test_hierarchical_annual -v
  python -m mpc_cost.render_hierarchical_throughput_report

The schedule command runs millions of batches. Results: hierarchical_schedule.json
and hierarchical_annual.json under results/. Model modules separately expose
ready-state stage latency, queue scheduling, and annual provisioning.

17 October 2026: hierarchical AWS throughput and circuit caching
---------------------------------------------------------------
CPU evaluation/garbling is omitted by assumption. The new analysis separates
directional GC traffic, tiled state I/O, fresh-circuit prefetch, and rebuild
availability. It includes small-table RAM caching and batch-aware per-bucket
lookahead, plus an immutable-equality cache interface with explicit bridges.

  ../output/pdf/hierarchical_aws_throughput.pdf
  ../output/latex/hierarchical_aws_throughput.tex

At B=1024 and 64-entry leaves, adaptive caching through capacity 2^16 gives
29/38 interparty-NIC hosts per party at N=2^28/2^32, before internal routing
and replica scheduling. Tiled EBS plus the small-state cache needs 17/24
hosts by byte capacity. Four prefetched circuits are insufficient at the
base: its mean bucket demand is 32 requests within a single batch.
Preloading four equality versions for every cold bucket on evaluator EBS
raises the interparty fleet to 29/39 hosts per party and needs 17.45/279.27 TB
of cold GC queues per independent state. This remains NIC-limited by bytes.

  python -m mpc_cost.hierarchical_throughput
  python -m unittest mpc_cost.test_hierarchical_throughput -v
  python -m mpc_cost.render_hierarchical_throughput_report

Ledger: results/hierarchical_throughput.json. Cache calculations need SciPy.
This is a transfer/loading model, not a measured fleet or latency guarantee.
The standalone LaTeX compiles with pdfLaTeX.

17 October 2026: hierarchical ORAM alternative report
----------------------------------------------------
New self-contained analysis of binary mutable hierarchical ORAM, 512-slot
routing buckets refined to 64/128-slot lookup buckets, per-parent residual
buffers, merged global stashes, and packed XOR-share payloads:
  ../output/latex/hierarchical_batch_oram_report.tex
  ../output/pdf/hierarchical_batch_oram_report.pdf

The B=1024, 64-slot case uses 21.389/28.455 MB unframed per lookup at N=2^28/2^32,
including 11.147/14.976 MB rebuilding. The report includes a concrete 160-byte
word-OT swap, source-stash re-admission, lifetime overflow bounds, sensitivities,
and explicit TODOs. It is an analytical alternative, not an implementation
or a replacement for the older reports. Fingerprint collisions are separate
from the structural overflow bound; no measured throughput is claimed.

Reproduce (SciPy and mpmath needed for probability calculations/tests):
  python -m mpc_cost.hierarchical_split_cost
  python -m unittest mpc_cost.test_hierarchical_split -v
  python -m mpc_cost.render_hierarchical_split_report

Ledger: results/hierarchical_split_comparison.json. Compile the delivered
self-contained LaTeX twice with pdfLaTeX. The 16 October hierarchical_cost.py
ledger is retained as the earlier unsplit 512-bucket reference.

16 October 2026: interactive shuffle technical report (current)
--------------------------------------------------------------
The current scheme and cost derivation are in the standalone report:
  ../output/latex/interactive_batch_oram_report.tex
  ../output/pdf/interactive_batch_oram_report.pdf

This report models secret-shared query keys, AES-CMAC cuckoo addressing,
match/tag/shuffle pool retrieval with hidden composed permutations, explicit
share-to-GC re-input, fused base-map exchange, and smaller batches. The selected
batch is 32 for both database sizes. Framed traffic is 237.832/301.293 MB per
complete lookup; annual network+state+modeled-I/O capacity is $39.05M/$51.40M.
CPU work and single-state throughput remain conditional, not benchmarked.
Two-carrier values are a separately labeled storage sensitivity; the primary
ledger uses Boolean records outside the temporary XOR-shared shuffle.

Reproduce from the repository root:
  python -m mpc_cost.interactive_shuffle_cost
  python -m unittest mpc_cost.test_interactive_shuffle -v
  python -m mpc_cost.render_interactive_shuffle_report

The generated ledger is results/interactive_shuffle_comparison.json. The
delivered .tex is self-contained with an embedded bibliography; compile it
twice with pdflatex. The modular editable source is interactive_shuffle_report.tex.
Earlier reports and numerical comparisons below are preserved as history.

16 October 2026: two-party public-routing audit and report refresh
----------------------------------------------------------------
Current proposal comparison: two-party Garbled RAM versus streamed interactive
2PC with Circuit OPRAM. Only the current batch's requested old leaf positions
are public; duplicate masking and hidden replacement positions are retained.
Public path sorting, public wire permutation and authorized terminal-output
reordering cost zero extra AND gates. These operations were not separately
charged in the old ledger, so the confirmed optimization gives no numerical
discount by itself. Private pool inverse/extraction allowances remain pending
a concrete replacement circuit. The JSON now itemizes these as a subset of
existing work, not an additional charge or a proven minimum.

Recomputed B256 figures remain 12.921M/16.008M AND per complete lookup and
$70.44M/$89.08M/year for network+state+modeled I/O; assumed 200M AND/s/node gives
$83.28M/$104.97M. One-state feasibility still requires <=17.92ms batch service.
The full and short reports now prioritize the two-party comparison, with the
earlier ten-party work clearly retained as historical material. Merkle-proof
costs are outside this update. The exact 206.8M-account layout remains separate
from the padded N=2^28 study.

  python -m mpc_cost.two_party_cost
  python -m mpc_cost.two_party_serial
  python -m unittest discover -s mpc_cost -p "test_*.py" -v
  python -m mpc_cost.render_report
  python -m mpc_cost.render_short_report

Compile mpc_oram_cost_report.tex from mpc_cost; final PDFs are in output/pdf.
The full report's current section is generated by render_two_party_section.py.

14 October 2026: two-party semi-honest comparison
-----------------------------------------------
Sequential-evaluator correction: the earlier 1/16/128-state capacity cases
do NOT establish target throughput. Read data/two_party_serial_notes.txt first.
Derive the independently evolving state count from per-state service time:

  python -m mpc_cost.two_party_serial

Results are in results/two_party_serial_comparison.json. PicoGRAM's fastest
online variant already avoids DDH; its reported/extrapolated evaluator times
cannot be divided by an assumed full-machine aggregate gate or hash rate.

New, separate estimate for Garbled Merge versus streamed batch Circuit OPRAM:

  python -m mpc_cost.two_party_cost
  python -m unittest mpc_cost.test_two_party mpc_cost.test_garbled -v

Read data/two_party_notes.txt; numerical results are in
results/two_party_comparison.json. The model separately counts ordinary
half-gate tables, source-derived merge/link work, hidden joint leaf generation,
batch pool processing, retained programs/state, NIC capacity and SSD costs.
The source artifact's full-horizon merge computation, unimplemented reset/epoch
handoff, batch-circuit allowances and unmeasured CPU rates are explicit limits.
Efficient-batch targets are not achieved implementations. These estimates do
not replace the earlier ten-party malicious-security study or its PDF.

13 October 2026 expansion: N=2^32 and multiparty garbled RAM
---------------------------------------------------------
The current report is mpc_oram_cost_report.tex, rendered to
../output/pdf/mpc_oram_cost_report.pdf. The original continuity report has a
dated summary directing readers to the revised numerical study.

Reproduce the larger interactive case and both garbled cases:

  python -m mpc_cost.run --full --config mpc_cost/data/design_2p32.json --output mpc_cost/results/size_2p32
  python -m mpc_cost.compare_scans --results mpc_cost/results/size_2p32
  python -m mpc_cost.garbled_cost
  python -m unittest discover -s mpc_cost -p "test_*.py" -v
  python -m mpc_cost.render_report

The Boolean gate template in garbled_circuit.py is independent of arithmetic
reduction counts. garbled_cost.py uses the audited finite Appendix H ledger
from 2025/444, zero stack/adaptor cost under the requested 2026/761 migration,
and user-assumed network throughput dominance. It separately prices global
preprocessing bytes, table delivery, literal retained state, complete programme
epochs on gp3 SSD, and full-duplex NIC capacity with arbitrary party imbalance.
Default T=2N and two complete retained epochs are policies, not space lower
bounds. The horizon sweep jointly reoptimizes map packing/base/template choices;
its selected horizon minimizes the conservative fleet endpoint. Smaller epochs
need a secure renewal protocol, not simply repeated input encoding. The main
source-derived template omits that protocol, concrete OLE/VOLE generation, and
reactive client-input integration. It is not a priced OT-only implementation.

Results: results/garbled_ram_comparison.json and results/size_comparison.json.
Primary-source derivation ledgers: data/garbling_backend_notes.txt,
data/garbled_ram_construction_notes.txt, data/garbled_ram_aws_notes.txt.
Prices: data/aws_garbled_prices_2026-10-13.json (official AWS US East snapshot).
Local source PDFs: ../multiparty_ot.pdf and ../garbled_merge.pdf.
The report distinguishes the finite multiplication-count repair from the
paper's printed approximation. Extra correlation traffic, supplied-control
initialization routing, internal hashes, epoch copies, independent states,
and cross-AZ transport are explicit sensitivities. They are not proven bounds
on the omitted implementations. Label width128 does not certify a128-bit
service-lifetime failure bound at the total workload under consideration.

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
