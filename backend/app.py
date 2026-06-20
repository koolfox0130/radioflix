import base64
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

app = FastAPI()

RADIKO_DIR = Path(os.getenv("RADIKO_DIR", "sample_programs"))

AUDIO_EXTENSIONS = {
    ".m4a",
    ".mp3",
    ".aac",
    ".wav",
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

    return {
        "id": make_program_id(name),
        "title": title,
        "network": network,
        "category": category,
        "raw_name": name,
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
        },
        {
            "id": "recommend-sakuma-ann0",
            "title": "佐久間宣行のANN0",
            "network": "ニッポン放送",
            "category": "おすすめ",
            "reason": "ANN0系の深夜トークと相性が良さそうだから",
            "raw_name": "recommend-sakuma-ann0",
        },
        {
            "id": "recommend-audrey-ann",
            "title": "オードリーのANN",
            "network": "ニッポン放送",
            "category": "おすすめ",
            "reason": "芸人の長尺フリートーク好き向け",
            "raw_name": "recommend-audrey-ann",
        },
        {
            "id": "recommend-shinku",
            "title": "真空ジェシカのラジオ父ちゃん",
            "network": "TBS Podcast",
            "category": "おすすめ",
            "reason": "若手芸人ラジオ好き向け",
            "raw_name": "recommend-shinku",
        },
        {
            "id": "recommend-sanshiro-ann0",
            "title": "三四郎のANN0",
            "network": "ニッポン放送",
            "category": "おすすめ",
            "reason": "ANN0好き向け",
            "raw_name": "recommend-sanshiro-ann0",
        },
        {
            "id": "recommend-hakuzan",
            "title": "問わず語りの神田伯山",
            "network": "TBS",
            "category": "おすすめ",
            "reason": "爆笑問題・山里のトークが好きなら刺さりそうだから",
            "raw_name": "recommend-hakuzan",
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

        episodes.append(
            {
                "filename": file.name,
                "title": file.stem,
                "size": stat.st_size,
                "updated_at": stat.st_mtime,
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


@app.get("/programs/{program_id}/episodes")
@app.get("/api/programs/{program_id}/episodes")
def program_episodes(program_id: str):
    return get_episode_files(program_id)


@app.get("/audio/{program_id}/{filename:path}")
@app.get("/api/audio/{program_id}/{filename:path}")
def audio_file(program_id: str, filename: str):
    folder = get_program_folder(program_id)

    if not folder:
        raise HTTPException(status_code=404, detail="Program folder not found")

    decoded_filename = unquote(filename)
    file_path = folder / decoded_filename

    try:
        resolved_folder = folder.resolve()
        resolved_file = file_path.resolve()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Audio file not found")

    if resolved_folder not in resolved_file.parents:
        raise HTTPException(status_code=403, detail="Invalid path")

    if not resolved_file.exists() or not resolved_file.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")

    if resolved_file.suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported audio file")

    media_type, _ = mimetypes.guess_type(str(resolved_file))

    return FileResponse(
        resolved_file,
        media_type=media_type or "audio/mp4",
        filename=resolved_file.name,
    )