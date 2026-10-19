from typing import Optional, List, Dict, Any
from flet import Tabs, Tab, Container, Text, Column, \
    alignment, MainAxisAlignment, CrossAxisAlignment, FontWeight, colors


class TabManager:
    """
    Менеджер для управления вкладками приложения.
    Позволяет блокировать/разблокировать, скрывать/показывать отдельные вкладки.
    """
    _instance: Optional['TabManager'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._tabs_control: Optional[Tabs] = None
            self._all_tabs: List[Tab] = []
            self._tabs_visibility_cache: dict = {}
            self._original_on_change = None  # Сохранение оригинального обработчика
            self._previous_tab_text: Optional[str] = None  # Текст предыдущей активной вкладки
            self._previous_tab_index: Optional[int] = None  # Индекс предыдущей активной вкладки

            # Словарь для хранения информации о ленивых вкладках
            # {tab_text: {'loader': function, 'params': tuple, 'loaded': bool, 'content': widget}}
            self._lazy_tabs: Dict[str, Dict[str, Any]] = {}
            self._lazy_tabs_enabled: bool = False  # Включен ли режим ленивой загрузки

            self._initialized = True

    def initialize(self, tabs_control: Tabs) -> None:
        """
        Инициализирует менеджер с контролом вкладок.

        Args:
            tabs_control: Объект Tabs из flet
        """
        self._tabs_control = tabs_control
        self._all_tabs = tabs_control.tabs.copy()

        # Сохраняем начальное состояние
        if tabs_control.selected_index is not None:
            self._previous_tab_index = tabs_control.selected_index
            if 0 <= self._previous_tab_index < len(self._all_tabs):
                self._previous_tab_text = self._all_tabs[self._previous_tab_index].text

        # Сохраняем старый обработчик, если он был установлен
        if hasattr(tabs_control, 'on_change') and tabs_control.on_change is not None:
            self._original_on_change = tabs_control.on_change
        # Назначаем свой обработчик
        tabs_control.on_change = self._on_tab_change

    def _on_tab_change(self, e) -> None:
        """
        Внутренний обработчик события смены вкладки.
        Вызывает сохранённый оригинальный обработчик.
        """
        if not self._tabs_control:
            return

        current_index = self._tabs_control.selected_index
        if 0 <= current_index < len(self._all_tabs):
            current_tab_text = self._all_tabs[current_index].text

            # Обработка ленивой загрузки
            if self._lazy_tabs_enabled and current_tab_text in self._lazy_tabs:
                self._load_lazy_tab(current_tab_text)

            # Если уходим с ленивой вкладки - очищаем её
            if self._lazy_tabs_enabled and self._previous_tab_text in self._lazy_tabs:
                if self._previous_tab_text != current_tab_text:  # Если переключились на другую вкладку
                    self._unload_lazy_tab(self._previous_tab_text)

            # Вызываем сохранённый оригинальный обработчик, если он был
            if self._original_on_change:
                self._original_on_change(e)

            # Обновляем информацию о предыдущей вкладке
            self._previous_tab_text = current_tab_text
            self._previous_tab_index = current_index

    def enable_lazy_tabs(self, lazy_tabs_config: Dict[str, tuple]) -> None:
        """
        Включает режим ленивой загрузки для указанных вкладок.

        Args:
            lazy_tabs_config: Словарь, где ключ - текст вкладки, значение - кортеж (функция_загрузки, кортеж_параметров)
                Например: {'Статистика': (create_statistics_layer, (config, current_user))}
        """
        self._lazy_tabs_enabled = True
        self._lazy_tabs.clear()

        for tab_text, (loader_func, params) in lazy_tabs_config.items():
            tab = self.get_tab_by_text(tab_text)
            if tab:
                # Сохраняем информацию о ленивой вкладке
                self._lazy_tabs[tab_text] = {
                    'loader': loader_func,
                    'params': params,
                    'loaded': False,
                    'content': None
                }

                # Заменяем содержимое на заглушку
                tab.content = self._create_loading_placeholder(tab_text)

    def _load_lazy_tab(self, tab_text: str) -> None:
        """
        Загружает содержимое ленивой вкладки.
        """
        if tab_text not in self._lazy_tabs:
            return

        tab_info = self._lazy_tabs[tab_text]

        if tab_info['loaded']:
            return

        tab = self.get_tab_by_text(tab_text)
        if not tab:
            return

        try:
            loader_func = tab_info['loader']
            params = tab_info['params']

            if isinstance(params, tuple):
                content = loader_func(*params)
            else:
                content = loader_func(params)

            # Если функция вернула Tab, извлекаем его content
            if isinstance(content, Tab):
                content = content.content
                # Если это Container, берем его
                if isinstance(content, Container) and hasattr(content, 'content'):
                    content = content.content
                elif content is None:
                    content = self._create_error_placeholder(tab_text, "Вкладка не содержит контента")

            tab.content = content
            tab_info['loaded'] = True
            tab_info['content'] = content

            if self._tabs_control:
                self._tabs_control.update()

        except Exception as err:
            print(f"[TabManager] Ошибка загрузки ленивой вкладки '{tab_text}': {err}")
            tab.content = self._create_error_placeholder(tab_text, str(err))
            if self._tabs_control:
                self._tabs_control.update()

    def _unload_lazy_tab(self, tab_text: str) -> None:
        """
        Выгружает содержимое ленивой вкладки (очищает виджеты).

        Args:
            tab_text: Текст вкладки для выгрузки
        """
        if tab_text not in self._lazy_tabs:
            return

        tab_info = self._lazy_tabs[tab_text]

        # Если не загружена - пропускаем
        if not tab_info['loaded']:
            return

        tab = self.get_tab_by_text(tab_text)
        if not tab:
            return

        # Очищаем содержимое и ставим заглушку
        tab.content = self._create_loading_placeholder(tab_text)
        tab_info['loaded'] = False
        tab_info['content'] = None

        if self._tabs_control:
            self._tabs_control.update()

    def _create_loading_placeholder(self, tab_text: str) -> Container:
        """
        Создает заглушку для ленивой вкладки.

        Args:
            tab_text: Текст вкладки для отображения в заглушке

        Returns:
            Container: Контейнер с заглушкой
        """
        return Container(
            content=Column(
                [
                    Text(
                        f"Загрузка вкладки '{tab_text}'...",
                        size=24,
                        weight=FontWeight.BOLD,
                    ),
                    Text(
                        "Пожалуйста, подождите",
                        size=16,
                        color=colors.GREY_600,
                    ),
                ],
                horizontal_alignment=CrossAxisAlignment.CENTER,
                alignment=MainAxisAlignment.CENTER,
            ),
            alignment=alignment.center,
            expand=True,
        )

    def _create_error_placeholder(self, tab_text: str, error_message: str) -> Container:
        """
        Создает заглушку для ошибки загрузки.

        Args:
            tab_text: Текст вкладки
            error_message: Сообщение об ошибке

        Returns:
            Container: Контейнер с сообщением об ошибке
        """
        return Container(
            content=Column(
                [
                    Text(
                        f"Ошибка загрузки вкладки '{tab_text}'",
                        size=24,
                        weight=FontWeight.BOLD,
                        color=colors.RED_400,
                    ),
                    Text(
                        f"Детали: {error_message}",
                        size=14,
                        color=colors.GREY_600,
                    ),
                ],
                horizontal_alignment=CrossAxisAlignment.CENTER,
                alignment=MainAxisAlignment.CENTER,
            ),
            alignment=alignment.center,
            expand=True,
        )

    def get_tab_by_text(self, tab_text: str) -> Optional[Tab]:
        """Возвращает вкладку по её тексту."""
        for tab in self._all_tabs:
            if tab.text == tab_text:
                return tab
        return None

    def show_tab(self, tab_text: str) -> bool:
        """
        Показывает конкретную вкладку.

        Args:
            tab_text: Текст вкладки для отображения

        Returns:
            bool: True если вкладка найдена и показана, иначе False
        """
        tab = self.get_tab_by_text(tab_text)
        if tab:
            tab.visible = True
            if self._tabs_control:
                self._tabs_control.update()
            return True
        return False

    def hide_tab(self, tab_text: str) -> bool:
        """
        Скрывает конкретную вкладку.

        Args:
            tab_text: Текст вкладки для скрытия

        Returns:
            bool: True если вкладка найдена и скрыта, иначе False
        """
        tab = self.get_tab_by_text(tab_text)
        if tab:
            tab.visible = False
            if self._tabs_control:
                self._tabs_control.update()
            return True
        return False

    def show_tabs(self, tab_texts: List[str]) -> None:
        """Показывает несколько вкладок по списку текстов."""
        for tab_text in tab_texts:
            self.show_tab(tab_text)

    def hide_tabs(self, tab_texts: List[str]) -> None:
        """Скрывает несколько вкладок по списку текстов."""
        for tab_text in tab_texts:
            self.hide_tab(tab_text)

    def show_all_tabs(self) -> None:
        """Показывает все вкладки."""
        for tab in self._all_tabs:
            tab.visible = True
        if self._tabs_control:
            self._tabs_control.update()

    def hide_all_tabs(self) -> None:
        """Скрывает все вкладки."""
        for tab in self._all_tabs:
            tab.visible = False
        if self._tabs_control:
            self._tabs_control.update()

    def block_tabs(self, allowed_tabs: List[str]) -> None:
        """
        Блокирует все вкладки, оставляя видимыми только указанные.

        Args:
            allowed_tabs: Список текстов вкладок, которые должны остаться видимыми
        """
        # Сохраняем текущее состояние для возможного восстановления
        self._tabs_visibility_cache.clear()

        for tab in self._all_tabs:
            self._tabs_visibility_cache[tab.text] = tab.visible
            tab.visible = tab.text in allowed_tabs

        if self._tabs_control:
            self._tabs_control.update()

    def unblock_tabs(self) -> None:
        """Восстанавливает видимость всех вкладок до последней блокировки."""
        if self._tabs_visibility_cache:
            for tab in self._all_tabs:
                if tab.text in self._tabs_visibility_cache:
                    tab.visible = self._tabs_visibility_cache[tab.text]
            self._tabs_visibility_cache.clear()
        else:
            self.show_all_tabs()

    def set_active_tab(self, tab_text: str) -> bool:
        """
        Устанавливает активную вкладку.

        Args:
            tab_text: Текст вкладки для активации

        Returns:
            bool: True если вкладка найдена и активирована, иначе False
        """
        tab = self.get_tab_by_text(tab_text)
        if tab and self._tabs_control:
            # Находим индекс вкладки
            for i, t in enumerate(self._all_tabs):
                if t.text == tab_text:
                    self._tabs_control.selected_index = i
                    self._tabs_control.update()
                    return True
        return False

    def get_current_tab(self) -> Optional[str]:
        """Возвращает текст текущей активной вкладки."""
        if self._tabs_control and 0 <= self._tabs_control.selected_index < len(self._all_tabs):
            return self._all_tabs[self._tabs_control.selected_index].text
        return None

    def is_tab_visible(self, tab_text: str) -> bool:
        """Проверяет, видима ли вкладка."""
        tab = self.get_tab_by_text(tab_text)
        return tab.visible if tab else False

    def switch_to_tab(self, tab_text: str) -> bool:
        """
        Переключает на указанную вкладку.

        Args:
            tab_text: Текст вкладки, на которую нужно переключиться

        Returns:
            bool: True если вкладка найдена и переключение выполнено, иначе False
        """
        if not self._tabs_control:
            return False

        for i, tab in enumerate(self._all_tabs):
            if tab.text == tab_text:
                self._tabs_control.selected_index = i
                self._tabs_control.update()
                return True
        return False


# Глобальный экземпляр менеджера
tab_manager = TabManager()