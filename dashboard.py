import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import gspread
import numpy as np                  
import plotly.graph_objects as go   
import os

# ==========================================
# 1. PAGE SETUP & SECURITY
# ==========================================
st.set_page_config(page_title="Dividend Tracker", layout="wide", page_icon="📈")

col_title, col_btn = st.columns([4, 1])
with col_title:
    st.title("My Dividend Portfolio Dashboard")
with col_btn:
    st.write("") # Spacing for alignment
    if st.button("🔄 Force Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.markdown("### Tracking progress toward the $3,000 - $4,500 CAD monthly passive income goal.")
st.divider()

# --- CSS OVERRIDE: AGGRESSIVE TAB FONT SCALING ---
st.markdown("""
<style>
    /* Force Streamlit tabs to adopt a massive, bold h3-style font */
    div[data-testid="stTabs"] button {
        font-size: 22px !important;
        font-weight: 600 !important;
    }
    div[data-testid="stTabs"] button p,
    div[data-testid="stTabs"] button span {
        font-size: 22px !important;
        font-weight: 600 !important;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# 3. ETF TRANSLATION DICTIONARY
# ==========================================
ETF_MAPPING = {
    "VUN.TO": {"Sector": "Broad Market ETF", "Country": "United States", "Factor": "Total Market Blend", "Asset_Type": "Equity"},
    "AVDV": {"Sector": "Broad Market ETF", "Country": "International Developed", "Factor": "Small-Cap Value", "Asset_Type": "Equity"},
    "AVUV": {"Sector": "Broad Market ETF", "Country": "United States", "Factor": "Small-Cap Value", "Asset_Type": "Equity"},
    "FLBR": {"Sector": "Broad Market ETF", "Country": "Brazil", "Factor": "Market-Cap Blend", "Asset_Type": "Equity"},
    "VFV.TO": {"Sector": "Broad Market ETF", "Country": "United States", "Factor": "Large-Cap Blend", "Asset_Type": "Equity"},
    "VTI": {"Sector": "Broad Market ETF", "Country": "United States", "Factor": "Total Market Blend", "Asset_Type": "Equity"},
    "XEC.TO": {"Sector": "Broad Market ETF", "Country": "Emerging Markets", "Factor": "Market-Cap Blend", "Asset_Type": "Equity"},
    "XEF.TO": {"Sector": "Broad Market ETF", "Country": "International Developed", "Factor": "Market-Cap Blend", "Asset_Type": "Equity"},
    "XEI.TO": {"Sector": "Dividend ETF", "Country": "Canada", "Factor": "High Yield", "Asset_Type": "Equity"},
    "XIC.TO": {"Sector": "Broad Market ETF", "Country": "Canada", "Factor": "Total Market Blend", "Asset_Type": "Equity"},
    "ZLB.TO": {"Sector": "Smart Beta ETF", "Country": "Canada", "Factor": "Low Volatility", "Asset_Type": "Equity"}
}

# ==========================================
# 4. DATA INGESTION: LEDGER & FUND DATA
# ==========================================
@st.cache_data(ttl=600)
def load_ledger_data():
    try:
        if os.path.exists("key.json"): gc = gspread.service_account(filename="key.json")
        else: gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])

        sheet = gc.open("PortfolioData").worksheet("Transactions")
        txn_data = sheet.get_all_records()
        if not txn_data: raise ValueError("The 'Transactions' tab is empty.")
        txn_df = pd.DataFrame(txn_data)
        
        fund_df = pd.DataFrame()
        try: 
            fund_sheet = gc.open("PortfolioData").worksheet("Fund_Data")
            # THE FIX: Raw value scraper. Immune to blank columns and Google Sheet formatting errors.
            raw_fund = fund_sheet.get_all_values()
            if len(raw_fund) > 1:
                fund_df = pd.DataFrame(raw_fund[1:], columns=raw_fund[0])
                fund_df.columns = fund_df.columns.astype(str).str.strip()
                fund_df = fund_df.loc[:, fund_df.columns != ''] # Drop phantom blank columns
                fund_df = fund_df.replace(r'^\s*$', np.nan, regex=True) # Force empty cells to NaN
        except Exception as e: 
            st.sidebar.error(f"Fund_Data Read Error: {e}")
            pass 
        
        positions = {}
        for index, row in txn_df.iterrows():
            action = str(row.get('Action', '')).strip().upper()
            ticker = str(row.get('Ticker', '')).strip().upper()
            
            if action in ['DEPOSIT', 'WITHDRAW'] or not ticker or ticker == 'NAN': 
                continue
                
            try: 
                shares = float(str(row.get('Shares', '0')).replace(',', ''))
                price = float(str(row.get('Price', '0')).replace(',', ''))
            except ValueError: 
                continue 
                
            if ticker not in positions: positions[ticker] = {'Shares': 0.0, 'Total_Cost': 0.0, 'Avg_Cost': 0.0}
            
            if action in ['BUY', 'DRIP']:
                positions[ticker]['Total_Cost'] += (shares * price)
                positions[ticker]['Shares'] += shares
                if positions[ticker]['Shares'] > 0: 
                    positions[ticker]['Avg_Cost'] = positions[ticker]['Total_Cost'] / positions[ticker]['Shares']
            elif action == 'SELL':
                positions[ticker]['Shares'] -= shares
                positions[ticker]['Total_Cost'] -= (shares * positions[ticker]['Avg_Cost'])
                if positions[ticker]['Shares'] <= 0.001: 
                    positions[ticker]['Shares'] = 0.0
                    positions[ticker]['Total_Cost'] = 0.0
                    positions[ticker]['Avg_Cost'] = 0.0
                    
        portfolio_list = [{'Ticker': t, 'Shares': d['Shares'], 'Avg_Cost': d['Avg_Cost']} for t, d in positions.items() if d['Shares'] > 0]
        return pd.DataFrame(portfolio_list), txn_df, fund_df

    except Exception as e:
        st.error(f"⚠️ Ledger Sync Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ==========================================
# 5. DATA INGESTION: LIVE API (YFINANCE)
# ==========================================
@st.cache_data(ttl=3600)
def fetch_live_data(tickers):
    try: usd_cad_rate = yf.Ticker("CAD=X").fast_info.get('lastPrice', 1.35)
    except Exception: usd_cad_rate = 1.35 
        
    live_data = []
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            price, info = stock.fast_info.get('lastPrice', 0.0), stock.info
            
            div_per_share, eps, ttm_div = info.get('dividendRate', 0.0) or 0.0, info.get('trailingEps', 0.0) or 0.0, info.get('trailingAnnualDividendRate', 0.0) or 0.0
            trailing_yield = info.get('trailingAnnualDividendYield', np.nan) 
            
            pe_ratio, payout_ratio, fcf = info.get('trailingPE', np.nan), info.get('payoutRatio', np.nan), info.get('freeCashflow', np.nan)
            raw_mcap, raw_aum = info.get('marketCap', np.nan), info.get('totalAssets', np.nan)
            mcap_b = raw_mcap / 1_000_000_000 if pd.notnull(raw_mcap) else np.nan
            aum_b = raw_aum / 1_000_000_000 if pd.notnull(raw_aum) else np.nan
            
            mer, beta, sec_yield = info.get('expenseRatio', np.nan), info.get('beta', info.get('beta3Year', np.nan)), info.get('yield', np.nan)
            currency, quote_type, sector_raw = info.get('currency', 'USD'), info.get('quoteType', ''), info.get('sector', 'Unknown')
            
            if ticker in ETF_MAPPING:
                sector, country, factor, asset_class, asset_type = ETF_MAPPING[ticker]["Sector"], ETF_MAPPING[ticker]["Country"], ETF_MAPPING[ticker]["Factor"], "ETF", "Equity"
            else:
                sector, country, factor = sector_raw, info.get('country', 'Unknown'), "Individual Equity"
                if quote_type == 'ETF' or 'ETF' in sector_raw: asset_class, asset_type = "ETF", "Equity"
                elif 'Real Estate' in sector_raw: asset_class, asset_type = "REIT", "Alternatives / Real Estate"
                else: asset_class, asset_type = "Stock", "Equity"
            
            if asset_class == "ETF" and "REIT" in factor.upper(): asset_class = "REIT"
            display_ticker = f"🔴 {ticker}" if asset_class == "REIT" else f"🟢 {ticker}" if asset_class == "ETF" else f"🔵 {ticker}"
            
            if currency == 'USD':
                price_cad, div_cad, eps_cad, ttm_div_cad = price * usd_cad_rate, div_per_share * usd_cad_rate, eps * usd_cad_rate, ttm_div * usd_cad_rate
                fcf_cad = (fcf * usd_cad_rate) / 1_000_000_000 if pd.notnull(fcf) else np.nan
                exchange_multiplier, note = usd_cad_rate, f"Converted ({usd_cad_rate:.3f})"
            else:
                price_cad, div_cad, eps_cad, ttm_div_cad = price, div_per_share, eps, ttm_div
                fcf_cad = fcf / 1_000_000_000 if pd.notnull(fcf) else np.nan
                exchange_multiplier, note = 1.0, "Native CAD"
                
            live_data.append({
                "Ticker": ticker, "Display Ticker": display_ticker, "Live Price (CAD)": price_cad, "Div Per Share (CAD)": div_cad,
                "Trailing Yield": trailing_yield, "EPS (CAD)": eps_cad, "TTM Div (CAD)": ttm_div_cad, "Exchange Multiplier": exchange_multiplier, 
                "Currency Note": note, "Asset Class": asset_class, "Asset_Type": asset_type, "Sector": sector, "Country": country, "Factor": factor,
                "P/E Ratio": pe_ratio, "Payout Ratio": payout_ratio, "FCF (B)": fcf_cad, "M-Cap (B)": mcap_b,
                "MER": mer, "AUM (B)": aum_b, "Beta": beta, "SEC Yield": sec_yield
            })
        except Exception: pass
    return pd.DataFrame(live_data)

# ==========================================
# 6. DATA INGESTION: HISTORICAL & CAGR
# ==========================================
@st.cache_data(ttl=3600)
def get_historical_data(tickers):
    all_data = {}
    for t in tickers:
        try:
            df_hist = yf.download(t, period="20y", interval="1mo", auto_adjust=True)['Close']
            if isinstance(df_hist, pd.Series) and not df_hist.empty: all_data[t] = df_hist
            elif isinstance(df_hist, pd.DataFrame) and not df_hist.empty: all_data[t] = df_hist.squeeze()
        except Exception: pass
    if not all_data: return pd.DataFrame()
    return pd.concat(all_data, axis=1).dropna(how='all')

def calculate_cagrs(hist_df, tickers):
    cagr_data = []
    periods = { '1Y CAGR': 12, '3Y CAGR': 36, '5Y CAGR': 60, '10Y CAGR': 120, '15Y CAGR': 180 }
    for t in tickers:
        if t not in hist_df.columns: continue
        series = hist_df[t].dropna()
        if series.empty: continue
        current_price = series.iloc[-1]
        ticker_cagrs = {"Ticker": t}
        for label, months in periods.items():
            if len(series) > months:
                past_price = series.iloc[-months-1]
                if past_price > 0:
                    years = months / 12
                    cagr = ((current_price / past_price) ** (1 / years)) - 1
                    ticker_cagrs[label] = f"{cagr * 100:.2f}%"
                else: ticker_cagrs[label] = "N/A"
            else: ticker_cagrs[label] = "N/A"
        cagr_data.append(ticker_cagrs)
    return pd.DataFrame(cagr_data)

# ==========================================
# 7. MAIN DASHBOARD COMPOSITION
# ==========================================
def load_unified_dashboard():
    with st.spinner("Syncing transaction ledger from Google Sheets..."):
        df, txn_df, fund_df = load_ledger_data() 
        
    if df.empty:
        st.warning("No active portfolio positions found.")
        return

    # --- DYNAMIC AVERAGE CONTRIBUTION ENGINE (YTD FIX) ---
    calculated_avg_contrib = 1000
    if not txn_df.empty:
        try:
            date_col = next((col for col in txn_df.columns if 'date' in col.lower()), None)
            txn_df['Clean_Action'] = txn_df.get('Action', '').astype(str).str.upper().str.strip()
            if 'Total Net Amount' in txn_df.columns:
                txn_df['Clean_Net_Amount'] = pd.to_numeric(txn_df['Total Net Amount'].astype(str).str.replace(r'[$, ]', '', regex=True), errors='coerce').fillna(0.0)
            else:
                txn_df['Clean_Net_Amount'] = 0.0

            if date_col:
                txn_df['Parsed_Date'] = pd.to_datetime(txn_df[date_col], errors='coerce')
                today = pd.Timestamp.today()
                ytd_df = txn_df[txn_df['Parsed_Date'].dt.year == today.year]
                months_elapsed = max(1, today.month) 
                total_ytd_deposits = ytd_df[ytd_df['Clean_Action'] == 'DEPOSIT']['Clean_Net_Amount'].sum()
                
                if total_ytd_deposits > 0:
                    calculated_avg_contrib = int(total_ytd_deposits / months_elapsed)
        except Exception:
            pass

    calculated_avg_contrib = int(round(calculated_avg_contrib / 100.0) * 100)
    calculated_avg_contrib = max(100, calculated_avg_contrib) 
    slider_max = calculated_avg_contrib * 2

    # ==========================================
    # 2. SIDEBAR: SIMULATION CONTROLS
    # ==========================================
    st.sidebar.header("⚙️ Simulation Parameters")
    st.sidebar.markdown("Adjust these variables to forecast your 12-Year Projection.")
    
    sim_avg_contribution = st.sidebar.slider("Average Monthly Contribution (CAD)", min_value=0, max_value=int(slider_max), value=int(calculated_avg_contrib), step=100)
    sim_proposed_contribution = st.sidebar.slider("Proposed Monthly Contribution (CAD)", min_value=0, max_value=10000, value=int(sim_avg_contribution), step=100)
    
    sim_capital_growth = st.sidebar.slider("Expected Capital Growth (%)", min_value=0.0, max_value=15.0, value=5.0, step=0.5)
    sim_div_yield = st.sidebar.slider("Target Dividend Yield (%)", min_value=0.0, max_value=10.0, value=4.0, step=0.1)
    sim_div_growth = st.sidebar.slider("Dividend Growth Rate (%)", min_value=0.0, max_value=15.0, value=5.0, step=0.1)
    sim_inflation = st.sidebar.slider("Canadian Inflation Rate (%)", min_value=0.0, max_value=10.0, value=2.0, step=0.1)
    sim_drip = st.sidebar.checkbox("Enable Dividend Reinvestment (DRIP)", value=True)

        
    tickers = df['Ticker'].unique().tolist()
    live_df = fetch_live_data(tickers)
    merged_df = pd.merge(df, live_df, on="Ticker", how="left")
    
    # --- API SILENT FAILURE SAFETY NET ---
    merged_df['Display Ticker'] = merged_df['Display Ticker'].fillna("⚠️ " + merged_df['Ticker'])
    merged_df['Asset Class'] = merged_df['Asset Class'].fillna("Stock") 
    merged_df['Exchange Multiplier'] = merged_df['Exchange Multiplier'].fillna(1.0)
    for col in ['Live Price (CAD)', 'Div Per Share (CAD)', 'Trailing Yield', 'EPS (CAD)', 'TTM Div (CAD)']:
        if col in merged_df.columns:
            merged_df[col] = merged_df[col].fillna(0.0)
    
    if not fund_df.empty and 'Ticker' in fund_df.columns:
        # Strip invisible spaces from the ticker column in Google Sheets
        fund_df['Ticker'] = fund_df['Ticker'].astype(str).str.upper().str.strip()
        
        # Ensure fund_df has unique tickers to prevent row multiplication during merge
        fund_df_unique = fund_df.drop_duplicates(subset=['Ticker'], keep='last')
        
        if 'MER' in fund_df_unique.columns:
            merged_df = pd.merge(merged_df, fund_df_unique[['Ticker', 'MER']].rename(columns={'MER': 'Manual_MER'}), on="Ticker", how="left")
            merged_df['MER'] = np.where(merged_df['Manual_MER'].notnull(), merged_df['Manual_MER'], merged_df['MER'])
        if 'Yield' in fund_df_unique.columns:
            merged_df = pd.merge(merged_df, fund_df_unique[['Ticker', 'Yield']].rename(columns={'Yield': 'Manual_Yield'}), on="Ticker", how="left")
            merged_df['Trailing Yield'] = np.where(merged_df['Manual_Yield'].notnull(), merged_df['Manual_Yield'], merged_df['Trailing Yield'])
            
        if 'Div_Frequency' in fund_df_unique.columns:
            merged_df = pd.merge(merged_df, fund_df_unique[['Ticker', 'Div_Frequency']], on="Ticker", how="left")
            
        if 'Payout_Months' in fund_df_unique.columns:
            merged_df = pd.merge(merged_df, fund_df_unique[['Ticker', 'Payout_Months']], on="Ticker", how="left")
            
        # USER OVERRIDE ENGINE: Bulletproof masking against invisible spaces and empty Pandas strings
        if 'Sector' in fund_df_unique.columns:
            merged_df = pd.merge(merged_df, fund_df_unique[['Ticker', 'Sector']].rename(columns={'Sector': 'Manual_Sector'}), on="Ticker", how="left")
            invalid_mask = merged_df['Manual_Sector'].astype(str).str.strip().isin(['', 'nan', 'None', 'NaN', '<NA>'])
            merged_df['Sector'] = np.where(invalid_mask, merged_df['Sector'], merged_df['Manual_Sector'].astype(str).str.strip())
            
        if 'Country' in fund_df_unique.columns:
            merged_df = pd.merge(merged_df, fund_df_unique[['Ticker', 'Country']].rename(columns={'Country': 'Manual_Country'}), on="Ticker", how="left")
            invalid_mask = merged_df['Manual_Country'].astype(str).str.strip().isin(['', 'nan', 'None', 'NaN', '<NA>'])
            merged_df['Country'] = np.where(invalid_mask, merged_df['Country'], merged_df['Manual_Country'].astype(str).str.strip())
            
        if 'Factor' in fund_df_unique.columns:
            merged_df = pd.merge(merged_df, fund_df_unique[['Ticker', 'Factor']].rename(columns={'Factor': 'Manual_Factor'}), on="Ticker", how="left")
            invalid_mask = merged_df['Manual_Factor'].astype(str).str.strip().isin(['', 'nan', 'None', 'NaN', '<NA>'])
            merged_df['Factor'] = np.where(invalid_mask, merged_df['Factor'], merged_df['Manual_Factor'].astype(str).str.strip())
    
    merged_df['Avg Cost (CAD)'] = merged_df['Avg_Cost'] * merged_df['Exchange Multiplier']
    merged_df['Total Cost (CAD)'] = merged_df['Shares'] * merged_df['Avg Cost (CAD)']
    merged_df['Market Value (CAD)'] = merged_df['Shares'] * merged_df['Live Price (CAD)']
    merged_df['Total Unrealized Gain (CAD)'] = merged_df['Market Value (CAD)'] - merged_df['Total Cost (CAD)']
    
    # Force data types to pure numeric to prevent string multiplication errors
    clean_yield = pd.to_numeric(merged_df['Trailing Yield'].astype(str).str.replace('%', '', regex=False), errors='coerce').fillna(0)
    clean_div = pd.to_numeric(merged_df['Div Per Share (CAD)'], errors='coerce').fillna(0)
    
    # Auto-adjust yield if it was written as a whole percentage (e.g. 4.5 instead of 0.045)
    clean_yield = np.where(clean_yield > 1, clean_yield / 100, clean_yield)

    merged_df['Annual Dividend (CAD)'] = np.where(
        merged_df['Asset Class'] == 'ETF',
        merged_df['Market Value (CAD)'] * clean_yield,
        merged_df['Shares'] * clean_div
    )
    
    # ==========================================
    # CASH FLOW FREQUENCY ENGINE
    # ==========================================
    freq_divisors = {
        'Monthly': 12, 'Mensal': 12, 
        'Trimester': 4, 'Quarterly': 4, 'Trimestral': 4, 
        'Semester': 2, 'Semi-Annual': 2, 'Semestral': 2, 
        'Annual': 1, 'Anual': 1
    }
    
    if 'Div_Frequency' not in merged_df.columns:
        merged_df['Div_Frequency'] = 'Trimester'
    else:
        merged_df['Div_Frequency'] = merged_df['Div_Frequency'].fillna('Trimester')
        
    merged_df['Payouts_Per_Year'] = merged_df['Div_Frequency'].str.strip().str.title().map(freq_divisors).fillna(4.0)
    merged_df['Cash Per Payout (CAD)'] = merged_df['Annual Dividend (CAD)'] / merged_df['Payouts_Per_Year']
    
    total_cost = merged_df['Total Cost (CAD)'].sum()
    total_market_value = merged_df['Market Value (CAD)'].sum()
    total_unrealized_gain = total_market_value - total_cost
    total_annual_div = merged_df['Annual Dividend (CAD)'].sum()
    monthly_div = total_annual_div / 12

    if not txn_df.empty and 'Total Net Amount' in txn_df.columns:
        cash_in = txn_df[txn_df['Clean_Action'].isin(['DEPOSIT', 'SELL'])]['Clean_Net_Amount'].sum()
        cash_out = txn_df[txn_df['Clean_Action'].isin(['WITHDRAW', 'BUY'])]['Clean_Net_Amount'].sum()
        available_cash = cash_in - cash_out
    else:
        available_cash = 0.0

    total_portfolio_value = total_market_value + available_cash

    tabs = st.tabs([
        "🏠 Dashboard", 
        "🧩 Diversification", 
        "🎯 Gap Analysis", 
        "📈 12-Year Projection", 
        "🏗️ Asset Allocation", 
        "🔬 Advance Analytics", 
        "📝 Transaction Ledger", 
        "🎲 Monte Carlo Simulation", 
        "🕵️ Performance Audit (IRR)"
    ])

    # --- TAB 1: DASHBOARD ---
    with tabs[0]:
        with st.expander("🔍 Audit Raw Data"):
            st.write("**1. Raw Google Sheets Ledger Data:**"); st.dataframe(txn_df, use_container_width=True)
            st.write("**2. Calculated Current Holdings:**"); st.dataframe(df, use_container_width=True)
            st.write("**3. Raw Yahoo Finance API Data:**"); st.dataframe(live_df, use_container_width=True)

        gain_color = "#2ca02c" if total_unrealized_gain >= 0 else "#ff6666"
        gain_sign = "+" if total_unrealized_gain >= 0 else "-"
        st.markdown(f"### Market Data & Valuation &nbsp;&nbsp;|&nbsp;&nbsp; <span style='color:{gain_color};'>Unrealized Gain: {gain_sign}${abs(total_unrealized_gain):,.2f}</span>", unsafe_allow_html=True)
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Available Cash", f"${available_cash:,.2f}")
        col2.metric("Total Invested", f"${total_cost:,.2f}")
        col3.metric("Market Value", f"${total_market_value:,.2f}", f"${total_unrealized_gain:,.2f}")
        col4.metric("Total Portfolio Value", f"${total_portfolio_value:,.2f}")
        col5.metric("Est. Monthly Div", f"${monthly_div:,.2f}")
        st.divider()

        st.markdown("#### **🗓️ The 12-Month Dividend Calendar**")
        st.markdown("Actual expected cash flow per month based on your declared asset payout schedules.")
        
        month_names = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun', 7:'Jul', 8:'Aug', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dec'}
        cal_data = []

        if 'Payout_Months' not in merged_df.columns:
            st.warning("⚠️ Waiting for Payout_Months data to sync from Google Sheets...")
            merged_df['Payout_Months'] = 'ALL' 
            
        # Determine Top 5 Dividend Payers
        top_payers = merged_df.groupby('Display Ticker')['Annual Dividend (CAD)'].sum().nlargest(5).index.tolist()
            
        for _, row in merged_df.iterrows():
            raw_ticker = row['Display Ticker']
            # Group smaller assets into "Others"
            ticker = raw_ticker if raw_ticker in top_payers else "Others"
            
            payout_str = str(row['Payout_Months']).strip().upper()
            cash_per_payout = row.get('Cash Per Payout (CAD)', 0.0)
            
            if pd.isna(cash_per_payout) or cash_per_payout <= 0 or payout_str == 'NA' or payout_str == 'NAN':
                continue
                
            months_to_pay = []
            if payout_str == 'ALL':
                months_to_pay = list(range(1, 13))
            else:
                try:
                    months_to_pay = [int(m.strip()) for m in payout_str.split(',') if m.strip().isdigit()]
                except Exception:
                    pass
                    
            for m in months_to_pay:
                if 1 <= m <= 12:
                    cal_data.append({
                        "Month_Num": m,
                        "Month": month_names[m],
                        "Ticker": ticker,
                        "Income (CAD)": cash_per_payout
                    })
                    
        if cal_data:
            cal_df = pd.DataFrame(cal_data)
            # Aggregate to merge all 'Others' into a single clean block per month
            cal_df = cal_df.groupby(['Month_Num', 'Month', 'Ticker'])['Income (CAD)'].sum().reset_index()
            
            total_per_month = cal_df.groupby("Month_Num")["Income (CAD)"].sum().reset_index()
            total_per_month["Month"] = total_per_month["Month_Num"].map(month_names)
            
            fig_cal = px.bar(
                cal_df.sort_values(['Month_Num', 'Ticker']), 
                x="Month", y="Income (CAD)", color="Ticker",
                labels={"Income (CAD)": "Cash Flow (CAD)", "Month": ""},
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            
            for _, r in total_per_month.iterrows():
                fig_cal.add_annotation(
                    x=r["Month"], y=r["Income (CAD)"],
                    text=f"<b>${r['Income (CAD)']:,.0f}</b>",
                    showarrow=False, yshift=15,
                    font=dict(size=14, color="#54A87A")
                )
            
            fig_cal.update_layout(
                margin=dict(t=40, b=10, l=10, r=10), 
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                legend=dict(title="Top Payers", orientation="v", yanchor="top", y=1, xanchor="left", x=1.02, font=dict(size=12)),
                xaxis=dict(categoryorder='array', categoryarray=list(month_names.values()), tickfont=dict(size=14, weight="bold")),
                yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)', tickformat="$,.0f"),
                hovermode="closest", height=500
            )
            st.plotly_chart(fig_cal, use_container_width=True)

        else:
            st.info("🗓️ Calendar Engine is waiting for 'Payout_Months' data to be populated in Google Sheets.")
            
        st.divider()

        col_a, col_b = st.columns([1, 4])
        with col_a: hide_total = st.checkbox("Hide TOTAL Row", value=False)
        st.markdown("**Asset Legend:** &nbsp; 🔵 Stock / ADR &nbsp;|&nbsp; 🟢 ETF &nbsp;|&nbsp; 🔴 REIT")

        hist_df = get_historical_data(tickers)
        cagr_df = calculate_cagrs(hist_df, tickers)
        if not cagr_df.empty: merged_df = pd.merge(merged_df, cagr_df, on="Ticker", how="left")
        
        merged_df['Yield on Cost (%)'] = np.where(merged_df['Total Cost (CAD)'] > 0, (merged_df['Annual Dividend (CAD)'] / merged_df['Total Cost (CAD)']) * 100, 0.0)
        merged_df['Weight (%)'] = (merged_df['Market Value (CAD)'] / total_market_value) * 100

        def render_table(title, df_slice):
            if df_slice.empty: return 
            st.subheader(title)
            
            df_slice = df_slice.sort_values(by='Ticker', ascending=True)
            base_c = ['Display Ticker', 'Shares', 'Avg_Cost', 'Live Price (CAD)', 'Market Value (CAD)', 'Weight (%)', 'Total Unrealized Gain (CAD)', 'Yield on Cost (%)', 'Annual Dividend (CAD)', 'EPS (CAD)', 'TTM Div (CAD)', '1Y CAGR', '3Y CAGR', '5Y CAGR', '10Y CAGR', '15Y CAGR', 'Sector', 'Country', 'Factor', 'Currency Note']
            
            if title == "Stock Holdings": cols = base_c[:16] + ['P/E Ratio', 'Payout Ratio', 'FCF (B)', 'M-Cap (B)']
            elif title == "ETF Holdings": cols = ['Display Ticker', 'Shares', 'Avg_Cost', 'Live Price (CAD)', 'Market Value (CAD)', 'Weight (%)', 'Total Unrealized Gain (CAD)', 'Annual Dividend (CAD)', 'Trailing Yield', 'Beta', 'AUM (B)', 'MER', '1Y CAGR', '3Y CAGR', '5Y CAGR', '10Y CAGR', '15Y CAGR']
            elif title == "REITs Holdings": cols = base_c[:16] + ['M-Cap (B)']
            else: cols = base_c
                
            disp_df = df_slice[[c for c in cols if c in df_slice.columns]].copy()
            disp_df.rename(columns={'Display Ticker': 'Ticker'}, inplace=True)
            
            circles = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳"]
            disp_df.rename(columns={c: f"{circles[i]} {c}" for i, c in enumerate(disp_df.columns)}, inplace=True)
            disp_df.insert(0, 'Row', range(1, len(disp_df) + 1)); disp_df['Row'] = disp_df['Row'].astype(str)
            ticker_col_name = f"{circles[0]} Ticker" 
            
            if not hide_total:
                t_row = {c: np.nan for c in disp_df.columns}; t_row['Row'], t_row[ticker_col_name] = 'TOTAL', '---'
                for c in disp_df.columns:
                    if 'Shares' in c: t_row[c] = df_slice['Shares'].sum()
                    elif 'Market Value' in c: t_row[c] = df_slice['Market Value (CAD)'].sum()
                    elif 'Weight' in c: t_row[c] = df_slice['Weight (%)'].sum()
                    elif 'Gain' in c: t_row[c] = df_slice['Total Unrealized Gain (CAD)'].sum()
                    elif 'Annual Dividend' in c: t_row[c] = df_slice['Annual Dividend (CAD)'].sum()
                disp_df = pd.concat([disp_df, pd.DataFrame([t_row])], ignore_index=True)
            
            def fmt_pct(x, col):
                if pd.isna(x) or type(x) == str: return "" if pd.isna(x) else x
                if any(raw in col for raw in ['Payout', 'MER', 'SEC', 'Trailing Yield']): return f"{x * 100:.2f}%" 
                return f"{x:.2f}%" 

            def fmt_curr(x):
                if pd.isna(x) or type(x) == str: return "" if pd.isna(x) else x
                return f"$({abs(x):,.2f})" if x < 0 else f"${x:,.2f}"

            for c in disp_df.columns:
                if 'Shares' in c: disp_df[c] = disp_df[c].apply(lambda x: f"{x:,.1f}" if pd.notnull(x) and type(x) != str else ("" if pd.isna(x) else x))
                elif any(k in c for k in ['Yield', 'Weight', 'Payout', 'MER']): disp_df[c] = disp_df[c].apply(lambda x: fmt_pct(x, c))
                elif any(k in c for k in ['Cost', 'Price', 'Value', 'Gain', 'Dividend', 'EPS', 'TTM', 'FCF']): disp_df[c] = disp_df[c].apply(fmt_curr)
                elif any(k in c for k in ['P/E', 'M-Cap', 'AUM', 'Beta']): disp_df[c] = disp_df[c].apply(lambda x: f"{x:,.2f}" if pd.notnull(x) and type(x) != str else ("" if pd.isna(x) else x))
                else: disp_df[c] = disp_df[c].fillna("") 
                    
            disp_df.set_index(['Row', ticker_col_name], inplace=True)
            
            def style_cells(row):
                is_total = (row.name[0] == 'TOTAL'); t_val = str(row.name[1])
                color = 'background-color: rgba(255,0,0,0.1); color: #ff6666;' if '🔴' in t_val else 'background-color: rgba(0,128,0,0.15); color: #85e085;' if '🟢' in t_val else 'background-color: rgba(0,0,255,0.15); color: #85c2ff;' if '🔵' in t_val else ''
                return [f"{color if c == ticker_col_name else ''} font-weight: bold;" if (is_total or c == ticker_col_name) else "" for c in row.index]
            
            styled_df = disp_df.style.apply(style_cells, axis=1).set_table_styles([{'selector': 'th', 'props': [('font-weight', 'bold')]}])
            st.dataframe(styled_df, use_container_width=True)

        render_table("Unified Portfolio Holdings", merged_df)
        render_table("Stock Holdings", merged_df[merged_df['Asset Class'] == 'Stock'])
        render_table("ETF Holdings", merged_df[merged_df['Asset Class'] == 'ETF'])
        render_table("REITs Holdings", merged_df[merged_df['Asset Class'] == 'REIT'])

        # ==========================================
        # 💧 THE DRIP SNOWBALL TRACKER
        # ==========================================
        st.divider()
        st.markdown("### 💧 The DRIP Snowball Tracker")
        st.markdown("Visualizing the exact number of shares required to generate enough passive income to automatically buy full new shares per payout period.")
        
        drip_df = merged_df[merged_df['Div Per Share (CAD)'] > 0].copy()
        
        if not drip_df.empty:
            drip_df = drip_df[['Display Ticker', 'Live Price (CAD)', 'Div Per Share (CAD)', 'Shares', 'Div_Frequency', 'Payouts_Per_Year']].copy()
            
            drip_df['Display Ticker'] = drip_df['Display Ticker'].astype(str)
            drip_df.rename(columns={'Display Ticker': 'Ticker'}, inplace=True)
            drip_df.sort_values(by='Ticker', inplace=True)
            
            drip_df['Div Per Payout (Share)'] = drip_df['Div Per Share (CAD)'] / drip_df['Payouts_Per_Year']
            drip_df['Shares for 1 DRIP'] = drip_df['Live Price (CAD)'] / drip_df['Div Per Payout (Share)']
            drip_df['Shares for 1 DRIP'] = drip_df['Shares for 1 DRIP'].replace([np.inf, -np.inf], np.nan).fillna(0)
            
            drip_df['Current DRIPs'] = np.floor(drip_df['Shares'] / drip_df['Shares for 1 DRIP']).fillna(0)
            drip_df['Next Target'] = drip_df['Current DRIPs'] + 1
            drip_df['Gap to Next DRIP (Shares)'] = (drip_df['Next Target'] * drip_df['Shares for 1 DRIP']) - drip_df['Shares']
            
            max_drips = int(drip_df['Current DRIPs'].max()) + 1
            max_drips = max(3, max_drips) 
            
            for i in range(1, max_drips + 1):
                suffix = "th" if 11 <= i % 100 <= 13 else {1:"st", 2:"nd", 3:"rd"}.get(i % 10, "th")
                col_name = f"Target: {i}{suffix} DRIP"
                drip_df[col_name] = drip_df['Shares for 1 DRIP'] * i
            
            base_cols = ['Ticker', 'Shares', 'Div_Frequency', 'Current DRIPs', 'Gap to Next DRIP (Shares)']
            target_cols = [c for c in drip_df.columns if 'Target:' in c]
            drip_disp = drip_df[base_cols + target_cols]
            
            fmt_dict = {'Shares': '{:.2f}', 'Current DRIPs': '{:.0f}x', 'Gap to Next DRIP (Shares)': '{:.2f}'}
            for c in target_cols: fmt_dict[c] = '{:.2f}'
            
            st.dataframe(
                drip_disp.style
                .format(fmt_dict)
                .background_gradient(subset=['Gap to Next DRIP (Shares)'], cmap='Blues_r')
                .set_table_styles([{'selector': 'th', 'props': [('font-weight', 'bold')]}]), 
                use_container_width=True
            )
             
    # --- TAB 2: DIVERSIFICATION ---
    with tabs[1]:
        st.subheader("Portfolio Diversification Metrics")
        ac_df = merged_df.groupby("Asset Class")["Market Value (CAD)"].sum().reset_index()
        geo_df = merged_df.groupby("Country")["Market Value (CAD)"].sum().reset_index()
        sec_cap_df = merged_df.groupby("Sector")["Market Value (CAD)"].sum().reset_index()
        sec_inc_df = merged_df.groupby("Sector")["Annual Dividend (CAD)"].sum().reset_index()
        fac_df = merged_df.groupby("Factor")["Market Value (CAD)"].sum().reset_index()

        def render_chart_pair(title, data, name_col, val_col, y_axis_label, color_map=None):
            st.markdown(f"##### {title}")
            data_sorted = data.sort_values(by=val_col, ascending=False)
            
            c1, c2 = st.columns(2)
            with c1: 
                fig_pie = px.pie(data_sorted, values=val_col, names=name_col, hole=0.4, color=name_col if color_map else None, color_discrete_map=color_map)
                fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>" + y_axis_label + ": $%{value:,.0f}<br>Weight: %{percent}<extra></extra>")
                fig_pie.update_layout(margin=dict(t=10, b=10, l=10, r=10), font=dict(size=18), hoverlabel=dict(font_size=20), legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5, font=dict(size=16)))
                st.plotly_chart(fig_pie, use_container_width=True)
                
            with c2: 
                fig_bar = px.bar(data_sorted, x=name_col, y=val_col, color=name_col, color_discrete_map=color_map)
                fig_bar.update_traces(hovertemplate="<b>%{x}</b><br>" + y_axis_label + ": $%{y:,.0f}<extra></extra>")
                fig_bar.update_layout(margin=dict(t=10, b=10, l=10, r=10), xaxis_title="", yaxis_title="", showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(size=18), hoverlabel=dict(font_size=20))
                fig_bar.update_yaxes(showgrid=True, gridcolor='rgba(128,128,128,0.2)', tickformat="$,.0f")
                fig_bar.update_xaxes(showgrid=False)
                st.plotly_chart(fig_bar, use_container_width=True)
            st.divider()

        asset_colors = {"Stock": "#1f77b4", "ETF": "#2ca02c", "REIT": "#d62728"}
        render_chart_pair("1. Asset Class Exposure", ac_df, "Asset Class", "Market Value (CAD)", "Market Value", color_map=asset_colors)
        render_chart_pair("2. Geographic Exposure", geo_df, "Country", "Market Value (CAD)", "Market Value")
        render_chart_pair("3. Sector Exposure (Capital)", sec_cap_df, "Sector", "Market Value (CAD)", "Market Value")
        render_chart_pair("4. Sector Contribution (Income)", sec_inc_df, "Sector", "Annual Dividend (CAD)", "Annual Dividend")
        render_chart_pair("5. Factor Exposure", fac_df, "Factor", "Market Value (CAD)", "Market Value")    

    # --- TAB 3: GAP ANALYSIS ---
    with tabs[2]:
        st.subheader("The Gap Analysis Engine")
        st.markdown("Quantifying the exact distance between your current reality and your 2038 passive income goal.")
        
        base_target_income = 3000.00 
        years_to_goal = 12
        target_income_inflated = base_target_income * ((1 + (sim_inflation / 100)) ** years_to_goal)
        income_gap = target_income_inflated - monthly_div
        
        req_capital = (target_income_inflated * 12) / (sim_div_yield / 100) if sim_div_yield > 0 else 0
        capital_gap = req_capital - total_portfolio_value
        
        r = (sim_capital_growth + (sim_div_yield if sim_drip else 0)) / 100
        r_mo = r / 12
        n_months = years_to_goal * 12
        
        if r_mo > 0:
            fv_current = total_portfolio_value * ((1 + r_mo) ** n_months)
            req_fv_from_contribs = req_capital - fv_current
            required_monthly_contrib = req_fv_from_contribs / ((( (1 + r_mo) ** n_months) - 1) / r_mo) if req_fv_from_contribs > 0 else 0.0
        else:
            required_monthly_contrib = capital_gap / n_months if capital_gap > 0 else 0.0

        st.markdown("#### 1. The Reality vs. The Goal (12-Year Horizon)")
        c1, c2, c3 = st.columns(3)
        c1.metric("Current Monthly Income", f"${monthly_div:,.2f}")
        c2.metric("Target (Inflation-Adjusted)", f"${target_income_inflated:,.2f}", f"↑ Base: ${base_target_income:,.0f}", delta_color="normal")
        c3.metric("The Income Gap", f"${income_gap:,.2f}", f"↓ -${income_gap:,.2f}" if income_gap > 0 else "Target Reached", delta_color="inverse" if income_gap > 0 else "normal")
        
        st.divider()
        st.markdown("#### 2. The Capital Fix")
        c4, c5 = st.columns(2)
        c4.metric("Required Total Capital", f"${req_capital:,.2f}", "↑ To generate target income", delta_color="normal")
        c5.metric("Current Capital Gap", f"${capital_gap:,.2f}", f"↓ -${capital_gap:,.2f}" if capital_gap > 0 else "Funded", delta_color="inverse" if capital_gap > 0 else "normal")
        
        if required_monthly_contrib > 0:
            st.info(f"**THE FIX:** Based on your current portfolio value and sidebar assumptions (Yield: {sim_div_yield}%, Growth: {sim_capital_growth}%, Inflation: {sim_inflation}%), you must invest **${required_monthly_contrib:,.2f} per month** for the next {years_to_goal} years.")
        else:
            st.success("**THE FIX:** You have already reached the critical mass required to hit your target! No further monthly contributions are strictly necessary if assumptions hold.")
            
        st.divider()
        st.markdown("#### **Current Passive Income Generators**")
        
        inc_df = merged_df[merged_df['Annual Dividend (CAD)'] > 0].copy()
        if not inc_df.empty:
            inc_df = inc_df.groupby('Ticker', as_index=False)['Annual Dividend (CAD)'].sum()
            
            inc_df = inc_df.sort_values(by='Annual Dividend (CAD)', ascending=False)
            if len(inc_df) > 15:
                top_tickers = inc_df.head(15).copy()
                others_sum = inc_df.iloc[15:]['Annual Dividend (CAD)'].sum()
                others_row = pd.DataFrame([{'Ticker': 'OTHERS', 'Annual Dividend (CAD)': others_sum}])
                inc_df = pd.concat([top_tickers, others_row], ignore_index=True)
                
            inc_df = inc_df.sort_values(by='Annual Dividend (CAD)', ascending=True)
            
            inc_df['Bold Ticker'] = '<b>' + inc_df['Ticker'] + '</b>'
            fig_inc = px.bar(inc_df, x="Annual Dividend (CAD)", y="Bold Ticker", orientation='h', color="Annual Dividend (CAD)", color_continuous_scale="viridis")
            fig_inc.update_traces(hovertemplate="<b>Annual_Dividend_Income=%{x:,.2f}</b><br><b>Ticker=%{customdata}</b><extra></extra>", customdata=inc_df['Ticker'])
            
            fig_inc.update_layout(
                coloraxis_showscale=False, 
                margin=dict(t=10, b=40, l=40, r=10), 
                plot_bgcolor="rgba(0,0,0,0)", 
                paper_bgcolor="rgba(0,0,0,0)", 
                xaxis_title="<b>Annual_Dividend_Income</b>", 
                yaxis_title="<b>Ticker</b>",                 
                font=dict(size=14), 
                height=500
            )
            fig_inc.update_xaxes(tickfont=dict(size=14, weight="bold", family="Arial Black"))
            st.plotly_chart(fig_inc, use_container_width=True)
        else:
            st.warning("No dividend-generating assets found in the portfolio.")

    # --- TAB 4: 12-YEAR PROJECTION ---
    with tabs[3]:
        st.subheader("12-Year Compounding Projection (2026 - 2038)")
        st.markdown("Forecasting portfolio value and passive income trajectory based on actual current holdings.")
        
        projection_data = []
        current_value, current_annual_div = total_market_value, total_annual_div
        
        projection_data.append({"Year": 2026, "Portfolio Value": current_value, "Nominal Monthly Div": current_annual_div / 12, "Real Monthly Div (Inflation Adj)": current_annual_div / 12, "Target Min ($3,000)": 3000, "Target Max ($4,500)": 4500})
        
        for year in range(1, 13):
            new_capital = (sim_proposed_contribution * 12) + (current_annual_div if sim_drip else 0)
            current_value = (current_value * (1 + (sim_capital_growth / 100))) + new_capital
            current_annual_div = (current_annual_div * (1 + (sim_div_growth / 100))) + (new_capital * (sim_div_yield / 100))
            proj_monthly_div = current_annual_div / 12
            real_monthly_div = proj_monthly_div / ((1 + (sim_inflation / 100)) ** year)
            projection_data.append({"Year": 2026 + year, "Portfolio Value": current_value, "Nominal Monthly Div": proj_monthly_div, "Real Monthly Div (Inflation Adj)": real_monthly_div, "Target Min ($3,000)": 3000, "Target Max ($4,500)": 4500})
            
        proj_df = pd.DataFrame(projection_data)
        
        fig_proj = go.Figure()
        fig_proj.add_trace(go.Bar(x=proj_df["Year"], y=proj_df["Portfolio Value"], name="Portfolio Value", marker_color="rgba(133, 194, 255, 0.6)", yaxis="y"))
        
        BASE_PALETTE = ["#FF0000", "#00A86B", "#0000FF", "#EE82EE", "#FFA500"] 
        
        fig_proj.add_trace(go.Scatter(x=proj_df["Year"], y=proj_df["Real Monthly Div (Inflation Adj)"], name="Real Monthly Div", mode="lines+markers", line=dict(color=BASE_PALETTE[1], width=4), marker=dict(size=8), yaxis="y2"))
        fig_proj.add_trace(go.Scatter(x=proj_df["Year"], y=proj_df["Target Max ($4,500)"], mode='lines', line=dict(width=0), showlegend=False, yaxis="y2", hoverinfo='skip'))
        fig_proj.add_trace(go.Scatter(x=proj_df["Year"], y=proj_df["Target Min ($3,000)"], mode='lines', fill='tonexty', fillcolor='rgba(255, 215, 0, 0.2)', line=dict(width=0), name="Goal Zone", yaxis="y2"))
        
        fig_proj.update_layout(
            margin=dict(t=20, b=10, l=10, r=10),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", 
            legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5, font=dict(size=18)), 
            yaxis=dict(title="Value ($)", side="left", showgrid=False, tickformat="$,.0f", title_font=dict(size=20, weight="bold"), tickfont=dict(size=16)), 
            yaxis2=dict(title="Div ($/mo)", side="right", overlaying="y", showgrid=True, gridcolor='rgba(128,128,128,0.2)', tickformat="$,.0f", title_font=dict(size=20, weight="bold"), tickfont=dict(size=16)), 
            hovermode="x unified", hoverlabel=dict(font_size=24), height=550
        )
        
        fig_proj.update_xaxes(tickmode='linear', dtick=1, tickfont=dict(size=16, weight="bold"))
        
        st.plotly_chart(fig_proj, use_container_width=True)
        st.divider()
        
        st.markdown("#### Projection Summary")
        
        expanded_df = proj_df.copy()
        expanded_df.rename(columns={
            "Portfolio Value": "Value ($)", 
            "Nominal Monthly Div": "Nominal Div ($)",
            "Real Monthly Div (Inflation Adj)": "Real Div ($)",
            "Target Min ($3,000)": "Min Target ($)",
            "Target Max ($4,500)": "Max Target ($)"
        }, inplace=True)
        
        format_dict = {"Value ($)": "${:,.0f}", "Nominal Div ($)": "${:,.0f}", "Real Div ($)": "${:,.0f}", "Min Target ($)": "${:,.0f}", "Max Target ($)": "${:,.0f}"}
        
        styled_table = expanded_df.style.format(format_dict).hide(axis="index").set_properties(**{
            'text-align': 'left',
            'font-size': '22px'
        }).set_table_styles([
            dict(selector='th', props=[
                ('text-align', 'left'), 
                ('font-size', '22px'),
                ('background-color', '#1e1e1e'),
                ('color', 'white'),
                ('font-weight', '900')
            ])
        ])
        st.table(styled_table)
    
    # --- TAB 5: ASSET ALLOCATION ---
    with tabs[4]:
        st.subheader("Structural Robustness (Asset Allocation)")
        
        alloc_df = merged_df[merged_df['Market Value (CAD)'] > 0].copy()
        
        st.markdown("#### Allocation by Weight (Pie Chart)")
        
        fig_pie = px.pie(alloc_df, values='Market Value (CAD)', names='Ticker', hole=0.4)
        fig_pie.update_traces(textinfo='label+percent', textposition='inside', hovertemplate="<b>%{label}</b><br>Value: $%{value:,.2f}<br>Weight: %{percent}<extra></extra>")
        fig_pie.update_layout(margin=dict(t=10, b=30, l=10, r=10), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(size=14), showlegend=True)
        st.plotly_chart(fig_pie, use_container_width=True)
        
        st.divider()
        
        st.markdown("#### Dynamic Asset Performance Dashboard (Treemap)")
        
        with st.expander("📚 Glossary of Terms"):
            st.markdown("**Price Gain (Unrealized Capital Gain):** This is the change in the *price* of your asset since you bought it.")
            st.markdown("**Total Return:** This is the most complete measure. It includes the Price Gain *plus* all the income (dividends and interest) you've received from that asset. It accounts for both appreciation and income, which is what your dividend portfolio aims for.")

        st.markdown("*(Use these controls to explore different performance metrics and time horizons.)*")
        c_metric, c_time = st.columns(2)
        selected_metric = c_metric.selectbox("Gain Metric", ["Price Gain", "Total Return"])
        selected_timeline = c_time.selectbox("Timeline", ["Since Inception", "1 Year (Annualized)", "3 Years (Annualized)"])
        
        alloc_df['Root'] = 'Portfolio'
        alloc_df['Since_Inception_Num'] = np.where(alloc_df['Total Cost (CAD)'] > 0, (alloc_df['Total Unrealized Gain (CAD)'] / alloc_df['Total Cost (CAD)']) * 100, 0.0)
        
        if '1Y CAGR' in alloc_df.columns and '3Y CAGR' in alloc_df.columns:
            alloc_df['1Y_Num'] = pd.to_numeric(alloc_df['1Y CAGR'].astype(str).str.replace('%', '', regex=False).str.replace('N/A', 'nan', regex=False), errors='coerce').fillna(0)
            alloc_df['3Y_Num'] = pd.to_numeric(alloc_df['3Y CAGR'].astype(str).str.replace('%', '', regex=False).str.replace('N/A', 'nan', regex=False), errors='coerce').fillna(0)
        else:
            alloc_df['1Y_Num'] = 0.0
            alloc_df['3Y_Num'] = 0.0

        if selected_timeline == "Since Inception": base_val = alloc_df['Since_Inception_Num']
        elif selected_timeline == "1 Year (Annualized)": base_val = alloc_df['1Y_Num']
        elif selected_timeline == "3 Years (Annualized)": base_val = alloc_df['3Y_Num']

        if selected_metric == "Total Return":
            alloc_df['Plot_Gain'] = base_val + (alloc_df['Trailing Yield'].fillna(0) * 100)
        else:
            alloc_df['Plot_Gain'] = base_val

        available_tickers = alloc_df['Ticker'].unique().tolist()
        default_exclusion = ['EMBJ'] if 'EMBJ' in available_tickers else []
        outliers_to_exclude = st.multiselect("Select Assets to Hide (Outlier Filter):", options=available_tickers, default=default_exclusion)
        
        filtered_df = alloc_df[~alloc_df['Ticker'].isin(outliers_to_exclude)].copy()
        
        if not filtered_df.empty:
            max_abs_gain = filtered_df['Plot_Gain'].abs().max()
            if pd.isna(max_abs_gain) or max_abs_gain == 0: max_abs_gain = 10 
            
            filtered_df['Center_Text'] = filtered_df['Plot_Gain'].apply(lambda x: f"{x:,.2f}%")
            filtered_df['Text_Color'] = np.where(filtered_df['Plot_Gain'].abs() >= 20.0, 'white', 'black')
                
            fig_tree = px.treemap(
                filtered_df, 
                path=['Root', 'Ticker'], 
                values='Market Value (CAD)',
                color='Plot_Gain',
                color_continuous_scale='RdYlGn',
                range_color=[-max_abs_gain, max_abs_gain],
                custom_data=['Center_Text', 'Text_Color']
            )
            fig_tree.update_traces(
                texttemplate='<span style="color:%{customdata[1]}"><b>%{label}</b><br>%{customdata[0]}</span>',
                textposition="middle center",
                textfont=dict(size=22), 
                hovertemplate="<b>%{label}</b><br>Value: $%{value:,.2f}<br>" + selected_metric + ": %{color:.2f}%<extra></extra>",
                marker=dict(line=dict(width=4, color='white')),
                hoverlabel=dict(bgcolor='rgba(0,0,0,0.9)', font_size=28, font_color='#FFFFE0') 
            )
            fig_tree.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                paper_bgcolor="rgba(255, 255, 255, 0.08)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(size=18, color="white"),
                coloraxis_colorbar=dict(title=dict(text="Gain (%)", font=dict(size=20)), tickfont=dict(size=18)), 
                height=800 
            )
            st.plotly_chart(fig_tree, use_container_width=True)
        else:
            st.warning("All assets have been excluded. Remove filters to view the Treemap.")

    # --- TAB 6: ADVANCE ANALYTICS ---
    with tabs[5]: 
        st.subheader("Comparative Analysis Engine")
        BENCHMARK_INDICES = {"S&P 500": "^GSPC", "TSX": "^GSPTSE", "NASDAQ": "^IXIC", "Gold": "GC=F"}
        port_df = merged_df[merged_df['Market Value (CAD)'] > 0]
        port_tickers = port_df['Ticker'].unique().tolist() if not port_df.empty else []
        
        with st.form("comp_form"):
            st.markdown("##### 1. Select Assets & Parameters")
            c1, c2 = st.columns(2)
            base_sel = c1.multiselect("Standard Assets:", ["MyPortfolio (Synthetic)"] + port_tickers + list(BENCHMARK_INDICES.keys()), default=["MyPortfolio (Synthetic)", "S&P 500"])
            custom_t = c2.text_input("Custom Tickers (use .TO for Canada):", placeholder="AAPL, RY.TO, SCHD")
            
            c3, c4 = st.columns(2)
            comp_hz = c3.selectbox("Horizon:", ["1 Month", "6 Months", "YTD", "1 Year", "3 Years", "5 Years", "10 Years", "30 Years"], index=4)
            comp_metric = c4.selectbox("Metric:", ["Total Return (%)", "Drawdown (%)", "Raw Price ($)"])
            
            use_log = False
            if comp_metric == "Raw Price ($)":
                use_log = st.checkbox("Use Logarithmic Scale (Prevents squashing lower-priced assets)", value=True)
                
            submitted = st.form_submit_button("Run Comparative Analysis 📊")

        if submitted:
            custom_list = [t.strip().upper() for t in custom_t.split(",") if t.strip()]
            all_targets = list(set(base_sel + custom_list))
            yf_t = [BENCHMARK_INDICES.get(t, t) for t in all_targets if t != "MyPortfolio (Synthetic)"]
            
            calc_myp = "MyPortfolio (Synthetic)" in all_targets
            if calc_myp: yf_t = list(set(yf_t + port_tickers))
            
            d_map = {"1 Month":30, "6 Months":180, "YTD":-1, "1 Year":365, "3 Years":1095, "5 Years":1825, "10 Years":3650, "30 Years":10950}
            d_back = d_map.get(comp_hz, 1095)
            start_d = pd.Timestamp.today() - pd.Timedelta(days=d_back) if d_back != -1 else pd.Timestamp(pd.Timestamp.today().year, 1, 1)
            
            with st.spinner("Fetching market data..."):
                raw_data = yf.download(yf_t, start=start_d, auto_adjust=True)['Close']
            
            if not raw_data.empty:
                if isinstance(raw_data, pd.Series): raw_data = raw_data.to_frame(name=yf_t[0])
                plot_df = pd.DataFrame(index=raw_data.index)
                
                if calc_myp and not port_df.empty:
                    w = port_df.set_index('Ticker')['Market Value (CAD)']
                    myp_ret = raw_data[port_tickers].pct_change().fillna(0).dot(w / w.sum())
                    plot_df["MyPortfolio (Synthetic)"] = 100 * (1 + myp_ret).cumprod()
                
                for t in all_targets:
                    if t == "MyPortfolio (Synthetic)": continue
                    sym = BENCHMARK_INDICES.get(t, t)
                    if sym in raw_data.columns: plot_df[t] = raw_data[sym]
                
                plot_df = plot_df.dropna(how='all').ffill()
                fig, warns = go.Figure(), []
                
                BASE_PALETTE = ["#FF0000", "#00A86B", "#0000FF", "#EE82EE", "#FFA500"] 
                INDEX_COLORS = {"S&P 500": "#000000", "TSX": "#555555", "NASDAQ": "#888888", "Gold": "#8B8989", "MyPortfolio (Synthetic)": "#14213D"}
                c_idx = 0
                
                for col in plot_df.columns:
                    s = plot_df[col]
                    if col in INDEX_COLORS:
                        l_color, l_dash = INDEX_COLORS[col], 'solid'
                    else:
                        l_color = BASE_PALETTE[c_idx % 5]
                        l_dash = 'dot' if c_idx >= 5 else 'solid'
                        c_idx += 1
                    
                    if comp_metric == "Total Return (%)": y_data, y_lab, f = ((s / s.iloc[0]) - 1) * 100, "Cumulative Return (%)", ".2f"
                    elif comp_metric == "Drawdown (%)":
                        y_data, y_lab, f = ((s - s.cummax()) / s.cummax()) * 100, "Drawdown (%)", ".2f"
                        if y_data.iloc[-1] <= -15.0: warns.append(f"🚨 **{col}** is heavily discounted (Drawdown: {y_data.iloc[-1]:.1f}%)")
                    else: y_data, y_lab, f = s, "Price ($)", "$,.2f"
                    
                    fig.add_trace(go.Scatter(x=y_data.index, y=y_data, mode='lines', name=col, line=dict(width=3, color=l_color, dash=l_dash)))
                
                fig.update_layout(margin=dict(t=10,b=10,l=10,r=10), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5, font=dict(size=16)), yaxis=dict(title=y_lab, tickformat=f, title_font=dict(size=18, weight="bold"), tickfont=dict(size=14), showgrid=True, gridcolor='rgba(128,128,128,0.2)'), hovermode="x unified", hoverlabel=dict(font_size=20), height=550)
                if comp_metric == "Raw Price ($)" and use_log: fig.update_yaxes(type="log", tickformat="$,.0f")
                st.plotly_chart(fig, use_container_width=True)
                if warns and comp_metric == "Drawdown (%)": st.warning("\n".join(warns))
    
    # --- TAB 7: TRANSACTION LEDGER ---
    with tabs[6]:
        st.subheader("Transaction Ledger")
        col_t1, col_t2, col_t3 = st.columns(3)
        col_t1.metric("Total Transactions", len(txn_df))
        if 'Action' in txn_df.columns:
            col_t2.metric("Buy Orders", len(txn_df[txn_df['Action'].astype(str).str.upper() == 'BUY']))
            col_t3.metric("Sell Orders", len(txn_df[txn_df['Action'].astype(str).str.upper() == 'SELL']))
        st.dataframe(txn_df, hide_index=True, use_container_width=True)

    # --- TAB 8: MONTE CARLO SIMULATION ---
    with tabs[7]:
        st.subheader("Phase Space Projection (Monte Carlo)")
        mc_df = merged_df[['Ticker', 'Shares', 'Live Price (CAD)', 'Market Value (CAD)']].copy()
        if not mc_df.empty:
            mc_df.rename(columns={'Live Price (CAD)': 'Price_CAD', 'Market Value (CAD)': 'Total_Value'}, inplace=True)
            mc_df['Current_Weight'] = (mc_df['Total_Value'] / mc_df['Total_Value'].sum()) * 100
            mc_df['Proposed_Weight'] = mc_df['Current_Weight']
            mc_df.set_index('Ticker', inplace=True)

            mc_col1, mc_col2 = st.columns([1.2, 1.4])
            with mc_col1:
                with st.form("mc_rebalance_form"):
                    c1, c2 = st.columns(2)
                    with c1: curr_cont = st.number_input("CURRENT CONTRIB ($/MO)", min_value=0.0, value=float(sim_avg_contribution))
                    with c2: prop_cont = st.number_input("PROPOSED CONTRIB ($/MO)", min_value=0.0, value=float(sim_proposed_contribution))
                    
                    edited_ledger = st.data_editor(mc_df, column_config={"Shares": st.column_config.NumberColumn("SHARES"), "Price_CAD": st.column_config.NumberColumn("PRICE (CAD)"), "Total_Value": st.column_config.NumberColumn("TOTAL VALUE", disabled=True, format="$%.2f"), "Current_Weight": st.column_config.NumberColumn("CURRENT WT (%)", disabled=True, format="%.1f %%"), "Proposed_Weight": st.column_config.NumberColumn("PROPOSED WT (%)", format="%.1f %%")}, num_rows="dynamic", use_container_width=True)
                    sum_shares, sum_value = edited_ledger["Shares"].sum(), edited_ledger["Total_Value"].sum()
                    sum_curr, sum_prop = edited_ledger["Current_Weight"].sum(), edited_ledger["Proposed_Weight"].sum()
                    st.markdown(f"Shares: **{sum_shares:,.0f}** | Value: **${sum_value:,.2f}** | Curr: **{sum_curr:.0f}%** | Prop: **{sum_prop:.0f}%**")
                    submitted = st.form_submit_button("Run Simulation 📊")

            if submitted:
                st.toast("Booting Monte Carlo Engine...", icon="⚙️")
                current_tickers, current_balance = edited_ledger.index.dropna().tolist(), edited_ledger["Total_Value"].sum()
                w_curr, w_prop = np.array(edited_ledger["Current_Weight"].dropna().tolist()) / 100.0, np.array(edited_ledger["Proposed_Weight"].dropna().tolist()) / 100.0

                if not np.isclose(np.sum(w_prop), 1.0): 
                    st.error(f"⚠️ Weights must equal 100%. Currently: {np.sum(w_prop * 100):.1f}%")
                else:
                    all_tickers = list(set(current_tickers + ["^GSPC", "^GSPTSE"]))
                    prices = get_historical_data(all_tickers)
                    if prices.empty: 
                        st.error("🚨 CRITICAL ERROR: The historical data matrix is empty.")
                    else:
                        monthly_returns = prices.pct_change().dropna()
                        valid_tickers = [t for t in current_tickers if t in monthly_returns.columns]
                        mean_returns, cov_matrix = monthly_returns.mean() * 12, monthly_returns.cov() * 12

                        mu_sp, sig_sp = mean_returns["^GSPC"], np.sqrt(cov_matrix.loc["^GSPC", "^GSPC"])
                        mu_tsx, sig_tsx = mean_returns["^GSPTSE"], np.sqrt(cov_matrix.loc["^GSPTSE", "^GSPTSE"])
                        mu_curr = np.sum(mean_returns[valid_tickers] * w_curr[:len(valid_tickers)])
                        sig_curr = np.sqrt(np.dot(w_curr[:len(valid_tickers)].T, np.dot(cov_matrix.loc[valid_tickers, valid_tickers], w_curr[:len(valid_tickers)])))
                        mu_prop = np.sum(mean_returns[valid_tickers] * w_prop[:len(valid_tickers)])
                        sig_prop = np.sqrt(np.dot(w_prop[:len(valid_tickers)].T, np.dot(cov_matrix.loc[valid_tickers, valid_tickers], w_prop[:len(valid_tickers)])))

                        dt = 1/12
                        def run_gbm(mu, sigma, balance, cont):
                            paths = np.zeros((145, 1000)); paths[0] = balance
                            for i in range(1, 145): paths[i] = paths[i-1] * np.exp((mu - 0.5 * sigma**2)*dt + sigma*np.sqrt(dt)*np.random.standard_normal(1000)) + cont
                            return paths

                        paths_curr, paths_prop = run_gbm(mu_curr, sig_curr, current_balance, curr_cont), run_gbm(mu_prop, sig_prop, current_balance, prop_cont)
                        paths_sp, paths_tsx = run_gbm(mu_sp, sig_sp, current_balance, prop_cont), run_gbm(mu_tsx, sig_tsx, current_balance, prop_cont)

                        with mc_col2:
                            fig = go.Figure()
                            time_axis = (np.arange(145) / 12) + 2026 
                            med_curr, med_prop = np.round(np.median(paths_curr, axis=1)), np.round(np.median(paths_prop, axis=1))
                            med_sp, med_tsx = np.round(np.median(paths_sp, axis=1)), np.round(np.median(paths_tsx, axis=1))
                            
                            BASE_PALETTE = ["#FF0000", "#00A86B", "#0000FF", "#EE82EE", "#FFA500"] 
                            INDEX_COLORS = {"S&P 500": "#000000", "TSX": "#555555", "NASDAQ": "#888888", "Gold": "#8B8989", "MyPortfolio (Synthetic)": "#14213D"}
                            
                            fig.add_trace(go.Scatter(x=time_axis, y=np.percentile(paths_prop, 95, axis=1), mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip'))
                            fig.add_trace(go.Scatter(x=time_axis, y=np.percentile(paths_prop, 5, axis=1), mode='lines', line=dict(width=0), fill='tonexty', fillcolor='rgba(176, 196, 222, 0.4)', name='Risk Corridor'))
                            fig.add_trace(go.Scatter(x=time_axis, y=med_sp, mode='lines', line=dict(color=INDEX_COLORS["S&P 500"], width=2), name='S&P 500'))
                            fig.add_trace(go.Scatter(x=time_axis, y=med_tsx, mode='lines', line=dict(color=INDEX_COLORS["TSX"], width=2), name='TSX'))
                            fig.add_trace(go.Scatter(x=time_axis, y=med_curr, mode='lines', line=dict(color=BASE_PALETTE[0], width=3, dash='dash'), name='Current')) 
                            fig.add_trace(go.Scatter(x=time_axis, y=med_prop, mode='lines', line=dict(color=BASE_PALETTE[1], width=3), name='Proposed')) 
                            
                            fig.update_layout(title="Phase Space Projection (2026 - 2038)", xaxis_title="Timeline (Years)", yaxis_title="Portfolio Value (CAD)", yaxis_tickformat="$,.0f", hovermode="x unified", margin=dict(l=0, r=0, t=40, b=0))
                            st.plotly_chart(fig, use_container_width=True)

                            st.divider()
                            m1, m2, m3 = st.columns(3)
                            inc_curr, inc_prop = np.round((med_curr[-1]*0.04)/12), np.round((med_prop[-1]*0.04)/12)
                            with m1: st.markdown(f"**CURRENT TRAJECTORY**\n* Contrib: **${curr_cont}/mo**\n* Volatility: **{sig_curr*100:.2f}%**\n* Monthly Divid: **${inc_curr:,.0f}**")
                            with m2: st.markdown(f"**PROPOSED TRAJECTORY**\n* Contrib: **${prop_cont}/mo**\n* Volatility: **{sig_prop*100:.2f}%**\n* Monthly Divid: **${inc_prop:,.0f}**")
                            with m3:
                                delta = inc_prop - inc_curr
                                if inc_prop >= 3000: st.success(f"STATUS: TARGET REACHED\n\nShift: +${delta:,.0f} /mo")
                                elif delta > 0: st.info(f"STATUS: OPTIMIZED\n\nShift: +${delta:,.0f} /mo")
                                else: st.warning("STATUS: NEUTRAL")
                                
    # --- TAB 9: PERFORMANCE AUDIT (IRR) ---
    with tabs[8]:
        st.subheader("Personal Performance Audit (IRR)")
        
        with st.expander("📚 Glossary: Personal Return Terms", expanded=False):
            st.markdown("### Simple Terms for Complex Math")
            st.markdown("- **IRR (Internal Rate of Return):** Your 'Personal Interest Rate.' It accounts for the exact day you put money in. If this is higher than the S&P 500, you are outperforming the market with your timing.")
            st.markdown("- **Cash Flow:** Any 'Deposit' is a negative flow (money leaving your wallet); the 'Final Value' of your portfolio is a positive flow (money returning to your wallet).")
            st.markdown("- **Time-Weighted Return:** The return of the *stocks*. It ignores your deposits. This is what you see on Yahoo Finance.")

        if not txn_df.empty:
            st.info("🔄 IRR Engine: Calculating your dollar-weighted return based on all historical deposits and current market value...")
            
            txn_df['Parsed_Date'] = pd.to_datetime(txn_df[date_col], errors='coerce')
            deposits = txn_df[txn_df['Clean_Action'] == 'DEPOSIT'].copy()
            
            flows = []
            for _, row in deposits.iterrows():
                flows.append({'date': row['Parsed_Date'], 'amount': -row['Clean_Net_Amount']})
            
            flows.append({'date': pd.Timestamp.today(), 'amount': total_portfolio_value})
            flow_df = pd.DataFrame(flows).sort_values('date')
            
            def calculate_xirr(df):
                def npv(rate, df):
                    t0 = df['date'].min()
                    return sum(row['amount'] / (1 + rate)**((row['date'] - t0).days / 365.25) for _, row in df.iterrows())
                
                try:
                    a, b = -0.5, 1.0
                    for _ in range(50):
                        mid = (a + b) / 2
                        if npv(mid, df) > 0: a = mid
                        else: b = mid
                    return mid * 100
                except: return 0.0

            personal_irr = calculate_xirr(flow_df)
            
            st.metric("Your Personal IRR (Since Inception)", f"{personal_irr:.2f}%")
            st.markdown(f"*(This means your timing and capital moves have generated a compounded annual growth rate of **{personal_irr:.2f}%** on every dollar you've touched.)*")
        else:
            st.warning("No transaction history found to calculate IRR.")
            
# --- FINAL EXECUTION HOOK ---
if __name__ == "__main__":
    load_unified_dashboard()
