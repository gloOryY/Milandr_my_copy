import os
import json
import torch
from ultralytics import YOLO
from typing import List, Dict, Any, Optional

from project.application.addition.logger import logger
from project.configuration.worker import read_from_json

torch.backends.cudnn.benchmark = True


class ModelsVault:
    """
    Класс-хранилище для загрузки и управления моделями YOLO.

    Attributes:
        _defects (List[Dict]): Список моделей для поиска дефектов пассификации
    """

    _device = None  # Глобальное устройство для всех моделей (cpu / cuda:0)

    def __init__(self, path: str) -> None:
        """Инициализация хранилища моделей."""
        self._crosses: List[Dict[str, Any]] = []
        self._working_zone: List[Dict[str, Any]] = []
        self._defects: List[Dict[str, Any]] = []
        self._load_models(path)

    @staticmethod
    def get_device() -> str:
        """Возвращает устройство для инференса (cpu или cuda:0)."""
        if ModelsVault._device is None:
            if torch.cuda.is_available():
                ModelsVault._device = 'cuda:0'
                logger.info(f"GPU доступен: {torch.cuda.get_device_name(0)}")
            else:
                ModelsVault._device = 'cpu'
                logger.warning("GPU не найден, используется CPU")

        return ModelsVault._device

    @staticmethod
    def _upload_model(model_path: str) -> YOLO:
        """
        Загрузка PyTorch-модели YOLO из .pt файла с немедленным переносом на
        актуальное устройство (GPU/CPU). ONNX-файлы игнорируются для сохранения
        корректности сегментации и простоты.
        """
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"Модель не найдена по пути: {model_path}")

        device = ModelsVault.get_device()
        model = YOLO(model_path, task="segment")  # явно указываем задачу сегментации
        model.fuse()  # графическая оптимизация
        model.to(device)  # перенос на GPU/CPU
        logger.debug(f"Загружена PyTorch-модель: {model_path} на {device}")

        if hasattr(torch, 'compile') and device != 'cpu':
            model.model = torch.compile(model.model, mode="reduce-overhead")

        return model

    def _fill_list(self, cam_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Заполнение списка моделей на основе данных из словаря.

        Args:
            cam_dict: Словарь с данными о моделях (ключ – камера/тип)

        Returns:
            Список словарей с ключами 'model', 'color', 'name', 'conf'
        """
        model_list = []
        for key, items in sorted(cam_dict.items()):
            pat_h = items.get('path')
            color = items.get('color', [255, 0, 0])
            name = items.get('name', 'Unnamed')
            conf = items.get('conf', 0.5)
            if os.path.isfile(pat_h):
                model = self._upload_model(pat_h)
                model_list.append({
                    'model': model,
                    'color': color,
                    'name': name,
                    'conf': conf
                })
            else:
                print(f'Файл не найден - {items["path"]}')
        return model_list

    def _fill_defects_list(self, defects_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Заполнение списка моделей дефектов на основе списка из JSON.

        Args:
            defects_list: Список словарей с данными о дефектах

        Returns:
            Список словарей с ключами 'model', 'color', 'name', 'conf', 'version_id', ...
        """
        model_list = []
        for defect_item in defects_list:
            for defect_name, defect_data in defect_item.items():
                versions = defect_data.get('versions', [])
                color = defect_data.get('color', [255, 0, 0])
                name = defect_data.get('name', 'Unnamed')

                for version in versions:
                    pat_h = version.get('path')
                    conf = version.get('conf', 0.5)
                    id_version = version.get('id_version', 1)
                    description_version = version.get('description_version', '')

                    if os.path.isfile(pat_h):
                        model = self._upload_model(pat_h)  # общий метод загрузки
                        model_list.append({
                            'model': model,
                            'color': color,
                            'name': name,
                            'conf': conf,
                            'version_id': id_version,
                            'description_version': description_version,
                            'defect_type': defect_name
                        })
                    else:
                        print(f'Файл не найден - {pat_h}')
        return model_list

    def _load_models(self, path: str) -> None:
        """Загрузка моделей из JSON-файла."""
        read_from_json(path, "defects")

        with open(path, 'r', encoding='utf-8') as file:
            data = json.load(file)

        self._defects = self._fill_defects_list(data.get('defects', []))

    @property
    def defects(self) -> list[dict]:
        return self._defects.copy()


# Глобальные переменные
path_to_models: str = r'project/algorithms/neural_network/models/models.json'
models: Optional[Dict[str, List[Dict[str, Any]]]] = None


def networks_init() -> None:
    """Инициализация сетей моделей."""
    global models
    networks = ModelsVault(path_to_models)
    models = {
        'defects': networks.defects
    }


def get_defect_model_by_type(defect_type: str):
    """Найти модель по типу дефекта."""
    for defect in models['defects']:
        if defect['defect_type'] == defect_type:
            return defect
    return None
