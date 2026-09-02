from pathlib import Path
from typing import Optional
import numpy as np
import cv2 as cv

# Путь к папке с изображениями
IMAGE_FOLDER = Path("C:/Users/user/PycharmProjects/Milandr/Milandr/test_photos")
IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


# ---------------------- ФОКУС-МЕТРИКИ ----------------------
def make_mask(gray: np.ndarray, satur_upper_pct: float = 0.99, satur_lower_pct: float = 0.01,
              use_edges: bool = True, dilate_px: int = 1) -> np.ndarray:
    """Маска для исключения бликов/провалов и отбора информативных пикселей."""
    q_hi = np.quantile(gray, satur_upper_pct)
    q_lo = np.quantile(gray, satur_lower_pct)
    base = (gray > q_lo) & (gray < q_hi)
    if use_edges:
        blur = cv.GaussianBlur(gray, (0, 0), 1.0)
        th_val, th_img = cv.threshold(blur, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
        lo = max(10, int(0.5 * float(th_val)))
        hi = max(20, int(1.5 * float(th_val)))
        edges = cv.Canny(gray, lo, hi, L2gradient=True)
        if dilate_px > 0:
            k = cv.getStructuringElement(cv.MORPH_RECT, (2 * dilate_px + 1, 2 * dilate_px + 1))
            edges = cv.dilate(edges, k)
        edge_mask = edges > 0
        base &= edge_mask
    return base.astype(np.uint8)


def tenengrad_sharpness(img: np.ndarray, mask: Optional[np.ndarray] = None, ksize: int = 3) -> float:
    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gx = cv.Sobel(gray, cv.CV_32F, 1, 0, ksize=ksize)
    gy = cv.Sobel(gray, cv.CV_32F, 0, 1, ksize=ksize)
    mag2 = gx * gx + gy * gy
    if mask is not None:
        vals = mag2[mask > 0]
    else:
        vals = mag2.ravel()
    return float(np.mean(vals)) if vals.size else 0.0


def laplacian_var_sharpness(img: np.ndarray, mask: Optional[np.ndarray] = None, ksize: int = 3) -> float:
    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY) if img.ndim == 3 else img
    lap = cv.Laplacian(gray, cv.CV_32F, ksize=ksize)
    if mask is not None:
        vals = lap[mask > 0]
    else:
        vals = lap.ravel()
    return float(np.var(vals)) if vals.size else 0.0


def simple_laplacian_sharpness(img: np.ndarray) -> float:
    """Простой метод Лапласиана без маски (для сравнения)"""
    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv.Laplacian(gray, cv.CV_64F).var()


# ---------------------- ОСНОВНАЯ ФУНКЦИЯ ----------------------
def analyze_all_images():
    """Анализирует все изображения в папке методами фокус-метрик"""

    print("🔍 Начинаем анализ изображений...")
    print(f"📁 Папка: {IMAGE_FOLDER}")

    # Собираем все изображения
    image_files = []
    for ext in IMG_EXTS:
        image_files.extend(IMAGE_FOLDER.glob(f"*{ext}"))
        image_files.extend(IMAGE_FOLDER.glob(f"*{ext.upper()}"))

    if not image_files:
        print(f"❌ В папке {IMAGE_FOLDER} не найдено изображений")
        return

    print(f"📊 Найдено {len(image_files)} изображений:")
    for img_file in image_files:
        print(f"   - {img_file.name}")

    # Результаты
    results = []

    # Анализируем каждое изображение
    for img_path in image_files:
        print(f"\n🔍 Анализ: {img_path.name}")

        try:
            # Загружаем изображение
            img = cv.imread(str(img_path))
            if img is None:
                print(f"   ❌ Не удалось загрузить изображение")
                continue

            # Вычисляем все метрики
            gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
            mask = make_mask(gray, use_edges=True, dilate_px=1)

            # Tenengrad с маской (чем больше, тем лучше)
            tenengrad_score = tenengrad_sharpness(img, mask)

            # Laplacian Variance с маской (чем больше, тем лучше)
            laplacian_var_score = laplacian_var_sharpness(img, mask)

            # Простой Laplacian без маски (для сравнения)
            simple_laplacian_score = simple_laplacian_sharpness(img)

            # Сохраняем результаты
            result = {
                'filename': img_path.name,
                'tenengrad_masked': round(tenengrad_score, 1),
                'laplacian_var_masked': round(laplacian_var_score, 1),
                'simple_laplacian': round(simple_laplacian_score, 1),
            }

            results.append(result)

            # Выводим результаты в консоль
            print(f"   ✅ Tenengrad: {tenengrad_score:.1f} (выше → лучше)")
            print(f"   ✅ Laplacian Var: {laplacian_var_score:.1f} (выше → лучше)")
            print(f"   ✅ Simple Laplacian: {simple_laplacian_score:.1f}")

        except Exception as e:
            print(f"   ❌ Ошибка анализа {img_path.name}: {e}")
            continue

    # Сохраняем результаты в CSV
    if results:
        try:

            # Сводная статистика по каждому методу
            print(f"\n📈 СВОДНАЯ СТАТИСТИКА:")
            print(f"   Всего проанализировано: {len(results)} изображений")

            # Топ по Tenengrad
            print(f"\n🏆 ТОП по Tenengrad (с маской):")
            sorted_tenengrad = sorted(results, key=lambda x: x['tenengrad_masked'], reverse=True)
            for i, result in enumerate(sorted_tenengrad[:5], 1):
                print(f"   {i}. {result['filename']} - {result['tenengrad_masked']}")

            # Топ по Laplacian Variance
            print(f"\n🏆 ТОП по Laplacian Variance (с маской):")
            sorted_laplacian = sorted(results, key=lambda x: x['laplacian_var_masked'], reverse=True)
            for i, result in enumerate(sorted_laplacian[:5], 1):
                print(f"   {i}. {result['filename']} - {result['laplacian_var_masked']}")

            # Топ по Simple Laplacian
            print(f"\n🏆 ТОП по Simple Laplacian (без маски):")
            sorted_simple = sorted(results, key=lambda x: x['simple_laplacian'], reverse=True)
            for i, result in enumerate(sorted_simple[:5], 1):
                print(f"   {i}. {result['filename']} - {result['simple_laplacian']}")

        except Exception as e:
            print(f"❌ Ошибка сохранения CSV: {e}")
    else:
        print("❌ Не удалось проанализировать ни одного изображения")


def print_methods_info():
    """Выводит информацию о методах оценки"""
    print("🎯 ИСПОЛЬЗУЕМЫЕ МЕТОДЫ ОЦЕНКИ РЕЗКОСТИ:")

    print("\n   1. Tenengrad с маской (фокус-метрика)")
    print("      - Основан на градиентах Собеля")
    print("      - Использует маску для исключения бликов и фона")
    print("      - Чем БОЛЬШЕ значение, тем РЕЗЧЕ изображение")

    print("\n   2. Laplacian Variance с маской (фокус-метрика)")
    print("      - Основан на дисперсии Лапласиана")
    print("      - Использует маску для исключения бликов и фона")
    print("      - Чем БОЛЬШЕ значение, тем РЕЗЧЕ изображение")

    print("\n   3. Simple Laplacian (базовый метод)")
    print("      - Простая дисперсия Лапласиана без маски")
    print("      - Чем БОЛЬШЕ значение, тем РЕЗЧЕ изображение")
    print("      - Может быть чувствителен к бликам и шуму")


if __name__ == "__main__":
    print("=" * 60)
    print("🖼️  АНАЛИЗ РЕЗКОСТИ ИЗОБРАЖЕНИЙ")
    print("=" * 60)

    print_methods_info()
    print("\n" + "=" * 60)

    analyze_all_images()

    print("\n" + "=" * 60)
    print("✅ Анализ завершен!")
    print("=" * 60)