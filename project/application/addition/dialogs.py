from flet import *
import tkinter as tk
import os
from tkinter import filedialog
from project.application.addition.colors import color_mode


def _show_message(title, message, page, config, msg_type="info", btn_text=None):
    """
    Выводит на экран модальное диалоговое окно с сообщением заданного типа.

    Args:
        title: Заголовок сообщения
        message: Тело сообщения
        page: Страница приложения
        config: Основной класс с данными
        msg_type: Тип сообщения: "info", "success", "warning", "error"
        btn_text: Текст на кнопке (по умолчанию в зависимости от типа)
    """

    def close_dialog(e):
        """ Закрывает диалоговое окно. """
        e.page.dialog.open = False
        e.page.update()

    application_colors = color_mode(config)

    # Настройки в зависимости от типа сообщения
    type_settings = {
        "info": {
            "title_color": application_colors.get("blue", Colors.BLUE_500),
            "btn_color": application_colors.get("active", Colors.BLUE_500),
            "btn_hover": application_colors.get("hover", Colors.BLUE_700),
            "default_btn_text": "ОК"
        },
        "success": {
            "title_color": application_colors.get("green", Colors.GREEN_500),
            "btn_color": application_colors.get("success", Colors.GREEN_500),
            "btn_hover": application_colors.get("hover_green", Colors.GREEN_700),
            "default_btn_text": "Продолжить"
        },
        "warning": {
            "title_color": application_colors.get("orange", Colors.ORANGE_500),
            "btn_color": application_colors.get("warning", Colors.ORANGE_500),
            "btn_hover": application_colors.get("hover_orange", Colors.ORANGE_700),
            "default_btn_text": "Закрыть"
        },
        "error": {
            "title_color": application_colors.get("red", Colors.RED_500),
            "btn_color": application_colors.get("active", Colors.RED_500),
            "btn_hover": application_colors.get("hover", Colors.RED_700),
            "default_btn_text": "Продолжить"
        }
    }

    # Получаем настройки для типа сообщения
    settings = type_settings.get(msg_type, type_settings["info"])

    # Определяем текст кнопки
    button_text = btn_text if btn_text else settings["default_btn_text"]

    dialog = AlertDialog(
        title=Text(
            title,
            size=28,
            font_family="Montserrat",
            weight=FontWeight.W_600,
            color=settings["title_color"],
            text_align=TextAlign.CENTER
        ),
        content=Text(
            message,
            size=24,
            font_family="Montserrat",
            weight=FontWeight.W_400,
            color=application_colors.get("text", Colors.BLACK),
            text_align=TextAlign.CENTER
        ),
        actions=[
            Container(
                content=TextButton(
                    content=Text(
                        button_text,
                        size=24,
                        font_family="Montserrat",
                        weight=FontWeight.BOLD,
                        color=application_colors.get("background", Colors.WHITE)
                    ),
                    width=180,
                    height=48,
                    on_click=close_dialog,
                    style=ButtonStyle(
                        bgcolor=settings["btn_color"],
                        color=application_colors.get("text", Colors.WHITE),
                        overlay_color=settings["btn_hover"],
                        shape=RoundedRectangleBorder(radius=8)
                    )
                ),
                alignment=alignment.center
            )
        ],
        modal=True,
        bgcolor=application_colors.get("background", Colors.WHITE)
    )

    # Добавляем диалоговое окно на страницу приложения
    page.dialog = dialog
    dialog.open = True
    page.update()


def show_info(title, message, page, config, btn_text=None):
    """ Выводит информационное сообщение. """
    _show_message(title, message, page, config, "info", btn_text)


def show_success(title, message, page, config, btn_text=None):
    """ Выводит сообщение об успехе. """
    _show_message(title, message, page, config, "success", btn_text)


def show_warning(title, message, page, config, btn_text=None):
    """ Выводит предупреждение. """
    _show_message(title, message, page, config, "warning", btn_text)


def show_error(title, message, page, config, btn_text=None):
    """ Выводит сообщение об ошибке. """
    _show_message(title, message, page, config, "error", btn_text)


def show_confirmation(title, message, page, config, on_confirm, on_cancel=None,
                      confirm_text="Да", cancel_text="Нет"):
    """
    Выводит на экран модальное диалоговое окно с подтверждением действия.

    Args:
        title: Заголовок сообщения
        message: Тело сообщения
        page: Страница приложения
        config: Основной класс с данными
        on_confirm: Функция, вызываемая при подтверждении (нажатии "Да")
        on_cancel: Функция, вызываемая при отмене (нажатии "Нет"), опционально
        confirm_text: Текст на кнопке подтверждения (по умолчанию "Да")
        cancel_text: Текст на кнопке отмены (по умолчанию "Нет")
    """

    def handle_confirm(e):
        """ Обработчик нажатия на кнопку подтверждения. """
        e.page.dialog.open = False
        e.page.update()
        if on_confirm:
            on_confirm(e)

    def handle_cancel(e):
        """ Обработчик нажатия на кнопку отмены. """
        e.page.dialog.open = False
        e.page.update()
        if on_cancel:
            on_cancel(e)

    def handle_close(e):
        """
        Обработчик закрытия диалога (если пользователь нажал вне окна или ESC).
        По умолчанию считаем это отменой.
        """
        if on_cancel:
            on_cancel(e)

    application_colors = color_mode(config)

    dialog = AlertDialog(
        title=Text(
            title,
            size=28,
            font_family="Montserrat",
            weight=FontWeight.W_600,
            color=application_colors.get("warning", Colors.ORANGE_500),
            text_align=TextAlign.CENTER
        ),
        content=Text(
            message,
            size=24,
            font_family="Montserrat",
            weight=FontWeight.W_400,
            color=application_colors.get("text", Colors.BLACK),
            text_align=TextAlign.CENTER
        ),
        actions=[
            Row(
                controls=[
                    # Кнопка "Нет" (отмена)
                    Container(
                        content=TextButton(
                            content=Text(
                                cancel_text,
                                size=24,
                                font_family="Montserrat",
                                weight=FontWeight.BOLD,
                                color=application_colors.get("background", Colors.WHITE)
                            ),
                            width=180,
                            height=48,
                            on_click=handle_cancel,
                            style=ButtonStyle(
                                bgcolor=application_colors.get("active", Colors.GREY_500),
                                color=application_colors.get("text", Colors.WHITE),
                                overlay_color=application_colors.get("hover", Colors.GREY_700),
                                shape=RoundedRectangleBorder(radius=10)
                            )
                        ),
                        alignment=alignment.center
                    ),
                    # Кнопка "Да" (подтверждение)
                    Container(
                        content=TextButton(
                            content=Text(
                                confirm_text,
                                size=24,
                                font_family="Montserrat",
                                weight=FontWeight.BOLD,
                                color=application_colors.get("background", Colors.WHITE)
                            ),
                            width=180,
                            height=48,
                            on_click=handle_confirm,
                            style=ButtonStyle(
                                bgcolor=application_colors.get("active", Colors.BLUE_500),
                                color=application_colors.get("text", Colors.WHITE),
                                overlay_color=application_colors.get("hover", Colors.BLUE_700),
                                shape=RoundedRectangleBorder(radius=10)
                            )
                        ),
                        alignment=alignment.center
                    ),
                ],
                alignment=MainAxisAlignment.SPACE_AROUND,
                spacing=20
            )
        ],
        modal=True,
        bgcolor=application_colors.get("background", Colors.WHITE),
        on_dismiss=handle_close
    )

    page.dialog = dialog
    dialog.open = True
    page.update()


def select_file(initial_dir: str = None, title: str = "Выберите файл",
                filetypes: list = None) -> str:
    """
    Универсальный диалог выбора файла.

    Args:
        initial_dir: Начальная директория
        title: Заголовок окна
        filetypes: Список кортежей с типами файлов [(description, pattern), ...]

    Returns:
        str: Путь к выбранному файлу или пустая строка если отмена
    """
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    if filetypes is None:
        filetypes = [("Все файлы", "*")]

    if initial_dir and os.path.exists(initial_dir):
        initial_dir = os.path.expanduser(initial_dir)
    else:
        initial_dir = os.path.expanduser("~")

    file_path = filedialog.askopenfilename(
        title=title,
        filetypes=filetypes,
        initialdir=initial_dir
    )

    root.destroy()
    return file_path


def select_directory(initial_dir: str = None, title: str = "Выберите папку") -> str:
    """
    Универсальный диалог выбора папки.

    Args:
        initial_dir: Начальная директория
        title: Заголовок окна

    Returns:
        Path: Путь к выбранной папке или пустая строка если отмена
    """
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    if initial_dir and os.path.exists(initial_dir):
        initial_dir = os.path.expanduser(initial_dir)
    else:
        initial_dir = os.path.expanduser("~")

    directory_path = filedialog.askdirectory(
        title=title,
        initialdir=initial_dir
    )

    root.destroy()
    return directory_path


def show_restart_message(title, message, page, config):
    """
    Отображает модальное диалоговое окно, где пользователь выбирает:
    перезагрузить приложение, чтобы поменять цветовую тему, или отменить действие.

    Предотвращает зависание окна при быстрых множественных нажатиях
    с помощью флага page._restart_dialog_open.

    Args:
        title: Заголовок сообщения
        message: Тело сообщения
        page: Страница приложения, поверх которой будет нарисовано окно
        config: Основной класс с данными
    """

    # Проверяем, не открыт ли уже диалог перезапуска
    if hasattr(page, '_restart_dialog_open') and page._restart_dialog_open:
        return

    # Устанавливаем флаг, что диалог открыт
    page._restart_dialog_open = True

    def close_dialog(e):
        """
        Закрывает диалоговое окно и восстанавливает состояние UI.
        Сбрасывает значение селектора формы на "Круглая" и снимает флаг блокировки.
        """
        try:
            # Восстанавливаем значение селектора формы на "Круглая"
            e.page.controls[0].tabs[0].content.content.controls[0].controls[3].controls[0].value = "Круглая"
        except (AttributeError, IndexError):
            # Игнорируем ошибки доступа к элементам UI, если структура изменилась
            pass

        # Закрываем диалог
        if e.page.dialog:
            e.page.dialog.open = False

        # Сбрасываем флаг блокировки
        page._restart_dialog_open = False
        e.page.update()

    def restart_app(e):
        """
        Изменяет цветовую тему, записанную в JSON и перезагружает приложение.
        Сбрасывает флаг блокировки перед уничтожением окна.
        """
        # Меняем тему если диалог вызван для смены фона
        if "фон" in title:
            if config.current_theme == "light":
                config.current_theme = "dark"
            else:
                config.current_theme = "light"

        # Закрываем диалог перед перезапуском приложения
        if e.page.dialog:
            e.page.dialog.open = False

        # Сбрасываем флаг блокировки
        page._restart_dialog_open = False
        e.page.update()

        # Уничтожаем окно приложения для перезапуска
        e.page.window_destroy()

    application_colors = color_mode(config)

    restart_dialog = AlertDialog(
        title=Text(
            title,
            size=28,
            font_family="Montserrat",
            weight=FontWeight.W_600,
            color=application_colors.get("red", Colors.RED),
            text_align=TextAlign.CENTER
        ),
        content=Text(
            message,
            size=24,
            font_family="Montserrat",
            weight=FontWeight.W_400,
            color=application_colors.get("text", Colors.BLACK),
            text_align=TextAlign.CENTER
        ),
        actions=[
            Row(
                controls=[
                    # Кнопка "Отмена" - закрывает диалог без изменений
                    TextButton(
                        content=Text(
                            "Отмена",
                            size=24,
                            font_family="Montserrat",
                            weight=FontWeight.BOLD,
                            color=application_colors.get("background", Colors.WHITE)
                        ),
                        width=180,
                        height=48,
                        on_click=close_dialog,
                        style=ButtonStyle(
                            bgcolor=application_colors.get("inactive", Colors.GREY),
                            color=application_colors.get("text", Colors.WHITE),
                            overlay_color=application_colors.get("hover", Colors.GREY_700),
                            shape=RoundedRectangleBorder(radius=10)
                        )
                    ),
                    # Кнопка "ОК" - применяет изменения и перезапускает приложение
                    TextButton(
                        content=Text(
                            "ОК",
                            size=24,
                            font_family="Montserrat",
                            weight=FontWeight.BOLD,
                            color=application_colors.get("background", Colors.WHITE)
                        ),
                        width=180,
                        height=48,
                        on_click=restart_app,
                        style=ButtonStyle(
                            bgcolor=application_colors.get("active", Colors.BLUE),
                            color=application_colors.get("text", Colors.WHITE),
                            overlay_color=application_colors.get("hover", Colors.BLUE_700),
                            shape=RoundedRectangleBorder(radius=10)
                        )
                    ),
                ],
                alignment=MainAxisAlignment.CENTER,
                spacing=20
            )
        ],
        modal=True,  # Блокирует взаимодействие с остальным интерфейсом
        bgcolor=application_colors.get("background", Colors.WHITE),
        # Обработчик закрытия диалога (клик вне окна или ESC)
        on_dismiss=lambda e: setattr(page, '_restart_dialog_open', False)
    )

    # Закрываем предыдущий диалог, если он остался открытым
    if page.dialog and page.dialog.open:
        page.dialog.open = False
        page.update()

    # Добавляем диалоговое окно в приложение
    page.dialog = restart_dialog
    restart_dialog.open = True
    page.update()
