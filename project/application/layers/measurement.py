from flet import *
from flet import canvas
import math
import time
from threading import Timer

from project.algorithms.autocentering import crop_frame_on_die
from project.application.addition.colors import color_mode
from project.application.addition.exceptions import CameraException
from project.application.addition.loadings import get_path
from project.application.addition.dialogs import show_error, show_warning
from project.application.addition.photo_viewer import open_frame_in_viewer
from project.station.camera.frame_capture import get_base64_from_frame, capture_frame, rotate_frame
from project.application.addition.logger import logger

CAMERA_CLICKED = False  # Глобальный параметр, отображающий, подключена ли камера к элементам вкладки


def create_measurements_layer(config, camera_manager) -> Tab:
    """
    Функция-конструктор вкладки "Измерение объектов на изображении".

    :param config: Класс конфигураций
    :param camera_manager: Класс-менеджер камер
    :return: flet.Tab measurement_tab
    """
    application_colors = color_mode(config)

    # Опции измерений
    measurement_units = ["Миллиметры (1 мм)", "Микрометры (1 мкм)", "Пиксели (1 пкс)"]
    tool_symbols = ["○", "↔", "▢", "△"]
    current_unit = config.current_measure_unit

    PAINT_CONSTANT = Paint(stroke_width=4, style=PaintingStyle.STROKE, color=application_colors["red"])

    # Список кнопок инструментов для синхронизации
    tool_buttons = []

    # Состояние рисования
    current_tool = None
    start_point = None
    shapes = []  # Список завершённых фигур
    temp_shape = None  # Текущая рисуемая фигура
    temp_mes_text = None
    drawing = False
    current_coefficient = config.translation_coefficient

    # Оптимизация обработки мыши
    last_mouse_time = 0
    mouse_delay = 0.01
    mouse_debounce_timer = None

    # === БАЗОВЫЕ ГРАФИЧЕСКИЕ ЭЛЕМЕНТЫ С ПОДДЕРЖКОЙ СОСТОЯНИЙ ===

    def create_button(active: bool = True, button_type: str = "default", **kwargs) -> ElevatedButton:
        """
        Универсальная функция создания кнопок с поддержкой состояний.

        :param active: True - активная кнопка, False - неактивная
        :param button_type: тип кнопки ("tool", "default")
        :param kwargs: дополнительные параметры для переопределения
        :return: настроенная кнопка
        """
        custom_text_size = kwargs.pop('text_size', None)

        button_configs = {
            "tool": {
                "radius": 10,
                "text_size": custom_text_size if custom_text_size else 36,
                "width": 120,
                "height": 120,
            },
            "default": {
                "radius": 10,
                "text_size": custom_text_size if custom_text_size else 22,
                "width": kwargs.pop('width', 120),
                "height": kwargs.pop('height', 48),
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
        Устанавливает состояние кнопки (активная/неактивная).

        :param button: кнопка для изменения состояния
        :param active: True - активная, False - неактивная
        """
        if active:
            button.style.bgcolor = application_colors["inactive"]
            button.style.color = application_colors["text"]
            button.disabled = False
        else:
            button.style.bgcolor = application_colors["top_bar"]
            button.style.color = application_colors["unclickable"]
            button.disabled = True

        button.update()

    def create_text_field(active: bool = False, **kwargs) -> TextField:
        """
        Создает поле ввода с поддержкой состояний (активное/неактивное)

        :param active: True - активное поле, False - неактивное (по умолчанию)
        :param kwargs: дополнительные параметры для переопределения (включая text_size, label_size)
        :return: настроенное поле ввода
        """
        text_size = kwargs.pop('text_size', 14)
        label_size = kwargs.pop('label_size', 12)

        if active:
            color = application_colors["text"]
            label_style_color = application_colors["text"]
            disabled = False
        else:
            color = application_colors["unclickable"]
            label_style_color = application_colors["unclickable"]
            disabled = True

        base_style = {
            "color": color,
            "bgcolor": application_colors["top_bar"],
            "border_color": application_colors["text"],
            "focused_border_color": application_colors["active"],
            "label_style": TextStyle(color=label_style_color, size=label_size),
            "text_style": TextStyle(color=color, size=text_size),
            "disabled": disabled
        }

        base_params = {
            "width": 120,
            "height": 48,
        }
        base_params.update(base_style)
        base_params.update(kwargs)

        return TextField(**base_params)

    def set_text_field_active(text_field: TextField, active: bool = True):
        """
        Устанавливает состояние поля ввода (активное/неактивное)

        :param text_field: поле ввода для изменения состояния
        :param active: True - активное, False - неактивное
        """
        if active:
            text_field.color = application_colors["text"]
            text_field.label_style = TextStyle(color=application_colors["text"])
            text_field.disabled = False
        else:
            text_field.color = application_colors["unclickable"]
            text_field.label_style = TextStyle(color=application_colors["unclickable"])
            text_field.disabled = True

        text_field.update()

    # === ГРАФИЧЕСКИЕ ЭЛЕМЕНТЫ ===

    # Выпадающий список единиц измерения
    units_dropdown = Dropdown(
        width=520,
        options=[dropdown.Option(unit) for unit in measurement_units],
        value=config.current_measure_unit,
        on_change=lambda e: on_option_change(e),
        text_size=18,
        text_style=TextStyle(weight=FontWeight.W_500),
        color=application_colors["text"],
        bgcolor=application_colors["inactive"],
        border_color=application_colors["inactive"],
        focused_border_color=application_colors["text"],
        border_radius=10,
        content_padding=padding.only(12, 8, 12, 8),
    )

    # Кнопки инструментов
    tools_buttons_row = Row(
        spacing=12,
        controls=[
            create_button(
                active=(i == 0),
                button_type="tool",
                text=tool_symbols[i],
            )
            for i in range(4)
        ],
        alignment=MainAxisAlignment.START
    )

    for i in range(4):
        tool_buttons.append(tools_buttons_row.controls[i])

    # Поле ввода коэффициента
    coefficient_input = create_text_field(
        active=False,
        label="Коэффициент",
        value=str(config.translation_coefficient),
        text_size=22,
        label_size=22,
        width=150,
        height=50,
    )

    # Кнопка активации поля ввода коэффициента
    change_coefficient_btn = create_button(
        active=True,
        text="Изменить",
        width=150
    )

    # Кнопка сохранения коэффициента
    save_coefficient_btn = create_button(
        active=False,
        text="Сохранить",
        width=150
    )

    # Строка с коэффициентом
    coefficient_row = Row(
        controls=[
            change_coefficient_btn,
            coefficient_input,
            save_coefficient_btn,
        ],
        alignment=MainAxisAlignment.CENTER,
        spacing=15,
        expand=True,
    )

    # Кнопки камеры
    camera_buttons = Row(
        controls=[
            create_button(
                active=True,
                button_type="default",
                text="Подключить камеру",
                width=250,
                height=48,
            ),
            create_button(
                active=False,
                button_type="default",
                text="Отключить камеру",
                width=250,
                height=48,
            ),
        ],
        alignment=MainAxisAlignment.START,
        spacing=30,
    )

    # Кнопка очистки
    clear_button = create_button(
        active=True,
        button_type="default",
        text="Очистить холст",
        width=530,
        height=48,
    )

    # Текстовое поле для отображения размеров
    mes_text = Text(
        value="",
        size=14,
        color=application_colors["text"],
        weight=FontWeight.W_500,
        bgcolor=application_colors["active"],
        width=600,
        text_align=TextAlign.CENTER
    )

    # Холст для рисования
    drawing_canvas = canvas.Canvas(width=600, height=890, shapes=shapes)

    # Детектор жестов мыши
    drawing_detector = GestureDetector(
        content=drawing_canvas,
        mouse_cursor=MouseCursor.BASIC
    )

    drawing_container = Container(
        content=Column(
            [drawing_detector, mes_text],
            spacing=1
        ),
        height=890,
        width=600,
        bgcolor=Colors.TRANSPARENT,
        border_radius=10,
        alignment=alignment.center
    )

    # Контейнер для изображения с камеры
    camera_container = Container(
        content=Image(src=get_path(False), fit=ImageFit.FILL, height=890, width=600),
        height=890,
        width=600,
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

    # Кнопка увеличения и обрезки фотографии по границам кристалла
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
        controls=[camera_container, drawing_container],
        height=890,
        width=600,
    )

    # Левая колонка с настройками
    left_column = Column(
        controls=[
            Row(controls=[
                Text("Настройки измерений", size=26, weight=FontWeight.BOLD, color=application_colors["text"])
            ]),
            Row(controls=[
                Text("Единицы измерения", size=22, color=application_colors["text"])
            ]),
            Container(
                content=units_dropdown,
                padding=padding.only(0, 0, 0, 0),
            ),
            Row(controls=[
                Text("Инструменты", size=22, color=application_colors["text"])
            ]),
            tools_buttons_row,
            Row(
                controls=[
                    Text("Коэффициент перевода", size=22, color=application_colors["text"])
                ],
                alignment=MainAxisAlignment.CENTER,
            ),
            Container(
                content=coefficient_row,
                alignment=alignment.center,
                width=530,
            ),
            clear_button,
            camera_buttons,
        ],
        spacing=24,
        alignment=MainAxisAlignment.CENTER,
        horizontal_alignment=CrossAxisAlignment.START,
    )

    # Центральная колонка
    center_column = Column(
        controls=[
            Text("Изображение с камеры", size=26, weight=FontWeight.BOLD, color=application_colors["text"]),
            camera_stack,
        ],
        alignment=MainAxisAlignment.CENTER,
        horizontal_alignment=CrossAxisAlignment.CENTER,
    )

    # Вкладка
    measurement_tab = Tab(
        text="Измерение объектов",
        content=Container(
            content=Row(
                controls=[
                    left_column,
                    Container(width=10),
                    center_column,
                ],
                alignment=MainAxisAlignment.CENTER,
                vertical_alignment=CrossAxisAlignment.CENTER,
                expand=True,
            ),
            bgcolor=application_colors["background"],
            expand=True,
        ),
    )

    # === ЛОГИКА ИЗМЕРЕНИЙ ===

    def calculate_dimensions(x1, y1, x2, y2):
        nonlocal current_unit, current_coefficient

        if current_tool is None:
            return "", x2, y2

        width = abs(x2 - x1)
        height = abs(y2 - y1)
        length = math.hypot(width, height)
        coefficient = current_coefficient

        text_x = x1 + (x2 - x1) * 0.3
        text_y = (y1 + y2) / 2

        if current_tool == 1:  # Отрезок
            if current_unit == "Миллиметры (1 мм)":
                return f"Длина: {coefficient * length:.2f} мм", text_x, text_y
            elif current_unit == "Пиксели (1 пкс)":
                return f"Длина: {length:.2f} пкс", text_x, text_y
            elif current_unit == "Микрометры (1 мкм)":
                return f"Длина: {coefficient * 1000 * length:.2f} мкм", text_x, text_y

        elif current_tool == 0:  # Эллипс
            semi_major_axis = width / 2
            semi_minor_axis = height / 2
            if current_unit == "Миллиметры (1 мм)":
                return (
                    f"Полуось a: {coefficient * semi_major_axis:.2f} мм,"
                    f" \nПолуось b: {coefficient * semi_minor_axis:.2f} мм",
                    text_x, text_y
                )
            elif current_unit == "Пиксели (1 пкс)":
                return (
                    f"Полуось a: {semi_major_axis:.2f} пкс,"
                    f" \nПолуось b: {semi_minor_axis:.2f} пкс",
                    text_x, text_y
                )
            elif current_unit == "Микрометры (1 мкм)":
                return (
                    f"Полуось a: {coefficient * 1000 * semi_major_axis:.2f} мкм,"
                    f" \nПолуось b: {coefficient * 1000 * semi_minor_axis:.1f} мкм",
                    text_x, text_y
                )

        elif current_tool == 2:  # Прямоугольник
            if current_unit == "Миллиметры (1 мм)":
                return (f"Ширина: {coefficient * width:.2f} мм,"
                        f" \nВысота: {coefficient * height:.2f} мм"), text_x, text_y
            elif current_unit == "Пиксели (1 пкс)":
                return (f"Ширина: {width:.2f} пкс,"
                        f" \nВысота: {height:.2f} пкс"), text_x, text_y
            elif current_unit == "Микрометры (1 мкм)":
                return (f"Ширина: {coefficient * 1000 * width:.2f} мкм,"
                        f" \nВысота: {coefficient * 1000 * height:.2f} мкм"), text_x, text_y

        elif current_tool == 3:  # Треугольник
            base = width
            height = abs(y2 - y1)
            if current_unit == "Миллиметры (1 мм)":
                return (f"Основание: {coefficient * base:.2f} мм,"
                        f" \nВысота: {coefficient * height:.2f} мм"), text_x, text_y
            elif current_unit == "Пиксели (1 пкс)":
                return (f"Основание: {base:.2f} пкс,"
                        f" \nВысота: {height:.2f} пкс"), text_x, text_y
            elif current_unit == "Микрометры (1 мкм)":
                return (f"Основание: {coefficient * 1000 * base:.2f} мкм,"
                        f" \nВысота: {coefficient * 1000 * height:.2f} мкм"), text_x, text_y

        return "", x2, y2

    def update_size_text(x1, y1, x2, y2):
        nonlocal temp_mes_text
        text_value, text_x, text_y = calculate_dimensions(x1, y1, x2, y2)

        if not temp_mes_text or temp_mes_text.text != text_value:
            temp_mes_text = canvas.Text(
                x=text_x,
                y=text_y,
                text=text_value,
                style=TextStyle(weight=FontWeight.BOLD, size=16, color=application_colors["red"], bgcolor=Colors.WHITE),
                text_align=TextAlign.CENTER,
            )

    def update_canvas():
        current_shapes = shapes.copy()
        if drawing:
            if temp_shape:
                current_shapes.append(temp_shape)
            if temp_mes_text:
                current_shapes.append(temp_mes_text)

        if drawing_canvas.shapes != current_shapes:
            drawing_canvas.shapes = current_shapes
            if drawing_canvas.page:
                drawing_canvas.page.update()

    # === ОБРАБОТЧИКИ МЫШИ ===

    def on_mouse_down(e):
        nonlocal start_point, drawing, temp_shape, temp_mes_text, current_coefficient
        if current_tool is None:
            return

        drawing = True
        current_coefficient = config.translation_coefficient
        start_point = (e.local_x, e.local_y)
        temp_mes_text = None
        update_canvas()

    def on_mouse_move(e):
        nonlocal last_mouse_time, mouse_debounce_timer, mouse_delay

        current_time = time.time()
        if current_time - last_mouse_time < mouse_delay:
            return

        last_mouse_time = current_time

        if mouse_debounce_timer is not None:
            mouse_debounce_timer.cancel()

        mouse_debounce_timer = Timer(mouse_delay, lambda: process_mouse_move(e))
        mouse_debounce_timer.start()

    def process_mouse_move(e):
        nonlocal temp_shape, temp_mes_text, start_point, drawing
        if not drawing or current_tool is None or start_point is None:
            return

        x1, y1 = start_point
        x2, y2 = e.local_x, e.local_y

        update_size_text(x1, y1, x2, y2)

        if current_tool == 1:  # Отрезок
            temp_shape = canvas.Line(
                x1=x1, y1=y1, x2=x2, y2=y2,
                paint=PAINT_CONSTANT
            )
        elif current_tool == 0:  # Эллипс
            width = abs(x2 - x1)
            height = abs(y2 - y1)
            temp_shape = canvas.Oval(
                x=min(x1, x2), y=min(y1, y2),
                width=width, height=height,
                paint=PAINT_CONSTANT
            )
        elif current_tool == 2:  # Прямоугольник
            temp_shape = canvas.Rect(
                x=min(x1, x2), y=min(y1, y2),
                width=abs(x2 - x1), height=abs(y2 - y1),
                paint=PAINT_CONSTANT
            )
        elif current_tool == 3:  # Треугольник
            triangle = canvas.Path(
                [
                    canvas.Path.MoveTo(x1, y1),
                    canvas.Path.LineTo(x2, y2),
                    canvas.Path.LineTo(x1 - (x2 - x1), y2),
                    canvas.Path.Close(),
                    canvas.Path.MoveTo(x1, y1),
                    canvas.Path.LineTo(((x1 - (x2 - x1)) + x2) / 2, y2),
                ],
                paint=PAINT_CONSTANT
            )
            temp_shape = triangle

        update_canvas()

    def on_mouse_up(e):
        nonlocal start_point, shapes, temp_shape, temp_mes_text, drawing
        if current_tool is None or start_point is None:
            return

        drawing = False
        x1, y1 = start_point
        x2, y2 = e.local_x, e.local_y

        if current_tool == 1:  # Отрезок
            shapes.append(canvas.Line(
                x1=x1, y1=y1, x2=x2, y2=y2,
                paint=PAINT_CONSTANT
            ))
        elif current_tool == 0:  # Эллипс
            width = abs(x2 - x1)
            height = abs(y2 - y1)
            shapes.append(canvas.Oval(
                x=min(x1, x2), y=min(y1, y2),
                width=width, height=height,
                paint=PAINT_CONSTANT
            ))
        elif current_tool == 2:  # Прямоугольник
            shapes.append(canvas.Rect(
                x=min(x1, x2), y=min(y1, y2),
                width=abs(x2 - x1), height=abs(y2 - y1),
                paint=PAINT_CONSTANT
            ))
        elif current_tool == 3:  # Треугольник
            triangle = canvas.Path(paint=PAINT_CONSTANT)
            triangle.MoveTo(x1, y1)
            triangle.LineTo(x2, y2)
            triangle.LineTo(x1 - (x2 - x1), y2)
            triangle.Close()
            triangle.MoveTo(x1, y1)
            triangle.LineTo((x1 + x2) / 2, y2)
            shapes.append(triangle)

        start_point = None
        temp_shape = None
        temp_mes_text = None
        update_canvas()

    # === ОБРАБОТЧИКИ СОБЫТИЙ ИНТЕРФЕЙСА ===

    def update_camera_enlarge_btn(show_button):
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

    update_camera_enlarge_btn(False)

    def clear_canvas(_e):
        nonlocal shapes, temp_shape, temp_mes_text
        shapes.clear()
        temp_mes_text = None
        temp_shape = None
        update_canvas()

    def on_option_change(e):
        nonlocal current_unit
        current_unit = e.control.value
        config.current_measure_unit = e.control.value

    def tool_changed(_e):
        nonlocal tool_buttons, current_tool

        for button in tool_buttons:
            set_button_active(button, False)

        index = tool_buttons.index(_e.control)
        set_button_active(tool_buttons[index], True)

        if index == 0:
            current_tool = 0
        elif index == 1:
            current_tool = 1
        elif index == 2:
            current_tool = 2
        elif index == 3:
            current_tool = 3

    def change_coefficient_handler(_e):
        """Активирует поле ввода коэффициента"""
        set_button_active(change_coefficient_btn, False)
        set_button_active(save_coefficient_btn, True)
        set_text_field_active(coefficient_input, True)

    def save_coefficient_handler(_e):
        """Сохраняет введённый коэффициент"""
        try:
            value = float(coefficient_input.value)
            if value <= 0:
                show_error("Ошибка коэффициента",
                           "Коэффициент должен быть положительным числом",
                           _e.page, config)
                return

            config.translation_coefficient = value
            coefficient_input.value = str(value)
            coefficient_input.update()

        except ValueError:
            show_error("Ошибка коэффициента",
                       "Введено некорректное значение. Должно быть положительное число.",
                       _e.page, config)
            return

        set_button_active(change_coefficient_btn, True)
        set_button_active(save_coefficient_btn, False)
        set_text_field_active(coefficient_input, False)

    def show_enlarged_image_handler(_e, is_cropped: bool = False):
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
        set_button_active(camera_buttons.controls[0], False)
        try:
            camera = camera_manager.connect_cam(index_of_cam=0, priority_window=0)
        except CameraException as e:
            show_error("Ошибка Камеры", str(e), _e.page, config)
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
                show_error("Ошибка Камеры", str(e), _e.page, config)
                disconnect_camera_handler(_e)
            except Exception as e:
                show_error("Ошибка Камеры", "Неизвестная ошибка", _e.page, config)
                logger.error(f"Ошибка в цикле захвата: {e}")
                disconnect_camera_handler(_e)

    def disconnect_camera_handler(_e):
        global CAMERA_CLICKED
        CAMERA_CLICKED = False

        set_button_active(camera_buttons.controls[0], True)
        set_button_active(camera_buttons.controls[1], False)

    # === ПРИВЯЗКА ОБРАБОТЧИКОВ ===

    for i in range(4):
        tools_buttons_row.controls[i].on_click = lambda e: tool_changed(e)

    change_coefficient_btn.on_click = lambda e: change_coefficient_handler(e)
    save_coefficient_btn.on_click = lambda e: save_coefficient_handler(e)

    camera_buttons.controls[0].on_click = lambda e: connect_camera_handler(e)
    camera_buttons.controls[1].on_click = lambda e: disconnect_camera_handler(e)

    clear_button.on_click = clear_canvas

    drawing_detector.on_tap_down = on_mouse_down
    drawing_detector.on_tap_up = on_mouse_up
    drawing_detector.on_pan_update = on_mouse_move

    camera_enlarge_btn.content.on_click = lambda e: show_enlarged_image_handler(e, is_cropped=False)
    camera_enlarge_and_crop_die_btn.content.on_click = lambda e: show_enlarged_image_handler(e, is_cropped=True)

    return measurement_tab