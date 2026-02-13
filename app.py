"""
EXPENSE TRACKER - STAGE 2: LOCAL WEB UI
========================================
Streamlit web interface for expense categorization and analysis.

FEATURES:
- Upload and process bank statements
- Visual spending dashboard (charts, summary)
- Interactive transaction table with filters
- Quick categorization for uncategorized items
- Save processed files locally for month-over-month comparison

Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os
from pathlib import Path

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

# Create data directory for saved files
DATA_DIR = Path("data/processed_statements")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Category colors for charts (clean, minimal palette)
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
# HELPER FUNCTIONS
# ============================================================================

def load_and_process_statement(uploaded_file):
    """
    Load bank statement and apply Stage 1 categorization.
    
    Args:
        uploaded_file: Streamlit uploaded file object
        
    Returns:
        DataFrame: Processed expense data with categories
    """
    try:
        # Try to read Excel file - first attempt with header at row 10 (common Indian bank format)
        try:
            df = pd.read_excel(uploaded_file, header=10)
        except:
            # If that fails, try reading from row 0 (standard Excel)
            df = pd.read_excel(uploaded_file, header=0)
        
        # Check if required columns exist
        # Common column names across banks
        date_col = None
        particulars_col = None
        withdrawal_col = None
        deposit_col = None
        
        # Find date column
        for col in df.columns:
            if any(x in str(col).lower() for x in ['date', 'value date', 'transaction date']):
                date_col = col
                break
        
        # Find particulars/description column
        for col in df.columns:
            if any(x in str(col).lower() for x in ['particulars', 'description', 'narration', 'details', 'transaction details']):
                particulars_col = col
                break
        
        # Find withdrawal column
        for col in df.columns:
            if any(x in str(col).lower() for x in ['withdrawal', 'debit', 'paid', 'dr']):
                withdrawal_col = col
                break
        
        # Find deposit column  
        for col in df.columns:
            if any(x in str(col).lower() for x in ['deposit', 'credit', 'received', 'cr']):
                deposit_col = col
                break
        
        # Verify we found the essential columns
        if not all([date_col, particulars_col, withdrawal_col]):
            st.error(f"""
            ❌ Could not identify required columns in your Excel file.
            
            **Required columns (with any of these names):**
            - Date: 'Date', 'Value Date', 'Transaction Date'
            - Description: 'Particulars', 'Description', 'Narration', 'Details'
            - Withdrawals: 'Withdrawal', 'Debit', 'Paid', 'Dr'
            
            **Your file has these columns:**
            {', '.join(df.columns.tolist())}
            
            **Please make sure your Excel file has standard bank statement columns.**
            """)
            return None
        
        # Clean data - remove rows where all essential columns are empty
        df = df.dropna(subset=[date_col, particulars_col], how='all')
        
        # Filter only rows with actual transaction data
        df = df[df[date_col].notna()]
        
        # Clean numeric columns
        df['Withdrawal_Clean'] = df[withdrawal_col].apply(clean_numeric_value)
        if deposit_col:
            df['Deposit_Clean'] = df[deposit_col].apply(clean_numeric_value)
        else:
            df['Deposit_Clean'] = 0
        
        # Clean date column
        df['Value Date_Clean'] = df[date_col].apply(clean_date)
        
        # Filter only expenses (withdrawals)
        expense_df = df[df['Withdrawal_Clean'] > 0].copy()
        
        if len(expense_df) == 0:
            st.warning("⚠️ No expense transactions found in the uploaded file.")
            return None
        
        # Categorize each transaction
        # Try to find transaction type column
        tran_type_col = None
        for col in df.columns:
            if any(x in str(col).lower() for x in ['type', 'tran type', 'transaction type', 'mode']):
                tran_type_col = col
                break
        
        if tran_type_col:
            expense_df['Category'] = expense_df.apply(
                lambda row: categorize_transaction(row[particulars_col], row[tran_type_col]),
                axis=1
            )
        else:
            expense_df['Category'] = expense_df.apply(
                lambda row: categorize_transaction(row[particulars_col], 'Unknown'),
                axis=1
            )
        
        # Create clean output dataframe
        output_df = pd.DataFrame({
            'Date': expense_df['Value Date_Clean'],
            'Particulars': expense_df[particulars_col],
            'Transaction Type': expense_df[tran_type_col] if tran_type_col else 'N/A',
            'Category': expense_df['Category'],
            'Amount': expense_df['Withdrawal_Clean']
        })
        
        return output_df
        
    except Exception as e:
        st.error(f"""
        ❌ Error processing file: {str(e)}
        
        **Please make sure:**
        - File is a valid Excel file (.xlsx or .xls)
        - File contains bank transaction data
        - File has columns for Date, Description, and Amount
        
        **If you continue to have issues, please contact support.**
        """)
        return None


def save_processed_statement(df, filename):
    """
    Save processed statement to data directory.
    
    Args:
        df: Processed DataFrame
        filename: Name for the saved file
    """
    filepath = DATA_DIR / filename
    df.to_excel(filepath, index=False, engine='openpyxl')
    return filepath


def get_category_summary(df):
    """
    Calculate spending summary by category.
    
    Args:
        df: Expense DataFrame
        
    Returns:
        DataFrame: Category-wise summary (sorted by amount)
    """
    summary = df.groupby('Category')['Amount'].agg(['sum', 'count']).reset_index()
    summary.columns = ['Category', 'Total', 'Count']
    summary = summary.sort_values('Total', ascending=False)
    summary['Percentage'] = (summary['Total'] / summary['Total'].sum() * 100).round(1)
    return summary


def get_available_categories():
    """Get list of all available categories for dropdown."""
    return sorted(CATEGORY_KEYWORDS.keys())


# ============================================================================
# STREAMLIT PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="Expense Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for clean, minimal design
st.markdown("""
<style>
    /* Main content area */
    .main {
        padding: 2rem;
    }
    
    /* Remove extra padding */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Metric cards */
    [data-testid="stMetricValue"] {
        font-size: 2rem;
        font-weight: 600;
    }
    
    /* Headers */
    h1 {
        font-weight: 600;
        margin-bottom: 2rem;
    }
    
    h2 {
        font-weight: 500;
        margin-top: 2rem;
        margin-bottom: 1rem;
    }
    
    /* Tables */
    .dataframe {
        font-size: 0.9rem;
    }
    
    /* Buttons */
    .stButton button {
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

if 'df' not in st.session_state:
    st.session_state.df = None
if 'edited_categories' not in st.session_state:
    st.session_state.edited_categories = {}


# ============================================================================
# MAIN APP
# ============================================================================

st.title("💰 Expense Tracker")

# File upload section (always visible)
st.markdown("---")
uploaded_file = st.file_uploader(
    "Upload Bank Statement (Excel)",
    type=['xlsx', 'xls'],
    help="Upload your bank statement Excel file. Supports most Indian bank formats."
)

if uploaded_file is not None:
    # Process file if not already processed
    if st.session_state.df is None or st.session_state.get('last_upload') != uploaded_file.name:
        with st.spinner("Processing transactions..."):
            st.session_state.df = load_and_process_statement(uploaded_file)
            st.session_state.last_upload = uploaded_file.name
            st.session_state.edited_categories = {}
        
        # Check if processing was successful
        if st.session_state.df is not None:
            st.success(f"✅ Processed {len(st.session_state.df)} transactions")
        else:
            st.error("❌ Failed to process file. Please check the format and try again.")

# Only show tabs if data is loaded
if st.session_state.df is not None:
    df = st.session_state.df.copy()
    
    # Apply any manual category edits
    for idx, new_category in st.session_state.edited_categories.items():
        df.loc[idx, 'Category'] = new_category
    
    st.markdown("---")
    
    # Create tabs
    tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "📋 All Transactions", "✏️ Fix Uncategorized"])
    
    
    # ========================================================================
    # TAB 1: DASHBOARD
    # ========================================================================
    with tab1:
        st.header("Spending Overview")
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        total_spent = df['Amount'].sum()
        total_transactions = len(df)
        uncategorized_count = len(df[df['Category'] == 'Uncategorized'])
        avg_transaction = df['Amount'].mean()
        
        with col1:
            st.metric("Total Spent", f"₹{total_spent:,.0f}")
        with col2:
            st.metric("Transactions", f"{total_transactions:,}")
        with col3:
            st.metric("Uncategorized", f"{uncategorized_count}")
        with col4:
            st.metric("Avg Transaction", f"₹{avg_transaction:,.0f}")
        
        st.markdown("---")
        
        # Charts
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Spending by Category")
            
            # Pie chart
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
                showlegend=False,
                height=400,
                margin=dict(t=20, b=20, l=20, r=20)
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with col2:
            st.subheader("Top Categories")
            
            # Bar chart (top 8 categories)
            top_categories = category_summary.head(8)
            
            fig_bar = px.bar(
                top_categories,
                x='Total',
                y='Category',
                orientation='h',
                color='Category',
                color_discrete_map=CATEGORY_COLORS,
                text='Total'
            )
            fig_bar.update_traces(texttemplate='₹%{text:,.0f}', textposition='outside')
            fig_bar.update_layout(
                showlegend=False,
                height=400,
                margin=dict(t=20, b=20, l=20, r=60),
                xaxis_title="Amount (₹)",
                yaxis_title=""
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        
        # Category breakdown table
        st.markdown("---")
        st.subheader("Category Breakdown")
        
        # Format the summary table nicely
        summary_display = category_summary.copy()
        summary_display['Total'] = summary_display['Total'].apply(lambda x: f"₹{x:,.2f}")
        summary_display['Percentage'] = summary_display['Percentage'].apply(lambda x: f"{x}%")
        
        st.dataframe(
            summary_display,
            hide_index=True,
            use_container_width=True
        )
        
        # Download section
        st.markdown("---")
        col1, col2 = st.columns([3, 1])
        
        with col2:
            # Save button
            if st.button("💾 Save Processed File", type="primary"):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"expenses_{timestamp}.xlsx"
                filepath = save_processed_statement(df, filename)
                st.success(f"✅ Saved to: {filepath}")
    
    
    # ========================================================================
    # TAB 2: ALL TRANSACTIONS
    # ========================================================================
    with tab2:
        st.header("All Transactions")
        
        # Filters
        col1, col2, col3 = st.columns([2, 2, 2])
        
        with col1:
            # Category filter
            categories = ['All'] + sorted(df['Category'].unique().tolist())
            selected_category = st.selectbox("Filter by Category", categories)
        
        with col2:
            # Date range filter
            if not df['Date'].isna().all():
                min_date = df['Date'].min()
                max_date = df['Date'].max()
                date_range = st.date_input(
                    "Date Range",
                    value=(min_date, max_date),
                    min_value=min_date,
                    max_value=max_date
                )
        
        with col3:
            # Search
            search_term = st.text_input("Search Particulars", "")
        
        # Apply filters
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
        
        # Display table
        display_df = filtered_df.copy()
        display_df['Date'] = display_df['Date'].dt.strftime('%d-%b-%Y')
        display_df['Amount'] = display_df['Amount'].apply(lambda x: f"₹{x:,.2f}")
        
        st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            height=500
        )
    
    
    # ========================================================================
    # TAB 3: FIX UNCATEGORIZED
    # ========================================================================
    with tab3:
        st.header("Fix Uncategorized Transactions")
        
        # Get uncategorized and miscellaneous
        needs_review = df[df['Category'].isin(['Uncategorized', 'Miscellaneous'])].copy()
        
        if len(needs_review) == 0:
            st.success("🎉 All transactions are categorized!")
        else:
            st.info(f"📝 {len(needs_review)} transactions need review")
            
            # Show filter option
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
            
            # Available categories for dropdown
            available_categories = get_available_categories()
            
            # Show each transaction with edit option
            for idx, row in needs_review.iterrows():
                with st.container():
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        # Transaction details
                        st.markdown(f"**Date:** {row['Date'].strftime('%d-%b-%Y')}")
                        st.markdown(f"**Amount:** ₹{row['Amount']:,.2f}")
                        st.markdown(f"**Type:** {row['Transaction Type']}")
                        st.markdown(f"**Details:** {row['Particulars']}")
                        st.markdown(f"*Current Category: {row['Category']}*")
                    
                    with col2:
                        # Category selector
                        current_category = st.session_state.edited_categories.get(idx, row['Category'])
                        
                        new_category = st.selectbox(
                            "Category",
                            available_categories,
                            index=available_categories.index(current_category) if current_category in available_categories else 0,
                            key=f"cat_{idx}"
                        )
                        
                        # Save if changed
                        if new_category != row['Category']:
                            if st.button("✓ Update", key=f"btn_{idx}", type="primary"):
                                st.session_state.edited_categories[idx] = new_category
                                st.rerun()
                    
                    st.markdown("---")
            
            # Show summary of changes
            if len(st.session_state.edited_categories) > 0:
                st.success(f"✅ {len(st.session_state.edited_categories)} categories updated (not yet saved)")
                st.info("💡 Go to Dashboard tab and click 'Save Processed File' to save your changes")

else:
    # Welcome message when no file is uploaded
    st.info("👆 Upload a bank statement to get started")
    
    st.markdown("### Features")
    st.markdown("""
    - 📊 **Visual Dashboard** - See your spending breakdown with charts
    - 📋 **Transaction Table** - Filter, search, and review all transactions
    - ✏️ **Quick Categorization** - Fix uncategorized items with full transaction details
    - 💾 **Save Processed Files** - Keep monthly statements for comparison
    """)
