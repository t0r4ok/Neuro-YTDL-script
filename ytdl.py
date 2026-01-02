import os
import sys
import re
import shutil
import yt_dlp

# ==============================
# 🔧 НАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ
# ==============================
DOWNLOAD_PATH = os.path.curdir
USER_AGENT = "" 
SHOW_NO_AUDIO_VARIANTS = False  # показывать ли варианты без аудио (помечаются как "(No Audio)")
# ==============================


def validate_url(url):
    youtube_regex = re.compile(
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|shorts/|.+\?v=)?([^&=%\?]{11})'
    )
    return bool(youtube_regex.match(url))


def has_ffmpeg():
    return shutil.which("ffmpeg") is not None


def get_video_info(url):
    """Получает метаданные без загрузки"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': False,
        'extract_flat': False,
        'ignoreerrors': True,
        'extractor_retries': 5,
        'source_address': '0.0.0.0',
    }
    if USER_AGENT:
        ydl_opts['http_headers'] = {'User-Agent': USER_AGENT}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def get_available_qualities(info, show_no_audio=False):
    """
    Возвращает Ordered dict / список (label -> format_selector).
    Правила:
     - Для каждой реально доступной высоты создаём вариант video+audio:
         bestvideo[height={H}]+bestaudio/best[height={H}]
     - Если на той же высоте есть fps>=60 — добавляем метку "H 60fps"
     - Добавляем "Лучшее доступное" = bestvideo+bestaudio/best
     - Добавляем "Аудио (MP3)" = bestaudio/best
     - Если show_no_audio=True — добавляем видео-only варианты (помечены (No Audio))
    """
    from collections import OrderedDict, defaultdict

    qualities = OrderedDict()

    formats = info.get("formats") or []
    # Соберём данные по высотам: для каждой высоты — есть ли fps>=60 и есть ли вообще video formats
    heights = defaultdict(lambda: {"has_video": False, "has_60fps": False})

    for f in formats:
        # пропускаем форматы без ссылки или без видеокодека (для видео)
        if f.get("vcodec") and f.get("height"):
            h = f.get("height")
            heights[h]["has_video"] = True
            fps = f.get("fps") or 0
            if fps >= 60:
                heights[h]["has_60fps"] = True

    # Сортируем высоты по убыванию
    sorted_heights = sorted([h for h in heights.keys()], reverse=True)

    # Формируем записи: сначала fps>=60 версии (если есть), затем обычные
    for h in sorted_heights:
        if heights[h]["has_60fps"]:
            label = f"{h}p 60fps"
            selector = f"bestvideo[height={h}][fps>=60]+bestaudio/best[height={h}]"
            qualities[label] = selector

        # стандартный вариант для этой высоты
        label = f"{h}p"
        selector = f"bestvideo[height={h}]+bestaudio/best[height={h}]"
        qualities[label] = selector

        # если пользователь хочет видеть видео-only варианты — добавляем помеченный вариант
        if show_no_audio:
            no_audio_label = f"{h}p (No Audio)"
            no_audio_selector = f"bestvideo[height={h}]"
            qualities[no_audio_label] = no_audio_selector

    # fallback - лучшее доступное (yt-dlp сам выберет)
    qualities["Лучшее доступное"] = "bestvideo+bestaudio/best"

    # аудио только
    qualities["Аудио (MP3)"] = "bestaudio/best"

    return qualities


def choose_quality(qualities):
    print("\nДоступные варианты качества:\n" + "=" * 40)
    keys = list(qualities.keys())
    for i, label in enumerate(keys, start=1):
        print(f"{i:2d}) {label}")
    print("=" * 40)
    while True:
        try:
            choice = int(input(f"Выберите качество (1-{len(keys)}): ").strip())
            if 1 <= choice <= len(keys):
                key = keys[choice - 1]
                return qualities[key], key
            else:
                print("Введите число в диапазоне.")
        except ValueError:
            print("Введите корректное число.")
        except KeyboardInterrupt:
            print("\nОтмена.")
            sys.exit(0)


def progress_hook(d):
    if d.get('status') == 'downloading':
        percent = d.get('_percent_str', 'N/A')
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        print(f"\rЗагрузка: {percent} | Скорость: {speed} | ETA: {eta}", end='', flush=True)
    elif d.get('status') == 'finished':
        print(f"\n✓ Загрузка завершена: {os.path.basename(d.get('filename',''))}")


def download_video(url, format_selector, quality_label):
    """
    Всегда стараемся скачивать video+audio и склеивать в mp4.
    Если выбран "Аудио (MP3)" — конвертируем в mp3.
    Если выбран вариант (No Audio) — скачиваем видео-only (но это опционально и помечено).
    """
    is_audio_only = format_selector.strip().startswith("bestaudio")
    is_video_only = "bestvideo[" in format_selector and "+bestaudio" not in format_selector and "bestaudio" not in format_selector

    # Формат файла и опции постобработки
    if is_audio_only:
        out_ext = "mp3"
    else:
        out_ext = "mp4"

    ydl_opts = {
        'format': format_selector,
        'outtmpl': os.path.join(DOWNLOAD_PATH, '%(title)s.%(ext)s'),
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'no_warnings': False,
        'progress_hooks': [progress_hook],
        'retries': 5,
        'fragment_retries': 5,
        'http_chunk_size': 10485760,
        'source_address': '0.0.0.0',
    }

    # если нужно — добавляем User-Agent заголовок
    if USER_AGENT:
        ydl_opts['http_headers'] = {'User-Agent': USER_AGENT}

    # Если это аудио — добавляем постобработчик для конвертации в mp3
    if is_audio_only:
        # потребует ffmpeg/avconv
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        # предупреждение про ffmpeg, если потребуется склеить и он отсутствует
        if (not is_audio_only) and ('+bestaudio' in format_selector or 'bestaudio' in format_selector):
            if not has_ffmpeg():
                print("\n⚠️ Warning: ffmpeg не найден в PATH. Если его нет, yt-dlp может сохранить раздельные файлы (video + audio), но не склеит их.")
                print("   Установи ffmpeg и добавь в PATH, чтобы автоматически получать единый mp4 с вшитым звуком.")

        print(f"\nНачинаем загрузку: {quality_label}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print(f"\n✅ Готово: {quality_label}")
        return True
    except Exception as e:
        print(f"\n❌ Ошибка загрузки: {e}")
        return False


def main():
    print("=" * 60)
    print("🎥 YouTube Downloader — обязательно с аудио (по умолчанию)")
    print("=" * 60)

    os.makedirs(DOWNLOAD_PATH, exist_ok=True)
    print(f"📁 Папка для загрузок: {DOWNLOAD_PATH}")
    print("🧩 User-Agent:", USER_AGENT if USER_AGENT else "по умолчанию")
    print("⚙️  Показать варианты без аудио:", "Да" if SHOW_NO_AUDIO_VARIANTS else "Нет")

    while True:
        url = input("\n🔗 Введите ссылку на видео (или 'exit'): ").strip()
        if not url:
            print("❌ Пустая ссылка.")
            continue
        if url.lower() in ['exit', 'quit', 'выход']:
            break
        if not validate_url(url):
            print("❌ Неверная ссылка.")
            continue

        try:
            info = get_video_info(url)
            if not info:
                print("❌ Не удалось получить информацию о видео.")
                continue
            print(f"\n📹 {info.get('title', 'Без названия')} — {info.get('uploader', 'Неизвестно')}")
        except Exception as e:
            print(f"Ошибка получения информации: {e}")
            continue

        qualities = get_available_qualities(info, show_no_audio=SHOW_NO_AUDIO_VARIANTS)
        fmt, label = choose_quality(qualities)
        success = download_video(url, fmt, label)

        if not success:
            print("\n⚠️ Попробуй другой вариант качества или проверь подключение/ffmpeg.")
        if input("\nСкачать ещё? (y/n): ").lower().strip() not in ['y', 'yes', 'д', 'да']:
            break


if __name__ == '__main__':
    main()
