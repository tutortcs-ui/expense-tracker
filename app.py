"""
EXPENSE TRACKER - STAGE 3: GOOGLE LOGIN + PERSONAL LEARNING
=============================================================

What's new in this version:
- Google login using streamlit-google-auth (no redirect session loss)
- After login: loads YOUR personal category rules from Google Drive
- Your rules apply BEFORE default rules — your preferences always win
- When you fix a category, the app learns and saves the rule to Drive
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
import json
import tempfile
import os
from pathlib import Path
from io import BytesIO

# Google auth — Streamlit-native, no redirect session loss
from streamlit_google_auth import Authenticate

# Google Drive libraries
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# Import Stage 1 categorization logic
from expense_categorizer import (
    categorize_transaction,
    CATEGORY_KEYWORDS
)

# Import multi-month analysis module (optional)
try:
    from multi_month import render_monthly_analysis_tab
    MULTI_MONTH_AVAILABLE = True
except ImportError:
    MULTI_MONTH_AVAILABLE = False


# ============================================================================
# CONFIGURATION
# ============================================================================

GOOGLE_CLIENT_ID     = st.secrets.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI         = st.secrets.get("REDIRECT_URI", "")

DRIVE_FOLDER_NAME = "expense-tracker"
RULES_FILENAME    = "my_rules.json"

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
# GOOGLE AUTH SETUP
# streamlit-google-auth needs a credentials JSON file on disk.
# We build it from Streamlit secrets and write it to a temp file.
# ============================================================================

def get_auth_object():
    """
    Create the Google Auth object each run.
    Writes credentials to a temp JSON file that streamlit-google-auth can read.
    Cannot be cached because it contains a Streamlit widget (cookie manager).
    """
    creds_dict = {
        "web": {
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }
    # Write to a temp file — streamlit-google-auth requires a file path
    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', delete=False
    )
    json.dump(creds_dict, tmp)
    tmp.flush()

    auth = Authenticate(
        secret_credentials_path=tmp.name,
        redirect_uri=REDIRECT_URI,
        cookie_name="expense_tracker_auth",
        cookie_key="expense_tracker_secret_key_2024",
        cookie_expiry_days=30,
    )
    return auth


# ============================================================================
# GOOGLE DRIVE FUNCTIONS
# ============================================================================

def get_drive_service_from_token(token):
    """
    Build a Google Drive service from the OAuth token stored in session state
    after login via streamlit-google-auth.
    """
    creds = Credentials(token=token)
    return build("drive", "v3", credentials=creds)


def get_or_create_folder(service):
    """Find or create the expense-tracker folder in Drive. Returns folder ID."""
    results = service.files().list(
        q=f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)"
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    folder = service.files().create(
        body={"name": DRIVE_FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
        fields="id"
    ).execute()
    return folder["id"]


def load_rules_from_drive(service):
    """
    Load personal category rules from Google Drive.
    Returns dict like {"SWIGGY": "Food"} or empty dict if none saved yet.
    """
    try:
        folder_id = get_or_create_folder(service)
        results = service.files().list(
            q=f"name='{RULES_FILENAME}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)"
        ).execute()
        files = results.get("files", [])
        if not files:
            return {}
        request = service.files().get_media(fileId=files[0]["id"])
        buffer = BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buffer.seek(0)
        return json.loads(buffer.read().decode("utf-8"))
    except Exception as e:
        st.warning(f"Could not load rules from Drive: {str(e)}")
        return {}


def save_rules_to_drive(service, rules):
    """Save personal rules dict back to Google Drive. Overwrites existing file."""
    try:
        folder_id = get_or_create_folder(service)
        rules_bytes = json.dumps(rules, indent=2).encode("utf-8")
        media = MediaIoBaseUpload(BytesIO(rules_bytes), mimetype="application/json")
        results = service.files().list(
            q=f"name='{RULES_FILENAME}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)"
        ).execute()
        files = results.get("files", [])
        if files:
            service.files().update(fileId=files[0]["id"], media_body=media).execute()
        else:
            service.files().create(
                body={"name": RULES_FILENAME, "parents": [folder_id]},
                media_body=media, fields="id"
            ).execute()
        return True
    except Exception as e:
        st.error(f"Could not save rules to Drive: {str(e)}")
        return False


# ============================================================================
# PERSONAL RULES: APPLY + LEARN
# ============================================================================

def apply_personal_rules(particulars, personal_rules):
    """
    Check if any of the user's personal keywords match this transaction.
    Returns the category if matched, or None if no match.
    Personal rules always beat default rules.
    """
    text = str(particulars).upper()
    for keyword, category in personal_rules.items():
        if keyword.upper() in text:
            return category
    return None


def learn_from_correction(particulars, new_category, personal_rules):
    """
    Extract a keyword from the transaction and save it as a personal rule.
    This is how the app learns — one correction = one new rule.
    """
    skip_words = {
        'UPI', 'NEFT', 'IMPS', 'RTGS', 'ACH', 'TO', 'FROM', 'BY',
        'DR', 'CR', 'VPA', 'REF', 'NO', 'TXN', 'TRANSFER', 'PAYMENT',
        'THE', 'AND', 'FOR', 'INR', 'AC'
    }
    for word in str(particulars).upper().split():
        clean = ''.join(c for c in word if c.isalnum())
        if clean and clean not in skip_words and len(clean) > 2:
            personal_rules[clean] = new_category
            break
    return personal_rules


def categorize_with_personal_rules(particulars, tran_type, amount, personal_rules):
    """Categorize using personal rules first, then default rules."""
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
        file_name = uploaded_file.name.lower()
        if file_name.endswith('.xls'):
            raw = pd.read_excel(uploaded_file, header=None, engine='xlrd')
        else:
            raw = pd.read_excel(uploaded_file, header=None, engine='openpyxl')

        COLUMN_KEYWORDS = {
            'date':        ['value date', 'transaction date', 'txn date', 'tran date', 'date'],
            'particulars': ['particulars', 'description', 'narration', 'details', 'transaction details'],
            'tran_type':   ['tran type', 'transaction type', 'mode'],
            'withdrawals': ['withdrawal', 'withdrawals', 'debit', 'paid', 'dr'],
            'deposits':    ['deposit', 'deposits', 'credit', 'received', 'cr'],
        }

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
            **First 5 rows:** {raw.head(5).to_string()}
            """)
            return None

        header_values = [str(v).lower().strip() for v in raw.iloc[header_row_index].values]
        col_map = {}
        for field, keywords in COLUMN_KEYWORDS.items():
            for kw in keywords:
                if kw in header_values:
                    col_map[field] = header_values.index(kw)
                    break

        if 'date' not in col_map or 'particulars' not in col_map:
            st.error(f"❌ Could not locate Date or Particulars columns.")
            return None

        if 'withdrawals' not in col_map:
            st.error(f"❌ Could not find a Withdrawal/Debit column.")
            return None

        data = raw.iloc[header_row_index + 1:].copy()
        data = data[data.iloc[:, col_map['date']].notna()]
        data = data[data.iloc[:, col_map['particulars']].notna()]

        if len(data) == 0:
            st.warning("⚠️ No transaction rows found after the header row.")
            return None

        def clean_amount(val):
            if pd.isna(val) or str(val).strip() in ['', 'nan']:
                return 0.0
            try:
                return float(str(val).replace(',', '').strip())
            except:
                return 0.0

        def clean_date_val(val):
            try:
                return pd.to_datetime(val, dayfirst=True)
            except:
                return pd.NaT

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

        expense_df = clean_data[clean_data['Withdrawals'] > 0].copy()

        if len(expense_df) == 0:
            st.warning("⚠️ No withdrawal transactions found in this file.")
            return None

        expense_df['Category'] = expense_df.apply(
            lambda row: categorize_with_personal_rules(
                row['Particulars'], row['Tran Type'], row['Withdrawals'], personal_rules
            ),
            axis=1
        )

        expense_df = expense_df.rename(columns={
            'Withdrawals': 'Amount',
            'Tran Type':   'Transaction Type'
        })

        return expense_df[['Date', 'Particulars', 'Transaction Type', 'Category', 'Amount']]

    except Exception as e:
        st.error(f"❌ Error processing file: {str(e)}")
        return None


# ============================================================================
# PDF GENERATION — kept exactly from original
# ============================================================================

def generate_pdf_report(df, category_summary):
    """Generate a PDF report with summary stats and pie chart."""
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    pdf_buffer = BytesIO()
    with PdfPages(pdf_buffer) as pdf:
        fig = plt.figure(figsize=(8.5, 11))
        fig.patch.set_facecolor('white')
        fig.text(0.5, 0.96, 'EXPENSE REPORT', ha='center', fontsize=22, weight='bold')
        fig.text(0.5, 0.93, f'Generated on {datetime.now().strftime("%B %d, %Y")}',
                 ha='center', fontsize=11, style='italic', color='#666666')

        from matplotlib.patches import Rectangle
        line1 = Rectangle((0.1, 0.915), 0.8, 0.002, transform=fig.transFigure, color='#CCCCCC')
        fig.patches.append(line1)

        total_spent        = df['Amount'].sum()
        total_transactions = len(df)
        n_months           = df['Date'].dt.to_period('M').nunique()
        avg_monthly        = total_spent / n_months if n_months > 0 else total_spent

        summary_items = [
            ('Total Spent',        f'₹{total_spent:,.2f}'),
            ('Total Transactions', f'{total_transactions:,}'),
            ('Months Covered',     f'{n_months}'),
            ('Average per Month',  f'₹{avg_monthly:,.0f}'),
            ('Miscellaneous',      f'{len(df[df["Category"] == "Miscellaneous"])}'),
        ]
        box_y = 0.85
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
            category_summary['Total'], labels=None, autopct='%1.1f%%',
            colors=colors, startangle=90, pctdistance=0.85
        )
        for at in autotexts:
            at.set_color('white'); at.set_fontsize(9); at.set_weight('bold')
        ax_pie.legend(category_summary['Category'], loc='upper center',
                      bbox_to_anchor=(0.5, -0.05), ncol=3, frameon=False, fontsize=9)
        ax_pie.set_title('Spending by Category', fontsize=13, weight='bold', pad=15)
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
    "personal_rules":    {},
    "rules_loaded":      False,
    "connected":         False,
    "oauth_token":       None,
    "name":              None,
    "email":             None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ============================================================================
# GOOGLE AUTH — streamlit-google-auth handles everything including cookies
# ============================================================================

auth = get_auth_object()
auth.check_authentification()

# ============================================================================
# HEADER
# ============================================================================

col_title, col_login = st.columns([3, 1])

with col_title:
    st.title("💰 Expense Tracker")

with col_login:
    if not st.session_state.get("connected", False):
        # Show login button
        auth.login()
    else:
        # Logged in — show user info
        name  = st.session_state.get("name", "Signed in")
        email = st.session_state.get("email", "")
        st.success(f"✅ {name}")
        n = len(st.session_state.personal_rules)
        st.caption(f"{n} personal rule{'s' if n != 1 else ''} loaded")
        if st.button("Sign out", use_container_width=True):
            auth.logout()
            st.session_state.personal_rules    = {}
            st.session_state.rules_loaded      = False
            st.session_state.edited_categories = {}
            st.session_state.df                = None
            st.rerun()

        # Load rules from Drive once per session after login
        if not st.session_state.rules_loaded:
            token = st.session_state.get("oauth_token")
            if token:
                try:
                    service = get_drive_service_from_token(token)
                    st.session_state.personal_rules = load_rules_from_drive(service)
                    st.session_state.rules_loaded   = True
                except Exception as e:
                    st.warning(f"Could not load Drive rules: {e}")
                    st.session_state.rules_loaded = True


# ============================================================================
# FILE UPLOAD
# ============================================================================

st.markdown("---")

if not st.session_state.get("connected", False):
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

    for idx, new_category in st.session_state.edited_categories.items():
        df.loc[idx, 'Category'] = new_category

    st.markdown("---")

    if MULTI_MONTH_AVAILABLE:
        tab1, tab2, tab3, tab4 = st.tabs([
            "📊 Dashboard", "📅 Monthly Analysis",
            "📋 All Transactions", "✏️ Fix Categories"
        ])
    else:
        tab1, tab3, tab4 = st.tabs([
            "📊 Dashboard", "📋 All Transactions", "✏️ Fix Categories"
        ])
        tab2 = None

    # ========================================================================
    # TAB 1: DASHBOARD
    # ========================================================================

    with tab1:
        st.header("Spending Overview")

        n_months            = df['Date'].dt.to_period('M').nunique()
        total_spent         = df['Amount'].sum()
        total_transactions  = len(df)
        uncategorized_count = len(df[df['Category'] == 'Miscellaneous'])
        avg_per_month       = total_spent / n_months if n_months > 0 else total_spent

        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("Total Spent",   f"₹{total_spent:,.0f}")
        with col2: st.metric("Transactions",  f"{total_transactions:,}")
        with col3: st.metric("Avg per Month", f"₹{avg_per_month:,.0f}")
        with col4: st.metric("Miscellaneous", f"{uncategorized_count}")

        if n_months > 1:
            st.caption(f"Aggregate across {n_months} months of data")

        st.markdown("---")
        category_summary = get_category_summary(df)
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Spending by Category")
            fig_pie = px.pie(
                category_summary, values='Total', names='Category',
                color='Category', color_discrete_map=CATEGORY_COLORS, hole=0.4
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie.update_layout(showlegend=False, height=400,
                                  margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            st.subheader("Top Categories")
            fig_bar = px.bar(
                category_summary.head(8), x='Total', y='Category',
                orientation='h', color='Category',
                color_discrete_map=CATEGORY_COLORS, text='Total'
            )
            fig_bar.update_traces(texttemplate='₹%{text:,.0f}', textposition='outside')
            fig_bar.update_layout(showlegend=False, height=400,
                                  margin=dict(t=20, b=20, l=20, r=60),
                                  xaxis_title="Amount (₹)", yaxis_title="")
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
            if st.button("🔄 Generate PDF", use_container_width=True, type="secondary"):
                with st.spinner("Creating PDF..."):
                    try:
                        pdf_data = generate_pdf_report(df, category_summary)
                        st.session_state.pdf_data     = pdf_data.getvalue()
                        st.session_state.pdf_filename = f"expense_report_{timestamp}.pdf"
                        st.success("✅ PDF ready!")
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
            if 'pdf_data' in st.session_state:
                st.download_button(
                    label="📥 Download PDF",
                    data=st.session_state.pdf_data,
                    file_name=st.session_state.pdf_filename,
                    mime="application/pdf",
                    use_container_width=True
                )

    # ========================================================================
    # TAB 2: MONTHLY ANALYSIS
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
                date_range = st.date_input("Date Range",
                    value=(min_date, max_date), min_value=min_date, max_value=max_date)
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

        if st.session_state.get("connected", False):
            st.info("✨ Every correction you make is remembered for future uploads.")
        else:
            st.warning("⚠️ Sign in with Google to save your corrections between sessions.")

        needs_review = df[df['Category'] == 'Miscellaneous'].copy()

        if len(needs_review) == 0:
            st.success("🎉 All transactions are categorized!")
        else:
            st.info(f"📝 {len(needs_review)} transactions in Miscellaneous")

            show_filter = st.radio(
                "Show:", ["All Miscellaneous", "Only those I haven't reviewed"],
                horizontal=True
            )
            if show_filter == "Only those I haven't reviewed":
                reviewed = set(st.session_state.edited_categories.keys())
                needs_review = needs_review[~needs_review.index.isin(reviewed)]

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
                            "Category", available_categories,
                            index=available_categories.index(current_cat)
                            if current_cat in available_categories else 0,
                            key=f"cat_{idx}"
                        )
                        if new_cat != row['Category']:
                            if st.button("✓ Save", key=f"btn_{idx}", type="primary"):
                                st.session_state.edited_categories[idx] = new_cat
                                st.session_state.personal_rules = learn_from_correction(
                                    row['Particulars'], new_cat,
                                    st.session_state.personal_rules
                                )
                                if st.session_state.get("connected", False):
                                    token = st.session_state.get("oauth_token")
                                    if token:
                                        try:
                                            service = get_drive_service_from_token(token)
                                            if save_rules_to_drive(service, st.session_state.personal_rules):
                                                st.toast("✅ Rule learned and saved to Drive!")
                                        except Exception as e:
                                            st.toast(f"Rule learned but Drive save failed: {e}")
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