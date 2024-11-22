import contextlib
import datetime
import logging
import time
from pathlib import Path

import keyboard
import pytesseract
from PIL import ImageGrab

with contextlib.redirect_stdout(None):
    import pygame

# poggers
logger = logging.getLogger('loggers')
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler('latest.log')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s'))
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(
    '\033[48;2;0;55;218m[%(asctime)s]\033[0m \033[38;2;59;120;255m[%(levelname)s]\033[0m %(message)s'
))
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# configure pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# strings
play_strings = ["get ready: 1", "get ready: 2", "rescue", "100", "0:00"]
stop_strings = ["round", "join", "next", "drowned"]
escaped_strings = ["escaped"]


def choose_song(paths: list):
    displayable_paths = []
    for path in paths:
        displayable_paths.append(path.__str__().replace(paths[0].cwd().__str__(), "")[1:].replace("\\", "/"))

    print(f"{len(displayable_paths)} Songs Found! "
          f"Type the number for the song you want to play, or simply press enter for no music.\n"
          # f"{'=' * os.get_terminal_size().columns}"
          f"")
    for i, dpath in enumerate(displayable_paths, 1):
        print(f"{i}. {dpath}")

    return displayable_paths[int(input("\nSelection: ")) - 1]


if __name__ == "__main__":
    # perf_debug = []
    volume = 0.35

    music_files = list((p.resolve() for p in Path("music").glob("**/*") if p.suffix in {'.mp3', '.ogg', '.wav'}))
    if len(music_files) == 0:
        logger.error("No music files detected in music folder! ")
        exit(0)
    elif len(music_files) == 1:
        song = music_files[0]
    else:
        song = choose_song(music_files)

    # input("Choose volume: ")

    running = False
    run_start = None
    session_start = time.time()
    attempts = 0
    pygame.mixer.init()
    pygame.mixer.music.load(song)
    pygame.mixer.music.set_volume(volume)
    logger.info(f"Initialized player with song '{song}' at volume {volume}")

    session = dict()
    session["session_start"] = time.time()

    best_attempt = dict()
    best_attempt['attempt'] = attempts - 1
    best_attempt['time'] = 1

    best_completion = dict()
    best_completion['attempt'] = None
    best_completion['time'] = None

    session["total_completions"] = 0
    session["best_attempt"] = best_attempt
    session["best_completion"] = best_completion

    while True:
        # perf_start = perf_counter()
        # get ready from 350, 870, 1000, 1000
        # notifs box from 600, 0, 1400, 250
        # rescue box from 700, 870, 1250, 990
        image_ready = ImageGrab.grab(bbox=(320, 850, 1000, 1000))
        image_notifications = ImageGrab.grab(bbox=(600, 0, 1300, 300))
        image_rescue = ImageGrab.grab(bbox=(700, 870, 1250, 990))
        image_share = ImageGrab.grab(bbox=(150, 0, 550, 50))

        # image_ready.save(f"images/image_ready_{time.time()}.png")
        # image_notifications.save(f"images/image_notifications_{time.time()}.png")
        # image_rescue.save(f"images/image_rescue_{time.time()}.png")

        all_text = ""
        for image in (image_ready, image_notifications, image_rescue, image_share):
            text = pytesseract.image_to_string(image)
            all_text = all_text + " " + text
        all_text = all_text.strip().replace("\n", " ").lower()

        # screenshot = ImageGrab.grab(bbox=(0, 0, 1920, 1080))
        # text = pytesseract.image_to_string(screenshot)
        # text = text.lower()

        if (any(partial in all_text for partial in play_strings) or keyboard.is_pressed(']')) and not running:
            running = True
            if "fe2.io" in all_text:
                logger.info("big delay")
                time.sleep(0.8)
            elif "get ready: 2" in all_text:
                logger.info("delay")
                time.sleep(0.35)
            pygame.mixer.music.play()
            attempts += 1
            run_start = time.time()
            logger.info(f"Playing {song} | Attempt {attempts}\n"
                        f"    All Text: " + all_text.strip().replace("\n", " "))
            continue
        elif (any(partial in all_text for partial in stop_strings) or keyboard.is_pressed('g')) and running:
            running = False
            pygame.mixer.music.stop()
            run_time = time.time() - run_start
            logger.info(f"Stopped music after {run_time}\n"
                        f"    All Text: " + all_text.strip().replace("\n", " "))
        elif keyboard.is_pressed('c') and running:
            running = False
            run_time = time.time() - run_start
            readable_time = datetime.datetime.fromtimestamp(run_time).strftime("%H:%M:%S.%f")[:-3]
            logger.info(f"Escaped map with time {run_time} after {attempts} attempts ({readable_time})\n"
                        f"    All Text: " + all_text.strip().replace("\n", " "))
            break
        elif keyboard.is_pressed('k'):
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            break
        # perf_stop = perf_counter()
        # perf_debug.append((perf_stop - perf_start, perf_stop, perf_start))

    # with open('debug.txt', 'w') as f:
    #     for line in perf_debug:
    #         f.write(f"{line}\n")

    while pygame.mixer.music.get_busy():
        pygame.time.wait(1000)

    session["total_attempts"] = attempts
