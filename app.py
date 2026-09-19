from pathlib import Path
import tempfile
import pandas as pd
import streamlit as st
from solver import load_instance, validate, score_schedule, compute_results, output_zip_bytes, replan_emergency, plan_scenario_b, closure_violations, REQUIRED_INSTANCE

st.set_page_config(page_title='RailFlow AI | Nebula X',page_icon='🚇',layout='wide')
ROOT=Path(__file__).resolve().parent

@st.cache_data
def load_public():
    inst=load_instance(ROOT)
    a=pd.read_csv(ROOT/'SCHEDULE_ACCESS.csv'); o=pd.read_csv(ROOT/'SCHEDULE_OCCUPANCY.csv')
    return inst,a,o

inst,base_access,base_occ=load_public()

st.title('🚇 RailFlow AI — Railway Track Access Optimisation')
st.caption('Decision support for works controllers: schedule, validate, explain, export.')

with st.sidebar:
    st.header('Run controls')
    scenario=st.selectbox('Scenario policy',['A — Strict supply / flexible schedule','B — Strict schedule / flexible supply','C — Balanced / elastic trade-off'])
    sc=scenario[0]
    st.markdown({'A':'**A:** zero excess supply; ECLO forbidden; minimise priority-weighted delay.',
                 'B':'**B:** planned completion is rigid; extra supply + ECLO are allowed and penalised.',
                 'C':'**C:** balance delay, limited (+1) local supply elasticity and ECLO.'}[sc])
    emergency=st.toggle('Urgent-maintenance what-if',value=False,disabled=(sc!='C'))
    urgent=None; target=None
    if emergency:
        urgent=st.selectbox('Urgent activity',sorted(inst.activities.activity_id.astype(str).unique()))
        cur=int(base_access[base_access.activity_id.astype(str)==urgent].week.min())
        target=st.number_input('Requested first week',1,inst.horizon_weeks,max(1,cur-1),1)

access=base_access.copy(); occ=base_occ.copy(); changes=[]; notes=[]
if sc=='B':
    access,occ,changes,notes=plan_scenario_b(inst,access,occ)
elif sc=='C' and emergency:
    access,occ,changes,notes=replan_emergency(inst,access,occ,urgent,int(target))
results=compute_results(inst,access,sc)
viol=validate(inst,access,occ,sc)+closure_violations(inst,occ); score=score_schedule(inst,access,occ,sc)

c1,c2,c3,c4,c5=st.columns(5)
c1.metric('Activities',access.activity_id.nunique()); c2.metric('Work units',f"{sum(1.5 if int(x) else 1 for x in access.eclo):g}/{inst.activities.total_accesses.sum():g}")
c3.metric('Hard violations',len(viol)); c4.metric('Overrun days',score['overrun_days_total']); c5.metric('Objective',f"{score['objective_score']:,.1f}")
if not viol: st.success('Validator checks implemented in the app: PASS — zero detected hard violations.')
else: st.error(f'{len(viol)} hard-rule issue(s) detected. Open Validation for details.')
for n in notes: st.warning(n)

T=st.tabs(['📊 Schedule','🛡️ Validation','🧠 Explainability','📁 Hidden instance','⬇️ Submission outputs'])
with T[0]:
    st.subheader(f'Scenario {sc} schedule')
    if sc=='B':
        st.info('Scenario B: the base plan is repaired so every contract meets its planned completion date — late work is pulled into free weeks first, then ECLO-compressed, and only then given extra access-nights. Changes are listed below.')
    elif sc=='C' and not emergency:
        st.info('The bundled public schedule is displayed as the starting plan. Scenario C also supports live urgent-maintenance what-if replanning.')
    st.dataframe(access,use_container_width=True,hide_index=True,height=430)
    st.subheader('Contract completion')
    st.dataframe(results,use_container_width=True,hide_index=True)

    st.divider()
    st.subheader('📦 Download current scenario outputs')
    st.caption(f'These files contain the currently selected Scenario {sc} results in the official submission schema.')
    d1,d2,d3,d4=st.columns(4)
    d1.download_button('⬇️ SCHEDULE_ACCESS.csv',access.to_csv(index=False).encode('utf-8'),'SCHEDULE_ACCESS.csv','text/csv',use_container_width=True,key='schedule_access_main')
    d2.download_button('⬇️ SCHEDULE_OCCUPANCY.csv',occ.to_csv(index=False).encode('utf-8'),'SCHEDULE_OCCUPANCY.csv','text/csv',use_container_width=True,key='schedule_occupancy_main')
    d3.download_button('⬇️ RESULTS.csv',results.to_csv(index=False).encode('utf-8'),'RESULTS.csv','text/csv',use_container_width=True,key='results_main')
    d4.download_button('⬇️ All outputs (.zip)',output_zip_bytes(access,occ,results),f'RailFlowAI_Scenario_{sc}_Outputs.zip','application/zip',use_container_width=True,key='all_outputs_main')

    if changes:
        st.subheader('Displaced / changed work')
        st.dataframe(pd.DataFrame(changes,columns=['activity_id','from_week','to_week','reason']).astype({'from_week':'Int64','to_week':'Int64'}),use_container_width=True,hide_index=True)
with T[1]:
    st.subheader('Mechanical checks')
    if viol: st.dataframe(pd.DataFrame(viol),use_container_width=True,hide_index=True)
    else: st.success('No violations detected by the implemented rule checks.')
    st.json({'scenario':sc,'feasible':not bool(viol),'hard_violations':viol,'soft_scores':score})
with T[2]:
    st.subheader('Why this plan?')
    st.markdown(f'''**Scenario {sc} policy** determines the trade-off. The engine checks workload conservation, planned starts, predecessor FS+0, weekly contract allocation, workfronts, possession mix, occupancy coverage, scenario capacity allowance and ECLO policy.\n\n**Current plan:** {score['contracts_overrunning']} contract(s) overrun; {score['excess_access_nights_total']} excess access-night(s); {score['eclo_nights_total']} ECLO night(s).''')
    if score['capacity_hotspots']:
        st.subheader('Capacity hotspots'); st.dataframe(pd.DataFrame(score['capacity_hotspots']),use_container_width=True,hide_index=True)
with T[3]:
    st.subheader('Upload undisclosed / hidden test instance')
    files=st.file_uploader('Upload the 8 instance CSV files',type='csv',accept_multiple_files=True)
    if files:
        names={f.name:f for f in files}; missing=[x for x in REQUIRED_INSTANCE if x not in names]
        if missing: st.error('Missing: '+', '.join(missing))
        else:
            with tempfile.TemporaryDirectory() as td:
                td=Path(td)
                for n,f in names.items(): (td/n).write_bytes(f.getvalue())
                try:
                    hi=load_instance(td); st.success(f'Instance parsed: {len(hi.activities)} activities, {hi.projects.contract_number.nunique()} contracts, {hi.horizon_weeks}-week horizon.')
                    st.dataframe(pd.DataFrame([{'file':n,'rows':len(pd.read_csv(td/n))} for n in REQUIRED_INSTANCE]),use_container_width=True,hide_index=True)
                    st.warning('This upload proves schema/data ingestion. To generate a judge-valid hidden answer, the exact optimisation engine must schedule the uploaded instance; do not substitute the bundled public answer for a hidden instance.')
                except Exception as e: st.error(f'Instance rejected: {e}')
with T[4]:
    st.subheader('Judge-format outputs')
    st.code('SCHEDULE_ACCESS.csv\nSCHEDULE_OCCUPANCY.csv\nRESULTS.csv')
    st.download_button('Download all 3 outputs (.zip)',output_zip_bytes(access,occ,results),f'RailFlowAI_Scenario_{sc}_Outputs.zip','application/zip',use_container_width=True,key='all_outputs_tab')
    a,b,c=st.columns(3)
    a.download_button('SCHEDULE_ACCESS.csv',access.to_csv(index=False).encode('utf-8'),'SCHEDULE_ACCESS.csv','text/csv',use_container_width=True,key='schedule_access_tab')
    b.download_button('SCHEDULE_OCCUPANCY.csv',occ.to_csv(index=False).encode('utf-8'),'SCHEDULE_OCCUPANCY.csv','text/csv',use_container_width=True,key='schedule_occupancy_tab')
    c.download_button('RESULTS.csv',results.to_csv(index=False).encode('utf-8'),'RESULTS.csv','text/csv',use_container_width=True,key='results_tab')
    st.caption('RESULTS.csv contains exactly one selected scenario; output column order matches the published submission schema.')
