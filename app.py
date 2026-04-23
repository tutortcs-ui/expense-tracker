"""
EXPENSE TRACKER - STAGE 3: GOOGLE LOGIN + PERSONAL LEARNING
=============================================================

What's new in this version (everything from Stage 2 is preserved):
- Google OAuth login button (top right)
- After login: loads YOUR personal category rules from Google Drive
- Your rules apply BEFORE default rules — your preferences always win
- When you fix a category, the app learns the rule and saves to Drive
- Guest mode still works — upload and analyze without logging in

Original features kept:
- Smart bank statement parser (works across all Indian banks)
- Dashboard with pie + bar charts, monthly averages
- Monthly Analysis tab (when multi_month.py is present)
- All Transactions tab with filters and search
- Fix Categories tab
- Excel + PDF download

Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os
import json
from pathlib import Path
from io import BytesIO
import requests

# Google OAuth libraries
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# Import Stage 1 categorization logic
from expense_categorizer import (
    categorize_transaction,
    CATEGORY_KEYWORDS
)

# Import multi-month analysis module (optional — tab disappears if file missing)
try:
    from multi_month import render_monthly_analysis_tab
    MULTI_MONTH_AVAILABLE = True
except ImportError:
    MULTI_MONTH_AVAILABLE = False


# ============================================================================
# CONFIGURATION
# ============================================================================

# Google OAuth credentials — stored in Streamlit secrets, never in code
GOOGLE_CLIENT_ID     = st.secrets.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI         = st.secrets.get("REDIRECT_URI", "")

# Google Drive folder and rules file names
DRIVE_FOLDER_NAME = "expense-tracker"
RULES_FILENAME    = "my_rules.json"

# Google API scopes — only access files created by this app
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.file",
]

# Category colors — kept exactly from original
CATEGORY_COLORS = {
    'Rent':                    '#795548',
    'Family':                  '#00BCD4',
    'Food':                    '#4CAF50',
    'Travel':                  '#2196F3',
    'Medical':                 '#F44336',
    'Subscriptions & Devices': '#3F51B5',
    'Books':                   '#9C27B0',
    'Garden':                  '#8BC34A',
    'Gifts':                   '#E91E63',
    'Miscellaneous':           '#9E9E9E',
}


# ============================================================================
# GOOGLE OAUTH FUNCTIONS
# ============================================================================

def get_google_auth_url():
    """
    Build the Google login URL.
    When the user clicks it, Google asks them to sign in and grant permission.
    """
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = REDIRECT_URI
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    st.session_state.oauth_state = state
    return auth_url


def exchange_code_for_credentials(code):
    """
    After Google redirects back with a ?code= parameter, exchange it for
    real credentials we can use to access Drive.
    """
    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [REDIRECT_URI],
                }
            },
            scopes=SCOPES,
            state=st.session_state.get("oauth_state"),
        )
        flow.redirect_uri = REDIRECT_URI
        flow.fetch_token(code=code)
        return flow.credentials
    except Exception as e:
        st.error(f"Login failed: {str(e)}")
        return None


def get_user_info(credentials):
    """Fetch the logged-in user's name and email from Google."""
    try:
        resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {credentials.token}"}
        )
        return resp.json()
    except:
        return {"name": "User", "email": ""}


def credentials_to_dict(credentials):
    """Convert credentials object to plain dict for storage in session state."""
    return {
        "token":         credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri":     credentials.token_uri,
        "client_id":     credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes":        credentials.scopes,
    }


def dict_to_credentials(creds_dict):
    """Rebuild credentials object from dict stored in session state."""
    return Credentials(
        token=creds_dict["token"],
        refresh_token=creds_dict.get("refresh_token"),
        token_uri=creds_dict["token_uri"],
        client_id=creds_dict["client_id"],
        client_secret=creds_dict["client_secret"],
        scopes=creds_dict["scopes"],
    )


# ============================================================================
# GOOGLE DRIVE FUNCTIONS
# ============================================================================

def get_drive_service(credentials):
    """Create a Google Drive API service using the user's credentials."""
    return build("drive", "v3", credentials=credentials)


def get_or_create_folder(service):
    """
    Find our 'expense-tracker' folder in the user's Drive.
    Creates it if it doesn't exist. Returns the folder ID.
    """
    results = service.files().list(
        q=f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)"
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    folder_metadata = {
        "name": DRIVE_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder"
    }
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    return folder["id"]


def load_rules_from_drive(service):
    """
    Load the user's personal category rules from their Google Drive.
    Returns a dict like: {"SWIGGY": "Food", "UBER": "Travel"}
    Returns empty dict if no rules file exists yet.
    """
    try:
        folder_id = get_or_create_folder(service)
        results = service.files().list(
            q=f"name='{RULES_FILENAME}' and '{folder_id}' in parents and trashed=false",
            fields="files(id, name)"
        ).execute()
        files = results.get("files", [])
        if not files:
            return {}
        file_id = files[0]["id"]
        request = service.files().get_media(fileId=file_id)
        buffer = BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buffer.seek(0)
        return json.loads(buffer.read().decode("utf-8"))
    except Exception as e:
        st.warning(f"Could not load your rules from Drive: {str(e)}")
        return {}


def save_rules_to_drive(service, rules):
    """
    Save the user's updated personal rules back to their Google Drive.
    Overwrites the existing file if it exists.
    """
    try:
        folder_id = get_or_create_folder(service)
        rules_json = json.dumps(rules, indent=2).encode("utf-8")
        media = MediaIoBaseUpload(BytesIO(rules_json), mimetype="application/json")
        results = service.files().list(
            q=f"name='{RULES_FILENAME}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)"
        ).execute()
        files = results.get("files", [])
        if files:
            service.files().update(fileId=files[0]["id"], media_body=media).execute()
        else:
            file_metadata = {"name": RULES_FILENAME, "parents": [folder_id]}
            service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        return True
    except Exception as e:
        st.error(f"Could not save rules to Drive: {str(e)}")
        return False


# ============================================================================
# PERSONAL RULES: APPLY + LEARN
# ============================================================================

def apply_personal_rules(particulars, personal_rules):
    """
    Check if any keyword from the user's personal rules matches this transaction.
    Personal rules always win over default rules.
    Returns the category string if matched, or None if no match.
    """
    particulars_upper = str(particulars).upper()
    for keyword, category in personal_rules.items():
        if keyword.upper() in particulars_upper:
            return category
    return None


def learn_from_correction(particulars, new_category, personal_rules):
    """
    When the user fixes a category, extract a keyword from the transaction
    description and add it as a new personal rule.
    This is how the app learns — each correction teaches it one new rule.
    """
    skip_words = {
        'UPI', 'NEFT', 'IMPS', 'RTGS', 'ACH', 'TO', 'FROM', 'BY',
        'DR', 'CR', 'VPA', 'REF', 'NO', 'TXN', 'TRANSFER', 'PAYMENT',
        'THE', 'AND', 'FOR', 'INR', 'A/C', 'AC'
    }
    words = str(particulars).upper().split()
    for word in words:
        clean_word = ''.join(c for c in word if c.isalnum())
        if clean_word and clean_word not in skip_words and len(clean_word) > 2:
            personal_rules[clean_word] = new_category
            break
    return personal_rules


def categorize_with_personal_rules(particulars, tran_type, amount, personal_rules):
    """
    Categorize using personal rules first, then default rules.
    Personal rules always take priority.
    """
    personal_cat = apply_personal_rules(particulars, personal_rules)
    if personal_cat:
        return personal_cat
    return categorize_transaction(particulars, tran_type, amount)


# ============================================================================
# FILE PARSER — kept exactly from original, personal_rules added
# ============================================================================

def load_and_process_statement(uploaded_file, personal_rules=None):
    """
    Load bank statement from any Indian bank and extract only the 5 columns we need.

    Strategy: Scan every row until we find one that looks like a header (contains
    keywords like 'date', 'particulars', 'withdrawal'). Then extract ONLY those
    columns — blank columns, bank info rows, junk rows are all discarded.

    Works across SBI, HDFC, Axis, Federal Bank, and most Indian bank formats.
    Personal rules are applied before default categorization if provided.
    """
    if personal_rules is None:
        personal_rules = {}

    try:
        # Step 1: Read raw file with NO assumptions about structure
        file_name = uploaded_file.name.lower()
        if file_name.endswith('.xls'):
            raw = pd.read_excel(uploaded_file, header=None, engine='xlrd')
        else:
            raw = pd.read_excel(uploaded_file, header=None, engine='openpyxl')

        # Step 2: Keyword map — order matters, more specific phrases first
        COLUMN_KEYWORDS = {
            'date':        ['value date', 'transaction date', 'txn date', 'tran date', 'date'],
            'particulars': ['particulars', 'description', 'narration', 'details', 'transaction details'],
            'tran_type':   ['tran type', 'transaction type', 'mode'],
            'withdrawals': ['withdrawal', 'withdrawals', 'debit', 'paid', 'dr'],
            'deposits':    ['deposit', 'deposits', 'credit', 'received', 'cr'],
        }

        # Step 3: Scan rows to find the header row automatically
        header_row_index = None
        for i, row in raw.iterrows():
            row_values = [str(v).lower().strip() for v in row.values]
            matches = sum(
                1 for keywords in COLUMN_KEYWORDS.values()
                if any(kw in row_values for kw in keywords)
            )
            if matches >= 3:
                header_row_index = i
                break

        if header_row_index is None:
            st.error(f"""
            ❌ Could not find the header row in your file.

            **Scanned:** {raw.shape[0]} rows × {raw.shape[1]} columns

            **What we look for:** A row containing words like 'Date', 'Particulars',
            'Withdrawal', 'Deposit', 'Narration', or 'Description'.

            **First 5 rows of your file (for debugging):**
            {raw.head(5).to_string()}
            """)
            return None

        # Step 4: Map each field to its exact column index
        header_values = [str(v).lower().strip() for v in raw.iloc[header_row_index].values]
        col_map = {}
        for field, keywords in COLUMN_KEYWORDS.items():
            for kw in keywords:
                if kw in header_values:
                    col_map[field] = header_values.index(kw)
                    break

        if 'date' not in col_map or 'particulars' not in col_map:
            st.error(f"""
            ❌ Found header row at row {header_row_index}, but could not locate
            Date or Particulars columns.

            **Columns found in that row:**
            {', '.join(str(v) for v in raw.iloc[header_row_index].values if str(v) != 'nan')}
            """)
            return None

        if 'withdrawals' not in col_map:
            st.error(f"""
            ❌ Could not find a Withdrawal/Debit column in your file.

            **Columns found:** {', '.join(str(v) for v in raw.iloc[header_row_index].values if str(v) != 'nan')}

            **Expected one of:** Withdrawal, Withdrawals, Debit, Paid, Dr
            """)
            return None

        # Step 5: Extract only data rows (skip header row and any footer rows)
        data = raw.iloc[header_row_index + 1:].copy()
        data = data[data.iloc[:, col_map['date']].notna()]
        data = data[data.iloc[:, col_map['particulars']].notna()]

        if len(data) == 0:
            st.warning("⚠️ No transaction rows found after the header row.")
            return None

        # Step 6: Clean amounts and dates
        def clean_amount(val):
            """Convert bank amount string like '1,999.00' to float 1999.0"""
            if pd.isna(val) or str(val).strip() in ['', 'nan']:
                return 0.0
            try:
                return float(str(val).replace(',', '').strip())
            except:
                return 0.0

        def clean_date_val(val):
            """Parse date strings and datetime objects into proper date objects"""
            try:
                return pd.to_datetime(val, dayfirst=True)
            except:
                return pd.NaT

        # Step 7: Build the clean 5-column DataFrame
        clean_data = pd.DataFrame({
            'Date': [clean_date_val(v) for v in data.iloc[:, col_map['date']]],
            'Particulars': [str(v) for v in data.iloc[:, col_map['particulars']]],
            'Tran Type': (
                [str(v) for v in data.iloc[:, col_map['tran_type']]]
                if 'tran_type' in col_map else ['N/A'] * len(data)
            ),
            'Withdrawals': [clean_amount(v) for v in data.iloc[:, col_map['withdrawals']]],
            'Deposits': (
                [clean_amount(v) for v in data.iloc[:, col_map['deposits']]]
                if 'deposits' in col_map else [0.0] * len(data)
            ),
        })

        # Step 8: Keep only expense rows, then categorize
        # Uses personal rules first, then default rules
        expense_df = clean_data[clean_data['Withdrawals'] > 0].copy()

        if len(expense_df) == 0:
            st.warning("⚠️ No withdrawal transactions found in this file.")
            return None

        expense_df['Category'] = expense_df.apply(
            lambda row: categorize_with_personal_rules(
                row['Particulars'],
                row['Tran Type'],
                row['Withdrawals'],
                personal_rules
            ),
            axis=1
        )

        # Rename for consistency with rest of app
        expense_df = expense_df.rename(columns={
            'Withdrawals': 'Amount',
            'Tran Type':   'Transaction Type'
        })

        return expense_df[['Date', 'Particulars', 'Transaction Type', 'Category', 'Amount']]

    except Exception as e:
        st.error(f"""
        ❌ Error processing file: {str(e)}

        **Please make sure:**
        - File is a valid Excel file (.xlsx or .xls)
        - File is a bank statement with transaction data
        - File has columns for Date, Description/Particulars, and Withdrawal/Debit amounts
        """)
        return None


# ============================================================================
# PDF GENERATION — kept exactly from original
# ============================================================================

def generate_pdf_report(df, category_summary):
    """
    Generate a professional PDF report with summary and charts.
    Returns BytesIO: PDF file in memory.
    """
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    pdf_buffer = BytesIO()
    with PdfPages(pdf_buffer) as pdf:

        # PAGE 1: SUMMARY + PIE CHART
        fig = plt.figure(figsize=(8.5, 11))
        fig.patch.set_facecolor('white')

        fig.text(0.5, 0.96, 'EXPENSE REPORT', ha='center', fontsize=22, weight='bold')
        report_date = datetime.now().strftime('%B %d, %Y')
        fig.text(0.5, 0.93, f'Generated on {report_date}',
                 ha='center', fontsize=11, style='italic', color='#666666')

        line1 = Rectangle((0.1, 0.915), 0.8, 0.002, transform=fig.transFigure, color='#CCCCCC')
        fig.patches.append(line1)

        summary_y = 0.88
        fig.text(0.5, summary_y, 'SUMMARY', ha='center', fontsize=14, weight='bold')

        total_spent        = df['Amount'].sum()
        total_transactions = len(df)
        uncategorized      = len(df[df['Category'] == 'Miscellaneous'])
        n_months           = df['Date'].dt.to_period('M').nunique()
        avg_monthly        = total_spent / n_months if n_months > 0 else total_spent

        summary_items = [
            ('Total Spent',         f'₹{total_spent:,.2f}'),
            ('Total Transactions',  f'{total_transactions:,}'),
            ('Months Covered',      f'{n_months}'),
            ('Average per Month',   f'₹{avg_monthly:,.0f}'),
            ('Miscellaneous Items', f'{uncategorized}'),
        ]

        box_y = summary_y - 0.03
        for label, value in summary_items:
            box = Rectangle((0.15, box_y - 0.025), 0.7, 0.03,
                             transform=fig.transFigure,
                             facecolor='#F5F5F5', edgecolor='#E0E0E0', linewidth=0.5)
            fig.patches.append(box)
            fig.text(0.18, box_y, f'{label}:', fontsize=11, va='center', ha='left')
            fig.text(0.55, box_y, value, fontsize=11, weight='bold', ha='left', va='center')
            box_y -= 0.04

        ax_pie = fig.add_axes([0.15, 0.25, 0.7, 0.38])
        colors = [CATEGORY_COLORS.get(cat, '#CCCCCC') for cat in category_summary['Category']]
        wedges, texts, autotexts = ax_pie.pie(
            category_summary['Total'],
            labels=None,
            autopct='%1.1f%%',
            colors=colors,
            startangle=90,
            pctdistance=0.85
        )
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(9)
            autotext.set_weight('bold')
        ax_pie.legend(category_summary['Category'], loc='upper center',
                      bbox_to_anchor=(0.5, -0.05), ncol=3, frameon=False, fontsize=9)
        ax_pie.set_title('Spending by Category', fontsize=13, weight='bold', pad=15)
        fig.text(0.5, 0.03, 'Expense Tracker - Your Financial Insights',
                 ha='center', fontsize=9, style='italic', color='#999999')
        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    pdf_buffer.seek(0)
    return pdf_buffer


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_category_summary(df):
    """Calculate spending summary by category, sorted by amount."""
    summary = df.groupby('Category')['Amount'].agg(['sum', 'count']).reset_index()
    summary.columns = ['Category', 'Total', 'Count']
    summary = summary.sort_values('Total', ascending=False)
    summary['Percentage'] = (summary['Total'] / summary['Total'].sum() * 100).round(1)
    return summary


def get_available_categories():
    """Get list of all available categories for dropdown."""
    return sorted(CATEGORY_KEYWORDS.keys())


# ============================================================================
# PAGE CONFIG
# ============================================================================

st.set_page_config(
    page_title="Expense Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
.main { padding: 2rem; }
.block-container { padding-top: 2rem; padding-bottom: 2rem; }
[data-testid="stMetricValue"] { font-size: 2rem; font-weight: 600; }
h1 { font-weight: 600; margin-bottom: 2rem; }
h2 { font-weight: 500; margin-top: 2rem; margin-bottom: 1rem; }
.dataframe { font-size: 0.9rem; }
.stButton button { width: 100%; }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# SESSION STATE
# ============================================================================

for key, default in {
    "df":                None,
    "edited_categories": {},
    "user_info":         None,
    "credentials":       None,
    "personal_rules":    {},
    "oauth_state":       None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ============================================================================
# HANDLE GOOGLE OAUTH CALLBACK
# Streamlit re-runs when URL changes — catch the ?code= param here
# ============================================================================

query_params = st.query_params
if "code" in query_params:
    code = query_params["code"]
    if st.session_state.credentials is None:
        with st.spinner("Completing login..."):
            creds = exchange_code_for_credentials(code)
            if creds:
                st.session_state.credentials   = credentials_to_dict(creds)
                st.session_state.user_info     = get_user_info(creds)
                service = get_drive_service(creds)
                st.session_state.personal_rules = load_rules_from_drive(service)
                n = len(st.session_state.personal_rules)
                st.success(f"Logged in! Loaded {n} personal rule{'s' if n != 1 else ''}.")
    st.query_params.clear()
    st.rerun()


# ============================================================================
# HEADER — title left, login button right
# ============================================================================

col_title, col_login = st.columns([3, 1])

with col_title:
    st.title("💰 Expense Tracker")

with col_login:
    if st.session_state.credentials is None:
        if GOOGLE_CLIENT_ID:
            auth_url = get_google_auth_url()
            st.link_button("🔐 Sign in with Google", auth_url, use_container_width=True)
            st.caption("Sign in to save your category rules")
        else:
            st.warning("Google login not configured")
    else:
        user = st.session_state.user_info or {}
        st.success(f"✅ {user.get('name', 'Signed in')}")
        n = len(st.session_state.personal_rules)
        st.caption(f"{n} personal rule{'s' if n != 1 else ''} loaded")
        if st.button("Sign out", use_container_width=True):
            for k in ["credentials", "user_info", "df"]:
                st.session_state[k] = None
            st.session_state.personal_rules    = {}
            st.session_state.edited_categories = {}
            st.rerun()


# ============================================================================
# FILE UPLOAD
# ============================================================================

st.markdown("---")

if st.session_state.credentials is None:
    st.info("💡 You're in guest mode. Sign in with Google to save your category corrections between sessions.")

uploaded_file = st.file_uploader(
    "Upload Bank Statement (Excel)",
    type=['xlsx', 'xls'],
    help="Upload your bank statement. Supports single-month and multi-month files from any Indian bank."
)

if uploaded_file is not None:
    if st.session_state.df is None or st.session_state.get('last_upload') != uploaded_file.name:
        with st.spinner("Processing transactions..."):
            st.session_state.df = load_and_process_statement(
                uploaded_file,
                st.session_state.personal_rules
            )
            st.session_state.last_upload       = uploaded_file.name
            st.session_state.edited_categories = {}

    if st.session_state.df is not None:
        n_months = st.session_state.df['Date'].dt.to_period('M').nunique()
        personal_applied = sum(
            1 for row in st.session_state.df.itertuples()
            if apply_personal_rules(row.Particulars, st.session_state.personal_rules) is not None
        )
        msg = f"✅ Processed {len(st.session_state.df)} transactions across {n_months} month(s)"
        if personal_applied > 0:
            msg += f" — {personal_applied} categorized by your personal rules"
        st.success(msg)
    else:
        st.error("❌ Failed to process file. Please check the format and try again.")


# ============================================================================
# MAIN TABS
# ============================================================================

if st.session_state.df is not None:
    df = st.session_state.df.copy()

    # Apply any manual category edits from the Fix Categories tab
    for idx, new_category in st.session_state.edited_categories.items():
        df.loc[idx, 'Category'] = new_category

    st.markdown("---")

    # Build tab list — Monthly Analysis only appears if module is available
    if MULTI_MONTH_AVAILABLE:
        tab1, tab2, tab3, tab4 = st.tabs([
            "📊 Dashboard",
            "📅 Monthly Analysis",
            "📋 All Transactions",
            "✏️ Fix Categories"
        ])
    else:
        tab1, tab3, tab4 = st.tabs([
            "📊 Dashboard",
            "📋 All Transactions",
            "✏️ Fix Categories"
        ])
        tab2 = None

    # ========================================================================
    # TAB 1: DASHBOARD
    # ========================================================================

    with tab1:
        st.header("Spending Overview")

        n_months           = df['Date'].dt.to_period('M').nunique()
        total_spent        = df['Amount'].sum()
        total_transactions = len(df)
        uncategorized_count = len(df[df['Category'] == 'Miscellaneous'])
        avg_per_month      = total_spent / n_months if n_months > 0 else total_spent

        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("Total Spent",   f"₹{total_spent:,.0f}")
        with col2: st.metric("Transactions",  f"{total_transactions:,}")
        with col3: st.metric("Avg per Month", f"₹{avg_per_month:,.0f}")
        with col4: st.metric("Miscellaneous", f"{uncategorized_count}")

        if n_months > 1:
            st.caption(f"Aggregate across {n_months} months of data")

        st.markdown("---")

        col1, col2 = st.columns(2)
        category_summary = get_category_summary(df)

        with col1:
            st.subheader("Spending by Category")
            fig_pie = px.pie(
                category_summary,
                values='Total',
                names='Category',
                color='Category',
                color_discrete_map=CATEGORY_COLORS,
                hole=0.4
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie.update_layout(
                showlegend=False, height=400,
                margin=dict(t=20, b=20, l=20, r=20)
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            st.subheader("Top Categories")
            top_categories = category_summary.head(8)
            fig_bar = px.bar(
                top_categories,
                x='Total', y='Category',
                orientation='h',
                color='Category',
                color_discrete_map=CATEGORY_COLORS,
                text='Total'
            )
            fig_bar.update_traces(texttemplate='₹%{text:,.0f}', textposition='outside')
            fig_bar.update_layout(
                showlegend=False, height=400,
                margin=dict(t=20, b=20, l=20, r=60),
                xaxis_title="Amount (₹)", yaxis_title=""
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        st.markdown("---")
        st.subheader("Category Breakdown")
        summary_display = category_summary.copy()
        summary_display['Total']      = summary_display['Total'].apply(lambda x: f"₹{x:,.2f}")
        summary_display['Percentage'] = summary_display['Percentage'].apply(lambda x: f"{x}%")
        st.dataframe(summary_display, hide_index=True, use_container_width=True)

        st.markdown("---")
        st.subheader("💾 Download Your Report")

        col1, col2 = st.columns(2)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with col1:
            st.markdown("**📊 Detailed Data (Excel)**")
            st.write("All transactions with categories")
            output = BytesIO()
            df.to_excel(output, index=False, engine='openpyxl')
            st.download_button(
                label="📥 Download Excel",
                data=output.getvalue(),
                file_name=f"expenses_{timestamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        with col2:
            st.markdown("**📄 Summary Report (PDF)**")
            st.write("Charts and category breakdown")
            if st.button("🔄 Generate PDF", use_container_width=True, type="secondary"):
                with st.spinner("Creating PDF report..."):
                    try:
                        pdf_data = generate_pdf_report(df, category_summary)
                        st.session_state.pdf_data     = pdf_data.getvalue()
                        st.session_state.pdf_filename = f"expense_report_{timestamp}.pdf"
                        st.success("✅ PDF ready!")
                    except Exception as e:
                        st.error(f"❌ Error generating PDF: {str(e)}")
            if 'pdf_data' in st.session_state:
                st.download_button(
                    label="📥 Download PDF",
                    data=st.session_state.pdf_data,
                    file_name=st.session_state.pdf_filename,
                    mime="application/pdf",
                    use_container_width=True
                )

    # ========================================================================
    # TAB 2: MONTHLY ANALYSIS (original module, unchanged)
    # ========================================================================

    if MULTI_MONTH_AVAILABLE and tab2 is not None:
        with tab2:
            render_monthly_analysis_tab(df)

    # ========================================================================
    # TAB 3: ALL TRANSACTIONS
    # ========================================================================

    with tab3:
        st.header("All Transactions")

        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            categories        = ['All'] + sorted(df['Category'].unique().tolist())
            selected_category = st.selectbox("Filter by Category", categories)
        with col2:
            if not df['Date'].isna().all():
                min_date   = df['Date'].min()
                max_date   = df['Date'].max()
                date_range = st.date_input(
                    "Date Range",
                    value=(min_date, max_date),
                    min_value=min_date, max_value=max_date
                )
        with col3:
            search_term = st.text_input("Search Particulars", "")

        filtered_df = df.copy()
        if selected_category != 'All':
            filtered_df = filtered_df[filtered_df['Category'] == selected_category]
        if search_term:
            filtered_df = filtered_df[
                filtered_df['Particulars'].str.contains(search_term, case=False, na=False)
            ]
        if 'date_range' in locals() and len(date_range) == 2:
            start_date, end_date = date_range
            filtered_df = filtered_df[
                (filtered_df['Date'].dt.date >= start_date) &
                (filtered_df['Date'].dt.date <= end_date)
            ]

        st.markdown(f"**Showing {len(filtered_df)} of {len(df)} transactions**")
        display_df = filtered_df.copy()
        display_df['Date']   = display_df['Date'].dt.strftime('%d-%b-%Y')
        display_df['Amount'] = display_df['Amount'].apply(lambda x: f"₹{x:,.2f}")
        st.dataframe(display_df, hide_index=True, use_container_width=True, height=500)

    # ========================================================================
    # TAB 4: FIX CATEGORIES (with learning)
    # ========================================================================

    with tab4:
        st.header("Fix Categories")

        if st.session_state.credentials:
            st.info("✨ Every correction you make here is remembered for future uploads.")
        else:
            st.warning("⚠️ Sign in with Google to save your corrections between sessions.")

        needs_review = df[df['Category'] == 'Miscellaneous'].copy()

        if len(needs_review) == 0:
            st.success("🎉 All transactions are categorized!")
        else:
            st.info(f"📝 {len(needs_review)} transactions in Miscellaneous — review and reassign if needed")

            show_filter = st.radio(
                "Show:",
                ["All Miscellaneous", "Only those I haven't reviewed"],
                horizontal=True
            )
            if show_filter == "Only those I haven't reviewed":
                reviewed_indices = set(st.session_state.edited_categories.keys())
                needs_review = needs_review[~needs_review.index.isin(reviewed_indices)]

            st.markdown(f"**Reviewing {len(needs_review)} transactions**")
            st.markdown("---")

            available_categories = get_available_categories()

            for idx, row in needs_review.iterrows():
                with st.container():
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**Date:** {row['Date'].strftime('%d-%b-%Y')}")
                        st.markdown(f"**Amount:** ₹{row['Amount']:,.2f}")
                        st.markdown(f"**Type:** {row['Transaction Type']}")
                        st.markdown(f"**Details:** {row['Particulars']}")
                        st.markdown(f"*Current: {row['Category']}*")
                    with col2:
                        current_cat = st.session_state.edited_categories.get(idx, row['Category'])
                        new_cat = st.selectbox(
                            "Category",
                            available_categories,
                            index=available_categories.index(current_cat)
                            if current_cat in available_categories else 0,
                            key=f"cat_{idx}"
                        )
                        if new_cat != row['Category']:
                            if st.button("✓ Save", key=f"btn_{idx}", type="primary"):
                                # Record edit for this session
                                st.session_state.edited_categories[idx] = new_cat

                                # Learn from this correction
                                st.session_state.personal_rules = learn_from_correction(
                                    row['Particulars'],
                                    new_cat,
                                    st.session_state.personal_rules
                                )

                                # Save rules to Drive if logged in
                                if st.session_state.credentials:
                                    creds   = dict_to_credentials(st.session_state.credentials)
                                    service = get_drive_service(creds)
                                    saved   = save_rules_to_drive(service, st.session_state.personal_rules)
                                    if saved:
                                        st.toast("✅ Rule learned and saved to Drive!")
                                else:
                                    st.toast("Rule learned for this session (sign in to save permanently)")

                                st.rerun()
                    st.markdown("---")

            if st.session_state.edited_categories:
                st.success(f"✅ {len(st.session_state.edited_categories)} corrections made this session")

else:
    st.info("👆 Upload a bank statement to get started")
    st.markdown("### Features")
    st.markdown("""
    - 📊 **Visual Dashboard** — Aggregate spending breakdown across all months
    - 📅 **Monthly Analysis** — Compare spending month by month, spot unusual spikes
    - 📋 **Transaction Table** — Filter, search, and review all transactions
    - ✏️ **Fix Categories** — Correct wrong categories; app learns your preferences
    - 🔐 **Sign in with Google** — Your corrections are saved and applied automatically next time
    - 💾 **Download Reports** — Excel and PDF exports
    """)