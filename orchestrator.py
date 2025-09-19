"""
Оркестратор для управления параллельными процессами bot_worker.
Координирует работу множества эмуляторов с системой автообнаружения и CLI управлением.
Интегрирован с EmulatorDiscovery для автоматического обнаружения и управления эмуляторами.
"""
import sys
import os
import time
import subprocess
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import click
from loguru import logger

# Добавляем корневую папку в путь для импорта
sys.path.append(str(Path(__file__).parent))

from utils.emulator_discovery import EmulatorDiscovery

# Настройка логирования
logger.add("logs/orchestrator_{time}.log", rotation="100 MB", level="INFO")


class Orchestrator:
    """Оркестратор для управления параллельными процессами bot_worker"""

    def __init__(self, max_workers=3):
        """
        Инициализация оркестратора

        Args:
            max_workers (int): Максимальное количество параллельных процессов
        """
        self.max_workers = max_workers
        self.discovery = EmulatorDiscovery()
        self.running_processes = {}  # Словарь активных процессов {emulator_name: process}

        logger.info(f"Orchestrator инициализирован с max_workers={max_workers}")

        # Создаём необходимые папки
        os.makedirs("logs", exist_ok=True)
        os.makedirs("screenshots", exist_ok=True)

    def auto_scan_emulators(self):
        """
        Автоматическое сканирование эмуляторов при запуске

        Returns:
            bool: True если сканирование успешно
        """
        try:
            logger.info("=== Автосканирование эмуляторов ===")

            # Загружаем существующую конфигурацию
            config = self.discovery.load_config()

            # Проверяем, нужно ли пересканировать
            should_rescan = False
            last_scan = config.get('ldplayer', {}).get('last_scan')

            if not last_scan:
                logger.info("Первый запуск - выполняем полное сканирование")
                should_rescan = True
            else:
                try:
                    last_scan_time = datetime.fromisoformat(last_scan)
                    scan_interval = config.get('ldplayer', {}).get('auto_scan_interval', 3600)

                    if datetime.now() - last_scan_time > timedelta(seconds=scan_interval):
                        logger.info(f"Прошло больше {scan_interval} секунд с последнего сканирования - пересканируем")
                        should_rescan = True
                    else:
                        logger.info(f"Последнее сканирование: {last_scan_time.strftime('%Y-%m-%d %H:%M:%S')} - пересканирование не требуется")
                except:
                    should_rescan = True

            if should_rescan:
                # Выполняем полное обнаружение
                result = self.discovery.discover_and_save()

                if result['success']:
                    logger.info(f"✓ Автосканирование завершено: {result['message']}")
                    return True
                else:
                    logger.error(f"✗ Ошибка автосканирования: {result['message']}")
                    return False
            else:
                # Просто загружаем существующую конфигурацию
                self.discovery.load_config()
                logger.info("✓ Конфигурация эмуляторов загружена из кэша")
                return True

        except Exception as e:
            logger.error(f"Ошибка автосканирования эмуляторов: {e}")
            return False

    def start_bot_worker(self, emulator):
        """
        Запуск bot_worker для одного эмулятора

        Args:
            emulator (dict): Данные эмулятора

        Returns:
            subprocess.Popen: Процесс или None при ошибке
        """
        try:
            emulator_name = emulator['name']
            adb_port = emulator.get('adb_port')

            if not adb_port:
                logger.warning(f"У эмулятора '{emulator_name}' не определён ADB порт - пропускаем")
                return None

            # Команда для запуска bot_worker
            cmd = [
                sys.executable, "bot_worker.py",
                "--emulator", emulator_name,
                "--port", str(adb_port)
            ]

            logger.info(f"Запуск bot_worker для '{emulator_name}' на порту {adb_port}")

            # Запускаем процесс
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            self.running_processes[emulator_name] = process
            logger.info(f"✓ Bot worker запущен для '{emulator_name}' (PID: {process.pid})")

            return process

        except Exception as e:
            logger.error(f"Ошибка запуска bot_worker для '{emulator['name']}': {e}")
            return None

    def run_batch(self, emulators, timeout=900):
        """
        Запуск батча эмуляторов параллельно

        Args:
            emulators (list): Список эмуляторов для обработки
            timeout (int): Таймаут для каждого процесса в секундах

        Returns:
            dict: Результаты выполнения батча
        """
        if not emulators:
            return {'success': True, 'processed': 0, 'failed': 0}

        logger.info(f"=== Запуск батча из {len(emulators)} эмуляторов ===")

        results = {
            'success': True,
            'processed': 0,
            'failed': 0,
            'details': []
        }

        try:
            # Используем ProcessPoolExecutor для параллельного запуска
            with ProcessPoolExecutor(max_workers=min(self.max_workers, len(emulators))) as executor:
                # Создаём задачи
                future_to_emulator = {}

                for emulator in emulators:
                    if emulator.get('adb_port'):
                        future = executor.submit(self._run_single_worker, emulator)
                        future_to_emulator[future] = emulator
                    else:
                        logger.warning(f"Пропускаем эмулятор '{emulator['name']}' - нет ADB порта")
                        results['failed'] += 1

                # Ждём завершения всех задач
                for future in as_completed(future_to_emulator, timeout=timeout):
                    emulator = future_to_emulator[future]
                    emulator_name = emulator['name']

                    try:
                        result = future.result(timeout=30)  # Дополнительный таймаут для получения результата

                        if result['success']:
                            logger.info(f"✓ Эмулятор '{emulator_name}' обработан успешно за {result['duration']:.1f}s")
                            results['processed'] += 1
                        else:
                            logger.error(f"✗ Ошибка обработки эмулятора '{emulator_name}': {result['error']}")
                            results['failed'] += 1

                        results['details'].append({
                            'emulator': emulator_name,
                            'success': result['success'],
                            'duration': result.get('duration', 0),
                            'error': result.get('error')
                        })

                    except Exception as e:
                        logger.error(f"✗ Исключение при обработке эмулятора '{emulator_name}': {e}")
                        results['failed'] += 1
                        results['details'].append({
                            'emulator': emulator_name,
                            'success': False,
                            'duration': 0,
                            'error': str(e)
                        })

        except Exception as e:
            logger.error(f"Ошибка выполнения батча: {e}")
            results['success'] = False

        # Итоговая статистика батча
        total = results['processed'] + results['failed']
        logger.info(f"=== Батч завершён: {results['processed']}/{total} успешно ===")

        return results

    def _run_single_worker(self, emulator):
        """
        Запуск одного bot_worker (для использования в ProcessPoolExecutor)

        Args:
            emulator (dict): Данные эмулятора

        Returns:
            dict: Результат выполнения
        """
        start_time = time.time()
        emulator_name = emulator['name']
        adb_port = emulator.get('adb_port')

        try:
            # Импортируем и запускаем bot_worker
            from bot_worker import BotWorker

            worker = BotWorker(emulator_name, adb_port)
            success = worker.process_account()

            duration = time.time() - start_time

            return {
                'success': success,
                'duration': duration,
                'error': None if success else 'Обработка завершилась с ошибками'
            }

        except Exception as e:
            duration = time.time() - start_time
            return {
                'success': False,
                'duration': duration,
                'error': str(e)
            }

    def run_all_enabled(self, batch_size=3, batch_delay=60, profile_filter=None):
        """
        Запуск всех включённых эмуляторов батчами

        Args:
            batch_size (int): Размер батча
            batch_delay (int): Пауза между батчами в секундах
            profile_filter (str, optional): Фильтр по профилю

        Returns:
            dict: Общие результаты выполнения
        """
        try:
            logger.info("=== Запуск всех включённых эмуляторов ===")

            # Автосканирование перед запуском
            if not self.auto_scan_emulators():
                logger.error("Не удалось выполнить автосканирование эмуляторов")
                return {'success': False, 'message': 'Ошибка автосканирования'}

            # Получаем список включённых эмуляторов
            enabled_emulators = self.discovery.get_enabled_emulators(
                profile_filter=profile_filter,
                running_only=False  # Обрабатываем все включённые, не только запущенные
            )

            if not enabled_emulators:
                message = f"Нет включённых эмуляторов" + (f" с профилем '{profile_filter}'" if profile_filter else "")
                logger.warning(message)
                return {'success': True, 'message': message, 'total_processed': 0}

            logger.info(f"Найдено включённых эмуляторов: {len(enabled_emulators)}")
            if profile_filter:
                logger.info(f"Фильтр по профилю: {profile_filter}")

            # Разбиваем на батчи
            batches = [enabled_emulators[i:i + batch_size] for i in range(0, len(enabled_emulators), batch_size)]

            logger.info(f"Разбито на {len(batches)} батчей по {batch_size} эмуляторов")

            # Общие результаты
            total_results = {
                'success': True,
                'total_processed': 0,
                'total_failed': 0,
                'batches': []
            }

            # Выполняем батчи
            for batch_num, batch in enumerate(batches, 1):
                logger.info(f"\n--- Батч {batch_num}/{len(batches)} ({len(batch)} эмуляторов) ---")

                # Выполняем батч
                batch_results = self.run_batch(batch)

                total_results['total_processed'] += batch_results['processed']
                total_results['total_failed'] += batch_results['failed']
                total_results['batches'].append(batch_results)

                # Пауза между батчами (кроме последнего)
                if batch_num < len(batches):
                    logger.info(f"Пауза {batch_delay} секунд перед следующим батчем...")
                    time.sleep(batch_delay)

            # Итоговая статистика
            total_emulators = total_results['total_processed'] + total_results['total_failed']
            success_rate = (total_results['total_processed'] / total_emulators * 100) if total_emulators > 0 else 0

            logger.info(f"\n=== ИТОГИ ВЫПОЛНЕНИЯ ===")
            logger.info(f"Всего эмуляторов: {total_emulators}")
            logger.info(f"Успешно обработано: {total_results['total_processed']}")
            logger.info(f"Ошибок: {total_results['total_failed']}")
            logger.info(f"Процент успеха: {success_rate:.1f}%")

            return total_results

        except Exception as e:
            logger.error(f"Ошибка запуска всех эмуляторов: {e}")
            return {'success': False, 'message': f'Ошибка: {str(e)}'}


# ===== CLI КОМАНДЫ ЧЕРЕЗ CLICK =====

@click.group()
@click.option('--debug', is_flag=True, help='Включить отладочный режим')
def cli(debug):
    """Beast Lord Bot Orchestrator - управление эмуляторами и запуск ботов"""
    if debug:
        logger.add(sys.stdout, level="DEBUG")


@cli.command()
@click.option('--force', is_flag=True, help='Принудительное пересканирование')
def scan(force):
    """Сканировать эмуляторы LDPlayer"""
    try:
        click.echo("🔍 Сканирование эмуляторов...")

        discovery = EmulatorDiscovery()

        if force:
            # Принудительное полное сканирование
            result = discovery.discover_and_save()
        else:
            # Умное сканирование (проверяет таймауты)
            orchestrator = Orchestrator()
            success = orchestrator.auto_scan_emulators()
            result = {'success': success}

        if result['success']:
            click.echo("✅ Сканирование завершено успешно")

            # Показываем результаты
            summary = discovery.get_summary()
            click.echo(f"\n📊 Сводка:")
            click.echo(f"  • Всего эмуляторов: {summary['total']}")
            click.echo(f"  • Запущено: {summary['running']}")
            click.echo(f"  • Включено: {summary['enabled']}")
            click.echo(f"  • С ADB портами: {summary['with_adb_ports']}")
            click.echo(f"  • Путь LDPlayer: {summary['ldplayer_path']}")
        else:
            click.echo("❌ Ошибка сканирования", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"❌ Ошибка: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--enabled-only', is_flag=True, help='Показать только включённые эмуляторы')
@click.option('--profile', help='Фильтр по профилю (rushing, developing, farming, dormant)')
@click.option('--pattern', help='Фильтр по паттерну имени (например, "сервер 333-*")')
def list(enabled_only, profile, pattern):
    """Показать список эмуляторов"""
    try:
        discovery = EmulatorDiscovery()
        discovery.load_config()

        # Применяем фильтры
        if pattern or profile or enabled_only:
            filtered = discovery.filter_emulators(
                name_pattern=pattern,
                profile=profile,
                enabled=True if enabled_only else None
            )

            click.echo(f"\n📋 Эмуляторы (фильтры применены):")
            if pattern:
                click.echo(f"  • Паттерн: {pattern}")
            if profile:
                click.echo(f"  • Профиль: {profile}")
            if enabled_only:
                click.echo(f"  • Только включённые")

            discovery.emulators = filtered
        else:
            click.echo("\n📋 Все эмуляторы:")

        # Показываем таблицу
        if discovery.emulators:
            discovery.print_emulators_table(show_disabled=not enabled_only)
        else:
            click.echo("Эмуляторы не найдены")

    except Exception as e:
        click.echo(f"❌ Ошибка: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('name_or_pattern')
def enable(name_or_pattern):
    """Включить эмулятор(ы) по имени или паттерну"""
    try:
        discovery = EmulatorDiscovery()
        discovery.load_config()

        enabled_count = discovery.enable_emulator(name_or_pattern)

        if enabled_count > 0:
            discovery.save_config()
            click.echo(f"✅ Включено эмуляторов: {enabled_count}")
        else:
            click.echo(f"⚠️ Не найдено эмуляторов по паттерну: {name_or_pattern}")

    except Exception as e:
        click.echo(f"❌ Ошибка: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('name_or_pattern')
def disable(name_or_pattern):
    """Выключить эмулятор(ы) по имени или паттерну"""
    try:
        discovery = EmulatorDiscovery()
        discovery.load_config()

        disabled_count = discovery.disable_emulator(name_or_pattern)

        if disabled_count > 0:
            discovery.save_config()
            click.echo(f"✅ Выключено эмуляторов: {disabled_count}")
        else:
            click.echo(f"⚠️ Не найдено эмуляторов по паттерну: {name_or_pattern}")

    except Exception as e:
        click.echo(f"❌ Ошибка: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('name_or_pattern')
@click.argument('profile', type=click.Choice(['rushing', 'developing', 'farming', 'dormant']))
def set_profile(name_or_pattern, profile):
    """Установить профиль для эмулятора(ов)"""
    try:
        discovery = EmulatorDiscovery()
        discovery.load_config()

        updated_count = discovery.set_emulator_profile(name_or_pattern, profile)

        if updated_count > 0:
            discovery.save_config()
            click.echo(f"✅ Обновлено профилей: {updated_count} -> {profile}")
        else:
            click.echo(f"⚠️ Не найдено эмуляторов по паттерну: {name_or_pattern}")

    except Exception as e:
        click.echo(f"❌ Ошибка: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--profile', help='Запустить только эмуляторы с определённым профилем')
@click.option('--pattern', help='Запустить эмуляторы по паттерну имени')
@click.option('--batch-size', default=3, help='Размер батча (по умолчанию: 3)')
@click.option('--batch-delay', default=60, help='Пауза между батчами в секундах (по умолчанию: 60)')
@click.option('--max-workers', default=3, help='Максимум параллельных процессов (по умолчанию: 3)')
def start(profile, pattern, batch_size, batch_delay, max_workers):
    """Запустить обработку эмуляторов"""
    try:
        click.echo("🚀 Запуск Beast Lord Bot Orchestrator...")

        # Создаём оркестратор
        orchestrator = Orchestrator(max_workers=max_workers)

        # Если указан паттерн, применяем его как фильтр
        if pattern:
            click.echo(f"🎯 Фильтр по паттерну: {pattern}")
            # Загружаем конфигурацию и применяем фильтр
            orchestrator.discovery.load_config()
            filtered = orchestrator.discovery.filter_emulators(name_pattern=pattern)

            if not filtered:
                click.echo(f"⚠️ Не найдено эмуляторов по паттерну: {pattern}")
                return

            # Временно заменяем список эмуляторов на отфильтрованный
            original_emulators = orchestrator.discovery.emulators
            orchestrator.discovery.emulators = filtered

        # Запускаем обработку
        results = orchestrator.run_all_enabled(
            batch_size=batch_size,
            batch_delay=batch_delay,
            profile_filter=profile
        )

        # Восстанавливаем оригинальный список
        if pattern:
            orchestrator.discovery.emulators = original_emulators

        if results['success']:
            total = results['total_processed'] + results['total_failed']
            click.echo(f"\n🎉 Обработка завершена!")
            click.echo(f"  • Всего: {total}")
            click.echo(f"  • Успешно: {results['total_processed']}")
            click.echo(f"  • Ошибок: {results['total_failed']}")

            if results['total_failed'] > 0:
                sys.exit(1)  # Код ошибки если были проблемы
        else:
            click.echo(f"❌ Ошибка: {results.get('message', 'Неизвестная ошибка')}", err=True)
            sys.exit(1)

    except KeyboardInterrupt:
        click.echo("\n⏹️ Остановлено пользователем")
        sys.exit(130)
    except Exception as e:
        click.echo(f"❌ Ошибка: {e}", err=True)
        sys.exit(1)


@cli.command()
def status():
    """Показать статус эмуляторов и системы"""
    try:
        discovery = EmulatorDiscovery()
        discovery.load_config()

        summary = discovery.get_summary()

        click.echo("\n📊 Статус системы Beast Lord Bot:")
        click.echo(f"  🔧 LDPlayer: {summary['ldplayer_path'] or 'не найден'}")
        click.echo(f"  📅 Последнее сканирование: {summary['last_scan'] or 'никогда'}")
        click.echo(f"  📦 Всего эмуляторов: {summary['total']}")
        click.echo(f"  ▶️ Запущено: {summary['running']}")
        click.echo(f"  ✅ Включено: {summary['enabled']}")
        click.echo(f"  🔌 С ADB портами: {summary['with_adb_ports']}")

        # Показываем краткую таблицу включённых эмуляторов
        enabled = discovery.get_enabled_emulators()
        if enabled:
            click.echo(f"\n📋 Включённые эмуляторы ({len(enabled)}):")
            for emu in enabled[:10]:  # Показываем первые 10
                status_icon = "▶️" if emu.get('is_running') else "⏸️"
                port = emu.get('adb_port', 'N/A')
                profile = emu.get('profile', 'N/A')
                click.echo(f"  {status_icon} {emu['name']} (порт: {port}, профиль: {profile})")

            if len(enabled) > 10:
                click.echo(f"  ... и ещё {len(enabled) - 10} эмуляторов")
        else:
            click.echo("\n⚠️ Нет включённых эмуляторов")

    except Exception as e:
        click.echo(f"❌ Ошибка: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    # Если запускается напрямую, используем CLI
    cli()