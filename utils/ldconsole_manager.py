"""
LDConsole Manager для управления жизненным циклом эмуляторов LDPlayer.
Интеграция с ldconsole.exe через subprocess для запуска, остановки и настройки эмуляторов.
"""
import os
import time
import subprocess
import psutil
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger


class LDConsoleManager:
    """Класс для управления эмуляторами LDPlayer через ldconsole"""

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

        # Если путь не указан, пытаемся найти автоматически
        if not self.ldconsole_path:
            self.ldconsole_path = self._find_ldconsole_path()

        if not self.ldconsole_path:
            raise FileNotFoundError("ldconsole.exe не найден. Укажите путь вручную")

        logger.info(f"LDConsoleManager инициализирован: {self.ldconsole_path}")

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

    def _run_ldconsole_command(self, command_args, timeout=None):
        """
        Выполнение ldconsole команды через subprocess

        Args:
            command_args (list): Аргументы команды
            timeout (int, optional): Таймаут выполнения

        Returns:
            dict: Результат выполнения со структурой:
                {
                    'success': bool,
                    'stdout': str,
                    'stderr': str,
                    'returncode': int,
                    'execution_time': float
                }
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

    def start_emulator(self, emulator_index, wait_ready=True, timeout=60):
        """
        Запуск эмулятора по индексу

        Args:
            emulator_index (int): Индекс эмулятора в LDPlayer
            wait_ready (bool): Ждать готовности ADB подключения
            timeout (int): Таймаут запуска и ожидания готовности

        Returns:
            dict: Результат операции со структурой:
                {
                    'success': bool,
                    'already_running': bool,
                    'start_time': float,         # Время запуска в секундах
                    'adb_ready_time': float,     # Время готовности ADB
                    'message': str,
                    'adb_port': int              # Порт ADB если определён
                }
        """
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
                # Не ждём готовности, считаем успешным
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
        """
        Остановка эмулятора

        Args:
            emulator_index (int): Индекс эмулятора
            force (bool): Принудительная остановка (killall)
            timeout (int): Таймаут операции

        Returns:
            dict: Результат остановки
        """
        logger.info(f"Остановка эмулятора {emulator_index} (принудительно: {force})")

        result = {
            'success': False,
            'was_running': False,
            'stop_time': 0,
            'message': ''
        }

        try:
            # Проверяем, запущен ли эмулятор
            if not self.is_running(emulator_index):
                result['success'] = True
                result['message'] = f'Эмулятор {emulator_index} уже остановлен'
                logger.info(result['message'])
                return result

            result['was_running'] = True

            # Выбираем команду остановки
            if force:
                command = ['killall']
                logger.info(f"Принудительная остановка всех эмуляторов")
            else:
                command = ['quit', '--index', str(emulator_index)]

            # Выполняем команду остановки
            cmd_result = self._run_ldconsole_command(command, timeout)
            result['stop_time'] = cmd_result['execution_time']

            if cmd_result['success']:
                # Дополнительная проверка что эмулятор действительно остановился
                time.sleep(2)  # Даём время на завершение процессов

                if not self.is_running(emulator_index):
                    result['success'] = True
                    result['message'] = f"Эмулятор {emulator_index} успешно остановлен за {result['stop_time']:.1f}s"
                    logger.info(f"✓ {result['message']}")

                    # Обновляем кэш
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
        """
        Проверка статуса работы эмулятора

        Args:
            emulator_index (int): Индекс эмулятора
            force_check (bool): Принудительная проверка (обход кэша)

        Returns:
            bool: True если эмулятор запущен
        """
        try:
            # Проверяем кэш если не принудительная проверка
            if not force_check and emulator_index in self.running_emulators:
                cached = self.running_emulators[emulator_index]
                last_check = cached['last_check']

                # Если проверка была меньше минуты назад, используем кэш
                if datetime.now() - last_check < timedelta(seconds=60):
                    is_running = cached['status'] == 'running'
                    logger.debug(f"Используем кэш для эмулятора {emulator_index}: {is_running}")
                    return is_running

            # Выполняем реальную проверку через ldconsole
            cmd_result = self._run_ldconsole_command(['list2'], timeout=10)

            if not cmd_result['success']:
                logger.warning(f"Не удалось получить список эмуляторов: {cmd_result['stderr']}")
                return False

            # Парсим вывод list2
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
                            # Обновляем кэш
                            self.running_emulators[emulator_index] = {
                                'status': 'running' if is_running_flag else 'stopped',
                                'last_check': datetime.now(),
                                'adb_port': self._get_adb_port_by_index(emulator_index) if is_running_flag else None
                            }

                            logger.debug(
                                f"Эмулятор {emulator_index} статус: {'запущен' if is_running_flag else 'остановлен'}")
                            return is_running_flag

                    except (ValueError, IndexError):
                        continue

            # Если эмулятор не найден в списке, считаем остановленным
            logger.debug(f"Эмулятор {emulator_index} не найден в списке - считаем остановленным")

            if emulator_index in self.running_emulators:
                self.running_emulators[emulator_index]['status'] = 'stopped'
                self.running_emulators[emulator_index]['last_check'] = datetime.now()

            return False

        except Exception as e:
            logger.error(f"Ошибка проверки статуса эмулятора {emulator_index}: {e}")
            return False

    def modify_resources(self, emulator_index, cpu=None, memory=None, resolution=None):
        """
        Изменение ресурсов эмулятора (CPU, память, разрешение)

        Args:
            emulator_index (int): Индекс эмулятора
            cpu (int, optional): Количество CPU ядер
            memory (int, optional): Объём памяти в MB
            resolution (str, optional): Разрешение экрана (например "720x1280")

        Returns:
            dict: Результат операции
        """
        logger.info(f"Изменение ресурсов эмулятора {emulator_index}: CPU={cpu}, RAM={memory}, RES={resolution}")

        result = {
            'success': False,
            'changes_applied': [],
            'changes_failed': [],
            'message': '',
            'restart_required': False
        }

        try:
            # Проверяем, что эмулятор остановлен (для изменения ресурсов)
            if self.is_running(emulator_index):
                result['message'] = f"Для изменения ресурсов эмулятор {emulator_index} должен быть остановлен"
                logger.warning(result['message'])
                result['restart_required'] = True
                # Но продолжаем - некоторые команды могут работать

            changes_count = 0

            # Изменение CPU
            if cpu is not None:
                cpu_result = self._run_ldconsole_command(['modify', '--index', str(emulator_index), '--cpu', str(cpu)])

                if cpu_result['success']:
                    result['changes_applied'].append(f"CPU: {cpu} ядер")
                    changes_count += 1
                    logger.info(f"✓ CPU установлен на {cpu} ядер")
                else:
                    result['changes_failed'].append(f"CPU: {cpu_result['stderr']}")
                    logger.error(f"✗ Ошибка установки CPU: {cpu_result['stderr']}")

            # Изменение памяти
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

            # Изменение разрешения
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

            # Формируем итоговое сообщение
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

    def _wait_emulator_ready(self, emulator_index, timeout=60):
        """
        Ожидание готовности эмулятора (ADB подключение)

        Args:
            emulator_index (int): Индекс эмулятора
            timeout (int): Таймаут ожидания

        Returns:
            dict: Результат ожидания
        """
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
                # Проверяем, что эмулятор всё ещё запущен
                if not self.is_running(emulator_index, force_check=True):
                    result['message'] = f"Эмулятор {emulator_index} неожиданно остановился"
                    break

                # Пытаемся определить ADB порт
                adb_port = self._get_adb_port_by_index(emulator_index)

                if adb_port:
                    # Проверяем ADB подключение
                    if self._test_adb_connection(adb_port):
                        result['success'] = True
                        result['adb_port'] = adb_port
                        result['message'] = f"Эмулятор готов, ADB порт: {adb_port}"
                        break

                # Ждём немного перед следующей проверкой
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
        """
        Получение ADB порта по индексу эмулятора

        Args:
            emulator_index (int): Индекс эмулятора

        Returns:
            int: ADB порт или None
        """
        try:
            # Стандартная формула LDPlayer: порт = 5554 + index * 2
            standard_port = 5554 + (emulator_index * 2)

            # Проверяем стандартный порт
            if self._test_adb_connection(standard_port):
                return standard_port

            # Если стандартный не работает, ищем среди активных портов
            try:
                result = subprocess.run(
                    ['adb', 'devices'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    lines = result.stdout.split('\n')[1:]  # Пропускаем заголовок

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
        """
        Тест ADB подключения к порту

        Args:
            port (int): ADB порт для проверки

        Returns:
            bool: True если подключение работает
        """
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

    def health_check(self):
        """
        Проверка здоровья LDConsole Manager

        Returns:
            dict: Результат проверки здоровья
        """
        result = {
            'healthy': True,
            'ldconsole_available': False,
            'adb_available': False,
            'running_emulators': 0,
            'issues': []
        }

        try:
            # Проверка ldconsole
            if os.path.exists(self.ldconsole_path):
                test_result = self._run_ldconsole_command(['list2'], timeout=10)
                result['ldconsole_available'] = test_result['success']

                if test_result['success']:
                    # Подсчитываем запущенные эмуляторы
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

            logger.info(f"Health check завершён: healthy={result['healthy']}, running={result['running_emulators']}")
            return result

        except Exception as e:
            result['healthy'] = False
            result['issues'].append(f"Ошибка health check: {str(e)}")
            logger.error(f"Ошибка health check: {e}")
            return result


# Тестовая функция
def test_ldconsole_manager():
    """Тестирование LDConsoleManager"""
    logger.info("=== Тестирование LDConsoleManager ===")

    try:
        # Инициализация
        manager = LDConsoleManager()

        # Health check
        health = manager.health_check()
        logger.info(f"Health check: {health}")

        if not health['healthy']:
            logger.error("LDConsoleManager не готов к работе")
            return False

        # Получение статуса всех эмуляторов
        all_status = manager.get_all_emulators_status()
        logger.info(f"Найдено эмуляторов: {len(all_status)}")

        for index, info in all_status.items():
            status = "запущен" if info['is_running'] else "остановлен"
            logger.info(f"  Эмулятор {index}: {info['name']} - {status}")

        # Тестируем на первом доступном эмуляторе
        if all_status:
            test_index = list(all_status.keys())[0]
            logger.info(f"Тестируем на эмуляторе {test_index}")

            # Проверяем статус
            is_running = manager.is_running(test_index, force_check=True)
            logger.info(f"Статус эмулятора {test_index}: {'запущен' if is_running else 'остановлен'}")

            # Получаем детальную информацию
            info = manager.get_emulator_info(test_index)
            if info:
                logger.info(f"Информация: {info}")

        logger.info("✓ Тестирование LDConsoleManager завершено успешно")
        return True

    except Exception as e:
        logger.error(f"Ошибка тестирования LDConsoleManager: {e}")
        return False


if __name__ == "__main__":
    test_ldconsole_manager()