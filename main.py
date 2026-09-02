# main.py
from project.application.build import building_application
from requirements_check import install_requirements

try:
    from flet import *
    import cv2
    import torch
    import numpy
    import serial
    import openpyxl
    import PIL
    import ultralytics
except ImportError:
    install_requirements()
    from flet import *

from project.application.addition.auth_view import AuthView
from project.application.addition.user_profile_widget import add_user_profile_overlay
from project.application.addition.logger import logger


def start_app(page: Page):
    """
    Главная точка входа в приложение.
    """
    page.title = "Управление системой"
    page.theme_mode = ThemeMode.DARK
    page.padding = 0

    def show_auth_screen():
        """Очищает экран и показывает окно авторизации/регистрации."""
        page.overlay.clear()
        page.clean()
        auth = AuthView(page=page, on_success_login=on_login_success)
        page.add(auth.build_view())
        page.update()

    def on_login_success(user_data: dict):
        """Вызывается после успешного входа или регистрации."""
        logger.info(f"Вход выполнен: {user_data['full_name']} ({user_data['role']})")
        page.session.set("current_user", user_data)
        page.clean()

        # 1. Запуск построения основных слоев интерфейса
        try:
            building_application(page, user_data)
        except TypeError:
            building_application(page)

        # 2. Добавление поверх всех экранов плавающей панели аккаунта
        add_user_profile_overlay(
            page=page,
            user_data=user_data,
            on_logout=show_auth_screen
        )
        page.update()

    # Стартуем с экрана авторизации
    show_auth_screen()


if __name__ == "__main__":
    app(target=start_app, assets_dir="assets")