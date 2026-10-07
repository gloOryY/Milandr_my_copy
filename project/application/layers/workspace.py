from flet import *
import threading
import os
import time
import datetime
import string
from pathlib import Path
from typing import Optional

from project.algorithms.core import main_algorithm
from project.algorithms.disk_space_monitor import detect_inspection_disk, DiskSpaceMonitor
from project.application.addition.colors import color_mode
from project.application.addition.dialogs import (show_error, show_warning, show_success, show_confirmation,
                                                  select_file, select_directory)
from project.application.addition.loadings import get_path
from project.configuration.config_manager import ConfigManager
from project.station.camera.camera_manager import CameraManager
from project.station.robot.robot_controller import RobotController
from project.application.data_work.wafer_visual import WaferMapVisual
from project.application.data_work.wafer_map_factory import WaferMapFactory
from project.application.data_work.wafer_map_bin_parser import WaferMapBinParser
from project.application.data_work.wafer_data import DieStatus, WaferMap
from project.application.data_work.protocol import Protocol
from project.application.addition.logger import logger
from project.application.tab_manager import tab_manager
from project.application.addition.exceptions import RobotException, CameraException, ValidationException, \
    ProtocolException, KnownSystemException
from project.application.addition.user_profile_widget import is_user_delegated, get_all_registered_operators


def create_workspace_layer(config: 'ConfigManager',
                           camera_manager: 'CameraManager',
                           robot: 'RobotController',
                           current_user: dict = None):
    """
    Функция-конструктор вкладки "Инспекция кристаллов".
    Поддерживает выбор оператора из списка, делегирование прав и сохранение инспекции между аккаунтами.
    """
    wafer_map_visual: Optional['WaferMapVisual'] = None

    application_colors = color_mode(config)
    strict_validation = True
    buttons_state_cache = {}

    def get_user_role() -> str:
        if isinstance(current_user, dict):
            return current_user.get("role", "operator")
        return "operator"

    def is_admin_access() -> bool:
        """Проверяет права: администратор или оператор с делегированными правами."""
        if get_user_role() == "admin":
            return True
        if isinstance(current_user, dict):
            return is_user_delegated(current_user)
        return False

    def auto_set_first_reference_die(wafer_map, wafer_map_visual=None):
        """Находит и устанавливает первый референсный кристалл в нижней строке."""
        if not wafer_map or not wafer_map.die_matrix:
            return None

        target_die = None
        for row_idx in range(wafer_map.total_rows - 1, -1, -1):
            row_dice = wafer_map.die_matrix[row_idx]
            for col_idx in range(wafer_map.total_cols):
                die = row_dice[col_idx]
                if (die is not None and getattr(die, 'status', None) !=
                        DieStatus.DUMMY and getattr(die, 'symbol', '') != 'D'):
                    target_die = die
                    break
            if target_die is not None:
                break

        if target_die is None:
            for row_idx in range(wafer_map.total_rows - 1, -1, -1):
                for col_idx in range(wafer_map.total_cols):
                    die = wafer_map.die_matrix[row_idx][col_idx]
                    if die is not None:
                        target_die = die
                        break
                if target_die is not None:
                    break

        if target_die and hasattr(wafer_map, 'orientation') and wafer_map.orientation:
            if hasattr(wafer_map.orientation, 'update_first_reference_die'):
                wafer_map.orientation.update_first_reference_die(target_die)
            elif hasattr(wafer_map.orientation, 'set_first_reference_die'):
                wafer_map.orientation.set_first_reference_die(target_die)
            else:
                wafer_map.orientation.first_reference_die = target_die

            if hasattr(wafer_map.orientation, 'notify_listeners'):
                wafer_map.orientation.notify_listeners()
            elif hasattr(wafer_map.orientation, '_notify_listeners'):
                wafer_map.orientation._notify_listeners()

            if wafer_map_visual is not None and target_die.die_visual is not None:
                try:
                    if hasattr(wafer_map_visual, 'sync_reference_visualization'):
                        wafer_map_visual.sync_reference_visualization(target_die)
                    else:
                        wafer_map_visual._update_reference_visualization(target_die)
                except Exception as ex:
                    logger.error(f"Ошибка визуализации автоматического реф. кристалла: {ex}")

            logger.info(f"Автоматически установлен 1-й референсный кристалл: ID={target_die.id}")

        return target_die

    # === БАЗОВЫЕ ГРАФИЧЕСКИЕ ЭЛЕМЕНТЫ С БЕЗОПАСНЫМ ОБНОВЛЕНИЕМ ===
    def create_button(active: bool = True, **kwargs) -> ElevatedButton:
        custom_text_style = kwargs.pop('text_style', None)
        custom_text_align = kwargs.pop('text_align', TextAlign.CENTER)

        if active:
            base_text_style = custom_text_style if custom_text_style else TextStyle(
                size=22, weight=FontWeight.BOLD
            )
            text_color = application_colors["text"]
            bg_color = application_colors["inactive"]
            disabled = False
        else:
            base_text_style = custom_text_style if custom_text_style else TextStyle(
                size=22, weight=FontWeight.BOLD
            )
            text_color = application_colors["unclickable"]
            bg_color = application_colors["top_bar"]
            disabled = True

        inner_text = Text(
            value=kwargs.get("text", ""),
            text_align=custom_text_align,
            style=base_text_style,
            color=text_color,
        )

        base_style = ButtonStyle(
            shape=RoundedRectangleBorder(radius=20),
            overlay_color=application_colors["hover"],
            bgcolor=bg_color,
            animation_duration=300
        )

        kwargs.pop('text', None)

        btn = ElevatedButton(
            width=kwargs.pop('width', 120),
            height=kwargs.pop('height', 54),
            style=base_style,
            disabled=disabled,
            content=Container(
                content=inner_text,
                alignment=alignment.center,
            ),
            **kwargs
        )

        btn._inner_text = inner_text
        btn._bg_color = bg_color
        btn._text_color = text_color

        return btn

    def set_button_active(button: ElevatedButton, active: bool = True):
        """Безопасно переключает состояние кнопки без вызова исключений на несмонтированных элементах."""
        if active:
            button.bgcolor = application_colors["inactive"]
            button.color = application_colors["text"]
            button.disabled = False
        else:
            button.bgcolor = application_colors["top_bar"]
            button.color = application_colors["unclickable"]
            button.disabled = True

        if hasattr(button, '_inner_text') and button._inner_text:
            button._inner_text.color = button.color
            if getattr(button._inner_text, "page", None) is not None:
                try:
                    button._inner_text.update()
                except Exception:
                    pass

        if getattr(button, "page", None) is not None:
            try:
                button.update()
            except Exception:
                pass

    def create_text_field(**kwargs) -> TextField:
        """Создаёт текстовое поле для модальных окон (всегда активно)."""
        text_size = kwargs.pop('text_size', 18)
        label_size = kwargs.pop('label_size', 20)

        base_style = {
            "color": application_colors["text"],
            "bgcolor": application_colors["top_bar"],
            "border_color": application_colors["text"],
            "focused_border_color": application_colors["active"],
            "label_style": TextStyle(color=application_colors["text"], size=label_size),
            "text_style": TextStyle(color=application_colors["text"], size=text_size),
            "disabled": False,
        }

        base_params = {
            "width": 270,
            "dense": True,
        }
        base_params.update(base_style)
        base_params.update(kwargs)

        return TextField(**base_params)

    def create_scale_button(text, position):
        step_button_configs = {
            "first": {"radius": border_radius.only(12, 0, 12, 0)},
            "middle": {"radius": 0},
            "last": {"radius": border_radius.only(0, 12, 0, 12)},
        }
        cfg = step_button_configs[position]

        return ElevatedButton(
            text=text,
            width=104,
            height=40,
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=cfg["radius"]),
                overlay_color=application_colors["hover"],
                bgcolor=application_colors["top_bar"],
                color=application_colors["unclickable"],
                text_style=TextStyle(size=22, weight=FontWeight.BOLD),
                animation_duration=300,
            ),
            disabled=True,
        )

    # === ГРАФИЧЕСКИЕ ЭЛЕМЕНТЫ ===
    has_admin = is_admin_access()

    settings_btn = create_button(
        active=False,
        text="Настройки",
        width=220,
        tooltip="Изменение параметров доступно только Администратору (или при делегировании прав)" if not has_admin else None
    )

    height_image = 800
    width_image = 580

    left_image_container = Container(
        content=Image(src=get_path(False), fit=ImageFit.FILL, height=height_image, width=width_image),
        height=height_image,
        width=width_image,
        bgcolor=application_colors["background"],
        border_radius=10,
        alignment=alignment.center,
    )

    right_image_container = Container(
        content=Image(src=get_path(False), fit=ImageFit.FILL, height=height_image, width=width_image),
        height=height_image,
        width=width_image,
        bgcolor=application_colors["background"],
        border_radius=10,
        alignment=alignment.center,
    )

    initial_container = Container(
        content=Column(
            controls=[
                Icon(Icons.FILE_UPLOAD_OUTLINED, size=80, color=application_colors["unclickable"]),
                Container(height=20),
                Text("Нажмите «Создать новую инспекцию»\nдля загрузки карты годности" if has_admin else "Ожидание создания инспекции\nАдминистратором",
                     size=26,
                     text_align=TextAlign.CENTER,
                     color=application_colors["unclickable"])
            ],
            alignment=MainAxisAlignment.CENTER,
            horizontal_alignment=CrossAxisAlignment.CENTER,
        ),
        width=600,
        height=600,
        alignment=alignment.center,
        bgcolor=application_colors["background"]
    )

    loading_container = Container(
        content=Column(
            controls=[
                ProgressRing(width=100, height=100, color=application_colors["active"]),
                Container(height=30),
                Text("Загрузка карты...", size=30, color=application_colors["text"])
            ],
            alignment=MainAxisAlignment.CENTER,
            horizontal_alignment=CrossAxisAlignment.CENTER,
        ),
        width=600,
        height=600,
        alignment=alignment.center,
        bgcolor=application_colors["background"],
    )

    button_grid = Container(
        width=600,
        height=600,
        clip_behavior=ClipBehavior.HARD_EDGE,
        bgcolor=application_colors["background"],
        alignment=alignment.center
    )

    dynamic_grid_container = Container(
        alignment=alignment.center,
        content=initial_container
    )

    create_new_inspection_btn = create_button(
        active=has_admin,
        text="Создать новую инспекцию",
        width=370,
        tooltip="Создание инспекции доступно только Администратору (или при делегировании прав)" if not has_admin else None
    )

    strict_validation_checkbox = Container(
        content=Row(
            controls=[
                Container(
                    content=Icon(
                        name=Icons.CHECK if strict_validation else "",
                        size=42,
                        color=application_colors["text"],
                    ),
                    width=50,
                    height=50,
                    border_radius=12,
                    border=border.all(3, application_colors["text"]),
                    bgcolor=application_colors["background"],
                    alignment=alignment.center
                ),
                Container(
                    content=Column(
                        controls=[
                            Text("Строгая",
                                 size=21,
                                 weight=FontWeight.BOLD,
                                 color=application_colors["text"]),
                            Text("валидация",
                                 size=21,
                                 weight=FontWeight.BOLD,
                                 color=application_colors["text"]),
                        ],
                        spacing=0,
                    ),
                    padding=padding.only(left=10),
                )
            ],
            alignment=MainAxisAlignment.START,
            vertical_alignment=CrossAxisAlignment.CENTER,
        ),
        bgcolor=application_colors["background"],
        border_radius=5,
        padding=padding.all(5),
    )

    settings_with_checkbox_column = Column(
        controls=[
            settings_btn,
            Container(height=10),
            Container(
                content=strict_validation_checkbox,
                width=220,
                alignment=alignment.center,
            ),
        ],
        horizontal_alignment=CrossAxisAlignment.CENTER,
        spacing=0,
    )

# === ОБЛАСТЬ ИНСПЕКЦИИ ===
    selection_mode_switch = Switch(
        value=False,
        active_color=application_colors["active"],
        inactive_thumb_color=application_colors["unclickable"]
    )
    
    reset_area_btn = create_button(
        active=False, text="Сбросить выделение", width=250, height=40, text_style=TextStyle(size=18, weight=FontWeight.BOLD)
    )

    area_selection_container = Container(
        content=Column(
            controls=[
                Row(
                    controls=[
                        Text("Режим выделения", size=20, weight=FontWeight.BOLD, color=application_colors["text"]),
                        selection_mode_switch
                    ],
                    alignment=MainAxisAlignment.SPACE_BETWEEN
                ),
                reset_area_btn
            ],
            alignment=MainAxisAlignment.CENTER,
            spacing=15
        ),
        padding=padding.all(15),
        bgcolor=application_colors["top_bar"],
        border_radius=10,
        width=370
    )

    # Создаем колонку, которая объединит кнопку создания и область инспекции
    inspection_and_area_column = Column(
        controls=[
            create_new_inspection_btn,
            area_selection_container,
        ],
        spacing=10,
        horizontal_alignment=CrossAxisAlignment.CENTER
    )

    download_wafer_map_controls_container = Row(
        controls=[
            inspection_and_area_column, 
            settings_with_checkbox_column,
        ],
        alignment=MainAxisAlignment.CENTER,
        spacing=15,
        vertical_alignment=CrossAxisAlignment.START,
    )

    scale_crystal_buttons = Row(
        controls=[
            Text(
                value="Масштаб кнопок: ",
                size=22,
                weight=FontWeight.BOLD,
                color=application_colors["text"]
            ),
            Container(width=12),
            create_scale_button("1x", "first"),
            create_scale_button("1,5x", "middle"),
            create_scale_button("2x", "last"),
        ],
        alignment=MainAxisAlignment.CENTER,
        spacing=5
    )

    scale_buttons = []
    for control in scale_crystal_buttons.controls[2:]:
        scale_buttons.append(control)

    center_column = Column(
        controls=[
            Container(height=1),
            Row(
                controls=[
                    Text("Визуализация пластины", size=26, weight=FontWeight.BOLD,
                         color=application_colors["text"]),
                ],
                alignment=MainAxisAlignment.CENTER,
            ),
            scale_crystal_buttons,
            Container(height=4),
            dynamic_grid_container,
            download_wafer_map_controls_container,
            Container(height=60),
        ],
        alignment=MainAxisAlignment.CENTER,
        horizontal_alignment=CrossAxisAlignment.CENTER,
    )

    change_detectable_dice_btn = create_button(
        active=False,
        text="Определить типы\nдетектируемых кристаллов",
        width=340,
        height=70,
    )

    update_protocol_btn = create_button(
        active=False,
        text="Обновить\nпротокол",
        width=150,
        height=70
    )

    change_detectable_dice_container = Row(
        controls=[
            update_protocol_btn,
            change_detectable_dice_btn,
        ],
        alignment=MainAxisAlignment.CENTER,
        spacing=40,
    )

    start_AOI_btn = create_button(
        active=True,
        text="Запуск"
    )

    pause_AOI_btn = create_button(
        active=False,
        text="Пауза"
    )

    continue_AOI_btn = create_button(
        active=False,
        text="Продолжить",
        width=170
    )

    stop_AOI_btn = create_button(
        active=False,
        text="Стоп"
    )

    inspection_buttons = Row(
        controls=[
            start_AOI_btn,
            pause_AOI_btn,
            continue_AOI_btn,
            stop_AOI_btn,
        ],
        alignment=MainAxisAlignment.CENTER,
        spacing=15,
    )

    left_column = Column(
            controls=[
                Text("Оригинальное изображение", size=26, weight=FontWeight.BOLD, color=application_colors["text"]),
                left_image_container,
                change_detectable_dice_container,
                Container(height=50),
            ],
            alignment=MainAxisAlignment.CENTER,
            horizontal_alignment=CrossAxisAlignment.CENTER,
        )

    right_column = Column(
        controls=[
            Text("Изображение с дефектами", size=26, weight=FontWeight.BOLD, color=application_colors["text"]),
            right_image_container,
            Container(height=1),
            inspection_buttons,
            Container(height=50),
        ],
        alignment=MainAxisAlignment.CENTER,
        horizontal_alignment=CrossAxisAlignment.CENTER,
    )

    workspace_tab = Tab(
        text="Инспекция кристаллов",
        content=Container(
            content=Row(
                controls=[
                    left_column,
                    Container(expand=0),
                    center_column,
                    Container(expand=0),
                    right_column,
                ],
                alignment=MainAxisAlignment.CENTER,
                vertical_alignment=CrossAxisAlignment.CENTER,
            ),
            padding=10,
            bgcolor=application_colors["background"],
        ),
    )

    def validate_input_file_path(file_path_wafer_map: str) -> str:
        if not file_path_wafer_map or not os.path.exists(file_path_wafer_map):
            return ""

        file_name = os.path.basename(file_path_wafer_map)
        if '.' not in file_name:
            return "bin"

        extension = os.path.splitext(file_name)[1].lower()
        if extension == '.bin':
            return "bin"
        elif extension == '.json':
            return "json"

        return ""

    # =================== БЕЗОПАСНОЕ АВТОВОССТАНОВЛЕНИЕ КАРТЫ ===================
    def restore_active_wafer_map_if_exists():
        """Восстанавливает созданную пластину оператору без вызова .update() на несмонтированных контролах."""
        nonlocal wafer_map_visual
        if WaferMap.has_instance():
            wm = WaferMap.get_instance()
            if wm and getattr(wm, 'die_matrix', None) and getattr(wm, 'wafer_id', None):
                wafer_map_visual = WaferMapVisual(application_colors, config)
                wafer_map_visual.on_selection_done = on_selection_complete
                wafer_map_visual.toggle_selection_mode(selection_mode_switch.value)
                grid_view = wafer_map_visual.generate_visual(
                    wafer_map=wm,
                    scale_value=config.scale_buttons_panel
                )
                if grid_view:
                    button_grid.content = grid_view
                    dynamic_grid_container.content = button_grid

                    change_detectable_dice_btn.disabled = False
                    change_detectable_dice_btn.bgcolor = application_colors["inactive"]
                    change_detectable_dice_btn.color = application_colors["text"]
                    if hasattr(change_detectable_dice_btn, '_inner_text'):
                        change_detectable_dice_btn._inner_text.color = application_colors["text"]

                    # Активируем кнопку "Настройки" (только если есть права)
                    if has_admin:
                        settings_btn.disabled = False
                        settings_btn.bgcolor = application_colors["inactive"]
                        settings_btn.color = application_colors["text"]
                        if hasattr(settings_btn, '_inner_text'):
                            settings_btn._inner_text.color = application_colors["text"]

                    update_protocol_btn.disabled = False
                    update_protocol_btn.bgcolor = application_colors["inactive"]
                    update_protocol_btn.color = application_colors["text"]
                    if hasattr(update_protocol_btn, '_inner_text'):
                        update_protocol_btn._inner_text.color = application_colors["text"]

                    for btn in scale_buttons:
                        btn.disabled = False
                        btn.bgcolor = application_colors["inactive"]
                        btn.color = application_colors["text"]
                    scale_mapping = {1.0: 0, 1.5: 1, 2.0: 2}
                    scale_buttons[scale_mapping.get(config.scale_buttons_panel, 0)].bgcolor = application_colors["active"]

                    logger.info(f"Сохранённая инспекция '{wm.wafer_id}' успешно отображена для текущего пользователя")

    restore_active_wafer_map_if_exists()

    # =================== ОБРАБОТЧИК: СОЗДАТЬ НОВУЮ ИНСПЕКЦИЮ ===================

    def create_new_inspection_handler(_e):
        page = _e.page

        if not is_admin_access():
            show_warning("Ограничение прав", "Создание новой инспекции доступно только Администратору.\nОбратитесь к администратору для делегирования прав.", page, config)
            return

        dialog_overlay = None
        current_date_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        # Получаем список всех зарегистрированных операторов
        registered_users = get_all_registered_operators()
        inspector_options = []
        for u in registered_users:
            fname = u.get("full_name") or u.get("name") or u.get("username")
            if fname and not any(opt.key == fname for opt in inspector_options):
                inspector_options.append(dropdown.Option(fname, fname))

        # Текущий пользователь по умолчанию
        cur_user_fname = current_user.get("full_name") or current_user.get("name") or current_user.get("username") if current_user else "Инспектор"
        if not any(opt.key == cur_user_fname for opt in inspector_options):
            inspector_options.insert(0, dropdown.Option(cur_user_fname, cur_user_fname))

        default_inspector_val = cur_user_fname if any(opt.key == cur_user_fname for opt in inspector_options) else inspector_options[0].key

        map_path_field = TextField(
            label="Файл карты годности",
            read_only=True,
            width=380,
            dense=True,
            text_size=15,
            color=application_colors["text"],
            bgcolor=application_colors["top_bar"],
            border_color=application_colors["text"],
        )

        wafer_id_input = TextField(
            label="ID пластины",
            hint_text="Например: PCFH70-11",
            width=500,
            dense=True,
            text_size=16,
            color=application_colors["text"],
            bgcolor=application_colors["top_bar"],
            border_color=application_colors["text"],
            focused_border_color=application_colors["active"],
        )

        wafer_type_dropdown = Dropdown(
            label="Тип пластины",
            options=[
                dropdown.Option("300", "300 мм"),
                dropdown.Option("200", "200 мм"),
                dropdown.Option("150", "150 мм"),
            ],
            value="300",
            width=500,
            dense=True,
            color=application_colors["text"],
            bgcolor=application_colors["top_bar"],
            border_color=application_colors["text"],
        )

        size_x_input = TextField(
            label="Шаг кристаллов по X (мм)",
            value=str(config.wafer_params.get("x_distance", "")),
            width=240,
            dense=True,
            text_size=16,
            color=application_colors["text"],
            bgcolor=application_colors["top_bar"],
            border_color=application_colors["text"],
        )

        size_y_input = TextField(
            label="Шаг кристаллов по Y (мм)",
            value=str(config.wafer_params.get("y_distance", "")),
            width=240,
            dense=True,
            text_size=16,
            color=application_colors["text"],
            bgcolor=application_colors["top_bar"],
            border_color=application_colors["text"],
        )

        date_input = TextField(
            label="Дата и время создания",
            value=current_date_str,
            read_only=True,
            width=500,
            dense=True,
            text_size=16,
            color=application_colors["unclickable"],
            bgcolor=application_colors["top_bar"],
            border_color=application_colors["text"],
        )

        # Выпадающий список зарегистрированных операторов
        inspector_dropdown = Dropdown(
            label="Инспектор (ответственный оператор)",
            options=inspector_options,
            value=default_inspector_val,
            width=500,
            dense=True,
            color=application_colors["text"],
            bgcolor=application_colors["top_bar"],
            border_color=application_colors["text"],
        )

        comment_input = TextField(
            label="Комментарий к пластине",
            hint_text="Введите примечание или комментарий...",
            multiline=True,
            min_lines=2,
            max_lines=3,
            width=500,
            text_size=15,
            color=application_colors["text"],
            bgcolor=application_colors["top_bar"],
            border_color=application_colors["text"],
            focused_border_color=application_colors["active"],
        )

        def pick_map_file(_):
            selected_path = select_file(
                initial_dir=config.input_file_path,
                title="Выберите карту годности для новой инспекции",
                filetypes=[
                    ("Все файлы", "*"),
                    ("Бинарные файлы (.bin)", "*.bin"),
                    ("JSON-файлы (.json)", "*.json"),
                ]
            )
            if selected_path:
                map_path_field.value = selected_path
                map_path_field.update()

                stem = Path(selected_path).stem
                if not wafer_id_input.value or wafer_id_input.value.strip() == "":
                    wafer_id_input.value = stem
                    wafer_id_input.update()

        choose_file_btn = ElevatedButton(
            text="Обзор...",
            width=110,
            height=40,
            on_click=pick_map_file,
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=8),
                bgcolor=application_colors["inactive"],
                color=application_colors["text"],
            )
        )

        def close_dialog():
            if dialog_overlay in page.overlay:
                page.overlay.remove(dialog_overlay)
            page.update()

        def confirm_create_inspection(_):
            file_path = map_path_field.value.strip()
            wafer_id = wafer_id_input.value.strip()

            if not file_path or not os.path.exists(file_path):
                show_error("Ошибка", "Пожалуйста, выберите существующий файл карты годности", page, config)
                return

            if not wafer_id:
                show_error("Ошибка", "Укажите ID пластины", page, config)
                return

            try:
                cell_x = float(size_x_input.value.replace(",", "."))
                cell_y = float(size_y_input.value.replace(",", "."))
            except ValueError:
                show_error("Ошибка", "Ошибка валидации введенных данных", page, config)
                return

            # === Валидация диапазонов (аналогично настройкам) ===
            error_title = "Ошибка валидации введенных данных"

            if not (1.56 <= cell_x <= 2.92):
                show_error(
                    error_title,
                    "Расстояние X должно быть в диапазоне от 1.56 до 2.92 мм\n"
                    "в связи с текущей конфигурацией оптического модуля",
                    page, config
                )
                return

            if not (2.3 <= cell_y <= 4.4):
                show_error(
                    error_title,
                    "Расстояние Y должно быть в диапазоне от 2.3 до 4.4 мм\n"
                    "в связи с текущей конфигурацией оптического модуля",
                    page, config
                )
                return

            w_type = wafer_type_dropdown.value
            insp_date = date_input.value
            insp_name = inspector_dropdown.value or "Инспектор"
            comment_val = comment_input.value.strip()

            close_dialog()

            config.wafer_params = {"x_distance": cell_x, "y_distance": cell_y}

            start_inspection_process(
                input_file_path=file_path,
                wafer_id=wafer_id,
                wafer_type=w_type,
                cell_x=cell_x,
                cell_y=cell_y,
                inspector=insp_name,
                inspection_date=insp_date,
                comment=comment_val
            )

        submit_btn = ElevatedButton(
            text="Создать",
            icon=Icons.CHECK,
            width=150,
            height=45,
            on_click=confirm_create_inspection,
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=10),
                bgcolor=application_colors["active"],
                color=application_colors["text"],
                text_style=TextStyle(size=18, weight=FontWeight.BOLD)
            )
        )

        cancel_btn = ElevatedButton(
            text="Отмена",
            width=120,
            height=45,
            on_click=lambda _: close_dialog(),
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=10),
                bgcolor=application_colors["inactive"],
                color=application_colors["text"],
            )
        )

        dialog_box = Container(
            width=560,
            bgcolor=application_colors["background"],
            border=border.all(2, application_colors["active"]),
            border_radius=12,
            padding=24,
            content=Column(
                tight=True,
                spacing=12,
                controls=[
                    Text("Создание новой инспекции", size=22, weight=FontWeight.BOLD, color=application_colors["text"]),
                    Divider(color=application_colors["inactive"]),
                    Row([map_path_field, choose_file_btn], spacing=10),
                    wafer_id_input,
                    wafer_type_dropdown,
                    Row([size_x_input, size_y_input], spacing=20),
                    date_input,
                    inspector_dropdown,
                    comment_input,
                    Container(height=8),
                    Row([cancel_btn, submit_btn], alignment=MainAxisAlignment.END, spacing=15)
                ]
            )
        )

        dialog_overlay = Stack(
            controls=[
                Container(
                    width=page.width,
                    height=page.height,
                    bgcolor=Colors.with_opacity(0.4, Colors.BLACK),
                    on_click=lambda _: close_dialog()
                ),
                Container(
                    content=dialog_box,
                    alignment=alignment.center,
                    width=page.width,
                    height=page.height
                )
            ]
        )

        page.overlay.append(dialog_overlay)
        page.update()

    def start_inspection_process(input_file_path: str,
                                 wafer_id: str,
                                 wafer_type: str,
                                 cell_x: float,
                                 cell_y: float,
                                 inspector: str,
                                 inspection_date: str,
                                 comment: str = ""):
        page = config.page

        extension_file = validate_input_file_path(input_file_path)
        if extension_file == "":
            show_error("Некорректный формат файла", "Выберите файл .bin, .json или без расширения", page, config)
            return

        config.input_file_path = str(Path(input_file_path).parent.as_posix())

        def proceed_with_loading(chosen_protocol_path: str):
            protocol: Optional['Protocol'] = Protocol()
            active_all_buttons(False)
            deactivate_scale_buttons()
            dynamic_grid_container.content = loading_container
            page.update()

            async def load_new_inspection_async():
                try:
                    if extension_file == 'bin':
                        parser = WaferMapBinParser(
                            file_path=input_file_path,
                            strict_validation_check=strict_validation
                        )
                        parser.parse()

                        wafer_map = WaferMapFactory.from_bin_parser(parser, config)
                        if wafer_id:
                            wafer_map.wafer_id = wafer_id
                        wafer_map.cell_size_x_mm = cell_x
                        wafer_map.cell_size_y_mm = cell_y
                        wafer_map.update_die_coordinates(is_need_update=True)

                        config.protocol_path = protocol.create_protocol(
                            protocol_path=chosen_protocol_path,
                            wafer_map_bin_file_path=input_file_path,
                            wafer_map=wafer_map,
                            wafer_type=wafer_type,
                            inspector=inspector,
                            inspection_date=inspection_date,
                            comment=comment
                        ).parent.as_posix()

                    else:
                        wafer_map = WaferMapFactory.from_json_protocol(input_file_path)
                        if wafer_id:
                            wafer_map.wafer_id = wafer_id

                        config.protocol_path = (
                            protocol.load_config_from_json(json_file_path=input_file_path)
                        ).parent.as_posix()

                        protocol.wafer_type = wafer_type
                        protocol.inspector = inspector
                        protocol.inspection_date = inspection_date
                        protocol.comment = comment

                    wafer_map.protocol = protocol
                    wafer_map.protocol.update_protocol(wafer_map)

                    nonlocal wafer_map_visual
                    wafer_map_visual = WaferMapVisual(application_colors, config)
                    wafer_map_visual.on_selection_done = on_selection_complete
                    wafer_map_visual.toggle_selection_mode(selection_mode_switch.value)
                    grid_view = wafer_map_visual.generate_visual(
                        wafer_map=wafer_map,
                        scale_value=config.scale_buttons_panel
                    )

                    auto_set_first_reference_die(wafer_map, wafer_map_visual=wafer_map_visual)

                    button_grid.content = grid_view
                    dynamic_grid_container.content = button_grid
                    await page.update_async()

                    show_success("Новая инспекция создана",
                                 f"Инспекция для пластины {wafer_id} успешно инициализирована.\n1-й референсный кристалл установлен автоматически.",
                                 page, config)
                    logger.info(f"Новая инспекция успешно создана: {wafer_id}")

                except (ProtocolException, KnownSystemException) as e:
                    show_error("Ошибка при обработке входных данных", str(e), page, config)

                except ValidationException as e:
                    show_error("Ошибка валидации бинарного файла карты годности", str(e), page, config)

                except Exception as e:
                    logger.error(f"Ошибка при обработке входных данных: {e}")
                    show_error("Ошибка при обработке входных данных",
                               "Точная причина неизвестна", page, config)

                finally:
                    active_all_buttons(True)
                    if dynamic_grid_container.content != button_grid:
                        dynamic_grid_container.content = initial_container
                    else:
                        set_button_active(reset_area_btn, True)
                        set_button_active(change_detectable_dice_btn, True)
                        set_button_active(update_protocol_btn, True)
                        if has_admin:
                            set_button_active(settings_btn, True)
                        activate_scale_buttons()
                    await page.update_async()

            time.sleep(0.1)
            page.run_task(load_new_inspection_async)

        if extension_file == 'bin':
            protocol_path = select_directory(
                initial_dir=config.protocol_path,
                title="Выберите папку для сохранения протокола текущей пластины",
            )
            if not protocol_path or not os.path.exists(protocol_path):
                show_warning("Предупреждение", "Папка протокола не выбрана. Создание отменено.", page, config)
                return

            def on_confirm_folder(_):
                if page.dialog:
                    page.dialog.open = False
                    page.update()
                proceed_with_loading(protocol_path)

            def on_cancel_folder(_):
                if page.dialog:
                    page.dialog.open = False
                    page.update()
                logger.info("Отмена создания инспекции после выбора папки")

            show_confirmation(
                title="Подтверждение папки сохранения",
                message=f"Вы уверены, что хотите сохранить протоколы и результаты инспекции в папку:\n\n{protocol_path}?",
                page=page,
                config=config,
                on_confirm=on_confirm_folder,
                on_cancel=on_cancel_folder,
                confirm_text="Подтвердить",
                cancel_text="Отмена"
            )
        else:
            proceed_with_loading("")

    def toggle_strict_validation_handler(_e):
        nonlocal strict_validation
        strict_validation = not strict_validation

        checkbox_icon = strict_validation_checkbox.content.controls[0].content
        checkbox_icon.name = Icons.CHECK if strict_validation else ""
        strict_validation_checkbox.update()

    def open_settings_handler(_e):
        page = _e.page

        if not is_admin_access():
            show_warning(
                "Ограничение прав",
                "Изменение параметров доступно только Администратору.",
                page,
                config
            )
            return

        settings_overlay = None

        # === Поля для расстояний между центрами кристаллов ===
        x_input = create_text_field(
            label="Шаг кристаллов по X (мм)",
            value=str(config.wafer_params.get("x_distance", "")),
            tooltip=(
                "Расстояние между центрами соседних кристаллов по оси X (мм).\n"
                "Используется для расчёта физических координат кристаллов на пластине.\n"
                "Ограничения текущей оптической конфигурации: от 1.56 до 2.92 мм."
            ),
        )

        y_input = create_text_field(
            label="Шаг кристаллов по Y (мм)",
            value=str(config.wafer_params.get("y_distance", "")),
            tooltip=(
                "Расстояние между центрами соседних кристаллов по оси Y (мм).\n"
                "Используется для расчёта физических координат кристаллов на пластине.\n"
                "Ограничения текущей оптической конфигурации: от 2.3 до 4.4 мм."
            ),
        )

        # === Поля для порогов расстояния (delay_params) ===
        threshold_xy_input = create_text_field(
            label="Порог задержки по XY (мм)",
            value=str(config.delay_params.get("distance_threshold_xy_mm_for_delay", "")),
            tooltip=(
                "Порог перемещения по XY, после которого включается задержка (мм).\n"
                "Если перемещение меньше порога — задержка не применяется.\n"
                "Ограничения: от 0 до 380 мм (размер рабочей области по XY)."
            ),
        )

        threshold_z_input = create_text_field(
            label="Порог задержки по Z (мм)",
            value=str(config.delay_params.get("distance_threshold_z_mm_for_delay", "")),
            tooltip=(
                "Порог перемещения по Z, после которого включается задержка (мм).\n"
                "Если перемещение меньше порога — задержка не применяется.\n"
                "Ограничения: от 0 до 80 мм (размер рабочей области по Z)."
            ),
        )

        # === Поля для параметров задержки (delay_params) ===
        growth_xy_input = create_text_field(
            label="Рост задержки по XY (сек/мм)",
            value=str(config.delay_params.get("delay_growth_xy_sec_per_mm", "")),
            tooltip=(
                "Скорость роста адаптивной задержки по XY (сек/мм).\n"
                "Показывает, на сколько секунд увеличивается задержка "
                "на каждый мм сверх порога.\n"
                "Ограничения: от 0 до 10 сек/мм."
            ),
        )

        growth_z_input = create_text_field(
            label="Рост задержки по Z (сек/мм)",
            value=str(config.delay_params.get("delay_growth_z_sec_per_mm", "")),
            tooltip=(
                "Скорость роста адаптивной задержки по Z (сек/мм).\n"
                "Показывает, на сколько секунд увеличивается задержка "
                "на каждый мм сверх порога по оси Z.\n"
                "Ограничения: от 0 до 10 сек/мм."
            ),
        )

        # === Поля для минимальной и максимальной адаптивной задержки ===
        min_adaptive_delay_input = create_text_field(
            label="Мин. задержка (с)",
            value=str(config.delay_params.get("min_adaptive_delay_sec", "")),
            tooltip=(
                "Минимальная адаптивная задержка по всем осям после перемещения (сек).\n"
                "Ограничения: от 0 до 60 секунд."
            ),
        )

        max_adaptive_delay_input = create_text_field(
            label="Макс. задержка (с)",
            value=str(config.delay_params.get("max_adaptive_delay_sec", "")),
            tooltip=(
                "Максимально возможная адаптивная задержка по всем осям после перемещения (сек).\n"
                "Ограничения: от 0 до 60 секунд.\n"
                "Принудительная задержка может быть больше — тогда применяется она."
            ),
        )

        post_move_delay_input = create_text_field(
            label="Принудительная задержка (с)",
            value=str(config.delay_params.get("post_move_delay_sec", "")),
            tooltip=(
                "Принудительная задержка после перемещения (секунды).\n"
                "Не масштабируется по расстоянию. Если она больше адаптивной, "
                "применяется она; иначе применяется адаптивная.\n"
                "Значение 0 — принудительная задержка отключена.\n"
                "Ограничения: от 0 до 60 секунд."
            ),
        )

        DEFAULT_DELAY_PARAMS = {
            "distance_threshold_xy_mm_for_delay": 5.0,
            "distance_threshold_z_mm_for_delay": 0.5,
            "delay_growth_xy_sec_per_mm": 0.5,
            "delay_growth_z_sec_per_mm": 0.5,
            "post_move_delay_sec": 0.0,
            "min_adaptive_delay_sec": 0.5,
            "max_adaptive_delay_sec": 2.0,
        }

        def _apply_default_delay_params_values():
            """Непосредственно заполняет поля базовыми значениями."""
            threshold_xy_input.value = str(DEFAULT_DELAY_PARAMS["distance_threshold_xy_mm_for_delay"])
            threshold_z_input.value = str(DEFAULT_DELAY_PARAMS["distance_threshold_z_mm_for_delay"])
            growth_xy_input.value = str(DEFAULT_DELAY_PARAMS["delay_growth_xy_sec_per_mm"])
            growth_z_input.value = str(DEFAULT_DELAY_PARAMS["delay_growth_z_sec_per_mm"])
            post_move_delay_input.value = str(DEFAULT_DELAY_PARAMS["post_move_delay_sec"])
            min_adaptive_delay_input.value = str(DEFAULT_DELAY_PARAMS["min_adaptive_delay_sec"])
            max_adaptive_delay_input.value = str(DEFAULT_DELAY_PARAMS["max_adaptive_delay_sec"])

            threshold_xy_input.update()
            threshold_z_input.update()
            growth_xy_input.update()
            growth_z_input.update()
            post_move_delay_input.update()
            min_adaptive_delay_input.update()
            max_adaptive_delay_input.update()

            logger.debug("Поля параметров задержки заполнены базовыми значениями")

        def apply_default_delay_params(_):
            """Запрашивает подтверждение и заполняет поля базовыми значениями."""

            def on_confirm(_e):
                _apply_default_delay_params_values()

            def on_cancel(_e):
                logger.info("Сброс параметров задержки отменён пользователем")

            show_confirmation(
                title="Подтверждение сброса",
                message=(
                    "Вы действительно хотите сбросить параметры задержки к базовым значениям?"
                ),
                page=page,
                config=config,
                on_confirm=on_confirm,
                on_cancel=on_cancel,
                confirm_text="Сбросить",
                cancel_text="Отмена"
            )

        def close_dialog():
            if settings_overlay in page.overlay:
                page.overlay.remove(settings_overlay)
            page.update()

        def _parse_float(field_value: str, field_name: str) -> float:
            """Парсит число из поля, поддерживает запятую как разделитель."""
            try:
                return float(field_value.replace(",", ".").strip())
            except (ValueError, AttributeError):
                raise ValueError(f"Некорректное значение в поле «{field_name}»")

        def save_settings(_):
            try:
                # Парсинг всех 6 значений
                cell_size_x_mm = _parse_float(x_input.value, "Шаг кристаллов по X (мм)")
                cell_size_y_mm = _parse_float(y_input.value, "Шаг кристаллов по Y (мм)")

                threshold_xy_mm = _parse_float(threshold_xy_input.value, "Порог задержки по XY (мм)")
                threshold_z_mm = _parse_float(threshold_z_input.value, "Порог задержки по Z (мм)")

                growth_xy_sec_per_mm = _parse_float(growth_xy_input.value, "Рост задержки по XY (мм/c)")
                growth_z_sec_per_mm = _parse_float(growth_z_input.value, "Рост задержки по Z (мм/c)")

                min_adaptive_delay_sec = _parse_float(min_adaptive_delay_input.value, "Мин. задержка (с)")
                max_adaptive_delay_sec = _parse_float(max_adaptive_delay_input.value, "Макс. задержка (с)")

                post_move_delay_sec = _parse_float(post_move_delay_input.value, "Принудительная задержка (с)")

            except ValueError as e:
                show_error("Ошибка ввода параметров", str(e), page, config)
                return

            # === Валидация ===

            error_title = "Ошибка валидации введенных данных"

            # 1. Расстояние между кристаллами по X мм
            if not (1.56 <= cell_size_x_mm <= 2.92):
                show_error(
                    error_title,
                    "Расстояние X должно быть в диапазоне от 1.56 до 2.92 мм\n"
                    "в связи с текущей конфигурацией оптическогог модуля",
                    page, config
                )
                return

            # 2. Расстояние между кристаллами по Y мм
            if not (2.3 <= cell_size_y_mm <= 4.4):
                show_error(
                    error_title,
                    "Расстояние Y должно быть в диапазоне от 2.3 до 4.4 мм\n"
                    "в связи с текущей конфигурацией оптическогог модуля",
                    page, config
                )
                return

            # 3. Порог по XY
            threshold_max_xy = abs(config.extreme_coordinates["x_max"] - config.extreme_coordinates["x_min"])
            if threshold_xy_mm < 0 or threshold_xy_mm > threshold_max_xy:
                show_error(
                    error_title,
                    f"Порог XY должен быть в диапазоне от 0 до {threshold_max_xy} мм.",
                    page, config
                )
                return

            # 4. Порог по Z
            threshold_max_z = abs(config.extreme_coordinates["z_max"] - config.extreme_coordinates["z_min"])
            if threshold_z_mm < 0 or threshold_z_mm > threshold_max_z:
                show_error(
                    error_title,
                    f"Порог Z должен быть в диапазоне от 0 до {threshold_max_z} мм.",
                    page, config
                )
                return

            # 5. Рост задержки по XY
            if growth_xy_sec_per_mm < 0 or growth_xy_sec_per_mm > 10:
                show_error(
                    error_title,
                    "Рост задержки по XY должен быть в диапазоне от 0 до 10 сек/мм.",
                    page, config
                )
                return

            # 6. Рост задержки по Z
            if growth_z_sec_per_mm < 0 or growth_z_sec_per_mm > 10:
                show_error(
                    error_title,
                    "Рост задержки по Z должен быть в диапазоне от 0 до 10 сек/мм.",
                    page, config
                )
                return

            # 7. Минимальная адаптивная задержка
            if min_adaptive_delay_sec < 0 or min_adaptive_delay_sec > 60:
                show_error(
                    error_title,
                    "Минимальная задержка должна быть в диапазоне от 0 до 60 секунд.",
                    page, config
                )
                return

            # 8. Максимальная адаптивная задержка
            if max_adaptive_delay_sec < 0 or max_adaptive_delay_sec > 60:
                show_error(
                    error_title,
                    "Максимальная задержка должна быть в диапазоне от 0 до 60 секунд.",
                    page, config
                )
                return

            # 9. Максимальная не должна быть меньше минимальной
            if max_adaptive_delay_sec < min_adaptive_delay_sec:
                show_error(
                    error_title,
                    "Максимальная задержка не может быть меньше минимальной.",
                    page, config
                )
                return

            # 10. Принудительная задержка
            if post_move_delay_sec < 0 or post_move_delay_sec > 60:
                show_error(
                    error_title,
                    "Принудительная должна быть в диапазоне от 0 до 60 секунд.",
                    page, config
                )
                return

            # === Сохранение ===
            try:
                wafer_params_changed = (
                        config.wafer_params.get("x_distance") != cell_size_x_mm or
                        config.wafer_params.get("y_distance") != cell_size_y_mm
                )

                delay_params_changed = (
                        config.delay_params.get("distance_threshold_xy_mm_for_delay") != threshold_xy_mm or
                        config.delay_params.get("distance_threshold_z_mm_for_delay") != threshold_z_mm or
                        config.delay_params.get("delay_growth_xy_sec_per_mm") != growth_xy_sec_per_mm or
                        config.delay_params.get("delay_growth_z_sec_per_mm") != growth_z_sec_per_mm or
                        config.delay_params.get("min_adaptive_delay_sec") != min_adaptive_delay_sec or
                        config.delay_params.get("max_adaptive_delay_sec") != max_adaptive_delay_sec or
                        config.delay_params.get("post_move_delay_sec") != post_move_delay_sec
                )

                if wafer_params_changed:
                    if wafer_map_visual is not None and wafer_map_visual.wafer_map is not None:
                        active_all_buttons(False)
                        try:
                            wafer_map = wafer_map_visual.wafer_map
                            wafer_map.cell_size_x_mm = cell_size_x_mm
                            wafer_map.cell_size_y_mm = cell_size_y_mm
                            wafer_map.update_die_coordinates(is_need_update=True)
                        finally:
                            active_all_buttons(True)

                    config.wafer_params = {
                        "x_distance": cell_size_x_mm,
                        "y_distance": cell_size_y_mm
                    }

                if delay_params_changed:
                    config.delay_params = {
                        "distance_threshold_xy_mm_for_delay": threshold_xy_mm,
                        "distance_threshold_z_mm_for_delay": threshold_z_mm,
                        "delay_growth_xy_sec_per_mm": growth_xy_sec_per_mm,
                        "delay_growth_z_sec_per_mm": growth_z_sec_per_mm,
                        "min_adaptive_delay_sec": min_adaptive_delay_sec,
                        "max_adaptive_delay_sec": max_adaptive_delay_sec,
                        "post_move_delay_sec": post_move_delay_sec,
                    }

                close_dialog()

            except Exception as ex:
                logger.error(f"Ошибка сохранения параметров: {ex}")
                show_error(
                    "Ошибка сохранения параметров",
                    "Точная причина неизвестна",
                    page,
                    config
                )

        save_btn = ElevatedButton(
            text="Сохранить",
            icon=Icons.CHECK,
            width=150,
            height=45,
            on_click=save_settings,
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=10),
                bgcolor=application_colors["active"],
                color=application_colors["text"],
                text_style=TextStyle(size=18, weight=FontWeight.BOLD)
            )
        )

        cancel_btn = ElevatedButton(
            text="Отмена",
            width=150,
            height=45,
            on_click=lambda _: close_dialog(),
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=10),
                bgcolor=application_colors["inactive"],
                color=application_colors["text"],
            )
        )

        apply_default_params_btn = ElevatedButton(
            text="Сброс",
            width=150,
            height=45,
            on_click=apply_default_delay_params,
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=10),
                bgcolor=application_colors["inactive"],
                color=application_colors["text"],
                text_style=TextStyle(size=16, weight=FontWeight.BOLD),
            )
        )

        def _section_label(text: str) -> Text:
            return Text(
                text,
                size=18,
                weight=FontWeight.BOLD,
                color=application_colors["unclickable"],
                text_align=TextAlign.LEFT,
            )

        dialog_box = Container(
            width=600,
            bgcolor=application_colors["background"],
            border=border.all(2, application_colors["active"]),
            border_radius=12,
            padding=20,
            content=Column(
                tight=True,
                spacing=14,
                controls=[
                    Row(
                        [Text(
                            "Настройки инспекции",
                            size=22,
                            weight=FontWeight.BOLD,
                            color=application_colors["text"],
                            text_align=TextAlign.CENTER,
                        )],
                        alignment=MainAxisAlignment.CENTER,
                    ),
                    Divider(color=application_colors["inactive"]),

                    # === Подпись перед строкой 1 ===
                    Row([_section_label("Геометрия кристаллов")],
                        alignment=MainAxisAlignment.START),

                    # Строка 1: Расстояния между кристаллами
                    Row([x_input, y_input], spacing=20, alignment=MainAxisAlignment.CENTER),

                    # === Подпись между строками 1 и 2 ===
                    Row([_section_label("Параметры задержки")],
                        alignment=MainAxisAlignment.START),

                    # Строка 2: Пороги
                    Row([threshold_xy_input, threshold_z_input], spacing=20,
                        alignment=MainAxisAlignment.CENTER),

                    # Строка 3: Рост задержки
                    Row([growth_xy_input, growth_z_input], spacing=20,
                        alignment=MainAxisAlignment.CENTER),

                    # Строка 4: Мин/макс адаптивная задержка
                    Row([min_adaptive_delay_input, max_adaptive_delay_input], spacing=20,
                        alignment=MainAxisAlignment.CENTER),

                    # Строка 5: Принудительная задержка
                    Row([post_move_delay_input], spacing=20,
                        alignment=MainAxisAlignment.CENTER),

                    Container(height=1),

                    Row([cancel_btn, apply_default_params_btn, save_btn],
                        alignment=MainAxisAlignment.CENTER, spacing=20),
                ]
            )
        )

        settings_overlay = Stack(
            controls=[
                Container(
                    width=page.width,
                    height=page.height,
                    bgcolor=Colors.with_opacity(0.4, Colors.BLACK),
                    on_click=lambda _: close_dialog()
                ),
                Container(
                    content=dialog_box,
                    alignment=alignment.center,
                    width=page.width,
                    height=page.height
                )
            ]
        )

        page.overlay.append(settings_overlay)
        page.update()

    algorithm_thread = None
    stop_event = threading.Event()
    pause_event = threading.Event()

    def run_AOI_algorithm():
        page = config.page
        try:
            while not stop_event.is_set():
                if pause_event.is_set():
                    pause_event.wait(timeout=0.5)
                    continue

                wafer_map = wafer_map_visual.wafer_map
                wafer_map.update_stats()

                count_need_check_dice = wafer_map.get_count_dice_of_status(status=DieStatus.NEED_CHECK)
                count_checked_dice = main_algorithm(
                    wafer_map_visual=wafer_map_visual,
                    robot=robot,
                    camera_manager=camera_manager,
                    config=config,
                    left_image_container=left_image_container,
                    right_image_container=right_image_container,
                    stop_event=stop_event,
                    pause_event=pause_event,
                    on_pause_request=pause_AOI_handler,
                )

                success = True
                wafer_map.update_stats()
                error_message_protocols = wafer_map.protocol.check_flag_update_files_success()
                if error_message_protocols is not None:
                    show_error("Ошибка обновления протоколов", error_message_protocols, page, config)
                    success = False

                if count_need_check_dice != count_checked_dice:
                    comparison = "МЕНЬШЕ" if count_checked_dice < count_need_check_dice else "БОЛЬШЕ"
                    error_message = (f"Количество проверенных кристаллов ({count_checked_dice}) {comparison}"
                                     f" заявленного ({count_need_check_dice})")
                    show_warning("Предупреждение", error_message, page, config)
                    success = False

                if success:
                    success_message = (f"Корректно проинспектировано {count_checked_dice} кристаллов "
                                       f"из {count_need_check_dice} запланированных.")
                    show_success("Инспекция успешно выполнена!", success_message, page, config)
                    logger.info(success_message)

                stop_AOI_handler()
                break

        except RobotException as e:
            show_error("Ошибка Манипулятора в режиме инспекции", e, page, config)
            stop_AOI_handler()

        except CameraException as e:
            show_error("Ошибка Камеры в режиме инспекции", e, page, config)
            stop_AOI_handler()

        except KnownSystemException as e:
            show_error("Системная ошибка в режиме инспекции", e, page, config)
            stop_AOI_handler()

        except Exception as e:
            show_error("Системная ошибка в режиме инспекции",
                       "Неизвестная ошибка",
                       page, config)

            logger.error(f"Ошибка в режиме инспекции: {e}")
            stop_AOI_handler()

    def start_AOI_handler(_e):
        page = _e.page

        if not (wafer_map_visual and wafer_map_visual.wafer_map):
            show_error("Ошибка моделей данных", "Отсутствуют данные по пластине. Создайте новую инспекцию.", page, config)
            return

        if config.sharpness_ideal <= 0 or wafer_map_visual.wafer_map.orientation.z_coord_of_first_reference_die is None:
            show_error("Ошибка настройки автофокуса",
                       "Эталонное значение резкости неизвестно, поскольку автофокус ни разу не был произведен",
                       page, config)
            return

        ret, error_message = wafer_map_visual.wafer_map.validate()
        if not ret:
            show_error("Ошибка калибровочных данных", error_message, page, config)
            return

        if not DiskSpaceMonitor(disk_path=detect_inspection_disk(), config=config).check_before_inspection():
            return

        wafer_map_visual.reset_all_reference_visualization()
        wafer_map_visual.inspection_active = True
        wafer_map_visual.wafer_map.update_stats()

        nonlocal algorithm_thread
        if algorithm_thread is None or not algorithm_thread.is_alive():
            stop_event.clear()
            pause_event.clear()

            disconnect_all_cams(_e)
            tab_manager.block_tabs(["Инспекция кристаллов", "Руководство оператора"])

            active_all_buttons(False)
            deactivate_scale_buttons()
            set_button_active(start_AOI_btn, False)
            set_button_active(pause_AOI_btn, True)
            set_button_active(continue_AOI_btn, False)
            set_button_active(stop_AOI_btn, True)

            time.sleep(0.5)
            algorithm_thread = threading.Thread(target=run_AOI_algorithm, daemon=True)
            algorithm_thread.start()

            wafer_map_visual.wafer_map.protocol.start_timer()
            logger.info("Инспекция запущена")

    def pause_AOI_handler(_e=None):
        if not stop_event.is_set() and not pause_event.is_set():
            if wafer_map_visual and wafer_map_visual.wafer_map:
                wafer_map_visual.wafer_map.protocol.stop_timer()

            set_button_active(pause_AOI_btn, False)
            set_button_active(continue_AOI_btn, True)
            set_button_active(update_protocol_btn, True)
            activate_scale_buttons()

            pause_event.set()
            tab_manager.show_all_tabs()
            wafer_map_visual.inspection_active = False

    def continue_AOI_handler(_e=None):
        if pause_event.is_set():
            if wafer_map_visual and wafer_map_visual.wafer_map:
                wafer_map_visual.wafer_map.protocol.start_timer()

            set_button_active(pause_AOI_btn, True)
            set_button_active(continue_AOI_btn, False)
            set_button_active(update_protocol_btn, False)
            deactivate_scale_buttons()

            pause_event.clear()
            tab_manager.block_tabs(["Инспекция кристаллов", "Руководство оператора"])
            wafer_map_visual.inspection_active = True

    def stop_AOI_handler(_e=None):
        nonlocal algorithm_thread
        if stop_event.is_set():
            return

        def execute_stop():
            nonlocal algorithm_thread
            page = config.page

            stop_event.set()
            pause_event.clear()

            left_image_container.content.src_base64 = ""
            left_image_container.update()
            right_image_container.content.src_base64 = ""
            right_image_container.update()

            wafer_map_visual.inspection_active = False
            disconnect_all_cams(_e)

            wafer_map = wafer_map_visual.wafer_map
            try:
                if wafer_map_visual and wafer_map_visual.wafer_map:
                    wafer_map_visual.wafer_map.protocol.stop_timer()
                wafer_map.protocol.update_protocol(wafer_map)
            except Exception as ex:
                show_error("Ошибка", str(ex), page, config)

            tab_manager.show_all_tabs()
            active_all_buttons(True)
            activate_scale_buttons()

            wafer_map.orientation.reset_first_reference_die(is_notify=False)
            wafer_map.orientation.reset_second_reference_die(is_notify=False)
            wafer_map.orientation.reset_rotation_angle(is_notify=True)

        if _e is None:
            execute_stop()
            return

        page = _e.page
        was_paused = pause_event.is_set()
        if not was_paused:
            pause_event.set()

        def on_confirm(e):
            page.dialog.open = False
            page.update()
            execute_stop()

        def on_cancel(e):
            if not was_paused:
                pause_event.clear()
            page.dialog.open = False
            page.update()

        show_confirmation(
            title="Остановка алгоритма",
            message="После остановки инспекции её уже не возобновить с места остановки.\nВы действительно хотите остановить алгоритм?",
            page=page,
            config=config,
            on_confirm=on_confirm,
            on_cancel=on_cancel,
            confirm_text="Подтвердить",
            cancel_text="Отмена"
        )

    def disconnect_all_cams(_e=None):
        page = config.page if _e is None else _e.page
        try:
            camera_manager.disconnect_all_cams()
        except CameraException as e:
            logger.error(f"Ошибка Камеры: {e}")
            show_error("Ошибка Камеры", e, page, config)
        except Exception as e:
            logger.error(f"Ошибка Камеры: {e}")
            show_error("Ошибка Камеры", "Неизвестная ошибка", page, config)

    def change_detectable_dice_handler(_e):
        page = _e.page

        if wafer_map_visual is None or wafer_map_visual.wafer_map is None:
            return

        wafer_map = wafer_map_visual.wafer_map
        current_selected_list = wafer_map.symbols_need_check

        # --- Динамический подсчет статистики (только для выделенной зоны, если она есть) ---
        symbol_stats = {}
        for row in range(wafer_map.total_rows):
            for col in range(wafer_map.total_cols):
                die = wafer_map.die_matrix[row][col]
                if not die or not die.symbol: continue
                
                # Фильтруем по выделенной области
                if wafer_map_visual.selected_area_dice_ids is not None:
                    if die.id not in wafer_map_visual.selected_area_dice_ids:
                        continue
                        
                symbol = die.symbol.translate(str.maketrans('', '', string.digits))
                symbol_stats[symbol] = symbol_stats.get(symbol, 0) + 1

        if not symbol_stats or current_selected_list is None:
            show_error("Ошибка", "Невозможно определить типы (выделенная область пуста)", _e.page, config)
            return

        has_inspected_dice = (
                wafer_map.get_count_dice_of_status(DieStatus.BAD) > 0 or
                wafer_map.get_count_dice_of_status(DieStatus.GOOD) > 0
        )

        if not hasattr(change_detectable_dice_handler, '_original_symbols_list_initialized'):
            if has_inspected_dice:
                change_detectable_dice_handler._original_symbols_list = current_selected_list.copy()
            else:
                change_detectable_dice_handler._original_symbols_list = None
            change_detectable_dice_handler._original_symbols_list_initialized = True

        available_symbols = [
            (symbol, count) for symbol, count in symbol_stats.items()
            if symbol != 'D'
        ]
        available_symbols.sort(key=lambda x: x[1], reverse=True)

        sorted_symbol_stats = {symbol: count for symbol, count in available_symbols}
        sorted_symbols_list = [symbol for symbol, _ in available_symbols]

        current_selected_set = set(current_selected_list) if current_selected_list else set()
        checkbox_states = {symbol: symbol in current_selected_set for symbol in sorted_symbols_list}
        checkboxes = []

        def create_checkbox(symbol: str):
            count = sorted_symbol_stats.get(symbol, 0)
            label_text = f"{symbol} ({count})"

            return Checkbox(
                label=label_text,
                value=checkbox_states[symbol],
                on_change=lambda e, s=symbol: toggle_checkbox(s, e.control.value),
                label_style=TextStyle(size=22, color=application_colors["text"]),
                fill_color={ControlState.DEFAULT: application_colors["active"]},
                check_color=application_colors["background"],
            )

        def toggle_checkbox(symbol: str, value: bool):
            checkbox_states[symbol] = value

        for symbol in sorted_symbols_list:
            checkboxes.append(create_checkbox(symbol))
            checkboxes.append(Container(height=5))

        checkboxes_column = Column(
            controls=checkboxes,
            spacing=0,
            horizontal_alignment=CrossAxisAlignment.START,
            scroll=ScrollMode.AUTO if len(sorted_symbols_list) > 8 else None,
            height=300 if len(sorted_symbols_list) > 8 else None,
        )

        save_btn = create_button(active=True, text="Сохранить", width=140, height=48)
        cancel_btn = create_button(active=True, text="Отмена", width=140, height=48)

        save_btn.on_click = lambda e: save_selection()
        cancel_btn.on_click = lambda e: close_dialog()

        def save_selection():
            selected_list = [s for s, state in checkbox_states.items() if state]
            config.symbols_need_check = selected_list
            wafer_map_visual.update_symbols_need_check(selected_list)
            close_dialog()

        def restore_original_list():
            if hasattr(change_detectable_dice_handler, '_original_symbols_list') and change_detectable_dice_handler._original_symbols_list is not None:
                original_list = change_detectable_dice_handler._original_symbols_list
                config.symbols_need_check = original_list

                wafer_map.symbols_need_check = original_list

                for row in range(wafer_map.total_rows):
                    for col in range(wafer_map.total_cols):
                        die = wafer_map.die_matrix[row][col]
                        if die and die.symbol:
                            new_status = wafer_map.determine_die_status(die.symbol)
                            
                            # Не "воскрешаем" кристаллы вне выделенной зоны!
                            if wafer_map_visual.selected_area_dice_ids is not None and die.id not in wafer_map_visual.selected_area_dice_ids:
                                new_status = DieStatus.SKIP
                                
                            if die.status != new_status:
                                die.status = new_status
                                if new_status == DieStatus.BAD: die.symbol = "FV"
                                elif new_status == DieStatus.GOOD: die.symbol = "PV"
                                wafer_map_visual.update_visual_die(die, is_need_update_canvas=False)

                if wafer_map_visual._canvas_ref:
                    wafer_map_visual._canvas_ref.update()
                wafer_map.update_stats()
            close_dialog()

        def close_dialog():
            if dialog_stack in page.overlay:
                page.overlay.remove(dialog_stack)
            page.update()

        buttons_row_controls = [save_btn, cancel_btn]

        if hasattr(change_detectable_dice_handler, '_original_symbols_list') and change_detectable_dice_handler._original_symbols_list is not None:
            current_selected = [s for s, state in checkbox_states.items() if state]
            original_list = change_detectable_dice_handler._original_symbols_list

            if set(current_selected) != set(original_list):
                restore_btn = create_button(
                    active=True, text="Вернуться к изначальному списку", width=420, height=48, text_style=TextStyle(size=22, weight=FontWeight.BOLD)
                )
                restore_btn.on_click = lambda e: restore_original_list()
                buttons_row_controls.append(restore_btn)

        # Текст заголовка зависит от того, выделена ли область
        area_text = "в выделенной области" if wafer_map_visual.selected_area_dice_ids is not None else "на пластине"

        dialog_content = Column(
            controls=[
                Container(
                    content=Text(
                        "Выберите типы кристаллов, которые нужно инспектировать",
                        size=22, weight=FontWeight.BOLD, color=application_colors["text"], text_align=TextAlign.CENTER,
                    ),
                    alignment=alignment.center, padding=padding.only(bottom=10),
                ),
                Container(
                    content=Column(
                        controls=[
                            Text(f"Всего типов {area_text}: {len(sorted_symbol_stats)}", size=20, color=application_colors["text"], italic=True),
                            Text(f"Всего не фиктивных кристаллов {area_text}: {sum(sorted_symbol_stats.values())}", size=20, color=application_colors["text"], italic=True),
                        ],
                        spacing=5,
                    ),
                    alignment=alignment.center, padding=padding.only(bottom=5),
                ),
                Container(
                    content=checkboxes_column, padding=padding.all(20), alignment=alignment.center,
                ),
                Row(controls=buttons_row_controls, alignment=MainAxisAlignment.CENTER, spacing=10, wrap=True),
            ],
            spacing=0, horizontal_alignment=CrossAxisAlignment.CENTER,
        )

        has_restore_btn = len(buttons_row_controls) > 2
        dialog_width = 500 if has_restore_btn else 460
        dialog_height = 320 + len(sorted_symbols_list) * 45 if has_restore_btn else 280 + len(sorted_symbols_list) * 45
        left_column_width = width_image + 40
        dialog_left = (left_column_width - dialog_width) / 2

        dialog_stack = Stack(
            controls=[
                Container(width=page.width, height=page.height, bgcolor=Colors.with_opacity(0.3, Colors.BLACK), on_click=lambda e: close_dialog()),
                Container(
                    width=dialog_width, height=dialog_height, bgcolor=application_colors["background"],
                    border_radius=2, border=border.all(2, application_colors["text"]), padding=20,
                    left=dialog_left + 40, top=page.height / 2 - dialog_height / 2, content=dialog_content,
                )
            ]
        )

        page.overlay.append(dialog_stack)
        page.update()

    def active_all_buttons(active: bool):
        admin_allowed = is_admin_access()
        buttons = [
            create_new_inspection_btn,
            settings_btn,
            change_detectable_dice_btn,
            update_protocol_btn,
            start_AOI_btn,
            pause_AOI_btn,
            continue_AOI_btn,
            stop_AOI_btn,
            reset_area_btn
        ]

        if not active:
            for btn in buttons:
                btn_key = btn.text if btn.text else str(id(btn))
                buttons_state_cache[btn_key] = not btn.disabled

            for btn in buttons:
                set_button_active(btn, False)
        else:
            for btn in buttons:
                btn_key = btn.text if btn.text else str(id(btn))

                if btn_key in buttons_state_cache:
                    if btn in (create_new_inspection_btn, settings_btn):
                        set_button_active(btn, admin_allowed and buttons_state_cache[btn_key])
                    else:
                        set_button_active(btn, buttons_state_cache[btn_key])
                else:
                    set_button_active(btn, False)

            buttons_state_cache.clear()

    def update_scale_button_highlight():
        scale_mapping = {1.0: 0, 1.5: 1, 2.0: 2}
        for btn in scale_buttons:
            btn.bgcolor = application_colors["inactive"]
        scale_buttons[scale_mapping.get(config.scale_buttons_panel, 0)].bgcolor = application_colors["active"]
        for btn in scale_buttons:
            if getattr(btn, "page", None) is not None:
                try:
                    btn.update()
                except Exception:
                    pass

    def activate_scale_buttons():
        for btn in scale_buttons:
            btn.disabled = False
            btn.bgcolor = application_colors["inactive"]
            btn.color = application_colors["text"]
        update_scale_button_highlight()

    def deactivate_scale_buttons():
        for btn in scale_buttons:
            btn.disabled = True
            btn.bgcolor = application_colors["top_bar"]
            btn.color = application_colors["unclickable"]
        for btn in scale_buttons:
            if getattr(btn, "page", None) is not None:
                try:
                    btn.update()
                except Exception:
                    pass

    def scale_changed(e, scale_value):
        if scale_buttons[0].disabled:
            return
        nonlocal wafer_map_visual
        if config.scale_buttons_panel == scale_value or wafer_map_visual is None or wafer_map_visual.wafer_map is None:
            return

        page = e.page
        deactivate_scale_buttons()
        active_all_buttons(False)
        dynamic_grid_container.content = loading_container
        page.update()

        async def load_wafer_map_async():
            try:
                grid_view = wafer_map_visual.generate_visual(scale_value=scale_value)
                if grid_view is not None:
                    button_grid.content = grid_view
                    dynamic_grid_container.content = button_grid
                    config.scale_buttons_panel = scale_value
                    update_scale_button_highlight()
                await page.update_async()
            except Exception as ex:
                logger.error(f"Ошибка при изменении масштаба: {ex}")
                dynamic_grid_container.content = button_grid
            finally:
                active_all_buttons(True)
                activate_scale_buttons()
                await page.update_async()

        time.sleep(0.1)
        page.run_task(load_wafer_map_async)

    # === ПРИВЯЗКА ОБРАБОТЧИКОВ ===

# === ПРИВЯЗКА ОБРАБОТЧИКОВ ===

    def toggle_selection_mode_handler(_e):
        page = _e.page
        
        # Проверяем, загружена ли карта
        if not wafer_map_visual or not wafer_map_visual.wafer_map:
            # Если нет, выводим стандартное предупреждение в стиле проекта
            show_warning(
                "Карта не загружена", 
                "Режим выделения недоступен.\nСначала создайте новую инспекцию и загрузите карту годности.", 
                page, config
            )
            # Возвращаем тумблер в выключенное состояние
            selection_mode_switch.value = False
            selection_mode_switch.update()
            return
            
        wafer_map_visual.toggle_selection_mode(selection_mode_switch.value)

    def reset_area_handler(_e):
        if not wafer_map_visual or not wafer_map_visual.wafer_map:
            return
            
        # 1. Принудительно стираем старые метки референсных кристаллов ("1" и "2")
        wafer_map_visual.reset_all_reference_visualization()
        
        # 2. Возвращаем исходные цвета и статусы (убираем серый фон с отключенных)
        wafer_map_visual.clear_inspection_area()
        
        # 3. Сбрасываем референсный кристалл на изначальное положение (автоматический поиск)
        auto_set_first_reference_die(wafer_map_visual.wafer_map, wafer_map_visual)
        
        selection_mode_switch.value = False # Автоматически выключаем режим выделения при сбросе
        wafer_map_visual.toggle_selection_mode(False)
        config.page.update()
        
    def on_selection_complete(start_die):
        """Коллбэк, который срабатывает после того, как пользователь нарисовал прямоугольник."""
        if start_die:
            wafer_map_visual.wafer_map.orientation.update_first_reference_die(start_die)
            wafer_map_visual._update_reference_visualization(start_die)
            
            # Выключаем режим выделения, чтобы можно было снова двигать карту
            selection_mode_switch.value = False
            wafer_map_visual.toggle_selection_mode(False)
            config.page.update()

    selection_mode_switch.on_change = toggle_selection_mode_handler
    reset_area_btn.on_click = reset_area_handler

    create_new_inspection_btn.on_click = lambda e: create_new_inspection_handler(e)

    checkbox_container = strict_validation_checkbox.content.controls[0]
    checkbox_container.on_click = lambda e: toggle_strict_validation_handler(e)

    settings_btn.on_click = lambda e: open_settings_handler(e)

    update_protocol_btn.on_click = lambda e: wafer_map_visual.wafer_map.protocol.update_protocol(
        wafer_map_visual.wafer_map)
    change_detectable_dice_btn.on_click = lambda e: change_detectable_dice_handler(e)

    start_AOI_btn.on_click = lambda e: start_AOI_handler(e)
    pause_AOI_btn.on_click = lambda e: pause_AOI_handler(e)
    continue_AOI_btn.on_click = lambda e: continue_AOI_handler(e)
    stop_AOI_btn.on_click = lambda e: stop_AOI_handler(e)

    scale_buttons[0].on_click = lambda e: scale_changed(e, 1.0)
    scale_buttons[1].on_click = lambda e: scale_changed(e, 1.5)
    scale_buttons[2].on_click = lambda e: scale_changed(e, 2.0)

    return workspace_tab