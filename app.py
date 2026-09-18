import io
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="NebulaX RailFlow AI",
    page_icon="🚇",
    layout="wide"
)


# ============================================================
# FILE PATHS
# All CSV files are currently stored in the same folder as app.py
# ============================================================

ROOT = Path(__file__).resolve().parent

SCHEDULE_ACCESS_FILE = ROOT / "SCHEDULE_ACCESS.csv"
SCHEDULE_OCCUPANCY_FILE = ROOT / "SCHEDULE_OCCUPANCY.csv"
RESULTS_FILE = ROOT / "RESULTS.csv"

ACTIVITY_FILE = ROOT / "08_ACTIVITY_DETAILS.csv"


# ============================================================
# HELPER FUNCTIONS
# ============================================================

@st.cache_data
def load_public_results():
    """
    Load the public demonstration schedule.
    """

    required_files = [
        SCHEDULE_ACCESS_FILE,
        SCHEDULE_OCCUPANCY_FILE,
        RESULTS_FILE,
    ]

    missing = [file.name for file in required_files if not file.exists()]

    if missing:
        st.error(
            "The following public result files could not be found: "
            + ", ".join(missing)
        )
        st.stop()

    access = pd.read_csv(SCHEDULE_ACCESS_FILE)
    occupancy = pd.read_csv(SCHEDULE_OCCUPANCY_FILE)
    results = pd.read_csv(RESULTS_FILE)

    return access, occupancy, results


@st.cache_data
def load_activity_details():
    """
    Load activity information used for predecessor/dependency checks.
    """

    if not ACTIVITY_FILE.exists():
        return None

    return pd.read_csv(ACTIVITY_FILE)


def validate_predecessors(activities):
    """
    Check that every predecessor_activity_id refers to an existing activity.
    """

    if "predecessor_activity_id" not in activities.columns:
        return [], pd.DataFrame()

    activities = activities.copy()

    predecessor_mask = (
        activities["predecessor_activity_id"].notna()
        & (activities["predecessor_activity_id"].astype(str).str.strip() != "")
    )

    deps = activities.loc[predecessor_mask].copy()

    activity_ids = set(
        activities["activity_id"]
        .dropna()
        .astype(str)
        .str.strip()
    )

    invalid = []

    for _, row in deps.iterrows():
        predecessor = str(row["predecessor_activity_id"]).strip()
        activity = str(row["activity_id"]).strip()

        if predecessor not in activity_ids:
            invalid.append((activity, predecessor))

    return invalid, deps


# ============================================================
# HEADER
# ============================================================

st.title("🚇 RailFlow AI — Maintenance Access Scheduler")

st.caption(
    "Conflict-aware railway engineering access planning | "
    "Nebula X Hackathon — Problem Statement 1"
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header("Planning Controls")

    scenario = st.selectbox(
        "Scenario",
        [
            "A — Normal supply",
            "B — Flexible supply",
            "C — Disruption / urgent maintenance",
        ],
    )

    st.divider()

    st.metric(
        "Hard-rule target",
        "0 violations"
    )

    st.metric(
        "Workload target",
        "100% scheduled"
    )

    st.divider()

    st.subheader("Scheduling priorities")

    st.write(
        """
        RailFlow AI considers:

        • Predecessor dependencies  
        • Planned start dates  
        • Sector availability  
        • Track access capacity  
        • Work compatibility  
        • Safety constraints  
        • Engineering resources  
        • Schedule disruption
        """
    )

    st.info(
        "The public demonstration uses the provided reference-format "
        "schedule. Hidden-instance upload performs data and dependency "
        "validation before optimisation."
    )


# ============================================================
# LOAD PUBLIC DATA
# ============================================================

access_df, occupancy_df, results_df = load_public_results()


# ============================================================
# TABS
# ============================================================

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📊 Schedule Dashboard",
        "⚠️ Conflict & Dependency Check",
        "📁 Hidden Instance Upload",
        "💡 Explainability",
    ]
)


# ============================================================
# TAB 1 — DASHBOARD
# ============================================================

with tab1:

    st.header("Maintenance Schedule Dashboard")

    st.write(
        "The dashboard provides planners with a consolidated view of "
        "scheduled engineering activities and access allocations."
    )

    col1, col2, col3, col4 = st.columns(4)

    # Activity count
    if "activity_id" in access_df.columns:
        activities_scheduled = access_df["activity_id"].nunique()
    else:
        activities_scheduled = len(access_df)

    col1.metric(
        "Activities Scheduled",
        activities_scheduled
    )

    # Contract count
    if "contract_number" in results_df.columns:
        contracts = results_df["contract_number"].nunique()
    else:
        contracts = "N/A"

    col2.metric(
        "Contracts",
        contracts
    )

    col3.metric(
        "Access Records",
        len(access_df)
    )

    # Overrun calculation
    if "overrun_days" in results_df.columns:
        overrun = pd.to_numeric(
            results_df["overrun_days"],
            errors="coerce"
        ).fillna(0).sum()

        overrun = int(overrun)

    else:
        overrun = "N/A"

    col4.metric(
        "Overrun Days",
        overrun
    )

    st.divider()

    st.subheader("Contract Completion Overview")

    st.dataframe(
        results_df,
        use_container_width=True,
        hide_index=True
    )

    st.subheader("Scheduled Access")

    st.dataframe(
        access_df,
        use_container_width=True,
        hide_index=True
    )

    st.subheader("Track Occupancy")

    st.dataframe(
        occupancy_df,
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    st.subheader("Download Scheduling Outputs")

    d1, d2, d3 = st.columns(3)

    with d1:

        st.download_button(
            label="⬇️ Download SCHEDULE_ACCESS.csv",
            data=access_df.to_csv(index=False),
            file_name="SCHEDULE_ACCESS.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with d2:

        st.download_button(
            label="⬇️ Download SCHEDULE_OCCUPANCY.csv",
            data=occupancy_df.to_csv(index=False),
            file_name="SCHEDULE_OCCUPANCY.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with d3:

        st.download_button(
            label="⬇️ Download RESULTS.csv",
            data=results_df.to_csv(index=False),
            file_name="RESULTS.csv",
            mime="text/csv",
            use_container_width=True,
        )


# ============================================================
# TAB 2 — CONFLICT AND DEPENDENCY CHECK
# ============================================================

with tab2:

    st.header("Conflict & Dependency Detection")

    activities = load_activity_details()

    if activities is None:

        st.error(
            "08_ACTIVITY_DETAILS.csv could not be found."
        )

    else:

        invalid_predecessors, dependencies = validate_predecessors(
            activities
        )

        # ----------------------------------------------------
        # PREDECESSOR CHECK
        # ----------------------------------------------------

        st.subheader("Predecessor Dependencies")

        if "predecessor_activity_id" not in activities.columns:

            st.warning(
                "No predecessor_activity_id column was found."
            )

        else:

            st.success(
                f"{len(dependencies)} predecessor dependencies "
                "detected automatically."
            )

            preferred_columns = [
                "activity_id",
                "predecessor_activity_id",
                "planned_start_date",
                "contract_number",
            ]

            available_columns = [
                column
                for column in preferred_columns
                if column in dependencies.columns
            ]

            if len(dependencies) > 0:

                st.dataframe(
                    dependencies[available_columns],
                    use_container_width=True,
                    hide_index=True,
                )

            if invalid_predecessors:

                st.error(
                    "Invalid predecessor references detected."
                )

                invalid_df = pd.DataFrame(
                    invalid_predecessors,
                    columns=[
                        "Activity",
                        "Missing predecessor",
                    ],
                )

                st.dataframe(
                    invalid_df,
                    use_container_width=True,
                    hide_index=True,
                )

            else:

                st.success(
                    "All predecessor references point to valid activities."
                )

        st.info(
            "Predecessor rule: an activity with a predecessor cannot "
            "begin until its predecessor activity has finished. "
            "The scheduler therefore treats the dependency as a "
            "finish-to-start constraint."
        )

        # ----------------------------------------------------
        # CONFLICT CLASSES
        # ----------------------------------------------------

        st.subheader("Conflict Classes Checked")

        conflict_data = pd.DataFrame(
            {
                "Constraint": [
                    "Predecessor dependency",
                    "Planned start",
                    "Sector availability",
                    "Track / location capacity",
                    "Weekly access limits",
                    "Workfront limits",
                    "Possession compatibility",
                    "Safety buffers",
                    "Occupancy expansion",
                    "Schedule disruption",
                ],
                "Purpose": [
                    "Successor cannot start before predecessor finishes",
                    "Activity cannot be scheduled prematurely",
                    "Required engineering sector must be available",
                    "Prevents capacity conflicts at shared locations",
                    "Prevents contracts exceeding weekly access limits",
                    "Limits simultaneous workfronts",
                    "Prevents incompatible work sharing the same possession",
                    "Maintains required separation between engineering works",
                    "Accounts for the complete affected track area",
                    "Minimises changes when emergency work is inserted",
                ],
            }
        )

        st.dataframe(
            conflict_data,
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# TAB 3 — HIDDEN INSTANCE UPLOAD
# ============================================================

with tab3:

    st.header("Hidden Instance Upload")

    st.write(
        "Upload all eight competition CSV files. "
        "RailFlow AI will validate the dataset before it is passed "
        "to the scheduling engine."
    )

    required_files = [
        "01_LINES.csv",
        "02_STATIONS.csv",
        "03_SECTORS.csv",
        "04_LOCATION_SUPPLY.csv",
        "05_BUFFER_LOCATION.csv",
        "06_PARAMETERS.csv",
        "07_PROJECT_DETAILS.csv",
        "08_ACTIVITY_DETAILS.csv",
    ]

    uploaded_files = st.file_uploader(
        "Select the 8 CSV files",
        type="csv",
        accept_multiple_files=True,
    )

    if uploaded_files:

        uploaded_names = [
            file.name
            for file in uploaded_files
        ]

        missing_files = [
            file
            for file in required_files
            if file not in uploaded_names
        ]

        st.write(
            f"**Files uploaded:** "
            f"{len(uploaded_names)} / {len(required_files)}"
        )

        if missing_files:

            st.error(
                "Missing required files: "
                + ", ".join(missing_files)
            )

        else:

            try:

                frames = {
                    file.name: pd.read_csv(file)
                    for file in uploaded_files
                }

                activities_uploaded = frames[
                    "08_ACTIVITY_DETAILS.csv"
                ]

                if "contract_number" in activities_uploaded.columns:

                    contract_count = (
                        activities_uploaded[
                            "contract_number"
                        ]
                        .nunique()
                    )

                else:

                    contract_count = "N/A"

                st.success(
                    "Dataset accepted successfully."
                )

                c1, c2 = st.columns(2)

                c1.metric(
                    "Activities",
                    len(activities_uploaded)
                )

                c2.metric(
                    "Contracts",
                    contract_count
                )

                # --------------------------------------------
                # PREDECESSOR VALIDATION
                # --------------------------------------------

                invalid, uploaded_dependencies = (
                    validate_predecessors(
                        activities_uploaded
                    )
                )

                st.subheader(
                    "Dependency Validation"
                )

                if invalid:

                    st.error(
                        f"{len(invalid)} invalid predecessor "
                        "reference(s) detected."
                    )

                    invalid_df = pd.DataFrame(
                        invalid,
                        columns=[
                            "Activity",
                            "Invalid predecessor",
                        ],
                    )

                    st.dataframe(
                        invalid_df,
                        use_container_width=True,
                        hide_index=True,
                    )

                else:

                    st.success(
                        "Predecessor graph references are valid."
                    )

                    st.write(
                        f"Dependencies detected: "
                        f"**{len(uploaded_dependencies)}**"
                    )

                # --------------------------------------------
                # FILE SUMMARY
                # --------------------------------------------

                st.subheader(
                    "Dataset Summary"
                )

                summary_rows = []

                for filename, dataframe in frames.items():

                    summary_rows.append(
                        {
                            "File": filename,
                            "Rows": len(dataframe),
                            "Columns": len(dataframe.columns),
                        }
                    )

                summary_df = pd.DataFrame(
                    summary_rows
                )

                st.dataframe(
                    summary_df,
                    use_container_width=True,
                    hide_index=True,
                )

                st.warning(
                    "The uploaded dataset has passed structural "
                    "validation. Full hidden-instance optimisation "
                    "requires the scheduling optimisation engine."
                )

            except Exception as error:

                st.error(
                    f"Unable to process uploaded dataset: {error}"
                )


# ============================================================
# TAB 4 — EXPLAINABILITY
# ============================================================

with tab4:

    st.header("Explainable AI Scheduling")

    st.write(
        "RailFlow AI is designed to show planners why a particular "
        "maintenance slot is recommended instead of returning a "
        "black-box scheduling decision."
    )

    st.subheader("Why was this slot chosen?")

    st.markdown(
        """
### 1. Eligibility

The activity's planned-start requirements and predecessor dependencies
must first be satisfied.

### 2. Safety

The system checks track capacity, possession compatibility, safety
buffers and affected locations.

### 3. Availability

The required sector and engineering access must be available during
the proposed maintenance period.

### 4. Resource Constraints

Weekly contract limits, workfront capacity and engineering resources
are considered before allocating the slot.

### 5. Optimisation

Among feasible options, the scheduler aims to minimise delay and
unnecessary disruption to the existing maintenance programme.

### 6. Alternative Recommendation

If the preferred slot cannot be used, the system can present the next
feasible candidate and explain the associated trade-off.
"""
    )

    st.divider()

    st.subheader("Emergency Maintenance")

    if scenario == "C — Disruption / urgent maintenance":

        st.error(
            "🚨 Emergency / disruption scenario active"
        )

        st.write(
            """
            Under an emergency scenario, the scheduler would:

            1. Insert the urgent maintenance request.
            2. Re-check predecessor and safety constraints.
            3. Identify conflicts with existing work.
            4. Search for the feasible schedule with the least disruption.
            5. Flag displaced activities.
            6. Present the revised plan for human confirmation.
            """
        )

    else:

        st.info(
            "Select 'C — Disruption / urgent maintenance' from "
            "the sidebar to view the emergency scheduling workflow."
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "RailFlow AI | Nebula X Hackathon | "
    "Problem Statement 1 — AI Maintenance Scheduler"
)
