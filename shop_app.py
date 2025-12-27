import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import time

# --- CONFIGURATION ---
DB_FILE = "shop_inventory.db"
MASTER_PASSWORD = "1234"  # CHANGE THIS PASSWORD!
LOW_STOCK_THRESHOLD = 5

st.set_page_config(page_title="Shop Manager", layout="wide", page_icon="🛒")

# --- HELPER FUNCTIONS ---

def make_download_button(df, filename):
    """Generates a download button for any dataframe"""
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="💾 Download Data (CSV)",
        data=csv,
        file_name=filename,
        mime="text/csv",
        help="Click to download this table as an Excel-compatible CSV file"
    )

def render_instructions(text):
    """Helper to render instructions at the bottom of pages"""
    st.divider()
    with st.expander("ℹ️ Help Guide: How to work with this page"):
        st.markdown(text)

# --- DATABASE FUNCTIONS ---

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Products Table
    c.execute('''CREATE TABLE IF NOT EXISTS products (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT UNIQUE,
                 rec_price REAL,
                 active INTEGER DEFAULT 1)''')
    
    # Inventory Table
    c.execute('''CREATE TABLE IF NOT EXISTS inventory (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 product_id INTEGER,
                 date TEXT,
                 qty_initial INTEGER,
                 qty_remaining INTEGER,
                 buy_price REAL,
                 FOREIGN KEY(product_id) REFERENCES products(id))''')
    
    # Sales Table
    c.execute('''CREATE TABLE IF NOT EXISTS sales (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 product_id INTEGER,
                 date TEXT,
                 qty_sold INTEGER,
                 sell_price REAL,
                 total_sell_price REAL,
                 cost_basis REAL,
                 note TEXT,
                 FOREIGN KEY(product_id) REFERENCES products(id))''')
    
    conn.commit()
    conn.close()

def run_query(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute(query, params)
        if fetch:
            data = c.fetchall()
            cols = [desc[0] for desc in c.description]
            conn.close()
            return pd.DataFrame(data, columns=cols)
        conn.commit()
    except Exception as e:
        st.error(f"Database error: {e}")
    finally:
        conn.close()

# --- FIFO SALES LOGIC ---

def execute_sale(product_id, qty_requested, sell_price, date, note):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    try:
        # Check Availability
        c.execute("SELECT SUM(qty_remaining) FROM inventory WHERE product_id = ?", (product_id,))
        result = c.fetchone()[0]
        current_stock = result if result else 0
        
        if current_stock < qty_requested:
            return False, f"Insufficient stock! Available: {current_stock}, Requested: {qty_requested}"
        
        # FIFO Algorithm
        c.execute("""SELECT id, qty_remaining, buy_price 
                     FROM inventory 
                     WHERE product_id = ? AND qty_remaining > 0 
                     ORDER BY date ASC, id ASC""", (product_id,))
        batches = c.fetchall()
        
        qty_needed = qty_requested
        total_cost_basis = 0.0
        
        for batch_id, batch_qty, batch_price in batches:
            if qty_needed <= 0:
                break
                
            take_qty = min(qty_needed, batch_qty)
            total_cost_basis += (take_qty * batch_price)
            c.execute("UPDATE inventory SET qty_remaining = qty_remaining - ? WHERE id = ?", (take_qty, batch_id))
            qty_needed -= take_qty
            
        # Record Sale
        total_sell = qty_requested * sell_price
        c.execute("""INSERT INTO sales (product_id, date, qty_sold, sell_price, total_sell_price, cost_basis, note)
                     VALUES (?, ?, ?, ?, ?, ?, ?)""",
                  (product_id, date, qty_requested, sell_price, total_sell, total_cost_basis, note))
        
        conn.commit()
        return True, "Sale successful!"
        
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# --- AUTH ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'is_admin' not in st.session_state:
    st.session_state['is_admin'] = False

def login():
    st.sidebar.title("🔐 Login")
    role = st.sidebar.radio("Role", ["Operator", "Administrator"])
    
    if role == "Administrator":
        pwd = st.sidebar.text_input("Master Password", type="password")
        if st.sidebar.button("Login as Admin"):
            if pwd == MASTER_PASSWORD:
                st.session_state['logged_in'] = True
                st.session_state['is_admin'] = True
                st.rerun()
            else:
                st.sidebar.error("Invalid password!")
    else:
        if st.sidebar.button("Login as Operator"):
            st.session_state['logged_in'] = True
            st.session_state['is_admin'] = False
            st.rerun()

def logout():
    st.session_state['logged_in'] = False
    st.session_state['is_admin'] = False
    st.rerun()

# --- PAGES ---

def page_products():
    st.header("📦 Page 1: Product Nomenclature")
    
    with st.form("new_product"):
        col1, col2 = st.columns(2)
        name = col1.text_input("Product Name")
        price = col2.number_input("Recommended Price", min_value=0.0, step=0.01)
        submitted = st.form_submit_button("Create Product")
        
        if submitted and name:
            try:
                run_query("INSERT INTO products (name, rec_price, active) VALUES (?, ?, 1)", (name, price))
                st.success(f"Product '{name}' created!")
            except:
                st.error("Product with this name already exists!")

    st.subheader("Product List")
    df = run_query("SELECT id as 'ID', name as 'Name', rec_price as 'Rec. Price', CASE WHEN active=1 THEN 'Active' ELSE 'Archived' END as 'Status' FROM products", fetch=True)
    
    make_download_button(df, "products_list.csv")
    st.dataframe(df, use_container_width=True)
    
    if st.session_state['is_admin']:
        with st.expander("🛠 Admin Settings (Edit / Archive)"):
            prod_id = st.number_input("Product ID to Edit", min_value=1, step=1)
            new_name = st.text_input("New Name")
            new_price = st.number_input("New Price", min_value=0.0)
            
            col_a, col_b, col_c = st.columns(3)
            if col_a.button("Update Info"):
                if new_name: run_query("UPDATE products SET name = ? WHERE id = ?", (new_name, prod_id))
                if new_price > 0: run_query("UPDATE products SET rec_price = ? WHERE id = ?", (new_price, prod_id))
                st.success("Updated!")
                st.rerun()
            if col_b.button("ARCHIVE"):
                run_query("UPDATE products SET active = 0 WHERE id = ?", (prod_id,))
                st.warning("Archived!")
                st.rerun()
            if col_c.button("REACTIVATE"):
                run_query("UPDATE products SET active = 1 WHERE id = ?", (prod_id,))
                st.success("Reactivated!")
                st.rerun()
    
    render_instructions("""
    ### Welcome to the starting point of your shop system!
    Before you can buy or sell anything, the system needs to know that a product exists. Think of this page as creating the **"Birth Certificate"** for your items.
    
    **How to use this page:**
    1.  **Look at the form at the top:** This is where you introduce a new item.
    2.  **Type the name:** Enter what the product is called (e.g., "Chicken Feed 5kg").
    3.  **Set a Recommended Price:** This is just a helper for the sales menu later.
    4.  **Click 'Create Product':** Once clicked, the item is saved and ready to be stocked in Page 2.
    
    **For Administrators:**
    If you stop selling an item, use the **'ARCHIVE'** button. This hides it from the sales menu but keeps your old reports accurate.
    """)

def page_inventory():
    st.header("📥 Page 2: Stock In (Inventory)")
    
    products_df = run_query("SELECT id, name FROM products WHERE active = 1 ORDER BY name ASC", fetch=True)
    if products_df.empty:
        st.warning("No active products defined!")
        return

    product_options = {row['name']: row['id'] for index, row in products_df.iterrows()}
    
    with st.form("add_inventory"):
        col1, col2 = st.columns(2)
        selected_name = col1.selectbox("Select Product (Type to search)", list(product_options.keys()))
        date = col2.date_input("Delivery Date", datetime.now())
        
        col3, col4 = st.columns(2)
        qty = col3.number_input("Quantity", min_value=1, step=1)
        price = col4.number_input("Buy Price (Unit)", min_value=0.0, step=0.01)
        
        if st.form_submit_button("Save to Inventory"):
            pid = product_options[selected_name]
            run_query("""INSERT INTO inventory (product_id, date, qty_initial, qty_remaining, buy_price) 
                         VALUES (?, ?, ?, ?, ?)""", (pid, date, qty, qty, price))
            st.success("Stock added!")
    
    st.divider()
    st.subheader("Delivery History")
    query = """
    SELECT i.id, i.date as 'Date', p.name as 'Product', i.qty_initial as 'Init Qty', 
           i.qty_remaining as 'Remaining Qty', 
           i.buy_price as 'Unit Price', (i.qty_initial * i.buy_price) as 'Total'
    FROM inventory i
    JOIN products p ON i.product_id = p.id
    ORDER BY i.date DESC, i.id DESC
    """
    df = run_query(query, fetch=True)
    
    make_download_button(df, "inventory_log.csv")
    st.dataframe(df, use_container_width=True)
    
    if st.session_state['is_admin']:
        with st.expander("🛠 Admin: Edit Delivery"):
            inv_id = st.number_input("Entry ID to Edit", min_value=1, step=1, key="inv_edit_id")
            new_qty = st.number_input("New Initial Qty", min_value=1, step=1, key="inv_new_qty")
            new_price = st.number_input("New Price", min_value=0.0, step=0.01, key="inv_new_price")
            
            c1, c2 = st.columns(2)
            if c1.button("Edit Entry"):
                run_query("UPDATE inventory SET qty_initial=?, qty_remaining=?, buy_price=? WHERE id=?", 
                          (new_qty, new_qty, new_price, inv_id)) 
                st.success("Entry updated!")
                st.rerun()

            if c2.button("DELETE Entry", type="primary"):
                 check = run_query("SELECT qty_initial, qty_remaining FROM inventory WHERE id=?", (inv_id,), fetch=True)
                 if not check.empty:
                     if check.iloc[0]['qty_initial'] == check.iloc[0]['qty_remaining']:
                         run_query("DELETE FROM inventory WHERE id=?", (inv_id,))
                         st.success("Deleted!")
                         st.rerun()
                     else:
                         st.error("Cannot delete used stock!")

    render_instructions("""
    ### This is where your shop receives goods.
    Think of this as the **"Loading Dock"**. When a truck arrives, you enter the items here.
    
    **Step-by-Step Guide:**
    1.  **Select Product:** Start typing the name of the arrived item.
    2.  **Quantity:** Count the items physically and enter the number.
    3.  **Buy Price (Unit):** How much did YOU pay for *one single unit*? This is critical for profit calculation.
    4.  **Save:** Click the button to put the items on your virtual shelf.
    
    **The Table Below:**
    The column **'Remaining Qty'** shows how many items from *that specific delivery* are still sitting in your shop.
    """)

def page_sales():
    st.header("💰 Page 3: Point of Sale (POS)")
    
    products_df = run_query("SELECT id, name, rec_price FROM products WHERE active = 1 ORDER BY name ASC", fetch=True)
    if products_df.empty:
        st.warning("No active products.")
        return

    prod_map = {row['name']: (row['id'], row['rec_price']) for index, row in products_df.iterrows()}
    
    selected_prod_name = st.selectbox("1. Select Product (Type to search)", list(prod_map.keys()))
    pid, rec_price = prod_map[selected_prod_name]
    
    # Check Stock
    res = run_query("SELECT SUM(qty_remaining) FROM inventory WHERE product_id=?", (pid,), fetch=True)
    curr_stock = res.iloc[0,0] if res.iloc[0,0] is not None else 0
    
    # --- LOW STOCK WARNING LOGIC ---
    if curr_stock == 0:
        st.error(f"❌ OUT OF STOCK! Available: 0")
    elif curr_stock < LOW_STOCK_THRESHOLD:
        st.warning(f"⚠️ LOW STOCK WARNING: Only {curr_stock} pcs left! Please reorder soon. | Rec. Price: {rec_price}")
    else:
        st.info(f"✅ Stock Available: {curr_stock} pcs | Rec. Price: {rec_price}")

    with st.form("make_sale"):
        col1, col2 = st.columns(2)
        qty = col1.number_input("Quantity to Sell", min_value=1, step=1)
        price = col2.number_input("Sell Price", value=float(rec_price), min_value=0.0, step=0.01)
        
        col3, col4 = st.columns(2)
        date = col3.date_input("Date", datetime.now())
        note = col4.text_input("Note/Customer Name")
        
        submitted = st.form_submit_button("✅ ADD SALE")
        
        if submitted:
            if qty > curr_stock:
                st.error(f"❌ ERROR: Insufficient stock! You have {curr_stock} pcs, but tried to sell {qty} pcs.")
            else:
                success, msg = execute_sale(pid, qty, price, date, note)
                if success:
                    st.success(msg)
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(msg)
    
    st.divider()
    st.subheader("Recent Sales")
    
    q_sales = """
        SELECT s.id, s.date as 'Date', p.name as 'Product', s.qty_sold as 'Qty', 
               s.sell_price as 'Price', s.total_sell_price as 'Total', s.note as 'Note'
        FROM sales s
        JOIN products p ON s.product_id = p.id
        ORDER BY s.date DESC, s.id DESC
        LIMIT 100
    """
    df_sales = run_query(q_sales, fetch=True)
    make_download_button(df_sales, "sales_log.csv")
    st.dataframe(df_sales, use_container_width=True)

    render_instructions("""
    ### Welcome to the Cash Register!
    This is where you record money coming in. 
    
    **The Sales Flow:**
    1.  **Select Product:** Pick the item. The system will alert you if stock is low (under 5 pcs) with an orange bar.
    2.  **Check Stock:** If you see a red bar, you cannot sell the item until you add stock in Page 2.
    3.  **Enter Quantity:** If you try to sell more than you have, the system will block the transaction.
    4.  **Confirm Price:** The system suggests the recommended price, but you can change it manually.
    
    **FIFO Logic:** The system automatically sells the *oldest* stock first to ensure your profit reports are mathematically perfect.
    """)

def page_stock_report():
    st.header("🔎 Page 4: Stock Status")
    
    search = st.text_input("🔍 Search Table")
    
    query = """
    SELECT p.name as 'Item', 
           SUM(i.qty_remaining) as 'Stock',
           ROUND(SUM(i.qty_remaining * i.buy_price) / SUM(i.qty_remaining), 2) as 'Avg Buy Price'
    FROM inventory i
    JOIN products p ON i.product_id = p.id
    WHERE i.qty_remaining > 0
    GROUP BY p.id
    """
    
    if search:
        query = f"""
        SELECT p.name as 'Item', 
               SUM(i.qty_remaining) as 'Stock',
               ROUND(SUM(i.qty_remaining * i.buy_price) / SUM(i.qty_remaining), 2) as 'Avg Buy Price'
        FROM inventory i
        JOIN products p ON i.product_id = p.id
        WHERE i.qty_remaining > 0 AND p.name LIKE '%{search}%'
        GROUP BY p.id
        """
        
    df = run_query(query, fetch=True)
    
    # --- HIGHLIGHT LOW STOCK IN TABLE ---
    def highlight_low_stock(val):
        color = 'red' if val < LOW_STOCK_THRESHOLD else 'white'
        return f'color: {color}; font-weight: bold' if val < LOW_STOCK_THRESHOLD else ''

    if not df.empty:
        styled_df = df.style.map(highlight_low_stock, subset=['Stock'])
        st.dataframe(styled_df, use_container_width=True)
        make_download_button(df, "current_stock.csv")
    else:
        st.info("Your shop is empty. Add stock in Page 2.")

    render_instructions("""
    ### Your Warehouse at a Glance
    This page shows you what is currently on your shelves.
    
    **Visual Alerts:**
    * **Red Numbers:** If a quantity in the 'Stock' column is red, it means you have less than 5 items left. It's time to reorder!
    * **Avg Buy Price:** This tells you the average cost of the items you currently have.
    
    **Tip:** Use this page to do a quick inventory check at the end of the day.
    """)

def page_financial_report():
    if not st.session_state['is_admin']:
        st.error("Access Denied!")
        return

    st.header("📈 Page 5: Sales Log (Detailed)")
    
    filter_date = st.date_input("Select Date", datetime.now())
    
    query = """
    SELECT s.date as 'Date', p.name as 'Item', s.qty_sold as 'Qty', 
           ROUND(s.cost_basis / s.qty_sold, 2) as 'Avg Cost',
           s.sell_price as 'Sell Price',
           s.total_sell_price as 'Total Sales',
           (s.total_sell_price - s.cost_basis) as 'Profit',
           ROUND(((s.total_sell_price - s.cost_basis) / s.total_sell_price) * 100, 1) as 'Margin %'
    FROM sales s
    JOIN products p ON s.product_id = p.id
    WHERE s.date = ?
    ORDER BY s.id DESC
    """
    
    df = run_query(query, (filter_date,), fetch=True)
    
    if not df.empty:
        total_turnover = df['Total Sales'].sum()
        total_profit = df['Profit'].sum()
        total_qty = df['Qty'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Daily Turnover", f"{total_turnover:.2f}")
        c2.metric("Total Profit", f"{total_profit:.2f}")
        c3.metric("Items Sold", f"{total_qty}")
        st.dataframe(df, use_container_width=True)
        make_download_button(df, f"sales_report_{filter_date}.csv")
    else:
        st.info("No sales recorded for this date.")

    render_instructions("""
    ### The Financial Audit Trail
    This is the **"Truth Page"**. It shows you exactly how much money you made on every single transaction today.
    * **Profit:** Calculated as (Total Sales - Actual Cost of those specific items).
    * **Margin %:** Shows your efficiency. High margin = high profit per item.
    """)

def page_item_sales_report():
    if not st.session_state['is_admin']:
        st.error("Access Denied!")
        return

    st.header("📊 Page 6: Sales by Item")
    
    c1, c2 = st.columns(2)
    d_start = c1.date_input("From Date", datetime.now())
    d_end = c2.date_input("To Date", datetime.now())
    
    query = """
    SELECT p.name as 'Item',
           SUM(s.cost_basis) as 'Total Cost',
           ROUND(SUM(s.cost_basis)/SUM(s.qty_sold), 2) as 'Unit Cost',
           SUM(s.total_sell_price) as 'Total Sales',
           ROUND(SUM(s.total_sell_price)/SUM(s.qty_sold), 2) as 'Unit Sell Price',
           SUM(s.total_sell_price - s.cost_basis) as 'Profit',
           ROUND((SUM(s.total_sell_price - s.cost_basis) / SUM(s.total_sell_price))*100, 1) as 'Margin %'
    FROM sales s
    JOIN products p ON s.product_id = p.id
    WHERE s.date BETWEEN ? AND ?
    GROUP BY p.id
    """
    
    df = run_query(query, (d_start, d_end), fetch=True)
    st.dataframe(df, use_container_width=True)
    make_download_button(df, f"item_report_{d_start}_{d_end}.csv")

    render_instructions("""
    ### Analyze Your Best Sellers
    This page aggregates your data. Instead of listing every sale, it shows you the **Total Performance** of each product over time.
    * Use this to see which product is your biggest money-maker.
    """)

def page_pricelist():
    st.header("📋 Page 7: Price List")
    
    query = """
    SELECT p.name as 'Product', p.rec_price as 'Sell Price',
           (SELECT ROUND(SUM(i.qty_remaining * i.buy_price) / SUM(i.qty_remaining), 2) 
            FROM inventory i WHERE i.product_id = p.id AND i.qty_remaining > 0) as 'Avg Stock Price',
           CASE WHEN p.active = 1 THEN 'Active' ELSE 'Archived' END as 'Status'
    FROM products p
    """
    df = run_query(query, fetch=True)
    
    df['Avg Stock Price'] = df['Avg Stock Price'].fillna(0)
    df['Proj. Margin %'] = df.apply(
        lambda x: round(((x['Sell Price'] - x['Avg Stock Price']) / x['Sell Price'] * 100), 1) 
        if x['Sell Price'] > 0 and x['Avg Stock Price'] > 0 else 0, axis=1
    )
    
    st.dataframe(df, use_container_width=True)
    make_download_button(df, "price_list.csv")

    render_instructions("""
    ### Strategic Pricing Dashboard
    This page tells you: *"If I sell this item at my recommended price, how much will I make?"*
    * It compares your planned price against the **actual average cost** of items currently in stock.
    """)

def page_daily_report():
    if not st.session_state['is_admin']:
        st.error("Access Denied!")
        return

    st.header("📅 Page 8: Daily Financial Report")
    
    c1, c2 = st.columns(2)
    d_start = c1.date_input("From Date", datetime.now())
    d_end = c2.date_input("To Date", datetime.now())
    
    query = """
    SELECT date as 'Date', SUM(qty_sold) as 'Total Qty', SUM(cost_basis) as 'Total Cost', SUM(total_sell_price) as 'Total Revenue'
    FROM sales WHERE date BETWEEN ? AND ? GROUP BY date ORDER BY date DESC
    """
    df = run_query(query, (d_start, d_end), fetch=True)
    
    if df.empty:
        st.info("No data for this period.")
        return

    df['Total Profit'] = df['Total Revenue'] - df['Total Cost']
    df['Margin %'] = df.apply(lambda x: round((x['Total Profit'] / x['Total Revenue'] * 100), 1) if x['Total Revenue'] > 0 else 0, axis=1)
    df = df[['Date', 'Total Revenue', 'Total Cost', 'Total Qty', 'Total Profit', 'Margin %']]
    
    st.dataframe(df, use_container_width=True)
    
    st.divider()
    st.subheader("📝 Period Summary")
    sum_revenue = df['Total Revenue'].sum()
    sum_profit = df['Total Profit'].sum()
    avg_margin = (sum_profit / sum_revenue * 100) if sum_revenue > 0 else 0
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Revenue", f"{sum_revenue:.2f}")
    col2.metric("Total Profit", f"{sum_profit:.2f}")
    col3.metric("Avg Margin", f"{avg_margin:.1f}%")
    make_download_button(df, "daily_report.csv")

    render_instructions("""
    ### The Executive Summary
    This page groups your sales by **Day**. It's the best way to see the growth of your business over weeks or months.
    """)

# --- MAIN MENU ---

def main():
    init_db()
    if not st.session_state['logged_in']:
        login()
        return

    st.sidebar.title("Shop Navigation")
    st.sidebar.write(f"Logged as: **{st.session_state['is_admin'] and 'Admin' or 'Operator'}**")
    if st.sidebar.button("Logout"):
        logout()
    
    options = ["1. Products", "2. Inventory (Stock In)", "3. POS (Sales)", "4. Stock Status", "7. Price List"]
    if st.session_state['is_admin']:
        options.extend(["5. Sales Log (Detailed)", "6. Sales by Item", "8. Daily Report"])
        
    choice = st.sidebar.radio("Go to Page:", options)
    
    if "1." in choice: page_products()
    elif "2." in choice: page_inventory()
    elif "3." in choice: page_sales()
    elif "4." in choice: page_stock_report()
    elif "5." in choice: page_financial_report()
    elif "6." in choice: page_item_sales_report()
    elif "7." in choice: page_pricelist()
    elif "8." in choice: page_daily_report()

if __name__ == '__main__':
    main()
