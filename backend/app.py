import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException

app = FastAPI()

RADIKO_DIR = Path(os.getenv("RADIKO_DIR", "sample_programs"))


def make_program_id(raw_name: str) -> str:
    program_id = raw_name.lower()
    program_id = re.sub(r"[^a-z0-9ぁ-んァ-ン一-龥ー]+", "-", program_id)
    program_id = program_id.strip("-")
    return program_id


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


@app.get("/")
def root():
    return {
        "message": "RadioFlix API",
        "radiko_dir": str(RADIKO_DIR),
    }


@app.get("/programs")
def programs():
    return get_recorded_programs()


@app.get("/recommendations")
def recommendations():
    recorded_titles = [
        program["title"] for program in get_recorded_programs()
    ]

    return [
        program
        for program in get_recommendation_candidates()
        if program["title"] not in recorded_titles
    ]


@app.get("/programs/{program_id}")
def program_detail(program_id: str):
    all_programs = get_recorded_programs() + recommendations()

    for program in all_programs:
        if program["id"] == program_id:
            return program

    raise HTTPException(status_code=404, detail="Program not found")