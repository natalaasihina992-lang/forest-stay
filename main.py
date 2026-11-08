import os
import hmac
import hashlib
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import quote

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Forest Stay")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")


def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "forest_stay"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        client_encoding="UTF8"
    )


def query(sql, params=(), one=False, commit=False):
    conn = get_connection()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            result = cur.fetchone() if one else cur.fetchall()
            if commit:
                conn.commit()
            return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS houses (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(160) NOT NULL,
                    location VARCHAR(160) NOT NULL,
                    description TEXT NOT NULL,
                    price INTEGER NOT NULL CHECK (price > 0),
                    guests INTEGER NOT NULL CHECK (guests > 0),
                    image_url TEXT NOT NULL,
                    amenities TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS bookings (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    house_id INTEGER NOT NULL REFERENCES houses(id) ON DELETE RESTRICT,
                    check_in DATE NOT NULL,
                    check_out DATE NOT NULL,
                    guests INTEGER NOT NULL CHECK (guests > 0),
                    total_price INTEGER NOT NULL,
                    status VARCHAR(30) NOT NULL DEFAULT 'confirmed',
                    payment_status VARCHAR(30) NOT NULL DEFAULT 'paid_demo',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK (check_out > check_in)
                );
            """)
            cur.execute("SELECT COUNT(*) FROM houses")
            count = cur.fetchone()[0]
            if count == 0:
                houses = [
                    ("Домик среди сосен", "Московская область", "Уютный деревянный домик среди высоких сосен. Панорамные окна, терраса и всё необходимое для спокойного отдыха на природе.", 6500, 4, "https://images.unsplash.com/photo-1449158743715-0a90sn7f3a1?auto=format&fit=crop&w=1200&q=85", "Wi-Fi,Камин,Терраса,Кухня"),
                    ("Тихий берег", "Тверская область", "Небольшой дом у воды для выходных вдали от городской суеты. Можно наслаждаться видом на озеро и готовить на мангале.", 7900, 3, "https://images.unsplash.com/photo-1470770841072-f978cf4d019e?auto=format&fit=crop&w=1200&q=85", "Озеро рядом,Мангал,Кухня,Парковка"),
                    ("Лесная резиденция", "Калужская область", "Просторный современный дом с большой гостиной и видом на лес. Подойдёт для отдыха небольшой компанией или семьёй.", 9200, 6, "https://images.unsplash.com/photo-1449158743715-0a90sn7f3a1?auto=format&fit=crop&w=1200&q=85", "Wi-Fi,Камин,Баня,Терраса"),
                    ("Маленький домик", "Владимирская область", "Компактный домик с тёплым интерьером и собственной верандой. Идеальное место, чтобы перезагрузиться на пару дней.", 4900, 2, "https://images.unsplash.com/photo-1449158743715-0a90sn7f3a1?auto=format&fit=crop&w=1200&q=85", "Терраса,Кухня,Парковка")
                ]
                cur.executemany("""
                    INSERT INTO houses (title, location, description, price, guests, image_url, amenities)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, houses)
        conn.commit()
    finally:
        conn.close()


@app.on_event("startup")
def startup():
    init_db()


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000)
    return salt + "$" + digest.hex()


def check_password(password, stored):
    try:
        salt, old_hash = stored.split("$", 1)
        new_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()
        return hmac.compare_digest(new_hash, old_hash)
    except ValueError:
        return False


def make_token(user_id):
    data = str(user_id)
    signature = hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()
    return data + "." + signature


def current_user(request):
    token = request.cookies.get("forest_token")
    if not token or "." not in token:
        return None
    user_id, signature = token.split(".", 1)
    expected = hmac.new(SECRET_KEY.encode(), user_id.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    if not user_id.isdigit():
        return None
    return query("SELECT id, name, email FROM users WHERE id = %s", (int(user_id),), one=True)


def page(request, template, **kwargs):
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"user": current_user(request), **kwargs}
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    houses = query("SELECT * FROM houses ORDER BY id LIMIT 3")
    return page(request, "index.html", houses=houses)


# === ИСПРАВЛЕННЫЙ КАТАЛОГ ===
@app.get("/houses", response_class=HTMLResponse)
def catalog(request: Request, q: str = "", guests: int = 1, max_price: str = ""):
    sql = "SELECT * FROM houses WHERE guests >= %s"
    params = [max(1, guests)]
    
    if q.strip():
        sql += " AND (title ILIKE %s OR location ILIKE %s)"
        params.extend([f"%{q.strip()}%", f"%{q.strip()}%"])
        
    # Проверяем, что строка не пустая и состоит из цифр
    if max_price and max_price.isdigit():
        sql += " AND price <= %s"
        params.append(int(max_price))
        
    sql += " ORDER BY price"
    houses = query(sql, tuple(params))
    return page(request, "catalog.html", houses=houses, q=q, guests=guests, max_price=max_price)


@app.get("/house/{house_id}", response_class=HTMLResponse)
def house_detail(request: Request, house_id: int):
    house = query("SELECT * FROM houses WHERE id = %s", (house_id,), one=True)
    if not house:
        raise HTTPException(status_code=404, detail="Домик не найден")
    return page(request, "house.html", house=house, today=date.today().isoformat())


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return page(request, "auth.html", mode="register", error=None)


@app.post("/register")
def register(name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    name, email = name.strip(), email.strip().lower()
    if len(name) < 2 or len(password) < 6:
        return RedirectResponse("/register?error=" + quote("Имя слишком короткое или пароль меньше 6 символов"), status_code=303)
    try:
        user = query(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (name, email, hash_password(password)), one=True, commit=True
        )
    except psycopg.errors.UniqueViolation:
        return RedirectResponse("/register?error=" + quote("Пользователь с такой почтой уже существует"), status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("forest_token", make_token(user["id"]), httponly=True, samesite="lax", max_age=60*60*24*7)
    return response


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return page(request, "auth.html", mode="login", error=request.query_params.get("error"))


@app.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    user = query("SELECT * FROM users WHERE email = %s", (email.strip().lower(),), one=True)
    if not user or not check_password(password, user["password_hash"]):
        return RedirectResponse("/login?error=" + quote("Неверная почта или пароль"), status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("forest_token", make_token(user["id"]), httponly=True, samesite="lax", max_age=60*60*24*7)
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("forest_token")
    return response


@app.post("/book/{house_id}")
def create_booking(
    request: Request,
    house_id: int,
    check_in: str = Form(...),
    check_out: str = Form(...),
    guests: int = Form(...)
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login?error=" + quote("Сначала войдите в аккаунт"), status_code=303)

    try:
        start = date.fromisoformat(check_in)
        end = date.fromisoformat(check_out)
    except ValueError:
        return RedirectResponse(f"/house/{house_id}?error=" + quote("Проверьте даты"), status_code=303)

    house = query("SELECT * FROM houses WHERE id = %s", (house_id,), one=True)
    if not house:
        raise HTTPException(status_code=404, detail="Домик не найден")
    if start < date.today() or end <= start:
        return RedirectResponse(f"/house/{house_id}?error=" + quote("Некорректные даты бронирования"), status_code=303)
    if guests < 1 or guests > house["guests"]:
        return RedirectResponse(f"/house/{house_id}?error=" + quote("Недопустимое количество гостей"), status_code=303)

    conn = get_connection()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, price FROM houses WHERE id = %s FOR UPDATE", (house_id,))
            locked_house = cur.fetchone()
            if not locked_house:
                raise HTTPException(status_code=404, detail="Домик не найден")

            cur.execute("""
                SELECT id FROM bookings
                WHERE house_id = %s AND status = 'confirmed'
                AND check_in < %s AND check_out > %s
            """, (house_id, end, start))
            conflict = cur.fetchone()
            if conflict:
                conn.rollback()
                return RedirectResponse(
                    f"/house/{house_id}?error=" + quote("На эти даты домик уже занят"),
                    status_code=303
                )

            nights = (end - start).days
            total = nights * locked_house["price"]
            cur.execute("""
                INSERT INTO bookings (user_id, house_id, check_in, check_out, guests, total_price, status, payment_status)
                VALUES (%s, %s, %s, %s, %s, %s, 'confirmed', 'paid_demo')
            """, (user["id"], house_id, start, end, guests, total))
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return RedirectResponse("/profile?success=" + quote("Бронирование оформлено! Демонстрационная оплата прошла успешно."), status_code=303)


@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    bookings = query("""
        SELECT b.*, h.title, h.location, h.image_url
        FROM bookings b JOIN houses h ON h.id = b.house_id
        WHERE b.user_id = %s ORDER BY b.created_at DESC
    """, (user["id"],))
    return page(request, "profile.html", bookings=bookings, success=request.query_params.get("success"))


@app.post("/booking/{booking_id}/cancel")
def cancel_booking(request: Request, booking_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    query("""
        UPDATE bookings SET status = 'cancelled', payment_status = 'refunded_demo'
        WHERE id = %s AND user_id = %s AND status = 'confirmed'
    """, (booking_id, user["id"]), commit=True)
    return RedirectResponse("/profile?success=" + quote("Бронирование отменено."), status_code=303)


@app.get("/health")
def health():
    query("SELECT 1", one=True)
    return {"status": "ok", "database": "connected"}