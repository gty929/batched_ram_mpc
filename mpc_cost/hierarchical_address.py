"""Current address protocol and a materialized case for every resource model.

Legacy input ledgers remain reproducible. Every published resource run upgrades
them once to a single projected AES plus fresh private dummy-address shares.
Private input transcripts are prepaid with the auxiliary circuit batch; their
forward/reverse communication and conservative RAM reservation are separate
from garbled gate bytes.
"""
from copy import deepcopy
from math import ceil

SCHEME = 'single_projected_aes_private_dummy_v1'
LEGACY = 'two_full_aes_v0'
PROJECTED_BYTES = (0,13,10,7)


def aes_dependencies(output_bytes):
    chosen=set(output_bytes)
    if not chosen or not chosen<=set(range(16)):
        raise ValueError('Select nonempty AES output byte positions 0..15')
    needed={10:chosen}; nonlinear={}
    for rnd in range(10,0,-1):
        before_mix=(needed[rnd] if rnd==10 else
                    {4*(i//4)+r for i in needed[rnd] for r in range(4)})
        before_shift={4*((i//4+i%4)%4)+i%4 for i in before_mix}
        nonlinear[rnd]=before_shift
        needed[rnd-1]=before_shift
    return needed,nonlinear


def short_aes_ands(bits,projection='column'):
    if not 1<=bits<=32 or projection not in ('column','prefix'):
        raise ValueError('Expected 1..32 address bits and column/prefix projection')
    positions=PROJECTED_BYTES[:ceil(bits/8)] if projection=='column' else tuple(range(ceil(bits/8)))
    return 32*sum(len(s) for s in aes_dependencies(positions)[1].values())


def scheme(c):
    return c.get('address_scheme',LEGACY)


def address_bits(c,row):
    return row['parent_routing_stages']+c['local_refinement']['suffix_bits']


def prf_ands(row):
    return row.get('lookup_prf_ands',10240)


def read_ands(c,row):
    return prf_ands(row)+134*row['read_slots']+address_bits(c,row)+4


def inputs(row):
    return row.get('dummy_input_forward_bytes',0),row.get('dummy_input_reverse_bytes',0)


def epoch_inputs(row):
    return row.get('fresh_key_input_bytes',16384)


def auxiliary(row):
    gc=32*(prf_ands(row)+134*row['global_stash']['capacity'])
    f,r=inputs(row)
    return dict(gc=gc,forward=gc+f,reverse=r,ram=gc+f+r,
                input_forward=f,input_reverse=r)


def current_case(original):
    c=deepcopy(original)
    if scheme(c)==SCHEME:
        return c
    if scheme(c)!=LEGACY:
        raise ValueError('Unknown address protocol')
    c['source_reference_total_bytes']=c['total_unframed_bytes_per_query']
    c['address_scheme']=SCHEME
    components={}; lookup_ands=lookup_bytes=worst=key_inputs=0.
    for row in c['rows']:
        bits=address_bits(c,row); gates=short_aes_ands(bits)
        row.update(lookup_prf_ands=gates,dummy_input_forward_bytes=48*bits,
                   dummy_input_reverse_bytes=16*bits,fresh_key_input_bytes=8192)
        row['components']['routing_prf']=row['capacity']*gates
        row['components']['fresh_epoch_key_schedules']=1280
        row['rebuild_ands']=sum(row['components'].values())
        row['rebuild_unframed_bytes']=(32*row['rebuild_ands']+8192+
            c['packed_payload_swap_bytes']*row['rebuild_payload_swaps'])
        interval=row['accesses_per_rebuild']
        key_inputs+=8192/interval
        for k,v in row['components'].items():
            components[k]=components.get(k,0.)+v/interval
        weight=1 if row['top'] else .5
        a=read_ands(c,row)
        amount=32*a+c['packed_payload_swap_bytes']*row['read_slots']+bits/4+64*bits
        lookup_ands+=weight*a; lookup_bytes+=weight*amount; worst+=amount
    c['rebuild_ands_components_per_query']=components
    c['rebuild_ands_per_query']=sum(components.values())
    c['rebuild_unframed_bytes_per_query']=(32*sum(components.values())+key_inputs+
        c['packed_payload_swap_bytes']*c['rebuild_payload_swaps_per_query'])
    c['read_ands_per_query']=lookup_ands
    c['read_unframed_bytes_per_query']=lookup_bytes
    c['worst_read_unframed_bytes_per_query']=worst
    c['total_unframed_bytes_per_query']=(lookup_bytes+c['rebuild_unframed_bytes_per_query']+
        c['frontend_and_dedup_unframed_bytes_per_query'])
    c['total_framed_bytes_per_query']=1.05*c['total_unframed_bytes_per_query']
    return c
