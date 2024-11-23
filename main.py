import asyncio
import contextlib
import logging
import subprocess
import time
from pathlib import Path
from typing import List
import json

import aiosqlite
import keyboard
import pytesseract
from PIL import Image, ImageGrab

from modules.databases import create_database
from modules.logs import add_logging_level

with contextlib.redirect_stdout(None):
    import pygame

database_name = 'fe2_companion_data.sqlite'

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
    magenta = '\033[48;2;180;0;158m'
    cyan = '\033[48;2;97;214;214m'
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
        logging.BYE: f"{cyan_background}{bold}{time_string}{reset} {cyan}{bold}{black}{level_string}{reset} {message_string}",
        logging.INFO: f"{blue_background}{bold}{time_string}{reset} {grey}{bold}{level_string}{reset} {message_string}",
        logging.WARNING: f"{yellow_background}{bold}{time_string}{reset} {yellow}{bold}{level_string}{reset} {message_string}",
        logging.ERROR: f"{red_background}{bold}{time_string}{reset} {red}{bold}{level_string}{reset} {message_string}",
        logging.CRITICAL: f"{red_background}{bold}{time_string}{reset} {red}{bold}{level_string}{reset} {red}{message_string}{reset}"
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, self.date_format)
        return formatter.format(record)


console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(SpecialFormatter())
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# configure pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# strings
play_strings = ["get ready: 1", "get ready: 2", "rescue", "100", "0:00"]
stop_strings = ["round", "join", "next", "drowned"]
escaped_strings = ["escaped"]

# best templates
template_best_attempt = {"attempt": 0, "time": 0}
template_best_completion = {"attempt": 0, "time": 999999}


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
    horizontal_padding = 300
    vertical_padding = 150
    image_width = max(widths) + horizontal_padding
    image_height = sum(heights) + vertical_padding
    new_img = Image.new('RGB', (image_width, image_height))

    x_offset = int(horizontal_padding * 0.5)
    y_offset = int(vertical_padding * 0.5)
    for img in images:
        new_img.paste(img, (x_offset, y_offset))
        y_offset += img.height

    Path('images').mkdir(exist_ok=True)
    return new_img


async def submit_new_map(database: aiosqlite.Connection):
    new_map = input("Enter name of map: ")
    if len(new_map) == 0:
        logger.error("Map name cannot be empty!")
        return await submit_new_map(database)
    song = await find_select_music()
    best_attempt = template_best_attempt.copy()
    best_completion = template_best_completion.copy()
    await database.execute('INSERT INTO maps VALUES(?, ?, ?, ?, ?, ?)',
                           [new_map, song, 0, 0, str(best_attempt), str(best_completion)])
    await database.commit()
    return {'name': new_map, 'song': song, 'total_attempts': 0, 'total_completions': 0, 'best_attempt': best_attempt,
            best_completion: best_completion}


async def query_maps(database: aiosqlite.Connection):
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
            return map_list[int(selection) - 1]
        except ValueError:
            logger.error("Invalid selection!")


async def query_map_table(database: aiosqlite.Connection):
    async with database.execute('SELECT * FROM maps') as cursor:
        column_names = [description[0] for description in cursor.description]
        map_data = []
        async for row in cursor:
            row_dict = dict(zip(column_names, row))
            map_data.append(row_dict)
        return map_data


async def select_map(database: aiosqlite.Connection):
    map_list = await query_map_table(database)
    if len(map_list) == 0:
        logger.info("No maps found! Adding first map...\n")
        return await submit_new_map(database)
    elif len(map_list) == 1:
        return map_list[0]
    else:
        return await select_map_from_list(map_list)


async def compare_run(compare_type: str, run_attempt: int, run_time: float, best_run: dict):
    new_best = None
    if compare_type == 'attempt':
        if run_time > best_run['time']:
            new_best = {"attempt": run_attempt, "time": run_time}
    elif compare_type == 'completion':
        if run_time < best_run['time']:
            new_best = {"attempt": run_attempt, "time": run_time}
    return new_best


async def main():
    git_hash = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()
    logger.info(f"FE2 Companion by pinheadtf2 [{git_hash}]")

    Path('music').mkdir(exist_ok=True)
    if not Path(database_name).exists():
        await create_database(database_name)
        logger.info(f"Created database {database_name}")
    database = await aiosqlite.connect(database_name)

    selected_map = await select_map(database)
    selected_map['best_attempt'] = json.loads(selected_map['best_attempt'])
    selected_map['best_completion'] = json.loads(selected_map['best_completion'])

    pygame.mixer.init()
    if not selected_map['song']:
        pygame.mixer.music.load('music/Hyperspace - V2 - luxTypes.mp3')
        volume = 0
        pygame.mixer.music.set_volume(volume)
    else:
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
                f"{" " * 33}Map Best Attempt: {selected_map['best_attempt']['time']} (Att. {selected_map['best_attempt']['attempt']})\n"
                f"{" " * 33}Map Best Completion: {selected_map['best_completion']['time']} (Att. {selected_map['best_completion']['attempt']})")

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
        # screenshot.save(f'images/image_{int(time.time())}.png')

        if any((match := partial) in text for partial in play_strings) and not running:
            running = True
            if "get ready: 3" in text:
                logger.info(f"Matched, pausing for get ready: 3")
                await asyncio.sleep(0.35)
            if "get ready: 2" in text:
                logger.info(f"Matched, pausing for get ready: 2")
                await asyncio.sleep(0.35)

            pygame.mixer.music.play()
            run_start = time.time()
            attempts += 1
            logger.match(f"Attempt {attempts} of {selected_map['name']}\n"
                         f"{" " * 34}Matches: {match} | All Text: {text}")
            continue
        elif (any((match := partial) in text for partial in stop_strings) or keyboard.is_pressed('g')) and running:
            running = False
            pygame.mixer.music.stop()
            run_time = round(time.time() - run_start, 3)

            session_attempt_comparison = await compare_run('attempt', attempts, run_time, session_best_attempt)
            if session_attempt_comparison:
                map_attempt_comparison = await compare_run('attempt', attempts, run_time, selected_map['best_attempt'])
                if map_attempt_comparison:
                    session_best_attempt = map_attempt_comparison
                    selected_map['best_attempt'] = session_best_attempt
                    logger.match(f"Stopped music after {run_time}\n"
                                 f"{" " * 34}New Map Best Attempt! | Attempt #{attempts} lasted for {run_time} seconds\n"
                                 f"{" " * 34}Matches: {match} | All Text: {text}")
                    await database.execute('UPDATE sessions SET best_attempt = ? WHERE rowid = ?',
                                           [str(session_best_attempt), run_id])
                    await database.execute('UPDATE maps SET best_attempt = ? WHERE rowid = ?',
                                           [str(session_best_attempt), run_id])
                else:
                    session_best_attempt = session_attempt_comparison
                    logger.match(f"Stopped music after {run_time}\n"
                                 f"{" " * 34}New Session Best Attempt! | Attempt #{attempts} lasted for {run_time} seconds\n"
                                 f"{" " * 34}Map Best Attempt: {selected_map['best_attempt']['time']} seconds (S. Att. {selected_map['best_attempt']['attempt']})\n"
                                 f"{" " * 34}Matches: {match} | All Text: {text}")
                    await database.execute('UPDATE sessions SET best_attempt = ? WHERE rowid = ?',
                                           [str(session_best_attempt), run_id])
            else:
                logger.match(f"Stopped music after {run_time}\n"
                             f"{" " * 34}Map Best Attempt: {selected_map['best_attempt']['time']} seconds (Att. {selected_map['best_attempt']['attempt']})\n"
                             f"{" " * 34}Session Best Attempt: {session_best_attempt['time']} seconds (S. Att. {session_best_attempt['attempt']})\n"
                             f"{" " * 34}All Text: {text} | Matches: {match}")

            await database.execute('UPDATE sessions SET total_attempts = ? WHERE rowid = ?',
                                   [attempts, run_id])
            await database.execute('UPDATE maps SET total_attempts = ? WHERE rowid = ?',
                                   [selected_map['total_attempts'] + attempts, run_id])
            await database.commit()
        elif keyboard.is_pressed('c') and running:
            run_time = round(time.time() - run_start, 3)
            completions += 1

            session_completion_comparison = await compare_run('completion', completions, run_time, session_best_completion)
            if session_completion_comparison:
                map_completion_comparison = await compare_run('completion', completions, run_time, selected_map['best_completion'])
                if map_completion_comparison:
                    session_best_completion = map_completion_comparison
                    logger.success(
                        f"Escaped map {selected_map['name']} after {attempts} attempts with a time of {run_time} seconds\n"
                        f"{" " * 37}This is your new map record! | Completions: {selected_map['completions'] + completions} ({completions} today)")
                    await database.execute('UPDATE sessions SET best_completion = ? WHERE rowid = ?',
                                           [str(session_best_completion), run_id])
                    await database.execute('UPDATE maps SET best_completion = ? WHERE rowid = ?',
                                           [str(session_best_completion), run_id])
                else:
                    session_best_completion = session_completion_comparison
                    logger.success(
                        f"Escaped map {selected_map['name']} after {attempts} attempts with a time of {run_time} seconds\n"
                        f"This is a new session record! | Completions: {selected_map['completions'] + completions} ({completions} today)\n"
                        f"Map Best Completion: {selected_map['best_completion']['time']} seconds (Att. {selected_map['best_completion']['attempt']})")
                    await database.execute('UPDATE sessions SET best_completion = ? WHERE rowid = ?',
                                           [str(session_best_completion), run_id])
            else:
                logger.success(
                    f"Escaped map {selected_map['name']} after {attempts} attempts with a time of {run_time} seconds\n"
                    f"{" " * 37}Map Best Completion: {selected_map['best_completion']['time']} seconds (Att. {selected_map['best_completion']['attempt']})\n"
                    f"{" " * 37}Session Best Completion: {session_best_completion['time']} seconds (Att. {session_best_completion['attempt']})")

            await database.execute('UPDATE sessions SET total_attempts = ?, total_completions = ? WHERE rowid = ?',
                                   [attempts, completions, run_id])
            await database.execute('UPDATE maps SET total_attempts = ?, total_completions = ? WHERE rowid = ?',
                                   [selected_map['total_attempts'] + attempts,
                                    selected_map['total_completions'] + completions, run_id])
            await database.commit()
            break
        elif keyboard.is_pressed('k'):
            pygame.mixer.music.stop()
            break

        perf_end = time.perf_counter()
        logger.debug(f"{perf_end - perf_start:.5f} seconds | Text: {text}")

    while pygame.mixer.music.get_busy():
        if keyboard.is_pressed('k'):
            pygame.mixer.music.stop()
        await asyncio.sleep(1)

    await database.close()

    logger.bye("See ya!")
    return


if __name__ == '__main__':
    asyncio.run(main())
    exit(0)
