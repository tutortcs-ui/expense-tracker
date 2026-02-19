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
from io import BytesIO
import base64

# Import our Stage 1 categorization logic
from expense_categorizer import (
    categorize_transaction,
    clean_numeric_value,
    clean_date,
    CATEGORY_KEYWORDS
)


# ============================================================================
# PDF GENERATION HELPER
# ============================================================================

def generate_pdf_report(df, category_summary):
    """
    Generate a professional PDF report with summary and charts.
    
    Args:
        df: Full expense DataFrame
        category_summary: Category-wise summary DataFrame
    
    Returns:
        BytesIO: PDF file in memory
    """
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    
    # Create PDF in memory
    pdf_buffer = BytesIO()
    
    with PdfPages(pdf_buffer) as pdf:
        # ====================================================================
        # PAGE 1: SUMMARY + PIE CHART (Portrait)
        # ====================================================================
        fig = plt.figure(figsize=(8.5, 11))  # Letter size portrait
        fig.patch.set_facecolor('white')
        
        # Title - Centered
        fig.text(0.5, 0.96, '💰 EXPENSE REPORT', 
                ha='center', fontsize=22, weight='bold')
        
        # Date - Centered
        report_date = datetime.now().strftime('%B %d, %Y')
        fig.text(0.5, 0.93, f'Generated on {report_date}',
                ha='center', fontsize=11, style='italic', color='#666666')
        
        # Horizontal line
        line1 = Rectangle((0.1, 0.915), 0.8, 0.002,
                         transform=fig.transFigure, color='#CCCCCC')
        fig.patches.append(line1)
        
        # Summary Statistics Box
        summary_y = 0.88
        fig.text(0.5, summary_y, 'SUMMARY', 
                ha='center', fontsize=14, weight='bold')
        
        total_spent = df['Amount'].sum()
        total_transactions = len(df)
        uncategorized = len(df[df['Category'] == 'Uncategorized'])
        avg_transaction = df['Amount'].mean()
        
        # Create a nice grid for summary - Values LEFT-aligned in a column
        summary_items = [
            ('Total Spent', f'₹{total_spent:,.2f}'),
            ('Total Transactions', f'{total_transactions:,}'),
            ('Uncategorized Items', f'{uncategorized}'),
            ('Average Transaction', f'₹{avg_transaction:,.2f}'),
        ]
        
        box_y = summary_y - 0.03
        for label, value in summary_items:
            # Light background box
            box = Rectangle((0.15, box_y - 0.025), 0.7, 0.03,
                          transform=fig.transFigure, 
                          facecolor='#F5F5F5', edgecolor='#E0E0E0', linewidth=0.5)
            fig.patches.append(box)
            
            # Label (left side)
            fig.text(0.18, box_y, f'{label}:', fontsize=11, va='center', ha='left')
            # Value (fixed position - LEFT ALIGNED from same starting point)
            fig.text(0.55, box_y, value, fontsize=11, weight='bold', 
                    ha='left', va='center')
            box_y -= 0.04
        
        # Pie Chart - Properly spaced from summary
        ax_pie = fig.add_axes([0.15, 0.25, 0.7, 0.45])  # [left, bottom, width, height]
        
        # Get colors
        colors = [CATEGORY_COLORS.get(cat, '#CCCCCC') for cat in category_summary['Category']]
        
        # Create pie chart with better label positioning
        wedges, texts, autotexts = ax_pie.pie(
            category_summary['Total'],
            labels=None,  # Don't put labels on pie
            autopct='%1.1f%%',
            colors=colors,
            startangle=90,
            pctdistance=0.85
        )
        
        # Style percentage labels
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(9)
            autotext.set_weight('bold')
        
        # Add legend below the pie chart
        ax_pie.legend(
            category_summary['Category'],
            loc='upper center',
            bbox_to_anchor=(0.5, -0.05),
            ncol=3,
            frameon=False,
            fontsize=9
        )
        
        ax_pie.set_title('Spending by Category', 
                        fontsize=13, weight='bold', pad=15)
        
        # Footer
        fig.text(0.5, 0.03, 'Expense Tracker - Your Financial Insights',
                ha='center', fontsize=9, style='italic', color='#999999')
        
        pdf.savefig(fig, bbox_inches='tight')
        plt.close()
        
        # ====================================================================
        # PAGE 2: BAR CHART + TABLE (Portrait - same as page 1)
        # ====================================================================
        fig = plt.figure(figsize=(8.5, 11))  # Portrait orientation
        fig.patch.set_facecolor('white')
        
        # Page title
        fig.text(0.5, 0.96, 'CATEGORY BREAKDOWN', 
                ha='center', fontsize=18, weight='bold')
        
        # Horizontal line
        line2 = Rectangle((0.1, 0.945), 0.8, 0.002,
                         transform=fig.transFigure, color='#CCCCCC')
        fig.patches.append(line2)
        
        # Bar Chart - Better positioned
        ax_bar = fig.add_axes([0.2, 0.65, 0.7, 0.25])
        
        top_categories = category_summary.head(10)  # Show top 10
        colors_bar = [CATEGORY_COLORS.get(cat, '#CCCCCC') for cat in top_categories['Category']]
        
        bars = ax_bar.barh(range(len(top_categories)), top_categories['Total'], 
                          color=colors_bar, height=0.7)
        
        # Set y-axis labels
        ax_bar.set_yticks(range(len(top_categories)))
        ax_bar.set_yticklabels(top_categories['Category'], fontsize=10)
        ax_bar.invert_yaxis()  # Highest at top
        
        ax_bar.set_xlabel('Amount (₹)', fontsize=11, weight='bold')
        ax_bar.set_title('Top Spending Categories', fontsize=13, weight='bold', pad=15)
        ax_bar.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        ax_bar.spines['top'].set_visible(False)
        ax_bar.spines['right'].set_visible(False)
        
        # Add value labels on bars
        for i, (bar, value) in enumerate(zip(bars, top_categories['Total'])):
            width = bar.get_width()
            ax_bar.text(width + max(top_categories['Total'])*0.01, 
                       i,
                       f'₹{value:,.0f}',
                       ha='left', va='center', fontsize=9, weight='bold')
        
        # Category Breakdown Table - Well spaced
        table_y = 0.58
        fig.text(0.5, table_y, 'Detailed Breakdown', 
                fontsize=12, weight='bold', ha='center')
        
        # Table with proper alignment
        col_headers = ['Category', 'Amount', 'Count', 'Percentage']
        col_x = [0.15, 0.45, 0.65, 0.78]
        col_align = ['left', 'right', 'center', 'center']
        
        header_y = table_y - 0.04
        
        # Header background
        header_box = Rectangle((0.12, header_y - 0.008), 0.76, 0.025,
                              transform=fig.transFigure,
                              facecolor='#E8E8E8', edgecolor='#999999', linewidth=0.5)
        fig.patches.append(header_box)
        
        # Headers
        for i, (header, x_pos, align) in enumerate(zip(col_headers, col_x, col_align)):
            fig.text(x_pos, header_y, header, fontsize=10, weight='bold', ha=align)
        
        # Table rows with alternating colors
        row_y = header_y - 0.035
        for idx, row in category_summary.iterrows():
            if row_y < 0.12:  # Stop if running out of space
                break
            
            # Alternating row background
            if idx % 2 == 0:
                row_box = Rectangle((0.12, row_y - 0.008), 0.76, 0.025,
                                   transform=fig.transFigure,
                                   facecolor='#F9F9F9', edgecolor='none')
                fig.patches.append(row_box)
            
            # Row data
            fig.text(col_x[0], row_y, row['Category'], fontsize=9, ha='left')
            fig.text(col_x[1], row_y, f"₹{row['Total']:,.2f}", fontsize=9, ha='right')
            fig.text(col_x[2], row_y, f"{row['Count']}", fontsize=9, ha='center')
            fig.text(col_x[3], row_y, f"{row['Percentage']}%", fontsize=9, ha='center')
            
            row_y -= 0.03
        
        # Total row with bold border
        total_box = Rectangle((0.12, row_y - 0.008), 0.76, 0.025,
                             transform=fig.transFigure,
                             facecolor='#E8F5E9', edgecolor='#4CAF50', linewidth=1)
        fig.patches.append(total_box)
        
        fig.text(col_x[0], row_y, 'TOTAL', fontsize=10, weight='bold', ha='left')
        fig.text(col_x[1], row_y, f"₹{total_spent:,.2f}", fontsize=10, weight='bold', ha='right')
        fig.text(col_x[2], row_y, f"{total_transactions}", fontsize=10, weight='bold', ha='center')
        fig.text(col_x[3], row_y, "100%", fontsize=10, weight='bold', ha='center')
        
        # Footer
        fig.text(0.5, 0.03, 'Expense Tracker - Your Financial Insights',
                ha='center', fontsize=9, style='italic', color='#999999')
        
        pdf.savefig(fig, bbox_inches='tight')
        plt.close()
    
    pdf_buffer.seek(0)
    return pdf_buffer


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


# ============================================================================
# STREAMLIT PAGE CONFIGURATION
# ============================================================================

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
# STREAMLIT PAGE CONFIGURATION (ACTUAL)
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
        st.subheader("💾 Download Your Report")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**📊 Detailed Data (Excel)**")
            st.write("All transactions with categories")
            
            # Create Excel file in memory
            output = BytesIO()
            df.to_excel(output, index=False, engine='openpyxl')
            excel_data = output.getvalue()
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_filename = f"expenses_{timestamp}.xlsx"
            
            # Download button for Excel
            st.download_button(
                label="📥 Download Excel",
                data=excel_data,
                file_name=excel_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        
        with col2:
            st.markdown("**📄 Summary Report (PDF)**")
            st.write("Charts and category breakdown")
            
            # Generate PDF filename
            pdf_filename = f"expense_report_{timestamp}.pdf"
            
            # Generate PDF button
            if st.button("🔄 Generate PDF", use_container_width=True, type="secondary"):
                with st.spinner("Creating PDF report..."):
                    try:
                        pdf_data = generate_pdf_report(df, category_summary)
                        st.success("✅ PDF ready!")
                        
                        # Store in session state for download
                        st.session_state.pdf_data = pdf_data.getvalue()
                        st.session_state.pdf_filename = pdf_filename
                    except Exception as e:
                        st.error(f"❌ Error generating PDF: {str(e)}")
            
            # Download button (only shows after PDF is generated)
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
