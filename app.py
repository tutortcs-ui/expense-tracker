"""
EXPENSE TRACKER - STAGE 2: LOCAL WEB UI
========================================
Streamlit web interface for expense categorization and analysis.

FEATURES:
- Upload and process bank statements (any Indian bank format)
- Visual spending dashboard (charts, summary) — aggregate across all months
- Monthly Analysis tab — month-by-month comparison and attention flags
- Interactive transaction table with filters
- Quick categorization for uncategorized items

Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os
from pathlib import Path
from io import BytesIO

# Import Stage 1 categorization logic
from expense_categorizer import (
    categorize_transaction,
    clean_numeric_value,
    clean_date,
    CATEGORY_KEYWORDS
)

# Import multi-month analysis module (optional — tab disappears if file is missing)
try:
    from multi_month import render_monthly_analysis_tab
    MULTI_MONTH_AVAILABLE = True
except ImportError:
    MULTI_MONTH_AVAILABLE = False


# ============================================================================
# CONFIGURATION
# ============================================================================

DATA_DIR = Path("data/processed_statements")
DATA_DIR.mkdir(parents=True, exist_ok=True)

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
# FILE PARSER
# ============================================================================

def load_and_process_statement(uploaded_file):
    """
    Load bank statement from any Indian bank and extract only the 5 columns we need.

    Strategy: Scan every row until we find one that looks like a header (contains
    keywords like 'date', 'particulars', 'withdrawal'). Then extract ONLY those
    columns — blank columns, bank info rows, junk rows are all discarded.

    Works across SBI, HDFC, Axis, Federal Bank, and most Indian bank formats.
    """
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
        expense_df = clean_data[clean_data['Withdrawals'] > 0].copy()

        if len(expense_df) == 0:
            st.warning("⚠️ No withdrawal transactions found in this file.")
            return None

        expense_df['Category'] = expense_df.apply(
            lambda row: categorize_transaction(row['Particulars'], row['Tran Type'], row['Withdrawals']),
            axis=1
        )

        # Rename for consistency with rest of app
        expense_df = expense_df.rename(columns={
            'Withdrawals': 'Amount',
            'Tran Type': 'Transaction Type'
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
# PDF GENERATION
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

        total_spent = df['Amount'].sum()
        total_transactions = len(df)
        uncategorized = len(df[df['Category'] == 'Uncategorized'])
        avg_transaction = df['Amount'].mean()

        # Detect number of months
        n_months = df['Date'].dt.to_period('M').nunique()
        avg_monthly = total_spent / n_months if n_months > 0 else total_spent

        summary_items = [
            ('Total Spent', f'₹{total_spent:,.2f}'),
            ('Total Transactions', f'{total_transactions:,}'),
            ('Months Covered', f'{n_months}'),
            ('Average per Month', f'₹{avg_monthly:,.0f}'),
            ('Uncategorized Items', f'{uncategorized}'),
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

if 'df' not in st.session_state:
    st.session_state.df = None
if 'edited_categories' not in st.session_state:
    st.session_state.edited_categories = {}


# ============================================================================
# MAIN APP
# ============================================================================

st.title("💰 Expense Tracker")

st.markdown("---")
uploaded_file = st.file_uploader(
    "Upload Bank Statement (Excel)",
    type=['xlsx', 'xls'],
    help="Upload your bank statement. Supports single-month and multi-month files from any Indian bank."
)

if uploaded_file is not None:
    if st.session_state.df is None or st.session_state.get('last_upload') != uploaded_file.name:
        with st.spinner("Processing transactions..."):
            st.session_state.df = load_and_process_statement(uploaded_file)
            st.session_state.last_upload = uploaded_file.name
            st.session_state.edited_categories = {}

    if st.session_state.df is not None:
        n_months = st.session_state.df['Date'].dt.to_period('M').nunique()
        st.success(f"✅ Processed {len(st.session_state.df)} transactions across {n_months} month(s)")
    else:
        st.error("❌ Failed to process file. Please check the format and try again.")


if st.session_state.df is not None:
    df = st.session_state.df.copy()

    # Apply any manual category edits from the Fix Uncategorized tab
    for idx, new_category in st.session_state.edited_categories.items():
        df.loc[idx, 'Category'] = new_category

    st.markdown("---")

    # Build tab list — Monthly Analysis only appears if module is available
    if MULTI_MONTH_AVAILABLE:
        tab1, tab2, tab3, tab4 = st.tabs([
            "📊 Dashboard",
            "📅 Monthly Analysis",
            "📋 All Transactions",
            "✏️ Fix Uncategorized"
        ])
    else:
        tab1, tab3, tab4 = st.tabs([
            "📊 Dashboard",
            "📋 All Transactions",
            "✏️ Fix Uncategorized"
        ])
        tab2 = None

    # ========================================================================
    # TAB 1: DASHBOARD (aggregate across all months)
    # ========================================================================

    with tab1:
        st.header("Spending Overview")

        n_months = df['Date'].dt.to_period('M').nunique()
        total_spent = df['Amount'].sum()
        total_transactions = len(df)
        uncategorized_count = len(df[df['Category'] == 'Uncategorized'])
        avg_per_month = total_spent / n_months if n_months > 0 else total_spent

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Spent", f"₹{total_spent:,.0f}")
        with col2:
            st.metric("Transactions", f"{total_transactions:,}")
        with col3:
            st.metric("Avg per Month", f"₹{avg_per_month:,.0f}")
        with col4:
            st.metric("Uncategorized", f"{uncategorized_count}")

        if n_months > 1:
            st.caption(f"Aggregate across {n_months} months of data")

        st.markdown("---")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Spending by Category")
            category_summary = get_category_summary(df)
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
        summary_display['Total'] = summary_display['Total'].apply(lambda x: f"₹{x:,.2f}")
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
                        st.session_state.pdf_data = pdf_data.getvalue()
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
    # TAB 2: MONTHLY ANALYSIS (new module)
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
            categories = ['All'] + sorted(df['Category'].unique().tolist())
            selected_category = st.selectbox("Filter by Category", categories)
        with col2:
            if not df['Date'].isna().all():
                min_date = df['Date'].min()
                max_date = df['Date'].max()
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
        display_df['Date'] = display_df['Date'].dt.strftime('%d-%b-%Y')
        display_df['Amount'] = display_df['Amount'].apply(lambda x: f"₹{x:,.2f}")
        st.dataframe(display_df, hide_index=True, use_container_width=True, height=500)

    # ========================================================================
    # TAB 4: FIX UNCATEGORIZED
    # ========================================================================

    with tab4:
        st.header("Fix Uncategorized Transactions")
        needs_review = df[df['Category'].isin(['Uncategorized', 'Miscellaneous'])].copy()

        if len(needs_review) == 0:
            st.success("🎉 All transactions are categorized!")
        else:
            st.info(f"📝 {len(needs_review)} transactions need review")
            show_filter = st.radio(
                "Show:",
                ["Uncategorized only", "Miscellaneous only", "Both"],
                horizontal=True
            )
            if show_filter == "Uncategorized only":
                needs_review = needs_review[needs_review['Category'] == 'Uncategorized']
            elif show_filter == "Miscellaneous only":
                needs_review = needs_review[needs_review['Category'] == 'Miscellaneous']

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
                        st.markdown(f"*Current Category: {row['Category']}*")
                    with col2:
                        current_category = st.session_state.edited_categories.get(idx, row['Category'])
                        new_category = st.selectbox(
                            "Category",
                            available_categories,
                            index=available_categories.index(current_category)
                            if current_category in available_categories else 0,
                            key=f"cat_{idx}"
                        )
                        if new_category != row['Category']:
                            if st.button("✓ Update", key=f"btn_{idx}", type="primary"):
                                st.session_state.edited_categories[idx] = new_category
                                st.rerun()
                    st.markdown("---")

            if len(st.session_state.edited_categories) > 0:
                st.success(f"✅ {len(st.session_state.edited_categories)} categories updated")

else:
    st.info("👆 Upload a bank statement to get started")
    st.markdown("### Features")
    st.markdown("""
    - 📊 **Visual Dashboard** — Aggregate spending breakdown across all months
    - 📅 **Monthly Analysis** — Compare spending month by month, spot unusual spikes
    - 📋 **Transaction Table** — Filter, search, and review all transactions
    - ✏️ **Quick Categorization** — Fix uncategorized items
    - 💾 **Download Reports** — Excel and PDF exports
    """)
