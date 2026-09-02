from flet import *
import threading
import time
from project.application.addition.colors import color_mode


def create_guide_layer(config):
    """
    Создает вкладку "Руководство пользователя" с актуальными инструкциями ко всем модулям системы
    и анимированной бегущей строкой в заголовке вкладки при наведении.

    :param config: Объект конфигурации приложения (ConfigManager)
    :return: Tab объект с руководством пользователя
    """
    application_colors = color_mode(config)

    def section_title(text: str) -> Text:
        return Text(
            text,
            size=18,
            weight=FontWeight.BOLD,
            color=application_colors["active"],
            text_align=TextAlign.LEFT
        )

    def regular_text(text: str, bold_prefix: str = "") -> Row:
        controls = []
        if bold_prefix:
            controls.append(
                Text(bold_prefix, size=15, weight=FontWeight.BOLD, color=application_colors["text"])
            )
        controls.append(
            Text(text, size=15, color=application_colors["text"])
        )
        return Row(
            controls=controls,
            alignment=MainAxisAlignment.START,
            wrap=True,
            spacing=4
        )

    def info_card(text: str, is_warning: bool = False) -> Container:
        card_color = Colors.ORANGE_400 if is_warning else application_colors["active"]
        return Container(
            content=Text(
                text,
                size=14,
                color=card_color,
                italic=True
            ),
            padding=12,
            border=border.all(1, card_color),
            border_radius=8,
            bgcolor=application_colors["top_bar"],
        )

    # === ПОДВКЛАДКА: ИНСПЕКЦИЯ КРИСТАЛЛОВ ===
    inspection_guide = Column(
        spacing=16,
        scroll=ScrollMode.AUTO,
        controls=[
            Container(height=5),
            section_title("1. Подготовка и создание новой инспекции"),
            regular_text("Нажмите кнопку «Создать новую инспекцию» в центральной панели под областью карты пластины (доступно Администраторам и делегированным операторам).", "• Создание: "),
            regular_text("В появившемся окне укажите путь к карте годности (.bin или протокол .json) и задайте рабочие параметры:", "• Параметры: "),
            Text("     — ID пластины (заполняется вручную или подставляется из имени файла);", size=14, color=application_colors["text"]),
            Text("     — Диаметр/тип пластины (150, 200, 300 мм);", size=14, color=application_colors["text"]),
            Text("     — Физические размеры кристалла по осям X и Y (в мм);", size=14, color=application_colors["text"]),
            Text("     — Ответственный оператор (выбирается из списка зарегистрированных пользователей) и комментарий.", size=14, color=application_colors["text"]),
            regular_text("Для файлов .bin укажите каталог сохранения генерируемых протоколов инспекции.", "• Директория протокола: "),
            
            section_title("2. Выбор инспектируемых кристаллов и масштабирование"),
            regular_text("Нажмите кнопку «Определить типы детектируемых кристаллов» в левой панели, чтобы отметить символы/категории кристаллов, подлежащие обязательному контролю (кристаллы с меткой Dummy исключаются автоматически).", "• Фильтрация кристаллов: "),
            regular_text("Используйте панель «Масштаб кнопок» (1x / 1.5x / 2x) для комфортного отображения матрицы пластины под ваше разрешение экрана.", "• Масштаб: "),

            section_title("3. Управление процессом контроля"),
            regular_text("Запуск полного цикла оптического контроля. Перед стартом система выполняет автоматическую валидацию наличия референсных точек, калибровки фокуса и достаточного места на диске.", "• «Запуск»: "),
            regular_text("Временная остановка движения манипулятора с фиксацией промежуточного состояния и разблокировкой вкладок.", "• «Пауза»: "),
            regular_text("Возобновление контроля с кристалла, на котором произошла пауза.", "• «Продолжить»: "),
            regular_text("Полная принудительная остановка контроля с фиксацией текущих результатов в JSON-протокол.", "• «Стоп»: "),
            info_card("⚠ Внимание: Не перекрывайте объектив камеры и не воздействуйте на механику манипулятора во время активного сканирования.", True),
        ]
    )

    # === ПОДВКЛАДКА: КАЛИБРОВКА СИСТЕМЫ ===
    calibration_guide = Column(
        spacing=16,
        scroll=ScrollMode.AUTO,
        controls=[
            Container(height=5),
            section_title("1. Инициализация и ручное позиционирование"),
            regular_text("Нажмите «Подключить камеру» для вывода видеопотока реального времени.", "• Видеопоток: "),
            regular_text("Нажмите «Откалибровать манипулятор» для вывода приводов в домашнюю позицию (Home). Если активен свитч «Перемещение на референсный кристалл», манипулятор автоматически поедет в стартовые координаты первой ячейки.", "• Калибровка осей: "),
            regular_text("Используйте сетку кнопок 3×5 (или цифровой блок Numpad 2, 4, 6, 8) для перемещения по осям X, Y, Z, а также кнопки быстрого обнуления координат (⌂ ВСЕ, ⌂ XY, ⌂ Z).", "• Управление: "),
            regular_text("Переключайте шаг перемещения: 0.01 мм, 0.1 мм, 1 мм, 10 мм либо фиксированный шаг на размер кристалла (иконка кристалла).", "• Величина шага: "),

            section_title("2. Установка референсных точек и расчет угла"),
            regular_text("Наведите камеру на первый опорный кристалл (выбрав радиокнопку «Референсный кристалл № 1») и нажмите «Сохранить координаты».", "• Референс № 1: "),
            regular_text("Переместите манипулятор на второй опорный кристалл по горизонтали/вертикали, выберите радиокнопку «Референсный кристалл № 2» и нажмите «Сохранить координаты».", "• Референс № 2: "),
            regular_text("Программа автоматически рассчитает угол поворота пластины и скорректирует траекторию движения при сканировании.", "• Угол поворота: "),

            section_title("3. Автоматические алгоритмы настройки"),
            regular_text("Выполняет прецизионную подстройку резкости по эталону. Доступны Стандартный режим (быстрый поиск) и Расширенный режим (детальное сканирование Z-диапазона).", "• Автофокусировка: "),
            regular_text("Автоматически определяет границы кристалла в кадре с помощью нейросетевых моделей и сдвигает оптическую ось точно в геометрический центр кристалла.", "• Автоцентровка: "),
            info_card("💡 Совет: При клике на любой кристалл в визуализации карты на вкладке «Инспекция», манипулятор автоматически спозиционируется на физические координаты выбранного кристалла."),
        ]
    )

    # === ПОДВКЛАДКА: СТАТИСТИКА И АНАЛИТИКА ===
    statistics_guide = Column(
        spacing=16,
        scroll=ScrollMode.AUTO,
        controls=[
            Container(height=5),
            section_title("1. Назначение и доступ"),
            regular_text("Вкладка «Статистика» аккумулирует JSON-протоколы завершенных и текущих инспекций, предоставляет инструменты фильтрации, выгрузки выборки, оценки выработки операторов и детального анализа дефектов."),
            regular_text("Выбор каталога отчетов закреплен за ролью «Администратор» либо за оператором с делегированными правами.", "• Ограничение прав: "),

            section_title("2. Подвкладки модуля статистики"),
            regular_text("Журнал инспекций. Позволяет задавать строгие фильтры выборки:", "• «Инспекции и фильтры»: "),
            Text("     — По типу пластины (150, 200, 300 мм);", size=14, color=application_colors["text"]),
            Text("     — По физическим размерам кристалла X и Y (с погрешностью ±0.05 мм);", size=14, color=application_colors["text"]),
            Text("     — По диапазону дат инспекции (С ... ПО ...);", size=14, color=application_colors["text"]),
            Text("     — По конкретному инспектору.", size=14, color=application_colors["text"]),
            Text("     Иконка круговой диаграммы рядом с отчетом открывает персональный модальный график распределения дефектов и процента выхода годных кристаллов.", size=14, color=application_colors["text"]),
            
            regular_text("Генерирует сводный текстовый отчет по всей отфильтрованной выборке, общую круговую диаграмму типов брака и таблицу продуктивности операторов (объем проверенных пластин, % годных, общее число брака).", "• «Сводный отчет»: "),
            
            regular_text("Отображает реестр всех кристаллов активной инспекции. Поддерживает мгновенный поиск: введите номер кристалла (напр., 45) или диапазон через дефис (напр., 1-150) и нажмите Enter.", "• «Кристаллы и метаданные»: "),
            
            regular_text("Интерактивная гистограмма. Строит сравнительные столбцы по годным кристаллам, суммарному браку и отдельным типам дефектов (сколы, трещины, геометрия и т.д.) для выбранных чекбоксами пластин.", "• «Сравнительные графики»: "),
            info_card("💡 Совет: Чтобы исключить поврежденные или тестовые протоколы из графиков, отметьте их галочками и нажмите «Убрать из списка»."),
        ]
    )

    # === ПОДВКЛАДКА: НАСТРОЙКА КАМЕРЫ ===
    picture_guide = Column(
        spacing=16,
        scroll=ScrollMode.AUTO,
        controls=[
            Container(height=5),
            section_title("1. Настройка оптических параметров"),
            regular_text("Вкладка позволяет в реальном времени корректировать характеристики видеопотока для лучшей распознаваемости топологии кристалла."),
            regular_text("Настройка яркости, контрастности, насыщенности цвета и подавления/усиления зернистости (слайдеры 0–100%). Значение можно вводить вручную в числовое поле.", "• Базовые фильтры: "),

            section_title("2. Цветовые каналы и сравнение"),
            regular_text("Каналы Red, Green, Blue позволяют выделить контрастные слои полупроводникового кристалла (металлизацию, кремний, диэлектрик).", "• RGB-фильтрация: "),
            regular_text("В центральной области отображается обработанный видеопоток с фильтрами, в правой области — оригинальное изображение с матрицы без модификаций.", "• Двухоконный режим: "),
            regular_text("Кнопки в верхнем правом углу каждого кадра позволяют открыть изображение в полный размер либо выполнить моментальную автообрезку кадра по контуру кристалла.", "• Просмотр: "),
        ]
    )

    # === ПОДВКЛАДКА: ИНСТРУМЕНТЫ ИЗМЕРЕНИЯ ===
    measurement_guide = Column(
        spacing=16,
        scroll=ScrollMode.AUTO,
        controls=[
            Container(height=5),
            section_title("1. Калибровка масштабного коэффициента"),
            regular_text("Выберите единицы отображения: Миллиметры (мм), Микрометры (мкм) или Пиксели (пкс).", "• Единицы: "),
            regular_text("Нажмите «Изменить», введите физический масштаб перевода пикселей в метрическую систему и нажмите «Сохранить». Коэффициент используется при всех расчетах геометрических примитивов.", "• Коэффициент: "),

            section_title("2. Графические инструменты"),
            regular_text("Измерение прямого расстояния между двумя произвольными точками топологии.", "• ↔ Отрезок: "),
            regular_text("Измерение большой и малой полуосей круглых и овальных элементов (контактных окон, дефектов).", "• ○ Эллипс: "),
            regular_text("Определение ширины, высоты и охватывающей площади прямоугольных структур кристалла.", "• ▢ Прямоугольник: "),
            regular_text("Расчет длины основания и высоты треугольных зон сколов или угловых дефектов.", "• △ Треугольник: "),
            regular_text("Кнопка «Очистить холст» удаляет все нанесенные измерительные метки.", "• Очистка: "),
        ]
    )

    # === КОНСТРУКТОР ВНУТРЕННИХ ПОДВКЛАДОК ===
    tabs = Tabs(
        selected_index=0,
        animation_duration=300,
        label_color=application_colors["active"],
        unselected_label_color=application_colors["text"],
        indicator_color=application_colors["active"],
        tabs=[
            Tab(
                text="Инспекция кристаллов",
                content=Container(content=inspection_guide, padding=padding.all(12)),
            ),
            Tab(
                text="Калибровка системы",
                content=Container(content=calibration_guide, padding=padding.all(12)),
            ),
            Tab(
                text="Статистика и отчеты",
                content=Container(content=statistics_guide, padding=padding.all(12)),
            ),
            Tab(
                text="Настройка камеры",
                content=Container(content=picture_guide, padding=padding.all(12)),
            ),
            Tab(
                text="Измерение объектов",
                content=Container(content=measurement_guide, padding=padding.all(12)),
            ),
        ],
    )

    # === АНИМИРОВАННЫЙ ТАБ «РУКОВОДСТВО ПОЛЬЗОВАТЕЛЯ» В ВЕРХНЕМ МЕНЮ ===
    guide_text = Text(
        value="Руководство пользователя",
        size=22,
        weight=FontWeight.BOLD,
        color=application_colors["text"],
        no_wrap=True,
    )

    marquee_row = Row(
        controls=[
            guide_text,
            Container(width=150)
        ],
        width=250,
        scroll=ScrollMode.HIDDEN,
    )

    hover_state = {"hovered": False, "animating": False}

    def scroll_worker():
        if hover_state["animating"]:
            return
        hover_state["animating"] = True

        offset_target = 150
        while hover_state["hovered"]:
            marquee_row.scroll_to(offset=offset_target, duration=2500)
            for _ in range(25):
                if not hover_state["hovered"]:
                    break
                time.sleep(0.1)
            offset_target = 0 if offset_target == 150 else 150

        hover_state["animating"] = False

    def on_guide_hover(e):
        if e.data == "true":
            hover_state["hovered"] = True
            threading.Thread(target=scroll_worker, daemon=True).start()
        else:
            hover_state["hovered"] = False
            marquee_row.scroll_to(offset=0, duration=500)

    guide_tab = Tab(
        text="Руководство пользователя",
        tab_content=Container(
            content=marquee_row,
            width=250,
            on_hover=on_guide_hover,
            alignment=alignment.center,
        ),
        content=Container(
            content=tabs,
            padding=10,
            bgcolor=application_colors["background"],
        ),
    )

    return guide_tab