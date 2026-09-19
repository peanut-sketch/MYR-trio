from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import math
import pandas as pd

REQUIRED_INSTANCE = [
    '01_LINES.csv','02_STATIONS.csv','03_SECTORS.csv','04_LOCATION_SUPPLY.csv',
    '05_BUFFER_LOCATION.csv','06_PARAMETERS.csv','07_PROJECT_DETAILS.csv','08_ACTIVITY_DETAILS.csv'
]

@dataclass
class Instance:
    root: Path
    lines: pd.DataFrame
    stations: pd.DataFrame
    sectors: pd.DataFrame
    supply: pd.DataFrame
    buffers: pd.DataFrame
    params: pd.DataFrame
    projects: pd.DataFrame
    activities: pd.DataFrame
    horizon_start: pd.Timestamp
    horizon_weeks: int


def load_instance(root: str | Path) -> Instance:
    root = Path(root)
    frames = {name: pd.read_csv(root / name) for name in REQUIRED_INSTANCE}
    params = dict(zip(frames['06_PARAMETERS.csv']['key'].astype(str), frames['06_PARAMETERS.csv']['value'].astype(str)))
    return Instance(root, frames['01_LINES.csv'], frames['02_STATIONS.csv'], frames['03_SECTORS.csv'],
                    frames['04_LOCATION_SUPPLY.csv'], frames['05_BUFFER_LOCATION.csv'], frames['06_PARAMETERS.csv'],
                    frames['07_PROJECT_DETAILS.csv'], frames['08_ACTIVITY_DETAILS.csv'],
                    pd.Timestamp(params.get('horizon_start','2027-01-04')), int(params.get('horizon_weeks','30')))


def week_of(date_value, horizon_start):
    return max(1, int((pd.Timestamp(date_value) - pd.Timestamp(horizon_start)).days // 7) + 1)


def week_end(week, horizon_start):
    return pd.Timestamp(horizon_start) + pd.Timedelta(days=(int(week)-1)*7 + 6)


def project_map(inst):
    return inst.projects.set_index('contract_number').to_dict('index')


def activity_map(inst):
    return inst.activities.set_index('activity_id').to_dict('index')


def build_location_paths(inst):
    paths = {}
    for line in inst.lines.line_code.astype(str):
        st = inst.stations[inst.stations.line_code.astype(str)==line].sort_values('seq').station_id.astype(str).tolist()
        for bound in ['EB','WB']:
            loc=[]
            for i,s in enumerate(st):
                loc.append(f'PLAT:{line}:{s}:{bound}')
                if i < len(st)-1:
                    a,b=st[i],st[i+1]
                    loc.append(f'SEC:{line}:{a}_{b}:{bound}')
            paths[(line,bound)] = loc
    return paths


def parse_loc(loc):
    p=str(loc).split(':')
    return (p[1],p[-1]) if len(p)>=4 else (None,None)


def base_work_locations(inst, row, paths):
    s,e=str(row['start_location_id']),str(row['end_location_id'])
    line,bound=parse_loc(s)
    path=paths.get((line,bound),[])
    try:
        i,j=path.index(s),path.index(e)
        if i>j: i,j=j,i
        return path[i:j+1]
    except ValueError:
        return [s] if s==e else [s,e]


def expand_locations(inst, activity_row, project_row, paths):
    base=base_work_locations(inst, activity_row, paths)
    nature=str(project_row['nature_of_activity'])
    bmap=inst.buffers.set_index('nature_of_works')
    buffer_sectors=int(bmap.loc[nature,'up_to_buffer_sectors']) if nature in bmap.index else 0
    opposite=int(bmap.loc[nature,'opposite_bound_required']) if nature in bmap.index else 0
    line,bound=parse_loc(base[0])
    path=paths.get((line,bound),[])
    expanded=set(base)
    if buffer_sectors and path:
        idx=[path.index(x) for x in base if x in path]
        if idx:
            # one sector roughly spans two path positions; include nearby platform/sector locations.
            lo=max(0,min(idx)-2*buffer_sectors); hi=min(len(path)-1,max(idx)+2*buffer_sectors)
            expanded.update(path[lo:hi+1])
    if opposite:
        other='WB' if bound=='EB' else 'EB'
        for x in list(expanded):
            parts=x.split(':'); parts[-1]=other; expanded.add(':'.join(parts))
    # Live work on H01-H02 crosses to the other line at interchange only.
    if nature=='Live' and any(('H01_H02' in x or ':H01:' in x or ':H02:' in x) for x in base):
        otherline='BET' if line=='ALP' else 'ALP'
        for x in list(expanded):
            if 'H01_H02' in x or ':H01:' in x or ':H02:' in x:
                parts=x.split(':'); parts[1]=otherline; expanded.add(':'.join(parts))
    valid=set(inst.supply.location_id.astype(str))
    return sorted(x for x in expanded if x in valid)


def access_units(eclo): return 1.5 if int(eclo)==1 else 1.0


def compute_results(inst, access, scenario):
    x=access.merge(inst.activities[['activity_id','contract_number']],on='activity_id',how='left')
    last=x.groupby('contract_number')['week'].max().to_dict()
    rows=[]
    for _,p in inst.projects.iterrows():
        w=int(last.get(p.contract_number,1)); completion=week_end(w,inst.horizon_start)
        planned=pd.Timestamp(p.planned_completion_date); over=max(0,int((completion-planned).days))
        rows.append({'scenario':scenario,'contract_number':p.contract_number,
                     'simulated_completion_date':completion.date().isoformat(),'overrun_days':over})
    return pd.DataFrame(rows)


def score_schedule(inst, access, occupancy, scenario):
    results=compute_results(inst,access,scenario)
    proj=inst.projects.set_index('contract_number')
    # priority overrun by contract tier
    priority_overrun={'1':0,'2':0,'3':0}
    for _,r in results.iterrows():
        tier=str(int(proj.loc[r.contract_number,'contract_priority']))
        priority_overrun[tier]+=int(r.overrun_days)
    # conservative weighted contract delay (activity nudge represented by max late activity priority factor)
    weights={1:100,2:10,3:1}; nudges={1:.3,2:.2,3:0}
    weighted=0.0
    for _,r in results.iterrows():
        if r.overrun_days<=0: continue
        p=proj.loc[r.contract_number]; acts=inst.activities[inst.activities.contract_number==r.contract_number]
        nudge=max([nudges.get(int(x),0) for x in acts.activity_priority] or [0])
        weighted += weights.get(int(p.contract_priority),1)*(1+nudge)*int(r.overrun_days)
    supply=inst.supply.set_index('location_id').supply_capacity.to_dict()
    groups=occupancy.groupby(['location_id','week']).co_share_group.nunique().reset_index(name='used') if len(occupancy) else pd.DataFrame(columns=['location_id','week','used'])
    excess=0; hotspots=[]
    for _,g in groups.iterrows():
        cap=int(supply.get(g.location_id,0)); ex=max(0,int(g.used)-cap); excess+=ex
        if int(g.used)>=cap: hotspots.append({'location_id':g.location_id,'week':int(g.week),'used':int(g.used),'capacity':cap,'excess':ex})
    eclo=int(pd.to_numeric(access.eclo,errors='coerce').fillna(0).sum())
    if scenario=='A': objective=weighted
    elif scenario=='B': objective=7*excess+5*eclo
    else: objective=weighted+7*excess+5*eclo
    return {'scenario':scenario,'overrun_days_total':int(results.overrun_days.sum()),
            'contracts_overrunning':int((results.overrun_days>0).sum()),'excess_access_nights_total':int(excess),
            'eclo_nights_total':eclo,'priority_overrun':priority_overrun,'priority_weighted_score':round(weighted,2),
            'objective_score':round(objective,2),'capacity_hotspots':hotspots}


def validate(inst, access, occupancy, scenario):
    v=[]; A=inst.activities.set_index('activity_id'); P=inst.projects.set_index('contract_number')
    # schema and workload
    expected_access=['activity_id','access_seq','week','eclo','access_night']; expected_occ=['activity_id','week','location_id','co_share_group']
    if list(access.columns)!=expected_access: v.append({'rule':'schema','detail':f'SCHEDULE_ACCESS columns must be {expected_access}'})
    if list(occupancy.columns)!=expected_occ: v.append({'rule':'schema','detail':f'SCHEDULE_OCCUPANCY columns must be {expected_occ}'})
    for aid,row in A.iterrows():
        s=access[access.activity_id.astype(str)==str(aid)]
        units=sum(access_units(x) for x in s.eclo) if len(s) else 0
        if units+1e-9 < float(row.total_accesses): v.append({'rule':'workload','detail':f'{aid}: {units:g}/{row.total_accesses} work units'})
        if len(s):
            if int(s.week.min()) < week_of(row.planned_start_date,inst.horizon_start): v.append({'rule':'planned_start','detail':f'{aid}: starts week {int(s.week.min())} too early'})
            if s.groupby('week').size().max()>1: v.append({'rule':'activity_week','detail':f'{aid}: more than one access in a week'})
    # predecessor
    first=access.groupby('activity_id').week.min().to_dict(); last=access.groupby('activity_id').week.max().to_dict()
    for aid,row in A.iterrows():
        pred=row.get('predecessor_activity_id')
        if pd.notna(pred) and str(pred).strip() and str(pred) in last and aid in first and int(first[aid])<=int(last[str(pred)]):
            v.append({'rule':'predecessor','detail':f'{aid}: first wk {int(first[aid])} must be > {pred} final wk {int(last[str(pred)])}'})
    # weekly allocation/workfront
    X=access.merge(inst.activities[['activity_id','contract_number','activity_type']],on='activity_id',how='left')
    for (c,t,w),g in X.groupby(['contract_number','activity_type','week']):
        pp=inst.projects[(inst.projects.contract_number==c)&(inst.projects.activity_type==t)]
        if pp.empty: continue
        p=pp.iloc[0]; cap=int(p.number_of_maximum_access_per_week); wf=int(p.number_of_workfronts)
        if g.access_night.nunique()>cap: v.append({'rule':'weekly_allocation','detail':f'{c}/{t} wk{w}: {g.access_night.nunique()} nights > {cap}'})
        for n,gg in g.groupby('access_night'):
            if gg.activity_id.nunique()>wf: v.append({'rule':'workfront','detail':f'{c}/{t} wk{w} night{n}: {gg.activity_id.nunique()} activities > {wf}'})
    # ECLO rules
    if scenario=='A' and int(access.eclo.sum())>0: v.append({'rule':'eclo','detail':'Scenario A forbids ECLO'})
    # planned completion in B
    if scenario=='B':
        R=compute_results(inst,access,'B')
        for _,r in R[R.overrun_days>0].iterrows(): v.append({'rule':'planned_date','detail':f'{r.contract_number}: {int(r.overrun_days)} days late'})
    # capacity / legal mixes based on possession groups
    supply=inst.supply.set_index('location_id').supply_capacity.to_dict()
    O=occupancy.merge(inst.activities[['activity_id','contract_number']],on='activity_id',how='left').merge(inst.projects[['contract_number','access_type']],on='contract_number',how='left')
    for (loc,w),g in O.groupby(['location_id','week']):
        used=g.co_share_group.nunique(); cap=int(supply.get(loc,0)); allowance=999999 if scenario=='B' else (1 if scenario=='C' else 0)
        if used>cap+allowance: v.append({'rule':'capacity','detail':f'wk{w} {loc}: {used} possessions > {cap}+{allowance}'})
        for grp,gg in g.groupby('co_share_group'):
            types=gg.drop_duplicates('activity_id').access_type.astype(str).tolist()
            if 'PM' in types:
                if len(types)>1: v.append({'rule':'legal_mix','detail':f'wk{w} {loc}/{grp}: PM must be alone'})
            elif types.count('PC')>1 or (types.count('PC')==1 and any(x not in ('PC','C') for x in types)) or (types.count('PC')==1 and types.count('C')>3) or (types.count('PC')==0 and (any(x!='C' for x in types) or types.count('C')>4)):
                v.append({'rule':'legal_mix','detail':f'wk{w} {loc}/{grp}: illegal possession mix {types}'})
    # occupancy presence for every access activity-week
    have=set(zip(occupancy.activity_id.astype(str),occupancy.week.astype(int)))
    for _,r in access.iterrows():
        if (str(r.activity_id),int(r.week)) not in have: v.append({'rule':'occupancy','detail':f'{r.activity_id} wk{r.week}: missing occupancy'})
    return v


def output_zip_bytes(access,occupancy,results):
    import io, zipfile
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('SCHEDULE_ACCESS.csv',access.to_csv(index=False))
        z.writestr('SCHEDULE_OCCUPANCY.csv',occupancy.to_csv(index=False))
        z.writestr('RESULTS.csv',results.to_csv(index=False))
    return b.getvalue()


def _shift_activity(access,occupancy,aid,delta):
    access.loc[access.activity_id.astype(str)==str(aid),'week'] += int(delta)
    occupancy.loc[occupancy.activity_id.astype(str)==str(aid),'week'] += int(delta)


def _repair_dependencies(inst,access,occupancy):
    moves=[]
    for _ in range(len(inst.activities)+2):
        changed=False; first=access.groupby('activity_id').week.min().to_dict(); last=access.groupby('activity_id').week.max().to_dict()
        for _,r in inst.activities.iterrows():
            aid=str(r.activity_id); pred=r.predecessor_activity_id
            if pd.notna(pred) and str(pred).strip() and aid in first and str(pred) in last:
                need=int(last[str(pred)])+1
                if int(first[aid])<need:
                    d=need-int(first[aid]); _shift_activity(access,occupancy,aid,d); moves.append((aid,int(first[aid]),need,'predecessor repair')); changed=True
        if not changed: break
    return moves


def replan_emergency(inst,base_access,base_occ,urgent_activity,target_week):
    access=base_access.copy(); occ=base_occ.copy(); notes=[]; moves=[]
    aid=str(urgent_activity); s=access[access.activity_id.astype(str)==aid].sort_values('access_seq')
    if s.empty: return access,occ,moves,[f'{aid} is not scheduled']
    ar=inst.activities[inst.activities.activity_id.astype(str)==aid].iloc[0]
    minw=week_of(ar.planned_start_date,inst.horizon_start); pred=ar.predecessor_activity_id
    if pd.notna(pred) and str(pred).strip():
        pw=access[access.activity_id.astype(str)==str(pred)].week
        if len(pw): minw=max(minw,int(pw.max())+1)
    target=max(int(target_week),minw); delta=target-int(s.week.min())
    if target!=int(target_week): notes.append(f'Requested week adjusted to {target} to satisfy planned-start/predecessor rules.')
    if delta:
        oldweeks=sorted(s.week.unique()); _shift_activity(access,occ,aid,delta); moves.append((aid,min(oldweeks),min(oldweeks)+delta,'urgent request'))
    moves += _repair_dependencies(inst,access,occ)
    return access.sort_values(['week','access_night','activity_id','access_seq']).reset_index(drop=True), occ.sort_values(['week','location_id','activity_id']).reset_index(drop=True), moves, notes


# ---------------------------------------------------------------------------
# Closure zones (span + buffer sectors, Live mirror + interchange cross-over)
# ---------------------------------------------------------------------------
def closure_zone(inst, aid, paths=None, _cache={}):
    """All locations an activity closes on its night (excluding nothing).
    Buffer = N sectors beyond the worked sectors on each side (05_BUFFER_LOCATION);
    Live also mirrors to the opposite bound and closes the other line's H01-H02."""
    key = (id(inst), str(aid))
    if key in _cache: return _cache[key]
    paths = paths or build_location_paths(inst)
    row = inst.activities.set_index('activity_id').loc[aid]
    nature = str(inst.projects.set_index('contract_number').loc[row.contract_number, 'nature_of_activity'])
    bmap = inst.buffers.set_index('nature_of_works')
    b = int(bmap.loc[nature, 'up_to_buffer_sectors']) if nature in bmap.index else 0
    opp = int(bmap.loc[nature, 'opposite_bound_required']) if nature in bmap.index else 0
    base = base_work_locations(inst, row, paths)
    line, bound = parse_loc(base[0]); path = paths.get((line, bound), [])
    zone = set(base)
    idx = [path.index(x) for x in base if x in path]
    if b and idx:
        zone.update(path[max(0, min(idx) - 2 * b): max(idx) + 2 * b + 1])
    if opp:
        other = 'WB' if bound == 'EB' else 'EB'
        zone |= {':'.join(x.split(':')[:-1] + [other]) for x in list(zone)}
    if nature == 'Live':
        otherline = 'BET' if line == 'ALP' else 'ALP'
        for x in list(zone):
            if 'H01_H02' in x or ':H01:' in x or ':H02:' in x:
                p = x.split(':'); p[1] = otherline; zone.add(':'.join(p))
    valid = set(inst.supply.location_id.astype(str))
    _cache[key] = zone & valid
    return _cache[key]


def closure_violations(inst, occupancy):
    """Approximation of the judge's `closure` rule: activity Y may not occupy X's buffer
    in the same week unless the two share a location (i.e. co-share, or are split onto
    separate nights by co_share_group there)."""
    v = []; paths = build_location_paths(inst); known = set(inst.activities.activity_id.astype(str))
    for w, gw in occupancy.groupby('week'):
        spans = {str(a): set(g.location_id) for a, g in gw.groupby('activity_id') if str(a) in known}
        for x, xs in spans.items():
            buf = closure_zone(inst, x, paths) - xs
            if not buf: continue
            for y, ys in spans.items():
                if y != x and (ys & buf) and not (ys & xs):
                    v.append({'rule': 'closure', 'detail': f'wk{w}: {y} inside closure of {x} at {sorted(ys & buf)}'})
    return v


# ---------------------------------------------------------------------------
# Scenario B: hit every planned completion date at least ECLO / excess cost
# ---------------------------------------------------------------------------
def deadline_week(inst, contract):
    """Last week whose week_end is on/before the contract's planned completion date."""
    planned = pd.Timestamp(inst.projects.set_index('contract_number').loc[contract, 'planned_completion_date'])
    return max(1, ((planned - inst.horizon_start).days - 6) // 7 + 1)


def plan_scenario_b(inst, base_access, base_occ):
    """Repair a base plan so no contract overruns (Scenario B). Levers, cheapest first:
    1) pull late accesses into a clean earlier week (0 cost),
    2) ECLO-compress an activity and drop its late tail accesses (5 per ECLO night),
    3) bump a blocking access to another clean week, then pull the late access in,
    4) as a last resort accept extra access-nights above supply (7 each)."""
    access = base_access.copy(); occ = base_occ.copy(); changes = []; notes = []
    paths = build_location_paths(inst)
    A = inst.activities.assign(activity_id=inst.activities.activity_id.astype(str)).set_index('activity_id')
    P = inst.projects.set_index(['contract_number', 'activity_type'])
    supply = inst.supply.set_index('location_id').supply_capacity.to_dict()
    dl = {c: deadline_week(inst, c) for c in inst.projects.contract_number}
    access['activity_id'] = access.activity_id.astype(str); occ['activity_id'] = occ.activity_id.astype(str)
    span = {a: sorted(set(g.location_id)) for a, g in occ.groupby('activity_id')}

    def weeks(a): return sorted(access.loc[access.activity_id == a, 'week'].astype(int))

    def window(a):
        r = A.loc[a]; lo = week_of(r.planned_start_date, inst.horizon_start)
        pred = r.predecessor_activity_id
        if pd.notna(pred) and str(pred).strip() and weeks(str(pred)): lo = max(lo, weeks(str(pred))[-1] + 1)
        hi = min(dl[r.contract_number], inst.horizon_weeks)
        for s in A.index[A.predecessor_activity_id.astype(str) == a]:
            if weeks(s): hi = min(hi, weeks(s)[0] - 1)
        return lo, hi

    def free_night(a, w):
        r = A.loc[a]; p = P.loc[(r.contract_number, r.activity_type)]
        X = access.merge(inst.activities[['activity_id', 'contract_number', 'activity_type']].astype({'activity_id': str}), on='activity_id')
        same = X[(X.contract_number == r.contract_number) & (X.activity_type == r.activity_type) & (X.week == w) & (X.activity_id != a)]
        for n in range(1, int(p.number_of_maximum_access_per_week) + 1):
            if same[same.access_night == n].activity_id.nunique() < int(p.number_of_workfronts): return n
        return None

    def check(a, w):
        """(blockers, excess) for placing activity a in week w. Strict: no buffer contact at all."""
        S = set(span[a]); mybuf = closure_zone(inst, a, paths) - S; blockers = set()
        gw = occ[(occ.week == w) & (occ.activity_id != a)]
        for x, gx in gw.groupby('activity_id'):
            xs = set(gx.location_id); xbuf = closure_zone(inst, x, paths) - xs
            if (S & xbuf) or (mybuf & xs) or (mybuf & xbuf): blockers.add(x)
        excess = sum(1 for L in S if gw[gw.location_id == L].co_share_group.nunique() + 1 > int(supply.get(L, 0)))
        return blockers, excess

    def contact(a, w):   # shares any location with other work that week (prefer weeks where it doesn't)
        return bool(set(span[a]) & set(occ[(occ.week == w) & (occ.activity_id != a)].location_id))

    def best_clean(a, exclude=()):
        ok = [t for t in candidates(a, exclude) if check(a, t) == (set(), 0)]
        return min(ok, key=lambda t: (contact(a, t), -t)) if ok else None

    def move(a, w_from, w_to, reason):
        nonlocal occ
        n = free_night(a, w_to)
        m = (access.activity_id == a) & (access.week == w_from)
        access.loc[m, ['week', 'access_night']] = [w_to, n]
        occ = occ[~((occ.activity_id == a) & (occ.week == w_from))]
        rows = []
        for L in span[a]:
            used = set(occ[(occ.location_id == L) & (occ.week == w_to)].co_share_group)
            rows.append({'activity_id': a, 'week': w_to, 'location_id': L,
                         'co_share_group': next(f'b{i}' for i in range(1, 99) if f'b{i}' not in used)})
        occ = pd.concat([occ, pd.DataFrame(rows)], ignore_index=True)
        changes.append((a, w_from, w_to, reason))

    def candidates(a, exclude=()):
        lo, hi = window(a); have = set(weeks(a))
        return [w for w in range(hi, lo - 1, -1) if w not in have and w not in exclude and free_night(a, w)]

    def late():
        return [(a, w) for a in A.index for w in weeks(a) if w > dl[A.loc[a, 'contract_number']]]

    def pull_clean(reason='pulled forward (free slot)'):
        for a, w in late():
            t = best_clean(a)
            if t is not None: move(a, w, t, reason)

    def compress():
        nonlocal occ
        for a in sorted({a for a, _ in late()}):
            d = dl[A.loc[a, 'contract_number']]; s = access[access.activity_id == a]
            keep = s[s.week <= d].sort_values('week', ascending=False)
            need = float(A.loc[a, 'total_accesses']); units = sum(access_units(x) for x in keep.eclo)
            convert = []
            for i, r in keep.iterrows():
                if units + 1e-9 >= need: break
                if int(r.eclo) == 0: convert.append(i); units += 0.5
            if units + 1e-9 < need: continue            # ECLO alone cannot absorb it
            for i in convert:
                access.loc[i, 'eclo'] = 1; changes.append((a, int(access.loc[i, 'week']), int(access.loc[i, 'week']), 'converted to ECLO (1.5 units)'))
            for w in sorted(s[s.week > d].week):
                access.drop(access[(access.activity_id == a) & (access.week == w)].index, inplace=True)
                occ = occ[~((occ.activity_id == a) & (occ.week == w))]
                changes.append((a, int(w), None, 'dropped (covered by ECLO)'))

    def bump_blockers():
        nonlocal access, occ
        for a, w in late():
            for t in candidates(a):
                blockers, _ = check(a, t)
                snap = (access.copy(), occ.copy(), len(changes)); ok = True
                for x in blockers:
                    t2 = best_clean(x, exclude=(t,))
                    if t2 is None: ok = False; break
                    move(x, t, t2, f'bumped to make room for {a}')
                if ok and not check(a, t)[0]:
                    move(a, w, t, 'pulled forward after re-slotting blocker(s)'); break
                access, occ = snap[0], snap[1]; del changes[snap[2]:]

    def accept_excess():
        for a, w in late():
            opts = [(check(a, t)[1], -t, t) for t in candidates(a) if not check(a, t)[0]]
            if opts: move(a, w, min(opts)[2], 'pulled forward using extra access-night(s)')

    pull_clean(); compress(); pull_clean(); bump_blockers(); accept_excess()
    for a, w in late(): notes.append(f'Scenario B: {a} still late in week {w} — no feasible repair found.')
    access = access.sort_values(['activity_id', 'week']).reset_index(drop=True)
    access['access_seq'] = access.groupby('activity_id').cumcount() + 1
    access = access[['activity_id', 'access_seq', 'week', 'eclo', 'access_night']].astype({'week': int, 'eclo': int, 'access_night': int})
    occ = occ.sort_values(['activity_id', 'week', 'location_id']).reset_index(drop=True)
    return access, occ, changes, notes
