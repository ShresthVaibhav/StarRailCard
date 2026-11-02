import aiohttp
from typing import Optional, Union
from .api import ApiMiHoMo
from ..model import api_mihomo
from ..tools import http, translator, options, ukrainization
from .error import StarRailCardError
from .hoyolab_parsed import AssetHoYoLabParsed

from pydantic import ValidationError


async def _lenient_characters(client, uid):
    import genshin

    raw = await client._request_starrail_record("avatar/info", uid, payload={"need_wiki": "true"})
    for avatar in raw.get("avatar_list", []):
        for key in ("relics", "ornaments"):
            avatar[key] = [r for r in avatar.get(key) or [] if r.get("main_property") and "wiki" in r]
    return genshin.models.StarRailDetailCharacterResponse(**raw)


LANG_MAP = {
    "cn": "zh-cn",
    "cht": "zh-tw",
    "de": "de-de",
    "en": "en-us",
    "es": "es-es",
    "fr": "fr-fr",
    "id": "id-id",
    "it": "it-it",
    "ja": "ja-jp",
    "ko": "ko-kr",
    "pt": "pt-pt",
    "ru": "ru-ru",
    "th": "th-th",
    "vi": "vi-vn",
    "tr": "tr",
}

class HoYoLabApi:
    """Class for interacting with the MiHoMo API."""

    def __init__(self, uid: str = 0, lang: str = "en"):
        """Initialize the HoYoLabApi object."""
        self.uid: str = uid
        self.lang: str = translator.SUPPORTED_LANGUAGES.get(lang, "en")
        self.ua_lang: str = lang == "en"
        api_mihomo.UA_LANG = False
        if lang == "ua":
            self.ua_lang = True
            api_mihomo.UA_LANG = True
            self.lang = "en"
        
        self.convert_lang = LANG_MAP.get(self.lang)


    async def get(self,cookie: dict, uid: Union[str,int] = 0):
        try:
            import genshin
        except ImportError:
            raise StarRailCardError(100, "Install the genshin.py module\n- pip install genshin")
        
        if uid == 0:
            uid = self.uid
            if uid == 0:
                raise StarRailCardError(5, "Specify UID")
            
        try:
            client = genshin.Client(cookie, game= genshin.Game.STARRAIL, lang= self.convert_lang)
            try:
                data = await client.get_starrail_characters(uid)
            except ValidationError:
                data = await _lenient_characters(client, uid)
            user = await client.get_starrail_user(uid)
        except Exception as e:
            print(e)
            raise

        player = {"player": {
            "uid": str(uid),
            "nickname": user.info.nickname,
            "level": user.info.level,
            "world_level": 0,
            "friend_count": 0,
            "avatar": {"id": "0", "name": user.info.nickname, "icon": user.info.avatar or user.in_game_avatar or ""},
            "signature": "",
            "is_display": True,
            "space_info": {
                "avatar_count": user.stats.avatar_num,
                "achievement_count": user.stats.achievement_num,
                "memory_data": None,
                "universe_level": None,
                "light_cone_count": None,
            },
        }}
        data = await AssetHoYoLabParsed(data, data.property_info).collect()
        
        
        if self.ua_lang:
            await ukrainization.TranslateDataManager().load_translate_data()

        return api_mihomo.MiHoMoApi(player=player["player"], characters= data, dont_update_link = False)
    

    
    
        