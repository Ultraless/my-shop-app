import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import time

# --- CONFIGURATION ---
DB_FILE = "shop_inventory.db"
SUPER_ADMIN_PASSWORD = "MASTER_OWNER_99" 
LOW_STOCK_THRESHOLD = 5

st.set_page_config(page_title="Pro Multi-Shop Manager", layout="wide", page_icon="🏢")

# --- DATABASE SYSTEM ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS shops (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 shop_name TEXT UNIQUE,
                 admin_pwd TEXT,
                 oper_pwd TEXT,
                 co_name TEXT, co_address TEXT, co_vat TEXT, co_phone TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS products (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id INTEGER,
                 name TEXT, rec_price REAL, active INTEGER DEFAULT 1)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS inventory (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id INTEGER,
                 product_id INTEGER, date TEXT, qty_initial INTEGER,
                 qty_remaining INTEGER, buy_price REAL)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id INTEGER,
                 date TEXT, customer_name TEXT, customer_details TEXT,
                 total_amount REAL, cost_basis REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS sale_items (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER,
                 product_id INTEGER, qty INTEGER, sell_price REAL, item_cost_basis REAL)''')
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

# --- FIFO & CART LOGIC ---
def process_checkout(shop_id, cart, customer_name, customer_details, date):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        total_revenue = 0
        total_cost_basis = 0
        c.execute("INSERT INTO invoices (shop_id, date, customer_name, customer_details, total_amount, cost_basis) VALUES (?,?,?,?,?,?)",
                  (shop_id, date, customer_name, customer_details, 0, 0))
        invoice_id = c.lastrowid
        
        for item in cart:
            pid, qty_needed, sell_price = item['id'], item['qty'], item['price']
            item_total_cost = 0
            c.execute("SELECT id, qty_remaining, buy_price FROM inventory WHERE product_id=? AND qty_remaining > 0 ORDER BY date ASC, id ASC", (pid,))
            batches = c.fetchall()
            
            temp_qty = qty_needed
            for b_id, b_qty, b_price in batches:
                if temp_qty <= 0: break
                take = min(temp_qty, b_qty)
                item_total_cost += (take * b_price)
                c.execute("UPDATE inventory SET qty_remaining = qty_remaining - ? WHERE id = ?", (take, b_id))
                temp_qty -= take
            
            c.execute("INSERT INTO sale_items (invoice_id, product_id, qty, sell_price, item_cost_basis) VALUES (?,?,?,?,?)",
                      (invoice_id, pid, qty_needed, sell_price, item_total_cost))
            total_revenue += (qty_needed * sell_price)
            total_cost_basis += item_total_cost
            
        c.execute("UPDATE invoices SET total_amount=?, cost_basis=? WHERE id=?", (total_revenue, total_cost_basis, invoice_id))
        conn.commit()
        return True, invoice_id
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# --- SESSION STATE ---
if 'auth' not in st.session_state:
    st.session_state.auth = {"logged_in": False, "shop_id": None, "role": None, "shop_name": ""}
if 'cart' not in st.session_state:
    st.session_state.cart = []

# --- UI COMPONENTS ---
def login_page():
    st.title("🛡️ Business Software Gateway")
    t1, t2, t3 = st.tabs(["Login", "Register New Shop", "Super-Admin"])
    
    with t1:
        shops = run_query("SELECT id, shop_name FROM shops", fetch=True)
        if not shops.empty:
            s_name = st.selectbox("Choose Shop", shops['shop_name'])
            role = st.radio("Access Level", ["Operator", "Administrator"], horizontal=True)
            pwd = st.text_input("Password", type="password", key="login_pwd")
            if st.button("Enter Store"):
                data = run_query("SELECT * FROM shops WHERE shop_name=?", (s_name,), fetch=True).iloc[0]
                if (role == "Administrator" and pwd == data['admin_pwd']) or (role == "Operator" and pwd == data['oper_pwd']):
                    st.session_state.auth = {"logged_in": True, "shop_id": data['id'], "role": role, "shop_name": s_name}
                    st.rerun()
                else: st.error("Access Denied")
        else: st.info("No shops registered. Go to 'Register' tab.")

    with t2:
        with st.form("reg"):
            n = st.text_input("Unique Shop Name")
            a_p = st.text_input("Admin Password (Full Control)")
            o_p = st.text_input("Operator Password (Sales Only)")
            if st.form_submit_button("Create My Shop"):
                if n and a_p and o_p:
                    try:
                        run_query("INSERT INTO shops (shop_name, admin_pwd, oper_pwd) VALUES (?,?,?)", (n, a_p, o_p))
                        st.success("Registration successful!")
                    except: st.error("Shop name already exists!")

    with t3:
        spwd = st.text_input("Global Control Key", type="password")
        if st.button("Open Super-Admin Panel"):
            if spwd == SUPER_ADMIN_PASSWORD:
                st.session_state.auth = {"logged_in": True, "shop_id": "ALL", "role": "SuperAdmin", "shop_name": "GLOBAL"}
                st.rerun()

def page_pos():
    st.header(f"🛒 Register Sale - {st.session_state.auth['shop_name']}")
    
    if st.session_state.cart:
        with st.container(border=True):
            st.subheader("📝 Current Cart")
            df_c = pd.DataFrame(st.session_state.cart)
            st.table(df_c[['Product', 'qty', 'price', 'Total']])
            if st.button("🗑️ Clear Everything"):
                st.session_state.cart = []
                st.rerun()

    prods = run_query("SELECT id, name, rec_price FROM products WHERE shop_id=? AND active=1", (st.session_state.auth['shop_id'],), fetch=True)
    if prods.empty: return st.warning("First, add products in the 'Products' page.")

    c1, c2, c3 = st.columns([3,1,1])
    sel = c1.selectbox("Pick Product", prods['name'])
    p_data = prods[prods['name'] == sel].iloc[0]
    
    # Stock Check
    stock_res = run_query("SELECT SUM(qty_remaining) FROM inventory WHERE product_id=?", (p_data['id'],), fetch=True)
    avail = stock_res.iloc[0,0] or 0
    st.caption(f"Stock in shelf: {avail} | Rec. Price: {p_data['rec_price']}")

    qty = c2.number_input("Qty", min_value=1, max_value=int(avail) if avail > 0 else 1)
    price = c3.number_input("Final Price", value=float(p_data['rec_price']))

    if st.button("➕ Add to Cart") and avail >= qty:
        st.session_state.cart.append({"id": p_data['id'], "Product": sel, "qty": qty, "price": price, "Total": qty*price})
        st.rerun()

    if st.session_state.cart:
        st.divider()
        st.subheader("Finalize & Invoice")
        cust = st.text_input("Customer Name / Company (Required)")
        det = st.text_area("Billing Details (Address, VAT, etc.)")
        if st.button("✅ ISSUE INVOICE") and cust:
            ok, inv_id = process_checkout(st.session_state.auth['shop_id'], st.session_state.cart, cust, det, str(datetime.now().date()))
            if ok:
                st.success(f"Invoice #{inv_id} created!")
                st.session_state.cart = []
                time.sleep(1)
                st.rerun()

def page_invoices():
    st.header("📋 Invoice List & Printing")
    invs = run_query("SELECT * FROM invoices WHERE shop_id=? ORDER BY id DESC", (st.session_state.auth['shop_id'],), fetch=True)
    
    for _, row in invs.iterrows():
        with st.expander(f"Invoice #{row['id']} - {row['customer_name']} ({row['total_amount']:.2f})"):
            st.write(f"**Date:** {row['date']}")
            st.write(f"**Client:** {row['customer_name']}")
            st.write(f"**Notes:** {row['customer_details']}")
            items = run_query("""SELECT p.name as Product, s.qty, s.sell_price as Price, (s.qty*s.sell_price) as Total 
                                 FROM sale_items s JOIN products p ON s.product_id=p.id WHERE s.invoice_id=?""", (row['id'],), fetch=True)
            st.table(items)
            st.button("🖨️ Open Print View", key=f"p_{row['id']}")

def page_inventory_management():
    st.header("📦 Inventory & Stock Control")
    if st.session_state.auth['role'] == "Administrator":
        with st.form("add_stock"):
            prods = run_query("SELECT id, name FROM products WHERE shop_id=? AND active=1", (st.session_state.auth['shop_id'],), fetch=True)
            sel_p = st.selectbox("Product", prods['name'])
            q = st.number_input("Quantity Received", min_value=1)
            b = st.number_input("Buy Price (per unit)", min_value=0.0)
            if st.form_submit_button("Add to Stock"):
                pid = prods[prods['name']==sel_p].iloc[0]['id']
                run_query("INSERT INTO inventory (shop_id, product_id, date, qty_initial, qty_remaining, buy_price) VALUES (?,?,?,?,?,?)",
                          (st.session_state.auth['shop_id'], pid, str(datetime.now().date()), q, q, b))
                st.success("Stock updated!")
    
    st.subheader("Current Stock Items")
    data = run_query("""SELECT i.id, p.name, i.qty_remaining, i.buy_price, i.date 
                        FROM inventory i JOIN products p ON i.product_id=p.id 
                        WHERE i.shop_id=? AND i.qty_remaining > 0""", (st.session_state.auth['shop_id'],), fetch=True)
    st.dataframe(data, use_container_width=True)

def main():
    init_db()
    if not st.session_state.auth['logged_in']:
        login_page()
        return

    st.sidebar.title(f"🏢 {st.session_state.auth['shop_name']}")
    st.sidebar.write(f"Access: **{st.session_state.auth['role']}**")
    
    menu = ["POS (Cart System)", "Invoices List", "Inventory Control", "Products List"]
    if st.session_state.auth['role'] == "Administrator":
        menu.extend(["Daily Analytics", "Shop Settings"])
    if st.session_state.auth['role'] == "SuperAdmin":
        menu = ["SUPER-ADMIN PANEL"]

    choice = st.sidebar.radio("Navigate", menu)
    
    if st.sidebar.button("Logout"):
        st.session_state.auth = {"logged_in": False}
        st.rerun()

    if choice == "POS (Cart System)": page_pos()
    elif choice == "Invoices List": page_invoices()
    elif choice == "Inventory Control": page_inventory_management()
    elif choice == "Products List":
        st.header("Manage Nomenclature")
        # Same logic as before but with WHERE shop_id = ...
    elif choice == "Shop Settings":
        st.header("Company Branding")
        # Form to update co_name, co_address etc.

if __name__ == "__main__":
    main()
    
