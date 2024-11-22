import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import List

import aiosqlite
import keyboard
import pytesseract
from PIL import Image, ImageGrab

from modules.databases import create_database
from modules.logs import add_logging_level

with contextlib.redirect_stdout(None):
    import pygame

version = "v2.0.0"
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
        logger.warning("No music files detected in music folder! "
                       "Music features will be unavailable, and this will only act as a tracker!")
        return None
    elif len(music_files) == 1:
        return music_files[0].__str__().replace(music_files[0].cwd().__str__(), "")[1:].replace("\\", "/")
    else:
        displayable_paths = []
        for path in music_files:
            displayable_paths.append(path.__str__().replace(music_files[0].cwd().__str__(), "")[1:].replace("\\", "/"))

        while True:
            logger.info(f"{len(displayable_paths)} Songs Found! "
                        f"Type the number for the song you want to play, or simply press enter for no music.\n"
                        # f"{'=' * os.get_terminal_size().columns}"
                        f"")
            for i, dpath in enumerate(displayable_paths, 1):
                print(f"{i}. {dpath}")

            try:
                selection = input("\nSong Number (or enter): ")
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
    new_img = Image.new('RGB', (max(widths), sum(heights)))

    y_offset = 0
    for img in images:
        new_img.paste(img, (0, y_offset))
        y_offset += img.height

    Path('images').mkdir(exist_ok=True)
    return new_img


async def submit_new_map(database: aiosqlite.Connection):
    new_map = input("Enter name of map: ")
    if len(new_map) == 0:
        logger.error("Map name cannot be empty!")
        return await submit_new_map(database)
    await database.execute('INSERT INTO maps VALUES(?)', [new_map])
    await database.commit()


async def query_maps(database: aiosqlite.Connection):
    database.row_factory = aiosqlite.Row
    async with database.execute('SELECT name FROM maps') as cursor:
        database.row_factory = None
        result = await cursor.fetchall()
        maps = []
        for data in result:
            maps.append(data[0])
        return maps


async def select_map(database: aiosqlite.Connection):
    maps = await query_maps(database)

    if len(maps) == 0:
        logger.info("No maps found! Adding first map...\n")
        await submit_new_map(database)
        maps = await query_maps(database)
    elif len(maps) == 1:
        return maps[0]

    while True:
        logger.info(f"{len(maps)} Maps Stored! "
                    f"Type the ID of the map you're playing on. For a new map, hit enter.\n")
        for i, name in enumerate(maps, 1):
            print(f"{i}. {name}")

        try:
            selection = input("\nSong Number (or enter): ")
            return maps[int(selection) - 1]
        except ValueError:
            logger.error("Invalid selection!")


async def main():
    logger.info(f"FE2 Companion {version} by pinheadtf2")

    if not Path(database_name).exists():
        await create_database(database_name)
        logger.info(f"Created database {database_name}")
    database = await aiosqlite.connect(database_name)

    pygame.mixer.init()
    Path('music').mkdir(exist_ok=True)
    music = await find_select_music()
    if music:
        pygame.mixer.music.load(music)
        volume = await choose_volume()
        pygame.mixer.music.set_volume(volume)
        logger.info(f"Initialized music player with song {music} at volume {volume}")
    else:
        pygame.mixer.music.load(music)
        pygame.mixer.music.set_volume(0)
    selected_map = await select_map(database)

    # this is where the session is officially declared as 'started'
    session_start = int(time.time())
    best_attempt = {'attempt': 0, 'time': 0}
    best_completion = {'attempt': 0, 'time': 999999}
    cursor = await database.execute('INSERT INTO sessions VALUES(?, ?, ?, ?, ?, ?, ?)',
                                    [selected_map, session_start, None, 0, 0, str(best_attempt), str(best_completion)])
    run_id = cursor.lastrowid
    await database.commit()

    logger.success(f"Started session {run_id} with map {selected_map} and song {music} (vol {volume})")

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
            attempts += 1
            run_start = time.time()
            logger.match(f"Attempt {attempts} of {selected_map} (Song: {music})\n"
                         f"    All Text: {text} | Matches: {match}")
            continue
        elif (any((match := partial) in text for partial in stop_strings) or keyboard.is_pressed('g')) and running:
            running = False
            pygame.mixer.music.stop()
            run_time = round(time.time() - run_start, 3)
            if run_time > best_attempt['time']:
                best_attempt = {'attempt': attempts, 'time': run_time}
                logger.match(f"Stopped music after {run_time}\n"
                             f"    New Best Attempt! Ran for {best_attempt['time']} seconds after {best_attempt['attempt']} runs\n"
                             f"    All Text: {text} | Matches: {match}")
                await database.execute('UPDATE sessions SET total_attempts = ?, best_attempt = ? WHERE rowid = ?',
                                       [attempts, str(best_attempt), run_id])
            else:
                logger.match(f"Stopped music after {run_time}\n"
                             f"    All Text: {text} | Matches: {match}")
                await database.execute('UPDATE sessions SET total_attempts = ? WHERE rowid = ?',
                                       [attempts, run_id])
            await database.commit()
        elif keyboard.is_pressed('c') and running:
            run_time = round(time.time() - run_start, 3)
            completions += 1
            logger.success(
                f"Escaped {selected_map} after {attempts} attempts with a time of {run_time} (Completion #{completions})")

            if run_time < best_completion['time']:
                best_completion = {'attempt': attempts, 'time': run_time}
                await database.execute(
                    'UPDATE sessions SET total_attempts = ?, total_completions = ?, best_completion = ? WHERE rowid = ?',
                    [attempts, completions, str(best_completion), run_id])
            else:
                await database.execute('UPDATE sessions SET total_attempts = ?, total_completions = ? WHERE rowid = ?',
                                       [attempts, completions, run_id])
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


if __name__ == '__main__':
    asyncio.run(main())

# if __name__ == "__main__":
#     running = False
#     run_start = None
#     session_start = time.time()
#     attempts = 0
#     pygame.mixer.init()
#     pygame.mixer.music.load(song)
#     pygame.mixer.music.set_volume(volume)
#     logger.info(f"Initialized player with song '{song}' at volume {volume}")
#
#     session = dict()
#     session["session_start"] = time.time()
#
#     best_attempt = dict()
#     best_attempt['attempt'] = attempts - 1
#     best_attempt['time'] = 1
#
#     best_completion = dict()
#     best_completion['attempt'] = None
#     best_completion['time'] = None
#
#     session["total_completions"] = 0
#     session["best_attempt"] = best_attempt
#     session["best_completion"] = best_completion
#
#     while True:
#         # perf_start = perf_counter()
#         # get ready from 350, 870, 1000, 1000
#         # notifs box from 600, 0, 1400, 250
#         # rescue box from 700, 870, 1250, 990
#         image_ready = ImageGrab.grab(bbox=(320, 850, 1000, 1000))
#         image_notifications = ImageGrab.grab(bbox=(600, 0, 1300, 300))
#         image_rescue = ImageGrab.grab(bbox=(700, 870, 1250, 990))
#         image_share = ImageGrab.grab(bbox=(150, 0, 550, 50))
#
#         # image_ready.save(f"images/image_ready_{time.time()}.png")
#         # image_notifications.save(f"images/image_notifications_{time.time()}.png")
#         # image_rescue.save(f"images/image_rescue_{time.time()}.png")
#
#         all_text = ""
#         for image in (image_ready, image_notifications, image_rescue, image_share):
#             text = pytesseract.image_to_string(image)
#             all_text = all_text + " " + text
#         all_text = all_text.strip().replace("\n", " ").lower()
#
#         # screenshot = ImageGrab.grab(bbox=(0, 0, 1920, 1080))
#         # text = pytesseract.image_to_string(screenshot)
#         # text = text.lower()
#
#         if (any(partial in all_text for partial in play_strings) or keyboard.is_pressed(']')) and not running:
#             running = True
#             if "fe2.io" in all_text:
#                 logger.info("big delay")
#                 time.sleep(0.8)
#             elif "get ready: 2" in all_text:
#                 logger.info("delay")
#                 time.sleep(0.35)
#             pygame.mixer.music.play()
#             attempts += 1
#             run_start = time.time()
#             logger.info(f"Playing {song} | Attempt {attempts}\n"
#                         f"    All Text: " + all_text.strip().replace("\n", " "))
#             continue
#         elif (any(partial in all_text for partial in stop_strings) or keyboard.is_pressed('g')) and running:
#             running = False
#             pygame.mixer.music.stop()
#             run_time = time.time() - run_start
#             logger.info(f"Stopped music after {run_time}\n"
#                         f"    All Text: " + all_text.strip().replace("\n", " "))
#         elif keyboard.is_pressed('c') and running:
#             running = False
#             run_time = time.time() - run_start
#             readable_time = datetime.datetime.fromtimestamp(run_time).strftime("%H:%M:%S.%f")[:-3]
#             logger.info(f"Escaped map with time {run_time} after {attempts} attempts ({readable_time})\n"
#                         f"    All Text: " + all_text.strip().replace("\n", " "))
#             break
#         elif keyboard.is_pressed('k'):
#             if pygame.mixer.music.get_busy():
#                 pygame.mixer.music.stop()
#             break
#         # perf_stop = perf_counter()
#         # perf_debug.append((perf_stop - perf_start, perf_stop, perf_start))
#
#     # with open('debug.txt', 'w') as f:
#     #     for line in perf_debug:
#     #         f.write(f"{line}\n")
#
#     while pygame.mixer.music.get_busy():
#         pygame.time.wait(1000)
#
#     session["total_attempts"] = attempts
