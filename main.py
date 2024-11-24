import asyncio
import contextlib
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import List

import aiosqlite
import keyboard
import pytesseract
import unicodedata
from PIL import Image, ImageGrab
from rapidfuzz.distance import DamerauLevenshtein

from modules.databases import create_database
from modules.logs import add_logging_level

with contextlib.redirect_stdout(None):
    import pygame

# misc configs
database_name = 'fe2_companion_data.sqlite'
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# strings
play_strings = ["get ready: ", "rescue"]
stop_strings = ["round", "join", "next", "drowned"]

# poggers
add_logging_level('SUCCESS', 21)
add_logging_level('MATCH', 22)
add_logging_level('BYE', 23)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler('latest.log', mode='w')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter('[%(asctime)s.%(msecs)d] [%(levelname)s] (%(filename)s:%(lineno)d) %(message)s',
                      '%m/%d/%Y %H:%M:%S'
                      ))


class SpecialFormatter(logging.Formatter):
    # backgrounds
    black_background = '\033[48;2;12;12;12m'
    red_background = '\033[48;2;197;15;31m'
    green_background = '\033[48;2;19;161;14m'
    yellow_background = '\033[48;2;193;156;0m'
    blue_background = '\033[48;2;0;55;218m'
    magenta_background = '\033[48;2;136;23;152m'
    cyan_background = '\033[48;2;58;150;221m'
    white_background = '\033[48;2;204;204;204m'

    # text
    red = '\033[38;2;231;72;86m'
    green = '\033[38;2;22;198;12m'
    yellow = '\033[38;2;249;241;165m'
    blue = '\033[38;2;59;120;255m'
    magenta = '\033[38;2;180;0;158m'
    cyan = '\033[38;2;97;214;214m'
    grey = '\033[38;2;118;118;118m'
    white = '\033[38;2;242;242;242m'
    black = '\033[38;2;12;12;12m'

    bold = '\033[1m'
    reset = "\033[0m"

    # strings
    time_string = "[%(asctime)s.%(msecs)d]"
    level_string = "[%(levelname)s]"
    message_string = "%(message)s"

    # format
    date_format = '%m/%d/%Y %H:%M:%S'
    FORMATS = {
        logging.DEBUG: f"{blue_background}{bold}{time_string}{reset} {grey}{bold}{level_string}{reset} {grey}{message_string}{reset}",
        logging.SUCCESS: f"{green_background}{bold}{time_string}{reset} {green}{bold}{level_string}{reset} {message_string}",
        logging.MATCH: f"{magenta_background}{bold}{time_string}{reset} {magenta}{bold}{level_string}{reset} {message_string}",
        logging.BYE: f"{cyan_background}{bold}{time_string}{reset} {cyan}{bold}{level_string}{reset} {message_string}",
        logging.INFO: f"{blue_background}{bold}{time_string}{reset} {grey}{bold}{level_string}{reset} {message_string}",
        logging.WARNING: f"{yellow_background}{bold}{time_string}{reset} {yellow}{bold}{level_string}{reset} {message_string}",
        logging.ERROR: f"{red_background}{bold}{time_string}{reset} {red}{bold}{level_string}{reset} {message_string}",
        logging.CRITICAL: f"{red_background}{bold}{time_string}{reset} {red}{bold}{level_string}{reset} {red}{message_string}{reset}"
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, self.date_format)
        return formatter.format(record)


special_formatter = SpecialFormatter()
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(special_formatter)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# best templates
template_best_attempt = {"attempt": 0, "time": 0}
template_best_completion = {"attempt": 0, "time": 999999}


async def slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '_', value).strip('-_')


async def find_select_music():
    music_files = list(
        reversed(
            list(
                p.resolve()
                for p in Path("music").glob("**/*")
                if p.suffix in {'.mp3', '.ogg', '.wav'}
            )
        )
    )
    if len(music_files) == 0:
        logger.warning("No music files detected in music folder!")
        return None
    elif len(music_files) == 1:
        return music_files[0].__str__().replace(music_files[0].cwd().__str__(), "")[1:].replace("\\", "/")
    else:
        displayable_paths = []
        for path in music_files:
            displayable_paths.append(path.__str__().replace(music_files[0].cwd().__str__(), "")[1:].replace("\\", "/"))

        while True:
            logger.info(f"{len(displayable_paths)} Songs Found! "
                        f"Type the number for the song you want this map to play, or simply press enter for no music.\n"
                        # f"{'=' * os.get_terminal_size().columns}"
                        f"")
            for i, dpath in enumerate(displayable_paths, 1):
                print(f"{i}. {dpath}")

            try:
                selection = input("\nSong Number (or enter): ")
                if len(selection) == 0:
                    return None
                return displayable_paths[int(selection) - 1]
            except ValueError:
                logger.error("Invalid selection!")


async def choose_volume():
    while True:
        try:
            volume = input("Choose volume (0-100, default: 35): ")
            if len(volume) == 0:
                return 0.35

            if 0 <= int(volume) <= 100:
                return int(volume) / 100
        except ValueError:
            return


async def combine_images(images: List[ImageGrab]):
    widths, heights = zip(*[img.size for img in images])
    horizontal_padding = 600
    vertical_padding = 600
    image_width = max(widths) + horizontal_padding
    image_height = sum(heights) + vertical_padding
    new_img = Image.new('RGB', (image_width, image_height))

    x_offset = int(horizontal_padding * 0.5)
    y_offset = int(vertical_padding * 0.5)
    for img in images:
        new_img.paste(img, (x_offset, y_offset))
        y_offset += img.height

    return new_img


async def submit_new_map():
    new_map = input("Enter name of map (enter to cancel): ")
    if len(new_map) == 0:
        return
    song = await find_select_music()
    best_attempt = template_best_attempt.copy()
    best_completion = template_best_completion.copy()
    cursor = await database.execute('INSERT INTO maps VALUES(?, ?, ?, ?, ?, ?)',
                                    [new_map, song, 0, 0, json.dumps(best_attempt), json.dumps(best_completion)])
    await database.commit()
    return {'rowid': cursor.lastrowid, 'name': new_map, 'song': song, 'total_attempts': 0, 'total_completions': 0,
            'best_attempt': best_attempt,
            'best_completion': best_completion}


async def query_maps():
    database.row_factory = aiosqlite.Row
    async with database.execute('SELECT name FROM maps') as cursor:
        database.row_factory = None
        result = await cursor.fetchall()
        maps = []
        for data in result:
            maps.append(data[0])
        return maps


async def select_map_from_list(map_list: List[dict]):
    while True:
        logger.info(f"{len(map_list)} Maps Stored! "
                    f"Type the ID of the map you're playing on. For a new map, hit enter.\n")
        for i, entry in enumerate(map_list, 1):
            print(f"{i}. {entry['name']}")

        try:
            selection = input("\nMap ID (or enter): ")
            if len(selection) == 0:
                await submit_new_map()
                return
            return map_list[int(selection) - 1]
        except (ValueError, IndexError):
            logger.error("Invalid selection!")


async def query_map_table():
    async with database.execute('SELECT rowid, * FROM maps') as cursor:
        data = await cursor.fetchall()
        column_names = [description[0] for description in cursor.description]
        map_data = []
        for row in data:
            row_dict = dict(zip(column_names, row))
            map_data.append(row_dict)
        return map_data


async def select_map():
    map_list = await query_map_table()
    if len(map_list) == 0:
        logger.info("No maps found! Adding first map...\n")
        await submit_new_map()
        map_list = await query_map_table()
    while True:
        result = await select_map_from_list(map_list)
        if result:
            return result
        else:
            map_list = await query_map_table()


async def compare_run(compare_type: str, run_attempt: int, run_time: float, best_run: dict):
    new_best = None
    if compare_type == 'attempt':
        if run_time > best_run['time']:
            new_best = {"attempt": run_attempt, "time": run_time}
    elif compare_type == 'completion':
        if run_time < best_run['time']:
            new_best = {"attempt": run_attempt, "time": run_time}
    return new_best


async def check_distance(target_word: str, word_list: List[str], max_distance: int):
    for entry in word_list:
        if '..' in target_word or 'get ready..' in target_word:
            continue
        distance = DamerauLevenshtein.distance(target_word, entry)
        # logger.debug(f"{entry} is {distance} from {target_word}")
        if distance <= max_distance:
            return True


async def main():
    git_hash = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()
    logger.info(f"FE2 Companion by pinheadtf2 [{git_hash}]")

    Path('images/completions').mkdir(exist_ok=True)
    Path('music').mkdir(exist_ok=True)
    if not Path(database_name).exists():
        await create_database(database_name)
        logger.info(f"Created database {database_name}")
    global database
    database = await aiosqlite.connect(database_name)

    selected_map = await select_map()
    selected_map['best_attempt'] = json.loads(selected_map['best_attempt'].replace("\'", "\""))  # just in case
    selected_map['best_completion'] = json.loads(selected_map['best_completion'].replace("\'", "\""))

    pygame.mixer.init()
    volume = 0
    if not selected_map['song']:
        pygame.mixer.music.load('music/Hyperspace - V2 - luxTypes.mp3')
        pygame.mixer.music.set_volume(volume)
    else:
        play_song_query = input(f"Play map's song {selected_map['song']} (Y/n)?")
        if len(play_song_query) == 0 or play_song_query[0].lower() == 'y':
            pygame.mixer.music.load(selected_map['song'])
            volume = await choose_volume()
            pygame.mixer.music.set_volume(volume)
    logger.info(f"Initialized music player with song {selected_map['song']} at volume {volume}")

    # this is where the session is officially declared as 'started'
    session_start = int(time.time())
    session_best_attempt = template_best_attempt.copy()
    session_best_completion = template_best_completion.copy()
    cursor = await database.execute('INSERT INTO sessions VALUES(?, ?, ?, ?, ?, ?, ?)',
                                    [selected_map['name'], session_start, None, 0, 0, str(session_best_attempt),
                                     str(session_best_completion)])
    run_id = cursor.lastrowid
    await database.commit()

    logger.info(f"Started session {run_id} with map {selected_map['name']}\n"
                f"{" " * 33}Map Totals: {selected_map['total_attempts']} attempts, {selected_map['total_completions']} completions\n"
                f"{" " * 33}Map Best Attempt: {selected_map['best_attempt']['time']} seconds (Att. {selected_map['best_attempt']['attempt']})\n"
                f"{" " * 33}Map Best Completion: {selected_map['best_completion']['time']} seconds (Att. {selected_map['best_completion']['attempt']})")

    running = False
    attempts = 0
    completions = 0
    run_start = None
    while True:
        perf_start = time.perf_counter()
        image_ready = ImageGrab.grab(bbox=(320, 850, 1000, 1000))
        image_notifications = ImageGrab.grab(bbox=(600, 0, 1300, 300))
        image_rescue = ImageGrab.grab(bbox=(700, 870, 1250, 990))
        # image_share = ImageGrab.grab(bbox=(150, 0, 550, 50))

        screenshot = await combine_images([image_ready, image_notifications, image_rescue])
        text = pytesseract.image_to_string(screenshot, lang='eng').strip().replace("\n", " ").lower()
        # screenshot_name = f'images/image_{time.time():.3f}.png'
        # screenshot.save(screenshot_name)
        # logger.debug(f"Saved image {screenshot_name} | Text: {text}")

        if (any((match := partial) in text for partial in play_strings) or await check_distance(text[:12], ["get ready: 3", "get ready: 2", "get ready: 1"], 3)) and not running:
            running = True
            if 'get ready:' in text:
                logger.info(f"Matched, pausing for get ready: ")
                await asyncio.sleep(1.2)

            pygame.mixer.music.play()
            run_start = time.time()
            attempts += 1
            if match not in text:
                match = "[Lev. Dist. Match]"
            logger.match(f"Attempt {attempts} of {selected_map['name']}\n"
                         f"{" " * 34}Matches: {match} | All Text: {text}")
            continue
        elif (any((match := partial) in text for partial in stop_strings) or keyboard.is_pressed('g')) and running:
            running = False
            pygame.mixer.music.stop()
            run_time = round(time.time() - run_start, 3)
            total_attempts = selected_map['total_attempts'] + attempts

            session_attempt_comparison = await compare_run('attempt', attempts, run_time, session_best_attempt)
            if session_attempt_comparison:
                map_attempt_comparison = await compare_run('attempt', total_attempts, run_time,
                                                           selected_map['best_attempt'])
                if map_attempt_comparison:
                    session_best_attempt = map_attempt_comparison
                    selected_map['best_attempt'] = session_best_attempt
                    logger.match(f"Stopped music after {run_time}\n"
                                 f"{" " * 34}This is a new map best attempt! | Attempt #{attempts} lasted for {run_time} seconds\n"
                                 f"{" " * 34}Matches: {match} | All Text: {text}")
                    await database.execute('UPDATE sessions SET best_attempt = ? WHERE rowid = ?',
                                           [json.dumps(session_best_attempt), run_id])
                    await database.execute('UPDATE maps SET best_attempt = ? WHERE rowid = ?',
                                           [json.dumps(session_best_attempt), selected_map['rowid']])
                else:
                    session_best_attempt = session_attempt_comparison
                    logger.match(f"Stopped music after {run_time}\n"
                                 f"{" " * 34}This is a new session best attempt! | Attempt #{total_attempts} lasted for {run_time} seconds\n"
                                 f"{" " * 34}Map Best Attempt: {selected_map['best_attempt']['time']} seconds (S. Att. {selected_map['best_attempt']['attempt']})\n"
                                 f"{" " * 34}Matches: {match} | All Text: {text}")
                    await database.execute('UPDATE sessions SET best_attempt = ? WHERE rowid = ?',
                                           [json.dumps(session_best_attempt), run_id])
            else:
                logger.match(f"Stopped music after {run_time}\n"
                             f"{" " * 34}Map Best Attempt: {selected_map['best_attempt']['time']} seconds (Att. {selected_map['best_attempt']['attempt']})\n"
                             f"{" " * 34}Session Best Attempt: {session_best_attempt['time']} seconds (S. Att. {session_best_attempt['attempt']})\n"
                             f"{" " * 34}All Text: {text} | Matches: {match}")

            await database.execute('UPDATE sessions SET total_attempts = ? WHERE rowid = ?',
                                   [attempts, run_id])
            await database.execute('UPDATE maps SET total_attempts = ? WHERE rowid = ?',
                                   [total_attempts, selected_map['rowid']])
            await database.commit()
        elif (keyboard.is_pressed('c') or re.search(r"(\d+)/(\d+) escaped", text)) and running:
            run_time = round(time.time() - run_start, 3)
            completions += 1
            total_attempts = selected_map['total_attempts'] + attempts
            total_completions = selected_map['total_completions'] + completions
            ImageGrab.grab().save(
                f'images/completions/{await slugify(selected_map["name"])}_{int(time.time())}_completion_{total_completions}.png',
                "PNG")

            session_completion_comparison = await compare_run('completion', total_attempts, run_time,
                                                              session_best_completion)
            if session_completion_comparison:
                map_completion_comparison = await compare_run('completion', total_attempts, run_time,
                                                              selected_map['best_completion'])
                if map_completion_comparison:
                    session_best_completion = map_completion_comparison
                    logger.success(
                        f"Escaped map {selected_map['name']} after {attempts} attempts with a time of {run_time} seconds\n"
                        f"{" " * 37}This is your new map record! | Completions: {selected_map['total_completions'] + completions} ({completions} today)\n"
                        f"{" " * 37}All Text: {text}")
                    await database.execute('UPDATE sessions SET best_completion = ? WHERE rowid = ?',
                                           [json.dumps(session_best_completion), run_id])
                    await database.execute('UPDATE maps SET best_completion = ? WHERE rowid = ?',
                                           [json.dumps(session_best_completion), selected_map['rowid']])
                else:
                    session_best_completion = session_completion_comparison
                    logger.success(
                        f"Escaped map {selected_map['name']} after {attempts} attempts with a time of {run_time} seconds\n"
                        f"{" " * 37}This is a new session record! | Completions: {selected_map['total_completions'] + completions} ({completions} today)\n"
                        f"{" " * 37}Map Best Completion: {selected_map['best_completion']['time']} seconds (Att. {selected_map['best_completion']['attempt']})\n"
                        f"{" " * 37}All Text: {text}")
                    await database.execute('UPDATE sessions SET best_completion = ? WHERE rowid = ?',
                                           [json.dumps(session_best_completion), run_id])
            else:
                logger.success(
                    f"Escaped map {selected_map['name']} after {attempts} attempts with a time of {run_time} seconds\n"
                    f"{" " * 37}Map Best Completion: {selected_map['best_completion']['time']} seconds (Att. {selected_map['best_completion']['attempt']})\n"
                    f"{" " * 37}Session Best Completion: {session_best_completion['time']} seconds (Att. {session_best_completion['attempt']})\n"
                    f"{" " * 37}All Text: {text}")

            await database.execute('UPDATE sessions SET total_attempts = ?, total_completions = ? WHERE rowid = ?',
                                   [attempts, completions, run_id])
            await database.execute('UPDATE maps SET total_attempts = ?, total_completions = ? WHERE rowid = ?',
                                   [total_attempts,
                                    total_completions, selected_map['rowid']])
            await database.commit()
            break
        elif keyboard.is_pressed('k') or keyboard.is_pressed('m'):
            pygame.mixer.music.stop()
            break
        perf_end = time.perf_counter()
        logger.debug(f"{perf_end - perf_start:.5f} seconds | Text: {text}")

    while pygame.mixer.music.get_busy():
        if keyboard.is_pressed('k'):
            pygame.mixer.music.stop()
        await asyncio.sleep(1)

    session_end = int(time.time())
    await database.execute('UPDATE sessions SET session_end = ? WHERE rowid = ?',
                           [session_end, run_id])
    await database.close()
    logger.info(f'Session ended! Duration: {session_end - session_start} seconds')

    if keyboard.is_pressed('m'):
        return await main()

    logger.bye("See ya!")
    return


if __name__ == '__main__':
    asyncio.run(main())
    exit(0)
