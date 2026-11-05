"""Exact numeric comparison kernel for a proposed committed data-API policy.

This is not a complete FairBind predicate: the caller must first validate purchase,
receipt, claims/commitment hashes, source identity/authenticity, and object limits.
Never construct trusted observations from an unverified seller-supplied list.
"""
from dataclasses import dataclass
from fractions import Fraction
import re
from typing import Dict, List, Optional, Tuple

@dataclass(frozen=True)
class FieldPolicy:
    unit: str
    absolute: str
    relative: str
    reference_spread: str

@dataclass(frozen=True)
class Policy:
    source_ids: Tuple[str, ...]
    quorum: int
    reference_time: int
    max_skew: int
    fields: Dict[str, FieldPolicy]

@dataclass(frozen=True)
class Observation:
    source: str
    observed_at: int
    values: Dict[str, str]
    units: Dict[str, str]

@dataclass(frozen=True)
class Comparison:
    verdict: str
    reason: str
    sources: Tuple[str, ...] = ()
    medians: Optional[Dict[str, str]] = None

def number(value):
    if not isinstance(value,str) or len(value)>128 or not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?',value):
        raise ValueError('unsupported decimal')
    return Fraction(value)

def compare(policy: Policy, response: Optional[Dict[str,str]], observations: List[Observation]) -> Comparison:
    """PASS/FAIL are class-comparison results, not signed protocol verdicts.

Policy: all selected fields are required. At least quorum distinct authorized
sources must have fresh, complete, unit-matching observations. All such sources
must agree within each committed reference spread; otherwise INCONCLUSIVE.
Compare the response with the exact median using absolute + relative tolerance.
"""
    inconclusive=lambda reason:Comparison('INCONCLUSIVE',reason)
    if response is None:return inconclusive('missing response')
    if not (1<=len(policy.source_ids)<=64 and len(set(policy.source_ids))==len(policy.source_ids)
            and 1<=policy.quorum<=len(policy.source_ids) and 1<=len(policy.fields)<=64
            and type(policy.reference_time) is int and type(policy.max_skew) is int
            and policy.reference_time>=0 and policy.max_skew>=0 and len(observations)<=64):
        return inconclusive('invalid policy or observation limit')
    try:
        limits={k:(number(v.absolute),number(v.relative),number(v.reference_spread)) for k,v in policy.fields.items()}
        if any(n<0 for values in limits.values() for n in values):raise ValueError('negative tolerance')
    except (ValueError,TypeError):return inconclusive('invalid numeric policy')
    seen=set();valid=[]
    for obs in observations:
        if obs.source in seen:return inconclusive('duplicate source')
        seen.add(obs.source)
        if obs.source not in policy.source_ids:return inconclusive('unregistered source')
        if type(obs.observed_at) is not int or abs(obs.observed_at-policy.reference_time)>policy.max_skew:continue
        try:
            values={key:number(obs.values[key]) for key in policy.fields}
            if any(obs.units.get(key)!=p.unit for key,p in policy.fields.items()):continue
        except (ValueError,TypeError,KeyError):continue
        valid.append((obs.source,values))
    if len(valid)<policy.quorum:return inconclusive('reference quorum unavailable')
    medians={}
    for key in policy.fields:
        values=sorted(row[key] for _,row in valid)
        if values[-1]-values[0]>limits[key][2]:return inconclusive('references disagree')
        median=(values[(len(values)-1)//2]+values[len(values)//2])/2
        medians[key]=median
    sources=tuple(sorted(source for source,_ in valid));serialized={k:str(v) for k,v in medians.items()}
    if any(key not in response for key in medians):
        return Comparison('FAIL','required field absent',sources,serialized)
    try: values={key:number(response[key]) for key in medians}
    except (ValueError,TypeError):return inconclusive('unsupported response numeric encoding')
    for key,median in medians.items():
        absolute,relative,_=limits[key]
        if abs(values[key]-median)>absolute+relative*abs(median):
            return Comparison('FAIL','tolerance exceeded',sources,serialized)
    return Comparison('PASS','all selected fields within tolerance',sources,serialized)
