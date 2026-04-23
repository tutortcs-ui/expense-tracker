"""
EXPENSE TRACKER - STAGE 3: GOOGLE LOGIN + PERSONAL LEARNING
=============================================================
What's new in this version:
- Google OAuth login button
- After login: loads YOUR personal category rules from Google Drive
- Your rules are applied BEFORE default rules (so your preferences always win)
- When you fix a category, the app learns and saves back to Drive automatically
- Guest mode still works — just no saving between sessions

Run locally: streamlit run app.py
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
import base64
import requests

# Google OAuth libraries
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# Import our Stage 1 categorization logic
from expense_categorizer import (
    categorize_transaction,
    clean_numeric_value,
    clean_date,
    CATEGORY_KEYWORDS
)

# ============================================================================
# CONFIGURATION
# ============================================================================

# These come from Streamlit secrets (never hardcode these)
GOOGLE_CLIENT_ID     = st.secrets.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI         = st.secrets.get("REDIRECT_URI", "")

# The folder name we create in your Google Drive
DRIVE_FOLDER_NAME = "expense-tracker"

# The filename where your personal rules are stored
RULES_FILENAME = "my_rules.json"

# Google API scopes — what we're allowed to access
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.file",  # Only files created by this app
]

# Category colors for charts
CATEGORY_COLORS = {
    'Food': '#4CAF50',
    'Travel': '#2196F3',
    'Medical': '#F44336',
    'Books': '#9C27B0',
    'Tools': '#FF9800',
    'Garden': '#8BC34A',
    'Rent': '#795548',
    'Clothes': '#E91E63',
    'Priyanka': '#00BCD4',
    'Miscellaneous': '#9E9E9E',
    'Uncategorized': '#607D8B'
}

# ============================================================================
# GOOGLE OAUTH FUNCTIONS
# ============================================================================

def get_google_auth_url():
    """
    Generate the Google login URL.
    When user clicks this, Google asks them to sign in and grant permission.
    Returns the URL to redirect the user to.
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
    After Google redirects back with a 'code', exchange it for real credentials.
    This gives us a token we can use to access Drive.
    Returns a Credentials object or None if it fails.
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
    """
    After login, fetch the user's name and email from Google.
    Returns a dict with 'name' and 'email'.
    """
    try:
        resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {credentials.token}"}
        )
        return resp.json()
    except:
        return {"name": "User", "email": ""}


def credentials_to_dict(credentials):
    """Convert credentials object to a plain dict so we can store in session state."""
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
    }


def dict_to_credentials(creds_dict):
    """Rebuild credentials object from the dict stored in session state."""
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
    """
    Create a Google Drive service object using the user's credentials.
    This is what we use to read/write files on their Drive.
    """
    return build("drive", "v3", credentials=credentials)


def get_or_create_folder(service):
    """
    Find our 'expense-tracker' folder in Drive, or create it if it doesn't exist.
    Returns the folder ID.
    """
    # Search for existing folder
    results = service.files().list(
        q=f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)"
    ).execute()

    files = results.get("files", [])
    if files:
        return files[0]["id"]  # Folder already exists

    # Create the folder
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

        # Look for the rules file in our folder
        results = service.files().list(
            q=f"name='{RULES_FILENAME}' and '{folder_id}' in parents and trashed=false",
            fields="files(id, name)"
        ).execute()

        files = results.get("files", [])
        if not files:
            return {}  # No rules yet — fresh start

        # Download and parse the rules file
        file_id = files[0]["id"]
        request = service.files().get_media(fileId=file_id)
        buffer = BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        buffer.seek(0)
        rules = json.loads(buffer.read().decode("utf-8"))
        return rules

    except Exception as e:
        st.warning(f"Could not load your rules from Drive: {str(e)}")
        return {}


def save_rules_to_drive(service, rules):
    """
    Save the user's updated personal rules back to their Google Drive.
    Overwrites the existing file if it exists.
    Rules format: {"SWIGGY": "Food", "UBER": "Travel", ...}
    """
    try:
        folder_id = get_or_create_folder(service)

        # Convert rules dict to JSON bytes
        rules_json = json.dumps(rules, indent=2).encode("utf-8")
        media = MediaIoBaseUpload(BytesIO(rules_json), mimetype="application/json")

        # Check if file already exists
        results = service.files().list(
            q=f"name='{RULES_FILENAME}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)"
        ).execute()

        files = results.get("files", [])
        if files:
            # Update existing file
            service.files().update(
                fileId=files[0]["id"],
                media_body=media
            ).execute()
        else:
            # Create new file
            file_metadata = {
                "name": RULES_FILENAME,
                "parents": [folder_id]
            }
            service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id"
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
    Check if any keyword from the user's personal rules matches this transaction.
    Personal rules always win over default rules.
    Returns the category string if a match is found, or None if no match.
    """
    particulars_upper = str(particulars).upper()
    for keyword, category in personal_rules.items():
        if keyword.upper() in particulars_upper:
            return category
    return None  # No personal rule matched


def learn_from_correction(particulars, new_category, personal_rules):
    """
    When the user fixes a category, extract a keyword from the transaction
    description and save it as a new personal rule.
    This is how the app learns — each correction teaches it one new rule.
    Returns the updated rules dict.
    """
    # Extract the most useful keyword from the particulars
    # Strategy: take the first meaningful word (skip common banking words)
    skip_words = {
        'UPI', 'NEFT', 'IMPS', 'RTGS', 'ACH', 'TO', 'FROM', 'BY',
        'DR', 'CR', 'VPA', 'REF', 'NO', 'TXN', 'TRANSFER', 'PAYMENT',
        'THE', 'AND', 'FOR', 'INR', 'A/C', 'AC'
    }

    words = str(particulars).upper().split()
    keyword = None
    for word in words:
        # Clean the word — remove special characters
        clean_word = ''.join(c for c in word if c.isalnum())
        if clean_word and clean_word not in skip_words and len(clean_word) > 2:
            keyword = clean_word
            break

    if keyword:
        personal_rules[keyword] = new_category

    return personal_rules


def categorize_with_personal_rules(particulars, tran_type, personal_rules):
    """
    Categorize a transaction using personal rules first, then default rules.
    Personal rules always take priority — this is what makes it personalized.
    """
    # First: check user's personal rules
    personal_category = apply_personal_rules(particulars, personal_rules)
    if personal_category:
        return personal_category

    # Second: fall back to default rules from expense_categorizer.py
    return categorize_transaction(particulars, tran_type)


# ============================================================================
# FILE PROCESSING
# ============================================================================

def load_and_process_statement(uploaded_file, personal_rules):
    """
    Load bank statement Excel file and categorize transactions.
    Uses personal rules first, then default rules.
    Returns a processed DataFrame with categories applied.
    """
    try:
        try:
            df = pd.read_excel(uploaded_file, header=10)
        except:
            df = pd.read_excel(uploaded_file, header=0)

        # Find required columns by common names across Indian banks
        date_col = particulars_col = withdrawal_col = deposit_col = tran_type_col = None

        for col in df.columns:
            col_lower = str(col).lower()
            if any(x in col_lower for x in ['date', 'value date', 'transaction date']):
                date_col = date_col or col
            if any(x in col_lower for x in ['particulars', 'description', 'narration', 'details']):
                particulars_col = particulars_col or col
            if any(x in col_lower for x in ['withdrawal', 'debit', 'paid', 'dr']):
                withdrawal_col = withdrawal_col or col
            if any(x in col_lower for x in ['deposit', 'credit', 'received', 'cr']):
                deposit_col = deposit_col or col
            if any(x in col_lower for x in ['type', 'tran type', 'transaction type', 'mode']):
                tran_type_col = tran_type_col or col

        if not all([date_col, particulars_col, withdrawal_col]):
            st.error(f"Could not find required columns. Your file has: {', '.join(df.columns.tolist())}")
            return None

        df = df.dropna(subset=[date_col, particulars_col], how='all')
        df = df[df[date_col].notna()]
        df['Withdrawal_Clean'] = df[withdrawal_col].apply(clean_numeric_value)
        df['Deposit_Clean']    = df[deposit_col].apply(clean_numeric_value) if deposit_col else 0
        df['Value Date_Clean'] = df[date_col].apply(clean_date)

        expense_df = df[df['Withdrawal_Clean'] > 0].copy()
        if len(expense_df) == 0:
            st.warning("No expense transactions found in this file.")
            return None

        # Categorize using personal rules + default rules
        expense_df['Category'] = expense_df.apply(
            lambda row: categorize_with_personal_rules(
                row[particulars_col],
                row[tran_type_col] if tran_type_col else 'Unknown',
                personal_rules
            ),
            axis=1
        )

        output_df = pd.DataFrame({
            'Date':             expense_df['Value Date_Clean'],
            'Particulars':      expense_df[particulars_col],
            'Transaction Type': expense_df[tran_type_col] if tran_type_col else 'N/A',
            'Category':         expense_df['Category'],
            'Amount':           expense_df['Withdrawal_Clean']
        })

        return output_df

    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        return None


# ============================================================================
# SUMMARY HELPERS
# ============================================================================

def get_category_summary(df):
    """Calculate total spending and transaction count per category."""
    summary = df.groupby('Category')['Amount'].agg(['sum', 'count']).reset_index()
    summary.columns = ['Category', 'Total', 'Count']
    summary = summary.sort_values('Total', ascending=False)
    summary['Percentage'] = (summary['Total'] / summary['Total'].sum() * 100).round(1)
    return summary


def get_available_categories():
    """Get all category names for the dropdown selector."""
    return sorted(CATEGORY_KEYWORDS.keys())


# ============================================================================
# PDF REPORT GENERATION
# ============================================================================

def generate_pdf_report(df, category_summary):
    """
    Generate a two-page PDF report:
    Page 1 — summary stats + pie chart
    Page 2 — bar chart + category breakdown table
    """
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    pdf_buffer = BytesIO()
    total_spent       = df['Amount'].sum()
    total_transactions = len(df)

    with PdfPages(pdf_buffer) as pdf:
        # Page 1: Summary + Pie
        fig = plt.figure(figsize=(8.5, 11))
        fig.patch.set_facecolor('white')
        fig.text(0.5, 0.96, 'EXPENSE REPORT', ha='center', fontsize=22, weight='bold')
        fig.text(0.5, 0.93, f'Generated on {datetime.now().strftime("%B %d, %Y")}',
                 ha='center', fontsize=11, style='italic', color='#666666')

        summary_items = [
            ('Total Spent',       f'₹{total_spent:,.2f}'),
            ('Total Transactions', f'{total_transactions:,}'),
            ('Uncategorized',     f'{len(df[df["Category"] == "Uncategorized"])}'),
            ('Avg Transaction',   f'₹{df["Amount"].mean():,.2f}'),
        ]
        box_y = 0.85
        for label, value in summary_items:
            box = Rectangle((0.15, box_y - 0.025), 0.7, 0.03, transform=fig.transFigure,
                             facecolor='#F5F5F5', edgecolor='#E0E0E0', linewidth=0.5)
            fig.patches.append(box)
            fig.text(0.18, box_y, f'{label}:', fontsize=11, va='center', ha='left')
            fig.text(0.55, box_y, value, fontsize=11, weight='bold', ha='left', va='center')
            box_y -= 0.04

        ax_pie = fig.add_axes([0.15, 0.25, 0.7, 0.45])
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

        # Page 2: Bar + Table
        fig = plt.figure(figsize=(8.5, 11))
        fig.patch.set_facecolor('white')
        fig.text(0.5, 0.96, 'CATEGORY BREAKDOWN', ha='center', fontsize=18, weight='bold')

        ax_bar = fig.add_axes([0.2, 0.65, 0.7, 0.25])
        top_cats   = category_summary.head(10)
        colors_bar = [CATEGORY_COLORS.get(c, '#CCCCCC') for c in top_cats['Category']]
        bars = ax_bar.barh(range(len(top_cats)), top_cats['Total'], color=colors_bar, height=0.7)
        ax_bar.set_yticks(range(len(top_cats)))
        ax_bar.set_yticklabels(top_cats['Category'], fontsize=10)
        ax_bar.invert_yaxis()
        ax_bar.set_xlabel('Amount (₹)', fontsize=11, weight='bold')
        ax_bar.set_title('Top Spending Categories', fontsize=13, weight='bold', pad=15)
        ax_bar.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        ax_bar.spines['top'].set_visible(False)
        ax_bar.spines['right'].set_visible(False)
        for bar, value in zip(bars, top_cats['Total']):
            ax_bar.text(bar.get_width() + max(top_cats['Total']) * 0.01,
                        bar.get_y() + bar.get_height() / 2,
                        f'₹{value:,.0f}', ha='left', va='center', fontsize=9, weight='bold')

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    pdf_buffer.seek(0)
    return pdf_buffer


# ============================================================================
# STREAMLIT PAGE CONFIG
# ============================================================================

st.set_page_config(
    page_title="Expense Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
.block-container { padding-top: 2rem; padding-bottom: 2rem; }
[data-testid="stMetricValue"] { font-size: 2rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

for key, default in {
    "df": None,
    "edited_categories": {},
    "user_info": None,
    "credentials": None,
    "personal_rules": {},
    "rules_saved": False,
    "oauth_state": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ============================================================================
# HANDLE GOOGLE OAUTH CALLBACK
# Streamlit re-runs when the URL changes, so we catch the ?code= param here
# ============================================================================

query_params = st.query_params
if "code" in query_params and st.session_state.credentials is None:
    code = query_params["code"]
    with st.spinner("Completing login..."):
        creds = exchange_code_for_credentials(code)
        if creds:
            st.session_state.credentials = credentials_to_dict(creds)
            st.session_state.user_info   = get_user_info(creds)
            # Load personal rules from Drive immediately after login
            service = get_drive_service(creds)
            st.session_state.personal_rules = load_rules_from_drive(service)
            rules_count = len(st.session_state.personal_rules)
            st.success(f"Logged in! Loaded {rules_count} personal rule{'s' if rules_count != 1 else ''}.")
    # Clean the URL
    st.query_params.clear()
    st.rerun()

# ============================================================================
# HEADER: LOGIN STATUS
# ============================================================================

st.title("💰 Expense Tracker")

col_title, col_login = st.columns([3, 1])

with col_login:
    if st.session_state.credentials is None:
        # Not logged in — show login button
        if GOOGLE_CLIENT_ID:
            auth_url = get_google_auth_url()
            st.markdown(
                f'<a href="{auth_url}" target="_self">'
                f'<button style="background:#4285F4;color:white;border:none;padding:8px 16px;'
                f'border-radius:4px;cursor:pointer;font-size:14px;width:100%">'
                f'🔐 Sign in with Google</button></a>',
                unsafe_allow_html=True
            )
            st.caption("Sign in to save your category rules")
        else:
            st.warning("Google login not configured")
    else:
        # Logged in — show user info and logout
        user = st.session_state.user_info or {}
        st.success(f"✅ {user.get('name', 'Signed in')}")
        rules_count = len(st.session_state.personal_rules)
        st.caption(f"{rules_count} personal rule{'s' if rules_count != 1 else ''} loaded")
        if st.button("Sign out", use_container_width=True):
            for key in ["credentials", "user_info", "personal_rules", "df", "edited_categories"]:
                st.session_state[key] = None if key in ["credentials", "user_info", "df"] else {}
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
    help="Upload your bank statement. Supports most Indian bank formats."
)

if uploaded_file is not None:
    if st.session_state.df is None or st.session_state.get('last_upload') != uploaded_file.name:
        with st.spinner("Processing transactions..."):
            st.session_state.df = load_and_process_statement(
                uploaded_file,
                st.session_state.personal_rules  # Pass personal rules to categorizer
            )
            st.session_state.last_upload = uploaded_file.name
            st.session_state.edited_categories = {}

    if st.session_state.df is not None:
        personal_applied = sum(
            1 for row in st.session_state.df.itertuples()
            if apply_personal_rules(row.Particulars, st.session_state.personal_rules) is not None
        )
        msg = f"✅ Processed {len(st.session_state.df)} transactions"
        if personal_applied > 0:
            msg += f" — {personal_applied} categorized using your personal rules"
        st.success(msg)

# ============================================================================
# MAIN TABS (only shown when data is loaded)
# ============================================================================

if st.session_state.df is not None:
    df = st.session_state.df.copy()

    # Apply any manual edits made this session
    for idx, new_category in st.session_state.edited_categories.items():
        df.loc[idx, 'Category'] = new_category

    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "📋 All Transactions", "✏️ Fix Categories"])

    # ========================================================================
    # TAB 1: DASHBOARD
    # ========================================================================
    with tab1:
        st.header("Spending Overview")

        total_spent       = df['Amount'].sum()
        total_transactions = len(df)
        uncategorized_count = len(df[df['Category'] == 'Uncategorized'])
        avg_transaction   = df['Amount'].mean()

        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("Total Spent",     f"₹{total_spent:,.0f}")
        with col2: st.metric("Transactions",    f"{total_transactions:,}")
        with col3: st.metric("Uncategorized",   f"{uncategorized_count}")
        with col4: st.metric("Avg Transaction", f"₹{avg_transaction:,.0f}")

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
            fig_pie.update_layout(showlegend=False, height=400, margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            st.subheader("Top Categories")
            top_categories = category_summary.head(8)
            fig_bar = px.bar(
                top_categories, x='Total', y='Category', orientation='h',
                color='Category', color_discrete_map=CATEGORY_COLORS, text='Total'
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

        # Downloads
        st.markdown("---")
        st.subheader("💾 Download Your Report")
        col1, col2 = st.columns(2)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with col1:
            st.markdown("**📊 Excel**")
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
            st.markdown("**📄 PDF Report**")
            if st.button("🔄 Generate PDF", use_container_width=True, type="secondary"):
                with st.spinner("Creating PDF..."):
                    try:
                        pdf_data = generate_pdf_report(df, category_summary)
                        st.session_state.pdf_data     = pdf_data.getvalue()
                        st.session_state.pdf_filename = f"expense_report_{timestamp}.pdf"
                        st.success("✅ PDF ready!")
                    except Exception as e:
                        st.error(f"PDF error: {str(e)}")
            if 'pdf_data' in st.session_state:
                st.download_button(
                    label="📥 Download PDF",
                    data=st.session_state.pdf_data,
                    file_name=st.session_state.pdf_filename,
                    mime="application/pdf",
                    use_container_width=True
                )

    # ========================================================================
    # TAB 2: ALL TRANSACTIONS
    # ========================================================================
    with tab2:
        st.header("All Transactions")

        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            categories    = ['All'] + sorted(df['Category'].unique().tolist())
            selected_cat  = st.selectbox("Filter by Category", categories)
        with col2:
            if not df['Date'].isna().all():
                min_date   = df['Date'].min()
                max_date   = df['Date'].max()
                date_range = st.date_input("Date Range", value=(min_date, max_date),
                                           min_value=min_date, max_value=max_date)
        with col3:
            search_term = st.text_input("Search Particulars", "")

        filtered_df = df.copy()
        if selected_cat != 'All':
            filtered_df = filtered_df[filtered_df['Category'] == selected_cat]
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
    # TAB 3: FIX CATEGORIES (with learning)
    # ========================================================================
    with tab3:
        st.header("Fix Categories")

        if st.session_state.credentials:
            st.info("✨ Any correction you make here will be remembered for future uploads.")
        else:
            st.warning("⚠️ Sign in with Google to save your corrections between sessions.")

        needs_review = df[df['Category'].isin(['Uncategorized', 'Miscellaneous'])].copy()

        if len(needs_review) == 0:
            st.success("🎉 All transactions are categorized!")
        else:
            st.markdown(f"**{len(needs_review)} transactions need review**")
            show_filter = st.radio("Show:", ["Uncategorized only", "Miscellaneous only", "Both"], horizontal=True)
            if show_filter == "Uncategorized only":
                needs_review = needs_review[needs_review['Category'] == 'Uncategorized']
            elif show_filter == "Miscellaneous only":
                needs_review = needs_review[needs_review['Category'] == 'Miscellaneous']

            available_categories = get_available_categories()

            for idx, row in needs_review.iterrows():
                with st.container():
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**{row['Particulars']}**")
                        st.markdown(f"₹{row['Amount']:,.2f} · {row['Date'].strftime('%d-%b-%Y')} · {row['Transaction Type']}")
                        st.caption(f"Current: {row['Category']}")
                    with col2:
                        current_cat = st.session_state.edited_categories.get(idx, row['Category'])
                        new_cat = st.selectbox(
                            "Category",
                            available_categories,
                            index=available_categories.index(current_cat) if current_cat in available_categories else 0,
                            key=f"cat_{idx}"
                        )
                        if new_cat != row['Category']:
                            if st.button("✓ Save", key=f"btn_{idx}", type="primary"):
                                # Record the edit for this session
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
    # Welcome screen
    st.info("👆 Upload a bank statement to get started")
    st.markdown("### What this app does")
    st.markdown("""
    - **Reads** your bank statement Excel file
    - **Categorizes** every transaction automatically
    - **Learns** from your corrections — sign in with Google to remember them forever
    - **Shows** your spending breakdown with charts
    - **Downloads** your processed data as Excel or PDF
    """)