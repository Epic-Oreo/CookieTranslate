import dearpygui.dearpygui as dpg
import os
from pathlib import Path
from PIL import Image
import numpy as np
from dearpygui_async import DearPyGuiAsync # import
from server.translator import CookieTranslator
from multiprocessing import Manager, Process, JoinableQueue, cpu_count, Lock, Value
import redis
import asyncio


dpg_async = DearPyGuiAsync() # initialize

WINDOW_EDIT_MODE = False




async def worker(
  queue,
  failedQueue,
  id,
  debug,
  outPath,
  cache_type,
  redis_url,
  fontSize
):
  # print(f"Worker {id} starting")
  worker_status = {id: ""}

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
  translator = CookieTranslator(
    redisCache=redisCache, debug=debug, fontSize=fontSize
  )

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
      # if r["cacheInfo"]["all"]:
      #     cachedCounter.value += 1

      save_name = f"{Path(name).stem}.webp"
      savePath = out_dir / save_name
      translated.save(savePath, "webp")

      # print(f"Saved {savePath}")
      worker_status[id] = f"Completed {name}"
    except Exception as e:
      # print(f"Error processing {name}:", e)
      worker_status[id] = f"Failed {name}"
      failedQueue.put({"path": path_str, "name": name, "error": str(e)})

    finally:
      queue.task_done()
      # with lock:
      #     counter.value += 1

def startWorker(*args):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(worker(*args))
    finally:
        loop.close()

def main():
  dpg.create_context()
  dpg.configure_app(
    docking=True,
    docking_space=True,
    docking_shift_only=True,
    load_init_file="custom_layout.ini",
  )
  dpg.create_viewport(
    title="Cookie Translate", width=800, height=600
  )  # Initial size, will be overridden
  dpg.setup_dearpygui()

  output_window = dpg.generate_uuid()
  preview_window = dpg.generate_uuid()
  left_window = dpg.generate_uuid()
  files_section = dpg.generate_uuid()
  
  
  images = []
  
  async def translateSingle(imageTag, _, __):
    
    dpg.focus_item(preview_window)
    dpg.render_dearpygui_frame()
    print(f"Translating {imageTag}")
    image = images[int(imageTag.split('_')[-1])]
    # Dummy translation: convert to grayscale
    
    font_size_value = dpg.get_value("font_size_option")

    translator = CookieTranslator(fontSize=font_size_value)
    translated_image = await translator.run(image)
    translator = None # free memory
    
    window_size = 320, 480
    
    with dpg.window(label="Translated Image", width=window_size[0]+20, height=window_size[1]+40):
      width, height = translated_image.size
      
      # Convert image to flat list of normalized RGBA values
      texture_data = []
      for y in range(height):
          for x in range(width):
              pixel: list[float] = translated_image.getpixel((x, y)) # type: ignore
              # Normalize color values to 0-1 range
              texture_data.extend([
                  pixel[0] / 255,
                  pixel[1] / 255, 
                  pixel[2] / 255,
                  pixel[3] / 255 if len(pixel) > 3 else 1.0
                  ])


      texture_tag = dpg.generate_uuid()
      with dpg.texture_registry():
          dpg.add_static_texture(width=width, height=height, default_value=texture_data, tag=texture_tag)
      
      dpg.add_image(texture_tag, width=window_size[0], height=window_size[1])

  async def viewSingleImage(imageTag, _, __):
    image = images[int(imageTag.split('_')[-1])]

    window_size = 320, 480
    
    with dpg.window(label="Image", width=window_size[0]+20, height=window_size[1]+40):
      width, height = image.size
      
      # Convert image to flat list of normalized RGBA values
      texture_data = []
      for y in range(height):
          for x in range(width):
              pixel: list[float] = image.getpixel((x, y)) # type: ignore
              # Normalize color values to 0-1 range
              texture_data.extend([
                  pixel[0] / 255,
                  pixel[1] / 255, 
                  pixel[2] / 255,
                  pixel[3] / 255 if len(pixel) > 3 else 1.0
                  ])


      texture_tag = dpg.generate_uuid()
      with dpg.texture_registry():
          dpg.add_static_texture(width=width, height=height, default_value=texture_data, tag=texture_tag)
      
      dpg.add_image(texture_tag, width=window_size[0], height=window_size[1])

  async def translateAll(processes_tag, cache_type, cache_address, output_location, font_size):
    processes_value = dpg.get_value(processes_tag)
    cache_type_value = dpg.get_value(cache_type)
    cache_address_value = dpg.get_value(cache_address)
    output_location_value = Path(dpg.get_value(output_location))
    font_size_value = dpg.get_value(font_size)

    silent = False

    debug = True

    print("Loading Translator")
    translator = CookieTranslator(fontSize=font_size_value)

    # if dir does not exist, create it
    output_location_value.mkdir(exist_ok=True)

    

    queue = JoinableQueue()
    failedQueue = JoinableQueue()


    for i, file in enumerate(images):

      # fp = target / str(file)
      if not silent:
        print(f"Queueing: #{i} - {file}")
      # put path into queue; open file in worker process instead
      queue.put({"path": file, "name": file})

    for _ in range(processes_value):
      queue.put(None)

    
    counter = Value("i", 0)
    lock = Lock()

    print("Starting Processes")

    runningProcesses = []
    for i in range(processes_value):
      print(f"Starting {i}")
      p = Process(
        target=startWorker,
        args=(
          queue,
          failedQueue,
          i,
          debug,
          output_location_value,
          cache_type,
          cache_address_value,
          font_size_value,
        ),
      )
      p.start()
      runningProcesses.append(p)

    # Wait for all tasks to be processed
    queue.join()

    # Workers should exit after receiving sentinel; join them
    for p in runningProcesses:
      p.join()
      if not silent:
        print("All tasks completed")


    
  def loadImages(appData):
    source = Path(appData["file_path_name"])
    files = [f for f in os.listdir(source) if f != ".DS_Store"]
    files.sort()
    with dpg.texture_registry():
    
      for i, file in enumerate(files):
        file_uid = dpg.generate_uuid()
        dpg.set_value("file_load_progress", (i/len(files)))
        
        image_path = source / file
        image = Image.open(image_path).convert("RGBA")
        images.append(image.copy())
        # image = image.resize((160, 240))
        image = image.resize((60, 120))
        width, height = image.size
        
        # Convert image to flat list of normalized RGBA values
        texture_data = []
        for y in range(height):
            for x in range(width):
                pixel: list[float] = image.getpixel((x, y)) # type: ignore
                # Normalize color values to 0-1 range
                texture_data.extend([
                    pixel[0] / 255,
                    pixel[1] / 255, 
                    pixel[2] / 255,
                    pixel[3] / 255 if len(pixel) > 3 else 1.0
                    ])

        dpg.add_static_texture(width=width, height=height, default_value=texture_data, tag=file_uid)
        
        with dpg.group(parent=files_section, horizontal=True):
          dpg.add_image(file_uid, width=40, height=60)
          with dpg.group():
            dpg.add_text(file)
            with dpg.group(horizontal=True):
              dpg.add_text(f"{width}x{height}")
              dpg.add_button(label='Test', show=False, tag=f'translate_{i}', callback=translateSingle)
              dpg.add_button(label='View', show=True, tag=f'view_picture_{i}', callback=viewSingleImage)
    
    
    dpg.configure_item("file_load_progress", show=False)
    dpg.configure_item("loaded_text", show=True)
    dpg.configure_item("translate_button", enabled=True)
    
    # show all translate buttons
    for item in range(len(files)):
      dpg.configure_item(f'translate_{item}', show=True)


  dpg.add_file_dialog(
    directory_selector=True,
    show=False,
    callback=lambda _, app_data: loadImages(app_data),
    tag="file_dialog_id",
    width=700,
    height=400,
  )
  
  # set output location
  dpg.add_file_dialog(
    directory_selector=True,
    show=False,
    callback=lambda _, app_data: dpg.set_value("output_location", app_data["file_path_name"]),
    tag="output_file_dialog_id",
    width=700,
    height=400,
  )
    
  with dpg.window(label="Input", tag=left_window, no_move=not WINDOW_EDIT_MODE, no_close=not WINDOW_EDIT_MODE):
    with dpg.group(horizontal=True):
      dpg.add_text("Select Image/Folder: ")
      dpg.add_button(label="Open Folder", callback=lambda: dpg.show_item("file_dialog_id"))
      dpg.add_button(label="Debug Add Image", callback=lambda: loadImages({"file_path_name": "./server/test_images"}))
      dpg.add_button(label="DB SM IMG", callback=lambda: loadImages({"file_path_name": "./server/test_images_small"}))
      
      
    dpg.add_separator()
    
    with dpg.child_window(height=300, resizable_y=True, tag=files_section):
      # files_section
      pass
    
    dpg.add_progress_bar( width=-1, tag="file_load_progress")
    
    dpg.add_text("Fully Loaded!", show=False, tag="loaded_text")
    
    
    dpg.add_separator()
    
    
    dpg.add_text("Options")
    # processes
    processes_tag = dpg.add_slider_int(label="Processes", width=150, min_value=1, max_value=4, default_value=1)
    
    # cache
    cache_type = dpg.add_combo(label="Cache Type", items=["None", "Redis"], default_value="None", width=150, callback=lambda s, a, u: dpg.configure_item(cache_address, show=(a != "None")))
    
    cache_address = dpg.generate_uuid()
    dpg.add_input_text(label="Cache Address", default_value="localhost:6379", width=150, tag=cache_address, show=False)
    
    # output
    output_location = dpg.add_input_text(label="Output Location", default_value="./output", width=150, tag="output_location")
    dpg.add_button(label="Set Output Location", callback=lambda: dpg.show_item("output_file_dialog_id"), width=150)
    
    # font size
    font_size = dpg.add_input_int(label="Font Size", width=150, default_value=25, tag="font_size_option")
    

    
    
    dpg.add_separator()
    
    # Translate Button
    with dpg.theme(tag="cta_button"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (100,100,150))
            


    async def initRun(_, __):
       await translateAll(processes_tag, cache_type, cache_address, output_location, font_size)

    dpg.add_button(label="Translate All", tag="translate_button", enabled=False, callback=initRun, width=-1)


    # with dpg.window(label="about", tag="main window"):
    #     dpg.add_button(label="Save Window pos", callback=lambda: dpg.save_init_file("dpg.ini"))

    dpg.bind_item_theme(dpg.last_item(), "cta_button")

      
  with dpg.window(label="Output", tag=output_window, no_move=not WINDOW_EDIT_MODE, no_close=not WINDOW_EDIT_MODE):
    pass

  with dpg.window(label="Preview", tag=preview_window, no_move=not WINDOW_EDIT_MODE, no_close=not WINDOW_EDIT_MODE):
    dpg.add_text("Under Construction :)")
  

  dpg.show_viewport()
  dpg_async.run()
  dpg.destroy_context()


if __name__ == "__main__":
    main()
