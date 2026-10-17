"""Single-PRF lookup and short-output AES correction to the reference ledger.

This module retains an independent delta ledger against the old two-PRF
construction. Current AWS schedules use hierarchical_address.current_case.
Output projection is standard AES-128 followed by a fixed public projection;
no AES rounds are removed. S-box-level dead-code elimination gives upper
bounds using the same 32-AND S-box as the original 5120-AND datapath.
"""
from pathlib import Path
import json

from .hierarchical_communication_audit import audit
from .hierarchical_address import PROJECTED_BYTES, aes_dependencies, short_aes_ands, SCHEME

ROOT = Path(__file__).resolve().parent


def corrected(c, prune=True):
    old = audit(c)
    useful = dict(old['useful'])
    lookup = rebuild = random_input = weighted_bits = 0.
    detail = []
    for row in c['rows']:
        bits = row['parent_routing_stages']+c['local_refinement']['suffix_bits']
        gates = short_aes_ands(bits) if prune else 5120
        w = 1 if row['top'] else .5
        lookup += w*32*gates
        rebuild += row['capacity']/row['accesses_per_rebuild']*32*gates
        weighted_bits += w*bits
        random_input += w*64*bits  # Fresh XOR-shared random address, not public.
        detail.append(dict(log_capacity=row['log_capacity'],address_bits=bits,
                           lookup_weight=w,prf_ands=gates))
    useful.pop('lookup_real_and_dummy_prfs')
    useful['lookup_single_real_prf'] = lookup
    useful['lookup_private_dummy_randomness_inputs'] = random_input
    useful['rebuild_routing_prfs'] = rebuild
    useful['rebuild_epoch_key_setup_and_inputs'] /= 2
    # The old t-AND secret address mux is already in other Boolean work.
    total = sum(useful.values())
    setup_saving = old['useful']['rebuild_epoch_key_setup_and_inputs']/2
    old_epoch_inputs = sum(16384/r['accesses_per_rebuild'] for r in c['rows'])
    backward_delta = 16*weighted_bits-old_epoch_inputs/8
    forward_delta = total-old['useful_total']-backward_delta
    dep = dict(old['deployment'])
    dep['unframed_interparty_forward'] += forward_delta
    dep['unframed_interparty_reverse'] += backward_delta
    dep['framed_interparty_total'] += 1.05*(total-old['useful_total'])
    dep['framed_network_total_sends'] += 1.05*(total-old['useful_total'])
    dep['bottleneck_nic_direction_per_party'] += 1.05*forward_delta
    return dict(log_records=c['log_records'],batch=c['batch'],child_z=c['child_z'],
        pruned_aes=prune,reference_total=old['useful_total'],useful=useful,
        total=total,saved=old['useful_total']-total,
        saved_fraction=1-total/old['useful_total'],weighted_address_bits=weighted_bits,
        lookup_prf=lookup,rebuild_prf=rebuild,
        all_prf_datapaths=useful['application_fingerprint_prf']+lookup+rebuild,
        dummy_random_input=random_input,epoch_setup_saving=setup_saving,
        rebuilding=c['rebuild_unframed_bytes_per_query']-
            old['useful']['rebuild_routing_prfs']+rebuild-setup_saving,
        # An optimistic public fresh nonce at the PRF input would require
        # collision/domain analysis; this is a cost comparison, not adoption.
        input_mux_instead_of_private_address_extra=4096*c['average_occupied_tables']-
            96*weighted_bits,
        optional_packed_key_total=old['optional_packed_fingerprint_rebuild']['total']+
            total-old['useful_total'],deployment=dep,rows=detail,
        address_scheme=SCHEME,
        annual_status='Current fleet/latency and prices are in hierarchical_schedule*.json and hierarchical_annual.json.')


def main():
    source = json.loads((ROOT/'results/hierarchical_split_comparison.json').read_text())
    cases = sorted([c for c in source['batch_sweep'] if c['batch'] in (1024,2048)
                    and c['child_z']==64],key=lambda c:(c['batch'],c['log_records']))
    data = dict(description=__doc__,projection_bytes=list(PROJECTED_BYTES),
        assumptions=dict(dummy='Fresh private XOR shares, 64 input bytes per address bit',
            prf='Independent secret table-epoch AES key; single real address computation',
            projection='Public fixed output projection; all 10 AES rounds retained',
            gates='S-box-level upper bound, 32 AND per full S-box; no partial S-box pruning',
            canonical='Unchanged full 128-bit AES-CMAC fingerprint; 32-byte application key'),
        one_full_prf=[corrected(c,False) for c in cases],
        one_projected_prf=[corrected(c,True) for c in cases])
    path = ROOT/'results/hierarchical_prf_optimization.json'
    path.write_text(json.dumps(data,indent=2)+'\n')
    for a,b in zip(data['one_full_prf'],data['one_projected_prf']):
        print(f"N2^{b['log_records']} B{b['batch']}: reference {b['reference_total']/1e6:.6f}, "
              f"one full {a['total']/1e6:.6f}, one projected {b['total']/1e6:.6f} MB/q; "
              f"save {100*b['saved_fraction']:.2f}%")


if __name__ == '__main__':
    main()
