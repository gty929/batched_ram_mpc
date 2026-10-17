"""Check AES pruning against independent native-AES vectors and byte ledgers."""
from pathlib import Path
import json
import unittest

from .hierarchical_prf_optimization import (PROJECTED_BYTES, aes_dependencies,
                                          short_aes_ands, corrected)
from .hierarchical_address import current_case
from .hierarchical_communication_audit import audit
from .hierarchical_throughput import directions

ROOT = Path(__file__).resolve().parent


def mul(a,b):
    out=0
    for _ in range(8):
        if b&1:
            out ^= a
        a = ((a << 1) ^ (0x11b if a&128 else 0)) & 255
        b >>= 1
    return out


def sbox(x):
    # FIPS 197 field inverse and affine map, independent of circuit counts.
    y, base, exponent = 1, x, 254
    while exponent:
        if exponent&1:
            y=mul(y,base)
        base=mul(base,base)
        exponent >>= 1
    return y ^ sum_rotate(y,1) ^ sum_rotate(y,2) ^ sum_rotate(y,3) ^ sum_rotate(y,4) ^ 0x63


def sum_rotate(x,k):
    return ((x << k) | (x >> (8-k))) & 255


SBOX = [sbox(i) for i in range(256)]


def keys(key):
    expanded=list(key)
    rcon=1
    while len(expanded)<176:
        last=expanded[-4:]
        if len(expanded)%16==0:
            last=[SBOX[x] for x in last[1:]+last[:1]]
            last[0] ^= rcon
            rcon=mul(rcon,2)
        for x in last:
            expanded.append(x^expanded[-16])
    return [expanded[i:i+16] for i in range(0,176,16)]


def projected_encrypt(key,block,positions):
    needed,nonlinear=aes_dependencies(positions)
    schedule=keys(key)
    state=[x^k for x,k in zip(block,schedule[0])]
    count=0
    for rnd in range(1,11):
        sub={i:SBOX[state[i]] for i in nonlinear[rnd]}
        count += len(sub)
        shifted={i:sub.get(4*((i//4+i%4)%4)+i%4) for i in range(16)}
        output=[None]*16
        for i in needed[rnd]:
            if rnd==10:
                value=shifted[i]
            else:
                col=[shifted[4*(i//4)+j] for j in range(4)]
                row=i%4
                value=mul(2,col[row])^mul(3,col[(row+1)%4])^col[(row+2)%4]^col[(row+3)%4]
            output[i]=value^schedule[rnd][i]
        state=output
    return bytes(state[i] for i in positions),count


class PrfOptimizationChecks(unittest.TestCase):
    def test_pruned_aes_matches_independent_native_cipher(self):
        data=json.loads((ROOT/'data/aes_pruning_vectors.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(len(data['vectors']),32)
        for vector in data['vectors']:
            key,block,expected=[bytes.fromhex(vector[k]) for k in ('key','plaintext','ciphertext')]
            for width in range(1,5):
                for positions in (PROJECTED_BYTES[:width],tuple(range(width))):
                    actual,count=projected_encrypt(key,block,positions)
                    self.assertEqual(actual,bytes(expected[i] for i in positions))
                    formula=128+4+width if positions==PROJECTED_BYTES[:width] else 128+5*width
                    self.assertEqual(count,formula)

    def test_all_ten_rounds_remain_and_cost_bound(self):
        for bits in range(1,33):
            needed,nl=aes_dependencies(PROJECTED_BYTES[:(bits+7)//8])
            self.assertEqual([len(nl[r]) for r in range(1,9)],[16]*8)
            self.assertEqual(len(nl[9]),4)
            self.assertEqual(short_aes_ands(bits),32*(132+(bits+7)//8))
        self.assertEqual(short_aes_ands(27,'prefix'),4736)
        self.assertEqual(short_aes_ands(27),4352)

    def test_native_vector_and_full_cipher(self):
        result,count=projected_encrypt(bytes.fromhex('000102030405060708090a0b0c0d0e0f'),
            bytes.fromhex('00112233445566778899aabbccddeeff'),tuple(range(16)))
        self.assertEqual(result.hex(),'69c4e0d86a7b0430d8cdb78070b4c55a')
        self.assertEqual(count,160)

    def test_cost_reconciliation_and_fresh_random_input(self):
        data=json.loads((ROOT/'results/hierarchical_split_comparison.json').read_text())
        for c in data['batch_sweep']:
            if c['child_z']!=64 or c['batch'] not in (1024,2048):
                continue
            full,short=corrected(c,False),corrected(c,True)
            a=c['average_occupied_tables']; h=short['weighted_address_bits']
            setup=48 if c['batch']==1024 else 24
            self.assertAlmostEqual(full['saved'],163840*a-64*h+setup)
            self.assertAlmostEqual(short['lookup_prf'],short['rebuild_prf'])
            self.assertAlmostEqual(sum(short['useful'].values()),short['total'])
            d=short['deployment']
            self.assertAlmostEqual(d['framed_interparty_total'],1.05*(
                d['unframed_interparty_forward']+d['unframed_interparty_reverse']))
            self.assertAlmostEqual(d['framed_network_total_sends'],d['framed_interparty_total']+
                1.05*d['internal_all_parties_total_sends'])
            self.assertGreater(full['total'],short['total'])
            materialized=current_case(c)
            self.assertEqual(current_case(materialized),materialized)
            independent=audit(materialized)
            self.assertAlmostEqual(independent['useful_total'],short['total'])
            for key,value in short['useful'].items():
                self.assertAlmostEqual(value,independent['useful'][key])
            direct=directions(materialized)
            self.assertAlmostEqual(direct['forward']+direct['backward'],short['total'])


if __name__=='__main__':
    unittest.main()
