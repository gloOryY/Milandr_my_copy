from flet import *
import threading
import time
import json
import os
import shutil
import uuid
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
import torch

from project.application.addition.colors import color_mode

try:
    from project.application.layers.dialogs import show_error
except ImportError:
    from project.application.addition.dialogs import show_error

MODELS_JSON = Path("project/algorithms/neural_network/models/models.json")


def read_model_imgsz(model_path: str) -> int:
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    if not isinstance(checkpoint, dict):
        raise ValueError("Неизвестный формат .pt: ожидается checkpoint YOLO.")
    train_args = checkpoint.get("train_args")
    if not isinstance(train_args, dict) or "imgsz" not in train_args:
        raise ValueError("В .pt отсутствует train_args/imgsz.")
    value = train_args["imgsz"]
    if isinstance(value, bool) or isinstance(value, (list, tuple, dict)):
        raise ValueError(f"Некорректное train_args/imgsz: {value!r}.")
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Некорректное train_args/imgsz: {value!r}.") from exc
    if str(value) != str(size) or size <= 0:
        raise ValueError(f"Некорректное train_args/imgsz: {value!r}.")
    return size


def choose_pt_file() -> str:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askopenfilename(
            parent=root,
            title="Выберите модель YOLO",
            filetypes=[("Модель PyTorch", "*.pt")],
        )
    finally:
        root.destroy()


def read_models_json() -> dict:
    with MODELS_JSON.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def get_version(data: dict, defect_key: str) -> dict:
    for defect in data.get("defects", []):
        if defect_key in defect:
            versions = defect[defect_key].get("versions", [])
            if not versions:
                raise ValueError(f"Для {defect_key} отсутствует версия модели.")
            return versions[0]
    raise ValueError(f"Дефект {defect_key} не найден в models.json.")


def save_model_version(defect_key: str, model_path: str, imgsz: int) -> str:
    """Копирует прошедшую проверку модель в архив и меняет путь в JSON."""
    data = read_models_json()
    version = get_version(data, defect_key)
    expected = version.get("imgsz")
    if expected is None:
        raise ValueError("В models.json для этой версии отсутствует ключ imgsz.")
    if imgsz != int(expected):
        raise ValueError(f"Модель не подходит для этой версии: требуется imgsz={expected}.")

    source = Path(model_path).resolve()
    if not source.is_file() or source.suffix.lower() != ".pt":
        raise ValueError("Выберите существующий .pt-файл.")

    models_dir = MODELS_JSON.parent
    models_dir.mkdir(parents=True, exist_ok=True)
    # Каждый импорт получает уникальное имя: ранее сохранённые файлы не заменяются.
    destination = models_dir / f"{defect_key}_{source.stem}_{uuid.uuid4().hex[:12]}.pt"
    tmp_model = models_dir / f".{destination.name}.tmp"
    tmp_json = MODELS_JSON.with_name(f".{MODELS_JSON.name}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as input_file, tmp_model.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file)
        os.replace(tmp_model, destination)
        # Путь относительно корня проекта совместим с текущим ModelsVault.
        version["path"] = destination.as_posix()
        with tmp_json.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=4)
            stream.write("\n")
        os.replace(tmp_json, MODELS_JSON)
    except Exception:
        tmp_model.unlink(missing_ok=True)
        tmp_json.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    return str(destination)


def create_guide_layer(config):
    application_colors = color_mode(config)

    def section_title(text: str) -> Text:
        return Text(text, size=18, weight=FontWeight.BOLD,
                    color=application_colors["active"], text_align=TextAlign.LEFT)

    def regular_text(text: str, bold_prefix: str = "") -> Row:
        controls = []
        if bold_prefix:
            controls.append(Text(bold_prefix, size=15, weight=FontWeight.BOLD,
                                 color=application_colors["text"]))
        controls.append(Text(text, size=15, color=application_colors["text"]))
        return Row(controls=controls, alignment=MainAxisAlignment.START, wrap=True, spacing=4)

    def info_card(text: str, is_warning: bool = False) -> Container:
        card_color = Colors.ORANGE_400 if is_warning else application_colors["active"]
        return Container(content=Text(text, size=14, color=card_color, italic=True),
                         padding=12, border=border.all(1, card_color), border_radius=8,
                         bgcolor=application_colors["top_bar"])

    inspection_guide = Column(spacing=16, scroll=ScrollMode.AUTO, controls=[
        Container(height=5), section_title("1. Подготовка и создание новой инспекции"),
        regular_text("Нажмите кнопку «Создать новую инспекцию» в центральной панели под областью карты пластины.", "• Создание: "),
        regular_text("В появившемся окне укажите карту годности, ID пластины, тип пластины, размеры кристалла и оператора.", "• Параметры: "),
        regular_text("Для файлов .bin укажите каталог сохранения протоколов инспекции.", "• Директория протокола: "),
        section_title("2. Выбор инспектируемых кристаллов и масштабирование"),
        regular_text("Выберите типы кристаллов для обязательного контроля. Кристаллы с меткой Dummy исключаются автоматически.", "• Фильтрация: "),
        regular_text("Используйте масштаб кнопок 1x, 1.5x или 2x для удобного отображения карты.", "• Масштаб: "),
        section_title("3. Управление процессом контроля"),
        regular_text("Кнопка «Запуск» начинает полный цикл оптического контроля.", "• Запуск: "),
        regular_text("Кнопка «Пауза» временно останавливает манипулятор.", "• Пауза: "),
        regular_text("Кнопка «Продолжить» возобновляет контроль.", "• Продолжить: "),
        regular_text("Кнопка «Стоп» завершает контроль и сохраняет текущие результаты.", "• Стоп: "),
        info_card("⚠ Не перекрывайте объектив камеры и не воздействуйте на механику манипулятора во время сканирования.", True),
    ])

    calibration_guide = Column(spacing=16, scroll=ScrollMode.AUTO, controls=[
        Container(height=5), section_title("1. Инициализация и ручное позиционирование"),
        regular_text("Нажмите «Подключить камеру» для вывода видеопотока."),
        regular_text("Нажмите «Откалибровать манипулятор» для перехода в Home.", "• Калибровка осей: "),
        regular_text("Используйте кнопки перемещения по X, Y, Z и кнопки обнуления координат.", "• Управление: "),
        section_title("2. Установка референсных точек и расчет угла"),
        regular_text("Установите и сохраните координаты двух референсных кристаллов."),
        regular_text("Программа рассчитает угол поворота пластины и скорректирует траекторию."),
        section_title("3. Автоматические алгоритмы настройки"),
        regular_text("Автофокусировка подстраивает резкость по эталону."),
        regular_text("Автоцентровка определяет границы кристалла и наводит оптическую ось в центр."),
    ])

    statistics_guide = Column(spacing=16, scroll=ScrollMode.AUTO, controls=[
        Container(height=5), section_title("1. Назначение и доступ"),
        regular_text("Вкладка аккумулирует протоколы инспекций и инструменты фильтрации."),
        section_title("2. Фильтры и отчеты"),
        regular_text("Можно фильтровать отчеты по типу пластины, размерам кристалла, датам и оператору."),
        regular_text("Сводный отчет содержит статистику дефектов и продуктивность операторов."),
    ])

    picture_guide = Column(spacing=16, scroll=ScrollMode.AUTO, controls=[
        Container(height=5), section_title("1. Настройка оптических параметров"),
        regular_text("Настройте яркость, контрастность, насыщенность и зернистость видеопотока."),
        section_title("2. Цветовые каналы и сравнение"),
        regular_text("Каналы Red, Green и Blue позволяют выделить нужные элементы изображения."),
    ])

    measurement_guide = Column(spacing=16, scroll=ScrollMode.AUTO, controls=[
        Container(height=5), section_title("1. Калибровка масштабного коэффициента"),
        regular_text("Выберите единицы измерения и задайте коэффициент перевода пикселей в физические единицы."),
        section_title("2. Графические инструменты"),
        regular_text("Используйте отрезок, эллипс, прямоугольник и треугольник для измерения объектов."),
    ])

    model_status = Text("Выберите .pt-файл для нужного типа дефекта.", size=14,
                        color=application_colors["text"])

    def model_row(defect_key: str, title: str) -> Row:
        path_field = TextField(label=title, read_only=True, expand=True,
                               color=application_colors["text"])
        try:
            path_field.value = get_version(read_models_json(), defect_key).get("path", "")
        except (OSError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            pass

        def on_select(e):
            selected = choose_pt_file()
            if not selected:
                return
            try:
                imgsz = read_model_imgsz(selected)
                stored_path = save_model_version(defect_key, selected, imgsz)
            except Exception as exc:
                model_status.value = "Модель не сохранена. Выберите подходящий .pt-файл."
                model_status.color = Colors.RED_400
                show_error(
                    "Ошибка выбора модели",
                    str(exc),
                    e.page,
                    config,
                    "Понятно",
                )
            else:
                path_field.value = stored_path
                model_status.value = f"Модель «{title}» сохранена (imgsz={imgsz})."
                model_status.color = application_colors["active"]
            e.page.update()

        button = TextButton(
            content=Text("Выбрать .pt", size=18, font_family="Montserrat",
                         weight=FontWeight.BOLD,
                         color=application_colors.get("background", Colors.WHITE)),
            width=180, height=48, on_click=on_select,
            style=ButtonStyle(
                bgcolor=application_colors.get("active", Colors.BLUE_500),
                color=application_colors.get("text", Colors.WHITE),
                overlay_color=application_colors.get("hover", Colors.BLUE_700),
                shape=RoundedRectangleBorder(radius=8),
            ),
        )
        return Row(controls=[path_field, button], spacing=12)

    neural_network_guide = Column(spacing=16, scroll=ScrollMode.AUTO, controls=[
        Container(height=5), section_title("Модели для поиска дефектов"),
        regular_text("Выберите обученные модели YOLO."),
        info_card("В первое окно выбирайте модель для дефекта «Инородное тело в центре кристалла». Для нее требуется размер 1280 на 720 пикселей."),
        model_row("black_point", "Модель для обнаружения дефекта «Инородное тело в центре кристалла»"),
        info_card("Во второе окно выбирайте модель для дефекта «Ошибка реза». Для нее требуется размер 608 на 400 пикселей."),
        model_row("cutting_error", "Модель для обнаружения дефекта «Ошибка реза»"),
        info_card("Если размеры изображений, на которых обучалась нейросеть не подходят для определённого поля, модель отклоняется.", True),
        model_status,
    ])

    tabs = Tabs(selected_index=0, animation_duration=300,
                label_color=application_colors["active"],
                unselected_label_color=application_colors["text"],
                indicator_color=application_colors["active"],
                tabs=[
                    Tab(text="Инспекция кристаллов", content=Container(content=inspection_guide, padding=padding.all(12))),
                    Tab(text="Калибровка системы", content=Container(content=calibration_guide, padding=padding.all(12))),
                    Tab(text="Статистика и отчеты", content=Container(content=statistics_guide, padding=padding.all(12))),
                    Tab(text="Настройка камеры", content=Container(content=picture_guide, padding=padding.all(12))),
                    Tab(text="Измерение объектов", content=Container(content=measurement_guide, padding=padding.all(12))),
                    Tab(text="Обучение нейросети", content=Container(content=neural_network_guide, padding=padding.all(12))),
                ])

    guide_text = Text(value="Руководство пользователя", size=22,
                      weight=FontWeight.BOLD, color=application_colors["text"], no_wrap=True)
    marquee_row = Row(controls=[guide_text, Container(width=150)], width=250, scroll=ScrollMode.HIDDEN)
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

    return Tab(
        text="Руководство пользователя",
        tab_content=Container(content=marquee_row, width=250,
                              on_hover=on_guide_hover, alignment=alignment.center),
        content=Container(content=tabs, padding=10,
                          bgcolor=application_colors["background"]),
    )