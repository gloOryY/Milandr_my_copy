import flet
from flet import *
from typing import Dict

from project.algorithms.autocentering import autocentering, crop_frame_on_die
from project.algorithms.autofocusing import autofocusing_extended, autofocusing_standard
from project.application.addition.colors import color_mode
from project.application.addition.exceptions import CameraException, RobotException, KnownSystemException
from project.application.addition.loadings import get_path
from project.application.addition.dialogs import show_error, show_success, show_warning
from project.application.addition.photo_viewer import open_frame_in_viewer
from project.application.data_work.wafer_data import WaferMap, Die
from project.configuration.config_manager import ConfigManager
from project.station.camera.camera_manager import CameraManager
from project.station.camera.frame_capture import get_base64_from_frame, capture_frame, rotate_frame
from project.application.addition.logger import logger
from project.station.robot.movements import move_robot_to_coordinates, robot_to_home
from project.station.robot.robot_command_queue import robot_command_queue
from project.station.robot.robot_controller import RobotController
from project.application.tab_manager import tab_manager

CAMERA_CLICKED = False
IS_MOCK_ROBOT = False


def create_calibration_layer(config: 'ConfigManager',
                             camera_manager: 'CameraManager',
                             robot: 'RobotController') -> flet.Tab:
    """
    Функция-конструктор вкладки "Калибровка системы".

    :param config: Класс конфигураций
    :param camera_manager: Класс-менеджер камер
    :param robot: Класс робота-манипулятора
    :return: flet.Tab calibration_tab
    """
    application_colors = color_mode(config)
    step_buttons = []
    button_titles = [" ", "↑", " ", "↑", "⌂ ВСЕ", "←", "⌂ XY", "→", "⌂ Z", "⌂ X", " ", "↓", " ", "↓", "⌂ Y"]
    tooltips = [
        "",
        "Движение камеры вперёд вдоль палеты на заданную величину шага в мм",
        "",
        "Движение камеры от палеты на заданную величину шага в мм",
        "Движение камеры на нулевые координаты по всем осям",
        "Движение камеры влево вдоль палеты на заданную величину шага в мм",
        "Движение камеры на нулевые координаты в плоскости палеты",
        "Движение камеры вправо вдоль палеты на заданную величину шага в мм",
        "Движение камеры на нулевые координаты по высоте",
        "Движение камеры на нулевые координаты по горизонтали вдоль палеты",
        "",
        "Движение камеры назад вдоль палеты на заданную величину шага в мм",
        "",
        "Движение камеры к палете на заданную величину шага в мм",
        "Движение камеры на нулевые координаты по вертикали вдоль палеты",
    ]
    wafer_map = WaferMap.get_instance()
    orientation = wafer_map.orientation

    # === БАЗОВЫЕ ГРАФИЧЕСКИЕ ЭЛЕМЕНТЫ С ПОДДЕРЖКОЙ СОСТОЯНИЙ ===

    def create_button(active: bool = True, button_type: str = "calibration", **kwargs) -> ElevatedButton:
        """
        Универсальная функция создания кнопок с поддержкой состояний

        :param active: True - активная кнопка, False - неактивная
        :param button_type: тип кнопки ("calibration", "grid", "step", "default")
        :param kwargs: дополнительные параметры для переопределения
        :return: настроенная кнопка
        """
        custom_text_size = kwargs.pop('text_size', None)

        button_configs = {
            "calibration": {
                "radius": 10,
                "text_size": custom_text_size if custom_text_size else 22,
                "width": 120,
                "height": 48,
            },
            "grid": {
                "radius": 8,
                "text_size": custom_text_size if custom_text_size else 22,
                "width": 110,
                "height": 110,
            },
            "default": {
                "radius": 20,
                "text_size": custom_text_size if custom_text_size else 22,
                "width": 120,
                "height": 48,
            }
        }

        config_btn = button_configs.get(button_type, button_configs["default"])

        if active:
            bg_color = application_colors["inactive"]
            text_color = application_colors["text"]
            disabled = False
        else:
            bg_color = application_colors["top_bar"]
            text_color = application_colors["unclickable"]
            disabled = True

        base_style = ButtonStyle(
            shape=RoundedRectangleBorder(radius=config_btn["radius"]),
            overlay_color=application_colors["hover"],
            bgcolor=bg_color,
            color=text_color,
            text_style=TextStyle(
                size=config_btn["text_size"],
                weight=FontWeight.BOLD
            ),
            animation_duration=300,
        )

        base_params = {
            "width": config_btn["width"],
            "height": config_btn["height"],
            "style": base_style,
            "disabled": disabled
        }

        base_params.update(kwargs)
        return ElevatedButton(**base_params)

    def set_button_active(button: ElevatedButton, active: bool = True):
        """
        Устанавливает состояние кнопки (активная/неактивная)

        :param button: кнопка для изменения состояния
        :param active: True - активная, False - неактивная
        """
        if (button == save_coords_btn and active and wafer_map.die_prev_ref is not None
                or button == save_coords_btn and wafer_map.wafer_id == ""):
            return

        if active:
            button.bgcolor = application_colors["inactive"]
            button.color = application_colors["text"]
            button.disabled = False
        else:
            button.bgcolor = application_colors["top_bar"]
            button.color = application_colors["unclickable"]
            button.disabled = True

        button.update()

    # === ГРАФИЧЕСКИЕ ЭЛЕМЕНТЫ ===

    # === Контейнеры для изображений и кнопки управления ими ===

    height_image = 860
    width_image = 600

    # Транслируемое изображение с камеры
    camera_container = Container(
        content=Image(src=get_path(False), fit=ImageFit.FILL, height=height_image, width=width_image),
        height=height_image,
        width=width_image,
        bgcolor=application_colors["background"],
        border_radius=10,
        alignment=alignment.center,
    )

    # Кнопка увеличения в правом верхнем углу
    camera_enlarge_btn = Container(
        content=IconButton(
            icon=Icons.CROP_FREE,
            icon_size=30,
            tooltip="Открыть изображение в полном размере",
            style=ButtonStyle(
                color=Colors.WHITE,
                bgcolor=Colors.with_opacity(0.3, Colors.BLACK),
                shape=RoundedRectangleBorder(radius=15),
            )
        ),
        top=10,
        right=10,
    )

    # Кнопка увеличения и обрезки фотографии по границам кристалла (в правом верхнем углу)
    camera_enlarge_and_crop_die_btn = Container(
        content=IconButton(
            icon=Icons.CENTER_FOCUS_STRONG,
            icon_size=30,
            tooltip="Открыть обрезанное по границам кристалла изображение в полном размере",
            style=ButtonStyle(
                color=Colors.WHITE,
                bgcolor=Colors.with_opacity(0.3, Colors.BLACK),
                shape=RoundedRectangleBorder(radius=15),
            )
        ),
        top=10,
        right=70,
    )

    camera_stack = Stack(
        controls=[camera_container],
        height=height_image,
        width=width_image,
    )

    # Кнопки для работы с камерой
    camera_buttons = Row(
        controls=[
            create_button(
                active=True,
                button_type="calibration",
                text="Подключить камеру",
                width=250,
                height=48
            ),
            create_button(
                active=False,
                button_type="calibration",
                text="Отключить камеру",
                width=250,
                height=48
            ),
        ],
        alignment=MainAxisAlignment.CENTER,
        spacing=30,
    )

    # Левая часть вкладки с камерой
    left_column = Column(
        controls=[
            camera_stack,
            camera_buttons,
        ],
        alignment=MainAxisAlignment.CENTER,
        horizontal_alignment=CrossAxisAlignment.CENTER,
        expand=True,
    )

    # Текст заголовка над сеткой кнопок
    control_panel_title = Text(
        "Пульт управления манипулятором",
        size=26,
        weight=FontWeight.BOLD,
        color=application_colors["text"]
    )

    # Сетка кнопок, управляющих движением манипулятора во время калибровки
    button_grid = Column(
        controls=[
            Row(
                controls=[
                    create_button(
                        active=False,
                        button_type="grid",
                        text=button_titles[i * 5 + j],
                        tooltip=tooltips[i * 5 + j],
                        opacity=0 if button_titles[i * 5 + j] == " " else 1,
                        disabled=True,
                        text_size=30
                    )
                    for j in range(5)
                ],
                alignment=alignment.center
            )
            for i in range(3)
        ],
        alignment=alignment.center
    )

    move_to_first_ref_die_switch = Row(
        spacing=5,
        controls=[
            Container(
                content=Text(
                    "Перемещение на референсный кристалл включено",
                    size=22,
                    weight=FontWeight.W_500,
                    color=Colors.WHITE
                ),
                width=600,
            ),
            Switch(
                value=config.move_to_first_ref_die_switch,
                active_color=application_colors["active"],
                inactive_thumb_color=application_colors["unclickable"],
            )
        ],
        alignment=MainAxisAlignment.START,
        vertical_alignment=CrossAxisAlignment.CENTER,
    )

    def create_step_button(text, value, position, is_icon=False, icon_name=None):
        """
        Создает кнопку шага в стиле второго слоя

        :param text: Текст на кнопке
        :param value: Значение шага
        :param position: Позиция ("first", "middle", "last")
        :param is_icon: Является ли кнопка иконкой
        :param icon_name: Имя иконки (если is_icon=True)
        :return: ElevatedButton
        """
        step_button_configs = {
            "first": {"radius": border_radius.only(12, 0, 12, 0)},
            "middle": {"radius": 0},
            "last": {"radius": border_radius.only(0, 12, 0, 12)},
        }

        config_btn = step_button_configs[position]

        if is_icon:
            return ElevatedButton(
                content=Icon(
                    name=icon_name,
                    size=24,
                    color=application_colors["unclickable"],  # Начальный цвет
                ),
                width=104,
                height=40,
                style=ButtonStyle(
                    shape=RoundedRectangleBorder(radius=config_btn["radius"]),
                    overlay_color=application_colors["hover"],
                    bgcolor=application_colors["top_bar"],
                    animation_duration=300,
                ),
                disabled=True,
                on_click=lambda e: step_changed(e, value),
                tooltip=f"Шаг равен размеру кристалла "
                        f"({config.wafer_params['x_distance']}×{config.wafer_params['y_distance']} мм)",
            )

        return ElevatedButton(
            text=text,
            width=104,
            height=40,
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=config_btn["radius"]),
                overlay_color=application_colors["hover"],
                bgcolor=application_colors["top_bar"],
                color=application_colors["unclickable"],
                text_style=TextStyle(size=22, weight=FontWeight.BOLD),
                animation_duration=300,
            ),
            disabled=True,
            on_click=lambda e: step_changed(e, value)
        )

    # Создаем step_block
    step_block = Row(
        controls=[
            Text(value="Шаг (мм):", size=22, weight=FontWeight.BOLD, color=application_colors["text"]),
            Container(width=12),
            create_step_button("0.01", 0.01, "first"),
            create_step_button("0.1", 0.1, "middle"),
            create_step_button("1", 1, "middle"),
            create_step_button("10", 10, "middle"),
            create_step_button("", "crystal_size", "last", is_icon=True, icon_name=Icons.FLIP_TO_FRONT),
        ],
        alignment=MainAxisAlignment.CENTER,
        spacing=2
    )

    step_buttons = []
    for control in step_block.controls[2:]:
        step_buttons.append(control)

    def create_label_row(start, end):
        """Создаёт строку с метками для ползунка."""
        step = ((abs(end - start) - 1) // 200 + 1) * 10
        return Row(
            controls=[
                Text(str(i), width=30, text_align=TextAlign.CENTER, weight=FontWeight.W_500, size=16)
                for i in range(start, end + 1, step)
            ],
            width=800,
            alignment=MainAxisAlignment.SPACE_BETWEEN
        )

    def create_slider(letter, min_value, max_value, label_row, tooltip):
        """Создаёт ползунок с метками и описанием."""
        return Column(
            controls=[
                Row(
                    controls=[
                        Text(
                            value=f"{letter.upper()}: {0:.2f}",
                            size=22,
                            weight=FontWeight.BOLD,
                            color=application_colors["text"],
                            width=110
                        ),
                        Stack(
                            controls=[
                                Slider(
                                    value=0,
                                    min=min_value,
                                    max=max_value,
                                    width=800,
                                    disabled=True,
                                    tooltip=tooltip
                                ),
                                Container(
                                    content=label_row,
                                    margin=margin.only(top=-10)
                                )
                            ],
                            width=800,
                            height=50,
                        ),
                    ],
                    alignment=alignment.center
                ),
            ],
            alignment=alignment.center,
            spacing=5
        )

    # Метки для осей
    label_x = create_label_row(config.extreme_coordinates["x_min"], config.extreme_coordinates["x_max"])
    label_y = create_label_row(config.extreme_coordinates["y_min"], config.extreme_coordinates["y_max"])
    label_z = create_label_row(config.extreme_coordinates["z_min"], config.extreme_coordinates["z_max"])

    # Создание ползунков для осей
    x_axis = create_slider("x", config.extreme_coordinates["x_min"], config.extreme_coordinates["x_max"],
                           label_x, "По оси X осуществляется движение влево/вправо вдоль палеты")
    y_axis = create_slider("y", config.extreme_coordinates["y_min"], config.extreme_coordinates["y_max"],
                           label_y, "По оси Y осуществляется движение вперёд/назад вдоль палеты")
    z_axis = create_slider("z", config.extreme_coordinates["z_min"], config.extreme_coordinates["z_max"],
                           label_z, "По оси Z осуществляется приближение/удаление камеры от палеты")

    calibration_btn = create_button(
        active=True,
        button_type="calibration",
        width=400,
        height=48,
        text="Откалибровать манипулятор"
    )

    # Средняя часть с управлением манипулятора во вкладке
    middle_column = Column(
        controls=[
            # Пульт управления
            control_panel_title,
            Container(height=24),
            button_grid,
            Container(height=32),
            step_block,  # Выбор шага
            Container(height=16),

            # Ползунки осей
            x_axis,
            Container(height=8),
            y_axis,
            Container(height=8),
            z_axis,
            Container(height=8),
            move_to_first_ref_die_switch,
            Container(height=2),
            calibration_btn
        ],
        alignment=MainAxisAlignment.CENTER,
        horizontal_alignment=CrossAxisAlignment.CENTER,
    )

    # Текстовые элементы для отображения информации о референсных объектах
    die_1_coords_text = Text(
        "не определены",
        size=20,
        weight=FontWeight.W_400,
        color=application_colors["text"]
    )

    die_1_index_text = Text(
        "не выбран",
        size=20,
        weight=FontWeight.W_400,
        color=application_colors["text"]
    )

    die_2_coords_text = Text(
        "не определены",
        size=20,
        weight=FontWeight.W_400,
        color=application_colors["text"]
    )

    die_2_index_text = Text(
        "не выбран",
        size=20,
        weight=FontWeight.W_400,
        color=application_colors["text"]
    )

    rotation_angle_text = Text(
        "не определён",
        size=20,
        weight=FontWeight.W_400,
        color=application_colors["text"]
    )

    # Референсные координаты
    reference_die_container = RadioGroup(
        content=Column(
            controls=[
                # Референсный кристалл № 1
                Container(
                    content=Column(
                        controls=[
                            Row(
                                controls=[
                                    Text(
                                        "Референсный кристалл № 1",
                                        size=22,
                                        weight=FontWeight.BOLD,
                                        color=application_colors["text"],
                                        expand=True,
                                    ),
                                ],
                                alignment=MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=CrossAxisAlignment.CENTER,
                            ),
                            Container(height=8),
                            Row(
                                controls=[
                                    Container(
                                        content=Radio(value="1"),
                                        tooltip="Установка текущего кристалла как первого референсного",
                                        width=24,
                                    ),
                                    Container(
                                        width=260,
                                        content=Column(
                                            controls=[
                                                Row(
                                                    controls=[
                                                        Text(
                                                            "Координаты:",
                                                            size=22,
                                                            weight=FontWeight.W_500,
                                                            color=application_colors["text"],
                                                            width=150,
                                                        ),
                                                        die_1_coords_text,
                                                    ],
                                                    spacing=5,
                                                ),
                                                Container(height=4),
                                                Row(
                                                    controls=[
                                                        Text(
                                                            "Индекс:",
                                                            size=22,
                                                            weight=FontWeight.W_500,
                                                            color=application_colors["text"],
                                                            width=150,
                                                        ),
                                                        die_1_index_text,
                                                    ],
                                                    spacing=5,
                                                ),
                                            ],
                                            spacing=0,
                                        ),
                                    ),
                                ],
                                spacing=10,
                                vertical_alignment=CrossAxisAlignment.START,
                            ),
                        ],
                        spacing=0,
                    ),
                    padding=16,
                    bgcolor=application_colors["top_bar"],
                    border_radius=8,
                    width=360,
                ),
                Container(height=8),
                # Референсный кристалл № 2
                Container(
                    content=Column(
                        controls=[
                            Row(
                                controls=[
                                    Text(
                                        "Референсный кристалл № 2",
                                        size=22,
                                        weight=FontWeight.BOLD,
                                        color=application_colors["text"],
                                        expand=True,
                                    ),
                                ],
                                alignment=MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=CrossAxisAlignment.CENTER,
                            ),
                            Container(height=8),
                            Row(
                                controls=[
                                    Container(
                                        content=Radio(value="2"),
                                        tooltip="Установка текущего кристалла как второго референсного",
                                        width=24,
                                    ),
                                    Container(
                                        width=260,
                                        content=Column(
                                            controls=[
                                                Row(
                                                    controls=[
                                                        Text(
                                                            "Координаты:",
                                                            size=22,
                                                            weight=FontWeight.W_500,
                                                            color=application_colors["text"],
                                                            width=150,
                                                        ),
                                                        die_2_coords_text,
                                                    ],
                                                    spacing=5,
                                                ),
                                                Container(height=4),
                                                Row(
                                                    controls=[
                                                        Text(
                                                            "Индекс:",
                                                            size=22,
                                                            weight=FontWeight.W_500,
                                                            color=application_colors["text"],
                                                            width=150,
                                                        ),
                                                        die_2_index_text,
                                                    ],
                                                    spacing=5,
                                                ),
                                            ],
                                            spacing=0,
                                        ),
                                    ),
                                ],
                                spacing=10,
                                vertical_alignment=CrossAxisAlignment.START,
                            ),
                        ],
                        spacing=0,
                    ),
                    padding=16,
                    bgcolor=application_colors["top_bar"],
                    border_radius=8,
                    width=360,
                ),
            ],
        ),
        value="1"
    )

    # Контейнер с углом поворота
    rotation_angle_container = Container(
        content=Row(
            controls=[
                Text(
                    "Угол поворота: ",
                    size=22,
                    weight=FontWeight.W_500,
                    color=application_colors["text"]
                ),
                rotation_angle_text,
            ],
            spacing=10,
            alignment=MainAxisAlignment.CENTER,
        ),
        padding=16,
        bgcolor=application_colors["top_bar"],
        border_radius=8,
        width=360,
    )

    # Создаем кнопку автофокусировки отдельно
    autofocus_btn = create_button(
        active=False,
        button_type="calibration",
        width=250,
        height=40,
        text="Запустить"
    )

    # Используем эту кнопку в RadioGroup
    autofocus_radio_group = RadioGroup(
        content=Column(
            controls=[
                Row(
                    controls=[
                        Text(
                            "Автофокусировка",
                            size=24,
                            weight=FontWeight.BOLD,
                            color=application_colors["text"],
                            expand=True,
                            text_align=TextAlign.CENTER,
                        ),
                    ],
                    alignment=MainAxisAlignment.CENTER,
                    vertical_alignment=CrossAxisAlignment.CENTER,
                ),
                Container(height=8),
                Row(
                    controls=[
                        Container(
                            content=Radio(value="extended"),
                            tooltip="Расширенная автофокусировка",
                            width=24,
                        ),
                        Container(
                            content=Text(
                                "Расширенная",
                                size=22,
                                weight=FontWeight.W_500,
                                color=application_colors["text"],
                            ),
                            padding=padding.only(left=8),
                        ),
                    ],
                    spacing=0,
                    vertical_alignment=CrossAxisAlignment.CENTER,
                ),
                Container(height=4),
                Row(
                    controls=[
                        Container(
                            content=Radio(value="standard"),
                            tooltip="Стандартная автофокусировка",
                            width=24,
                        ),
                        Container(
                            content=Text(
                                "Стандартная",
                                size=22,
                                weight=FontWeight.W_500,
                                color=application_colors["text"],
                            ),
                            padding=padding.only(left=8),
                        ),
                    ],
                    spacing=0,
                    vertical_alignment=CrossAxisAlignment.CENTER,
                ),
                Container(height=16),
                autofocus_btn  # Используем сохраненную кнопку
            ],
            spacing=0,
            alignment=MainAxisAlignment.CENTER,
            horizontal_alignment=CrossAxisAlignment.CENTER,
        ),
        value="extended"
    )

    autofocus_container = Container(
        content=autofocus_radio_group,
        padding=16,
        bgcolor=application_colors["top_bar"],
        border_radius=8,
        width=280,
    )

    # Создаем кнопку центрирования отдельно
    centering_btn = create_button(
        active=False,
        button_type="calibration",
        width=250,
        height=40,
        text="Запустить"
    )

    # Автоцентровка
    centering_container = Container(
        content=Column(
            controls=[
                Text(
                    "Автоцентровка",
                    size=24,
                    weight=FontWeight.BOLD,
                    color=application_colors["text"],
                    text_align=TextAlign.CENTER,
                ),
                Container(height=8),
                centering_btn
            ],
            spacing=4,
            alignment=MainAxisAlignment.CENTER,
            horizontal_alignment=CrossAxisAlignment.CENTER,
        ),
        padding=16,
        bgcolor=application_colors["top_bar"],
        border_radius=8,
        width=280,
    )

    save_coords_btn = create_button(
        active=False,
        button_type="calibration",
        width=280,
        height=48,
        text="Сохранить координаты"
    )

    # === СЛУШАТЕЛЬ ДЛЯ БЛОКИРОВКИ save_coords_btn ===

    def on_die_prev_ref_changed():
        """Callback при изменении опорного кристалла"""
        if wafer_map.die_prev_ref is not None:
            set_button_active(save_coords_btn, False)
        elif robot.is_homed:
            set_button_active(save_coords_btn, True)

    orientation.add_listener(on_die_prev_ref_changed)
    on_die_prev_ref_changed()

    # Правая часть вкладки с информацией о референсных объектах
    right_column = Column(
        controls=[
            Container(height=8),
            Text(
                "Референсные кристаллы",
                size=26,
                weight=FontWeight.BOLD,
                color=application_colors["text"]
            ),
            Container(height=4),
            reference_die_container,
            Container(height=4),
            rotation_angle_container,
            Container(height=4),
            Container(
                content=save_coords_btn,
                bgcolor=application_colors["top_bar"],
                border_radius=8,
                width=320,
            ),
            Container(height=4),
            autofocus_container,
            Container(height=4),
            centering_container,
        ],
        alignment=MainAxisAlignment.START,
        horizontal_alignment=CrossAxisAlignment.CENTER,
    )

    calibration_tab = Tab(
        text="Калибровка системы",
        content=Container(
            content=Row(
                controls=[
                    left_column,
                    Container(width=2),
                    middle_column,
                    right_column,
                ],
                alignment=MainAxisAlignment.CENTER,
                vertical_alignment=CrossAxisAlignment.START,
                expand=True,
            ),
            bgcolor=application_colors["background"],
            expand=True,
        ),
    )

    # === ЛОГИКА ОБРАБОТКИ ===

    def update_reference_die_display():
        """Обновляет отображение данных референсных кристаллов и угла поворота"""
        try:
            # Координаты первого референсного кристалла
            if orientation.is_coordinates_of_first_reference_die():
                die_1_coords_text.value = (f"({orientation.x_coord_of_first_reference_die:.2f}, "
                                           f"{orientation.y_coord_of_first_reference_die:.2f})")
            else:
                die_1_coords_text.value = "не определены"

            # Индекс первого референсного кристалла
            if orientation.is_first_reference_cell():
                die_1_index_text.value = f"{orientation.first_reference_die.id}"
            else:
                die_1_index_text.value = "не выбран"

            # Координаты второго референсного кристалла
            if orientation.is_coordinates_of_second_reference_die():
                die_2_coords_text.value = (f"({orientation.x_coord_of_second_reference_die:.2f}, "
                                           f"{orientation.y_coord_of_second_reference_die:.2f})")
            else:
                die_2_coords_text.value = "не определены"

            # Индекс второго референсного кристалла
            if orientation.is_second_reference_cell():
                die_2_index_text.value = f"{orientation.second_reference_die.id}"
            else:
                die_2_index_text.value = "не выбран"

            # Угол поворота
            if orientation.angle_deg is not None:
                rotation_angle_text.value = f"{orientation.angle_deg:.3f}°"
            else:
                rotation_angle_text.value = "не определён"

            die_1_coords_text.update()
            die_1_index_text.update()
            die_2_coords_text.update()
            die_2_index_text.update()
            rotation_angle_text.update()

        except Exception as e:
            logger.error(f"Ошибка обновления данных референсных кристаллов: {e}")
            show_error("Ошибка референсных кристаллов", "Не удалось обновить информацию о референсных кристаллах",
                       config, config.page)

    orientation.add_listener(update_reference_die_display)

    def update_slider(coordinates):
        """
        Обновляет текстовые поля отображения текущих координат манипулятора в интерфейсе.

        :param coordinates: Словарь с координатами для обновления
        """
        for letter, value in coordinates.items():
            letter = letter.lower()
            if letter == "x":
                x = max(config.extreme_coordinates["x_min"],
                        min(config.extreme_coordinates["x_max"], value))
                x_axis.controls[0].controls[0].value = f"X={x:.2f}"
                x_axis.controls[0].controls[1].controls[0].value = x
                x_axis.update()
            elif letter == "y":
                y = max(config.extreme_coordinates["y_min"],
                        min(config.extreme_coordinates["y_max"], value))
                y_axis.controls[0].controls[0].value = f"Y={y:.2f}"
                y_axis.controls[0].controls[1].controls[0].value = y
                y_axis.update()
            elif letter == "z":
                z = max(config.extreme_coordinates["z_min"],
                        min(config.extreme_coordinates["z_max"], value))
                z_axis.controls[0].controls[0].value = f"Z={z:.2f}"
                z_axis.controls[0].controls[1].controls[0].value = z
                z_axis.update()

    def update_step_button_highlight():
        """Обновляет подсветку кнопок шага в соответствии с текущим config.movement_step"""
        step_mapping = {
            0.01: 0,
            0.1: 1,
            1: 2,
            10: 3,
            "crystal_size": 4,
        }

        # Сбрасываем все кнопки к неактивному состоянию
        for btn in step_buttons:
            btn.bgcolor = application_colors["inactive"]
            btn.disabled = False
            # Обновляем цвет как для текста, так и для иконки
            if hasattr(btn, 'content') and isinstance(btn.content, Icon):
                btn.content.color = application_colors["text"]
                btn.content.update()
            else:
                btn.color = application_colors["text"]
            btn.update()

        # Подсвечиваем активную кнопку
        active_index = step_mapping.get(config.movement_step)
        if active_index is not None:
            btn = step_buttons[active_index]
            btn.bgcolor = application_colors["active"]
            if hasattr(btn, 'content') and isinstance(btn.content, Icon):
                btn.content.color = application_colors["text"]  # Белый на активном фоне
                btn.content.update()
            else:
                btn.color = application_colors["text"]
            btn.update()

    def update_camera_enlarge_btn(show_button):
        """Показывает или скрывает кнопки управления изображением"""
        if show_button:
            if camera_enlarge_btn not in camera_stack.controls:
                camera_stack.controls.append(camera_enlarge_btn)
            if camera_enlarge_and_crop_die_btn not in camera_stack.controls:
                camera_stack.controls.append(camera_enlarge_and_crop_die_btn)
        else:
            if camera_enlarge_btn in camera_stack.controls:
                camera_stack.controls.remove(camera_enlarge_btn)
            if camera_enlarge_and_crop_die_btn in camera_stack.controls:
                camera_stack.controls.remove(camera_enlarge_and_crop_die_btn)

        if camera_stack.page is not None:
            camera_stack.update()

    update_camera_enlarge_btn(False)  # Изначально скрываем кнопку

    # === ОБРАБОТЧИКИ СОБЫТИЙ ===

    def calibration_handler(_e=None, target_coords: Dict[str, float] = None) -> None:
        """Обработчик нажатия на кнопку 'Откалибровать манипулятор'"""

        nonlocal x_axis, y_axis, z_axis
        page = _e.page if _e else config.page

        set_button_active(calibration_btn, False)
        cam_btn_0_active = camera_buttons.controls[0].disabled is False
        cam_btn_1_active = camera_buttons.controls[1].disabled is False
        set_button_active(camera_buttons.controls[0], False)
        set_button_active(camera_buttons.controls[1], False)

        def execute_calibration():
            nonlocal x_axis, y_axis, z_axis
            success = False
            try:
                if not IS_MOCK_ROBOT:
                    if target_coords is not None:
                        move_robot_to_coordinates(robot=robot, config=config,
                                                  x=target_coords["x"], y=target_coords["y"], z=target_coords["z"])
                    else:
                        robot_to_home(robot=robot, config=config)
                        if move_to_first_ref_die_switch.controls[1].value:
                            move_robot_to_coordinates(robot=robot, config=config,
                                                      x=config.coordinate_of_the_first_cell["x"],
                                                      y=config.coordinate_of_the_first_cell["y"],
                                                      z=config.coordinate_of_the_first_cell["z"])
                success = True

            except RobotException as e:
                show_error("Ошибка Манипулятора", str(e), page, config)

            finally:
                set_button_active(calibration_btn, True)
                set_button_active(camera_buttons.controls[0], cam_btn_0_active)
                set_button_active(camera_buttons.controls[1], cam_btn_1_active)

                if success:
                    active_main_buttons()

                update_slider({"x": config.current_coordinates["x"],
                               "y": config.current_coordinates["y"],
                               "z": config.current_coordinates["z"]})

        robot_command_queue.put(execute_calibration)

    def save_coords_handler(_e):
        """Обработчик нажатия на кнопку 'Сохранить координаты'"""
        nonlocal x_axis, y_axis, z_axis

        # Сохраняем координаты
        if not IS_MOCK_ROBOT:
            x, y, z = (round(config.current_coordinates[axis], 2) for axis in ("x", "y", "z"))
        else:
            x, y, z = 188.65, 78.68, -72.06

        if reference_die_container.value == "1":
            ret, error_message = orientation.update_coordinates_of_first_reference_die(x, y, z)
            config.coordinate_of_the_first_cell = {"x": x, "y": y, "z": z}
        else:
            ret, error_message = orientation.update_coordinates_of_second_reference_die(x, y)

        if not ret and error_message is not None:
            show_warning("Предупреждение", error_message, _e.page, config)

    def move_to_die_callback(die: 'Die') -> None:
        """ Перемещает робота в координаты переданного кристалла. """
        if not die.has_physical_coords():
            show_error(
                title="Ошибка перемещения на кристалл",
                message=f"У кристалла {die.id} не определены физические координаты.\n"
                        f"Перемещение камеры на него невозможно.",
                page=config.page,
                config=config
            )
            return

        target_x = die.physical_x
        target_y = die.physical_y

        if config.current_coordinates["z"] == 0:
            target_z = config.coordinate_of_the_first_cell["z"]
        else:
            target_z = config.current_coordinates["z"]

        target_coords = {
            "x": target_x,
            "y": target_y,
            "z": target_z
        }

        tab_manager.switch_to_tab("Калибровка системы")

        # Имитируем нажатие кнопки "Начать движение" с передачей целевых координат
        calibration_handler(target_coords=target_coords)

    wafer_map.set_move_to_die_callback(move_to_die_callback)

    def create_movement_handler(dx=0, dy=0, dz=0, home_x=False, home_y=False, home_z=False):
        """Универсальный обработчик движения с динамическим шагом"""

        def handler(_e):
            page = _e.page

            # Определяем текущий шаг
            current_step = config.movement_step
            if current_step == "crystal_size":
                step_x = config.wafer_params["x_distance"]
                step_y = config.wafer_params["y_distance"]
                step_z = 1.0
            else:
                step_x = current_step
                step_y = current_step
                step_z = current_step

            target_x = config.current_coordinates["x"] + dx * step_x
            target_y = config.current_coordinates["y"] + dy * step_y
            target_z = config.current_coordinates["z"] + dz * step_z

            if home_x:
                target_x = 0
            if home_y:
                target_y = 0
            if home_z:
                target_z = 0

            def execute_command():
                if home_x and home_y and home_z:
                    robot_to_home(robot=robot, config=config)
                    update_slider({"x": 0, "y": 0, "z": 0})
                else:
                    move_robot_to_coordinates(robot=robot, config=config, x=target_x, y=target_y, z=target_z)
                    updates = {}
                    if not home_x:
                        updates["x"] = target_x
                    if not home_y:
                        updates["y"] = target_y
                    if not home_z:
                        updates["z"] = target_z
                    update_slider(updates)

            def on_error(e):
                show_error("Ошибка Манипулятора", str(e), page, config)

            robot_command_queue.put(execute_command, error_callback=on_error)

        return handler

    on_click_up_xy = create_movement_handler(dy=1)
    on_click_down_xy = create_movement_handler(dy=-1)
    on_click_left_xy = create_movement_handler(dx=-1)
    on_click_right_xy = create_movement_handler(dx=1)
    on_click_up_z = create_movement_handler(dz=1)
    on_click_down_z = create_movement_handler(dz=-1)
    on_click_home_x = create_movement_handler(home_x=True)
    on_click_home_y = create_movement_handler(home_y=True)
    on_click_home_xy = create_movement_handler(home_x=True, home_y=True)
    on_click_home_z = create_movement_handler(home_z=True)
    on_click_home_all = create_movement_handler(home_x=True, home_y=True, home_z=True)

    def step_changed(_e, value):
        """Обработчик нажатия на кнопку смены шага движения манипулятора"""
        config.movement_step = value  # value может быть 0.01, 0.1, 1, 10 или "crystal_size"
        update_step_button_highlight()

    def set_axis_sliders_active(active):
        """
        Устанавливает состояние активности слайдеров осей X, Y, Z

        :param active: True - активировать, False - деактивировать
        """
        axes = [x_axis, y_axis, z_axis]
        for axis in axes:
            axis.controls[0].controls[1].controls[0].disabled = active
            axis.update()

    def active_main_buttons():
        """
        Активация следующих кнопок:
        - Кнопки выбора шага движения манипулятора
        - Кнопки управления манипулятором (сетка 3x5)
        - Кнопки автофокусировки и центрирования
        - Слайдеры управления координатами по осям X, Y, Z
        """
        for btn in step_buttons:
            set_button_active(btn, True)

        update_step_button_highlight()

        set_button_active(autofocus_btn, True)
        set_button_active(centering_btn, True)

        for i in range(3):
            for j in range(5):
                set_button_active(button_grid.controls[i].controls[j], True)

        set_axis_sliders_active(False)

    def inactive_main_buttons():
        """
        Дизктивация следующих кнопок:
        - Кнопки выбора шага движения манипулятора
        - Кнопки управления манипулятором (сетка 3x5)
        - Кнопки автофокусировки и центрирования
        - Слайдеры управления координатами по осям X, Y, Z
        """
        for btn in step_buttons:
            set_button_active(btn, False)

        set_button_active(autofocus_btn, False)
        set_button_active(centering_btn, False)

        for i in range(3):
            for j in range(5):
                set_button_active(button_grid.controls[i].controls[j], False)

        set_axis_sliders_active(True)

    def change_coordinates(_e, letter, value):
        """Обработчик перемещения слайдера"""
        page = _e.page
        config.current_coordinates[letter] = value
        current_coords = config.current_coordinates.copy()

        def execute_move():
            try:
                move_robot_to_coordinates(robot, config, **current_coords)
            except RobotException as e:
                show_error("Ошибка Манипулятора", str(e), page, config)
                return
            update_slider({letter: value})

        robot_command_queue.put(execute_move)

    def update_move_to_first_ref_die_switch_label(_e):
        """ Меняет текст свича перемещения на первый реф. кристалл при калибровке и сохраняет значение в config. """
        for control in move_to_first_ref_die_switch.controls:
            if isinstance(control, Switch):
                switch = control
                break

        config.move_to_first_ref_die_switch = switch.value

        text_container = move_to_first_ref_die_switch.controls[0]
        text_widget = text_container.content
        text_widget.value = f"Перемещение на референсный кристалл {'включено' if switch.value else 'выключено'}"
        text_widget.update()
        switch.update()

    def show_enlarged_image_handler(_e, is_cropped: bool = False):
        """Открывает увеличенное изображение с камеры"""
        try:
            if not CAMERA_CLICKED:
                show_error("Ошибка открытия изображения",
                           "Изображение нельзя открыть, поскольку трансляция с камеры отключена",
                           config, _e.page)
                return

            camera = camera_manager.get_connected_camera(index_of_cam=0)
            frame = rotate_frame(capture_frame(cam=camera))

            if is_cropped:
                frame = crop_frame_on_die(frame=frame, config=config, camera=camera)
                if frame is None:
                    message_error = "Не удалось обрезать изображение кристалла по границам кристалла"
                    logger.warning(f"Ошибка открытия изображения: {message_error}")
                    show_warning("Ошибка открытия изображения", message_error, _e.page, config)

            if not open_frame_in_viewer(frame):
                show_error("Ошибка открытия изображения",
                           "Не удалось открыть изображение ни в Paint, ни в стандартном просмотровщике",
                           _e.page, config)
                return

        except Exception as ex:
            logger.error(f"Ошибка при открытии изображения: {ex}")
            show_error("Ошибка", "Не удалось открыть изображение", _e.page, config)

    def connect_camera_handler(_e):
        """Обработчик нажатия на кнопку 'Подключить камеру'"""
        set_button_active(camera_buttons.controls[0], False)
        try:
            camera = camera_manager.connect_cam(index_of_cam=0, priority_window=0)
        except CameraException as e:
            show_error("Ошибка Камеры", e, _e.page, config)
            disconnect_camera_handler(_e)
            return
        except Exception as e:
            show_error("Ошибка Камеры", "Неизвестная ошибка", _e.page, config)
            logger.error(f"Ошибка Камеры: {e}")
            disconnect_camera_handler(_e)
            return

        global CAMERA_CLICKED
        CAMERA_CLICKED = True

        update_camera_enlarge_btn(True)
        set_button_active(camera_buttons.controls[1], True)

        while True:
            try:
                img_base64 = get_base64_from_frame(capture_frame(cam=camera), target_size=(860, 600))

                if camera.is_allowed_broadcast and CAMERA_CLICKED:
                    camera_container.content.src_base64 = img_base64
                    camera_container.update()
                else:
                    update_camera_enlarge_btn(False)
                    camera.disconnect()
                    disconnect_camera_handler(_e)
                    camera_container.content.src_base64 = ""
                    camera_container.update()
                    break

            except CameraException as e:
                show_error("Ошибка Камеры", e, _e.page, config)
                disconnect_camera_handler(_e)
            except Exception as e:
                show_error("Ошибка Камеры", "Неизвестная ошибка", _e.page, config)
                logger.error(f"Ошибка Камеры: {e}")
                disconnect_camera_handler(_e)

    def disconnect_camera_handler(_e):
        """Обработчик нажатия на кнопку 'Отключить камеру'"""
        global CAMERA_CLICKED
        CAMERA_CLICKED = False

        set_button_active(camera_buttons.controls[0], True)
        set_button_active(camera_buttons.controls[1], False)

    def autofocus_handler(_e):
        """Обработчик нажатия на кнопку 'Запустить' автофокусировку"""
        if not CAMERA_CLICKED:
            show_error("Предупреждение", "Перед автофокусировкой подключите камеру", _e.page, config)
            return

        page = _e.page

        set_button_active(save_coords_btn, False)
        set_button_active(camera_buttons.controls[1], False)
        inactive_main_buttons()

        selected_type = autofocus_container.content.value
        try:
            if not IS_MOCK_ROBOT:
                focus_type = "Расширенная" if selected_type == "extended" else "Стандартная"
                logger.info(f"Запуск {focus_type.lower()} автофокусировки")

                camera = camera_manager.get_connected_camera(index_of_cam=0)
                autofocus_func = autofocusing_extended if selected_type == "extended" else autofocusing_standard

                # timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                # time_start = time.time()
                autofocus_func(robot=robot, camera=camera, config=config, is_set_ideal_sharpness=True)
                # save_frame(frame=frame, filename=f"После_автофокуса_{timestamp}.jpg",
                #            dir_save=Path(r"C:\Users\user\PycharmProjects\Milandr\photos_debugging"))
                # print(f"Время автофокуса ({focus_type}): {time.time() - time_start}")

                show_success(f"{focus_type} автофокусировка прошла успешно",
                             "Фокусное расстояние было подкорректировано.\nБыли изменены эталонные параметры фокуса",
                             _e.page, config)
                logger.info(f"{focus_type} автофокусировка прошла успешно")
                orientation.z_coord_of_first_reference_die = config.current_coordinates["z"]

            else:
                config.sharpness_ideal = 10000

        except RobotException as e:
            show_error("Ошибка Манипулятора при автофокусировке", e, page, config)

        except CameraException as e:
            show_error("Ошибка Камеры при автофокусировке", e, page, config)

        except KnownSystemException as e:
            show_error("Системная ошибка при автофокусировке", e, page, config)

        except Exception as e:
            logger.error(f"Ошибка при автофокусировке: {e}")
            show_error("Ошибка автофокусировки", "Точная причина неизвестна", _e.page, config)

        finally:
            set_button_active(save_coords_btn, True)
            set_button_active(camera_buttons.controls[1], True)
            active_main_buttons()
            update_slider({"x": config.current_coordinates["x"],
                           "y": config.current_coordinates["y"],
                           "z": config.current_coordinates["z"]})

    def centering_handler(_e):
        """Обработчик нажатия на кнопку 'Запустить' центрирование"""
        if not CAMERA_CLICKED:
            show_error("Предупреждение",
                       "Перед автоцентровкой кристалла подключите камеру", _e.page, config)
            return

        page = _e.page

        set_button_active(save_coords_btn, False)
        set_button_active(camera_buttons.controls[1], False)
        inactive_main_buttons()

        try:
            if not IS_MOCK_ROBOT:
                camera = camera_manager.get_connected_camera(index_of_cam=0)

                # timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                # time_start = time.time()
                _, _, cropped_frame, _ = autocentering(robot=robot, camera=camera, config=config, dir_save=None)
                # save_frame(frame=cropped_frame, filename=f"После_центровки_{timestamp}.jpg",
                #            dir_save=Path(r"C:\Users\user\PycharmProjects\Milandr\photos_debugging"))
                # print(f"Время центровки: {time.time() - time_start}")

                if cropped_frame is None:  # Вторая попытка автоцентровки со смягченными ограничениями
                    # time_start = time.time()
                    _, _, cropped_frame, _ = autocentering(robot=robot, camera=camera, config=config,
                                                           max_attempts=6, max_offset_mm=0.08, dir_save=None)
                    # save_frame(frame=cropped_frame, filename=f"После_центровки_{timestamp}.jpg",
                    #            dir_save=Path(r"C:\Users\user\PycharmProjects\Milandr\photos_debugging"))
                    # print(f"Время центровки: {time.time() - time_start}")`

                if cropped_frame is None:
                    show_warning("Предупреждение",
                                 "Автоцентровка не сработала, требуется ручное позиционирование на кристалл",
                                 config=config, page=page)
                else:
                    show_success("Автоцентровка прошла успешно",
                                 "Было произведено позиционирование на центр ближайшего кристалла",
                                 config=config, page=page)

        except RobotException as e:
            show_error("Ошибка Манипулятора при автоцентровке", e, page, config)

        except CameraException as e:
            show_error("Ошибка Камеры при автоцентровке", e, page, config)

        except KnownSystemException as e:
            show_error("Системная ошибка при автоцентровке", e, page, config)

        except Exception as e:
            logger.error(f"Ошибка при автоцентровке: {e}")
            show_error("Ошибка автоцентровки", "Точная причина неизвестна", page, config)

        finally:
            set_button_active(save_coords_btn, True)
            set_button_active(camera_buttons.controls[1], True)
            active_main_buttons()
            update_slider({"x": config.current_coordinates["x"],
                           "y": config.current_coordinates["y"],
                           "z": config.current_coordinates["z"]})

    def on_keyboard(e: flet.KeyboardEvent):
        """Обработчик нажатий клавиш для управления манипулятором"""
        if e.page != config.page:
            return

        # Сопоставление клавиш Numpad с функциями движения
        if e.key == "Numpad 8":  # Вверх по Y (вперёд)
            on_click_up_xy(e)
        elif e.key == "Numpad 2":  # Вниз по Y (назад)
            on_click_down_xy(e)
        elif e.key == "Numpad 4":  # Влево по X
            on_click_left_xy(e)
        elif e.key == "Numpad 6":  # Вправо по X
            on_click_right_xy(e)

    config.page.on_keyboard_event = on_keyboard
    config.page.update()

    # === ПРИВЯЗКА ОБРАБОТЧИКОВ ===

    # Привязываем обработчики к кнопкам сетки
    button_grid.controls[0].controls[1].on_click = lambda e: on_click_up_xy(e)
    button_grid.controls[0].controls[3].on_click = lambda e: on_click_up_z(e)
    button_grid.controls[0].controls[4].on_click = lambda e: on_click_home_all(e)
    button_grid.controls[1].controls[0].on_click = lambda e: on_click_left_xy(e)
    button_grid.controls[1].controls[1].on_click = lambda e: on_click_home_xy(e)
    button_grid.controls[1].controls[2].on_click = lambda e: on_click_right_xy(e)
    button_grid.controls[1].controls[3].on_click = lambda e: on_click_home_z(e)
    button_grid.controls[1].controls[4].on_click = lambda e: on_click_home_x(e)
    button_grid.controls[2].controls[1].on_click = lambda e: on_click_down_xy(e)
    button_grid.controls[2].controls[3].on_click = lambda e: on_click_down_z(e)
    button_grid.controls[2].controls[4].on_click = lambda e: on_click_home_y(e)

    # Привязываем обработчики к слайдерам
    x_axis.controls[0].controls[1].controls[0].on_change_end = lambda e: change_coordinates(e, "x", e.control.value)
    y_axis.controls[0].controls[1].controls[0].on_change_end = lambda e: change_coordinates(e, "y", e.control.value)
    z_axis.controls[0].controls[1].controls[0].on_change_end = lambda e: change_coordinates(e, "z", e.control.value)

    move_to_first_ref_die_switch.controls[1].on_change = lambda e: update_move_to_first_ref_die_switch_label(e)

    # Привязываем обработчики к кнопкам управления
    calibration_btn.on_click = lambda e: calibration_handler(e)
    save_coords_btn.on_click = lambda e: save_coords_handler(e)

    # Привязываем обработчики к кнопкам камеры
    camera_buttons.controls[0].on_click = lambda e: connect_camera_handler(e)
    camera_buttons.controls[1].on_click = lambda e: disconnect_camera_handler(e)

    # Привязываем обработчики к дополнительным кнопкам
    camera_enlarge_btn.content.on_click = lambda e: show_enlarged_image_handler(e, is_cropped=False)
    camera_enlarge_and_crop_die_btn.content.on_click = lambda e: show_enlarged_image_handler(e, is_cropped=True)

    autofocus_btn.on_click = lambda e: autofocus_handler(e)
    centering_btn.on_click = lambda e: centering_handler(e)

    return calibration_tab
