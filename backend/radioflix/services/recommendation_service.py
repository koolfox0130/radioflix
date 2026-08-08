from radioflix.services.program_service import ProgramService


class RecommendationService:
    def __init__(self, program_service: ProgramService):
        self.program_service = program_service

    def get_recommendation_candidates(self):
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

    def recommendations(self):
        recorded_titles = [
            program["title"]
            for program in self.program_service.get_recorded_programs()
        ]

        return [
            program
            for program in self.get_recommendation_candidates()
            if program["title"] not in recorded_titles
        ]

    def find_recommendation(self, program_id: str):
        for program in self.recommendations():
            if program["id"] == program_id:
                return program

        return None
