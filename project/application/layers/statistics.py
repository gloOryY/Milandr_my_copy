"""Статистика инспекций с фильтрацией, текстовыми отчетами и круговыми диаграммами."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from flet import *

from project.application.addition.colors import color_mode
from project.application.addition.logger import logger
from project.configuration.config_manager import ConfigManager
from project.application.addition.user_profile_widget import is_user_delegated


def key_name(value: Any) -> str:
    return "".join(c for c in str(value).strip().lower() if c.isalnum())


def to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = value.replace(",", ".")
        return float(value)
    except (TypeError, ValueError):
        return default


def show_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def as_dict(value: Any) -> dict[str, Any]:
    return {key_name(k): v for k, v in value.items()} if isinstance(value, dict) else {}


def find_value(root: Any, *names: str, default: Any = None) -> Any:
    wanted = {key_name(n) for n in names}
    for item in walk(root):
        if isinstance(item, dict):
            data = as_dict(item)
            for name in wanted:
                if name in data:
                    return data[name]
    return default


def find_dict(root: Any, *names: str) -> dict[str, Any]:
    return as_dict(find_value(root, *names, default={}))


def find_dies(root: Any) -> list[dict[str, Any]]:
    value = find_value(root, "dicesinfo", "diesinfo", "dice_info", "dies", default=[])
    return [as_dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def file_date(path: Path, modified: float) -> str:
    name = path.stem
    for fmt, length in (("%Y%m%d_%H%M%S", 15), ("%Y%m%d%H%M%S", 14)):
        for i in range(len(name)):
            try:
                return datetime.strptime(name[i:i + length], fmt).strftime("%d.%m.%Y %H:%M:%S")
            except ValueError:
                pass
    return datetime.fromtimestamp(modified).strftime("%d.%m.%Y %H:%M")


def parse_datetime(date_str: str) -> Optional[datetime]:
    if not date_str or date_str == "—":
        return None
    date_str = str(date_str).strip()
    formats = [
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y%m%d_%H%M%S"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    return None


@dataclass
class Inspection:
    path: Path
    raw: Any
    modified: float
    recognized: bool

    @property
    def dies(self):
        return find_dies(self.raw)

    @property
    def start_stats(self) -> dict[str, Any]:
        return find_dict(self.raw, "startstats", "start_stats")

    @property
    def final_stats(self) -> dict[str, Any]:
        return find_dict(self.raw, "finalstats", "final_stats")

    def value(self, *names, default=None):
        return find_value(self.raw, *names, default=default)

    @property
    def wafer(self):
        return show_value(self.value("waferid", "wafer_id", default=self.path.stem))

    @property
    def wafer_type(self) -> str:
        return str(self.value("wafertype", "wafer_type", default="300")).strip()

    @property
    def cell_size_x(self) -> float:
        return to_float(self.value("cellsizexmm", "cell_size_x_mm", default=0.0))

    @property
    def cell_size_y(self) -> float:
        return to_float(self.value("cellsizeymm", "cell_size_y_mm", default=0.0))

    @property
    def inspector(self) -> str:
        return show_value(self.value("inspector", "operator", default="Не указан"))

    @property
    def inspection_date(self) -> str:
        return show_value(self.value("inspectiondate", "inspection_date", default=self.date))

    @property
    def parsed_date(self) -> datetime:
        dt = parse_datetime(self.inspection_date)
        if dt:
            return dt
        return datetime.fromtimestamp(self.modified)

    @property
    def comment(self):
        return show_value(self.value("comment", "comments", "note", "notes", default="—"))

    @property
    def total(self):
        value = self.value("totaldice", "total_dice", default=None)
        return to_int(value) if value is not None else len(self.dies)

    @property
    def passed(self):
        val = self.final_stats.get("good")
        if val is not None:
            return to_int(val)
        return 0

    @property
    def failed(self):
        val = self.final_stats.get("bad")
        if val is not None:
            return to_int(val)
        return 0

    @property
    def defects(self):
        value = self.value("totaldefects", "total_defects", default=None)
        if value is not None:
            return to_int(value)
        return sum(to_int(d.get("totaldefectsondie", 0)) for d in self.dies)

    @property
    def checked(self):
        start_need = to_int(self.start_stats.get("needcheck", 0))
        final_need = to_int(self.final_stats.get("needcheck", 0))
        diff = start_need - final_need
        return max(0, diff)

    @property
    def avg_time(self):
        val = self.value("averagetimeperdie", "average_time_per_die", default=None)
        if val is None or val == "":
            return "—"
        try:
            f_val = float(val)
            return f"{f_val:.3f} сек"
        except (ValueError, TypeError):
            return str(val)

    @property
    def defects_statistics(self) -> dict[str, int]:
        val = self.value("defectsstatistics", "defects_statistics", default={})
        if isinstance(val, dict):
            return {k: to_int(v) for k, v in val.items() if to_int(v) > 0}
        return {}

    @property
    def date(self):
        return file_date(self.path, self.modified)


def create_statistics_layer(config: ConfigManager, current_user: dict = None) -> Tab:
    colors = color_mode(config)
    directory = Path(getattr(config, "statistics_reports_path", "") or ".")
    all_reports: list[Inspection] = []
    filtered_reports: list[Inspection] = []
    selected: set[Path] = set()
    hidden_reports: set[Path] = set()
    current: Inspection | None = None

    PALETTE = [
        Colors.RED_ACCENT_400, Colors.AMBER_500, Colors.BLUE_400, Colors.PURPLE_400,
        Colors.CYAN_400, Colors.LIGHT_GREEN_400, Colors.PINK_400, Colors.DEEP_ORANGE_400,
        Colors.INDIGO_400, Colors.TEAL_400, Colors.LIME_400, Colors.BROWN_400
    ]

    def is_admin_access() -> bool:
        """Проверяет права: администратор или оператор с делегированными правами."""
        if isinstance(current_user, dict):
            if current_user.get("role") == "admin":
                return True
            return is_user_delegated(current_user)
        return False

    def safe_update(control: Control) -> None:
        if control.page is None:
            return
        try:
            control.update()
        except Exception:
            try:
                control.page.update()
            except Exception:
                pass

    def message(page: Page, title: str, body: str, color=None):
        """Стилизованное диалоговое окно в теме приложения."""
        def close(event):
            if page.dialog is not None:
                page.dialog.open = False
                page.update()

        page.dialog = AlertDialog(
            modal=True,
            bgcolor=colors["background"],
            shape=RoundedRectangleBorder(radius=12),
            surface_tint_color=Colors.TRANSPARENT,
            content_padding=padding.all(24),
            actions_padding=padding.only(left=24, right=24, bottom=20),
            title=Row(
                controls=[
                    Icon(Icons.ADMIN_PANEL_SETTINGS_OUTLINED, color=colors["active"], size=28),
                    Text(
                        title,
                        size=22,
                        weight=FontWeight.BOLD,
                        color=colors["text"]
                    ),
                ],
                spacing=10,
                vertical_alignment=CrossAxisAlignment.CENTER,
            ),
            content=Container(
                width=460,
                content=Text(
                    body,
                    size=16,
                    color=colors["text"],
                    selectable=True
                ),
            ),
            actions=[
                ElevatedButton(
                    text="Закрыть",
                    width=130,
                    height=42,
                    on_click=close,
                    style=ButtonStyle(
                        shape=RoundedRectangleBorder(radius=8),
                        bgcolor=colors["inactive"],
                        color=colors["text"],
                        overlay_color=colors["hover"],
                        text_style=TextStyle(size=15, weight=FontWeight.BOLD),
                    ),
                )
            ],
            actions_alignment=MainAxisAlignment.END,
        )
        page.dialog.open = True
        page.update()

    def card(content, expand=False):
        return Container(content=content, padding=14, expand=expand,
                         bgcolor=colors["top_bar"], border_radius=12,
                         border=border.all(1, colors["inactive"]))

    def make_button(label, icon, width, callback, danger=False):
        return ElevatedButton(
            text=label, icon=icon, width=width, height=48, on_click=callback,
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=12),
                bgcolor=colors["red"] if danger else colors["inactive"],
                color=colors["text"], overlay_color=colors["hover"],
                text_style=TextStyle(size=16, weight=FontWeight.BOLD),
            ),
        )

    # === ЭЛЕМЕНТЫ ФИЛЬТРАЦИИ ===
    filter_wafer_type = Dropdown(
        label="Тип пластины",
        width=160,
        height=48,
        text_size=14,
        options=[
            dropdown.Option("ALL", "Все типы"),
            dropdown.Option("300", "300 мм"),
            dropdown.Option("200", "200 мм"),
            dropdown.Option("150", "150 мм"),
        ],
        value="ALL",
        color=colors["text"],
        bgcolor=colors["top_bar"],
        border_color=colors["inactive"],
    )

    filter_size_x = TextField(
        label="Разм. X (мм)",
        hint_text="напр. 2.95",
        width=130,
        height=48,
        text_size=14,
        color=colors["text"],
        bgcolor=colors["top_bar"],
        border_color=colors["inactive"],
    )

    filter_size_y = TextField(
        label="Разм. Y (мм)",
        hint_text="напр. 3.62",
        width=130,
        height=48,
        text_size=14,
        color=colors["text"],
        bgcolor=colors["top_bar"],
        border_color=colors["inactive"],
    )

    filter_date_from = TextField(
        label="Дата С (ДД.ММ.ГГГГ)",
        hint_text="12.03.2025",
        width=175,
        height=48,
        text_size=14,
        color=colors["text"],
        bgcolor=colors["top_bar"],
        border_color=colors["inactive"],
    )

    filter_date_to = TextField(
        label="Дата ПО (ДД.ММ.ГГГГ)",
        hint_text="21.06.2025",
        width=175,
        height=48,
        text_size=14,
        color=colors["text"],
        bgcolor=colors["top_bar"],
        border_color=colors["inactive"],
    )

    filter_inspector = Dropdown(
        label="Инспектор",
        width=240,
        height=48,
        text_size=14,
        options=[dropdown.Option("ALL", "Все инспекторы")],
        value="ALL",
        color=colors["text"],
        bgcolor=colors["top_bar"],
        border_color=colors["inactive"],
    )

    folder = Text(
        f"Каталог: {directory.resolve()}" if directory.is_dir() else "Каталог: не выбран",
        color=colors["unclickable"],
        size=14,
        weight=FontWeight.W_500,
        expand=True
    )
    
    report_list = Column(scroll=ScrollMode.AUTO, spacing=7, expand=True)
    details = Column(scroll=ScrollMode.AUTO, spacing=10, expand=True)
    analytics_view = Column(scroll=ScrollMode.AUTO, spacing=15, expand=True)
    charts = Column(scroll=ScrollMode.AUTO, expand=True)
    
    search = TextField(
        label="ID кристалла (или диапазон 1-100) и Enter",
        width=420,
        color=colors["text"], bgcolor=colors["top_bar"],
        border_color=colors["text"], focused_border_color=colors["active"],
        label_style=TextStyle(color=colors["text"]),
    )
    search_status = Text("", size=13, color=colors["unclickable"])
    filtered_dies: list[dict[str, Any]] = []

    dies_table = DataTable(
        columns=[DataColumn(Text(x, color=colors["text"], weight=FontWeight.BOLD))
                 for x in ("ID", "Map X", "Map Y", "Символ", "Статус", "Дефекты")],
        rows=[],
        heading_row_color=colors["inactive"],
        border=border.all(1, colors["inactive"]),
        column_spacing=20,
        horizontal_margin=12,
    )
    dies_view = Column([dies_table], scroll=ScrollMode.AUTO, expand=True)

    file_picker = FilePicker()

    def on_dialog_result(e: FilePickerResultEvent):
        if not e.path:
            return
        nonlocal directory, current
        directory = Path(e.path)
        folder.value = f"Каталог: {directory.resolve()}"
        folder.update()
        current = None
        all_reports.clear()
        filtered_reports.clear()
        selected.clear()
        hidden_reports.clear()
        details.controls = [Text("Выберите инспекцию в списке слева.", color=colors["unclickable"], size=18)]
        safe_update(details)
        load_reports()
        apply_reports_filters()
        try:
            config.statistics_reports_path = str(directory)
        except Exception:
            pass

    file_picker.on_result = on_dialog_result

    def choose_directory(event):
        # Проверка прав администратора / делегирования
        if not is_admin_access():
            message(event.page, "Ограничение прав", "Выбор каталога отчётов доступен только Администратору.\nОбратитесь к администратору для делегирования прав.", Colors.AMBER_400)
            return

        if file_picker not in event.page.overlay:
            event.page.overlay.append(file_picker)
            event.page.update()
        file_picker.get_directory_path(dialog_title="Выберите каталог с JSON-отчётами")

    def read_report(path: Path) -> Optional[Inspection]:
        try:
            with path.open("r", encoding="utf-8-sig") as stream:
                raw = json.load(stream)
            if not isinstance(raw, (dict, list)):
                return None
            recognized_names = {"waferid", "dicesinfo", "diesinfo", "finalstats", "totaldice", "totalfaildice", "totalpassdice"}
            recognized = any(key_name(k) in recognized_names for item in walk(raw) if isinstance(item, dict) for k in item)
            return Inspection(path, raw, path.stat().st_mtime, recognized)
        except Exception as error:
            logger.warning(f"Не удалось прочитать JSON {path}: {error}")
            return None

    def load_reports():
        all_reports.clear()
        if not directory.is_dir():
            return
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            if path in hidden_reports:
                continue
            report = read_report(path)
            if report is not None:
                all_reports.append(report)
        all_reports.sort(key=lambda item: item.parsed_date)
        update_inspector_options()

    def update_inspector_options():
        inspectors = sorted(list({r.inspector for r in all_reports if r.inspector and r.inspector != "—"}))
        filter_inspector.options = [dropdown.Option("ALL", "Все инспекторы")] + [dropdown.Option(insp, insp) for insp in inspectors]
        safe_update(filter_inspector)

    # === ЛОГИКА ФИЛЬТРАЦИИ ОТЧЕТОВ ===
    def apply_reports_filters(event=None):
        nonlocal filtered_reports
        filtered_reports = all_reports.copy()

        # 1. По типу пластины
        if filter_wafer_type.value and filter_wafer_type.value != "ALL":
            filtered_reports = [r for r in filtered_reports if r.wafer_type == filter_wafer_type.value]

        # 2. По размерам кристаллов
        target_x = to_float(filter_size_x.value, 0.0) if filter_size_x.value else 0.0
        target_y = to_float(filter_size_y.value, 0.0) if filter_size_y.value else 0.0

        if target_x > 0:
            filtered_reports = [r for r in filtered_reports if abs(r.cell_size_x - target_x) <= 0.05]
        if target_y > 0:
            filtered_reports = [r for r in filtered_reports if abs(r.cell_size_y - target_y) <= 0.05]

        # 3. По датам
        d_from = parse_datetime(filter_date_from.value.strip()) if filter_date_from.value else None
        d_to = parse_datetime(filter_date_to.value.strip()) if filter_date_to.value else None
        if d_to:
            d_to = d_to.replace(hour=23, minute=59, second=59)

        if d_from:
            filtered_reports = [r for r in filtered_reports if r.parsed_date >= d_from]
        if d_to:
            filtered_reports = [r for r in filtered_reports if r.parsed_date <= d_to]

        # 4. По инспектору
        if filter_inspector.value and filter_inspector.value != "ALL":
            filtered_reports = [r for r in filtered_reports if r.inspector == filter_inspector.value]

        update_list()
        build_analytics_summary()
        update_charts()

    def reset_reports_filters(event=None):
        filter_wafer_type.value = "ALL"
        filter_size_x.value = ""
        filter_size_y.value = ""
        filter_date_from.value = ""
        filter_date_to.value = ""
        filter_inspector.value = "ALL"
        safe_update(filter_wafer_type)
        safe_update(filter_size_x)
        safe_update(filter_size_y)
        safe_update(filter_date_from)
        safe_update(filter_date_to)
        safe_update(filter_inspector)
        apply_reports_filters()

    # === МОДАЛЬНОЕ ОКНО: КРУГОВОЙ ГРАФИК ДЛЯ КОНКРЕТНОЙ ИНСПЕКЦИИ ===
    def open_inspection_pie_chart_dialog(page: Page, report: Inspection):
        def close_dialog(e):
            page.dialog.open = False
            page.update()

        defect_stats = report.defects_statistics
        total_defects_count = sum(defect_stats.values())
        
        defect_sections = []
        defect_legend = []
        
        if total_defects_count > 0:
            for idx, (defect_name, count) in enumerate(defect_stats.items()):
                c = PALETTE[idx % len(PALETTE)]
                pct = (count / total_defects_count) * 100
                defect_sections.append(
                    PieChartSection(
                        value=count,
                        title=f"{pct:.1f}%" if pct >= 5 else "",
                        title_style=TextStyle(size=12, weight=FontWeight.BOLD, color=Colors.WHITE),
                        color=c,
                        radius=65,
                    )
                )
                defect_legend.append(
                    Row([
                        Container(width=14, height=14, bgcolor=c, border_radius=3),
                        Text(f"{defect_name}: {count} шт. ({pct:.1f}%)", size=13, color=colors["text"])
                    ], spacing=6)
                )
        else:
            defect_legend.append(Text("Дефекты отсутствуют (0)", color=colors["active"], size=14))

        total_d = report.total or 1
        pass_pct = (report.passed / total_d) * 100
        fail_pct = (report.failed / total_d) * 100
        
        pass_fail_sections = [
            PieChartSection(value=report.passed, title=f"{pass_pct:.1f}%", color=colors["active"], radius=60, title_style=TextStyle(color=Colors.WHITE, weight=FontWeight.BOLD, size=12)),
            PieChartSection(value=report.failed, title=f"{fail_pct:.1f}%" if report.failed > 0 else "", color=colors["red"], radius=60, title_style=TextStyle(color=Colors.WHITE, weight=FontWeight.BOLD, size=12)),
        ]

        pie_defects_chart = PieChart(
            sections=defect_sections if defect_sections else [PieChartSection(value=1, title="Нет", color=colors["inactive"], radius=60)],
            sections_space=2,
            center_space_radius=35,
            width=220,
            height=220,
        )

        pie_pass_fail_chart = PieChart(
            sections=pass_fail_sections,
            sections_space=2,
            center_space_radius=35,
            width=220,
            height=220,
        )

        content_box = Container(
            width=800,
            content=Column([
                Text(f"Пластина: {report.wafer} ({report.inspection_date})", size=18, weight=FontWeight.BOLD, color=colors["text"]),
                Text(f"Инспектор: {report.inspector} • Тип: {report.wafer_type} мм • Размер: {report.cell_size_x}×{report.cell_size_y} мм", color=colors["unclickable"]),
                Divider(color=colors["inactive"]),
                Row([
                    Column([
                        Text("Виды обнаруженных дефектов", size=16, weight=FontWeight.BOLD, color=colors["text"]),
                        Container(content=pie_defects_chart, alignment=alignment.center),
                        Container(content=Column(defect_legend, spacing=4, scroll=ScrollMode.AUTO, height=130), width=360),
                    ], horizontal_alignment=CrossAxisAlignment.CENTER, expand=True),
                    
                    VerticalDivider(color=colors["inactive"]),
                    
                    Column([
                        Text("Выход годных кристаллов", size=16, weight=FontWeight.BOLD, color=colors["text"]),
                        Container(content=pie_pass_fail_chart, alignment=alignment.center),
                        Column([
                            Row([Container(width=14, height=14, bgcolor=colors["active"], border_radius=3), Text(f"Годные (Pass): {report.passed} шт. ({pass_pct:.1f}%)", size=13, color=colors["text"])]),
                            Row([Container(width=14, height=14, bgcolor=colors["red"], border_radius=3), Text(f"Негодные (Fail): {report.failed} шт. ({fail_pct:.1f}%)", size=13, color=colors["text"])]),
                            Row([Container(width=14, height=14, bgcolor=colors["inactive"], border_radius=3), Text(f"Всего кристаллов: {report.total} шт.", size=13, color=colors["unclickable"])]),
                        ], spacing=6),
                    ], horizontal_alignment=CrossAxisAlignment.CENTER, expand=True),
                ], expand=True),
            ], tight=True, spacing=10),
            padding=10,
        )

        page.dialog = AlertDialog(
            modal=True,
            title=Text("Круговой анализ инспекции", weight=FontWeight.BOLD),
            content=content_box,
            actions=[TextButton("Закрыть", on_click=close_dialog, style=ButtonStyle(color=colors["active"]))],
        )
        page.dialog.open = True
        page.update()

    # === СВОДНЫЙ ТЕКСТОВЫЙ ОТЧЁТ И АНАЛИТИКА ПО ВЫБОРКЕ ===
    def build_analytics_summary():
        analytics_view.controls.clear()
        if not filtered_reports:
            analytics_view.controls.append(Text("Нет данных по заданным критериям фильтрации.", color=colors["unclickable"], size=18))
            safe_update(analytics_view)
            return

        total_inspections = len(filtered_reports)
        total_dice_sum = sum(r.total for r in filtered_reports)
        total_passed_sum = sum(r.passed for r in filtered_reports)
        total_failed_sum = sum(r.failed for r in filtered_reports)
        total_defects_sum = sum(r.defects for r in filtered_reports)
        overall_yield = (total_passed_sum / total_dice_sum * 100) if total_dice_sum else 0.0

        aggregated_defects: dict[str, int] = {}
        for r in filtered_reports:
            for d_name, count in r.defects_statistics.items():
                aggregated_defects[d_name] = aggregated_defects.get(d_name, 0) + count

        inspector_stats: dict[str, dict[str, int]] = {}
        for r in filtered_reports:
            insp = r.inspector
            if insp not in inspector_stats:
                inspector_stats[insp] = {"wafers": 0, "dice": 0, "passed": 0, "failed": 0, "defects": 0}
            inspector_stats[insp]["wafers"] += 1
            inspector_stats[insp]["dice"] += r.total
            inspector_stats[insp]["passed"] += r.passed
            inspector_stats[insp]["failed"] += r.failed
            inspector_stats[insp]["defects"] += r.defects

        text_report_lines = [
            f"• Всего пластин в выборке: {total_inspections} шт.",
            f"• Проверено кристаллов: {total_dice_sum} шт.",
            f"• Годных кристаллов: {total_passed_sum} шт. ({overall_yield:.2f}%)",
            f"• Негодных кристаллов: {total_failed_sum} шт. ({100 - overall_yield:.2f}%)",
            f"• Общее количество зафиксированных дефектов: {total_defects_sum} шт.",
        ]

        if filter_inspector.value and filter_inspector.value != "ALL":
            text_report_lines.insert(0, f"Инспектор: {filter_inspector.value}")

        summary_defect_sections = []
        summary_defect_legend = []
        for idx, (def_name, def_cnt) in enumerate(sorted(aggregated_defects.items(), key=lambda x: x[1], reverse=True)):
            c = PALETTE[idx % len(PALETTE)]
            pct = (def_cnt / total_defects_sum * 100) if total_defects_sum else 0
            summary_defect_sections.append(
                PieChartSection(value=def_cnt, title=f"{pct:.1f}%" if pct >= 5 else "", color=c, radius=65, title_style=TextStyle(color=Colors.WHITE, weight=FontWeight.BOLD, size=11))
            )
            summary_defect_legend.append(
                Row([Container(width=12, height=12, bgcolor=c, border_radius=2), Text(f"{def_name}: {def_cnt} ({pct:.1f}%)", size=13, color=colors["text"])], spacing=6)
            )

        pie_summary_chart = PieChart(
            sections=summary_defect_sections if summary_defect_sections else [PieChartSection(value=1, title="0", color=colors["inactive"])],
            sections_space=2,
            center_space_radius=40,
            width=240,
            height=240,
        )

        inspector_rows = []
        for insp_name, data in inspector_stats.items():
            insp_yield = (data["passed"] / data["dice"] * 100) if data["dice"] else 0
            inspector_rows.append(DataRow(cells=[
                DataCell(Text(insp_name, color=colors["text"], weight=FontWeight.BOLD)),
                DataCell(Text(str(data["wafers"]), color=colors["text"])),
                DataCell(Text(str(data["dice"]), color=colors["text"])),
                DataCell(Text(str(data["passed"]), color=colors["active"])),
                DataCell(Text(f"{data['failed']} ({100 - insp_yield:.1f}%)", color=colors["red"])),
                DataCell(Text(str(data["defects"]), color=colors["red"])),
            ]))

        inspector_table = DataTable(
            columns=[DataColumn(Text(x, color=colors["text"], weight=FontWeight.BOLD)) for x in ("Инспектор", "Пластин", "Кристаллов", "Годных", "Негодных", "Дефектов")],
            rows=inspector_rows,
            heading_row_color=colors["inactive"],
            border=border.all(1, colors["inactive"]),
            column_spacing=24,
        )

        analytics_view.controls = [
            Text("Сводный текстовый отчёт и распределение", size=22, weight=FontWeight.BOLD, color=colors["text"]),
            Row([
                card(Column([
                    Text("Итоговые показатели выборки", size=18, weight=FontWeight.BOLD, color=colors["active"]),
                    Divider(color=colors["inactive"]),
                    Column([Text(line, size=15, color=colors["text"], selectable=True) for line in text_report_lines], spacing=6),
                ]), expand=True),
                card(Column([
                    Text("Круговая диаграмма дефектов (Выборка)", size=18, weight=FontWeight.BOLD, color=colors["text"]),
                    Row([
                        Container(content=pie_summary_chart, alignment=alignment.center),
                        Container(content=Column(summary_defect_legend, spacing=4, scroll=ScrollMode.AUTO, height=180), width=320),
                    ], spacing=15),
                ]), expand=True),
            ], spacing=15),
            Text("Выработка по инспекторам", size=20, weight=FontWeight.BOLD, color=colors["text"]),
            card(Column([inspector_table], scroll=ScrollMode.AUTO)),
        ]
        safe_update(analytics_view)

    # === РАБОТА С КРИСТАЛЛАМИ ТЕКУЩЕЙ ПЛАСТИНЫ ===
    def apply_filter(force_message=False):
        nonlocal filtered_dies
        filtered_dies = []
        
        if current is None:
            search_status.value = "Выберите инспекцию на первой подвкладке."
            safe_update(search_status)
            build_dies_table()
            return

        q = (search.value or "").strip()
        
        if not q:
            search_status.value = "Ожидание ввода. Введите ID или диапазон (например, 1-100) и нажмите Enter."
        else:
            if "-" in q and q.count("-") == 1:
                try:
                    start_str, end_str = q.split("-")
                    start_id = int(start_str.strip())
                    end_id = int(end_str.strip())
                    
                    for die in current.dies:
                        die_id_raw = die.get("id")
                        try:
                            die_id_int = int(die_id_raw)
                            if start_id <= die_id_int <= end_id:
                                filtered_dies.append(die)
                        except (ValueError, TypeError):
                            pass
                except ValueError:
                    for die in current.dies:
                        did = show_value(die.get("id"))
                        if q == did or q.casefold() in did.casefold():
                            filtered_dies.append(die)
            else:
                for die in current.dies:
                    did = show_value(die.get("id"))
                    if q == did or q.casefold() in did.casefold():
                        filtered_dies.append(die)
                        
            search_status.value = f"Найдено: {len(filtered_dies)}"
            if force_message:
                search_status.value += f" (по запросу '{q}')"
                
        build_dies_table()
        safe_update(search_status)

    def build_dies_table():
        if current is None or not filtered_dies:
            dies_table.rows = []
            safe_update(dies_table)
            return
        rows = []
        for die in filtered_dies:
            count = to_int(die.get("totaldefectsondie", 0))
            rows.append(DataRow(cells=[
                DataCell(Text(show_value(die.get("id")), color=colors["text"])),
                DataCell(Text(show_value(die.get("mapx")), color=colors["text"])),
                DataCell(Text(show_value(die.get("mapy")), color=colors["text"])),
                DataCell(Text(show_value(die.get("symbol")), color=colors["text"])),
                DataCell(Text(show_value(die.get("status")), color=colors["text"])),
                DataCell(Text(str(count), color=colors["red"] if count else colors["text"])),
            ]))
        dies_table.rows = rows
        safe_update(dies_table)

    def show_report(report: Inspection):
        nonlocal current, filtered_dies
        current = report
        
        percent = round(report.failed * 100 / report.total, 2) if report.total else 0
        fields = [
            ("Пластина", "waferid"),
            ("Тип пластины", "wafertype"),
            ("Инспектор", "inspector"),
            ("Дата инспекции", "inspectiondate"),
            ("Размер X, мм", "cellsizexmm"),
            ("Размер Y, мм", "cellsizeymm"),
            ("Комментарий", "comment"),
            ("Имя JSON", "jsonprotocolfilename"),
            ("Строк", "totalrows"),
            ("Столбцов", "totalcols"),
            ("Время инспекции", "inspectiontimeformatted"),
            ("Ср. время на кристалл", "averagetimeperdie"),
            ("Каталог", "mainfolderpath")
        ]
        
        metrics = Row([
            card(Column([Text("Всего", color=colors["unclickable"]), Text(str(report.total), size=20, color=colors["text"], weight=FontWeight.BOLD)]), True),
            card(Column([Text("Проверено", color=colors["unclickable"]), Text(str(report.checked), size=20, color=colors["text"], weight=FontWeight.BOLD)]), True),
            card(Column([Text("Годных", color=colors["unclickable"]), Text(str(report.passed), size=20, color=colors["active"], weight=FontWeight.BOLD)]), True),
            card(Column([Text("Негодных", color=colors["unclickable"]), Text(f"{report.failed} ({percent}%)", size=20, color=colors["red"], weight=FontWeight.BOLD)]), True),
            card(Column([Text("Дефектов", color=colors["unclickable"]), Text(str(report.defects), size=20, color=colors["red"], weight=FontWeight.BOLD)]), True),
        ], spacing=8)

        pie_btn = ElevatedButton(
            text="Круговой график дефектов",
            icon=Icons.PIE_CHART_OUTLINE,
            height=45,
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=10),
                bgcolor=colors["active"],
                color=colors["text"],
                text_style=TextStyle(size=15, weight=FontWeight.BOLD)
            ),
            on_click=lambda e, r=report: open_inspection_pie_chart_dialog(e.page, r)
        )

        details_controls = [
            Row([
                Column([
                    Text(f"Инспекция: {report.wafer}", size=22, weight=FontWeight.BOLD, color=colors["text"]),
                    Text(f"{report.date} • {report.path.name}", color=colors["unclickable"]),
                ], expand=True),
                pie_btn
            ], alignment=MainAxisAlignment.SPACE_BETWEEN),
            metrics,
        ]

        if report.comment and report.comment != "—":
            details_controls.append(
                card(
                    Column([
                        Row([Icon(Icons.COMMENT_OUTLINED, color=colors["active"], size=20),
                             Text("Комментарий к пластине", size=16, weight=FontWeight.BOLD, color=colors["text"])]),
                        Text(report.comment, size=14, color=colors["text"], selectable=True),
                    ], spacing=6)
                )
            )

        details_controls.append(
            card(Column([
                Text("Метаданные пластины", size=18, weight=FontWeight.BOLD, color=colors["text"]),
                *[Row([Text(label, width=200, color=colors["unclickable"]), Text(show_value(report.value(key)), color=colors["text"], selectable=True)]) for label, key in fields],
            ]))
        )

        if not report.recognized:
            details_controls.insert(2, Text("Raw report: структура распознана частично.", color=colors["active"]))

        details.controls = details_controls
        safe_update(details)
        
        search.value = ""
        safe_update(search)
        apply_filter()

    # ...=== СТОЛБЧАТЫЕ ГРАФИКИ ===...
    def update_charts():
        WIDTH_PER_GROUP = 140
        MIN_CHART_WIDTH = 900
        CHART_HEIGHT = 520
        LABEL_MAX_CHARS = 20
        SCROLLBAR_RESERVE = 40

        chosen = [item for item in filtered_reports if item.path in selected] or filtered_reports
        charts.controls.clear()
        if not chosen:
            charts.controls.append(Text("JSON-отчёты не найдены.", color=colors["unclickable"], size=18))
            safe_update(charts)
            return

        all_defect_types = set()
        for report in chosen:
            stats = report.defects_statistics
            if isinstance(stats, dict):
                for orig_key in stats.keys():
                    all_defect_types.add(orig_key)

        all_defect_types = sorted(list(all_defect_types))

        bar_groups = []
        x_labels = []
        max_y = 0

        for i, report in enumerate(chosen):
            x_val = i + 1
            wafer_clean = str(report.wafer).replace('"', '').replace("'", "")
            waf_label = f"{x_val}. {wafer_clean}"
            short_waf = waf_label if len(waf_label) <= LABEL_MAX_CHARS else waf_label[:LABEL_MAX_CHARS - 2] + ".."
            x_labels.append(
                ChartAxisLabel(
                    value=x_val,
                    label=Container(
                        content=Text(short_waf, size=12, color=colors["text"], no_wrap=True),
                        padding=padding.only(top=6),
                    ),
                )
            )

            rods = []
            passed = report.passed
            rods.append(BarChartRod(to_y=passed, color=colors["active"], tooltip=f"{wafer_clean} • Годные: {passed}"))
            max_y = max(max_y, passed)

            total_defs = report.defects
            rods.append(BarChartRod(to_y=total_defs, color=colors["red"], tooltip=f"{wafer_clean} • Всего дефектов: {total_defs}"))
            max_y = max(max_y, total_defs)

            raw_stats = report.defects_statistics
            for j, def_type in enumerate(all_defect_types):
                count = to_int(raw_stats.get(def_type, 0))
                color_idx = (j + 2) % len(PALETTE)
                def_clean = str(def_type).replace('"', '').replace("'", "")
                rods.append(BarChartRod(to_y=count, color=PALETTE[color_idx], tooltip=f"{wafer_clean} • {def_clean}: {count}"))
                max_y = max(max_y, count)

            bar_groups.append(BarChartGroup(x=x_val, bar_rods=rods))

        step = max(1, (max_y + 5) // 6)
        y_max = max(step * 6, max_y, 1)
        chart_max_y = y_max + step * 2

        legend_items = [
            Row([Container(width=12, height=12, bgcolor=colors["active"], border_radius=2), Text("Годные кристаллы", color=colors["text"], size=12)]),
            Row([Container(width=12, height=12, bgcolor=colors["red"], border_radius=2), Text("Всего дефектов", color=colors["text"], size=12)])
        ]
        for j, def_type in enumerate(all_defect_types):
            c_idx = (j + 2) % len(PALETTE)
            legend_items.append(Row([Container(width=12, height=12, bgcolor=PALETTE[c_idx], border_radius=2), Text(def_type, color=colors["text"], size=12)]))

        chart_width = max(MIN_CHART_WIDTH, WIDTH_PER_GROUP * len(chosen))

        bar_chart = BarChart(
            bar_groups=bar_groups,
            left_axis=ChartAxis(
                labels=[ChartAxisLabel(value=i, label=Text(str(i), size=12, color=colors["text"])) for i in range(0, int(chart_max_y) + 1, step)],
                labels_size=45,
                title=Text("Количество", color=colors["text"], weight=FontWeight.BOLD),
            ),
            bottom_axis=ChartAxis(labels=x_labels, labels_size=60),
            horizontal_grid_lines=ChartGridLines(color=colors.get("inactive", Colors.GREY_800), width=1, dash_pattern=[4, 4]),
            tooltip_bgcolor=colors.get("top_bar", Colors.GREY_900),
            max_y=chart_max_y,
            width=chart_width,
            height=CHART_HEIGHT,
            interactive=True,
        )

        fixed_width_chart = Container(content=bar_chart, width=chart_width, height=CHART_HEIGHT)

        scrollable_row = Row(
            controls=[fixed_width_chart],
            scroll=ScrollMode.ALWAYS,
            spacing=0,
        )

        # Скроллбар в стиле проекта: акцентный цвет для "бегунка", нейтральный для трека
        scroll_container = Container(
            content=scrollable_row,
            height=CHART_HEIGHT + SCROLLBAR_RESERVE,
            padding=padding.only(bottom=SCROLLBAR_RESERVE - 10),
            theme=Theme(
                scrollbar_theme=ScrollbarTheme(
                    thumb_visibility=True,
                    track_visibility=True,
                    thickness=10,
                    thumb_color=colors["active"],
                    track_color=colors["inactive"],
                    track_border_color=colors["inactive"],
                    radius=6,
                )
            ),
        )

        # Заголовок оставлен, подсказка про "Показано плат: N" убрана полностью
        charts.controls = [
            Text("Сравнительное количество дефектов и годных кристаллов", size=22, weight=FontWeight.BOLD, color=colors["text"]),
            card(scroll_container),
            Row(legend_items, wrap=True, spacing=15, run_spacing=10),
        ]
        safe_update(charts)

    def update_list():
        report_list.controls.clear()
        for report in filtered_reports:
            checkbox = Checkbox(value=report.path in selected, active_color=colors["active"])
            def toggle(event, item=report):
                if event.control.value:
                    selected.add(item.path)
                else:
                    selected.discard(item.path)
                update_charts()
            checkbox.on_change = toggle
            report_list.controls.append(card(Row([
                checkbox,
                Column([
                    Text(report.wafer, size=17, weight=FontWeight.BOLD, color=colors["text"]),
                    Text(f"{report.date} • {report.inspector} • {report.cell_size_x}×{report.cell_size_y} мм", size=13, color=colors["unclickable"]),
                    Text(f"Годные: {report.passed} | Негодные: {report.failed} | Дефектов: {report.defects}", size=12, color=colors["active"]),
                ], expand=True),
                IconButton(icon=Icons.VISIBILITY_OUTLINED, icon_color=colors["active"], tooltip="Открыть карточку", on_click=lambda e, item=report: show_report(item)),
                IconButton(icon=Icons.PIE_CHART, icon_color=colors["active"], tooltip="Круговой график", on_click=lambda e, item=report: open_inspection_pie_chart_dialog(e.page, item)),
            ], vertical_alignment=CrossAxisAlignment.CENTER)))
            
        if not filtered_reports:
            report_list.controls.append(Text("Инспекции не найдены по текущим критериям.", color=colors["unclickable"], size=16))
        safe_update(report_list)

    def refresh(event=None):
        nonlocal current
        current_dir = directory
        all_reports.clear()
        filtered_reports.clear()
        selected.clear()
        current = None
        details.controls = [Text("Выберите инспекцию в списке слева.", color=colors["unclickable"], size=18)]
        safe_update(details)
        if current_dir.is_dir():
            load_reports()
        apply_reports_filters()

    def remove_selected(event):
        nonlocal current
        if not selected:
            message(event.page, "Статистика", "Отметьте инспекции галочками, которые нужно убрать из списка.")
            return
        
        for p in selected:
            hidden_reports.add(p)
            
        removed = selected.copy()
        all_reports[:] = [item for item in all_reports if item.path not in removed]
        selected.clear()
        
        if current and current.path in removed:
            current = None
            details.controls = [Text("Выберите инспекцию в списке слева.", color=colors["unclickable"], size=18)]
            safe_update(details)
            dies_table.rows = []
            safe_update(dies_table)
            search_status.value = ""
            safe_update(search_status)
            
        apply_reports_filters()

    search.on_submit = lambda e: apply_filter(force_message=True)

    # Привязка фильтров
    filter_wafer_type.on_change = apply_reports_filters
    filter_inspector.on_change = apply_reports_filters
    filter_size_x.on_submit = apply_reports_filters
    filter_size_y.on_submit = apply_reports_filters
    filter_date_from.on_submit = apply_reports_filters
    filter_date_to.on_submit = apply_reports_filters

    load_reports()
    apply_reports_filters()

    # Панель фильтров
    filter_panel = card(
        Column([
            Row([
                Text("Фильтрация инспекций:", size=16, weight=FontWeight.BOLD, color=colors["text"]),
                Container(width=10),
                make_button("Применить", Icons.FILTER_ALT_OUTLINED, 150, apply_reports_filters),
                make_button("Сбросить", Icons.FILTER_ALT_OFF_OUTLINED, 140, reset_reports_filters),
            ], vertical_alignment=CrossAxisAlignment.CENTER),
            Row([
                filter_wafer_type,
                filter_size_x,
                filter_size_y,
                filter_date_from,
                filter_date_to,
                filter_inspector,
            ], wrap=True, spacing=10),
        ], spacing=10)
    )

    btn_choose_dir = make_button("Выбрать каталог", Icons.FOLDER_OPEN, 200, choose_directory)
    if not is_admin_access():
        btn_choose_dir.tooltip = "Выбор каталога доступен только Администратору (или при делегировании прав)"

    inspections_page = Container(content=Column([
        Row([
            Text("Журнал инспекций", size=24, weight=FontWeight.BOLD, color=colors["text"], expand=True),
            btn_choose_dir,
            make_button("Обновить", Icons.REFRESH, 140, refresh),
            make_button("Убрать из списка", Icons.DELETE_OUTLINE, 200, remove_selected, True),
        ]),
        Row([Icon(Icons.FOLDER_OUTLINED, color=colors["active"]), folder]),
        filter_panel,
        Divider(color=colors["inactive"]),
        Row([
            Container(content=Column([Text("Список отчетов", size=20, weight=FontWeight.BOLD, color=colors["text"]), report_list], expand=True), width=580),
            VerticalDivider(color=colors["inactive"]),
            Container(content=details, expand=True),
        ], expand=True),
    ], expand=True), padding=10, bgcolor=colors["background"], expand=True)

    analytics_page = Container(content=analytics_view, padding=10, bgcolor=colors["background"], expand=True)

    dies_page = Container(content=Column([
        Row([Text("Кристаллы выбранной инспекции", size=22, weight=FontWeight.BOLD, color=colors["text"], expand=True), search]),
        search_status,
        Text("Поиск: введите ID кристалла или диапазон (например 1-100) и нажмите Enter.", color=colors["unclickable"]),
        dies_view,
    ], expand=True), padding=10, bgcolor=colors["background"], expand=True)

    charts_page = Container(content=charts, padding=10, bgcolor=colors["background"], expand=True)

    return Tab(text="Статистика", content=Tabs(
        tabs=[
            Tab(text="Инспекции и фильтры", content=inspections_page),
            Tab(text="Сводный отчет", content=analytics_page),
            Tab(text="Кристаллы и метаданные", content=dies_page),
            Tab(text="Сравнительные графики", content=charts_page),
        ],
        selected_index=0,
        animation_duration=300,
        expand=True,
        label_color=colors["active"],
        unselected_label_color=colors["text"],
        indicator_color=colors["active"],
        divider_color=colors["top_bar"],
    ))