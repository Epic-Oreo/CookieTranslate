import argparse
from pathlib import Path
from os import listdir, path
from translator import CookieTranslator
from PIL import Image
from tqdm import tqdm
from multiprocessing import Manager, Process, JoinableQueue, cpu_count, Lock, Value
import asyncio
import redis
import json
import time
import threading


def createStatusBar(total, process_count):
    """Creates a multi-line progress bar with worker status lines"""
    main_bar = tqdm(total=total, desc="Overall Progress", position=0, colour="green")
    status_bars = []
    for i in range(process_count):
        status_bars.append(
            tqdm(
                total=0,
                desc=f"Worker {i}",
                position=i + 1,
                bar_format="{desc}: {unit}",
                leave=True,
            )
        )
    return main_bar, status_bars


async def worker(
    queue,
    failedQueue,
    id,
    debug,
    outPath,
    cache_type,
    redis_url,
    counter,
    lock,
    cachedCounter,
    worker_status,
    imageOptions,
):
    # print(f"Worker {id} starting")
    worker_status[id] = f"Starting..."

    redisCache = None
    if cache_type == "redis":
        worker_status[id] = f"Connecting to {redis_url}"

        if not redis_url:
            raise Exception("!!Something bad!!")
        redisCache = redis.Redis(redis_url, decode_responses=True)

    out_dir = Path(outPath)
    out_dir.mkdir(parents=True, exist_ok=True)

    worker_status[id] = "Loading Module"
    translator = CookieTranslator(redisCache=redisCache, debug=debug, fontSize=imageOptions["fontSize"])

    while True:
        item = queue.get()
        # handle sentinel for clean shutdown
        if item is None:
            worker_status[id] = "Finished"
            queue.task_done()
            break

        path_str = item.get("path")
        name = item.get("name")

        worker_status[id] = f"Processing {name}"

        try:
            # print(f"Worker {id} processing {name}")
            # open the image inside the worker process (images are not reliably picklable)
            img = Image.open(path_str)

            # translated = await translator.run(img)
            r = await translator.expandedRun(img)
            translated = r["image"]
            if r["cacheInfo"]["all"]:
                cachedCounter.value += 1

            save_name = f"{Path(name).stem}.webp"
            savePath = out_dir / save_name
            translated.save(savePath, "webp")

            # print(f"Saved {savePath}")
            worker_status[id] = f"Completed {name}"
        except Exception as e:
            print(f"Error processing {name}:", e)
            worker_status[id] = f"Failed {name}"
            failedQueue.put({"path": path_str, "name": name, "error": str(e)})

        finally:
            queue.task_done()
            with lock:
                counter.value += 1


def startWorker(*args):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(worker(*args))
    finally:
        loop.close()


def progress_monitor(counter, total_items, lock, worker_status):
    """Monitor progress in main process with worker status"""
    main_bar, status_bars = createStatusBar(total_items, processes)

    try:
        while True:
            with lock:
                current = counter.value

            main_bar.n = current
            main_bar.refresh()

            # Update worker status bars
            for i in range(processes):
                # status_bars[i].set_postfix_str(worker_status.get(i, "Waiting...").removeprefix(", "))
                status_bars[i].unit = worker_status.get(i, "Waiting...")
                # status_bars[i].set_postfix_str("Test123")

                status_bars[i].refresh()

            if current >= total_items:
                break

            time.sleep(0.1)
    finally:
        main_bar.close()
        for bar in status_bars:
            bar.close()


def runBulk(target, outPath, debug, cache_type, redis_url, processes, fontSize):

    imageOptions = {"fontSize": fontSize}

    files = [f for f in listdir(target) if f != ".DS_Store"]

    files.sort()
    queue = JoinableQueue()
    for i, file in enumerate(files):

        # if i >= FIRST_PAGE and i <= LAST_PAGE:
        fp = target / str(file)
        print(f"Queueing: #{i} - {file}")
        # put path into queue; open file in worker process instead
        queue.put({"path": str(fp), "name": file})

    for _ in range(processes):
        queue.put(None)

    failedQueue = JoinableQueue()

    total_items = len(files)
    counter = Value("i", 0)
    cachedCounter = Value("i", 0)
    lock = Lock()

    with Manager() as manager:
        worker_status = manager.dict()

        # Start progress monitor in separate thread
        monitor_thread = threading.Thread(
            target=progress_monitor, args=(counter, total_items, lock, worker_status)
        )
        monitor_thread.daemon = True
        monitor_thread.start()

        runningProcesses = []
        for i in range(processes):
            p = Process(
                target=startWorker,
                args=(
                    queue,
                    failedQueue,
                    i,
                    debug,
                    outPath,
                    cache_type,
                    redis_url,
                    counter,
                    lock,
                    cachedCounter,
                    worker_status,
                    imageOptions,
                ),
            )
            p.start()
            runningProcesses.append(p)

            # Wait for all tasks to be processed
        queue.join()

        # Workers should exit after receiving sentinel; join them
        for p in runningProcesses:
            p.join()

            print("All tasks completed")

        print(f"{cachedCounter.value}/{total_items} Items fully cached")

        # Save failed tasks to a JSON file
        failed_tasks = []
        while not failedQueue.empty():
            failed_tasks.append(failedQueue.get())
            failedQueue.task_done()

        if failed_tasks:
            failed_path = Path("./failed_tasks.json")
            with open(failed_path, "w") as f:
                json.dump(failed_tasks, f, indent=2)
            print(f"Saved {len(failed_tasks)} failed tasks to {failed_path}")
        else:
            print("No failed tasks")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        prog="Cookie Translator",
        description="Translate manga images using OCR and Google Translate",
        epilog="2025 EpicOreo",
    )

    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug mode with additional output",
    )
    parser.add_argument(
        "-i", "--input", type=str, required=True, help="Path to the input image file"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Path to save the translated image (or directory for bulk mode), default: ./out/ or ./out.png",
    )
    parser.add_argument(
        "-t",
        "--cache-type",
        type=str,
        choices=["file", "redis", "none"],
        help="Type of cache to use (default: file)",
    )
    parser.add_argument(
        "-r",
        "--redis-url",
        type=str,
        help="Redis server URL (required if cache type is redis)",
    )
    parser.add_argument(
        "-b", "--bulk", action="store_true", help="Enable bulk processing mode"
    )
    parser.add_argument(
        "--processes",
        type=int,
        default=4,
        help="Number of parallel processes for bulk mode (default: 4)",
    )

    parser.add_argument(
        "--font-size",
        type=int,
        default=25,
        help="Font size for pasted text (default: 25)",
    )

    args = parser.parse_args()

    target = args.input
    outPath = args.output
    debug = args.debug
    cache_type = args.cache_type
    redis_url = args.redis_url
    bulk = args.bulk
    processes = args.processes

    fontSize = args.fontSize

    if cache_type == "redis" and not redis_url:
        parser.error(
            "The --redis-url argument is required when --cache-type is 'redis'"
        )

    if not outPath:
        if bulk:
            outPath = "./out/"
        else:
            outPath = "./out.png"

    if bulk:
      if cache_type != "redis" and cache_type != None:
        parser.error(
          "In bulk mode, cache type can only be 'redis' for process safety"
        )

      # check that input and output are directories
      input_path = Path(target)
      if not input_path.is_dir():
        parser.error("In bulk mode, the input path must be a directory")
      out_path = Path(outPath)
      if not out_path.is_dir():
        parser.error("In bulk mode, the output path must be a directory")

      cpu_cores = cpu_count()
      if processes < 1 or processes > cpu_cores:
        parser.error(f"The number of processes must be between 1 and {cpu_cores}")

      print(f"Running in bulk mode with {processes} processes")

      runBulk(input_path, outPath, debug, cache_type, redis_url, processes, fontSize)
    else:

      # check that input is a file
      input_path = Path(target)
      if not input_path.is_file():
        parser.error("The input path must be a valid file")
      out_path = Path(outPath)
      if out_path.exists() and out_path.is_dir():
        parser.error("The output path must be a file, not a directory")

      print("Running in single image mode")
      translator = CookieTranslator(
          redisCache=(
              redis.Redis(redis_url, decode_responses=True)
              if cache_type == "redis"
              else None
          ),
          debug=debug,
          fontSize = fontSize
      )

      print(f"Translating {input_path}...")
      img = Image.open(input_path)
      translated = asyncio.run(translator.run(img))
      translated.save(out_path, "PNG")
      print(f"Saved translated image to {out_path}")
