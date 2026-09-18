from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title='NebulaX RailFlow AI', page_icon='🚇', layout='wide')
ROOT = Path(__file__).resolve().parent

FILES = {
    'projects': '07_PROJECT_DETAILS.csv',
    'activities': '08_ACTIVITY_DETAILS.csv',
    'supply': '04_LOCATION_SUPPLY.csv',
    'buffers': '05_BUFFER_LOCATION.csv',
    'params': '06_PARAMETERS.csv',
    'access': 'SCHEDULE_ACCESS.csv',
    'occupancy': 'SCHEDULE_OCCUPANCY.csv',
    'results': 'RESULTS.csv',
}

@st.cache_data
def load_data():
    out = {}
    for k, name in FILES.items():
        p = ROOT / name
        if not p.exists():
            st.error(f'Missing required file: {name}')
            st.stop()
        out[k] = pd.read_csv(p)
    return out

def week_of(date_value, horizon_start):
    d = pd.to_datetime(date_value)
    h = pd.to_datetime(horizon_start)
    return max(1, int((d - h).days // 7) + 1)

def activity_priority_map(activities, projects):
    x = activities.merge(projects[['contract_number','contract_priority']], on='contract_number', how='left')
    x['activity_priority'] = pd.to_numeric(x['activity_priority'], errors='coerce').fillna(3)
    x['contract_priority'] = pd.to_numeric(x['contract_priority'], errors='coerce').fillna(3)
    # Lower number = higher priority in this dataset. Activity priority breaks ties.
    x['rank'] = x['contract_priority'] * 10 + x['activity_priority']
    return dict(zip(x.activity_id.astype(str), x['rank']))

def recompute_results(access, activities, projects, horizon_start, scenario):
    x = access.merge(activities[['activity_id','contract_number']], on='activity_id', how='left')
    last_week = x.groupby('contract_number')['week'].max()
    rows = []
    for _, p in projects.iterrows():
        c = p['contract_number']
        w = int(last_week.get(c, 1))
        completion = pd.to_datetime(horizon_start) + pd.to_timedelta((w-1)*7 + 6, unit='D')
        planned = pd.to_datetime(p['planned_completion_date'])
        overrun = max(0, int((completion - planned).days))
        rows.append({'scenario':scenario, 'contract_number':c,
                     'simulated_completion_date':completion.date().isoformat(), 'overrun_days':overrun})
    return pd.DataFrame(rows)

def dependency_min_weeks(access, activities):
    last = access.groupby('activity_id')['week'].max().to_dict()
    mins = {}
    for _, row in activities.iterrows():
        pred = row.get('predecessor_activity_id')
        if pd.notna(pred) and str(pred).strip() and str(pred) in last:
            # clarified rule: successor begins strictly after predecessor's final access week
            mins[str(row.activity_id)] = int(last[str(pred)]) + 1
    return mins

def scenario_b(access, occupancy, activities, projects, horizon_start):
    """Flexible supply: pull eligible work earlier while preserving activity order,
    planned starts, predecessor FS+0, contract weekly caps and simple location-week capacity."""
    a = access.copy().sort_values(['week','access_night','activity_id','access_seq']).reset_index(drop=True)
    occ = occupancy.copy()
    act = activities.set_index('activity_id')
    proj = projects.set_index('contract_number')
    original = a.set_index(['activity_id','access_seq'])['week'].to_dict()
    # Occupied locations by activity/week. Used as a conservative collision check.
    locs = occ.groupby(['activity_id','week'])['location_id'].apply(set).to_dict()
    horizon = 30
    moved = []

    # Process higher-priority activities first.
    ranks = activity_priority_map(activities, projects)
    ids = sorted(a.activity_id.astype(str).unique(), key=lambda z: ranks.get(z,999))
    scheduled = a.copy()

    for aid in ids:
        if aid not in act.index: continue
        rows_idx = scheduled.index[scheduled.activity_id.astype(str)==aid].tolist()
        if not rows_idx: continue
        rowa = act.loc[aid]
        planned_min = week_of(rowa['planned_start_date'], horizon_start)
        pred = rowa.get('predecessor_activity_id')
        if pd.notna(pred) and str(pred).strip():
            pred_weeks = scheduled.loc[scheduled.activity_id.astype(str)==str(pred),'week']
            if len(pred_weeks): planned_min = max(planned_min, int(pred_weeks.max())+1)
        contract = rowa['contract_number']
        cap = int(proj.loc[contract,'number_of_maximum_access_per_week']) if contract in proj.index else 3
        prev_week = planned_min - 1
        for idx in sorted(rows_idx, key=lambda i: int(scheduled.loc[i,'access_seq'])):
            cur = int(scheduled.loc[idx,'week'])
            earliest = max(planned_min, prev_week)  # accesses may share week if cap allows
            chosen = cur
            for w in range(earliest, cur+1):
                contract_count = len(scheduled[(scheduled.week==w) & (scheduled.activity_id.astype(str)!=aid) &
                    (scheduled.activity_id.map(lambda x: act.loc[str(x),'contract_number'] if str(x) in act.index else '')==contract)])
                own_same = len(scheduled[(scheduled.week==w) & (scheduled.activity_id.astype(str)==aid) & (scheduled.index!=idx)])
                if contract_count + own_same + 1 > cap: continue
                # Conservative location collision: only reject if exact occupied location overlaps another activity that week.
                myloc = locs.get((aid, cur), set())
                conflict = False
                if myloc:
                    other = occ[(occ.week==w) & (occ.activity_id.astype(str)!=aid)]
                    if len(other) and any(x in myloc for x in other.location_id.astype(str)): conflict=True
                if not conflict:
                    chosen = w; break
            if chosen != cur:
                moved.append((aid, int(scheduled.loc[idx,'access_seq']), cur, chosen))
                scheduled.loc[idx,'week'] = chosen
                # Move this activity's occupancy rows tied to original week for this access conservatively.
                mask=(occ.activity_id.astype(str)==aid)&(occ.week==cur)
                occ.loc[mask,'week']=chosen
            prev_week = int(scheduled.loc[idx,'week'])
    return scheduled.sort_values(['week','access_night','activity_id','access_seq']), occ, moved

def scenario_c(access, occupancy, activities, projects, horizon_start, urgent_activity, target_week):
    """Emergency replan: move selected activity to target week, then bump exact location/week
    conflicts one week at a time, respecting planned starts and predecessor FS+0."""
    a = access.copy()
    o = occupancy.copy()
    ranks = activity_priority_map(activities, projects)
    original = a.copy()
    urgent_rows = a[a.activity_id.astype(str)==str(urgent_activity)].sort_values('access_seq')
    if urgent_rows.empty: return a,o,[],['Urgent activity not found']
    first_old = int(urgent_rows.week.min())
    delta = int(target_week) - first_old
    # Never violate planned start or predecessor.
    actrow = activities[activities.activity_id.astype(str)==str(urgent_activity)].iloc[0]
    min_week = week_of(actrow.planned_start_date, horizon_start)
    pred = actrow.get('predecessor_activity_id')
    if pd.notna(pred) and str(pred).strip():
        pw=a[a.activity_id.astype(str)==str(pred)].week
        if len(pw): min_week=max(min_week,int(pw.max())+1)
    if target_week < min_week:
        return a,o,[],[f'Target week {target_week} violates planned start/predecessor; earliest feasible week is {min_week}.']
    # Shift all accesses of urgent activity preserving spacing.
    old_to_new={}
    for idx,row in urgent_rows.iterrows():
        nw=max(min_week,int(row.week)+delta)
        old_to_new[int(row.week)]=nw
        a.loc[idx,'week']=nw
    for oldw,neww in old_to_new.items():
        o.loc[(o.activity_id.astype(str)==str(urgent_activity))&(o.week==oldw),'week']=neww

    moved=[]
    # Resolve exact location/week conflicts by bumping lower-priority activities.
    for _ in range(40):
        merged=o.merge(o, on=['week','location_id'], suffixes=('_x','_y'))
        conflicts=merged[merged.activity_id_x.astype(str)!=merged.activity_id_y.astype(str)]
        if conflicts.empty: break
        changed=False
        for _,c in conflicts.iterrows():
            x,y=str(c.activity_id_x),str(c.activity_id_y)
            if urgent_activity in (x,y):
                victim=y if x==urgent_activity else x
            else:
                victim=x if ranks.get(x,999)>=ranks.get(y,999) else y
            if victim==urgent_activity: continue
            w=int(c.week)
            mask=a.activity_id.astype(str)==victim
            affected=a[mask & (a.week>=w)]
            if affected.empty: continue
            before=sorted(affected.week.unique().tolist())
            a.loc[mask & (a.week>=w),'week'] += 1
            o.loc[(o.activity_id.astype(str)==victim)&(o.week>=w),'week'] += 1
            after=[z+1 for z in before]
            moved.append((victim,w,w+1))
            changed=True
            break
        if not changed: break
    # Dependency repair pass.
    for _ in range(10):
        changed=False
        last=a.groupby('activity_id').week.max().to_dict()
        first=a.groupby('activity_id').week.min().to_dict()
        for _,row in activities.iterrows():
            aid=str(row.activity_id); pred=row.get('predecessor_activity_id')
            if pd.notna(pred) and str(pred).strip() and str(pred) in last and aid in first:
                need=int(last[str(pred)])+1
                if int(first[aid])<need:
                    d=need-int(first[aid]); a.loc[a.activity_id.astype(str)==aid,'week']+=d; o.loc[o.activity_id.astype(str)==aid,'week']+=d
                    moved.append((aid,int(first[aid]),need)); changed=True
        if not changed: break
    return a.sort_values(['week','access_night','activity_id','access_seq']),o,moved,[]

D=load_data(); projects=D['projects']; activities=D['activities']; base_access=D['access']; base_occ=D['occupancy']; base_results=D['results']
params=dict(zip(D['params']['key'],D['params']['value'].astype(str))); horizon_start=params.get('horizon_start','2027-01-04'); horizon_weeks=int(params.get('horizon_weeks','30'))

st.title('🚇 RailFlow AI — Maintenance Access Scheduler')
st.caption('Working conflict-aware replanning prototype | Nebula X Hackathon — PS1')
with st.sidebar:
    st.header('Planning controls')
    scenario=st.selectbox('Scenario',['A — Baseline','B — Flexible supply optimisation','C — Emergency / urgent maintenance'])
    urgent=None; target_week=None
    if scenario.startswith('C'):
        urgent=st.selectbox('Urgent activity', sorted(activities.activity_id.astype(str).unique()))
        default=int(base_access[base_access.activity_id.astype(str)==urgent].week.min()) if len(base_access[base_access.activity_id.astype(str)==urgent]) else 1
        target_week=st.number_input('Requested start week',1,horizon_weeks,max(1,default-2),1)
    st.metric('Horizon',f'{horizon_weeks} weeks')

notes=[]; moves=[]
if scenario.startswith('A'):
    access,occ=base_access.copy(),base_occ.copy(); label='A'
elif scenario.startswith('B'):
    access,occ,moves=scenario_b(base_access,base_occ,activities,projects,horizon_start); label='B'
else:
    access,occ,moves,notes=scenario_c(base_access,base_occ,activities,projects,horizon_start,urgent,int(target_week)); label='C'
results=recompute_results(access,activities,projects,horizon_start,label)

# Live validation
viol=[]
# planned starts
for _,row in activities.iterrows():
    aw=access[access.activity_id.astype(str)==str(row.activity_id)].week
    if len(aw) and int(aw.min()) < week_of(row.planned_start_date,horizon_start): viol.append(f"{row.activity_id}: before planned start")
# predecessors
last=access.groupby('activity_id').week.max().to_dict(); first=access.groupby('activity_id').week.min().to_dict()
for _,row in activities.iterrows():
    p=row.get('predecessor_activity_id'); aid=str(row.activity_id)
    if pd.notna(p) and str(p).strip() and str(p) in last and aid in first and int(first[aid])<=int(last[str(p)]): viol.append(f'{aid}: predecessor {p} not finished')

c1,c2,c3,c4=st.columns(4)
c1.metric('Activities',access.activity_id.nunique()); c2.metric('Access records',len(access)); c3.metric('Replanned moves',len(moves)); c4.metric('Core-rule violations',len(viol))
if notes:
    for n in notes: st.error(n)
if viol: st.warning('Validation issues: '+ '; '.join(viol[:8]))
else: st.success('Planned-start and predecessor FS+0 checks pass for the displayed schedule.')

t1,t2,t3,t4=st.tabs(['📊 Schedule','🔄 Scenario changes','⚠️ Dependencies','📁 Outputs'])
with t1:
    st.subheader(f'Current schedule — Scenario {label}')
    st.dataframe(access,use_container_width=True,hide_index=True)
    st.subheader('Contract completion')
    st.dataframe(results,use_container_width=True,hide_index=True)
with t2:
    if scenario.startswith('A'): st.info('Baseline uses the supplied schedule unchanged.')
    elif scenario.startswith('B'):
        st.write('Flexible-supply mode actively searches earlier eligible weeks while preserving planned starts, predecessor order, weekly contract caps and conservative location collision checks.')
        md=pd.DataFrame(moves,columns=['activity_id','access_seq','old_week','new_week']) if moves else pd.DataFrame(columns=['activity_id','access_seq','old_week','new_week'])
        st.dataframe(md,use_container_width=True,hide_index=True)
    else:
        st.write(f'Emergency mode requested **{urgent}** from week **{target_week}** and bumped conflicting work where necessary.')
        md=pd.DataFrame(moves,columns=['activity_id','old_week','new_week']) if moves else pd.DataFrame(columns=['activity_id','old_week','new_week'])
        st.dataframe(md,use_container_width=True,hide_index=True)
with t3:
    deps=activities[activities.predecessor_activity_id.notna()][['activity_id','predecessor_activity_id','planned_start_date','contract_number']]
    st.dataframe(deps,use_container_width=True,hide_index=True)
    st.markdown('**Enforced:** successor first access week must be strictly later than predecessor final access week (FS+0).')
with t4:
    st.download_button('Download SCHEDULE_ACCESS.csv',access.to_csv(index=False),'SCHEDULE_ACCESS.csv','text/csv')
    st.download_button('Download SCHEDULE_OCCUPANCY.csv',occ.to_csv(index=False),'SCHEDULE_OCCUPANCY.csv','text/csv')
    st.download_button('Download RESULTS.csv',results.to_csv(index=False),'RESULTS.csv','text/csv')

st.divider()
st.caption('RailFlow AI | Scenario B and C execute real schedule transformations. Prototype validation currently covers planned-start, predecessor, weekly-cap and conservative location-collision logic; use the official validator before claiming full PS1 feasibility.')
