import json
import sqlite3
from pathlib import Path
from flet import *

from project.configuration.worker import read_from_json, write_to_json


def get_delegated_operators() -> set[str]:
    """Возвращает множество всех идентификаторов операторов, которым делегированы права."""
    try:
        data = read_from_json("project/configuration/delegation.json", "delegated_users")
        if isinstance(data, list):
            return {str(x).strip().lower() for x in data if x is not None}
        return set()
    except Exception:
        return set()


def save_delegated_operators(delegated_set: set[str]):
    """Сохраняет делегированные права в конфигурационный файл."""
    try:
        write_to_json(
            "project/configuration/delegation.json",
            "delegated_users",
            list(delegated_set)
        )
    except Exception as e:
        print(f"Ошибка сохранения делегирования: {e}")


def is_user_delegated(user_data: dict) -> bool:
    """
    Проверяет, делегированы ли права администратора данному пользователю
    по любому из его идентификаторов (username, login, full_name, name, id).
    """
    if not user_data or not isinstance(user_data, dict):
        return False
    delegated = get_delegated_operators()
    if not delegated:
        return False

    for key in ["username", "login", "full_name", "name", "id"]:
        val = user_data.get(key)
        if val is not None and str(val).strip():
            val_clean = str(val).strip().lower()
            if val_clean in delegated:
                return True
    return False


def get_all_registered_operators() -> list[dict]:
    """
    Загружает список всех зарегистрированных пользователей из SQLite-баз данных
    или JSON-файлов проекта.
    """
    operators = []

    current_dir = Path(__file__).parent.absolute()
    project_root = current_dir.parent.parent.parent

    db_files = list(project_root.rglob("*.db")) + list(project_root.rglob("*.sqlite3"))
    possible_db_paths = [
                            project_root / "project/database/auth.db",
                            project_root / "project/database/users.db",
                            project_root / "project/database/database.db",
                            project_root / "project/configuration/auth.db",
                            project_root / "project/configuration/users.db",
                            project_root / "project/configuration/database.db",
                            project_root / "database.db",
                            project_root / "users.db",
                            project_root / "auth.db",
                            project_root / "accounts.sqlite3",
                        ] + db_files

    # Убираем дубликаты, сохраняя порядок
    seen = set()
    unique_paths = []
    for p in possible_db_paths:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)

    for db_path in unique_paths:
        if db_path.exists() and db_path.is_file():
            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [row[0] for row in cursor.fetchall()]
                for table in ["users", "accounts", "user", "auth", "operators"]:
                    if table in tables:
                        cursor.execute(f"PRAGMA table_info({table});")
                        cols = [c[1].lower() for c in cursor.fetchall()]
                        cursor.execute(f"SELECT * FROM {table};")
                        for r in cursor.fetchall():
                            user_dict = dict(zip(cols, r))
                            if "login" in user_dict and "username" not in user_dict:
                                user_dict["username"] = user_dict["login"]
                            if "name" in user_dict and "full_name" not in user_dict:
                                user_dict["full_name"] = user_dict["name"]
                            if user_dict.get("username") or user_dict.get("full_name"):
                                operators.append(user_dict)
                conn.close()
                if operators:
                    return operators
            except Exception:
                pass

    # 2. Поиск в JSON файлах (аналогично)
    json_paths = [
        project_root / "project/configuration/users.json",
        project_root / "project/configuration/auth.json",
        project_root / "configuration/users.json",
        project_root / "project/configuration/accounts.json",
        project_root / "users.json",
    ]

    for p in json_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for u in data:
                            if isinstance(u, dict):
                                operators.append(u)
                    elif isinstance(data, dict):
                        if "users" in data and isinstance(data["users"], list):
                            for u in data["users"]:
                                if isinstance(u, dict):
                                    operators.append(u)
                        else:
                            for k, v in data.items():
                                if isinstance(v, dict):
                                    v_copy = v.copy()
                                    if "username" not in v_copy:
                                        v_copy["username"] = k
                                    operators.append(v_copy)
                if operators:
                    return operators
            except Exception:
                pass

    return operators


def add_user_profile_overlay(page: Page, user_data: dict, on_logout, on_role_update=None):
    """
    Панель профиля с возможностью персонального делегирования прав администратора операторам.
    """
    full_name = user_data.get("full_name") or user_data.get("name") or "Пользователь"
    username = user_data.get("username") or user_data.get("login") or ""
    role_raw = user_data.get("role", "operator")
    birth_date = user_data.get("birth_date", "")

    is_current_delegated = is_user_delegated(user_data)

    if role_raw == "admin":
        role_title = "Администратор"
        role_color = Colors.BLUE_400
    elif is_current_delegated:
        role_title = "Оператор (Полный доступ)"
        role_color = Colors.AMBER_500
    else:
        role_title = "Оператор"
        role_color = Colors.TEAL_400

    BADGE_WIDTH = 295
    HANDLE_WIDTH = 38

    def get_screen_w():
        return page.window_width or page.width or 1920

    def get_screen_h():
        return page.window_height or page.height or 1080

    state = {
        "expanded": False,
        "is_tucked": False,
    }

    initials = "".join([part[0].upper() for part in full_name.split()[:2]]) if full_name else "U"

    panel_container = Container(
        top=70,
        left=get_screen_w() - BADGE_WIDTH - 20,
        animate_position=150,
    )

    def snap_to_edge(tuck: bool = False):
        screen_w = get_screen_w()
        if tuck:
            state["is_tucked"] = True
            panel_container.left = screen_w - HANDLE_WIDTH
        else:
            state["is_tucked"] = False
            panel_container.left = max(10, screen_w - BADGE_WIDTH - 20)
        panel_container.update()

    def on_pan_update(e: DragUpdateEvent):
        screen_w = get_screen_w()
        screen_h = get_screen_h()
        cur_top = panel_container.top if panel_container.top is not None else 70
        cur_left = panel_container.left if panel_container.left is not None else (screen_w - BADGE_WIDTH - 20)
        dx = getattr(e, 'delta_x', 0)
        dy = getattr(e, 'delta_y', 0)
        new_left = max(10, min(screen_w - HANDLE_WIDTH, cur_left + dx))
        new_top = max(45, min(screen_h - 120, cur_top + dy))
        state["is_tucked"] = (new_left >= screen_w - (BADGE_WIDTH // 2))
        panel_container.left = new_left
        panel_container.top = new_top
        panel_container.update()

    def on_pan_end(_e):
        screen_w = get_screen_w()
        cur_left = panel_container.left or (screen_w - BADGE_WIDTH - 20)
        if cur_left > (screen_w - BADGE_WIDTH + 40):
            snap_to_edge(tuck=True)

    def on_handle_click(_e):
        if state["is_tucked"]:
            snap_to_edge(tuck=False)
        else:
            snap_to_edge(tuck=True)

    def toggle_expand(_e):
        if state["is_tucked"]:
            snap_to_edge(tuck=False)
        state["expanded"] = not state["expanded"]
        render_content()
        panel_container.update()

    def handle_logout_click(_e):
        if panel_container in page.overlay:
            page.overlay.remove(panel_container)
        on_logout()

    def on_toggle_operator_delegation(op_dict: dict, is_checked: bool):
        current_delegated = get_delegated_operators()

        # Собираем все токены оператора для надежного сопоставления
        tokens = set()
        for k in ["username", "login", "full_name", "name", "id"]:
            v = op_dict.get(k)
            if v is not None and str(v).strip():
                tokens.add(str(v).strip().lower())

        if is_checked:
            current_delegated.update(tokens)
        else:
            current_delegated.difference_update(tokens)

        save_delegated_operators(current_delegated)

        display_name = op_dict.get("full_name") or op_dict.get("username") or "Оператор"
        status = "предоставлены" if is_checked else "отозваны"
        snack = SnackBar(
            content=Text(f"Права для '{display_name}' {status}!", color=Colors.WHITE),
            bgcolor=Colors.AMBER_700 if is_checked else Colors.GREY_800,
            duration=2500,
        )
        page.overlay.append(snack)
        snack.open = True
        page.update()

        if on_role_update:
            on_role_update(current_delegated)

    def render_content():
        if not state["expanded"]:
            handle_icon = Container(
                content=Icon(Icons.DRAG_INDICATOR, size=18, color=Colors.GREY_400),
                width=24,
                height=34,
                alignment=alignment.center,
                tooltip="Потяните или нажмите, чтобы скрыть/показать",
                on_click=on_handle_click,
            )

            collapsed_row = Row(
                controls=[
                    handle_icon,
                    CircleAvatar(
                        content=Text(initials, size=12, weight=FontWeight.BOLD, color=Colors.WHITE),
                        bgcolor=role_color,
                        radius=14,
                    ),
                    Container(
                        content=Text(
                            full_name,
                            size=13,
                            weight=FontWeight.W_500,
                            color=Colors.WHITE,
                            no_wrap=True,
                            overflow=TextOverflow.ELLIPSIS,
                        ),
                        width=170,
                    ),
                    IconButton(
                        icon=Icons.KEYBOARD_ARROW_DOWN,
                        icon_size=18,
                        icon_color=Colors.GREY_300,
                        tooltip="Развернуть профиль",
                        on_click=toggle_expand,
                    )
                ],
                alignment=MainAxisAlignment.START,
                vertical_alignment=CrossAxisAlignment.CENTER,
                spacing=4,
            )

            panel_container.content = GestureDetector(
                on_pan_update=on_pan_update,
                on_pan_end=on_pan_end,
                content=Container(
                    width=BADGE_WIDTH,
                    content=collapsed_row,
                    padding=padding.only(left=4, right=4, top=3, bottom=3),
                    bgcolor="#1e1e1e",
                    border=border.all(1, "#3d3d3d"),
                    border_radius=20,
                    shadow=BoxShadow(
                        blur_radius=8,
                        color=Colors.with_opacity(0.45, Colors.BLACK),
                        offset=Offset(0, 3),
                    )
                )
            )
        else:
            admin_delegation_block = Container()

            if role_raw == "admin":
                all_ops = get_all_registered_operators()
                # Исключаем самого администратора из списка делегирования
                only_operators = [
                    u for u in all_ops
                    if (u.get("role") != "admin") and (u.get("username") != username)
                       and (u.get("full_name") != full_name)
                ]

                operator_checkboxes = []
                for op in only_operators:
                    op_fname = op.get("full_name") or op.get("name") or op.get("username") or "Оператор"
                    is_del = is_user_delegated(op)

                    cb = Checkbox(
                        label=f"{op_fname}",
                        value=is_del,
                        active_color=Colors.AMBER_400,
                        check_color=Colors.BLACK,
                        label_style=TextStyle(size=12, color=Colors.WHITE),
                        on_change=lambda e, operator_data=op: on_toggle_operator_delegation(operator_data, e.control.value),
                    )
                    operator_checkboxes.append(cb)

                list_height = min(130, max(40, len(operator_checkboxes) * 34)) if operator_checkboxes else 40

                admin_delegation_block = Container(
                    content=Column(
                        spacing=6,
                        controls=[
                            Divider(height=1, color=Colors.GREY_700),
                            Row(
                                controls=[
                                    Icon(Icons.ADMIN_PANEL_SETTINGS_OUTLINED, size=18, color=Colors.AMBER_400),
                                    Text("Делегирование прав", size=13, weight=FontWeight.BOLD, color=Colors.WHITE),
                                ],
                                spacing=6,
                            ),
                            Text(
                                "Отметьте операторов для предоставления полного доступа:",
                                size=11,
                                color=Colors.GREY_400,
                            ),
                            Container(
                                content=Column(
                                    controls=operator_checkboxes if operator_checkboxes else [
                                        Text("Операторы не найдены", size=12, color=Colors.GREY_500)
                                    ],
                                    spacing=2,
                                    scroll=ScrollMode.AUTO,
                                ),
                                height=list_height,
                            ),
                        ]
                    ),
                    padding=padding.only(top=4, bottom=4),
                )
            elif is_current_delegated:
                admin_delegation_block = Container(
                    content=Row(
                        controls=[
                            Icon(Icons.VERIFIED_USER_OUTLINED, size=16, color=Colors.AMBER_400),
                            Text("Вам делегированы права администратора", size=11, color=Colors.AMBER_400, weight=FontWeight.W_500),
                        ],
                        spacing=6,
                    ),
                    padding=padding.symmetric(vertical=4),
                )

            expanded_card = Column(
                spacing=10,
                tight=True,
                controls=[
                    Row(
                        controls=[
                            Row(
                                controls=[
                                    Icon(Icons.DRAG_INDICATOR, size=20, color=Colors.GREY_400),
                                    Text("Текущий профиль", size=14, weight=FontWeight.BOLD, color=Colors.GREY_300),
                                ],
                                spacing=4,
                            ),
                            IconButton(
                                icon=Icons.KEYBOARD_ARROW_UP,
                                icon_size=20,
                                icon_color=Colors.GREY_300,
                                tooltip="Свернуть",
                                on_click=toggle_expand,
                            )
                        ],
                        alignment=MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    Divider(height=1, color=Colors.GREY_700),
                    Row(
                        controls=[
                            CircleAvatar(
                                content=Text(initials, size=16, weight=FontWeight.BOLD, color=Colors.WHITE),
                                bgcolor=role_color,
                                radius=20,
                            ),
                            Column(
                                spacing=2,
                                controls=[
                                    Text(
                                        full_name,
                                        size=14,
                                        weight=FontWeight.BOLD,
                                        color=Colors.WHITE,
                                        width=210,
                                        no_wrap=True,
                                        overflow=TextOverflow.ELLIPSIS,
                                    ),
                                    Container(
                                        content=Text(role_title, size=10, weight=FontWeight.W_600, color=Colors.WHITE),
                                        bgcolor=role_color,
                                        padding=padding.symmetric(horizontal=6, vertical=2),
                                        border_radius=6,
                                    )
                                ]
                            )
                        ],
                        spacing=10,
                    ),
                    Column(
                        spacing=3,
                        controls=[
                            Text(f"Логин: {username}", size=12, color=Colors.GREY_400),
                            Text(f"Дата рожд.: {birth_date}", size=12, color=Colors.GREY_400) if birth_date else Container(),
                        ]
                    ),
                    admin_delegation_block,
                    Divider(height=1, color=Colors.GREY_700),
                    ElevatedButton(
                        text="Сменить аккаунт",
                        icon=Icons.SWITCH_ACCOUNT_OUTLINED,
                        style=ButtonStyle(
                            bgcolor=Colors.RED_700,
                            color=Colors.WHITE,
                            shape=RoundedRectangleBorder(radius=8),
                        ),
                        width=300,
                        height=40,
                        on_click=handle_logout_click,
                    )
                ]
            )

            panel_container.content = GestureDetector(
                on_pan_update=on_pan_update,
                on_pan_end=on_pan_end,
                content=Container(
                    width=330,
                    content=expanded_card,
                    padding=padding.all(12),
                    bgcolor=Colors.with_opacity(0.96, "#222222"),
                    border=border.all(1, Colors.GREY_700),
                    border_radius=12,
                    shadow=BoxShadow(
                        blur_radius=15,
                        color=Colors.with_opacity(0.6, Colors.BLACK),
                        offset=Offset(0, 6),
                    )
                )
            )

    render_content()
    page.overlay.append(panel_container)
    page.update()