"""
Модуль автообнаружения эмуляторов LDPlayer.
Сканирует систему, находит ldconsole.exe, получает список эмуляторов и сохраняет конфигурацию.
"""
import os
import re
import subprocess
import winreg
from datetime import datetime
from pathlib import Path
import yaml
from loguru import logger


class EmulatorDiscovery:
    """Класс для автообнаружения и управления эмуляторами LDPlayer"""

    def __init__(self, config_path="configs/emulator_profiles.yaml"):
        """
        Инициализация системы обнаружения эмуляторов

        Args:
            config_path (str): Путь к файлу конфигурации эмуляторов
        """
        self.config_path = Path(config_path)
        self.ldplayer_path = None
        self.emulators = []
        self.last_scan = None

        # Создаём папку configs если её нет
        self.config_path.parent.mkdir(exist_ok=True)

        logger.info("EmulatorDiscovery инициализирован")

    def find_ldplayer_path(self):
        """
        Поиск пути к ldconsole.exe в стандартных местах

        Returns:
            str: Путь к ldconsole.exe или None если не найден
        """
        logger.info("Поиск LDPlayer в системе...")

        # Стандартные пути установки LDPlayer
        common_paths = [
            r"C:\LDPlayer\LDPlayer9\ldconsole.exe",
            r"C:\LDPlayer\LDPlayer4.0\ldconsole.exe",
            r"C:\Program Files\LDPlayer\LDPlayer9\ldconsole.exe",
            r"C:\Program Files (x86)\LDPlayer\LDPlayer9\ldconsole.exe",
            r"D:\LDPlayer\LDPlayer9\ldconsole.exe",
            r"E:\LDPlayer\LDPlayer9\ldconsole.exe",
        ]

        # Проверяем стандартные пути
        for path in common_paths:
            if os.path.exists(path):
                logger.info(f"✓ LDPlayer найден: {path}")
                self.ldplayer_path = path
                return path

        # Поиск через реестр Windows
        logger.info("Поиск LDPlayer через реестр Windows...")
        registry_path = self._find_ldplayer_in_registry()
        if registry_path:
            logger.info(f"✓ LDPlayer найден в реестре: {registry_path}")
            self.ldplayer_path = registry_path
            return registry_path

        # Поиск по всему диску C: (медленно, но надёжно)
        logger.info("Поиск ldconsole.exe по всему диску C:...")
        disk_search_path = self._search_ldconsole_on_disk()
        if disk_search_path:
            logger.info(f"✓ LDPlayer найден на диске: {disk_search_path}")
            self.ldplayer_path = disk_search_path
            return disk_search_path

        logger.error("✗ LDPlayer не найден в системе")
        return None

    def _find_ldplayer_in_registry(self):
        """Поиск LDPlayer через реестр Windows"""
        try:
            # Проверяем различные ветки реестра
            registry_keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\LDPlayer"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\LDPlayer"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\LDPlayer"),
            ]

            for hkey, subkey in registry_keys:
                try:
                    with winreg.OpenKey(hkey, subkey) as key:
                        install_path, _ = winreg.QueryValueEx(key, "InstallDir")
                        ldconsole_path = os.path.join(install_path, "ldconsole.exe")

                        if os.path.exists(ldconsole_path):
                            return ldconsole_path

                except (FileNotFoundError, OSError):
                    continue

        except Exception as e:
            logger.debug(f"Ошибка поиска в реестре: {e}")

        return None

    def _search_ldconsole_on_disk(self):
        """Поиск ldconsole.exe по диску C: (последний резерв)"""
        try:
            # Ищем только в типичных папках программ
            search_dirs = [
                r"C:\Program Files",
                r"C:\Program Files (x86)",
                r"C:\LDPlayer",
                r"C:\Games",
            ]

            for search_dir in search_dirs:
                if not os.path.exists(search_dir):
                    continue

                logger.debug(f"Поиск в {search_dir}...")

                for root, dirs, files in os.walk(search_dir):
                    if "ldconsole.exe" in files:
                        ldconsole_path = os.path.join(root, "ldconsole.exe")
                        # Проверяем, что это действительно LDPlayer
                        if "ldplayer" in root.lower():
                            return ldconsole_path

                    # Ограничиваем глубину поиска для скорости
                    if len(root.split(os.sep)) > 5:
                        dirs.clear()

        except Exception as e:
            logger.debug(f"Ошибка поиска на диске: {e}")

        return None

    def scan_emulators(self):
        """
        Сканирование эмуляторов через ldconsole list2

        Returns:
            list: Список найденных эмуляторов
        """
        if not self.ldplayer_path:
            logger.error("Путь к ldconsole.exe не найден. Запустите find_ldplayer_path() сначала")
            return []

        logger.info("Сканирование эмуляторов...")

        try:
            # Выполняем команду ldconsole list2
            result = subprocess.run(
                [self.ldplayer_path, "list2"],
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8'
            )

            if result.returncode != 0:
                logger.error(f"Ошибка выполнения ldconsole list2: {result.stderr}")
                return []

            # Парсим вывод команды
            emulators = self._parse_ldconsole_output(result.stdout)

            # Получаем ADB порты отдельно
            adb_ports = self._get_adb_ports()

            # Сопоставляем эмуляторы с ADB портами
            emulators = self._match_emulators_with_ports(emulators, adb_ports)

            self.emulators = emulators
            self.last_scan = datetime.now()

            logger.info(f"✓ Найдено эмуляторов: {len(emulators)}")

            for emu in emulators:
                port_info = f"ADB: {emu['adb_port']}" if emu['adb_port'] else "ADB: не определён"
                logger.info(f"  - {emu['name']} (индекс: {emu['index']}, {port_info})")

            return emulators

        except subprocess.TimeoutExpired:
            logger.error("Таймаут выполнения ldconsole list2")
            return []
        except Exception as e:
            logger.error(f"Ошибка сканирования эмуляторов: {e}")
            return []

    def _parse_ldconsole_output(self, output):
        """
        Парсинг вывода команды ldconsole list2

        Args:
            output (str): Вывод команды ldconsole list2

        Returns:
            list: Список словарей с данными эмуляторов
        """
        emulators = []

        try:
            lines = output.strip().split('\n')

            for line in lines:
                if not line.strip():
                    continue

                # Реальный формат ldconsole list2 в LDPlayer 9:
                # index,name,handle1,handle2,is_running,pid1,pid2,width,height,dpi
                # 0,0) astralshop@gmail,0,0,0,-1,-1,540,960,240

                parts = line.split(',')

                if len(parts) >= 5:
                    try:
                        index = int(parts[0])
                        name = parts[1].strip()
                        is_running = parts[4] == '1'

                        emulator = {
                            'name': name,
                            'index': index,
                            'adb_port': None,  # Будем получать отдельно
                            'is_running': is_running,
                            'enabled': True,  # По умолчанию включен
                            'profile': 'rushing',  # Профиль по умолчанию
                            'priority': index + 1,  # Приоритет по порядку
                        }

                        emulators.append(emulator)

                    except (ValueError, IndexError) as e:
                        logger.debug(f"Ошибка парсинга строки '{line}': {e}")
                        continue

        except Exception as e:
            logger.error(f"Ошибка парсинга вывода ldconsole: {e}")

        return emulators

    def _get_adb_ports(self):
        """
        Получение списка активных ADB портов

        Returns:
            list: Список активных ADB портов
        """
        try:
            # Выполняем adb devices
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                logger.warning(f"Ошибка выполнения adb devices: {result.stderr}")
                return []

            ports = []
            lines = result.stdout.strip().split('\n')[1:]  # Пропускаем заголовок "List of devices attached"

            for line in lines:
                if not line.strip():
                    continue

                parts = line.split()
                if len(parts) >= 2:
                    device = parts[0]
                    status = parts[1]

                    # Извлекаем порт из device ID
                    if 'emulator-' in device:
                        # Формат: emulator-5556
                        port = device.replace('emulator-', '')
                        if port.isdigit():
                            ports.append(int(port))
                    elif ':' in device:
                        # Формат: 127.0.0.1:5556
                        port = device.split(':')[1]
                        if port.isdigit():
                            ports.append(int(port))

            logger.info(f"Найдено активных ADB портов: {ports}")
            return sorted(ports)

        except Exception as e:
            logger.warning(f"Ошибка получения ADB портов: {e}")
            return []

    def _match_emulators_with_ports(self, emulators, adb_ports):
        """
        Сопоставление эмуляторов с ADB портами

        Args:
            emulators (list): Список эмуляторов из ldconsole
            adb_ports (list): Список активных ADB портов

        Returns:
            list: Эмуляторы с назначенными портами
        """
        try:
            # Стратегия 1: Стандартная формула LDPlayer (порт = 5554 + index * 2)
            for emu in emulators:
                standard_port = 5554 + (emu['index'] * 2)

                # Если стандартный порт активен, назначаем его
                if standard_port in adb_ports:
                    emu['adb_port'] = standard_port
                    logger.debug(f"Эмулятор '{emu['name']}' (индекс {emu['index']}) -> стандартный порт {standard_port}")

            # Стратегия 2: Для оставшихся эмуляторов назначаем порты по порядку
            used_ports = {emu['adb_port'] for emu in emulators if emu['adb_port']}
            available_ports = [port for port in adb_ports if port not in used_ports]

            running_emulators_without_ports = [
                emu for emu in emulators
                if emu['is_running'] and emu['adb_port'] is None
            ]

            for i, emu in enumerate(running_emulators_without_ports):
                if i < len(available_ports):
                    emu['adb_port'] = available_ports[i]
                    logger.debug(f"Эмулятор '{emu['name']}' (запущен) -> свободный порт {available_ports[i]}")

            # Стратегия 3: Для неактивных эмуляторов оставляем порт как None
            # но можем предположить стандартный порт для будущего использования
            for emu in emulators:
                if not emu['is_running'] and emu['adb_port'] is None:
                    potential_port = 5554 + (emu['index'] * 2)
                    # Не назначаем порт, но логируем потенциальный
                    logger.debug(f"Эмулятор '{emu['name']}' (остановлен) -> потенциальный порт {potential_port}")

            return emulators

        except Exception as e:
            logger.error(f"Ошибка сопоставления эмуляторов с портами: {e}")
            return emulators

    def load_config(self):
        """
        Загрузка существующей конфигурации эмуляторов

        Returns:
            dict: Конфигурация или пустой словарь
        """
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}

                logger.info(f"Конфигурация загружена из {self.config_path}")

                # Восстанавливаем путь к LDPlayer из конфига
                if 'ldplayer' in config and 'path' in config['ldplayer']:
                    self.ldplayer_path = config['ldplayer']['path']

                return config
            else:
                logger.info("Файл конфигурации не найден, создаём новый")
                return {}

        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
            return {}

    def save_config(self):
        """
        Сохранение текущей конфигурации в YAML файл

        Returns:
            bool: True если сохранение успешно
        """
        try:
            config = self.load_config()  # Загружаем существующий конфиг

            # Обновляем секцию ldplayer
            config['ldplayer'] = {
                'path': self.ldplayer_path,
                'last_scan': self.last_scan.isoformat() if self.last_scan else None,
                'auto_scan_interval': 3600  # 1 час
            }

            # Обновляем секцию emulators
            # Сохраняем настройки пользователя (enabled, profile) если они есть
            existing_emulators = {emu['name']: emu for emu in config.get('emulators', [])}

            updated_emulators = []
            for emu in self.emulators:
                # Если эмулятор уже был в конфиге, сохраняем пользовательские настройки
                if emu['name'] in existing_emulators:
                    existing = existing_emulators[emu['name']]
                    emu['enabled'] = existing.get('enabled', True)
                    emu['profile'] = existing.get('profile', 'rushing')
                    emu['priority'] = existing.get('priority', emu['priority'])

                # Убираем None значения для чистоты конфига
                clean_emu = {}
                for key, value in emu.items():
                    if value is not None:
                        clean_emu[key] = value

                updated_emulators.append(clean_emu)

            config['emulators'] = updated_emulators

            # Добавляем правила автоназначения профилей если их нет
            if 'auto_profiles' not in config:
                config['auto_profiles'] = {
                    'patterns': [
                        {'pattern': 'сервер 333-*', 'profile': 'rushing'},
                        {'pattern': 'сервер 444-*', 'profile': 'farming'},
                    ],
                    'default_profile': 'rushing',
                    'new_emulators_enabled': False
                }

            # Сохраняем в файл
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, indent=2)

            logger.info(f"✓ Конфигурация сохранена в {self.config_path}")
            logger.info(f"  - LDPlayer: {self.ldplayer_path}")
            logger.info(f"  - Эмуляторов: {len(self.emulators)}")
            logger.info(f"  - Время сканирования: {self.last_scan}")

            return True

        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации: {e}")
            return False

    def discover_and_save(self):
        """
        Полный цикл: поиск LDPlayer → сканирование эмуляторов → сохранение конфига

        Returns:
            dict: Результат операции
        """
        logger.info("=== Автообнаружение эмуляторов ===")

        result = {
            'success': False,
            'ldplayer_found': False,
            'emulators_found': 0,
            'config_saved': False,
            'message': ''
        }

        try:
            # 1. Поиск LDPlayer
            logger.info("1. Поиск LDPlayer...")
            ldplayer_path = self.find_ldplayer_path()

            if not ldplayer_path:
                result['message'] = "LDPlayer не найден в системе"
                return result

            result['ldplayer_found'] = True

            # 2. Сканирование эмуляторов
            logger.info("2. Сканирование эмуляторов...")
            emulators = self.scan_emulators()

            result['emulators_found'] = len(emulators)

            if not emulators:
                result['message'] = "Эмуляторы не найдены"
                return result

            # 3. Сохранение конфигурации
            logger.info("3. Сохранение конфигурации...")
            config_saved = self.save_config()

            result['config_saved'] = config_saved

            if config_saved:
                result['success'] = True
                result['message'] = f"Успешно: найден LDPlayer, {len(emulators)} эмуляторов, конфиг сохранён"
            else:
                result['message'] = "Ошибка сохранения конфигурации"

            return result

        except Exception as e:
            logger.error(f"Ошибка автообнаружения: {e}")
            result['message'] = f"Ошибка: {str(e)}"
            return result

    def get_emulator_by_name(self, name):
        """
        Получить эмулятор по имени

        Args:
            name (str): Имя эмулятора

        Returns:
            dict: Данные эмулятора или None
        """
        for emu in self.emulators:
            if emu['name'] == name:
                return emu
        return None

    def get_running_emulators(self):
        """
        Получить список запущенных эмуляторов

        Returns:
            list: Список запущенных эмуляторов
        """
        return [emu for emu in self.emulators if emu.get('is_running', False)]

    def get_summary(self):
        """
        Получить сводку по эмуляторам

        Returns:
            dict: Сводная информация
        """
        if not self.emulators:
            return {
                'total': 0,
                'running': 0,
                'enabled': 0,
                'with_adb_ports': 0,
                'ldplayer_path': self.ldplayer_path,
                'last_scan': self.last_scan
            }

        total = len(self.emulators)
        running = len([emu for emu in self.emulators if emu.get('is_running', False)])
        enabled = len([emu for emu in self.emulators if emu.get('enabled', True)])
        with_ports = len([emu for emu in self.emulators if emu.get('adb_port') is not None])

        return {
            'total': total,
            'running': running,
            'enabled': enabled,
            'with_adb_ports': with_ports,
            'ldplayer_path': self.ldplayer_path,
            'last_scan': self.last_scan
        }


def test_emulator_discovery():
    """Тестовая функция для проверки EmulatorDiscovery"""
    logger.info("=== Тестирование EmulatorDiscovery ===")

    discovery = EmulatorDiscovery()

    # Полный цикл обнаружения
    result = discovery.discover_and_save()

    logger.info(f"Результат обнаружения: {result}")

    # Показываем сводку
    summary = discovery.get_summary()
    logger.info(f"Сводка по эмуляторам: {summary}")

    return result['success']


if __name__ == "__main__":
    test_emulator_discovery()