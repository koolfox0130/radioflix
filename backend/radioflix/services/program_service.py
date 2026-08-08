import base64
from pathlib import Path


class ProgramService:
    def __init__(self, radiko_dir: Path, recommendations):
        self.radiko_dir = radiko_dir
        self.recommendations = recommendations

    def make_program_id(self, raw_name: str) -> str:
        encoded = base64.urlsafe_b64encode(raw_name.encode("utf-8")).decode("ascii")
        return encoded.rstrip("=")

    def normalize_title(self, title: str) -> str:
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

    def parse_program_name(self, name: str):
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

        title = self.normalize_title(title)
        program_id = self.make_program_id(name)

        return {
            "id": program_id,
            "title": title,
            "network": network,
            "category": category,
            "raw_name": name,
            "thumbnail_url": f"/programs/{program_id}/thumbnail",
        }

    def get_recorded_programs(self):
        if not self.radiko_dir.exists():
            return []

        programs = []

        for program_path in self.radiko_dir.iterdir():
            if not program_path.is_dir():
                continue

            if program_path.name.startswith("."):
                continue

            if program_path.name in ["old", "TBS"]:
                continue

            programs.append(self.parse_program_name(program_path.name))

        return sorted(programs, key=lambda x: x["title"])

    def get_all_programs(self):
        return self.get_recorded_programs() + self.recommendations()

    def find_program(self, program_id: str):
        for program in self.get_all_programs():
            if program["id"] == program_id:
                return program

        return None

    def get_program_folder(self, program_id: str):
        program = self.find_program(program_id)

        if not program:
            return None

        if program["category"] == "おすすめ":
            return None

        folder = self.radiko_dir / program["raw_name"]

        if not folder.exists() or not folder.is_dir():
            return None

        return folder
