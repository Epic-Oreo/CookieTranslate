// ==UserScript==
// @name        Translator
// @namespace   EpicScripts
// @match       http://127.0.0.1:8080/test.html
// @grant       none
// @version     1.0
// @author      EpicOreo
// @description 9/17/2025, 10:51:53 PM
// @require https://ajax.googleapis.com/ajax/libs/jquery/3.4.1/jquery.min.js
// @require https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4

// ==/UserScript==



SERVER="http://127.0.0.1:5000/api"


images = $("img")

for (img of images) {
  const d = document.createElement("div")
  d.classList = "relative group"

  const parent = img.parentElement

  d.appendChild(img)

  const translateButton = document.createElement("button")

  translateButton.innerText = "Translate"


  translateButton.className = "bg-red-500 w-20 h-10 absolute top-2 left-2 rounded-full group-hover:opacity-100 opacity-0 z-[999] cursor-pointer"

  translateButton.onclick = async ()=>{

    translateButton.innerText = "Loading"

    $.getJSON(`${SERVER}/translate?callback=?&url=${img.src}`, function(result) {
      console.log("Returned", result.url)

      if (result.error) {
        console.log("Error:", result.error)
      } else {
        img.src = result.url
      }

      translateButton.innerText = "Translate"
    })
  }


  d.appendChild(translateButton)

  parent.appendChild(d)
}

