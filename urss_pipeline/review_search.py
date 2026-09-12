"""PDF review D02/D03: repaired beam and interruptible operational certification.

The feasible set uses the frozen floating-point raw-moment diagnostic with its
explicit numeric tolerance. These are certificates for this implemented set and
fixed reference compiler, not exact-arithmetic certificates for the LP moments.
Historical algorithms remain available under *_historical entrypoints.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
import heapq
import math
import time
from typing import Callable
import numpy as np
from .e1_exactness import action_options
from .e2_resources import _action_key, _evaluate_design
from .fibre_selector import (FibreCandidate, FibreSearchResult, FibreSelectorError,
    _candidate, _stable_actions_key, fibre_normalisation)
from .polynomial import canonicalize, cubic_supports


def _setup(polynomial, n_original, selector, moments, apply_qaoa_hard_limits):
    canonical=canonicalize(polynomial);cubics=tuple(sorted(cubic_supports(canonical)))
    fibre=selector['fibre_risk'];margin=float(fibre['positive_penalty_margin'])
    tau=float(fibre['threshold_tau']);tol=float(fibre['numeric_tolerance'])
    if not math.isfinite(tau) or not math.isfinite(tol) or tol<0 or margin<=0:
        raise ValueError('Invalid fibre threshold, numeric tolerance or positive margin')
    for key,weight in selector['weights'].items():
        if not math.isfinite(float(weight)) or float(weight)<0 or float(selector['scales'][key])<=0:
            raise ValueError('Bounds require finite nonnegative weights and positive scales')
    normalisation=fibre_normalisation(canonical,positive_margin=margin);cache={}
    def evaluate(actions):
        actions=tuple(actions)
        if actions not in cache:
            cache[actions]=_candidate(canonical,cubics,n_original=n_original,actions=actions,
                selector=selector,moments=moments,normalisation=normalisation,tau=tau,
                positive_margin=margin,apply_qaoa_hard_limits=apply_qaoa_hard_limits)
        return cache[actions]
    return canonical,cubics,margin,tau,tol,cache,evaluate


def _inc_key(item,cubics):
    return item.score,item.risk.normalised_excess,_action_key(cubics,item.actions)


def _rank_group(items):
    """NSGA-II ranks and crowding; constant coordinates add no endpoints."""
    if not items:return {}
    vectors=np.asarray([i.pareto_vector for i in items],dtype=float)
    if not np.isfinite(vectors).all():raise ValueError('Crowding requires finite coordinates')
    dominates=np.all(vectors[:,None,:]<=vectors[None,:,:],axis=2)&np.any(vectors[:,None,:]<vectors[None,:,:],axis=2)
    counts=dominates.sum(axis=0);remaining=np.ones(len(items),dtype=bool);result={};rank=0
    while remaining.any():
        front=np.flatnonzero(remaining&(counts==0));crowd={int(i):0.0 for i in front}
        if not len(front):raise AssertionError('Dominance cycle')
        for dim in range(vectors.shape[1]):
            order=sorted(map(int,front),key=lambda i:(vectors[i,dim],_stable_actions_key(items[i].actions)))
            low,high=vectors[order[0],dim],vectors[order[-1],dim]
            if low==high:continue
            crowd[order[0]]=crowd[order[-1]]=math.inf
            for pos in range(1,len(order)-1):
                i=order[pos]
                if not math.isinf(crowd[i]):
                    crowd[i]+=(vectors[order[pos+1],dim]-vectors[order[pos-1],dim])/(high-low)
        for i in front:result[items[int(i)].actions]=(rank,crowd[int(i)])
        remaining[front]=False;counts-=dominates[front].sum(axis=0);rank+=1
    return result


def ranking(candidates, selector, n_original, hard_limits):
    """Compute K_P on the entire level, separately by feasibility (Eq. 65)."""
    limits=selector['feasibility_limits'];fibre=selector['fibre_risk'];pre_rejected=set()
    for c in candidates:
        # Reference metrics happen to be cheaply available, but pre-compilation
        # rejects have sentinel rank/score, never fabricated infinite vectors.
        if c.risk.normalised_excess>float(fibre['threshold_tau'])+float(fibre['numeric_tolerance']):
            pre_rejected.add(c.actions)
        if hard_limits and (c.resources.n_qubits>int(limits['maximum_qubits']) or
                            float(c.resources.maximum_penalty)>float(limits['maximum_penalty'])):
            pre_rejected.add(c.actions)
    ranks={}
    for feasible in [True,False]:
        ranks.update(_rank_group([c for c in candidates if c.feasible==feasible and c.actions not in pre_rejected]))
    for actions in pre_rejected:ranks[actions]=(math.inf,0.0)
    return ranks,pre_rejected


def beam_select_fibre_design(polynomial, *, n_original, selector, moments,
        apply_qaoa_hard_limits, certified=None):
    """Implement Algorithm 3 ranking/allocation and retain all evaluated incumbents.

    Infeasible native completions do not prune their prefixes. Width truncation
    remains heuristic and does not provide a subtree certificate.
    """
    start=time.perf_counter()
    canonical,cubics,margin,tau,tol,cache,evaluate=_setup(polynomial,n_original,selector,moments,apply_qaoa_hard_limits)
    width=int(selector['search_settings']['beam_width'])
    if width<1:raise ValueError('Beam width must be positive')
    incumbent=evaluate((None,)*len(cubics));incumbent=incumbent if incumbent.feasible else None
    beam=[()]
    for depth,cubic in enumerate(cubics):
        children=[]
        for prefix in beam:
            for action in action_options(cubic):
                child=prefix+(action,);c=evaluate(child+(None,)*(len(cubics)-len(child)))
                children.append((child,c))
                if c.feasible and (incumbent is None or _inc_key(c,cubics)<_inc_key(incumbent,cubics)):incumbent=c
        ranks,rejected=ranking([c for _,c in children],selector,n_original,apply_qaoa_hard_limits)
        b=min(width,len(children));score_count=(b+1)//2
        by_score=sorted(children,key=lambda pc:(not pc[1].feasible,
            math.inf if pc[1].actions in rejected else pc[1].score,
            pc[1].risk.normalised_excess,_stable_actions_key(pc[1].actions)))
        chosen=[p for p,_ in by_score[:score_count]];chosen_set=set(chosen)
        remainder=[pc for pc in children if pc[0] not in chosen_set]
        remainder.sort(key=lambda pc:(not pc[1].feasible,ranks[pc[1].actions][0],
            -ranks[pc[1].actions][1],_stable_actions_key(pc[1].actions)))
        beam=chosen+[p for p,_ in remainder[:b-score_count]]
    if incumbent is None:raise FibreSelectorError('Repaired beam found no feasible design; heuristic failure does not prove infeasibility')
    evaluation=_evaluate_design(canonical,n_original=n_original,actions=incumbent.actions,
        selector=selector,apply_qaoa_hard_limits=apply_qaoa_hard_limits)
    optimum=certified.certified_optimum_score if certified is not None else None
    regret=evaluation.score-optimum if optimum is not None else None
    if regret is not None and regret<0:raise FibreSelectorError('Beam score below supplied certificate')
    return FibreSearchResult(incumbent.actions,evaluation,incumbent.risk,
        'review_v2_algorithm3_raw_moment_beam',len(cache),time.perf_counter()-start,optimum,regret)


@dataclass(frozen=True)
class AnytimeCertificate:
    result: FibreSearchResult | None
    trace: tuple[dict,...]
    explored_nodes: int
    evaluated_leaves: int
    pruned_by_bound: int
    pruned_by_capacity: int
    proof_complete: bool
    final_lower_bound: Fraction | float
    final_upper_bound: Fraction | float
    runtime_sec: float
    termination_reason: str
    feasible_set: str
    numeric_tolerance: float
    frontier: tuple[tuple,...]


def branch_and_bound_fibre_optimum(polynomial, *, n_original, selector, moments,
        trace_interval_nodes=256,apply_qaoa_hard_limits=True,max_nodes=None,
        max_evaluations=None,time_limit_sec=None,stop_requested:Callable[[],bool]|None=None):
    """Return committed frontier bounds on completion or an explicit interruption.

    No incumbent is represented by U=+inf. An infeasible native design does not
    end the search. Limits are checked between atomic node evaluations; an
    evaluation interrupted by KeyboardInterrupt is returned to the frontier.
    """
    from .four_part_addendum import _partial_resource_lower_bound
    start=time.perf_counter()
    canonical,cubics,margin,tau,tol,cache,evaluate=_setup(polynomial,n_original,selector,moments,apply_qaoa_hard_limits)
    for value in [max_nodes,max_evaluations,time_limit_sec]:
        if value is not None and (not math.isfinite(float(value)) or value<0):raise ValueError('Limits must be nonnegative and finite')
    limits=selector['feasibility_limits'];heap=[(Fraction(0),(),0,())];incumbent=None
    count=explored=leaves=pruned_bound=pruned_capacity=0;trace=[];reason='complete'
    def bounds():
        upper=incumbent.score if incumbent is not None else math.inf
        lower=min(upper,heap[0][0]) if heap else upper
        return lower,upper
    def sample(event):
        lower,upper=bounds()
        trace.append(dict(event=event,elapsed_sec=time.perf_counter()-start,explored_nodes=explored,
            evaluated_leaves=leaves,frontier_nodes=len(heap),lower_bound=float(lower),
            upper_bound=float(upper),gap=float(upper-lower) if math.isfinite(float(upper)) else math.inf))
    def stop():
        if max_nodes is not None and explored>=max_nodes:return 'node_limit'
        if time_limit_sec is not None and time.perf_counter()-start>=time_limit_sec:return 'time_limit'
        if stop_requested is not None and stop_requested():return 'requested_stop'
        return None
    if (max_evaluations is None or max_evaluations>0) and not stop():
        try:
            native=evaluate((None,)*len(cubics))
            if native.feasible:incumbent=native
        except KeyboardInterrupt:reason='keyboard_interrupt'
    sample('initial_incumbent' if incumbent is not None else 'no_initial_incumbent')
    while heap and reason!='keyboard_interrupt':
        why=stop()
        if why:reason=why;break
        node=heapq.heappop(heap);lower,key,_,prefix=node
        if incumbent is not None and lower>incumbent.score:pruned_bound+=1;explored+=1;continue
        if len(prefix)==len(cubics):
            if prefix not in cache and max_evaluations is not None and len(cache)>=max_evaluations:
                heapq.heappush(heap,node);reason='evaluation_limit';break
            try:item=evaluate(prefix)
            except KeyboardInterrupt:
                heapq.heappush(heap,node);reason='keyboard_interrupt';break
            leaves+=1
            if item.feasible and (incumbent is None or _inc_key(item,cubics)<_inc_key(incumbent,cubics)):
                incumbent=item;sample('incumbent_update')
        else:
            # Complete expansion is committed atomically; on an interrupt restore
            # the parent before any children become visible.
            children=[];local_capacity=local_bound=0
            try:
                for option,action in enumerate(action_options(cubics[len(prefix)])):
                    child=prefix+(action,)
                    bound,active,penalty=_partial_resource_lower_bound(canonical,cubics,child,selector,margin)
                    if apply_qaoa_hard_limits and (n_original+active>int(limits['maximum_qubits']) or penalty>Fraction(str(limits['maximum_penalty']))):
                        local_capacity+=1;continue
                    if incumbent is not None and bound>incumbent.score:local_bound+=1;continue
                    children.append((bound,key+(option,),child))
            except KeyboardInterrupt:
                heapq.heappush(heap,node);reason='keyboard_interrupt';break
            for bound,childkey,child in children:
                count+=1;heapq.heappush(heap,(bound,childkey,count,child))
            pruned_bound+=local_bound;pruned_capacity+=local_capacity
        explored+=1
        if trace_interval_nodes>0 and explored%trace_interval_nodes==0:sample('node_interval')
    complete=not heap
    if complete:reason='optimal' if incumbent is not None else 'infeasible'
    lower,upper=bounds();result=None
    if incumbent is not None:
        evaluation=_evaluate_design(canonical,n_original=n_original,actions=incumbent.actions,selector=selector,
            apply_qaoa_hard_limits=apply_qaoa_hard_limits)
        if evaluation.score!=incumbent.score:raise AssertionError('Reference and fast scores differ')
        result=FibreSearchResult(incumbent.actions,evaluation,incumbent.risk,
            'review_v2_certified_operational_optimum' if complete else 'review_v2_interrupted_incumbent',
            len(cache),time.perf_counter()-start,incumbent.score if complete else None,Fraction(0) if complete else None)
    sample('proof_complete' if complete else reason)
    return AnytimeCertificate(result,tuple(trace),explored,leaves,pruned_bound,pruned_capacity,
        complete,lower,upper,time.perf_counter()-start,reason,
        'fixed_reference_compiler_raw_moment_diagnostic_le_tau_plus_numeric_tolerance',tol,tuple(heap))
