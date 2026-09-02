import sqlite3
import hashlib
import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# База данных создается в корне проекта рядом с main.py
DB_PATH = Path(__file__).resolve().parents[3] / "accounts.sqlite3"


def _get_connection():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Инициализирует таблицу пользователей, если она не существует."""
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,          -- 'admin' или 'operator'
                full_name TEXT NOT NULL,     -- ФИО
                birth_date TEXT NOT NULL,    -- Формат: ДД-ММ-ГГГГ
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def _hash_password(password: str) -> str:
    """Хэширование пароля методом SHA-256."""
    return hashlib.sha256(password.strip().encode('utf-8')).hexdigest()


def _validate_birth_date(date_str: str) -> bool:
    """Проверка формата ДД-ММ-ГГГГ и корректности даты."""
    try:
        parts = date_str.strip().split('-')
        if len(parts) != 3 or len(parts[0]) != 2 or len(parts[1]) != 2 or len(parts[2]) != 4:
            return False
        day, month, year = map(int, parts)
        datetime.date(year, month, day)
        return True
    except (ValueError, TypeError):
        return False


def register_user(username: str, password: str, role: str, full_name: str, birth_date: str) -> Tuple[bool, str]:
    """
    Регистрация нового пользователя.
    role: 'admin' | 'operator'
    """
    username = username.strip()
    full_name = full_name.strip()
    birth_date = birth_date.strip()

    if not username or not password or not full_name or not birth_date:
        return False, "Все поля обязательны для заполнения!"

    if len(username) < 3:
        return False, "Логин должен содержать минимум 3 символа!"

    if len(password) < 4:
        return False, "Пароль должен содержать минимум 4 символа!"

    if not _validate_birth_date(birth_date):
        return False, "Неверный формат даты рождения! Используйте формат ДД-ММ-ГГГГ (например, 15-05-1990)."

    pwd_hash = _hash_password(password)

    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (username, password_hash, role, full_name, birth_date)
                VALUES (?, ?, ?, ?, ?)
            """, (username, pwd_hash, role, full_name, birth_date))
            conn.commit()
            return True, f"Аккаунт '{username}' успешно создан!"
    except sqlite3.IntegrityError:
        return False, "Пользователь с таким логином уже существует!"
    except Exception as e:
        return False, f"Ошибка базы данных: {str(e)}"


def authenticate_user(username: str, password: str, expected_role: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Авторизация пользователя по логину, паролю и выбранной роли.
    """
    username = username.strip()
    pwd_hash = _hash_password(password)

    if not username or not password:
        return False, None, "Введите логин и пароль!"

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, role, full_name, birth_date, created_at
            FROM users 
            WHERE username = ? AND password_hash = ?
        """, (username, pwd_hash))
        user = cursor.fetchone()

        if not user:
            return False, None, "Неверный логин или пароль!"

        user_dict = dict(user)
        if user_dict['role'] != expected_role:
            role_ru = "Администратор" if user_dict['role'] == "admin" else "Оператор"
            return False, None, f"У данного аккаунта роль '{role_ru}'. Выберите правильный тип входа!"

        return True, user_dict, "Успешный вход в систему"