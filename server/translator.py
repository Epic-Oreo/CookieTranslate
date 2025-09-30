from manga_ocr import MangaOcr
import easyocr
from googletrans import Translator
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from collections.abc import Callable, Sequence
import json
import hashlib
import numpy as np
import asyncio
import redis
from loguru import logger
import warnings

class CookieTranslator():
  
  def __init__(self, redisCache=None, debug=False, fontSize=25):
    # print("Loading Models...")
    
    logger.disable("manga_ocr.ocr") # Disable ugly logger output
    
    self.reader = easyocr.Reader(['ja'])
    self.mocr = MangaOcr()
    self.translator = Translator()
    self.debug = debug
    
    self.__redisCache: redis.Redis | None = redisCache

    self.fontSize = fontSize
    

       
    
    

  # Allows to call a function with a caching wrapper
  def __cacheHelper(self, section: str, key: str, getter: Callable, params: list):
        
    if self.__redisCache:
      fullKey = f"{section}:{key}"

      if self.__redisCache.exists(fullKey):
        return self.__redisCache.json().get(fullKey), True
      else:
        result = getter(*params)
        self.__redisCache.json().set(fullKey, "$", result)
        return result, False
    else:
      return getter(*params), False
    # else:
    #   if section not in self.__cache.keys():
    #     self.__cache[section] = {}
        
    #   if key in self.__cache[section].keys():
    #     return self.__cache[section][key]
    #   else:
    #     result = getter(*params)
    #     self.__cache[section][key] = result
    #     return result
    
  async def __asyncCacheHelper(self, section: str, key: str, getter: Callable, params: list):
    if self.__redisCache:
      fullKey = f"{section}:{key}"
      

      if self.__redisCache.exists(fullKey):
        return self.__redisCache.json().get(fullKey), True
      else:
        result = await getter(*params)
        self.__redisCache.json().set(fullKey, "$", result)
        return result, False
    else:
      return (await getter(*params)), False
      
    # else:
    #   if section not in self.__cache.keys():
    #     self.__cache[section] = {}
        
    #   if key in self.__cache[section].keys():
    #     return self.__cache[section][key]
    #   else:
    #     result = await getter(*params)
    #     self.__cache[section][key] = result
    #     return result
    
  # ! file cache is disabled for now
  # Saves the cache to its file
  # def saveCache(self):
  #   if not self.__objectCache:
  #     with open("./cache.json", "w") as f:
  #       json.dump(self.__cache, f)



  def __getBoxes(self, image: Image.Image):
    numpy_image = np.array(image)
    # Sequence[tuple[list, str, np.floating]] 
    with warnings.catch_warnings(action="ignore"):
      boxes = self.reader.readtext(numpy_image, slope_ths=0.4, height_ths=0.8)
    
    # Fixes having np int32's instead of normal int's
    processed_boxes = []
    for box in boxes:
      coords, _, score = box
      processed_coords = [[int(nums[0]), int(nums[1])] for nums in coords]
      processed_boxes.append((processed_coords, float(score)))
    return processed_boxes
  
  
  def __combineBoxes(self, boxes: list, image: Image.Image, tolerance=0):
    def get_intersect_area(box1, box2):
      coords1, _ = box1
      coords2, _ = box2

      x1 = max(coords1[0][0], coords2[0][0])
      y1 = max(coords1[0][1], coords2[0][1])
      x2 = min(coords1[2][0], coords2[2][0])
      y2 = min(coords1[2][1], coords2[2][1])

      if x2 < x1 or y2 < y1:
            return 0
      return (x2 - x1) * (y2 - y1)
    
    def combine(box1, box2):
      coords1, t1 = box1
      coords2, t2 = box2
      
      x1 = min(coords1[0][0], coords2[0][0])
      y1 = min(coords1[0][1], coords2[0][1])
      x2 = max(coords1[2][0], coords2[2][0])
      y2 = max(coords1[2][1], coords2[2][1])
      
      return ([
        [x1, y1],
        [x2, y1],
        [x2, y2],
        [x1, y2],
      ], (t1 + t2)/2)
    
    # used to save debug images for testing combining the boxes
    def debugOut(id, b):
      image_copy = image.copy()
      copy_draw = ImageDraw.Draw(image_copy)
      
      
      for x in b:
        coords, _ = x
        copy_draw.rectangle((coords[0], coords[2]), None, "red")
        
      image_copy.save(f"./imgs/{id}.png")
      
    result = boxes.copy()
    
    finished = False
    run = 0
    while not finished:
      if self.debug:
        print("Run #"+str(run))
      run += 1
      # input(">Press enter to run<")
      finished = True
      
      for i1 in range(len(result)):
        for i2 in range(i1+1, len(result)):
          box1 = result[i1]
          box2 = result[i2]          
          
          intersect = get_intersect_area(box1, box2)
          
          if intersect > tolerance:
            finished = False
            combined = combine(box1, box2)
            result[i1] = combined
            result.pop(i2)
            break
          
          
        if not finished:
          break

    return result
  
  def __getSubImages(self, image: Image.Image, boxes: list) -> list[Image.Image]:
    subImages = []
    for box in boxes:
      coords, _ = box
      
      size = (*coords[0], *coords[2])
      
      subImages.append(image.copy().crop(size))
    
    return subImages
  
  def __readWithMocr(self, image: Image.Image):
    return self.mocr(image)
  
  async def __translate(self, untranslated: str):
    return (await self.translator.translate(untranslated)).text
  
  async def __translateBulk(self, untranslated: list[str]):
    return [t.text for t in (await self.translator.translate(untranslated))]
  
  async def __extractText(self, subImages: list[Image.Image], boxes: list, imageHash: str):
    texts = []
    
    untranslated = []
    extractCached = True
    
    for i, image in enumerate(subImages):
      if self.debug:
        print(f"Getting #{i}")
        
      text, textCached = self.__cacheHelper("readText", imageHash + str(i), self.__readWithMocr, [image])
      
      if textCached == False:
        extractCached = False
      
      untranslated.append(text)
    
      
    if self.debug:
      print(f"Bulk Translating")
    untranslated_hash = hashlib.sha256(json.dumps(untranslated).encode()).hexdigest()
    
    
    texts, translateCached = await self.__asyncCacheHelper("translate", untranslated_hash, self.__translateBulk, [untranslated])
    
    # translated = await self.__asyncCacheHelper("translate", untranslated, self.__translate, [untranslated])
    # texts.append(translated)
    return texts, extractCached, translateCached

  def __pasteBackground(self, image: Image.Image, subImages: list[Image.Image], boxes: list):
    
    for i, subImage in enumerate(subImages):
      coords, _ = boxes[i]
      
      blurred = subImage.filter(ImageFilter.GaussianBlur(20))
      enhancer = ImageEnhance.Brightness(blurred)
      blurred = enhancer.enhance(1.4)
      
      # Have to separate coords or it someone re adds it to the list
      image.paste(blurred, (coords[0][0], coords[0][1]))
      
  def __addLineBreaks(self, text: str, boxWidth: int, font: ImageFont.FreeTypeFont):
    # get individual words
    words = text.split(" ")
    
    # Define the maximum width a line can be
    allowance = boxWidth
    workingText = ""
    
    for i, word in enumerate(words):
      wordSize = font.getlength(word)
      
      if (allowance - wordSize) > 0:
        if workingText != "":
          workingText += " "
        workingText += word
        allowance -= wordSize
      
      else:
        if (i != 0):
          workingText += "\n"
        workingText += word
        allowance = boxWidth - wordSize
      
    return workingText
 
  def __writeText(self, draw: ImageDraw.ImageDraw, texts: Sequence[str], boxes: list, fontFile: str, subImages: list[Image.Image]):
    fontSize = self.fontSize #? Font Size should be rather small
    font = ImageFont.truetype(fontFile, fontSize)
    
    for i, text in enumerate(texts):
      coords, _ = boxes[i]
      
      boxWidth = coords[2][0] - coords[0][0]
      boxHeight = coords[2][1] - coords[0][1]
      
      text = self.__addLineBreaks(text, boxWidth, font)
            
      img = subImages[i]
      img = img.convert("RGB")

      np_img = np.array(img)

      avg_r = int(np.mean(np_img[:, :, 0]))
      avg_g = int(np.mean(np_img[:, :, 1]))
      avg_b = int(np.mean(np_img[:, :, 2]))
      
      avg = avg_r + avg_g + avg_b
      
      if avg > 382.5:
        # Is light color
        textFill = "black"
      else:
        # Is dark color
        textFill = "white"

      draw.text(
        (coords[0][0] + round(boxWidth/2), coords[0][1] + round(boxHeight/2)), 
        text, 
        font=font, 
        anchor="mm", 
        align="center", 
        fill=textFill,
      )
  
  def __addDebugInfo(self, draw: ImageDraw.ImageDraw, boxes: list, fontFile: str):
    print("Adding debug!")
    font = ImageFont.truetype(fontFile, 20)
    
    for i, box in enumerate(boxes):
      coords, _ = box
      
      draw.rectangle((coords[0], coords[2]), None, "red")
      draw.text((coords[0][0], coords[2][1] - 10), str(i), font=font, fill="green")
  
  async def expandedRun(self, image: Image.Image) -> dict:
    imageHash = hashlib.sha256(image.tobytes()).hexdigest()
    draw = ImageDraw.Draw(image)
    font = "./NotoSansJP-Regular.ttf"
    
    if self.debug:
      print("Getting text location")
    boxes, boxesCached = self.__cacheHelper("boxes", imageHash, self.__getBoxes, [image])
    
    if self.debug:
      print("Combining Boxes")
    if boxes is not None:
      boxes = self.__combineBoxes(boxes, image)
    else:
      boxes = []
    
    boxHash = hashlib.sha256(bytes(json.dumps(boxes), "utf-8")).hexdigest()
    
    if self.debug:
      print("Getting Sub Images")
    subImages = self.__getSubImages(image, boxes)
    
    if self.debug:
      print("Read and Translate Text")
    # Combine hashes to make sure box changes are taken account of 
    # texts = [str(text) for text in ( or [])]
    texts, extractCached, translateCached = await self.__extractText(subImages, boxes, imageHash+boxHash)
    texts = [str(text) for text in (texts or [])]
    
    if self.debug:
      print("Drawing Backgrounds")
    self.__pasteBackground(image, subImages, boxes)
    
    if self.debug:
      print("Drawing Text")
    self.__writeText(draw, texts, boxes, font, subImages)
    
    
    if self.debug:
      self.__addDebugInfo(draw, boxes, font)
    

    return {
      "image": image,
      "bb": boxes,
      "cacheInfo": {
        "all": boxesCached and extractCached and translateCached,
        "boxes": boxesCached,
        "extract": extractCached,
        "translate": translateCached
      }
    }
    
  


  async def run(self, image: Image.Image) -> Image.Image:
    return (await self.expandedRun(image=image))["image"]

  async def test(self, image, outPath):
    out = await self.run(image)
    out.save(outPath, "PNG")
    # self.saveCache()



if __name__ == "__main__":
  target = Image.open("./test.png")
  outPath = "./out.png"

  t = CookieTranslator(debug=True)
  asyncio.run(t.test(target, outPath))
  