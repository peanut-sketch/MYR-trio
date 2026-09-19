# 🚇 RailFlow AI
### AI-Powered Railway Track Access Optimisation
Nebula X Hackathon — Problem Statement 1

Team Members:
- Ritikaa
- Minchai Kwak
- Lim Yi Ning

## 1. Problem

Railway maintenance, renewal and construction activities compete for
limited engineering access windows.

RailFlow AI automatically creates track-access schedules while considering
physical safety constraints, track availability, work compatibility,
contract limits, dependencies and project priorities.

## 2. Our Solution

RailFlow AI is a decision-support system for railway access planners.

The application:

- Generates track-access schedules
- Detects scheduling conflicts
- Enforces predecessor dependencies
- Checks weekly allocation and workfront limits
- Accounts for sector/platform capacity
- Supports possession compatibility and co-sharing
- Handles safety buffers and Live-rail mirroring
- Supports Scenario A, B and C planning policies
- Explains scheduling decisions
- Produces competition-ready CSV outputs

For a quick overview, watch our video: https://youtu.be/RRZOZKBmaxc

## 3. Scenarios

### Scenario A — Strict Supply / Flexible Schedule

Track capacity is fixed.

- No excess capacity
- ECLO prohibited
- Schedule delay is permitted
- Objective: minimise priority-weighted overrun

### Scenario B — Strict Schedule / Flexible Supply

Planned completion dates are fixed.

- Zero planned-date overrun required
- Additional access capacity permitted
- ECLO permitted
- Objective: minimise cost of additional capacity and ECLO

### Scenario C — Balanced / Elastic

Balances schedule delay and additional capacity.

- Limited capacity elasticity
- ECLO permitted
- Priority-weighted delay considered
- Additional access usage penalised

## 4. Input Files

The scheduler accepts the following eight CSV files:

1. `01_LINES.csv`
2. `02_STATIONS.csv`
3. `03_SECTORS.csv`
4. `04_LOCATION_SUPPLY.csv`
5. `05_BUFFER_LOCATION.csv`
6. `06_PARAMETERS.csv`
7. `07_PROJECT_DETAILS.csv`
8. `08_ACTIVITY_DETAILS.csv`

## 5. Output Files

For each scenario, RailFlow AI produces:

### SCHEDULE_ACCESS.csv

activity_id, access_seq, week, eclo, access_night

### SCHEDULE_OCCUPANCY.csv

activity_id, week, location_id, co_share_group

### RESULTS.csv

scenario, contract_number, simulated_completion_date, overrun_days

All outputs can be downloaded directly through the web application.

## 6. Scheduling Constraints

RailFlow AI considers:

- 100% workload conservation
- Planned start dates
- FS+0 predecessor dependencies
- Closures and exclusion buffers
- Live-rail opposite-bound mirroring
- Interchange Live-rail effects
- Possession-location capacity
- PM / PC / C legal mixes
- Co-sharing
- Weekly access allocation
- Contract workfront limits
- ECLO rules
- Scenario-specific capacity rules

## 7. Web Application

Hosted Application: (via Streamlit)

https://myr-triogit-v6uad4bj8lmeqncnteo7dk.streamlit.app/

The web interface allows planners to:

1. Select Scenario A, B or C
2. View schedule KPIs
3. Inspect scheduled accesses
4. Inspect location occupancy
5. Identify conflicts
6. Understand scheduling decisions
7. Upload hidden competition instances
8. Download the generated competition CSV files

## 8. Running Locally

Clone the repository:

git clone [INSERT GITLAB URL]

Enter the project directory:

cd [REPOSITORY NAME]

Install dependencies:

pip install -r requirements.txt

Start the application:

streamlit run app.py

## 9. Repository Structure

.
├── app.py
├── solver.py
├── requirements.txt
├── README.md
├── 01_LINES.csv
├── 02_STATIONS.csv
├── 03_SECTORS.csv
├── 04_LOCATION_SUPPLY.csv
├── 05_BUFFER_LOCATION.csv
├── 06_PARAMETERS.csv
├── 07_PROJECT_DETAILS.csv
├── 08_ACTIVITY_DETAILS.csv
├── SCHEDULE_ACCESS.csv
├── SCHEDULE_OCCUPANCY.csv
└── RESULTS.csv

## 10. Technology

- Python
- Streamlit
- Pandas
- Custom railway scheduling and validation engine

## 11. Explainability

RailFlow AI provides planner-readable explanations for scheduling
decisions.

For each decision, the system considers:

1. Eligibility
2. Safety
3. Capacity
4. Contract/resource constraints
5. Schedule optimisation
6. Alternative scheduling options

This allows works controllers to understand not only what was scheduled,
but why.

## 12. Competition Deliverables

### Public Test Results
Three CSV outputs are provided for each planning scenario.

### Live Application
(https://myr-triogit-v6uad4bj8lmeqncnteo7dk.streamlit.app/)

### Video Demonstration
(https://youtu.be/RRZOZKBmaxc)


---

Nebula X Hackathon
Problem Statement 1 — Railway Track Access Optimisation
