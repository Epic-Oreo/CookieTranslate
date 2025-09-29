
from io import BytesIO
from quart import Quart, request, jsonify
import requests, base64
from translator import CookieTranslator
from PIL import Image
import hashlib
from os import path

app = Quart(__name__)
BASE_URL = 'http://127.0.0.1:5000'

@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"
  

@app.route("/api/translate", methods=["GET"])
async def translate():
  global cookieTranslate
  url = request.args.get('url')
  print(f"Starting web translate of {url}")
  
  if not url:
    return jsonify({"error": "no url"})
  url_hash = hashlib.sha256(url.encode()).hexdigest()
  savePath = f"./static/translated/{url_hash}.webp"
  
  
  if path.exists(savePath):
    print("Using existing")
    data = {'url': BASE_URL+(savePath[1:])}
    return jsonify(data)
  
  
  if url.startswith("data:image"):
    base64_string = url.split(',')[1]
    img_data = base64.b64decode(base64_string)
  else:
    img_data = requests.get(url).content

  byte_stream = BytesIO(img_data)
  image = Image.open(byte_stream)
  

  
  translated = await cookieTranslate.run(image)
  
  translated.save(savePath, "webp")

  data = {'url': BASE_URL+savePath[1:]}
  return jsonify(data)



@app.after_request
async def after_request(response):
  callback = request.args.get('callback')
  if callback:
    response.data = f"{callback}({(await response.data).decode('utf-8')});"
    response.mimetype = 'application/javascript'

  header = response.headers
  header['Access-Control-Allow-Origin'] = '*'
  header['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
  header['Access-Control-Allow-Methods'] = 'OPTIONS, HEAD, GET, POST, DELETE, PUT'
  return response





if __name__ == "__main__":  
  
  cookieTranslate = CookieTranslator()

  
  app.run(port=5000)