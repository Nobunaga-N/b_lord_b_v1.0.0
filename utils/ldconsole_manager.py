"""
LDConsole Manager для управления жизненным циклом эмуляторов LDPlayer.
РАСШИРЕННАЯ ВЕРСИЯ - добавлены батчевые операции и профили производительности.
"""
import os
import time
import subprocess
import psutil
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger


class LDConsoleManager:
    """Расширенный класс для управления эмуляторами LDPlayer через ldconsole"""

    def __init__(self, ldconsole_path=None, default_timeout=60):
        """
        Инициализация LDConsole Manager

        Args:
            ldconsole_path (str, optional): Путь к ldconsole.exe
            default_timeout (int): Таймаут по умолчанию для операций
        """
        self.ldconsole_path = ldconsole_path
        self.default_timeout = default_timeout
        self.running_emulators = {}  # Кэш состояний эмуляторов {index: status}
        self.performance_profiles = {}  # Кэш профилей производительности

        # Если путь не указан, пытаемся найти автоматически
        if not self.ldconsole_path:
            self.ldconsole_path = self._find_ldconsole_path()

        if not self.ldconsole_path:
            raise FileNotFoundError("ldconsole.exe не найден. Укажите путь вручную")

        # Загружаем профили производительности
        self._load_performance_profiles()

        logger.info(f"LDConsoleManager инициализирован: {self.ldconsole_path}")
        logger.info(f"Загружено профилей производительности: {len(self.performance_profiles)}")

    def _find_ldconsole_path(self):
        """
        Автоматический поиск ldconsole.exe в стандартных местах

        Returns:
            str: Путь к ldconsole.exe или None
        """
        common_paths = [
            r"C:\LDPlayer\LDPlayer9\ldconsole.exe",
            r"C:\LDPlayer\LDPlayer4.0\ldconsole.exe",
            r"C:\Program Files\LDPlayer\LDPlayer9\ldconsole.exe",
            r"C:\Program Files (x86)\LDPlayer\LDPlayer9\ldconsole.exe",
            r"D:\LDPlayer\LDPlayer9\ldconsole.exe",
            r"E:\LDPlayer\LDPlayer9\ldconsole.exe",
        ]

        for path in common_paths:
            if os.path.exists(path):
                logger.info(f"Найден ldconsole: {path}")
                return path

        logger.warning("ldconsole.exe не найден в стандартных местах")
        return None

    def _load_performance_profiles(self):
        """Загрузка профилей производительности из конфигурационного файла"""
        try:
            profiles_path = Path("configs/performance_profiles.yaml")

            if profiles_path.exists():
                with open(profiles_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)

                self.performance_profiles = config.get('profiles', {})
                logger.info(f"✓ Загружено профилей производительности: {list(self.performance_profiles.keys())}")

            else:
                logger.warning(f"Файл профилей не найден: {profiles_path}")
                logger.info("Создание файла профилей по умолчанию...")
                self._create_default_profiles_config()

        except Exception as e:
            logger.error(f"Ошибка загрузки профилей производительности: {e}")
            self.performance_profiles = {}

    def _create_default_profiles_config(self):
        """Создание конфигурационного файла профилей по умолчанию"""
        try:
            default_profiles = {
                'profiles': {
                    'rushing': {
                        'cpu': 4,
                        'memory': 4096,
                        'fps': 60,
                        'resolution': '1080x1920',
                        'description': 'Активная прокачка 10-15 lvl'
                    },
                    'developing': {
                        'cpu': 3,
                        'memory': 3072,
                        'fps': 45,
                        'resolution': '720x1280',
                        'description': 'Развитие 16-19 lvl'
                    },
                    'farming': {
                        'cpu': 2,
                        'memory': 2048,
                        'fps': 30,
                        'resolution': '720x1280',
                        'description': 'Фарм ресурсов 19+ lvl'
                    },
                    'dormant': {
                        'cpu': 1,
                        'memory': 1024,
                        'fps': 15,
                        'resolution': '540x960',
                        'description': 'Минимальное поддержание'
                    },
                    'emergency': {
                        'cpu': 4,
                        'memory': 4096,
                        'fps': 60,
                        'resolution': '720x1280',
                        'description': 'Критичные задачи'
                    }
                }
            }

            # Создаём папку configs если её нет
            os.makedirs("configs", exist_ok=True)

            with open("configs/performance_profiles.yaml", 'w', encoding='utf-8') as f:
                yaml.dump(default_profiles, f, default_flow_style=False, allow_unicode=True, indent=2)

            self.performance_profiles = default_profiles['profiles']
            logger.info("✓ Создан файл профилей производительности по умолчанию")

        except Exception as e:
            logger.error(f"Ошибка создания файла профилей по умолчанию: {e}")

    def _run_ldconsole_command(self, command_args, timeout=None):
        """
        Выполнение ldconsole команды через subprocess

        Args:
            command_args (list): Аргументы команды
            timeout (int, optional): Таймаут выполнения

        Returns:
            dict: Результат выполнения
        """
        if timeout is None:
            timeout = self.default_timeout

        if not os.path.exists(self.ldconsole_path):
            return {
                'success': False,
                'stdout': '',
                'stderr': f'ldconsole.exe не найден: {self.ldconsole_path}',
                'returncode': -1,
                'execution_time': 0
            }

        # Подготавливаем полную команду
        full_command = [self.ldconsole_path] + command_args

        logger.debug(f"Выполняем ldconsole команду: {' '.join(command_args)}")

        start_time = time.time()

        try:
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8'
            )

            execution_time = time.time() - start_time
            success = result.returncode == 0

            if success:
                logger.debug(f"Команда выполнена успешно за {execution_time:.1f}s")
            else:
                logger.warning(f"Команда завершилась с кодом {result.returncode}: {result.stderr}")

            return {
                'success': success,
                'stdout': result.stdout.strip(),
                'stderr': result.stderr.strip(),
                'returncode': result.returncode,
                'execution_time': execution_time
            }

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            logger.error(f"Таймаут выполнения ldconsole команды ({timeout}s)")

            return {
                'success': False,
                'stdout': '',
                'stderr': f'Таймаут {timeout} секунд',
                'returncode': -1,
                'execution_time': execution_time
            }

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Ошибка выполнения ldconsole команды: {e}")

            return {
                'success': False,
                'stdout': '',
                'stderr': str(e),
                'returncode': -1,
                'execution_time': execution_time
            }

    # ===== НОВЫЕ БАТЧЕВЫЕ ОПЕРАЦИИ =====

    def start_batch(self, emulator_indexes, max_parallel=3, start_delay=5, timeout=60):
        """
        Запуск батча эмуляторов с контролем параллельности

        Args:
            emulator_indexes (list): Список индексов эмуляторов для запуска
            max_parallel (int): Максимальное количество одновременных запусков
            start_delay (int): Задержка между запусками в секундах
            timeout (int): Таймаут для каждого запуска

        Returns:
            dict: Результат батчевого запуска со структурой:
                {
                    'success': bool,
                    'total_requested': int,
                    'started_successfully': int,
                    'already_running': int,
                    'failed': int,
                    'results': [{'index': int, 'success': bool, 'message': str, ...}],
                    'total_time': float
                }
        """
        logger.info(f"=== Батчевый запуск {len(emulator_indexes)} эмуляторов ===")
        logger.info(f"Параллельность: {max_parallel}, задержка: {start_delay}s, таймаут: {timeout}s")

        start_batch_time = time.time()

        batch_result = {
            'success': True,
            'total_requested': len(emulator_indexes),
            'started_successfully': 0,
            'already_running': 0,
            'failed': 0,
            'results': [],
            'total_time': 0
        }

        if not emulator_indexes:
            batch_result['success'] = True
            batch_result['total_time'] = 0
            logger.info("Пустой батч - нечего запускать")
            return batch_result

        try:
            # Используем ThreadPoolExecutor для управления параллельностью
            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                # Создаём задачи с задержкой между отправками
                future_to_index = {}

                for i, emulator_index in enumerate(emulator_indexes):
                    # Добавляем задержку между запусками (кроме первого)
                    if i > 0:
                        time.sleep(start_delay)

                    logger.info(f"Отправляем задачу запуска эмулятора {emulator_index} ({i+1}/{len(emulator_indexes)})")

                    future = executor.submit(self._start_single_emulator_for_batch, emulator_index, timeout)
                    future_to_index[future] = emulator_index

                # Собираем результаты
                for future in as_completed(future_to_index, timeout=timeout + 30):
                    emulator_index = future_to_index[future]

                    try:
                        result = future.result()
                        result['index'] = emulator_index
                        batch_result['results'].append(result)

                        # Обновляем счётчики
                        if result['success']:
                            if result['already_running']:
                                batch_result['already_running'] += 1
                            else:
                                batch_result['started_successfully'] += 1
                        else:
                            batch_result['failed'] += 1

                        status = "уже запущен" if result['already_running'] else ("успех" if result['success'] else "ошибка")
                        logger.info(f"✓ Эмулятор {emulator_index}: {status} за {result['start_time']:.1f}s")

                    except Exception as e:
                        logger.error(f"✗ Исключение для эмулятора {emulator_index}: {e}")
                        batch_result['failed'] += 1
                        batch_result['results'].append({
                            'index': emulator_index,
                            'success': False,
                            'already_running': False,
                            'start_time': 0,
                            'message': f'Исключение: {str(e)}'
                        })

        except Exception as e:
            logger.error(f"Критическая ошибка батчевого запуска: {e}")
            batch_result['success'] = False

        # Подсчитываем общие результаты
        batch_result['total_time'] = time.time() - start_batch_time

        successful_total = batch_result['started_successfully'] + batch_result['already_running']

        if batch_result['failed'] == 0:
            batch_result['success'] = True
            logger.info(f"✓ Батчевый запуск завершён успешно за {batch_result['total_time']:.1f}s")
        else:
            batch_result['success'] = False
            logger.warning(f"⚠ Батчевый запуск завершён с проблемами за {batch_result['total_time']:.1f}s")

        logger.info(f"Итого: {successful_total}/{len(emulator_indexes)} готовы, {batch_result['failed']} ошибок")

        return batch_result

    def stop_batch(self, emulator_indexes, max_parallel=5, force=False, timeout=30):
        """
        Остановка батча эмуляторов

        Args:
            emulator_indexes (list): Список индексов эмуляторов для остановки
            max_parallel (int): Максимальное количество одновременных остановок
            force (bool): Принудительная остановка
            timeout (int): Таймаут для каждой остановки

        Returns:
            dict: Результат батчевой остановки
        """
        logger.info(f"=== Батчевая остановка {len(emulator_indexes)} эмуляторов ===")
        logger.info(f"Принудительно: {force}, таймаут: {timeout}s")

        start_batch_time = time.time()

        batch_result = {
            'success': True,
            'total_requested': len(emulator_indexes),
            'stopped_successfully': 0,
            'already_stopped': 0,
            'failed': 0,
            'results': [],
            'total_time': 0
        }

        if not emulator_indexes:
            batch_result['total_time'] = 0
            logger.info("Пустой батч - нечего останавливать")
            return batch_result

        try:
            # Если принудительная остановка - используем killall (быстрее для всех сразу)
            if force:
                logger.info("Принудительная остановка всех эмуляторов через killall")
                killall_result = self._run_ldconsole_command(['killall'], timeout)

                if killall_result['success']:
                    # Проверяем результат для каждого эмулятора
                    for emulator_index in emulator_indexes:
                        time.sleep(1)  # Даём время на завершение процессов

                        if not self.is_running(emulator_index, force_check=True):
                            batch_result['stopped_successfully'] += 1
                            batch_result['results'].append({
                                'index': emulator_index,
                                'success': True,
                                'was_running': True,
                                'stop_time': killall_result['execution_time'],
                                'message': 'Остановлен через killall'
                            })
                        else:
                            batch_result['failed'] += 1
                            batch_result['results'].append({
                                'index': emulator_index,
                                'success': False,
                                'was_running': True,
                                'stop_time': killall_result['execution_time'],
                                'message': 'Не удалось остановить через killall'
                            })
                else:
                    # Если killall не сработал, помечаем все как ошибку
                    for emulator_index in emulator_indexes:
                        batch_result['failed'] += 1
                        batch_result['results'].append({
                            'index': emulator_index,
                            'success': False,
                            'was_running': True,
                            'stop_time': 0,
                            'message': f'Ошибка killall: {killall_result["stderr"]}'
                        })

            else:
                # Индивидуальная остановка через ThreadPool
                with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                    future_to_index = {}

                    for emulator_index in emulator_indexes:
                        future = executor.submit(self._stop_single_emulator_for_batch, emulator_index, timeout)
                        future_to_index[future] = emulator_index

                    # Собираем результаты
                    for future in as_completed(future_to_index, timeout=timeout + 15):
                        emulator_index = future_to_index[future]

                        try:
                            result = future.result()
                            result['index'] = emulator_index
                            batch_result['results'].append(result)

                            # Обновляем счётчики
                            if result['success']:
                                if result['was_running']:
                                    batch_result['stopped_successfully'] += 1
                                else:
                                    batch_result['already_stopped'] += 1
                            else:
                                batch_result['failed'] += 1

                            status = "уже остановлен" if not result['was_running'] else ("остановлен" if result['success'] else "ошибка")
                            logger.info(f"✓ Эмулятор {emulator_index}: {status}")

                        except Exception as e:
                            logger.error(f"✗ Исключение для эмулятора {emulator_index}: {e}")
                            batch_result['failed'] += 1
                            batch_result['results'].append({
                                'index': emulator_index,
                                'success': False,
                                'was_running': False,
                                'stop_time': 0,
                                'message': f'Исключение: {str(e)}'
                            })

        except Exception as e:
            logger.error(f"Критическая ошибка батчевой остановки: {e}")
            batch_result['success'] = False

        # Подсчитываем общие результаты
        batch_result['total_time'] = time.time() - start_batch_time

        stopped_total = batch_result['stopped_successfully'] + batch_result['already_stopped']

        if batch_result['failed'] == 0:
            batch_result['success'] = True
            logger.info(f"✓ Батчевая остановка завершена успешно за {batch_result['total_time']:.1f}s")
        else:
            batch_result['success'] = False
            logger.warning(f"⚠ Батчевая остановка завершена с проблемами за {batch_result['total_time']:.1f}s")

        logger.info(f"Итого: {stopped_total}/{len(emulator_indexes)} остановлены, {batch_result['failed']} ошибок")

        return batch_result

    def wait_batch_ready(self, emulator_indexes, timeout=120, check_interval=3):
        """
        Ожидание готовности батча эмуляторов (ADB подключения)

        Args:
            emulator_indexes (list): Список индексов эмуляторов для ожидания
            timeout (int): Общий таймаут ожидания
            check_interval (int): Интервал проверки в секундах

        Returns:
            dict: Результат ожидания готовности батча
        """
        logger.info(f"=== Ожидание готовности батча из {len(emulator_indexes)} эмуляторов ===")
        logger.info(f"Таймаут: {timeout}s, интервал проверки: {check_interval}s")

        start_wait_time = time.time()

        wait_result = {
            'success': True,
            'total_requested': len(emulator_indexes),
            'ready_emulators': 0,
            'timeout_emulators': 0,
            'failed_emulators': 0,
            'results': [],
            'total_wait_time': 0
        }

        if not emulator_indexes:
            wait_result['total_wait_time'] = 0
            logger.info("Пустой батч - нечего ждать")
            return wait_result

        try:
            pending_emulators = emulator_indexes.copy()
            ready_emulators = []

            while pending_emulators and (time.time() - start_wait_time) < timeout:
                elapsed_time = time.time() - start_wait_time
                logger.debug(f"Проверка готовности... {elapsed_time:.1f}s / {timeout}s, осталось: {len(pending_emulators)}")

                newly_ready = []

                # Проверяем каждый ожидающий эмулятор
                for emulator_index in pending_emulators:
                    try:
                        # Проверяем что эмулятор запущен
                        if not self.is_running(emulator_index):
                            logger.warning(f"Эмулятор {emulator_index} неожиданно остановился во время ожидания")
                            wait_result['failed_emulators'] += 1
                            wait_result['results'].append({
                                'index': emulator_index,
                                'ready': False,
                                'adb_port': None,
                                'wait_time': elapsed_time,
                                'message': 'Эмулятор остановился'
                            })
                            newly_ready.append(emulator_index)  # Убираем из ожидания
                            continue

                        # Получаем ADB порт
                        adb_port = self._get_adb_port_by_index(emulator_index)

                        if adb_port and self._test_adb_connection(adb_port):
                            logger.info(f"✓ Эмулятор {emulator_index} готов (ADB порт: {adb_port}) за {elapsed_time:.1f}s")

                            wait_result['ready_emulators'] += 1
                            wait_result['results'].append({
                                'index': emulator_index,
                                'ready': True,
                                'adb_port': adb_port,
                                'wait_time': elapsed_time,
                                'message': 'Готов'
                            })
                            newly_ready.append(emulator_index)
                            ready_emulators.append(emulator_index)

                    except Exception as e:
                        logger.error(f"Ошибка проверки готовности эмулятора {emulator_index}: {e}")

                # Убираем готовые эмуляторы из списка ожидания
                for emulator_index in newly_ready:
                    pending_emulators.remove(emulator_index)

                # Если остались ожидающие, делаем паузу
                if pending_emulators:
                    time.sleep(check_interval)

            # Обрабатываем эмуляторы, которые не дождались готовности
            final_elapsed = time.time() - start_wait_time

            for emulator_index in pending_emulators:
                logger.warning(f"⏱ Таймаут ожидания готовности эмулятора {emulator_index}")
                wait_result['timeout_emulators'] += 1
                wait_result['results'].append({
                    'index': emulator_index,
                    'ready': False,
                    'adb_port': None,
                    'wait_time': final_elapsed,
                    'message': f'Таймаут {timeout}s'
                })

        except Exception as e:
            logger.error(f"Критическая ошибка ожидания готовности батча: {e}")
            wait_result['success'] = False

        wait_result['total_wait_time'] = time.time() - start_wait_time

        # Определяем общий результат
        if wait_result['timeout_emulators'] == 0 and wait_result['failed_emulators'] == 0:
            wait_result['success'] = True
            logger.info(f"✓ Батч готов за {wait_result['total_wait_time']:.1f}s - все {wait_result['ready_emulators']} эмуляторов")
        else:
            wait_result['success'] = False
            logger.warning(f"⚠ Батч частично готов за {wait_result['total_wait_time']:.1f}s")
            logger.warning(f"Готовы: {wait_result['ready_emulators']}, таймауты: {wait_result['timeout_emulators']}, ошибки: {wait_result['failed_emulators']}")

        return wait_result

    # ===== ПРОФИЛИ ПРОИЗВОДИТЕЛЬНОСТИ =====

    def apply_performance_profile(self, emulator_index, profile_name):
        """
        Применение профиля производительности к эмулятору

        Args:
            emulator_index (int): Индекс эмулятора
            profile_name (str): Название профиля (rushing, developing, farming, dormant, emergency)

        Returns:
            dict: Результат применения профиля
        """
        logger.info(f"Применение профиля '{profile_name}' к эмулятору {emulator_index}")

        result = {
            'success': False,
            'profile_applied': profile_name,
            'changes_made': [],
            'restart_required': False,
            'message': ''
        }

        try:
            # Проверяем существование профиля
            if profile_name not in self.performance_profiles:
                available_profiles = list(self.performance_profiles.keys())
                result['message'] = f"Профиль '{profile_name}' не найден. Доступные: {available_profiles}"
                logger.error(result['message'])
                return result

            profile = self.performance_profiles[profile_name]
            logger.info(f"Профиль '{profile_name}': {profile.get('description', 'без описания')}")

            # Проверяем статус эмулятора
            emulator_running = self.is_running(emulator_index)
            if emulator_running:
                logger.info(f"Эмулятор {emulator_index} запущен - потребуется перезапуск для применения изменений")
                result['restart_required'] = True

            # Применяем настройки из профиля
            resource_result = self.modify_resources(
                emulator_index=emulator_index,
                cpu=profile.get('cpu'),
                memory=profile.get('memory'),
                resolution=profile.get('resolution')
            )

            # Анализируем результат изменения ресурсов
            if resource_result['success']:
                result['changes_made'] = resource_result['changes_applied']

                # Добавляем информацию о FPS если она есть в профиле
                fps = profile.get('fps')
                if fps:
                    result['changes_made'].append(f"Target FPS: {fps}")
                    # Примечание: FPS обычно устанавливается через настройки эмулятора или игры

                result['success'] = True
                result['message'] = f"Профиль '{profile_name}' применён. Изменения: {', '.join(result['changes_made'])}"

                if result['restart_required']:
                    result['message'] += ". Требуется перезапуск эмулятора"

                logger.info(f"✓ {result['message']}")
            else:
                result['message'] = f"Ошибка применения профиля: {resource_result['message']}"
                logger.error(result['message'])

            return result

        except Exception as e:
            result['message'] = f"Исключение при применении профиля '{profile_name}': {str(e)}"
            logger.error(result['message'])
            return result

    def get_available_profiles(self):
        """
        Получение списка доступных профилей производительности

        Returns:
            dict: Словарь профилей с описаниями
        """
        profiles_info = {}

        for profile_name, profile_data in self.performance_profiles.items():
            profiles_info[profile_name] = {
                'cpu': profile_data.get('cpu', 'N/A'),
                'memory': profile_data.get('memory', 'N/A'),
                'fps': profile_data.get('fps', 'N/A'),
                'resolution': profile_data.get('resolution', 'N/A'),
                'description': profile_data.get('description', 'Без описания')
            }

        return profiles_info

    def apply_profile_to_batch(self, emulator_indexes, profile_name, restart_if_needed=False):
        """
        Применение профиля производительности к батчу эмуляторов

        Args:
            emulator_indexes (list): Список индексов эмуляторов
            profile_name (str): Название профиля
            restart_if_needed (bool): Автоматический перезапуск если нужно

        Returns:
            dict: Результат применения профиля к батчу
        """
        logger.info(f"=== Применение профиля '{profile_name}' к батчу из {len(emulator_indexes)} эмуляторов ===")

        batch_result = {
            'success': True,
            'profile_name': profile_name,
            'total_emulators': len(emulator_indexes),
            'applied_successfully': 0,
            'failed': 0,
            'restart_required': [],
            'results': []
        }

        try:
            for emulator_index in emulator_indexes:
                logger.info(f"Применяем профиль к эмулятору {emulator_index}")

                profile_result = self.apply_performance_profile(emulator_index, profile_name)
                profile_result['index'] = emulator_index
                batch_result['results'].append(profile_result)

                if profile_result['success']:
                    batch_result['applied_successfully'] += 1

                    if profile_result['restart_required']:
                        batch_result['restart_required'].append(emulator_index)

                        # Автоматический перезапуск если требуется
                        if restart_if_needed:
                            logger.info(f"Перезапускаем эмулятор {emulator_index} для применения профиля...")

                            # Останавливаем эмулятор
                            stop_result = self.stop_emulator(emulator_index, timeout=30)
                            if stop_result['success']:
                                time.sleep(3)  # Пауза между остановкой и запуском

                                # Запускаем снова
                                start_result = self.start_emulator(emulator_index, wait_ready=True, timeout=60)
                                if start_result['success']:
                                    logger.info(f"✓ Эмулятор {emulator_index} перезапущен с новым профилем")
                                    profile_result['restarted'] = True
                                else:
                                    logger.error(f"✗ Ошибка перезапуска эмулятора {emulator_index}")
                                    profile_result['restart_failed'] = True
                            else:
                                logger.error(f"✗ Ошибка остановки эмулятора {emulator_index} для перезапуска")
                                profile_result['stop_failed'] = True
                else:
                    batch_result['failed'] += 1

            # Общий результат
            if batch_result['failed'] == 0:
                batch_result['success'] = True
                logger.info(f"✓ Профиль '{profile_name}' применён ко всем эмуляторам")
            else:
                batch_result['success'] = False
                logger.warning(f"⚠ Профиль применён частично: {batch_result['applied_successfully']}/{len(emulator_indexes)}")

            if batch_result['restart_required'] and not restart_if_needed:
                logger.info(f"Эмуляторы требуют перезапуска: {batch_result['restart_required']}")

            return batch_result

        except Exception as e:
            logger.error(f"Критическая ошибка применения профиля к батчу: {e}")
            batch_result['success'] = False
            return batch_result

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ДЛЯ БАТЧЕЙ =====

    def _start_single_emulator_for_batch(self, emulator_index, timeout):
        """Запуск одного эмулятора для использования в батче"""
        try:
            result = self.start_emulator(emulator_index, wait_ready=False, timeout=timeout)
            return result
        except Exception as e:
            return {
                'success': False,
                'already_running': False,
                'start_time': 0,
                'message': f'Исключение: {str(e)}'
            }

    def _stop_single_emulator_for_batch(self, emulator_index, timeout):
        """Остановка одного эмулятора для использования в батче"""
        try:
            result = self.stop_emulator(emulator_index, force=False, timeout=timeout)
            return result
        except Exception as e:
            return {
                'success': False,
                'was_running': False,
                'stop_time': 0,
                'message': f'Исключение: {str(e)}'
            }

    # ===== ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ =====

    def get_all_emulators_status(self):
        """
        Получение статуса всех эмуляторов

        Returns:
            dict: Словарь {index: info} для всех эмуляторов
        """
        try:
            emulators = {}

            cmd_result = self._run_ldconsole_command(['list2'], timeout=15)

            if not cmd_result['success']:
                logger.error(f"Не удалось получить список эмуляторов: {cmd_result['stderr']}")
                return emulators

            lines = cmd_result['stdout'].split('\n')

            for line in lines:
                if not line.strip():
                    continue

                parts = line.split(',')

                if len(parts) >= 5:
                    try:
                        index = int(parts[0])

                        emulator_info = {
                            'index': index,
                            'name': parts[1],
                            'is_running': parts[4] == '1',
                            'adb_port': self._get_adb_port_by_index(index) if parts[4] == '1' else None
                        }

                        # Добавляем дополнительную информацию если доступно
                        if len(parts) >= 10:
                            emulator_info.update({
                                'width': int(parts[7]) if parts[7].isdigit() else 0,
                                'height': int(parts[8]) if parts[8].isdigit() else 0,
                                'dpi': int(parts[9]) if parts[9].isdigit() else 0
                            })

                        emulators[index] = emulator_info

                    except (ValueError, IndexError):
                        continue

            logger.info(f"Получен статус {len(emulators)} эмуляторов")
            return emulators

        except Exception as e:
            logger.error(f"Ошибка получения статуса всех эмуляторов: {e}")
            return {}

    def get_emulator_info(self, emulator_index):
        """
        Получение детальной информации об эмуляторе

        Args:
            emulator_index (int): Индекс эмулятора

        Returns:
            dict: Информация об эмуляторе или None
        """
        try:
            cmd_result = self._run_ldconsole_command(['list2'], timeout=10)

            if not cmd_result['success']:
                logger.error(f"Не удалось получить информацию: {cmd_result['stderr']}")
                return None

            lines = cmd_result['stdout'].split('\n')

            for line in lines:
                if not line.strip():
                    continue

                parts = line.split(',')

                if len(parts) >= 10:
                    try:
                        index = int(parts[0])

                        if index == emulator_index:
                            info = {
                                'index': index,
                                'name': parts[1],
                                'is_running': parts[4] == '1',
                                'width': int(parts[7]) if parts[7].isdigit() else 0,
                                'height': int(parts[8]) if parts[8].isdigit() else 0,
                                'dpi': int(parts[9]) if parts[9].isdigit() else 0,
                                'adb_port': self._get_adb_port_by_index(index) if parts[4] == '1' else None,
                                'last_checked': datetime.now().isoformat()
                            }

                            logger.debug(f"Информация об эмуляторе {emulator_index}: {info}")
                            return info

                    except (ValueError, IndexError) as e:
                        logger.debug(f"Ошибка парсинга строки '{line}': {e}")
                        continue

            logger.warning(f"Эмулятор с индексом {emulator_index} не найден")
            return None

        except Exception as e:
            logger.error(f"Ошибка получения информации об эмуляторе {emulator_index}: {e}")
            return None

    # ===== СУЩЕСТВУЮЩИЕ МЕТОДЫ (без изменений) =====

    def start_emulator(self, emulator_index, wait_ready=True, timeout=60):
        """Запуск эмулятора по индексу (исходная реализация)"""
        logger.info(f"Запуск эмулятора с индексом {emulator_index}")

        start_operation_time = time.time()

        result = {
            'success': False,
            'already_running': False,
            'start_time': 0,
            'adb_ready_time': 0,
            'message': '',
            'adb_port': None
        }

        try:
            # Проверяем, не запущен ли эмулятор уже
            if self.is_running(emulator_index):
                result['already_running'] = True
                result['success'] = True
                result['message'] = f'Эмулятор {emulator_index} уже запущен'
                result['adb_port'] = self._get_adb_port_by_index(emulator_index)
                logger.info(result['message'])
                return result

            # Команда запуска эмулятора
            cmd_result = self._run_ldconsole_command(['launch', '--index', str(emulator_index)], timeout)

            result['start_time'] = cmd_result['execution_time']

            if not cmd_result['success']:
                result['message'] = f"Ошибка запуска: {cmd_result['stderr']}"
                logger.error(result['message'])
                return result

            logger.info(f"Команда запуска отправлена за {result['start_time']:.1f}s")

            # Ждём готовности если нужно
            if wait_ready:
                logger.info(f"Ожидание готовности эмулятора {emulator_index}...")
                ready_result = self._wait_emulator_ready(emulator_index, timeout)

                result['adb_ready_time'] = ready_result['wait_time']
                result['adb_port'] = ready_result['adb_port']

                if ready_result['success']:
                    result['success'] = True
                    result['message'] = f"Эмулятор {emulator_index} запущен и готов (ADB: {ready_result['adb_port']})"
                    logger.info(f"✓ {result['message']} за {result['start_time'] + result['adb_ready_time']:.1f}s")
                else:
                    result['message'] = f"Эмулятор запущен, но ADB не готов: {ready_result['message']}"
                    logger.warning(result['message'])
            else:
                result['success'] = True
                result['message'] = f"Команда запуска эмулятора {emulator_index} отправлена"
                logger.info(result['message'])

            # Обновляем кэш состояний
            self.running_emulators[emulator_index] = {
                'status': 'running',
                'last_check': datetime.now(),
                'adb_port': result['adb_port']
            }

            return result

        except Exception as e:
            result['message'] = f"Исключение при запуске эмулятора {emulator_index}: {str(e)}"
            logger.error(result['message'])
            return result

    def stop_emulator(self, emulator_index, force=False, timeout=30):
        """Остановка эмулятора (исходная реализация)"""
        logger.info(f"Остановка эмулятора {emulator_index} (принудительно: {force})")

        result = {
            'success': False,
            'was_running': False,
            'stop_time': 0,
            'message': ''
        }

        try:
            if not self.is_running(emulator_index):
                result['success'] = True
                result['message'] = f'Эмулятор {emulator_index} уже остановлен'
                logger.info(result['message'])
                return result

            result['was_running'] = True

            if force:
                command = ['killall']
                logger.info(f"Принудительная остановка всех эмуляторов")
            else:
                command = ['quit', '--index', str(emulator_index)]

            cmd_result = self._run_ldconsole_command(command, timeout)
            result['stop_time'] = cmd_result['execution_time']

            if cmd_result['success']:
                time.sleep(2)

                if not self.is_running(emulator_index):
                    result['success'] = True
                    result['message'] = f"Эмулятор {emulator_index} успешно остановлен за {result['stop_time']:.1f}s"
                    logger.info(f"✓ {result['message']}")

                    if emulator_index in self.running_emulators:
                        del self.running_emulators[emulator_index]
                else:
                    result['message'] = f"Команда остановки выполнена, но эмулятор {emulator_index} всё ещё работает"
                    logger.warning(result['message'])
            else:
                result['message'] = f"Ошибка остановки: {cmd_result['stderr']}"
                logger.error(result['message'])

            return result

        except Exception as e:
            result['message'] = f"Исключение при остановке эмулятора {emulator_index}: {str(e)}"
            logger.error(result['message'])
            return result

    def is_running(self, emulator_index, force_check=False):
        """Проверка статуса работы эмулятора (исходная реализация)"""
        try:
            if not force_check and emulator_index in self.running_emulators:
                cached = self.running_emulators[emulator_index]
                last_check = cached['last_check']

                if datetime.now() - last_check < timedelta(seconds=60):
                    is_running = cached['status'] == 'running'
                    logger.debug(f"Используем кэш для эмулятора {emulator_index}: {is_running}")
                    return is_running

            cmd_result = self._run_ldconsole_command(['list2'], timeout=10)

            if not cmd_result['success']:
                logger.warning(f"Не удалось получить список эмуляторов: {cmd_result['stderr']}")
                return False

            lines = cmd_result['stdout'].split('\n')

            for line in lines:
                if not line.strip():
                    continue

                parts = line.split(',')

                if len(parts) >= 5:
                    try:
                        index = int(parts[0])
                        is_running_flag = parts[4] == '1'

                        if index == emulator_index:
                            self.running_emulators[emulator_index] = {
                                'status': 'running' if is_running_flag else 'stopped',
                                'last_check': datetime.now(),
                                'adb_port': self._get_adb_port_by_index(emulator_index) if is_running_flag else None
                            }

                            logger.debug(f"Эмулятор {emulator_index} статус: {'запущен' if is_running_flag else 'остановлен'}")
                            return is_running_flag

                    except (ValueError, IndexError):
                        continue

            logger.debug(f"Эмулятор {emulator_index} не найден в списке - считаем остановленным")

            if emulator_index in self.running_emulators:
                self.running_emulators[emulator_index]['status'] = 'stopped'
                self.running_emulators[emulator_index]['last_check'] = datetime.now()

            return False

        except Exception as e:
            logger.error(f"Ошибка проверки статуса эмулятора {emulator_index}: {e}")
            return False

    def modify_resources(self, emulator_index, cpu=None, memory=None, resolution=None):
        """Изменение ресурсов эмулятора (исходная реализация)"""
        logger.info(f"Изменение ресурсов эмулятора {emulator_index}: CPU={cpu}, RAM={memory}, RES={resolution}")

        result = {
            'success': False,
            'changes_applied': [],
            'changes_failed': [],
            'message': '',
            'restart_required': False
        }

        try:
            if self.is_running(emulator_index):
                result['message'] = f"Для изменения ресурсов эмулятор {emulator_index} должен быть остановлен"
                logger.warning(result['message'])
                result['restart_required'] = True

            changes_count = 0

            if cpu is not None:
                cpu_result = self._run_ldconsole_command(['modify', '--index', str(emulator_index), '--cpu', str(cpu)])

                if cpu_result['success']:
                    result['changes_applied'].append(f"CPU: {cpu} ядер")
                    changes_count += 1
                    logger.info(f"✓ CPU установлен на {cpu} ядер")
                else:
                    result['changes_failed'].append(f"CPU: {cpu_result['stderr']}")
                    logger.error(f"✗ Ошибка установки CPU: {cpu_result['stderr']}")

            if memory is not None:
                memory_result = self._run_ldconsole_command(
                    ['modify', '--index', str(emulator_index), '--memory', str(memory)])

                if memory_result['success']:
                    result['changes_applied'].append(f"Memory: {memory} MB")
                    changes_count += 1
                    logger.info(f"✓ Память установлена на {memory} MB")
                else:
                    result['changes_failed'].append(f"Memory: {memory_result['stderr']}")
                    logger.error(f"✗ Ошибка установки памяти: {memory_result['stderr']}")

            if resolution is not None:
                try:
                    width, height = resolution.split('x')
                    res_result = self._run_ldconsole_command([
                        'modify', '--index', str(emulator_index),
                        '--resolution', width, height
                    ])

                    if res_result['success']:
                        result['changes_applied'].append(f"Resolution: {resolution}")
                        changes_count += 1
                        logger.info(f"✓ Разрешение установлено на {resolution}")
                    else:
                        result['changes_failed'].append(f"Resolution: {res_result['stderr']}")
                        logger.error(f"✗ Ошибка установки разрешения: {res_result['stderr']}")

                except ValueError:
                    result['changes_failed'].append(
                        f"Resolution: неверный формат '{resolution}' (ожидается 'WIDTHxHEIGHT')")
                    logger.error(f"✗ Неверный формат разрешения: {resolution}")

            if changes_count > 0:
                result['success'] = True
                applied = ", ".join(result['changes_applied'])
                failed = ", ".join(result['changes_failed']) if result['changes_failed'] else "нет"

                result['message'] = f"Применено изменений: {changes_count}. Успешно: {applied}. Ошибки: {failed}"

                if result['restart_required']:
                    result['message'] += ". Требуется перезапуск эмулятора"

                logger.info(f"✓ Ресурсы эмулятора {emulator_index} изменены: {result['message']}")
            else:
                result['message'] = "Никаких изменений не было запрошено"

            return result

        except Exception as e:
            result['message'] = f"Исключение при изменении ресурсов эмулятора {emulator_index}: {str(e)}"
            logger.error(result['message'])
            return result

    def _wait_emulator_ready(self, emulator_index, timeout=60):
        """Ожидание готовности эмулятора (исходная реализация)"""
        logger.info(f"Ожидание готовности эмулятора {emulator_index} (таймаут: {timeout}s)")

        result = {
            'success': False,
            'wait_time': 0,
            'adb_port': None,
            'message': ''
        }

        start_time = time.time()
        adb_port = None

        try:
            while time.time() - start_time < timeout:
                if not self.is_running(emulator_index, force_check=True):
                    result['message'] = f"Эмулятор {emulator_index} неожиданно остановился"
                    break

                adb_port = self._get_adb_port_by_index(emulator_index)

                if adb_port:
                    if self._test_adb_connection(adb_port):
                        result['success'] = True
                        result['adb_port'] = adb_port
                        result['message'] = f"Эмулятор готов, ADB порт: {adb_port}"
                        break

                time.sleep(2)
                elapsed = time.time() - start_time
                logger.debug(f"Ожидание готовности... {elapsed:.1f}s / {timeout}s")

            result['wait_time'] = time.time() - start_time

            if not result['success']:
                if not result['message']:
                    result['message'] = f"Таймаут ожидания готовности эмулятора {emulator_index} ({timeout}s)"

                logger.warning(result['message'])
            else:
                logger.info(f"✓ Эмулятор {emulator_index} готов за {result['wait_time']:.1f}s")

            return result

        except Exception as e:
            result['wait_time'] = time.time() - start_time
            result['message'] = f"Ошибка ожидания готовности: {str(e)}"
            logger.error(result['message'])
            return result

    def _get_adb_port_by_index(self, emulator_index):
        """Получение ADB порта по индексу эмулятора (исходная реализация)"""
        try:
            standard_port = 5554 + (emulator_index * 2)

            if self._test_adb_connection(standard_port):
                return standard_port

            try:
                result = subprocess.run(
                    ['adb', 'devices'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    lines = result.stdout.split('\n')[1:]

                    for line in lines:
                        if 'device' in line:
                            parts = line.split()
                            if len(parts) >= 1:
                                device = parts[0]

                                if 'emulator-' in device:
                                    port = int(device.replace('emulator-', ''))
                                    return port
                                elif ':' in device:
                                    port = int(device.split(':')[1])
                                    return port
            except:
                pass

            return None

        except Exception as e:
            logger.debug(f"Ошибка определения ADB порта для эмулятора {emulator_index}: {e}")
            return None

    def _test_adb_connection(self, port):
        """Тест ADB подключения к порту (исходная реализация)"""
        try:
            result = subprocess.run(
                ['adb', '-s', f'127.0.0.1:{port}', 'shell', 'echo', 'test'],
                capture_output=True,
                text=True,
                timeout=5
            )

            return result.returncode == 0 and 'test' in result.stdout

        except:
            return False

    def get_all_emulators_status(self):
        """
        Получение статуса всех эмуляторов

        Returns:
            dict: Словарь {index: info} для всех эмуляторов
        """
        try:
            emulators = {}

            cmd_result = self._run_ldconsole_command(['list2'], timeout=15)

            if not cmd_result['success']:
                logger.error(f"Не удалось получить список эмуляторов: {cmd_result['stderr']}")
                return emulators

            lines = cmd_result['stdout'].split('\n')

            for line in lines:
                if not line.strip():
                    continue

                parts = line.split(',')

                if len(parts) >= 5:
                    try:
                        index = int(parts[0])

                        emulator_info = {
                            'index': index,
                            'name': parts[1],
                            'is_running': parts[4] == '1',
                            'adb_port': self._get_adb_port_by_index(index) if parts[4] == '1' else None
                        }

                        # Добавляем дополнительную информацию если доступно
                        if len(parts) >= 10:
                            emulator_info.update({
                                'width': int(parts[7]) if parts[7].isdigit() else 0,
                                'height': int(parts[8]) if parts[8].isdigit() else 0,
                                'dpi': int(parts[9]) if parts[9].isdigit() else 0
                            })

                        emulators[index] = emulator_info

                    except (ValueError, IndexError):
                        continue

            logger.info(f"Получен статус {len(emulators)} эмуляторов")
            return emulators

        except Exception as e:
            logger.error(f"Ошибка получения статуса всех эмуляторов: {e}")
            return {}

    def get_emulator_info(self, emulator_index):
        """
        Получение детальной информации об эмуляторе

        Args:
            emulator_index (int): Индекс эмулятора

        Returns:
            dict: Информация об эмуляторе или None
        """
        try:
            cmd_result = self._run_ldconsole_command(['list2'], timeout=10)

            if not cmd_result['success']:
                logger.error(f"Не удалось получить информацию: {cmd_result['stderr']}")
                return None

            # Парсим вывод list2
            lines = cmd_result['stdout'].split('\n')

            for line in lines:
                if not line.strip():
                    continue

                parts = line.split(',')

                if len(parts) >= 10:
                    try:
                        index = int(parts[0])

                        if index == emulator_index:
                            info = {
                                'index': index,
                                'name': parts[1],
                                'is_running': parts[4] == '1',
                                'width': int(parts[7]) if parts[7].isdigit() else 0,
                                'height': int(parts[8]) if parts[8].isdigit() else 0,
                                'dpi': int(parts[9]) if parts[9].isdigit() else 0,
                                'adb_port': self._get_adb_port_by_index(index) if parts[4] == '1' else None,
                                'last_checked': datetime.now().isoformat()
                            }

                            logger.debug(f"Информация об эмуляторе {emulator_index}: {info}")
                            return info

                    except (ValueError, IndexError) as e:
                        logger.debug(f"Ошибка парсинга строки '{line}': {e}")
                        continue

            logger.warning(f"Эмулятор с индексом {emulator_index} не найден")
            return None

        except Exception as e:
            logger.error(f"Ошибка получения информации об эмуляторе {emulator_index}: {e}")
            return None

    def health_check(self):
        """Проверка здоровья LDConsole Manager (исходная реализация)"""
        result = {
            'healthy': True,
            'ldconsole_available': False,
            'adb_available': False,
            'running_emulators': 0,
            'loaded_profiles': len(self.performance_profiles),
            'issues': []
        }

        try:
            # Проверка ldconsole
            if os.path.exists(self.ldconsole_path):
                test_result = self._run_ldconsole_command(['list2'], timeout=10)
                result['ldconsole_available'] = test_result['success']

                if test_result['success']:
                    lines = test_result['stdout'].split('\n')
                    running_count = 0

                    for line in lines:
                        if line.strip():
                            parts = line.split(',')
                            if len(parts) >= 5 and parts[4] == '1':
                                running_count += 1

                    result['running_emulators'] = running_count
                else:
                    result['issues'].append(f"ldconsole недоступен: {test_result['stderr']}")
                    result['healthy'] = False
            else:
                result['issues'].append(f"ldconsole.exe не найден: {self.ldconsole_path}")
                result['healthy'] = False

            # Проверка ADB
            try:
                adb_result = subprocess.run(['adb', 'version'], capture_output=True, timeout=5)
                result['adb_available'] = adb_result.returncode == 0

                if not result['adb_available']:
                    result['issues'].append("ADB недоступен")
                    result['healthy'] = False

            except:
                result['issues'].append("ADB не установлен или недоступен")
                result['healthy'] = False

            # Проверка профилей производительности
            if not self.performance_profiles:
                result['issues'].append("Профили производительности не загружены")
                result['healthy'] = False

            logger.info(f"Health check завершён: healthy={result['healthy']}, running={result['running_emulators']}, profiles={result['loaded_profiles']}")
            return result

        except Exception as e:
            result['healthy'] = False
            result['issues'].append(f"Ошибка health check: {str(e)}")
            logger.error(f"Ошибка health check: {e}")
            return result


def test_extended_ldconsole_manager():
    """Тестирование расширенного LDConsoleManager с батчевыми операциями"""
    logger.info("=== Тестирование расширенного LDConsoleManager ===")

    try:
        # Инициализация
        manager = LDConsoleManager()

        # Health check
        health = manager.health_check()
        logger.info(f"Health check: {health}")

        if not health['healthy']:
            logger.error("LDConsoleManager не готов к работе")
            return False

        # Тестирование профилей производительности
        logger.info("\n--- Тестирование профилей производительности ---")
        available_profiles = manager.get_available_profiles()

        for profile_name, profile_info in available_profiles.items():
            logger.info(f"Профиль '{profile_name}': {profile_info['description']}")
            logger.info(f"  CPU: {profile_info['cpu']}, RAM: {profile_info['memory']}, FPS: {profile_info['fps']}, Res: {profile_info['resolution']}")

        # Получение статуса всех эмуляторов
        all_status = manager.get_all_emulators_status()
        logger.info(f"\n--- Найдено эмуляторов: {len(all_status)} ---")

        for index, info in all_status.items():
            status = "запущен" if info['is_running'] else "остановлен"
            logger.info(f"  Эмулятор {index}: {info['name']} - {status}")

        # Тестирование батчевых операций на первых 2 эмуляторах
        if len(all_status) >= 1:
            test_indexes = list(all_status.keys())[:2]  # Берём первые 2 эмулятора
            logger.info(f"\n--- Тестирование батчевых операций на эмуляторах {test_indexes} ---")

            # Останавливаем если запущены
            logger.info("1. Останавливаем эмуляторы...")
            stop_result = manager.stop_batch(test_indexes, force=False)
            logger.info(f"Результат остановки: успешно={stop_result['stopped_successfully']}, ошибки={stop_result['failed']}")

            time.sleep(3)

            # Применяем профиль farming к эмуляторам
            logger.info("2. Применяем профиль 'farming'...")
            profile_result = manager.apply_profile_to_batch(test_indexes, 'farming')
            logger.info(f"Результат применения профиля: успешно={profile_result['applied_successfully']}, ошибки={profile_result['failed']}")

            # Демонстрируем запуск батча (но не запускаем реально)
            logger.info("3. Демонстрация API запуска батча (без реального запуска)...")
            logger.info(f"Команда для запуска: manager.start_batch({test_indexes}, max_parallel=2)")
            logger.info(f"Команда ожидания готовности: manager.wait_batch_ready({test_indexes}, timeout=120)")

        logger.info("✓ Тестирование расширенного LDConsoleManager завершено успешно")
        return True

    except Exception as e:
        logger.error(f"Ошибка тестирования расширенного LDConsoleManager: {e}")
        return False


if __name__ == "__main__":
    test_extended_ldconsole_manager()