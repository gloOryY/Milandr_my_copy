# main.py
import sys
import os

try:
    from flet import *
    import cv2
    import torch
    import numpy
    import serial
    import openpyxl
    import PIL
    import ultralytics
    # import gxipy as gx
    import hid

    from project.application.build import building_application
    from project.application.addition.auth_view import AuthView
    from project.application.addition.user_profile_widget import add_user_profile_overlay
    from project.application.addition.logger import logger

except ImportError as e:
    print(f"❌ Отсутствует зависимость: {e}")
    print("📦 Устанавливаю все зависимости...")

    from requirements_check import install_requirements

    if install_requirements():
        print("✅ Зависимости установлены. Перезапускаю приложение...")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        print("❌ Ошибка установки зависимостей")
        sys.exit(1)


# === АВТО-ВХОД (для отладки/автоматизации) ===
AUTO_LOGIN_ENABLED = True
AUTO_LOGIN_USERNAME = "admin" # oper / admin

# Данные пользователя, которые подставляются при авто-входе.
# ВАЖНО: структура должна совпадать с той, что возвращает AuthView
# при успешной авторизации. Проверь ключи в auth_view.py.
AUTO_LOGIN_USER_DATA = {
    "username": AUTO_LOGIN_USERNAME,
    "full_name": "Администратор",
    "role": "admin", # operator / admin
    "user_id": 1,
}


def start_app(page: Page):
    page.title = "Управление системой"
    page.theme_mode = ThemeMode.DARK
    page.padding = 0

    def show_auth_screen():
        page.overlay.clear()
        page.clean()
        auth = AuthView(page=page, on_success_login=on_login_success)
        page.add(auth.build_view())
        page.update()

    def on_login_success(user_data: dict):
        logger.info(f"Вход выполнен: {user_data['full_name']} ({user_data['role']})")
        page.session.set("current_user", user_data)
        page.clean()

        try:
            building_application(page, user_data)
        except TypeError:
            building_application(page)

        add_user_profile_overlay(
            page=page,
            user_data=user_data,
            on_logout=show_auth_screen
        )
        page.update()

    # === АВТО-ВХОД ===
    if AUTO_LOGIN_ENABLED:
        logger.info(f"[AUTO-LOGIN] Автоматический вход: {AUTO_LOGIN_USERNAME}")
        on_login_success(AUTO_LOGIN_USER_DATA)
    else:
        show_auth_screen()


if __name__ == "__main__":
    app(target=start_app, assets_dir="assets")