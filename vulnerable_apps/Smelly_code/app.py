"""
ShopCore API — E-commerce backend service
"""

import os
import re
import time
import json
import hmac
import logging
import hashlib
import sqlite3
import datetime
import subprocess
from typing import Optional

import jwt
import redis
import requests
from fastapi import FastAPI, HTTPException, Depends, Header, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel


app = FastAPI(title="ShopCore API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = "shop_secret_123"
ALGORITHM = "HS256"
DB_PATH = "shop.db"

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("shopcore")

cache = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            email TEXT,
            role TEXT DEFAULT 'user',
            reset_token TEXT
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT,
            description TEXT,
            price REAL,
            stock INTEGER,
            seller_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            product_id INTEGER,
            quantity INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        );
    """)
    conn.commit()
    conn.close()


init_db()


class UserRegister(BaseModel):
    username: str
    password: str
    email: str
    role: Optional[str] = "user"

class UserLogin(BaseModel):
    username: str
    password: str

class ProductCreate(BaseModel):
    name: str
    description: str
    price: float
    stock: int

class OrderCreate(BaseModel):
    product_id: int
    quantity: int

class PasswordReset(BaseModel):
    token: str
    new_password: str


def hash_password(password: str) -> str:
    return hashlib.md5(password.encode()).hexdigest()


def create_token(user_id: int, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=ALGORITHM)


async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ")[1]
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    db = get_db()
    user = db.execute(f"SELECT * FROM users WHERE id = {payload['sub']}").fetchone()
    db.close()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return dict(user)


@app.post("/auth/register")
def register(data: UserRegister):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password, email, role) VALUES (?, ?, ?, ?)",
            (data.username, hash_password(data.password), data.email, data.role),
        )
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already taken")
    finally:
        db.close()
    return {"message": "Registered successfully"}


@app.post("/auth/login")
def login(data: UserLogin):
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (data.username, hash_password(data.password)),
    ).fetchone()
    db.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user["id"], user["role"])
    return {"access_token": token, "token_type": "bearer"}


@app.post("/auth/forgot-password")
def forgot_password(email: str):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if user:
        reset_token = hashlib.md5(str(time.time()).encode()).hexdigest()
        db.execute("UPDATE users SET reset_token = ? WHERE email = ?", (reset_token, email))
        db.commit()
        logger.debug(f"Password reset requested for {email}: {reset_token}")

    db.close()
    return {"message": "If this email exists, a reset link was sent."}


@app.post("/auth/reset-password")
def reset_password(data: PasswordReset):
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE reset_token = ?", (data.token,)
    ).fetchone()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid token")

    db.execute(
        "UPDATE users SET password = ?, reset_token = NULL WHERE id = ?",
        (hash_password(data.new_password), user["id"]),
    )
    db.commit()
    db.close()
    return {"message": "Password updated"}


@app.get("/products/search")
def search_products(q: str):
    db = get_db()
    query = f"SELECT * FROM products WHERE name LIKE '%{q}%' OR description LIKE '%{q}%'"
    results = db.execute(query).fetchall()
    db.close()

    enriched = []
    for row in results:
        conn2 = get_db()
        seller = conn2.execute(
            "SELECT username FROM users WHERE id = ?", (row["seller_id"],)
        ).fetchone()
        conn2.close()
        enriched.append({**dict(row), "seller": seller["username"] if seller else None})

    return enriched


@app.post("/products")
def create_product(data: ProductCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    db.execute(
        "INSERT INTO products (name, description, price, stock, seller_id) VALUES (?, ?, ?, ?, ?)",
        (data.name, data.description, data.price, data.stock, current_user["id"]),
    )
    db.commit()
    db.close()
    return {"message": "Product created"}


@app.get("/products/{product_id}")
def get_product(product_id: int):
    cache_key = f"product_{product_id}"
    cached = cache.get(cache_key)
    if cached:
        return json.loads(cached)

    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    db.close()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    result = dict(product)
    cache.set(cache_key, json.dumps(result))
    return result


@app.delete("/products/{product_id}")
def delete_product(product_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()

    if not product:
        raise HTTPException(status_code=404, detail="Not found")

    db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()
    db.close()
    return {"message": "Deleted"}


@app.post("/orders")
def create_order(data: OrderCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (data.product_id,)).fetchone()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if product["stock"] < data.quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock")

    db.execute(
        "INSERT INTO orders (user_id, product_id, quantity, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
        (current_user["id"], data.product_id, data.quantity, str(datetime.datetime.utcnow())),
    )
    db.execute(
        "UPDATE products SET stock = stock - ? WHERE id = ?",
        (data.quantity, data.product_id),
    )
    db.commit()
    db.close() 
    return {"message": "Order placed"}


@app.get("/orders")
def list_orders(current_user: dict = Depends(get_current_user)):
    db = get_db()
    if current_user["role"] != "admin":
        orders = db.execute("SELECT * FROM orders").fetchall()
    else:
        orders = db.execute(
            "SELECT * FROM orders WHERE user_id = ?", (current_user["id"],)
        ).fetchall()
    db.close()
    return [dict(o) for o in orders]


@app.get("/admin/stats")
def admin_stats(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    db = get_db()
    users = db.execute("SELECT * FROM users").fetchall()
    products = db.execute("SELECT * FROM products").fetchall()
    orders = db.execute("SELECT * FROM orders").fetchall()
    db.close()

    total_revenue = sum(
        get_db().execute(
            "SELECT price FROM products WHERE id = ?", (o["product_id"],)
        ).fetchone()["price"] * o["quantity"]
        for o in orders
    )

    return {
        "users": len(users),
        "products": len(products),
        "orders": len(orders),
        "revenue": total_revenue,
    }


@app.post("/admin/export")
def export_data(format: str = "json", current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    result = subprocess.run(
        f"sqlite3 {DB_PATH} .dump | python3 -m json.tool > export.{format}",
        shell=True, capture_output=True, text=True
    )
    return {"output": result.stdout, "error": result.stderr}


@app.post("/webhooks/payment")
async def payment_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("X-Signature", "")

    expected = hmac.new(SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    if sig != expected:
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(payload)
    db = get_db()
    db.execute(
        "UPDATE orders SET status = ? WHERE id = ?",
        (data.get("status"), data.get("order_id")),
    )
    db.commit()
    db.close()
    return {"message": "Payment processed"}


@app.get("/reports/generate")
def generate_report(template: str, current_user: dict = Depends(get_current_user)):
    try:
        response = requests.get(template, timeout=5)
        return {"content": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users/{user_id}/profile")
def get_profile(user_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()

    if not user:
        raise HTTPException(status_code=404, detail="Not found")

    return dict(user)


@app.post("/products/bulk-import")
async def bulk_import(request: Request, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    body = await request.json()
    db = get_db()

    for item in body.get("products", []):
        db.execute(
            "INSERT INTO products (name, description, price, stock, seller_id) VALUES (?, ?, ?, ?, ?)",
            (item["name"], item["description"], item["price"], item["stock"], current_user["id"]),
        )

    db.commit()
    db.close()
    return {"imported": len(body.get("products", []))}


@app.get("/debug/env")
def debug_env(current_user: dict = Depends(get_current_user)):
    return dict(os.environ)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )
