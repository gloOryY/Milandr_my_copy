from flet import *


def get_path(dark_theme):
    if not dark_theme:
        return "project/assets/video/load_light.gif"
    else:
        "project/assets/video/load.gif"


def show_loading_screen(page: Page):
    """
    Отображает загрузку страницы

    :param page: Страница, на которой будет отображаться экран загрузки.

     Examples:
        >>> show_loading_screen(page)
        >>> # Код для подготовки рендеринга основного экрана application_main
        >>> close_loading_screen(page)
    """

    page.window_width = 1920
    page.window_height = 1080
    page.window_maximized = True

    loading = Container(
        content=Column(
            [
                ProgressRing(width=64, height=64, color="white"),
                Text("Загрузка...", size=64, color="white")
            ],
            alignment=MainAxisAlignment.CENTER,
            horizontal_alignment=CrossAxisAlignment.CENTER
        ),
        alignment=alignment.center,
        bgcolor=Colors.BLACK,
        expand=True
    )

    page.add(loading)
    page.update()


def close_loading_screen(page: Page):
    """
    Закрываем загрузку страницы

    Параметры:
    page (Page): Страница, которую нужно очистить
    """
    page.clean()
