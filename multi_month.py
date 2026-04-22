"""
MULTI-MONTH ANALYSIS MODULE
============================
This module adds the Monthly Analysis tab to the expense tracker.
It is self-contained — delete this file to remove the tab entirely.

What it does:
- Takes the already-parsed expense DataFrame (from app.py)
- Groups transactions by month
- Builds a category x month comparison table
- Flags any category that spikes 30%+ above its own average
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


# ── Colour palette (matches app.py CATEGORY_COLORS) ─────────────────────────
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
    'Uncategorized': '#607D8B',
    'Recharge': '#FF5722',
    'Subscriptions': '#3F51B5',
    'Transfers': '#795548',
}


def get_sorted_months(df):
    """
    Return month labels in chronological order.
    Example output: ['Jan 2026', 'Feb 2026', 'Mar 2026']
    """
    df = df.copy()
    df['_period'] = df['Date'].dt.to_period('M')
    df['_label'] = df['Date'].dt.strftime('%b %Y')
    mapping = df[['_period', '_label']].drop_duplicates().sort_values('_period')
    return mapping['_label'].tolist()


def build_monthly_totals(df, months):
    """
    Calculate total spending per month.
    Returns a Series: index = month label, value = total amount.
    """
    df = df.copy()
    df['Month'] = df['Date'].dt.strftime('%b %Y')
    totals = df.groupby('Month')['Amount'].sum()
    return totals.reindex(months, fill_value=0)


def build_pivot_table(df, months):
    """
    Build a Category × Month comparison table.
    Rows = spending categories, Columns = months, Values = total spent.
    A 'Total' column is appended and rows are sorted by total descending.
    """
    df = df.copy()
    df['Month'] = df['Date'].dt.strftime('%b %Y')

    pivot = df.pivot_table(
        index='Category',
        columns='Month',
        values='Amount',
        aggfunc='sum',
        fill_value=0
    )
    # Ensure columns are in chronological order
    pivot = pivot.reindex(columns=months, fill_value=0)
    pivot['Total'] = pivot[months].sum(axis=1)
    pivot = pivot.sort_values('Total', ascending=False)
    return pivot


def get_attention_flags(pivot, months, threshold=0.30):
    """
    Find categories where any single month is MORE than threshold% above
    that category's average across all months.

    Example: Food average = ₹1,700. March Food = ₹2,904 (+70%) → flagged.

    threshold=0.30 means 30% above average triggers a flag.
    Returns a list of dicts with keys: Category, Month, Amount, Avg, PctAbove.
    """
    flags = []
    for category in pivot.index:
        monthly_values = pivot.loc[category, months]
        avg = monthly_values.mean()
        if avg == 0:
            continue
        for month in months:
            val = pivot.loc[category, month]
            if val > avg * (1 + threshold):
                pct = int(((val - avg) / avg) * 100)
                flags.append({
                    'Category': category,
                    'Month': month,
                    'Amount': val,
                    'Avg': round(avg, 0),
                    'PctAbove': pct
                })
    # Sort by most severe first
    flags.sort(key=lambda x: x['PctAbove'], reverse=True)
    return flags


def render_monthly_analysis_tab(df):
    """
    Main entry point — called from app.py to render the Monthly Analysis tab.
    Expects df with columns: Date, Particulars, Transaction Type, Category, Amount.
    """
    st.header("Monthly Analysis")

    # Guard: need at least 2 months to do a comparison
    months = get_sorted_months(df)
    if len(months) < 2:
        st.info("Upload a file with at least 2 months of data to see monthly comparison.")
        return

    # ── Section 1: Monthly totals bar chart ──────────────────────────────────
    st.subheader("Total spending by month")

    monthly_totals = build_monthly_totals(df, months)

    fig_bar = px.bar(
        x=monthly_totals.index,
        y=monthly_totals.values,
        labels={'x': 'Month', 'y': 'Amount (₹)'},
        color=monthly_totals.index,
        color_discrete_sequence=['#2196F3', '#4CAF50', '#FF9800', '#E91E63',
                                  '#9C27B0', '#00BCD4', '#F44336', '#795548',
                                  '#3F51B5', '#FF5722', '#607D8B', '#8BC34A'],
        text=monthly_totals.values
    )
    fig_bar.update_traces(
        texttemplate='₹%{text:,.0f}',
        textposition='outside'
    )
    fig_bar.update_layout(
        showlegend=False,
        height=350,
        margin=dict(t=30, b=20, l=20, r=20),
        yaxis_title="Amount (₹)",
        xaxis_title=""
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("---")

    # ── Section 2: Category × Month comparison table ─────────────────────────
    st.subheader("Category breakdown — month by month")
    st.caption("Rows = spending categories · Columns = months · Values = ₹ spent")

    pivot = build_pivot_table(df, months)

    # Format for display: add ₹ symbol, keep Total column
    display_pivot = pivot.copy()
    for col in months + ['Total']:
        display_pivot[col] = display_pivot[col].apply(
            lambda x: f"₹{x:,.0f}" if x > 0 else "—"
        )
    display_pivot.index.name = 'Category'
    st.dataframe(display_pivot, use_container_width=True)

    st.markdown("---")

    # ── Section 3: Attention flags ────────────────────────────────────────────
    st.subheader("Attention needed")
    st.caption("Categories where spending in any month is 30%+ above that category's average")

    flags = get_attention_flags(pivot, months, threshold=0.30)

    if not flags:
        st.success("✅ No unusual spikes detected — spending is consistent across months.")
    else:
        # Show flags as cards in a 2-column grid
        cols = st.columns(2)
        for i, flag in enumerate(flags):
            with cols[i % 2]:
                # Colour the card border based on severity
                if flag['PctAbove'] >= 80:
                    border_color = '#F44336'   # red — severe
                    emoji = '🔴'
                elif flag['PctAbove'] >= 50:
                    border_color = '#FF9800'   # orange — moderate
                    emoji = '🟠'
                else:
                    border_color = '#FFC107'   # yellow — mild
                    emoji = '🟡'

                st.markdown(
                    f"""
                    <div style="border-left: 4px solid {border_color};
                                padding: 12px 16px;
                                margin-bottom: 12px;
                                border-radius: 0 8px 8px 0;
                                background: var(--background-color, #fafafa)">
                        <div style="font-weight: 600; font-size: 15px;">
                            {emoji} {flag['Category']} — {flag['Month']}
                        </div>
                        <div style="font-size: 14px; margin-top: 4px;">
                            Spent <b>₹{flag['Amount']:,.0f}</b>
                            vs average ₹{flag['Avg']:,.0f}
                            &nbsp;
                            <span style="color:{border_color}; font-weight:600;">
                                +{flag['PctAbove']}%
                            </span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
