"""
Модуль конфигураций для разных уровней и фаз игры.
"""
import os
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).parent


def load_config(filename):
    """Загрузка конфигурационного файла"""
    config_path = CONFIG_DIR / filename
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return None