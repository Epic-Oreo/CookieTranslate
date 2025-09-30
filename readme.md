
![vlogo](https://raw.githubusercontent.com/Epic-Oreo/CookieTranslate/refs/heads/main/docs/cookieTranslateBanner.png)

With Cookie Translate you can translate single manga panels or bulk translate a entire folder!


Huge shout-out to [Manga OCR](https://github.com/kha-white/manga-ocr) 
and [EasyOCR](https://github.com/JaidedAI/EasyOCR)


# Table of Contents
* [Table of Contents](#table-of-contents)
* [Quick Start](#quick-start)
* [CLI Options](#cli-options)
* [Future Plans](#future)


# Quick Start
Download the project with

```sh
git clone https://github.com/Epic-Oreo/CookieTranslate.git
```

Then open the project

```sh
cd CookieTranslate
```

Install the python packages

```sh
pip install -r requirements.txt
```


Then you can run the program
```sh
python ./server/run.py -i image.png -o image_out.png
```

# CLI Options


| Option              | Example                    | Description                                                 |
|---------------------|----------------------------|------------|
| `-h` `--help`       |                            | Displays help message                                       |
| `-d` `--debug`     |                            | Adds extra debug info to images                             |
| `-i` `--input`      | *`image.png` or `folder/`  | Input file or folder path                                   |
| `-o` `--output`     | *`output.png` or `output/` | Output file or folder path                                  |
| `-t` `--cache-type` | `redis` or `none`          | The type of cache to use, will support file cache in future |
| `-r` `--redis-url` | `localhost:6379` | The url of a redis database if cache type is set to redis |
|`-b` `--bulk`|| Enables bulk mode which can multi-process large numbers of images |
|`--processes`| 4 | Number of processes to use in bulk mode |
|`--font-size`| 20 | Font size of pasted text |


\* = Changes depending if its in bulk mode or not
