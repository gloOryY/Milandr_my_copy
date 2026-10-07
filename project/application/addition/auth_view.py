# project/application/addition/auth_view.py
import flet as ft
from project.application.data_work.accounts_db import init_db, authenticate_user, register_user


class AuthView:
    def __init__(self, page: ft.Page, on_success_login):
        self.page = page
        self.on_success_login = on_success_login
        init_db()

        # Поля входа
        self.login_role = ft.RadioGroup(
            content=ft.Row(
                controls=[
                    ft.Radio(value="operator", label="Войти как оператор"),
                    ft.Radio(value="admin", label="Войти как администратор"),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            value="operator"
        )
        self.login_user = ft.TextField(
            label="Логин",
            prefix_icon=ft.icons.PERSON_OUTLINE,
            width=360,
            autofocus=True
        )
        self.login_pwd = ft.TextField(
            label="Пароль",
            password=True,
            can_reveal_password=True,
            prefix_icon=ft.icons.LOCK_OUTLINE,
            width=360,
            on_submit=lambda _: self._handle_login()
        )
        self.login_status = ft.Text(value="", color=ft.colors.RED_400, size=13, weight=ft.FontWeight.W_500)

        self.reg_role_label = ft.Text(
            "Выберите роль для нового аккаунта:",
            size=16,
            weight=ft.FontWeight.W_500,
        )
        self.reg_role = ft.RadioGroup(
            content=ft.Row(
                controls=[
                    ft.Radio(value="operator", label="Оператор"),
                    ft.Radio(value="admin", label="Администратор"),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            value="operator"
        )
        self.reg_fio = ft.TextField(
            label="ФИО",
            hint_text="Иванов Иван Иванович",
            prefix_icon=ft.icons.BADGE_OUTLINED,
            width=360
        )
        self.reg_birth = ft.TextField(
            label="Дата рождения (ДД-ММ-ГГГГ)",
            hint_text="Например: 12-04-1995",
            prefix_icon=ft.icons.CALENDAR_TODAY_OUTLINED,
            width=360
        )
        self.reg_user = ft.TextField(
            label="Логин",
            prefix_icon=ft.icons.ACCOUNT_CIRCLE_OUTLINED,
            width=360
        )
        self.reg_pwd = ft.TextField(
            label="Пароль",
            password=True,
            can_reveal_password=True,
            prefix_icon=ft.icons.LOCK_OUTLINE,
            width=360
        )
        self.reg_status = ft.Text(value="", color=ft.colors.RED_400, size=13, weight=ft.FontWeight.W_500)

    def _handle_login(self):
        username = self.login_user.value or ""
        pwd = self.login_pwd.value or ""
        role = self.login_role.value

        success, user_data, msg = authenticate_user(username, pwd, role)
        if success:
            self.login_status.value = ""
            self.page.update()
            self.on_success_login(user_data)
        else:
            self.login_status.color = ft.colors.RED_400
            self.login_status.value = msg
            self.page.update()

    def _handle_register(self, tabs_control: ft.Tabs):
        fio = self.reg_fio.value or ""
        birth = self.reg_birth.value or ""
        username = self.reg_user.value or ""
        pwd = self.reg_pwd.value or ""
        role = self.reg_role.value

        success, msg = register_user(username, pwd, role, fio, birth)
        if success:
            self.reg_status.color = ft.colors.GREEN_400
            self.reg_status.value = msg
            # Подставляем логин во вкладку входа и переключаем
            self.login_user.value = username
            self.login_pwd.value = ""
            self.login_role.value = role
            self.login_status.color = ft.colors.GREEN_400
            self.login_status.value = "Регистрация успешна! Введите пароль для входа."
            tabs_control.selected_index = 0
            self.page.update()
        else:
            self.reg_status.color = ft.colors.RED_400
            self.reg_status.value = msg
            self.page.update()

    def build_view(self) -> ft.Container:
        """Возвращает центрированный контейнер с карточкой авторизации."""
        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=250,
            tabs=[
                ft.Tab(
                    text="Вход в систему",
                    icon=ft.icons.LOGIN,
                    content=ft.Container(
                        padding=20,
                        content=ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=14,
                            tight=True,
                            controls=[
                                self.login_role,
                                self.login_user,
                                self.login_pwd,
                                self.login_status,
                                ft.ElevatedButton(
                                    text="Войти в систему",
                                    icon=ft.icons.CHECK_CIRCLE_OUTLINE,
                                    width=360,
                                    height=45,
                                    style=ft.ButtonStyle(
                                        bgcolor=ft.colors.BLUE_700,
                                        color=ft.colors.WHITE,
                                        shape=ft.RoundedRectangleBorder(radius=8)
                                    ),
                                    on_click=lambda _: self._handle_login()
                                )
                            ]
                        )
                    )
                ),
                ft.Tab(
                    text="Регистрация",
                    icon=ft.icons.PERSON_ADD_ALT_1,
                    content=ft.Container(
                        padding=20,
                        content=ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=12,
                            tight=True,
                            controls=[
                                self.reg_role_label,
                                self.reg_role,
                                self.reg_fio,
                                self.reg_birth,
                                self.reg_user,
                                self.reg_pwd,
                                self.reg_status,
                                ft.ElevatedButton(
                                    text="Создать аккаунт",
                                    icon=ft.icons.SAVE_OUTLINED,
                                    width=360,
                                    height=45,
                                    style=ft.ButtonStyle(
                                        bgcolor=ft.colors.TEAL_700,
                                        color=ft.colors.WHITE,
                                        shape=ft.RoundedRectangleBorder(radius=8)
                                    ),
                                    on_click=lambda _: self._handle_register(tabs)
                                )
                            ]
                        )
                    )
                )
            ]
        )

        card = ft.Card(
            elevation=8,
            content=ft.Container(
                width=450,
                padding=20,
                border_radius=12,
                content=ft.Column(
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            controls=[
                                ft.Icon(ft.icons.SECURITY, size=32, color=ft.colors.BLUE_400),
                                ft.Text("Система контроля кристаллов", size=20, weight=ft.FontWeight.BOLD),
                            ]
                        ),
                        ft.Divider(height=20, color=ft.colors.OUTLINE_VARIANT),
                        tabs
                    ]
                )
            )
        )

        return ft.Container(
            content=card,
            alignment=ft.alignment.center,
            expand=True
        )
