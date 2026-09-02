from flet import *

from project.algorithms.autocentering import crop_frame_on_die
from project.application.addition.colors import color_mode
from project.application.addition.exceptions import CameraException
from project.application.addition.loadings import get_path
from project.application.addition.dialogs import show_error, show_warning
from project.application.addition.photo_viewer import open_frame_in_viewer
from project.configuration.config_manager import ConfigManager
from project.station.camera.camera_manager import CameraManager
from project.station.camera.frame_capture import get_base64_from_frame, capture_frame, rotate_frame
from project.application.addition.logger import logger
from project.station.camera.frame_settings import apply_settings_to_frame

CAMERA_CLICKED = False  # Глобальный параметр, отображающий, подключена ли камера к элементам вкладки


def create_picture_layer(config: 'ConfigManager', camera_manager: 'CameraManager') -> Tab:
    """
    Функция-конструктор вкладки "Настройка камеры".

    :param config: Класс конфигураций
    :param camera_manager: Класс-менеджер камер
    :return: flet.Tab camera_tab
    """
    application_colors = color_mode(config)

    # Названия слайдеров и ключи параметров
    slider_titles = ["Яркость, %", "Контрастность, %", "Насыщенность, %", "Зернистость, %"]
    filter_titles = ["Красный фильтр, %", "Зелёный фильтр, %", "Синий фильтр, %"]
    keys_list = ["brightness", "contrast", "saturation", "grain_level",
                 "red_filter", "green_filter", "blue_filter"]

    # Списки для синхронизации слайдеров и текстовых полей
    sliders = []
    text_fields = []

    # === БАЗОВЫЕ ГРАФИЧЕСКИЕ ЭЛЕМЕНТЫ С ПОДДЕРЖКОЙ СОСТОЯНИЙ ===

    def create_button(active: bool = True, button_type: str = "picture", **kwargs) -> ElevatedButton:
        """
        Универсальная функция создания кнопок с поддержкой состояний.

        :param active: True - активная кнопка, False - неактивная
        :param button_type: тип кнопки ("picture", "default")
        :param kwargs: дополнительные параметры для переопределения
        :return: настроенная кнопка
        """
        custom_text_size = kwargs.pop('text_size', None)

        button_configs = {
            "picture": {
                "radius": 10,
                "text_size": custom_text_size if custom_text_size else 22,
                "width": 120,
                "height": 48,
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
        Устанавливает состояние кнопки (активная/неактивная).

        :param button: кнопка для изменения состояния
        :param active: True - активная, False - неактивная
        """
        if active:
            button.bgcolor = application_colors["inactive"]
            button.color = application_colors["text"]
            button.disabled = False
        else:
            button.bgcolor = application_colors["top_bar"]
            button.color = application_colors["unclickable"]
            button.disabled = True

        button.update()

    def create_slider_row(title: str, value: float, active_color: str = None) -> Column:
        """
        Создаёт строку с текстовым полем и слайдером для настройки параметра.

        :param title: название параметра
        :param value: текущее значение
        :param active_color: цвет активной части слайдера
        :return: Column с элементами управления
        """
        if active_color is None:
            active_color = application_colors["text"]

        return Column(
            controls=[
                Row(
                    controls=[
                        Container(
                            content=Text(
                                title,
                                font_family="Trebuchet MS",
                                width=220,
                                height=32,
                                size=22,
                                color=active_color,
                            ),
                            padding=padding.only(24, 9, 0, 5),
                        ),
                        TextField(
                            width=100,
                            height=32,
                            value=str(int(value)),
                            text_align=TextAlign.RIGHT,
                            content_padding=padding.only(0, 0, 12, 0),
                            color=application_colors["text"],
                            bgcolor=application_colors["inactive"],
                            border_color=application_colors["inactive"],
                            focused_border_color=application_colors["text"],
                            on_change=lambda e: update_slider_from_text_field(e),
                        ),
                    ],
                    alignment=MainAxisAlignment.SPACE_BETWEEN,
                    width=520,
                ),
                Slider(
                    width=520,
                    min=0,
                    max=100,
                    value=round(value),
                    active_color=active_color,
                    inactive_color=application_colors["inactive"],
                    on_change=lambda e: update_text_field_from_slider(e),
                ),
            ],
            spacing=0,
            width=520,
        )

    # === ГРАФИЧЕСКИЕ ЭЛЕМЕНТЫ ===

    # Кнопки для работы с камерой
    camera_buttons = Row(
        controls=[
            create_button(
                active=True,
                button_type="picture",
                text="Подключить камеру",
                width=250,
                height=48
            ),
            create_button(
                active=False,
                button_type="picture",
                text="Отключить камеру",
                width=250,
                height=48
            ),
        ],
        alignment=MainAxisAlignment.START,
        spacing=30,
    )

    # Левая часть с настройками изображения и RGB фильтрами
    left_column = Column(
        controls=
        [
            Row(controls=[
                Text("Настройки фильтров", size=26, weight=FontWeight.BOLD, color=application_colors["text"])
            ])
        ] +
        [
            create_slider_row(
                slider_titles[i],
                config.picture_parameters[keys_list[i]],
            )
            for i in range(4)
        ] +
        [
            create_slider_row(
                filter_titles[i],
                config.picture_parameters[keys_list[i + 4]],
                active_color=(
                    application_colors["red"] if i == 0 else
                    application_colors["green"] if i == 1 else
                    application_colors["active"]
                ),
            )
            for i in range(3)
        ] +
        [camera_buttons],
        spacing=24,
        alignment=MainAxisAlignment.CENTER,
        horizontal_alignment=CrossAxisAlignment.START,
    )

    # Заполнение списков синхронизации
    for i in range(7):
        text_fields.append(left_column.controls[i + 1].controls[0].controls[1])
        sliders.append(left_column.controls[i + 1].controls[1])

    # === Контейнеры для изображений и кнопки управления ими ===

    height_image = 890
    width_image = 600

    # Левый контейнер для изображений с камеры
    camera_left_container = Container(
        content=Image(src=get_path(False), fit=ImageFit.FILL, height=height_image, width=width_image),
        height=height_image,
        width=width_image,
        bgcolor=application_colors["background"],
        border_radius=10,
        alignment=alignment.center,
    )

    # Правый контейнер для изображений с камеры
    camera_right_container = Container(
        content=Image(src=get_path(False), fit=ImageFit.FILL, height=height_image, width=width_image),
        height=height_image,
        width=width_image,
        bgcolor=application_colors["background"],
        border_radius=10,
        alignment=alignment.center,
    )

    # Кнопка увеличения в правом верхнем углу
    camera_left_enlarge_btn = Container(
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
    camera_left_enlarge_and_crop_die_btn = Container(
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

    # Кнопка увеличения в правом верхнем углу
    camera_right_enlarge_btn = Container(
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
    camera_right_enlarge_and_crop_die_btn = Container(
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

    camera_left_stack = Stack(
        controls=[
            camera_left_container,
        ],
        width=width_image,
        height=height_image,
    )

    camera_right_stack = Stack(
        controls=[
            camera_right_container,
        ],
        width=width_image,
        height=height_image,
    )

    # Центральная часть с изображением
    center_column = Column(
        controls=[
            Text("Изображение с фильтрами", size=26, weight=FontWeight.BOLD, color=application_colors["text"]),
            camera_left_stack,
        ],
        alignment=MainAxisAlignment.CENTER,
        horizontal_alignment=CrossAxisAlignment.CENTER,
    )

    # Правая часть
    right_column = Column(
        controls=[
            Text("Оригинальное изображение", size=26, weight=FontWeight.BOLD, color=application_colors["text"]),
            camera_right_stack,
        ],
        alignment=MainAxisAlignment.CENTER,
        horizontal_alignment=CrossAxisAlignment.CENTER,
    )

    camera_tab = Tab(
        text="Настройка камеры",
        content=Container(
            content=Row(
                controls=[
                    left_column,
                    Container(width=10),
                    center_column,
                    Container(width=10),
                    right_column,
                ],
                alignment=MainAxisAlignment.CENTER,
                vertical_alignment=CrossAxisAlignment.CENTER,
                expand=True,
            ),
            bgcolor=application_colors["background"],
            expand=True,
        ),
    )

    # === ЛОГИКА ОБРАБОТКИ ===

    def update_camera_left_enlarge_btn(show_button):
        """Показывает или скрывает кнопки управления изображением"""
        if show_button:
            if camera_left_enlarge_btn not in camera_left_stack.controls:
                camera_left_stack.controls.append(camera_left_enlarge_btn)
            if camera_left_enlarge_and_crop_die_btn not in camera_left_stack.controls:
                camera_left_stack.controls.append(camera_left_enlarge_and_crop_die_btn)
        else:
            if camera_left_enlarge_btn in camera_left_stack.controls:
                camera_left_stack.controls.remove(camera_left_enlarge_btn)
            if camera_left_enlarge_and_crop_die_btn in camera_left_stack.controls:
                camera_left_stack.controls.remove(camera_left_enlarge_and_crop_die_btn)

        if camera_left_stack.page is not None:
            camera_left_stack.update()

    update_camera_left_enlarge_btn(False)  # Изначально скрываем кнопку

    def update_camera_right_enlarge_btn(show_button):
        """Показывает или скрывает кнопки управления изображением"""
        if show_button:
            if camera_right_enlarge_btn not in camera_right_stack.controls:
                camera_right_stack.controls.append(camera_right_enlarge_btn)
            if camera_right_enlarge_and_crop_die_btn not in camera_right_stack.controls:
                camera_right_stack.controls.append(camera_right_enlarge_and_crop_die_btn)
        else:
            if camera_right_enlarge_btn in camera_right_stack.controls:
                camera_right_stack.controls.remove(camera_right_enlarge_btn)
            if camera_right_enlarge_and_crop_die_btn in camera_right_stack.controls:
                camera_right_stack.controls.remove(camera_right_enlarge_and_crop_die_btn)

        if camera_right_stack.page is not None:
            camera_right_stack.update()

    update_camera_right_enlarge_btn(False)  # Изначально скрываем кнопку

    # === ОБРАБОТЧИКИ СОБЫТИЙ ===

    def update_slider_from_text_field(e):
        """
        Обработчик изменения значения текстового поля, синхронизирует с ним соответствующий слайдер.

        :param e: событие изменения значения текстового поля
        """
        try:
            index = text_fields.index(e.control)
            value = float(e.control.value)

            if 0 <= value <= 100:
                sliders[index].value = value
                sliders[index].update()

                config.update_picture_parameter(keys_list[index], round(value))

        except Exception:
            pass

    def update_text_field_from_slider(e):
        """
        Обработчик изменения значения слайдера, синхронизирует с ним соответствующее текстовое поле.

        :param e: событие изменения значения слайдера
        """
        try:
            index = sliders.index(e.control)
            text_fields[index].value = str(int(e.control.value))
            text_fields[index].update()

            config.update_picture_parameter(keys_list[index], round(e.control.value))

        except Exception:
            pass

    def show_enlarged_image_handler(_e, is_filter: bool = False, is_cropped: bool = False):
        """Открывает увеличенное изображение с камеры"""
        try:
            if not CAMERA_CLICKED:
                show_error("Ошибка открытия изображения",
                           "Изображение нельзя открыть, поскольку трансляция с камеры отключена",
                           config, _e.page)
                return

            camera = camera_manager.get_connected_camera(index_of_cam=0)
            frame = rotate_frame(capture_frame(cam=camera))

            if is_filter:
                frame = apply_settings_to_frame(frame, config)

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
        """
        Обработчик нажатия на кнопку "Подключить камеру".

        :param _e: Событие нажатия на кнопку
        """
        set_button_active(camera_buttons.controls[0], False)
        try:
            camera = camera_manager.connect_cam(index_of_cam=0, priority_window=0)
        except CameraException as e:
            show_error("Ошибка подключения камеры", e, _e.page, config)
            return
        except Exception as e:
            show_error("Ошибка подключения камеры", "Неизвестная ошибка", _e.page, config)
            logger.error(f"Ошибка Камеры: {e}")
            return

        global CAMERA_CLICKED
        CAMERA_CLICKED = True

        update_camera_left_enlarge_btn(True)
        update_camera_right_enlarge_btn(True)
        set_button_active(camera_buttons.controls[1], True)

        while True:
            try:
                img_base64_filtered = get_base64_from_frame(capture_frame(cam=camera), target_size=(860, 600),
                                                            config=config)
                img_base64_base = get_base64_from_frame(capture_frame(cam=camera), target_size=(860, 600))

                if camera.is_allowed_broadcast and CAMERA_CLICKED:
                    camera_left_container.content.src_base64 = img_base64_filtered
                    camera_left_container.update()

                    camera_right_container.content.src_base64 = img_base64_base
                    camera_right_container.update()
                else:
                    update_camera_left_enlarge_btn(False)
                    update_camera_right_enlarge_btn(False)
                    camera.disconnect()
                    disconnect_camera_handler(_e)

                    camera_left_container.content.src_base64 = ""
                    camera_left_container.update()

                    camera_right_container.content.src_base64 = ""
                    camera_right_container.update()

                    break

            except CameraException as e:
                show_error("Ошибка Камеры", e, _e.page, config)
                disconnect_camera_handler(_e)
            except Exception as e:
                show_error("Ошибка Камеры", "Неизвестная ошибка", _e.page, config)
                logger.error(f"Ошибка в цикле захвата: {e}")
                disconnect_camera_handler(_e)

    def disconnect_camera_handler(_e):
        """
        Обработчик нажатия на кнопку "Отключить камеру".

        :param _e: Событие нажатия на кнопку
        """
        global CAMERA_CLICKED
        CAMERA_CLICKED = False

        set_button_active(camera_buttons.controls[0], True)
        set_button_active(camera_buttons.controls[1], False)

    # === ПРИВЯЗКА ОБРАБОТЧИКОВ ===

    # Привязываем обработчики к кнопкам камеры
    camera_buttons.controls[0].on_click = lambda e: connect_camera_handler(e)
    camera_buttons.controls[1].on_click = lambda e: disconnect_camera_handler(e)

    camera_left_enlarge_btn.content.on_click = lambda e: show_enlarged_image_handler(
        e, is_filter=True, is_cropped=False)
    camera_left_enlarge_and_crop_die_btn.content.on_click = lambda e: show_enlarged_image_handler(
        e, is_filter=True, is_cropped=True)

    camera_right_enlarge_btn.content.on_click = lambda e: show_enlarged_image_handler(
        e, is_filter=False, is_cropped=False)
    camera_right_enlarge_and_crop_die_btn.content.on_click = lambda e: show_enlarged_image_handler(
        e, is_filter=False, is_cropped=True)

    return camera_tab
