import sys
import subprocess
import os


def install_requirements():
    """Установка всех зависимостей"""
    try:
        print("📦 Установка зависимостей...")

        if not os.path.exists('requirements.txt'):
            print("❌ requirements.txt не найден")
            return False

        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install',
            '-r', 'requirements.txt'
        ])

        print("✅ Все зависимости установлены!")
        return True

    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка: {e}")
        print("Попробуйте установить вручную:")
        print("  pip install -r requirements.txt")
        return False