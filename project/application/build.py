from flet import *
import threading
from project.application.addition.loadings import show_loading_screen, close_loading_screen
from project.application.list import create_layers_list
from project.application.addition.colors import color_mode
from project.configuration.config_manager import ConfigManager
import project.algorithms.neural_network.networks_vault as nv
from project.station.camera.camera_manager import CameraManager
from project.station.robot.robot_controller import RobotController
from project.application.tab_manager import tab_manager
from project.application.layers.statistics import create_statistics_layer
from project.application.layers.guide import create_guide_layer


def building_application(application_page: Page, current_user: dict = None):
    """
    Настраивает основное окно приложения, добавляет необходимые вкладки.
    """
    show_loading_screen(application_page)

    threading.Thread(target=nv.networks_init(), daemon=True).start()

    application_page.window_width = 1920
    application_page.window_height = 1080
    application_page.window_maximized = True

    application_page.title = "Управление системой"
    application_page.vertical_alignment = MainAxisAlignment.CENTER
    application_page.horizontal_alignment = CrossAxisAlignment.CENTER

    config = ConfigManager(page=application_page)
    robot = RobotController(config=config)
    camera_manager = CameraManager()

    application_colors = color_mode(config)
    application_page.bgcolor = application_colors["background"]
    application_page.theme = Theme(
        slider_theme=SliderTheme(disabled_thumb_color=application_colors["active"]),
        scrollbar_theme=ScrollbarTheme(thickness=0),
    )

    # Создание вкладок с передачей данных пользователя
    tabs_list = create_layers_list(config, robot, camera_manager, current_user=current_user)

    application_tabs = Tabs(
        tabs=tabs_list,
        expand=True,
        selected_index=0,
        animation_duration=400,
        label_color=application_colors["active"],
        divider_color=application_colors["top_bar"],
        indicator_color=application_colors["active"],
        unselected_label_color=application_colors["text"],
        indicator_tab_size=True,
        scrollable=False,
        label_text_style=TextStyle(
            size=22,
            weight=FontWeight.BOLD,
        ),
    )
    tab_manager.initialize(application_tabs)

    # Настройка ленивых вкладок
    tab_manager.enable_lazy_tabs({
        # 'Название_вкладки': (функция_загрузки, (параметры))
        'Статистика': (create_statistics_layer, (config, current_user)),
        'Руководство пользователя': (create_guide_layer, config)
    })

    close_loading_screen(application_page)
    application_page.add(application_tabs)