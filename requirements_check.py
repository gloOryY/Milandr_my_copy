import sys
import subprocess
import time

from project.application.addition.logger import logger


def is_cuda_available():
    """Проверяет, установлен ли драйвер NVIDIA и работает ли CUDA."""
    try:
        # Простая проверка через nvidia-smi (если есть)
        subprocess.run(['nvidia-smi'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def install_requirements():
    try:
        if is_cuda_available():
            logger.info("Обнаружена видеокарта NVIDIA. Устанавливаем PyTorch с поддержкой CUDA...")
            # Установка PyTorch с CUDA 12.4 (подходит для драйверов 525+)
            subprocess.check_call([
                sys.executable, '-m', 'pip', 'install',
                'torch', 'torchvision', 'torchaudio',
                '--index-url', 'https://download.pytorch.org/whl/cu124'
            ])
            # Устанавливаем остальные зависимости, исключая torch (уже есть)
            subprocess.check_call([
                sys.executable, '-m', 'pip', 'install',
                '-r', 'requirements.txt',
                '--ignore-installed', 'torch'  # не трогаем только что установленный torch
            ])
        else:
            logger.info("GPU не найден. Устанавливаем стандартный PyTorch (CPU).")
            # Обычная установка из requirements.txt (там torch без CUDA)
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])

        print("Все пакеты успешно установлены! Перезапустите приложение.")
        time.sleep(5)
        exit()
    except subprocess.CalledProcessError:
        print("Ошибка при установке пакетов.")
        time.sleep(5)
        exit(1)
