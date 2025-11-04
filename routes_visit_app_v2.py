
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date

# ============================================
# Expected ROUTES_SHEET columns (new structure)
# ============================================
ROUTE_COLS = [
    "Name",
    "Latitude",
    "Longitude",
    "Distance from Office (km)",
    "Visited",
    "Visit_date",
    "Contact_Person",
    "Contact_Number",
    "Visit_Month",
    "Business_Month",
    "Remarks",
    "Agent_Code",
    "Agent_Name",
]

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

@st.cache_resource(show_spinner=False)
def get_gs_client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPE
    )
    return gspread.authorize(creds)

def _get_sa_email():
    try:
        return st.secrets["gcp_service_account"]["client_email"]
    except Exception:
        return "(service account email not found in secrets)"

@st.cache_resource(show_spinner=False)
def open_spreadsheet():
    gc = get_gs_client()
    ss_id = st.secrets.get("SPREADSHEET_ID", "").strip()
    ss_name = st.secrets.get("SPREADSHEET_NAME", "").strip()

    # Allow runtime override (sidebar)
    if "runtime_spreadsheet_id" in st.session_state and st.session_state.runtime_spreadsheet_id:
        ss_id = st.session_state.runtime_spreadsheet_id.strip()

    # Prefer ID to avoid name collisions
    if ss_id:
        try:
            return gc.open_by_key(ss_id)
        except gspread.SpreadsheetNotFound:
            sa = _get_sa_email()
            st.error(
                f"Could not open by SPREADSHEET_ID='{ss_id}'. "
                f"Share the sheet with **{sa}** (Editor) and verify the ID."
            )
            raise

    # Fallback to name (requires Drive access + exact title)
    if ss_name:
        try:
            return gc.open(ss_name)
        except gspread.SpreadsheetNotFound:
            # Helpful diagnostics: list spreadsheets visible to SA
            try:
                all_ss = gc.openall()
            except Exception:
                st.error("Failed to list accessible spreadsheets. Check Drive access for the Service Account.")
                raise
            exact = [s for s in all_ss if getattr(s, "title", "") == ss_name]
            partial = [s for s in all_ss if ss_name.lower() in getattr(s, "title", "").lower()]
            sa = _get_sa_email()
            if exact or partial:
                st.error("Spreadsheet not found by name. Sheets visible to your Service Account:")
                def fmt(spreadsheet):
                    sid = getattr(spreadsheet, "id", "(unknown id)")
                    return f"- Title: '{spreadsheet.title}'  |  ID: {sid}"
                if exact:
                    st.info("**Exact title matches**:")
                    st.text("\\n".join(fmt(s) for s in exact))
                if partial and not exact:
                    st.info("**Partial title matches**:")
                    st.text("\\n".join(fmt(s) for s in partial))
                st.warning(
                    "If the expected sheet isn't listed, the Service Account cannot see it. "
                    f"Share with **{sa}** (Editor) and prefer using `SPREADSHEET_ID`."
                )
            else:
                st.error(
                    f"No spreadsheets visible with title '{ss_name}'. "
                    "Share the sheet with the Service Account, or set SPREADSHEET_ID."
                )
            raise

    raise RuntimeError("Set SPREADSHEET_ID or SPREADSHEET_NAME in secrets (or use the sidebar override).")

def get_worksheet(ss, sheet_name: str):
    try:
        return ss.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Worksheet '{sheet_name}' not found. Check the exact tab name.")
        st.stop()

def worksheet_to_df(ws):
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if not df.empty:
        df.insert(0, "_sheet_row", range(2, len(df) + 2))
    return df

def batch_update_row(ws, row_number: int, updates: dict, header_map: dict):
    requests = []
    for col_name, value in updates.items():
        if col_name not in header_map:
            continue
        col_idx = header_map[col_name]
        requests.append({
            "range": gspread.utils.rowcol_to_a1(row_number, col_idx),
            "values": [[value]]
        })
    if requests:
        ws.batch_update(requests)

def month_label(dt: date) -> str:
    """Return YYYY-MM (e.g., 2025-11)."""
    return f"{dt.year:04d}-{dt.month:02d}"

def parse_date_guess(value, default: date) -> date:
    """Parse a variety of common date formats, fallback to default."""
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value.strip():
        candidates = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y")
        for fmt in candidates:
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except Exception:
                continue
        try:
            return pd.to_datetime(value).date()
        except Exception:
            return default
    if pd.notna(value):
        try:
            return pd.to_datetime(value).date()
        except Exception:
            return default
    return default

# ==============================
# UI
# ==============================
st.set_page_config(page_title="Routes Visits – Separate App", layout="wide")
st.title("🗂️ Routes Visits Updater (Separate Spreadsheet)")

with st.sidebar:
    st.header("Config / Debug")
    sa_email = _get_sa_email()
    st.caption("Service Account")
    st.code(sa_email)

    st.caption("Secrets overview")
    st.write({
        "SPREADSHEET_ID": st.secrets.get("SPREADSHEET_ID","(unset)")[:8] + "..." if st.secrets.get("SPREADSHEET_ID") else "(unset)",
        "SPREADSHEET_NAME": st.secrets.get("SPREADSHEET_NAME","(unset)"),
        "ROUTES_SHEET_NAME": st.secrets.get("ROUTES_SHEET_NAME","Routes"),
        "AGENTS_SHEET_NAME": st.secrets.get("AGENTS_SHEET_NAME","Agents"),
    })

    st.caption("Override Spreadsheet ID (optional)")
    st.session_state.runtime_spreadsheet_id = st.text_input(
        "Spreadsheet ID", value=st.session_state.get("runtime_spreadsheet_id","")
    )
    st.caption("Tip: Share the sheet with the Service Account (Editor).")

# Connect
ss = open_spreadsheet()
routes_ws = get_worksheet(ss, st.secrets.get("ROUTES_SHEET_NAME", "Routes"))
agents_ws = get_worksheet(ss, st.secrets.get("AGENTS_SHEET_NAME", "Agents"))

routes_df = worksheet_to_df(routes_ws)
agents_df = worksheet_to_df(agents_ws)

# Column sanity check
missing_cols = [c for c in ROUTE_COLS if c not in routes_df.columns]
if missing_cols:
    st.warning(f"Missing expected columns in '{st.secrets.get('ROUTES_SHEET_NAME','Routes')}' sheet: {missing_cols}")

# -----------------
# LOGIN
# -----------------
st.subheader("Login")

agent_code_col = "agent_code" if "agent_code" in agents_df.columns else None
agent_name_col = "agent_name" if "agent_name" in agents_df.columns else None
password_col_candidates = [c for c in ["Password", "PIN", "Passcode", "Secret"] if c in agents_df.columns]
password_col = password_col_candidates[0] if password_col_candidates else None

if not agent_code_col:
    st.error("Agents sheet must contain at least 'agent_code'.")
    st.stop()

c1, c2, c3 = st.columns([1,1,1])
with c1:
    input_code = st.text_input("Agent Code", value="", placeholder="e.g., AGNT001")
with c2:
    input_secret = st.text_input("Password / PIN", type="password", placeholder="Required if your Agents sheet has one")
with c3:
    login_btn = st.button("Sign In", type="primary")

if "auth" not in st.session_state:
    st.session_state.auth = None

def try_login(code: str, secret: str):
    if not code:
        st.warning("Enter your Agent Code.")
        return None
    df = agents_df.copy()
    df = df[df[agent_code_col].astype(str).str.strip().str.upper() == code.strip().upper()]
    if df.empty:
        st.error("Invalid Agent Code.")
        return None
    if password_col:
        stored = str(df.iloc[0][password_col]).strip()
        if not secret:
            st.error(f"Password / PIN required. ({password_col})")
            return None
        if secret.strip() != stored:
            st.error("Incorrect Password / PIN.")
            return None
    agent_name = df.iloc[0][agent_name_col] if agent_name_col and agent_name_col in df.columns else ""
    return {"code": code.strip(), "name": str(agent_name).strip()}

if login_btn:
    st.session_state.auth = try_login(input_code, input_secret)

if st.session_state.auth is None:
    st.info("Please sign in to continue.")
    st.stop()

agent = st.session_state.auth
st.success(f"Signed in as **{agent.get('name') or agent.get('code')}**")

# -----------------
# FILTER / SELECT
# -----------------
st.subheader("Update Visit Details")

if routes_df.empty:
    st.info("No rows found in the routes sheet.")
    st.stop()

with st.expander("Filters", expanded=True):
    f1, f2, f3, f4 = st.columns([1,1,1,1])
    with f1:
        only_unvisited = st.checkbox("Show only Unvisited", value=True)
    with f2:
        name_contains = st.text_input("Search by Name contains", value="")
    with f3:
        max_km = st.number_input("Max Distance (km)", min_value=0.0, value=0.0, step=1.0, help="0 means no limit")
    with f4:
        show_assigned_only = st.checkbox("Show only my assignments", value=False)

df_view = routes_df.copy()

if "Visited" in df_view.columns and only_unvisited:
    df_view = df_view[(df_view["Visited"].astype(str).str.strip() == "") | (df_view["Visited"].isna()) | (df_view["Visited"].astype(str).str.upper().isin(["N","NO","0"]))]

if name_contains:
    df_view = df_view[df_view["Name"].astype(str).str.contains(name_contains, case=False, na=False)]

if max_km and max_km > 0:
    km_col = "Distance from Office (km)"
    if km_col in df_view.columns:
        def as_float(x):
            try:
                return float(str(x).replace(",","").strip())
            except Exception:
                return 999999.0
        df_view = df_view[df_view[km_col].apply(as_float) <= float(max_km)]

if show_assigned_only and "agent_code" in df_view.columns:
    df_view = df_view[df_view["agent_code"].astype(str).str.strip().str.upper() == agent["code"].upper()]

if "Distance from Office (km)" in df_view.columns:
    try:
        df_view = df_view.copy()
        df_view["__dist__"] = pd.to_numeric(df_view["Distance from Office (km)"], errors="coerce")
        df_view = df_view.sort_values(by="__dist__", ascending=True).drop(columns=["__dist__"])
    except Exception:
        pass

st.caption("Select a row to update:")
mini_cols = [c for c in ["_sheet_row","Name","Distance from Office (km)","Visited","Visit_date","Contact_Person","Contact_Number","Visit_Month","Business_Month","Remarks","agent_code","agent_name"] if c in df_view.columns or c=="_sheet_row"]
mini = df_view[mini_cols].copy()
mini = mini.reset_index(drop=True)
st.dataframe(mini, use_container_width=True, hide_index=True)

row_numbers = mini["_sheet_row"].tolist()
labels = [f"{r} – {n}" for r, n in zip(mini["_sheet_row"], mini["Name"].astype(str))]
selected = st.selectbox("Pick a row (Sheet Row – Name)", options=row_numbers, format_func=lambda x: labels[row_numbers.index(x)] if x in row_numbers else str(x))

# -----------------
# EDIT & SAVE
# -----------------
st.markdown("---")
st.subheader("Edit & Save")

headers = routes_ws.row_values(1)
header_map = {name: idx for idx, name in enumerate(headers, start=1)}

current = routes_df[routes_df["_sheet_row"] == selected]
if current.empty:
    st.error("Selected row could not be found. Try refreshing.")
    st.stop()
row_data = current.iloc[0]

# Defaults
today = date.today()
default_visit_date = parse_date_guess(row_data.get("Visit_date"), default=today)

c1, c2, c3 = st.columns([1,1,1])
with c1:
    visited_flag = st.selectbox(
        "Visited", options=["", "Y", "N"],
        index=["","Y","N"].index(str(row_data.get("Visited","")).strip().upper()) if str(row_data.get("Visited","")).strip().upper() in ["","Y","N"] else 0,
        help="Set 'Y' if visited, 'N' if not."
    )
with c2:
    visit_date = st.date_input("Visit date", value=default_visit_date)
with c3:
    computed_visit_month = month_label(visit_date)
    visit_month = st.text_input("Visit_Month (YYYY-MM)", value=str(row_data.get("Visit_Month", computed_visit_month) or computed_visit_month))

c4, c5, c6 = st.columns([1,1,1])
with c4:
    contact_person = st.text_input("Contact Person", value=str(row_data.get("Contact_Person","")).strip())
with c5:
    contact_number = st.text_input("Contact Number", value=str(row_data.get("Contact_Number","")).strip())
with c6:
    # Business_Month options around current month plus existing
    current_bm = str(row_data.get("Business_Month","")).strip()
    default_bm = current_bm if current_bm else month_label(today)
    ym_now = month_label(today)
    ym_prev = month_label(date(today.year - (1 if today.month == 1 else 0), 12 if today.month == 1 else today.month - 1, 1))
    ym_next = month_label(date(today.year + (1 if today.month == 12 else 0), 1 if today.month == 12 else today.month + 1, 1))
    options = list(dict.fromkeys([default_bm, ym_prev, ym_now, ym_next]))  # dedupe but keep order
    bm_choice = st.selectbox("Business_Month", options=options, index=0)

remarks = st.text_area("Remarks", value=str(row_data.get("Remarks","")).strip(), height=100)

auto_assign = st.checkbox("Assign this record to me", value=True, help="Will set Agent_Code and Agent_Name to your login.")

save_btn = st.button("💾 Save Update", type="primary")

if save_btn:
    # Basic phone clean
    contact_number_clean = contact_number.replace(" ", "").replace("-", "")
    # Prepare updates
    updates = {
        "Visited": visited_flag,
        "Visit_date": visit_date.strftime("%Y-%m-%d"),
        "Contact_Person": contact_person,
        "Contact_Number": contact_number_clean,
        "Visit_Month": visit_month if visit_month else month_label(visit_date),
        "Business_Month": bm_choice,
        "Remarks": remarks,
    }
    if auto_assign:
        updates["agent_code"] = agent["code"]
        if "agent_name" in header_map and agent.get("name"):
            updates["agent_name"] = agent["name"]

    try:
        batch_update_row(routes_ws, int(selected), updates, header_map)
        st.success("Row updated successfully!")
        st.toast("Saved ✅", icon="✅")
        st.balloons()
    except Exception as e:
        st.error(f"Failed to update the sheet: {e}")
        st.stop()

    # Refresh and rerun
    routes_df = worksheet_to_df(routes_ws)
    st.experimental_rerun()
