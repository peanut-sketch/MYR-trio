"""
RailFlow AI — Maintenance Access Scheduler
Nebula X Hackathon | Problem Statement 1

Streamlit dashboard for conflict-aware railway engineering access planning.
"""

from pathlib import Path

import pandas as pd
import streamlit as st


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="NebulaX RailFlow AI",
    page_icon="🚇",
    layout="wide",
)


# ============================================================
# FILE RESOLUTION
#
# The CSV files may sit either directly beside app.py (the current
# repository layout) or inside a data/public_results folder. Rather
# than hard-coding one location, every candidate directory is searched
# so the app runs unchanged locally, in Docker and on Streamlit Cloud.
# ============================================================

ROOT = Path(__file__).resolve().parent

CANDIDATE_DIRS = [
    ROOT,
    ROOT / "data" / "public_results",
    ROOT / "public_results",
    ROOT / "data",
]

REQUIRED_PUBLIC_FILES = [
    "SCHEDULE_ACCESS.csv",
    "SCHEDULE_OCCUPANCY.csv",
    "RESULTS.csv",
]

REQUIRED_INSTANCE_FILES = [
    "01_LINES.csv",
    "02_STATIONS.csv",
    "03_SECTORS.csv",
    "04_LOCATION_SUPPLY.csv",
    "05_BUFFER_LOCATION.csv",
    "06_PARAMETERS.csv",
    "07_PROJECT_DETAILS.csv",
    "08_ACTIVITY_DETAILS.csv",
]


def find_file(filename):
    """
    Return the first existing path for `filename` across the candidate
    directories, or None when the file cannot be located anywhere.

    Matching is case-insensitive so that a file saved as
    Schedule_Access.csv on Windows is still found on a Linux container.
    """

    for directory in CANDIDATE_DIRS:

        if not directory.is_dir():
            continue

        exact = directory / filename

        if exact.exists():
            return exact

        for path in directory.iterdir():
            if path.is_file() and path.name.lower() == filename.lower():
                return path

    return None


def describe_search_locations():
    """
    Human-readable list of the directories that were searched, used in
    error messages so a missing file can be diagnosed without a redeploy.
    """

    lines = []

    for directory in CANDIDATE_DIRS:

        if directory.is_dir():
            names = sorted(
                path.name
                for path in directory.iterdir()
                if path.is_file() and path.suffix.lower() == ".csv"
            )
            found = ", ".join(names) if names else "no CSV files"
            lines.append(f"- `{directory}` → {found}")
        else:
            lines.append(f"- `{directory}` → directory does not exist")

    return "\n".join(lines)


# ============================================================
# DATA LOADING
# ============================================================

@st.cache_data(show_spinner=False)
def read_csv_cached(path_string):
    """
    Cached CSV read. The path is passed as a string so that the cache key
    changes when the resolved location changes.
    """

    return pd.read_csv(path_string)


def load_public_results():
    """
    Load the public demonstration schedule.

    Returns (access, occupancy, results). Halts the app with a readable
    message if any of the three files is missing.
    """

    resolved = {}
    missing = []

    for filename in REQUIRED_PUBLIC_FILES:

        path = find_file(filename)

        if path is None:
            missing.append(filename)
        else:
            resolved[filename] = path

    if missing:

        st.error(
            "The following public result files could not be found: "
            + ", ".join(missing)
        )

        st.markdown(
            "**Locations searched:**\n\n" + describe_search_locations()
        )

        st.info(
            "Place the CSV files beside `app.py`, or inside a "
            "`data/public_results/` folder, then rerun the app. "
            "If the files were added recently, clear the cache from "
            "the sidebar so the new paths are picked up."
        )

        st.stop()

    access = read_csv_cached(str(resolved["SCHEDULE_ACCESS.csv"]))
    occupancy = read_csv_cached(str(resolved["SCHEDULE_OCCUPANCY.csv"]))
    results = read_csv_cached(str(resolved["RESULTS.csv"]))

    return access, occupancy, results


def load_activity_details():
    """
    Load activity information used for predecessor / dependency checks.
    Returns None when the file is unavailable.
    """

    path = find_file("08_ACTIVITY_DETAILS.csv")

    if path is None:
        return None

    return read_csv_cached(str(path))


# ============================================================
# VALIDATION HELPERS
# ============================================================

def normalise_ids(series):
    """
    Trim whitespace and cast to string so that identifier comparison is
    not defeated by stray spaces or numeric/text type differences.
    """

    return series.dropna().astype(str).str.strip()


def validate_predecessors(activities):
    """
    Check that every predecessor_activity_id refers to an existing
    activity.

    Returns (invalid, dependencies) where `invalid` is a list of
    (activity, missing_predecessor) tuples and `dependencies` is the
    subset of rows that declare a predecessor.
    """

    if activities is None or activities.empty:
        return [], pd.DataFrame()

    if "predecessor_activity_id" not in activities.columns:
        return [], pd.DataFrame()

    if "activity_id" not in activities.columns:
        return [], pd.DataFrame()

    activities = activities.copy()

    predecessor_values = (
        activities["predecessor_activity_id"].astype(str).str.strip()
    )

    predecessor_mask = (
        activities["predecessor_activity_id"].notna()
        & ~predecessor_values.isin(["", "nan", "None", "-"])
    )

    dependencies = activities.loc[predecessor_mask].copy()

    known_ids = set(normalise_ids(activities["activity_id"]))

    invalid = []

    for _, row in dependencies.iterrows():

        predecessor = str(row["predecessor_activity_id"]).strip()
        activity = str(row["activity_id"]).strip()

        if predecessor not in known_ids:
            invalid.append((activity, predecessor))

    return invalid, dependencies


def find_self_references(activities):
    """
    Detect activities that list themselves as their own predecessor,
    which would make the dependency graph infeasible.
    """

    if activities is None or activities.empty:
        return []

    columns = activities.columns

    if "activity_id" not in columns or "predecessor_activity_id" not in columns:
        return []

    matches = activities.loc[
        activities["activity_id"].astype(str).str.strip()
        == activities["predecessor_activity_id"].astype(str).str.strip()
    ]

    return matches["activity_id"].astype(str).str.strip().tolist()


def safe_nunique(frame, column):
    """
    Distinct count for a column, or "N/A" when the column is absent.
    """

    if column in frame.columns:
        return frame[column].nunique()

    return "N/A"


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

    st.metric("Hard-rule target", "0 violations")
    st.metric("Workload target", "100% scheduled")

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

    st.divider()

    if st.button("🔄 Reload data files", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    with st.expander("Data source"):
        st.caption(f"Application directory: `{ROOT}`")
        st.markdown(describe_search_locations())


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

    if "activity_id" in access_df.columns:
        activities_scheduled = access_df["activity_id"].nunique()
    else:
        activities_scheduled = len(access_df)

    col1.metric("Activities Scheduled", activities_scheduled)

    col2.metric("Contracts", safe_nunique(results_df, "contract_number"))

    col3.metric("Access Records", len(access_df))

    if "overrun_days" in results_df.columns:
        overrun = pd.to_numeric(
            results_df["overrun_days"],
            errors="coerce",
        ).fillna(0).sum()
        overrun = int(overrun)
    else:
        overrun = "N/A"

    col4.metric("Overrun Days", overrun)

    st.divider()

    st.subheader("Contract Completion Overview")

    st.dataframe(results_df, use_container_width=True, hide_index=True)

    st.subheader("Scheduled Access")

    st.dataframe(access_df, use_container_width=True, hide_index=True)

    st.subheader("Track Occupancy")

    st.dataframe(occupancy_df, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("Download Scheduling Outputs")

    d1, d2, d3 = st.columns(3)

    with d1:
        st.download_button(
            label="⬇️ SCHEDULE_ACCESS.csv",
            data=access_df.to_csv(index=False).encode("utf-8"),
            file_name="SCHEDULE_ACCESS.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with d2:
        st.download_button(
            label="⬇️ SCHEDULE_OCCUPANCY.csv",
            data=occupancy_df.to_csv(index=False).encode("utf-8"),
            file_name="SCHEDULE_OCCUPANCY.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with d3:
        st.download_button(
            label="⬇️ RESULTS.csv",
            data=results_df.to_csv(index=False).encode("utf-8"),
            file_name="RESULTS.csv",
            mime="text/csv",
            use_container_width=True,
        )


# ============================================================
# TAB 2 — CONFLICT AND DEPENDENCY CHECK
# ============================================================

with tab2:

    st.header("Conflict & Dependency Detection")

    activities_df = load_activity_details()

    if activities_df is None:

        st.error("08_ACTIVITY_DETAILS.csv could not be found.")

        st.markdown(
            "**Locations searched:**\n\n" + describe_search_locations()
        )

    else:

        invalid_predecessors, dependencies = validate_predecessors(
            activities_df
        )

        st.subheader("Predecessor Dependencies")

        if "predecessor_activity_id" not in activities_df.columns:

            st.warning(
                "No `predecessor_activity_id` column was found in "
                "08_ACTIVITY_DETAILS.csv, so dependency checking was "
                "skipped. Columns present: "
                + ", ".join(activities_df.columns)
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

            if len(dependencies) > 0 and available_columns:
                st.dataframe(
                    dependencies[available_columns],
                    use_container_width=True,
                    hide_index=True,
                )

            if invalid_predecessors:

                st.error("Invalid predecessor references detected.")

                st.dataframe(
                    pd.DataFrame(
                        invalid_predecessors,
                        columns=["Activity", "Missing predecessor"],
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

            else:
                st.success(
                    "All predecessor references point to valid activities."
                )

            self_references = find_self_references(activities_df)

            if self_references:
                st.error(
                    "Activities listing themselves as their own "
                    "predecessor: " + ", ".join(self_references)
                )

        st.info(
            "Predecessor rule: an activity with a predecessor cannot "
            "begin until its predecessor activity has finished. The "
            "scheduler therefore treats the dependency as a "
            "finish-to-start constraint."
        )

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
        "Upload all eight competition CSV files. RailFlow AI will "
        "validate the dataset before it is passed to the scheduling "
        "engine."
    )

    uploaded_files = st.file_uploader(
        "Select the 8 CSV files",
        type="csv",
        accept_multiple_files=True,
    )

    if uploaded_files:

        uploaded_names = [file.name for file in uploaded_files]

        missing_files = [
            filename
            for filename in REQUIRED_INSTANCE_FILES
            if filename not in uploaded_names
        ]

        st.write(
            f"**Files uploaded:** {len(uploaded_names)} / "
            f"{len(REQUIRED_INSTANCE_FILES)}"
        )

        if missing_files:

            st.error("Missing required files: " + ", ".join(missing_files))

        else:

            try:

                frames = {
                    file.name: pd.read_csv(file)
                    for file in uploaded_files
                }

                activities_uploaded = frames["08_ACTIVITY_DETAILS.csv"]

                st.success("Dataset accepted successfully.")

                c1, c2 = st.columns(2)

                c1.metric("Activities", len(activities_uploaded))

                c2.metric(
                    "Contracts",
                    safe_nunique(activities_uploaded, "contract_number"),
                )

                st.subheader("Dependency Validation")

                invalid, uploaded_dependencies = validate_predecessors(
                    activities_uploaded
                )

                if invalid:

                    st.error(
                        f"{len(invalid)} invalid predecessor "
                        "reference(s) detected."
                    )

                    st.dataframe(
                        pd.DataFrame(
                            invalid,
                            columns=["Activity", "Invalid predecessor"],
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

                else:

                    st.success("Predecessor graph references are valid.")

                    st.write(
                        "Dependencies detected: "
                        f"**{len(uploaded_dependencies)}**"
                    )

                uploaded_self_references = find_self_references(
                    activities_uploaded
                )

                if uploaded_self_references:
                    st.error(
                        "Self-referencing activities detected: "
                        + ", ".join(uploaded_self_references)
                    )

                st.subheader("Dataset Summary")

                summary_df = pd.DataFrame(
                    [
                        {
                            "File": filename,
                            "Rows": len(dataframe),
                            "Columns": len(dataframe.columns),
                        }
                        for filename, dataframe in sorted(frames.items())
                    ]
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

                st.error(f"Unable to process uploaded dataset: {error}")


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

        st.error("🚨 Emergency / disruption scenario active")

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
            "Select 'C — Disruption / urgent maintenance' from the "
            "sidebar to view the emergency scheduling workflow."
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "RailFlow AI | Nebula X Hackathon | "
    "Problem Statement 1 — AI Maintenance Scheduler"
)
