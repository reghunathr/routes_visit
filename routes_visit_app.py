
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date

# ====== Bring in your shared password verifier ======
try:
    from sheets_utils import verify_password as _verify_external
except Exception:
    _verify_external = None

def verify_password(raw: str, stored: str) -> bool:
    if _external_verify := _verify_external:
        try:
            return bool(_external_verify(raw, stored))
        except Exception:
            pass
    return (raw or "").strip() == (stored or "").strip()

# ====== Constants ======
ROUTE_COLS = [
    "Name","Latitude","Longitude","Distance from Office (km)",
    "Visited","Visit_date","Contact_Person","Contact_Number",
    "Visit_Month","Business_Month","Remarks","Agent_Code","Agent_Name",
]
AGENTS_REQUIRED = [
    "agent_code","agent_name","agent_email","agent_mobile",
    "passcode","agent_status","reset_code","reset_expires",
]
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ====== Utilities ======
def role_is_enabled(status: str) -> bool:
    if status is None:
        return False
    v = str(status).strip().lower()
    if not v:
        return False
    enabled_roles = {"user","admin","superadmin"}
    disabled_tokens = {"inactive","disabled","blocked","suspended","deleted","deactivated","0","false","no"}
    if v in enabled_roles:
        return True
    if v in disabled_tokens:
        return False
    try:
        extra = st.secrets.get("AGENT_ENABLED_ROLES", [])
    except Exception:
        extra = []
    return v in {str(x).strip().lower() for x in extra}

def month_label(dt: date) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"

def parse_date_guess(value, default: date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return default
        return dt.date()
    except Exception:
        return default

def parse_checkbox(val) -> bool:
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in {"true", "y", "yes", "1", "checked"}

def is_unvisited_cell(val) -> bool:
    if isinstance(val, bool):
        return not val
    s = str(val).strip().lower()
    return s in {"", "n", "no", "0", "false"}

def ws_to_df(ws):
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame()
    headers = [str(h).strip() for h in values[0]]
    rows = values[1:]
    fixed = []
    for r in rows:
        r = [(str(x) if x is not None else "").strip() for x in r]
        if len(r) < len(headers):
            r += [""] * (len(headers) - len(r))
        elif len(r) > len(headers):
            r = r[:len(headers)]
        fixed.append(r)
    df = pd.DataFrame(fixed, columns=headers)
    if not df.empty:
        df.insert(0, "_sheet_row", range(2, len(df) + 2))
    return df

# ====== Google Sheets ======
@st.cache_resource(show_spinner=False)
def get_gs_client():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def open_spreadsheet():
    gc = get_gs_client()
    ss_id = (st.secrets.get("SPREADSHEET_ID", "") or st.secrets.get("SHEET_ID","")).strip()
    ss_name = st.secrets.get("SPREADSHEET_NAME", "").strip()
    if ss_id:
        return gc.open_by_key(ss_id)
    if ss_name:
        return gc.open(ss_name)
    raise RuntimeError("Set SPREADSHEET_ID (or SHEET_ID) or SPREADSHEET_NAME in secrets.")

def get_worksheet(ss, sheet_name: str):
    try:
        return ss.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Worksheet '{sheet_name}' not found. Check the exact tab name.")
        st.stop()

# ====== Page config & CSS (mobile friendly) ======
st.set_page_config(page_title="Routes Visits – Mobile", layout="wide")
st.markdown("""
<style>
/* Maximize tap targets on mobile */
.stButton > button, .stDownloadButton > button {
  padding: 0.9rem 1.1rem;
  font-size: 1rem;
  border-radius: 12px;
}
/* Compact input labels on small screens */
@media (max-width: 480px) {
  .stTextInput label, .stSelectbox label, .stCheckbox label, .stDateInput label, .stTextArea label {
    font-size: 0.92rem;
  }
}
/* Card look for mobile rows */
.card {
  padding: 0.85rem 1rem;
  border-radius: 16px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.06);
  background: white;
  margin-bottom: 10px;
  border: 1px solid rgba(0,0,0,0.05);
}
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.75rem;
  background: #EEF2FF;
  color: #4F46E5;
  margin-left: 6px;
}
/* Sticky action bar for save on mobile */
.sticky-footer {
  position: sticky;
  bottom: 0;
  z-index: 999;
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(6px);
  padding: 0.6rem 0.4rem 0.9rem 0.4rem;
  border-top: 1px solid rgba(0,0,0,0.05);
}
</style>
""", unsafe_allow_html=True)

st.title("📍 Routes Visits")

# ====== Secrets sanity (clear message if missing) ======
REQUIRED = ["gcp_service_account", "SPREADSHEET_ID", "ROUTES_SHEET_NAME", "AGENTS_SHEET_NAME"]
missing = [k for k in REQUIRED if k not in st.secrets]
if missing:
    st.error("Missing Streamlit secrets: " + ", ".join(missing) + ". Add them in Settings → Secrets.")
    st.stop()

# ====== Sheets ======
ss = open_spreadsheet()
routes_ws = get_worksheet(ss, st.secrets.get("ROUTES_SHEET_NAME", "Routes"))
agents_ws = get_worksheet(ss, st.secrets.get("AGENTS_SHEET_NAME", "agents"))

routes_df = ws_to_df(routes_ws)
agents_df = ws_to_df(agents_ws)
agents_df.columns = [c.strip().lower() for c in agents_df.columns]

# Validate required columns
missing_agent_cols = [c for c in AGENTS_REQUIRED if c not in agents_df.columns]
if missing_agent_cols:
    st.error(f"The 'agents' sheet is missing required columns: {missing_agent_cols}")
    st.stop()

# ====== Login (email + passcode; code as fallback) ======
with st.container():
    st.subheader("Sign in")
    lc1, lc2, lc3 = st.columns([1.2, 1.0, 0.7])
    with lc1:
        input_email = st.text_input("Email", value="", placeholder="name@example.com")
    with lc2:
        input_pass = st.text_input("Passcode", type="password", placeholder="Enter passcode")
    with lc3:
        login_btn = st.button("Sign In", type="primary")

if "auth" not in st.session_state:
    st.session_state.auth = None

def try_login(email: str, passcode: str):
    email = (email or "").strip().lower()
    passcode = (passcode or "").strip()
    if not email:
        st.warning("Enter your Email."); return None
    if not passcode:
        st.warning("Enter your Passcode."); return None

    df = agents_df.copy()
    df["__email_norm__"] = df["agent_email"].astype(str).str.strip().str.lower()
    df["__code_norm__"]  = df["agent_code"].astype(str).str.strip().str.lower()

    sel = df[df["__email_norm__"] == email]
    if sel.empty:
        sel = df[df["__code_norm__"] == email]

    if sel.empty:
        st.error("Invalid login. Check your email (or agent code) and try again."); return None

    row = sel.iloc[0]
    if not role_is_enabled(row.get("agent_status", "")):
        st.error("Your account is not enabled for login. Contact administrator."); return None

    stored = str(row.get("passcode",""))
    if not verify_password(passcode, stored):
        st.error("Incorrect passcode."); return None

    return {
        "code": str(row.get("agent_code","")).strip(),
        "name": str(row.get("agent_name","")).strip(),
        "email": str(row.get("agent_email","")).strip(),
        "mobile": str(row.get("agent_mobile","")).strip(),
        "role": str(row.get("agent_status","")).strip(),
    }

if login_btn:
    st.session_state.auth = try_login(input_email, input_pass)

if st.session_state.auth is None:
    st.stop()

agent = st.session_state.auth
st.success(f"Welcome, **{agent.get('name') or agent.get('email')}**  \nRole: `{agent.get('role','')}`")

# ====== View mode toggle: Desktop table vs Mobile cards ======
vmode = st.segmented_control(
    "View",
    options=["Mobile", "Desktop"],
    selection_mode="single",
    default="Mobile",
    help="Switch between a mobile-friendly card view and a desktop table view."
)

# ====== Filters ======
with st.expander("Filters", expanded=True):
    c1, c2, c3, c4 = st.columns([1,1,1,1])
    with c1:
        only_unvisited = st.checkbox("Only Unvisited", value=True)
    with c2:
        name_contains = st.text_input("Name contains", value="")
    with c3:
        max_km = st.number_input("Max Distance (km)", min_value=0.0, value=0.0, step=1.0, help="0 = no limit")
    with c4:
        my_only = st.checkbox("Only my assignments", value=False)

df_view = routes_df.copy()
if only_unvisited and "Visited" in df_view.columns:
    df_view = df_view[df_view["Visited"].apply(is_unvisited_cell)]
if name_contains:
    df_view = df_view[df_view["Name"].astype(str).str.contains(name_contains, case=False, na=False)]
if max_km and max_km > 0 and "Distance from Office (km)" in df_view.columns:
    def as_float(x):
        try: return float(str(x).replace(",","").strip())
        except Exception: return 999999.0
    df_view = df_view[df_view["Distance from Office (km)"].apply(as_float) <= float(max_km)]
if my_only and "Agent_Code" in df_view.columns:
    df_view = df_view[df_view["Agent_Code"].astype(str).str.strip().str.upper() == agent["code"].upper()]

if df_view.empty:
    st.info("No rows match the selected filters.")
    st.stop()

# ====== Desktop view: single dataframe ======
if vmode == "Desktop":
    mini_cols = [c for c in ["_sheet_row","Name","Distance from Office (km)","Visited","Visit_date","Contact_Person","Contact_Number","Visit_Month","Business_Month","Remarks","Agent_Code","Agent_Name"] if c in df_view.columns or c=="_sheet_row"]
    df_show = df_view[mini_cols].copy().reset_index(drop=True)
    if "Visited" in df_show.columns:
        df_show["Visited"] = df_show["Visited"].apply(lambda v: "✓" if parse_checkbox(v) else "")
    st.dataframe(
        df_show,
        width="stretch",
        height=420,
        column_config={
            "_sheet_row": st.column_config.NumberColumn("Row", format="%d", width="small"),
            "Distance from Office (km)": st.column_config.NumberColumn("Km", help="Distance from office", format="%.2f"),
            "Visited": st.column_config.TextColumn("Visited"),
            "Visit_date": st.column_config.TextColumn("Visit Date"),
            "Contact_Person": st.column_config.TextColumn("Contact Person"),
            "Contact_Number": st.column_config.TextColumn("Contact Number"),
            "Visit_Month": st.column_config.TextColumn("Visit Month"),
            "Business_Month": st.column_config.TextColumn("Business Month"),
        }
    )

# ====== Mobile view: card list with per-row edit ======
if vmode == "Mobile":
    choices = [(int(r), f"{int(r)} – {n}") for r, n in zip(df_view["_sheet_row"], df_view["Name"].astype(str))]
    selected_row = st.selectbox("Pick a place", options=[row for row, _ in choices], format_func=dict(choices).get)

    headers = routes_ws.row_values(1)
    header_map = {name: idx for idx, name in enumerate(headers, start=1)}
    row_vals = routes_ws.row_values(int(selected_row))
    if len(row_vals) < len(headers):
        row_vals += [""] * (len(headers) - len(row_vals))
    row_dict = dict(zip(headers, row_vals))

    dist = row_dict.get("Distance from Office (km)", "")
    st.markdown(f"""
    <div class="card">
      <div style="font-weight:700; font-size:1.05rem">{row_dict.get('Name','')}</div>
      <div style="opacity:0.8; font-size:0.9rem">Distance: {dist} km
        <span class="badge">{row_dict.get('Agent_Code','').strip() or 'Unassigned'}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    today = date.today()
    def_date = parse_date_guess(row_dict.get("Visit_date",""), default=today)
    if not isinstance(def_date, date):
        def_date = today
    rowkey = str(selected_row)

    c1, c2 = st.columns(2)
    with c1:
        visited_flag = st.checkbox("Visited", value=parse_checkbox(row_dict.get("Visited","")), key=f"visited_{rowkey}")
    with c2:
        visit_date = st.date_input("Visit date", value=def_date, key=f"visit_date_{rowkey}")

    c3, c4 = st.columns(2)
    with c3:
        contact_person = st.text_input("Contact Person", value=str(row_dict.get("Contact_Person","")).strip(), key=f"contact_person_{rowkey}")
    with c4:
        contact_number = st.text_input("Contact Number", value=str(row_dict.get("Contact_Number","")).strip(), key=f"contact_number_{rowkey}")

    computed_visit_month = month_label(visit_date)
    c5, c6 = st.columns(2)
    with c5:
        visit_month = st.text_input("Visit_Month (YYYY-MM)", value=str(row_dict.get("Visit_Month", computed_visit_month) or computed_visit_month), key=f"visit_month_{rowkey}")
    with c6:
        current_bm = str(row_dict.get("Business_Month","")).strip()
        default_bm = current_bm if current_bm else month_label(today)
        ym_now  = month_label(today)
        ym_prev = month_label(date(today.year - (1 if today.month == 1 else 0), 12 if today.month == 1 else today.month - 1, 1))
        ym_next = month_label(date(today.year + (1 if today.month == 12 else 0), 1 if today.month == 12 else today.month + 1, 1))
        bm_options = list(dict.fromkeys([default_bm, ym_prev, ym_now, ym_next]))
        bm_choice = st.selectbox("Business_Month", options=bm_options, index=0, key=f"business_month_{rowkey}")

    remarks = st.text_area("Remarks", value=str(row_dict.get("Remarks","")).strip(), height=100, key=f"remarks_{rowkey}")
    auto_assign = st.checkbox("Assign this record to me", value=True, key=f"auto_assign_{rowkey}")

    with st.container():
        st.markdown('<div class="sticky-footer">', unsafe_allow_html=True)
        save_btn = st.button("💾 Save Update", type="primary")
        st.markdown('</div>', unsafe_allow_html=True)

    if save_btn:
        contact_number_clean = contact_number.replace(" ", "").replace("-", "")
        updates = {
            "Visited": bool(visited_flag),
            "Visit_date": visit_date.strftime("%Y-%m-%d"),
            "Contact_Person": contact_person,
            "Contact_Number": contact_number_clean,
            "Visit_Month": visit_month if visit_month else month_label(visit_date),
            "Business_Month": bm_choice,
            "Remarks": remarks,
        }
        if auto_assign:
            updates["Agent_Code"] = agent["code"]
            if "Agent_Name" in header_map and agent.get("name"):
                updates["Agent_Name"] = agent["name"]

        try:
            routes_ws.batch_update(
                [
                    {"range": gspread.utils.rowcol_to_a1(int(selected_row), header_map[k]), "values": [[v]]}
                    for k, v in updates.items() if k in header_map
                ],
                value_input_option="RAW"
            )
            st.success("Row updated successfully!")
            st.toast("Saved ✅", icon="✅")
        except Exception as e:
            st.error(f"Failed to update the sheet: {e}")
            st.stop()

        st.experimental_rerun()

# ====== Desktop inline editor ======
if vmode == "Desktop":
    choices = [(int(r), f"{int(r)} – {n}") for r, n in zip(df_view["_sheet_row"], df_view["Name"].astype(str))]
    selected_row = st.selectbox("Pick a row to edit", options=[row for row, _ in choices], format_func=dict(choices).get, key="desktop_picker")

    headers = routes_ws.row_values(1)
    header_map = {name: idx for idx, name in enumerate(headers, start=1)}
    row_vals = routes_ws.row_values(int(selected_row))
    if len(row_vals) < len(headers):
        row_vals += [""] * (len(headers) - len(row_vals))
    row_dict = dict(zip(headers, row_vals))

    today = date.today()
    def_date = parse_date_guess(row_dict.get("Visit_date",""), default=today)
    if not isinstance(def_date, date):
        def_date = today
    rowkey = f"desk_{selected_row}"

    d1, d2, d3 = st.columns([1,1,1])
    with d1:
        visited_flag = st.checkbox("Visited", value=parse_checkbox(row_dict.get("Visited","")), key=f"visited_{rowkey}")
    with d2:
        visit_date = st.date_input("Visit date", value=def_date, key=f"visit_date_{rowkey}")
    with d3:
        computed_visit_month = month_label(visit_date)
        visit_month = st.text_input("Visit_Month (YYYY-MM)", value=str(row_dict.get("Visit_Month", computed_visit_month) or computed_visit_month), key=f"visit_month_{rowkey}")

    d4, d5, d6 = st.columns([1,1,1])
    with d4:
        contact_person = st.text_input("Contact Person", value=str(row_dict.get("Contact_Person","")).strip(), key=f"contact_person_{rowkey}")
    with d5:
        contact_number = st.text_input("Contact Number", value=str(row_dict.get("Contact_Number","")).strip(), key=f"contact_number_{rowkey}")
    with d6:
        current_bm = str(row_dict.get("Business_Month","")).strip()
        default_bm = current_bm if current_bm else month_label(today)
        ym_now  = month_label(today)
        ym_prev = month_label(date(today.year - (1 if today.month == 1 else 0), 12 if today.month == 1 else today.month - 1, 1))
        ym_next = month_label(date(today.year + (1 if today.month == 12 else 0), 1 if today.month == 12 else today.month + 1, 1))
        bm_options = list(dict.fromkeys([default_bm, ym_prev, ym_now, ym_next]))
        bm_choice = st.selectbox("Business_Month", options=bm_options, index=0, key=f"business_month_{rowkey}")

    remarks = st.text_area("Remarks", value=str(row_dict.get("Remarks","")).strip(), height=100, key=f"remarks_{rowkey}")
    auto_assign = st.checkbox("Assign this record to me", value=True, key=f"auto_assign_{rowkey}")
    save_btn = st.button("💾 Save Update", type="primary", key=f"save_{rowkey}")

    if save_btn:
        contact_number_clean = contact_number.replace(" ", "").replace("-", "")
        updates = {
            "Visited": bool(visited_flag),
            "Visit_date": visit_date.strftime("%Y-%m-%d"),
            "Contact_Person": contact_person,
            "Contact_Number": contact_number_clean,
            "Visit_Month": visit_month if visit_month else month_label(visit_date),
            "Business_Month": bm_choice,
            "Remarks": remarks,
        }
        if auto_assign:
            updates["Agent_Code"] = agent["code"]
            if "Agent_Name" in header_map and agent.get("name"):
                updates["Agent_Name"] = agent["name"]

        try:
            routes_ws.batch_update(
                [
                    {"range": gspread.utils.rowcol_to_a1(int(selected_row), header_map[k]), "values": [[v]]}
                    for k, v in updates.items() if k in header_map
                ],
                value_input_option="RAW"
            )
            st.success("Row updated successfully!")
            st.toast("Saved ✅", icon="✅")
        except Exception as e:
            st.error(f"Failed to update the sheet: {e}")
            st.stop()

        st.rerun()
