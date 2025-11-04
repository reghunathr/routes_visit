import streamlit as st
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

SCOPES = [
 "https://www.googleapis.com/auth/spreadsheets",
 "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def _client():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_data(ttl=15)
def get_all_data():
    sh = _client().open_by_key(st.secrets["SHEET_ID"])

    def df(sheet):
        return pd.DataFrame(sh.worksheet(sheet).get_all_records())

    return (
        df(st.secrets["AGENTS_SHEET_NAME"]),
        df(st.secrets["INSTITUTIONS_SHEET_NAME"]),
        df(st.secrets["VEHICLES_SHEET_NAME"])
    )

def verify_password(pwd, hashed):
    from make_admin_hash import verify_password as v
    return v(pwd, hashed)

def get_agent_context(df, email):
    r = df[df["agent_email"] == email]
    if r.empty:
        return None
    return r.iloc[0].to_dict()

def save_call_result(row, agent, outcome, nxt, notes):
    sh = _client().open_by_key(st.secrets["SHEET_ID"])
    ws = sh.worksheet(st.secrets["INSTITUTIONS_SHEET_NAME"])
    rownum = row["_row_index"]

    ws.update(f"M{rownum}:Q{rownum}", [[
        outcome,
        pd.Timestamp.now().isoformat(),
        nxt.strftime("%d/%m/%Y"),
        row["attempt_count"] + 1,
        notes
    ]])

def write_agents_to_sheet(df):
    sh = _client().open_by_key(st.secrets["SHEET_ID"])
    sh.worksheet(st.secrets["AGENTS_SHEET_NAME"]).update(
        [df.columns.values.tolist()] + df.values.tolist()
    )
