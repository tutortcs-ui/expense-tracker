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
    # Read Excel file
    df = pd.read_excel(uploaded_file, header=10)
    
    # Clean data
    df = df[df['Sl. No.'].notna()]
    df = df[df['Sl. No.'].apply(lambda x: str(x).isdigit())]
    
    # Clean numeric columns
    df['Withdrawal_Clean'] = df['Withdrawal'].apply(clean_numeric_value)
    df['Deposit_Clean'] = df['Deposit'].apply(clean_numeric_value)
    df['Value Date_Clean'] = df['Value Date'].apply(clean_date)
    
    # Filter only expenses (withdrawals)
    expense_df = df[df['Withdrawal_Clean'] > 0].copy()
    
    # Categorize each transaction
    expense_df['Category'] = expense_df.apply(
        lambda row: categorize_transaction(row['Particulars'], row['Tran Type']),
        axis=1
    )
    
    # Create clean output dataframe
    output_df = pd.DataFrame({
        'Date': expense_df['Value Date_Clean'],
        'Particulars': expense_df['Particulars'],
        'Transaction Type': expense_df['Tran Type'],
        'Category': expense_df['Category'],
        'Amount': expense_df['Withdrawal_Clean']
    })
    
    return output_df


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
    type=['xlsx'],
    help="Upload your bank statement Excel file (OpTransactionHistory format)"
)

if uploaded_file is not None:
    # Process file if not already processed
    if st.session_state.df is None or st.session_state.get('last_upload') != uploaded_file.name:
        with st.spinner("Processing transactions..."):
            st.session_state.df = load_and_process_statement(uploaded_file)
            st.session_state.last_upload = uploaded_file.name
            st.session_state.edited_categories = {}
        st.success(f"✅ Processed {len(st.session_state.df)} transactions")

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
