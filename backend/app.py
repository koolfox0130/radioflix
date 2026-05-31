import os
from pathlib import Path

from fastapi import FastAPI

app = FastAPI()

RADIKO_DIR = Path(os.getenv("RADIKO_DIR", "sample_programs"))


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

    return {
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

    candidates = [
        {
            "title": "空気階段の踊り場",
            "network": "TBS",
            "category": "おすすめ",
            "reason": "JUNK系・芸人雑談が好きそうだから",
        },
        {
            "title": "佐久間宣行のオールナイトニッポン0",
            "network": "ニッポン放送",
            "category": "おすすめ",
            "reason": "ANN0系の深夜トークと相性が良さそうだから",
        },
        {
            "title": "オードリーのオールナイトニッポン",
            "network": "ニッポン放送",
            "category": "おすすめ",
            "reason": "芸人の長尺フリートーク好き向け",
        },
        {
            "title": "真空ジェシカのラジオ父ちゃん",
            "network": "TBS Podcast",
            "category": "おすすめ",
            "reason": "若手芸人ラジオ好き向け",
        },
        {
            "title": "三四郎のオールナイトニッポン0",
            "network": "ニッポン放送",
            "category": "おすすめ",
            "reason": "ANN0好き向け",
        },
        {
            "title": "問わず語りの神田伯山",
            "network": "TBS",
            "category": "おすすめ",
            "reason": "爆笑問題・山里系のトークが好きなら刺さりそうだから",
        },
    ]

    return [
        program
        for program in candidates
        if program["title"] not in recorded_titles
    ]