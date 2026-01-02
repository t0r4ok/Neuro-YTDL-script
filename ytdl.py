import os
import sys
import re
import shutil
import yt_dlp

# ==============================
# 🔧 НАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ
# ==============================
# Скачиваем в папку "Загрузки/YTDL" в домашней директории пользователя
DOWNLOAD_PATH = os.path.join(os.path.expanduser("~"), "Downloads", "YTDL")
USER_AGENT = ""  # Оставь пустым, чтобы библиотека использовала стандартный (рекомендуется)
SHOW_NO_AUDIO_VARIANTS = False  # Показывать ли варианты "(No Audio)"
# ==============================


def validate_url(url):
    """Простая проверка формата ссылки, основную валидацию делает yt-dlp"""
    if not url:
        return False
    # Расширенный regex для поддержки youtube.com, youtu.be, shorts и т.д.
    youtube_regex = re.compile(
        r'^(https?://)?(www\.|m\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+$'
    )
    return bool(youtube_regex.match(url))


def has_ffmpeg():
    """Проверяет наличие FFmpeg в системе"""
    return shutil.which("ffmpeg") is not None


def get_video_info(url):
    """Получает метаданные видео"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'ignoreerrors': True,  # Не падать при ошибке плейлиста, просто пропускать
        'extractor_retries': 3,
    }
    if USER_AGENT:
        ydl_opts['http_headers'] = {'User-Agent': USER_AGENT}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            return ydl.extract_info(url, download=False)
        except Exception:
            return None


def get_available_qualities(info, show_no_audio=False):
    """
    Анализирует форматы и возвращает словарь: "Название качества" -> "Строка селектора"
    """
    from collections import OrderedDict, defaultdict

    qualities = OrderedDict()
    formats = info.get("formats", [])
    
    # Словарь: высота -> {есть ли видео, есть ли 60fps}
    heights_data = defaultdict(lambda: {"has_video": False, "has_60fps": False})

    for f in formats:
        # Фильтруем форматы: должны быть vcodec != none и height != none
        if f.get("vcodec") != "none" and f.get("height"):
            h = f.get("height")
            heights_data[h]["has_video"] = True
            if f.get("fps") and f.get("fps") >= 60:
                heights_data[h]["has_60fps"] = True

    # Сортируем высоты от большего к меньшему
    sorted_heights = sorted(heights_data.keys(), reverse=True)

    for h in sorted_heights:
        # Вариант 60 FPS
        if heights_data[h]["has_60fps"]:
            label = f"{h}p 60fps"
            # Строгий выбор: видео этой высоты с fps>=60 + лучшее аудио
            selector = f"bestvideo[height={h}][fps>=60]+bestaudio/bestvideo[height={h}][fps>=60]"
            qualities[label] = selector

        # Обычный вариант для этой высоты
        label = f"{h}p"
        # Выбираем видео этой высоты + лучшее аудио. 
        # Если аудио нет (merge fail), fallback на просто видео этой высоты (но yt-dlp обычно качает 2 файла)
        selector = f"bestvideo[height={h}]+bestaudio/bestvideo[height={h}]"
        qualities[label] = selector

        # Вариант без звука (если включено в настройках)
        if show_no_audio:
            label_na = f"{h}p (No Audio)"
            selector_na = f"bestvideo[height={h}]"
            qualities[label_na] = selector_na

    # Добавляем общие варианты
    qualities["Лучшее доступное (Auto)"] = "bestvideo+bestaudio/best"
    qualities["Только Аудио (MP3)"] = "bestaudio/best"

    return qualities


def choose_quality(qualities):
    """Интерактивное меню выбора качества"""
    print("\n📋 Доступные варианты:\n" + "-" * 30)
    keys = list(qualities.keys())
    for i, label in enumerate(keys, start=1):
        print(f"{i:2d}) {label}")
    print("-" * 30)
    
    while True:
        try:
            choice_input = input(f"👉 Выберите номер (1-{len(keys)}): ").strip()
            if not choice_input: continue
            
            choice = int(choice_input)
            if 1 <= choice <= len(keys):
                key = keys[choice - 1]
                return qualities[key], key
            else:
                print("⚠️ Число вне диапазона.")
        except ValueError:
            print("⚠️ Введите целое число.")
        except KeyboardInterrupt:
            print("\nВыход.")
            sys.exit(0)


def progress_hook(d):
    """Хук для отображения прогресса"""
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '').strip()
        speed = d.get('_speed_str', '').strip()
        eta = d.get('_eta_str', '').strip()
        # \r возвращает каретку в начало строки, чтобы обновлять одну строку
        sys.stdout.write(f"\r⏳ Загрузка: {percent} | Скорость: {speed} | ETA: {eta}   ")
        sys.stdout.flush()
    elif d['status'] == 'finished':
        sys.stdout.write("\n🔄 Обработка / Склейка файлов...\n")


def download_video(url, format_selector, quality_label):
    is_audio_only = format_selector.startswith("bestaudio")
    
    # Опции для yt-dlp
    ydl_opts = {
        'format': format_selector,
        # Сохраняем в указанную папку, имя файла очищается от спецсимволов
        'paths': {'home': DOWNLOAD_PATH},
        'outtmpl': '%(title)s.%(ext)s',
        
        # Санитизация имен файлов (чтобы Windows не ругалась на "?" или "|")
        'restrictfilenames': True,  # Убирает пробелы и не-ASCII (опционально)
        'windowsfilenames': True,   # Убирает запрещенные в Windows символы
        
        'noplaylist': True,
        'ignoreerrors': False,
        'no_warnings': True,
        'progress_hooks': [progress_hook],
        
        # Настройки сети
        'retries': 10,
        'fragment_retries': 10,
    }

    if USER_AGENT:
        ydl_opts['http_headers'] = {'User-Agent': USER_AGENT}

    # Настройки для АУДИО
    if is_audio_only:
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    # Настройки для ВИДЕО (склейка в mp4)
    else:
        ydl_opts['merge_output_format'] = 'mp4'

    # Проверка FFmpeg перед загрузкой "сложных" форматов
    # Если мы качаем bestvideo+bestaudio, нам нужен FFmpeg для склейки
    need_ffmpeg = (not is_audio_only) and ('+bestaudio' in format_selector)
    ffmpeg_available = has_ffmpeg()

    if need_ffmpeg and not ffmpeg_available:
        print("\n⚠️  ВНИМАНИЕ: FFmpeg не найден!")
        print("   Видео будет скачано двумя файлами: видео (без звука) и аудио отдельно.")
        print("   Установите FFmpeg и добавьте его в PATH, чтобы получать один MP4 файл.")
        # Убираем требование склейки, чтобы не вызывать ошибку
        if 'merge_output_format' in ydl_opts:
            del ydl_opts['merge_output_format']

    try:
        print(f"\n🚀 Начинаем загрузку: {quality_label}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print(f"\n✅ Успешно сохранено в: {DOWNLOAD_PATH}")
        return True
    except Exception as e:
        print(f"\n❌ Ошибка при загрузке: {e}")
        return False


def main():
    # Очистка консоли (кроссплатформенная)
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("=" * 60)
    print("🎥 YouTube Downloader (Safe Fix)")
    print("=" * 60)

    # Проверка создания папки
    try:
        os.makedirs(DOWNLOAD_PATH, exist_ok=True)
    except OSError as e:
        print(f"❌ Ошибка создания папки {DOWNLOAD_PATH}: {e}")
        return

    print(f"📂 Папка: {DOWNLOAD_PATH}")
    if not has_ffmpeg():
        print("⚠️  FFmpeg не обнаружен. Склейка видео+аудио невозможна (будут раздельные файлы).")
    else:
        print("✅ FFmpeg обнаружен. Видео и аудио будут склеены.")

    while True:
        url = input("\n🔗 Вставьте ссылку (или 'q' для выхода): ").strip()
        
        if not url: continue
        if url.lower() in ['q', 'quit', 'exit', 'выход']: break
        
        if not validate_url(url):
            print("❌ Ссылка не похожа на YouTube.")
            continue

        print("\n🔎 Получаем данные о видео...")
        try:
            info = get_video_info(url)
            if not info:
                print("❌ Видео не найдено или недоступно.")
                continue
            
            title = info.get('title', 'Без названия')
            author = info.get('uploader', 'Неизвестно')
            duration = info.get('duration_string', 'N/A')
            print(f"🎬 {title}")
            print(f"👤 {author} | ⏱ {duration}")

            qualities = get_available_qualities(info, show_no_audio=SHOW_NO_AUDIO_VARIANTS)
            if not qualities:
                print("❌ Не найдено подходящих форматов для скачивания.")
                continue

            selector, label = choose_quality(qualities)
            download_video(url, selector, label)

        except Exception as e:
            print(f"❌ Непредвиденная ошибка: {e}")
            import traceback
            traceback.print_exc()

        print("-" * 60)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Программа остановлена пользователем.")