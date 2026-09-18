# RailFlow AI — Nebula X Hackathon PS1

**Team:** Ritikaa · Minchai Kwak · Lim Yi Ning  
**Challenge:** Railway Track Access Optimisation / AI Maintenance Scheduler

RailFlow AI is a planner-facing prototype for turning competing railway engineering access requests into an explainable possession schedule. It combines schedule visibility, predecessor/dependency checks, conflict categories, public-test results, and a hidden-instance upload workflow in one Streamlit interface.

## Competition clarification covered
`08_ACTIVITY_DETAILS.csv.predecessor_activity_id` is treated as a finish-to-start, zero-lag dependency: the successor's first access must be in a week strictly later than the predecessor's final scheduled access week.

## What the prototype demonstrates
- Dashboard for `SCHEDULE_ACCESS.csv` and contract completion results.
- Explicit predecessor/dependency detection.
- Conflict classes for planned start, capacity, buffers, co-sharing, live-rail mirroring, weekly caps and workfront.
- Upload and schema validation for all eight hidden-instance CSVs.
- Explainability flow for recommended slots and emergency replanning.
- Downloadable public result files in the required schema.

## Important implementation status
The bundled `data/public_results/` files are the organiser-provided feasible reference-format public schedule and are included so the UI and submission workflow can be demonstrated reliably. The hidden-instance upload currently validates inputs and dependencies; a full optimisation engine must be connected before claiming hidden-instance solver feasibility.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy quickly (Streamlit Community Cloud)
1. Create a GitHub repository and upload this folder.
2. In Streamlit Community Cloud choose **Create app**.
3. Select the repository and set the entrypoint to `app.py`.
4. Deploy and copy the public URL into the hackathon submission form.

## Submission files
`data/public_results/` contains:
- `SCHEDULE_ACCESS.csv`
- `SCHEDULE_OCCUPANCY.csv`
- `RESULTS.csv`

## Architecture
**UI:** Streamlit  
**Data:** pandas / CSV  
**Optimisation design:** constraint-first scheduling with a priority-weighted objective; emergency mode is designed to re-optimise with a schedule-churn penalty.  
**Explainability:** rule-by-rule reason codes surfaced to the works controller.

## Core scheduling model
Hard constraints: workload conservation, planned start, predecessor FS+0, physical occupancy/buffers, live-rail mirroring, interchange rules, location capacity, weekly contract caps and workfront. Soft objectives: reduce planned completion overrun, prioritise high-priority contracts/activities, minimise excess access/ECLO use, and minimise disruption during replanning.

## Team pitch
RailFlow AI turns hours of manual coordination into an auditable decision-support workflow: detect the conflict, explain the rule, propose the least-disruptive feasible slot, and show what changes when an emergency arrives.
