import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import time

# --- CONFIGURATION ---
DB_FILE = "shop_inventory.db"
SUPER_ADMIN_PASSWORD = "MASTER_OWNER_99" # Your global access
LOW_STOCK_THRESHOLD = 5

st.set_page_config(page_title="Multi-Shop Manager", layout="wide", page_icon="🏢")

# --- DATABASE INITIALIZATION ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Shops/Profiles table
    c.execute('''CREATE TABLE IF NOT EXISTS shops (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 shop_name TEXT UNIQUE,
                 admin_pwd TEXT,
                 oper_pwd TEXT,
                 co_name TEXT, co_address TEXT, co_vat TEXT, co_phone TEXT)''')
    
    # Products (linked to shop)
    c.execute('''CREATE TABLE IF NOT EXISTS products (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 shop_id INTEGER,
                 name TEXT,
                 rec_price REAL,
                 active INTEGER DEFAULT 1)''')
    
    # Inventory (linked to shop)
    c.execute('''CREATE TABLE IF NOT EXISTS inventory (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 shop_id INTEGER,
                 product_id INTEGER,
                 date TEXT,
                 qty_initial INTEGER,
                 qty_remaining INTEGER,
                 buy_price REAL)''')
    
    # Sales/Invoices (linked to shop)
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 shop_id INTEGER,
                 date TEXT,
                 customer_name TEXT,
                 customer_details TEXT,
                 total_amount REAL,
                 cost_basis REAL)''')

    # Sale Items (details of each invoice)
    c.execute('''CREATE TABLE IF NOT EXISTS sale_items (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 invoice_id INTEGER,
                 product_id INTEGER,
                 qty INTEGER,
                 sell_price REAL,
                 item_cost_basis REAL)''')
    
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
            return pd.DataFrame(data, columns=cols)
        conn.commit()
    finally:
        conn.close()

# --- FIFO LOGIC (Modified for multi-item) ---
def process_checkout(shop_id, cart, customer_name, customer_details, date):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        total_revenue = 0
        total_cost_basis = 0
        
        # 1. Create Invoice Header
        c.execute("INSERT INTO invoices (shop_id, date, customer_name, customer_details, total_amount, cost_basis) VALUES (?,?,?,?,?,?)",
                  (shop_id, date, customer_name, customer_details, 0, 0))
        invoice_id = c.lastrowid
        
        for item in cart:
            pid = item['id']
            qty_needed = item['qty']
            sell_price = item['price']
            item_total_cost = 0
            
            # FIFO deduction
            c.execute("SELECT id, qty_remaining, buy_price FROM inventory WHERE product_id=? AND qty_remaining > 0 ORDER BY date ASC, id ASC", (pid,))
            batches = c.fetchall()
            
            temp_qty = qty_needed
            for b_id, b_qty, b_price in batches:
                if temp_qty <= 0: break
                take = min(temp_qty, b_qty)
                item_total_cost += (take * b_price)
                c.execute("UPDATE inventory SET qty_remaining = qty_remaining - ? WHERE id = ?", (take, b_id))
                temp_qty -= take
            
            # Record sale item
            c.execute("INSERT INTO sale_items (invoice_id, product_id, qty, sell_price, item_cost_basis) VALUES (?,?,?,?,?)",
                      (invoice_id, pid, qty_needed, sell_price, item_total_cost))
            
            total_revenue += (qty_needed * sell_price)
            total_cost_basis += item_total_cost
            
        # Update Invoice Totals
        c.execute("UPDATE invoices SET total_amount=?, cost_basis=? WHERE id=?", (total_revenue, total_cost_basis, invoice_id))
        conn.commit()
        return True, "Success"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# --- AUTH SYSTEM ---
if 'auth' not in st.session_state:
    st.session_state.auth = {"logged_in": False, "shop_id": None, "role": None, "shop_name": ""}
if 'cart' not in st.session_state:
    st.session_state.cart = []

def login_page():
    st.title("🛡️ Software Access")
    tab1, tab2, tab3 = st.tabs(["Login", "Create New Shop", "Super-Admin"])
    
    with tab1:
        shop_names = run_query("SELECT shop_name FROM shops", fetch=True)
        if not shop_names.empty:
            s_name = st.selectbox("Select Shop", shop_names['shop_name'])
            role = st.radio("Access Level", ["Operator", "Administrator"], horizontal=True)
            pwd = st.text_input("Enter Password", type="password", key="pwd_login")
            if st.button("Enter Shop"):
                shop_data = run_query("SELECT * FROM shops WHERE shop_name=?", (s_name,), fetch=True).iloc[0]
                valid = (role == "Administrator" and pwd == shop_data['admin_pwd']) or (role == "Operator" and pwd == shop_data['oper_pwd'])
                if valid:
                    st.session_state.auth = {"logged_in": True, "shop_id": shop_data['id'], "role": role, "shop_name": s_name}
                    st.rerun()
                else: st.error("Wrong Password!")
        else: st.info("No shops created yet.")

    with tab2:
        with st.form("new_shop"):
            new_n = st.text_input("Shop Name (Unique)")
            adm_p = st.text_input("Admin Password")
            opr_p = st.text_input("Operator Password")
            if st.form_submit_button("Create My Shop"):
                if new_n and adm_p and opr_p:
                    try:
                        run_query("INSERT INTO shops (shop_name, admin_pwd, oper_pwd) VALUES (?,?,?)", (new_n, adm_p, opr_p))
                        st.success("Shop created! You can now login.")
                    except: st.error("Name already taken!")

    with tab3:
        spwd = st.text_input("Global Master Password", type="password")
        if st.button("Login as Super-Admin"):
            if spwd == SUPER_ADMIN_PASSWORD:
                st.session_state.auth = {"logged_in": True, "shop_id": "ALL", "role": "SuperAdmin", "shop_name": "GLOBAL CONTROL"}
                st.rerun()

# --- PAGES ---
def page_pos():
    st.header(f"🛒 POS - {st.session_state.auth['shop_name']}")
    
    # Cart display
    if st.session_state.cart:
        with st.expander("📝 Current Cart", expanded=True):
            cart_df = pd.DataFrame(st.session_state.cart)
            st.table(cart_df)
            if st.button("🗑️ Clear Cart"):
                st.session_state.cart = []
                st.rerun()

    # Product selection
    prods = run_query("SELECT id, name, rec_price FROM products WHERE shop_id=? AND active=1", (st.session_state.auth['shop_id'],), fetch=True)
    if prods.empty: 
        st.warning("Add products first!")
        return

    col1, col2, col3 = st.columns([2,1,1])
    sel_name = col1.selectbox("Product", prods['name'])
    p_info = prods[prods['name'] == sel_name].iloc[0]
    
    qty = col2.number_input("Qty", min_value=1, step=1)
    price = col3.number_input("Price", value=float(p_info['rec_price']))
    
    if st.button("➕ Add to List"):
        st.session_state.cart.append({"id": p_info['id'], "Product": sel_name, "qty": qty, "price": price, "Total": qty*price})
        st.rerun()

    if st.session_state.cart:
        st.divider()
        st.subheader("Finalize Transaction")
        c_name = st.text_input("Customer/Company Name (Required)")
        c_details = st.text_area("Additional Details (Address, VAT, etc.)")
        if st.button("✅ COMPLETE SALE & GENERATE INVOICE"):
            if c_name:
                ok, msg = process_checkout(st.session_state.auth['shop_id'], st.session_state.cart, c_name, c_details, str(datetime.now().date()))
                if ok:
                    st.success("Sale Recorded!")
                    st.session_state.cart = []
                    time.sleep(1)
                    st.rerun()
                else: st.error(msg)
            else: st.warning("Customer Name is required for the invoice.")

def page_invoices():
    st.header("📄 Invoice Management")
    invs = run_query("SELECT * FROM invoices WHERE shop_id=? ORDER BY id DESC", (st.session_state.auth['shop_id'],), fetch=True)
    
    if invs.empty:
        st.info("No invoices found.")
        return

    for idx, row in invs.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([1,2,1])
            c1.write(f"**INV #{row['id']}**")
            c1.write(row['date'])
            c2.write(f"👤 {row['customer_name']}")
            c3.write(f"💰 {row['total_amount']:.2f}")
            
            if st.button(f"👁️ View / Print #{row['id']}", key=f"btn_{row['id']}"):
                items = run_query("""SELECT p.name, s.qty, s.sell_price, (s.qty * s.sell_price) as subtotal 
                                     FROM sale_items s JOIN products p ON s.product_id = p.id 
                                     WHERE s.invoice_id=?""", (row['id'],), fetch=True)
                st.markdown(f"### INVOICE #{row['id']}")
                st.write(f"**Customer:** {row['customer_name']}")
                st.write(f"**Details:** {row['customer_details']}")
                st.table(items)
                st.write(f"### Total: {row['total_amount']:.2f}")
                st.button("🖨️ Print (Ctrl+P)")

def page_admin_settings():
    if st.session_state.auth['role'] != "Administrator":
        st.error("Access Denied")
        return
    
    st.header("⚙️ Admin - Company Details")
    shop = run_query("SELECT * FROM shops WHERE id=?", (st.session_state.auth['shop_id'],), fetch=True).iloc[0]
    
    with st.form("co_details"):
        new_co = st.text_input("Company Name", value=shop['co_name'] or "")
        new_addr = st.text_input("Address", value=shop['co_address'] or "")
        new_vat = st.text_input("VAT/Tax ID", value=shop['co_vat'] or "")
        if st.form_submit_button("Update Details"):
            run_query("UPDATE shops SET co_name=?, co_address=?, co_vat=? WHERE id=?", (new_co, new_addr, new_vat, st.session_state.auth['shop_id']))
            st.success("Updated!")

# --- MAIN ---
def main():
    init_db()
    if not st.session_state.auth['logged_in']:
        login_page()
        return

    # Sidebar
    st.sidebar.title(f"🏢 {st.session_state.auth['shop_name']}")
    st.sidebar.write(f"Role: **{st.session_state.auth['role']}**")
    if st.sidebar.button("🚪 Logout"):
        st.session_state.auth = {"logged_in": False, "shop_id": None, "role": None}
        st.rerun()

    menu = ["POS (Sales)", "Invoices List", "Stock Status", "Products"]
    if st.session_state.auth['role'] == "Administrator":
        menu.extend(["Daily Reports", "Company Settings"])
    
    choice = st.sidebar.radio("Navigation", menu)

    # Simple page routing
    if choice == "POS (Sales)": page_pos()
    elif choice == "Invoices List": page_invoices()
    elif choice == "Company Settings": page_admin_settings()
    # (Other pages remain similarly structured but filtered by shop_id)
    elif choice == "Products":
        # Add shop_id filter to your existing Page 1 logic
        st.write("Manage your products here (Linked to your shop ID)")
        # ... [Existing logic with shop_id filter]

if __name__ == "__main__":
    main()
    
