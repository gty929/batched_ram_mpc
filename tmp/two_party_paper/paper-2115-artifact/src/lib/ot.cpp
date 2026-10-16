#include "header/ot.hpp"
#include <emp-ot/emp-ot.h>
#include <memory>


namespace nog {
using namespace emp;
// ElGamal OT
void ot_send_bit_labels(GarblerCtx& ctx, const std::vector<GBit>& zero_labels) {
    std::vector<block> m0(zero_labels.size()), m1(zero_labels.size());
    for (size_t i=0;i<zero_labels.size();++i) {
        m0[i] = zero_labels[i].z;
        m1[i] = zero_labels[i].z ^ ctx.DELTA;
    }
    IKNP<NetIO> ot(ctx.io);
    ot.send(m0.data(), m1.data(), (int)zero_labels.size());
}

void ot_recv_bit_labels(EvaluatorCtx& ctx, const std::vector<bool>& choice, std::vector<EBit>& out) {
    out.resize(choice.size());
    std::vector<block> r(choice.size());
    std::unique_ptr<bool[]> cbuf(new bool[choice.size()]);
    for (size_t i=0; i<choice.size(); ++i) cbuf[i] = choice[i];
    IKNP<NetIO> ot(ctx.io);
    ot.recv(r.data(), cbuf.get(), (int)choice.size());
    for (size_t i=0;i<choice.size();++i) out[i].a = r[i];
}

}
