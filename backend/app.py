import base64
import mimetypes
import os
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

try:
    from mutagen.mp4 import MP4, MP4Cover
except ImportError:
    MP4 = None
    MP4Cover = None


app = FastAPI()

# 家庭内LAN開発用：
# localhost:3000 だけでなく、192.168.x.x:3000 からのアクセスも許可する
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

RADIKO_DIR = Path(os.getenv("RADIKO_DIR", "sample_programs"))

AUDIO_EXTENSIONS = {
    ".m4a",
    ".mp3",
    ".aac",
    ".wav",
}

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

THUMBNAIL_FILENAMES = {
    "folder.jpg",
    "folder.jpeg",
    "folder.png",
    "folder.webp",
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "cover.webp",
    "Folder.jpg",
    "Folder.jpeg",
    "Folder.png",
    "Folder.webp",
}


def make_program_id(raw_name: str) -> str:
    encoded = base64.urlsafe_b64encode(raw_name.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def normalize_title(title: str) -> str:
    return (
        title
        .replace("オールナイトニッポンX(クロス)", "ANNX")
        .replace("オールナイトニッポンX", "ANNX")
        .replace("オールナイトニッポン0(ZERO)", "ANN0")
        .replace("オールナイトニッポン０(ZERO)", "ANN0")
        .replace("オールナイトニッポンZERO", "ANN0")
        .replace("オールナイトニッポン０", "ANN0")
        .replace("オールナイトニッポン0", "ANN0")
        .replace("オールナイトニッポン", "ANN")
    )


def parse_program_name(name: str):
    network = ""
    category = ""
    title = name

    if name.startswith("TBS_JUNK-"):
        network = "TBS"
        category = "JUNK"
        title = name.replace("TBS_JUNK-", "")

    elif name.startswith("LFR_"):
        network = "ニッポン放送"
        category = "ANN"
        title = name.replace("LFR_", "")

    elif name.startswith("FMJ_"):
        network = "J-WAVE"
        category = "GURU"
        title = name.replace("FMJ_", "")

    elif name.startswith("IBS_"):
        network = "LuckyFM"
        category = "ANN"
        title = name.replace("IBS_", "")

    elif name.startswith("JORF_"):
        network = "ラジオ日本"
        category = "その他"
        title = name.replace("JORF_", "")

    title = normalize_title(title)
    program_id = make_program_id(name)

    return {
        "id": program_id,
        "title": title,
        "network": network,
        "category": category,
        "raw_name": name,
        "thumbnail_url": f"/programs/{program_id}/thumbnail",
    }


def get_recorded_programs():
    if not RADIKO_DIR.exists():
        return []

    programs = []

    for p in RADIKO_DIR.iterdir():
        if not p.is_dir():
            continue

        if p.name.startswith("."):
            continue

        if p.name in ["old", "TBS"]:
            continue

        programs.append(parse_program_name(p.name))

    return sorted(programs, key=lambda x: x["title"])


def get_recommendation_candidates():
    return [
        {
            "id": "recommend-odoriba",
            "title": "空気階段の踊り場",
            "network": "TBS",
            "category": "おすすめ",
            "reason": "JUNK系・芸人雑談が好きそうだから",
            "raw_name": "recommend-odoriba",
            "thumbnail_url": "",
        },
        {
            "id": "recommend-sakuma-ann0",
            "title": "佐久間宣行のANN0",
            "network": "ニッポン放送",
            "category": "おすすめ",
            "reason": "ANN0系の深夜トークと相性が良さそうだから",
            "raw_name": "recommend-sakuma-ann0",
            "thumbnail_url": "",
        },
        {
            "id": "recommend-audrey-ann",
            "title": "オードリーのANN",
            "network": "ニッポン放送",
            "category": "おすすめ",
            "reason": "芸人の長尺フリートーク好き向け",
            "raw_name": "recommend-audrey-ann",
            "thumbnail_url": "",
        },
        {
            "id": "recommend-shinku",
            "title": "真空ジェシカのラジオ父ちゃん",
            "network": "TBS Podcast",
            "category": "おすすめ",
            "reason": "若手芸人ラジオ好き向け",
            "raw_name": "recommend-shinku",
            "thumbnail_url": "",
        },
        {
            "id": "recommend-sanshiro-ann0",
            "title": "三四郎のANN0",
            "network": "ニッポン放送",
            "category": "おすすめ",
            "reason": "ANN0好き向け",
            "raw_name": "recommend-sanshiro-ann0",
            "thumbnail_url": "",
        },
        {
            "id": "recommend-hakuzan",
            "title": "問わず語りの神田伯山",
            "network": "TBS",
            "category": "おすすめ",
            "reason": "爆笑問題・山里のトークが好きなら刺さりそうだから",
            "raw_name": "recommend-hakuzan",
            "thumbnail_url": "",
        },
    ]


def recommendations():
    recorded_titles = [
        program["title"] for program in get_recorded_programs()
    ]

    return [
        program
        for program in get_recommendation_candidates()
        if program["title"] not in recorded_titles
    ]


def get_all_programs():
    return get_recorded_programs() + recommendations()


def find_program(program_id: str):
    for program in get_all_programs():
        if program["id"] == program_id:
            return program

    return None


def get_program_folder(program_id: str):
    program = find_program(program_id)

    if not program:
        return None

    if program["category"] == "おすすめ":
        return None

    folder = RADIKO_DIR / program["raw_name"]

    if not folder.exists() or not folder.is_dir():
        return None

    return folder


def get_safe_file_path(folder: Path, filename: str):
    decoded_filename = unquote(filename)
    file_path = folder / decoded_filename

    try:
        resolved_folder = folder.resolve()
        resolved_file = file_path.resolve()
    except FileNotFoundError:
        return None

    if resolved_folder not in resolved_file.parents:
        return None

    if not resolved_file.exists() or not resolved_file.is_file():
        return None

    return resolved_file


def get_thumbnail_file(program_id: str):
    folder = get_program_folder(program_id)

    if not folder:
        return None

    for filename in THUMBNAIL_FILENAMES:
        thumbnail_path = folder / filename

        if thumbnail_path.exists() and thumbnail_path.is_file():
            return thumbnail_path

    target_names = {name.lower() for name in THUMBNAIL_FILENAMES}

    for file in folder.iterdir():
        if not file.is_file():
            continue

        if file.name.lower() in target_names:
            return file

    for file in folder.iterdir():
        if not file.is_file():
            continue

        if file.suffix.lower() in IMAGE_EXTENSIONS:
            return file

    return None


def get_sidecar_episode_thumbnail(audio_file: Path):
    for image_extension in IMAGE_EXTENSIONS:
        image_file = audio_file.with_suffix(image_extension)

        if image_file.exists() and image_file.is_file():
            return image_file

    return None


def get_embedded_artwork(audio_file: Path):
    if MP4 is None:
        return None

    if audio_file.suffix.lower() not in {".m4a", ".mp4"}:
        return None

    try:
        audio = MP4(str(audio_file))

        if not audio.tags:
            return None

        covers = audio.tags.get("covr")

        if not covers:
            return None

        cover = covers[0]
        image_bytes = bytes(cover)
        media_type = "image/jpeg"

        if MP4Cover is not None:
            if cover.imageformat == MP4Cover.FORMAT_PNG:
                media_type = "image/png"
            elif cover.imageformat == MP4Cover.FORMAT_JPEG:
                media_type = "image/jpeg"

        return {
            "content": image_bytes,
            "media_type": media_type,
        }

    except Exception:
        return None


def get_episode_files(program_id: str):
    folder = get_program_folder(program_id)

    if not folder:
        return []

    episodes = []

    for file in folder.iterdir():
        if not file.is_file():
            continue

        if file.suffix.lower() not in AUDIO_EXTENSIONS:
            continue

        stat = file.stat()
        encoded_filename = quote(file.name, safe="")

        episodes.append(
            {
                "filename": file.name,
                "title": file.stem,
                "size": stat.st_size,
                "updated_at": stat.st_mtime,
                "thumbnail_url": f"/programs/{program_id}/episodes/{encoded_filename}/thumbnail",
                "audio_url": f"/audio/{program_id}/{encoded_filename}",
            }
        )

    return sorted(
        episodes,
        key=lambda x: x["updated_at"],
        reverse=True,
    )


@app.get("/")
def root():
    return {
        "message": "RadioFlix API",
        "radiko_dir": str(RADIKO_DIR),
        "mutagen_available": MP4 is not None,
    }


@app.get("/programs")
@app.get("/api/programs")
def programs():
    return get_recorded_programs()


@app.get("/recommendations")
@app.get("/api/recommendations")
def recommendation_api():
    return recommendations()


@app.get("/programs/{program_id}")
@app.get("/api/programs/{program_id}")
def program_detail(program_id: str):
    program = find_program(program_id)

    if not program:
        raise HTTPException(status_code=404, detail="Program not found")

    return program


@app.get("/programs/{program_id}/thumbnail")
@app.get("/api/programs/{program_id}/thumbnail")
def program_thumbnail(program_id: str):
    thumbnail_file = get_thumbnail_file(program_id)

    if not thumbnail_file:
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    media_type, _ = mimetypes.guess_type(str(thumbnail_file))

    return FileResponse(
        thumbnail_file,
        media_type=media_type or "image/jpeg",
        headers={
            "Content-Disposition": "inline"
        },
    )


@app.get("/programs/{program_id}/debug-files")
@app.get("/api/programs/{program_id}/debug-files")
def program_debug_files(program_id: str):
    folder = get_program_folder(program_id)

    if not folder:
        raise HTTPException(status_code=404, detail="Program folder not found")

    files = []

    for file in folder.iterdir():
        files.append(
            {
                "name": file.name,
                "is_file": file.is_file(),
                "is_dir": file.is_dir(),
                "suffix": file.suffix,
                "path": str(file),
            }
        )

    return {
        "program_id": program_id,
        "radiko_dir": str(RADIKO_DIR),
        "folder": str(folder),
        "folder_exists": folder.exists(),
        "mutagen_available": MP4 is not None,
        "files": files,
    }


@app.get("/programs/{program_id}/episodes")
@app.get("/api/programs/{program_id}/episodes")
def program_episodes(program_id: str):
    return get_episode_files(program_id)


@app.get("/programs/{program_id}/episodes/{filename:path}/thumbnail")
@app.get("/api/programs/{program_id}/episodes/{filename:path}/thumbnail")
def episode_thumbnail(program_id: str, filename: str):
    folder = get_program_folder(program_id)

    if not folder:
        raise HTTPException(status_code=404, detail="Program folder not found")

    audio_file = get_safe_file_path(folder, filename)

    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")

    if audio_file.suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported audio file")

    sidecar_thumbnail = get_sidecar_episode_thumbnail(audio_file)

    if sidecar_thumbnail:
        media_type, _ = mimetypes.guess_type(str(sidecar_thumbnail))

        return FileResponse(
            sidecar_thumbnail,
            media_type=media_type or "image/jpeg",
            headers={
                "Content-Disposition": "inline"
            },
        )

    embedded_artwork = get_embedded_artwork(audio_file)

    if embedded_artwork:
        return Response(
            content=embedded_artwork["content"],
            media_type=embedded_artwork["media_type"],
            headers={
                "Content-Disposition": "inline"
            },
        )

    program_thumbnail_file = get_thumbnail_file(program_id)

    if program_thumbnail_file:
        media_type, _ = mimetypes.guess_type(str(program_thumbnail_file))

        return FileResponse(
            program_thumbnail_file,
            media_type=media_type or "image/jpeg",
            headers={
                "Content-Disposition": "inline"
            },
        )

    raise HTTPException(status_code=404, detail="Episode thumbnail not found")


@app.get("/audio/{program_id}/{filename:path}")
@app.get("/api/audio/{program_id}/{filename:path}")
def audio_file(program_id: str, filename: str):
    folder = get_program_folder(program_id)

    if not folder:
        raise HTTPException(status_code=404, detail="Program folder not found")

    resolved_file = get_safe_file_path(folder, filename)

    if not resolved_file:
        raise HTTPException(status_code=404, detail="Audio file not found")

    if resolved_file.suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported audio file")

    media_type, _ = mimetypes.guess_type(str(resolved_file))

    return FileResponse(
        resolved_file,
        media_type=media_type or "audio/mp4",
        filename=resolved_file.name,
    )