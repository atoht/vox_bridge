from app.schemas import LanguageCode


LANGUAGE_NAMES: dict[LanguageCode, str] = {
    "zh": "中文",
    "ja": "日语",
    "en": "英语",
}


def language_name(code: LanguageCode) -> str:
    """把语言代码转换为中文名称，便于构造提示词。"""

    return LANGUAGE_NAMES.get(code, code)
