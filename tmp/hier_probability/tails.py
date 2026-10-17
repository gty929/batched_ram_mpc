"""Residual-capacity bounds for fixed-load parent-to-child splitting.

No model/report edits. Numerical evaluation of explicit rigorous analytic
bounds; floating-point evaluation is not interval certified.
"""
import json
import math
from pathlib import Path
from scipy.special import logsumexp
from scipy.stats import poisson
from scipy.optimize import minimize_scalar

LN2 = math.log(2)
Q = 2**32

def parent_tests(log_n, batch):
    return Q*(log_n-int(math.log2(batch))+2)/512

def local_logp(z, capacity):
    # R>s implies some nonempty subset J of overflowing children has
    # sum X_j >= |J| z+s+1. Each such subset's binomial mgf is <= Poisson's.
    g=512//z
    out=[]
    for k in range(1,g+1):
        threshold=k*z+capacity+1
        if threshold>512:
            continue # parent has at most512 records, conditioned on no failure.
        mu=k*z/2
        out.append(math.log(math.comb(g,k))-threshold*math.log(threshold/mu)+threshold-mu)
    return min(0.,float(logsumexp(out))) if out else -math.inf

def local_capacity(log_n,batch,z, target_bits=64):
    tests=parent_tests(log_n,batch)
    cap=0
    while local_logp(z,cap)+math.log(tests)>-target_bits*LN2:
        cap+=1
    return dict(capacity=cap,per_parent_log2=local_logp(z,cap)/LN2,
                horizon_log2=(local_logp(z,cap)+math.log(tests))/LN2,
                parent_tests=tests)

def residual_logmgf(z,t):
    # Exact MGF of (Pois(z/2)-z)_+ evaluated without losing tiny increments.
    mu=z/2
    logp=float(poisson.logsf(z,mu))
    logtilted=-t*z+mu*math.expm1(t)+float(poisson.logsf(z,mu*math.exp(t)))
    diff=min(-1e-16,logp-logtilted)
    logdelta=logtilted+math.log(-math.expm1(diff))
    return math.log1p(math.exp(logdelta)) if logdelta<700 else logdelta

def global_logp(n,z,capacity):
    m=2*n//z
    # Independent Pois occupancy with total T~Pois(n). Overflow is monotone
    # in balls, so P_multinom(n)[bad] <= P_Pois[bad]/Pr[T>=n] <=2 P_Pois[bad].
    # Integer n is a Poisson median. This avoids sqrt(n) conditioning loss.
    logfactor=LN2
    result=minimize_scalar(lambda t:m*residual_logmgf(z,t)-(capacity+1)*t,
                           bounds=(1e-8,6.),method='bounded',options={'xatol':1e-12})
    return min(0.,result.fun+logfactor),float(result.x)

def global_capacity(n,z,batch=1024,target_bits=64):
    # At most Q/B rebuilds across all levels. Same per-build target everywhere.
    rebuilds=Q/batch
    target=-target_bits*LN2-math.log(rebuilds)
    lo,hi=-1,1
    while global_logp(n,z,hi)[0]>target:
        hi*=2
    while hi-lo>1:
        mid=(hi+lo)//2
        if global_logp(n,z,mid)[0]<=target:hi=mid
        else:lo=mid
    lp,t=global_logp(n,z,hi)
    expectation=(2*n/z)*((z/2)*poisson.sf(z-1,z/2)-z*poisson.sf(z,z/2))
    return dict(capacity=hi,per_build_log2=lp/LN2,
                horizon_union_log2=(lp+math.log(rebuilds))/LN2,
                tilt=t,poisson_mean_residual=float(expectation))

def rounded_table(batch=1024,target_bits=66):
    rows=[]
    for exponent in range(int(math.log2(batch)),33):
        row=dict(log_capacity=exponent,capacity=2**exponent)
        for z in [64,128]:
            c=global_capacity(2**exponent,z,batch,target_bits)
            rounded=8*((c['capacity']+7)//8)
            lp,t=global_logp(2**exponent,z,rounded)
            row[f'z{z}']=dict(minimum_capacity=c['capacity'],rounded_capacity=rounded,
                per_build_log2=float(lp/LN2),tilt=t,
                poisson_mean_residual=c['poisson_mean_residual'])
        rows.append(row)
    return dict(batch=batch,horizon=Q,global_horizon_budget_bits=target_bits,
                global_per_build_budget_bits=target_bits+math.log2(Q/batch),
                depoissonization_factor=2,local_parent_stash=64,rows=rows)

def main():
    out=[]
    for batch in [256,1024]:
        for logn in [28,32]:
            for z in [64,128]:
                out.append(dict(log_records=logn,batch=batch,child_capacity=z,
                    local=local_capacity(logn,batch,z),
                    global_top=global_capacity(2**logn,z,batch),
                    global_small=global_capacity(batch,z,batch)))
    print(json.dumps(out,indent=2))
    target=Path(__file__).with_name('rounded_capacities.json')
    target.write_text(json.dumps(rounded_table(),indent=2)+'\n')

if __name__=='__main__':main()
