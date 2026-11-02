import os
from pathlib import Path

from ..tools import http
from ..tools.json_data import JsonManager
from ..tools.enums import PathData

_STORE = "https://raw.githubusercontent.com/EnkaNetwork/API-docs/master/store/hsr/{name}.json"
_ENKA_CDN = "https://enka.network{path}"


def _cdn(path: str) -> str:
    return _ENKA_CDN.format(path=path)

_LANG_MAP = {
    "zh-cn": "cn", "zh-tw": "cht", "de": "de", "en": "en", "es": "es",
    "fr": "fr", "id": "id", "ja": "jp", "ko": "kr", "pt": "pt", "ru": "ru",
    "th": "th", "vi": "vi",
}


async def _fetch(name: str):
    return await http.AioSession.get(_STORE.format(name=name))


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum()) or "unknown"


_SKILL_POSITIONS = {
    0: {"suffix": "01", "tree_max_level": 6,  "skill_max_level": 10, "type": "Normal",  "type_text": "Basic ATK"},
    1: {"suffix": "02", "tree_max_level": 10, "skill_max_level": 15, "type": "BPSkill", "type_text": "Skill"},
    2: {"suffix": "03", "tree_max_level": 10, "skill_max_level": 15, "type": "Ultra",   "type_text": "Ultimate"},
    3: {"suffix": "04", "tree_max_level": 10, "skill_max_level": 15, "type": "Talent",  "type_text": "Talent"},
    4: {"suffix": "07", "tree_max_level": 1,  "skill_max_level": 1,  "type": "Maze",    "type_text": "Technique"},
}


def _flatten_skill_tree(tree: dict) -> list[str]:
    ids: list[str] = []
    for branch in tree.values():
        ids.extend(str(x) for x in branch.get("AvatarSkills", []))
        for group in branch.get("PropSkills", []):
            ids.extend(str(x) for x in group)
        ids.extend(str(x) for x in branch.get("SummonSkills", []))
    return ids


async def _load(base: Path, lang: str, fname: str) -> dict:
    data = await JsonManager(base / lang / f"{fname}.json").read()
    return data or {}


async def _save(base: Path, lang: str, fname: str, data: dict):
    await JsonManager(base / lang / f"{fname}.json").write(data)


async def gap_fill_assets(lang: str | None = None) -> dict:
    base = PathData.ENKA_INDEX.value

    avatars = await _fetch("avatars")
    weapons = await _fetch("weapons")
    relics_full = await _fetch("relics")
    relics_raw = relics_full.get("Items", {})
    relic_sets_raw = relics_full.get("Sets", {})
    affixes = await _fetch("affixes")
    honker = await _fetch("honker_meta")
    names_by_lang = await _fetch("hsr")
    ranks_raw = await _fetch("ranks")
    skills_raw = await _fetch("skills")

    if lang:
        target_langs = [lang]
    else:
        target_langs = [p.name for p in base.iterdir() if p.is_dir()]

    report = {"characters": [], "light_cones": [], "relics": [], "relic_sets": []}

    equip_promo = honker.get("equipment", {})
    equip_skill = honker.get("equipmentSkill", {})

    for local_lang in target_langs:
        enka_lang_key = next(
            (k for k, v in _LANG_MAP.items() if v == local_lang), "en"
        )
        names = names_by_lang.get(enka_lang_key, {})

        characters = await _load(base, local_lang, "characters")
        ranks_doc = await _load(base, local_lang, "character_ranks")
        trees_doc = await _load(base, local_lang, "character_skill_trees")
        skills_doc = await _load(base, local_lang, "character_skills")
        promotions_doc = await _load(base, local_lang, "character_promotions")

        changed_char = changed_rank = changed_tree = changed_skill = changed_promo = False

        for cid, a in avatars.items():
            if cid in characters:
                continue

            name_hash = str(a.get("AvatarName", {}).get("Hash", ""))
            name = names.get(name_hash) or f"Character {cid}"

            skill_tree_ids = _flatten_skill_tree(a.get("SkillTree", {}))
            rank_ids = [str(x) for x in a.get("RankIDList", [])]
            skill_ids = [str(x) for x in a.get("SkillList", [])]

            splash = a.get("AvatarCutinFrontImgPath", "")
            characters[cid] = {
                "id": cid,
                "name": name,
                "tag": _slug(name),
                "rarity": a.get("Rarity", 4),
                "path": a.get("AvatarBaseType", ""),
                "element": a.get("Element", ""),
                "max_sp": 120,
                "ranks": rank_ids,
                "skills": skill_ids,
                "skill_trees": skill_tree_ids,
                "icon": _cdn(a.get("AvatarSideIconPath", "")),
                "preview": _cdn(splash),
                "portrait": _cdn(splash),
            }
            changed_char = True
            report["characters"].append(cid)

            if cid not in promotions_doc:
                promo = a.get("Promotion", {})
                values = []
                for lvl in sorted(promo, key=int):
                    v = promo[lvl]
                    values.append({
                        "hp": {"base": v.get("HPBase", 0), "step": v.get("HPAdd", 0)},
                        "atk": {"base": v.get("AttackBase", 0), "step": v.get("AttackAdd", 0)},
                        "def": {"base": v.get("DefenceBase", 0), "step": v.get("DefenceAdd", 0)},
                        "spd": {"base": v.get("SpeedBase", 0), "step": 0},
                        "taunt": {"base": v.get("BaseAggro", 0), "step": 0},
                        "crit_rate": {"base": v.get("CriticalChance", 0), "step": 0},
                        "crit_dmg": {"base": v.get("CriticalDamage", 0), "step": 0},
                    })
                promotions_doc[cid] = {"id": cid, "values": values}
                changed_promo = True

            for rid in rank_ids:
                if rid in ranks_doc:
                    continue
                icon_path = ranks_raw.get(rid, {}).get("IconPath", "")
                ranks_doc[rid] = {
                    "id": rid,
                    "name": "",
                    "rank": int(rid[-1]) if rid[-1].isdigit() else 0,
                    "desc": "",
                    "materials": [],
                    "level_up_skills": [],
                    "icon": _cdn(icon_path) if icon_path else f"icon/skill/{cid}_rank{rid[-1]}.png",
                }
                changed_rank = True

            resolved_skill_meta = {}

            for i, pid in enumerate(skill_tree_ids):
                pos = _SKILL_POSITIONS.get(i)
                anchor = f"Point{i + 1:02d}"
                tree_max_level = pos["tree_max_level"] if pos else 1
                icon_path = skills_raw.get(pid, {}).get("IconPath", "")
                icon = _cdn(icon_path) if icon_path else f"icon/skill/{pid}.png"

                level_up_skills = []
                if pos:
                    skill_id = f"{cid}{pos['suffix']}"
                    if skill_id in skill_ids:
                        level_up_skills = [{"id": skill_id, "num": 1}]
                        resolved_skill_meta[skill_id] = (
                            icon, pos["type"], pos["type_text"], pos["skill_max_level"]
                        )

                if pid not in trees_doc:
                    trees_doc[pid] = {
                        "id": pid,
                        "name": "",
                        "max_level": tree_max_level,
                        "desc": "",
                        "params": [],
                        "anchor": anchor,
                        "icon": icon,
                        "pre_points": [],
                        "level_up_skills": level_up_skills,
                        "levels": [{"promotion": 0, "level": 0, "properties": [], "materials": []}],
                    }
                    changed_tree = True

            for sid in skill_ids:
                if sid in skills_doc:
                    continue
                icon, s_type, s_type_text, s_max_level = resolved_skill_meta.get(
                    sid, (f"icon/skill/{sid}.png", "", "", 1)
                )
                skills_doc[sid] = {
                    "id": sid,
                    "name": "",
                    "max_level": s_max_level,
                    "element": a.get("Element", ""),
                    "type": s_type,
                    "type_text": s_type_text,
                    "effect": "",
                    "effect_text": "",
                    "simple_desc": "",
                    "desc": "",
                    "params": [],
                    "icon": icon,
                }
                changed_skill = True

        if changed_char:
            await _save(base, local_lang, "characters", characters)
        if changed_rank:
            await _save(base, local_lang, "character_ranks", ranks_doc)
        if changed_tree:
            await _save(base, local_lang, "character_skill_trees", trees_doc)
        if changed_skill:
            await _save(base, local_lang, "character_skills", skills_doc)
        if changed_promo:
            await _save(base, local_lang, "character_promotions", promotions_doc)

        light_cones = await _load(base, local_lang, "light_cones")
        lc_promo = await _load(base, local_lang, "light_cone_promotions")
        lc_ranks = await _load(base, local_lang, "light_cone_ranks")
        changed_lc = changed_lc_promo = changed_lc_ranks = False

        for wid, w in weapons.items():
            if wid not in light_cones:
                name_hash = str(w.get("EquipmentName", {}).get("Hash", ""))
                name = names.get(name_hash) or f"Light Cone {wid}"
                image_path = w.get("ImagePath", "")
                light_cones[wid] = {
                    "id": wid,
                    "name": name,
                    "tag": _slug(name),
                    "rarity": w.get("Rarity", 3),
                    "path": w.get("AvatarBaseType", ""),
                    "icon": _cdn(image_path) if image_path else f"icon/light_cone/{wid}.png",
                    "preview": _cdn(image_path) if image_path else "",
                    "portrait": _cdn(image_path) if image_path else "",
                }
                changed_lc = True
                report["light_cones"].append(wid)

            if wid not in lc_promo and wid in equip_promo:
                values = []
                for lvl in sorted(equip_promo[wid], key=int):
                    v = equip_promo[wid][lvl]
                    values.append({
                        "hp": {"base": v.get("BaseHP", 0), "step": v.get("HPAdd", 0)},
                        "atk": {"base": v.get("BaseAttack", 0), "step": v.get("AttackAdd", 0)},
                        "def": {"base": v.get("BaseDefence", 0), "step": v.get("DefenceAdd", 0)},
                    })
                lc_promo[wid] = {"id": wid, "values": values}
                changed_lc_promo = True

            if wid not in lc_ranks and wid in equip_skill:
                skill_data = equip_skill[wid]
                properties = []
                for rank in ("1", "2", "3", "4", "5"):
                    props = skill_data.get(rank, {}).get("props", {})
                    properties.append([{"type": k, "value": v} for k, v in props.items()])
                lc_ranks[wid] = {
                    "id": wid,
                    "skill": "",
                    "desc": "",
                    "params": [],
                    "properties": properties,
                }
                changed_lc_ranks = True

        if changed_lc:
            await _save(base, local_lang, "light_cones", light_cones)
        if changed_lc_promo:
            await _save(base, local_lang, "light_cone_promotions", lc_promo)
        if changed_lc_ranks:
            await _save(base, local_lang, "light_cone_ranks", lc_ranks)

        relics_doc = await _load(base, local_lang, "relics")
        main_affix_doc = await _load(base, local_lang, "relic_main_affixes")
        sub_affix_doc = await _load(base, local_lang, "relic_sub_affixes")
        changed_relics = changed_main = changed_sub = False

        for rid, r in relics_raw.items():
            if rid in relics_doc:
                continue
            set_id = str(r.get("SetID", ""))
            set_info = relic_sets_raw.get(set_id, {})
            set_name = names.get(str(set_info.get("Name", ""))) or f"Relic Set {set_id}"
            relics_doc[rid] = {
                "id": rid,
                "set_id": set_id,
                "name": f"{set_name} ({r.get('Type', '')})",
                "rarity": r.get("Rarity", 2),
                "type": r.get("Type", ""),
                "max_level": 6,
                "main_affix_id": str(r.get("MainAffixGroup", "")),
                "sub_affix_id": str(r.get("SubAffixGroup", "")),
                "icon": _cdn(r["Icon"]) if r.get("Icon") else f"icon/relic/{set_id}_{r.get('Type', '')}.png",
            }
            changed_relics = True
            report["relics"].append(rid)

        main_affix = affixes.get("MainAffix", {})
        for group_id, levels in main_affix.items():
            if group_id in main_affix_doc:
                continue
            main_affix_doc[group_id] = levels
            changed_main = True

        sub_affix = affixes.get("SubAffix", {})
        for group_id, levels in sub_affix.items():
            if group_id in sub_affix_doc:
                continue
            sub_affix_doc[group_id] = levels
            changed_sub = True

        if changed_relics:
            await _save(base, local_lang, "relics", relics_doc)
        if changed_main:
            await _save(base, local_lang, "relic_main_affixes", main_affix_doc)
        if changed_sub:
            await _save(base, local_lang, "relic_sub_affixes", sub_affix_doc)

        relic_sets_doc = await _load(base, local_lang, "relic_sets")
        changed_sets = False

        for set_id, s in relic_sets_raw.items():
            if set_id in relic_sets_doc:
                continue
            name_hash = str(s.get("Name", ""))
            name = names.get(name_hash) or f"Relic Set {set_id}"
            set_skills = s.get("SetSkills", {})
            properties = []
            desc = []
            for piece_count in sorted(set_skills, key=int):
                props = set_skills[piece_count].get("props", {})
                properties.append([{"type": k, "value": v} for k, v in props.items()])
                desc.append("")
            if not properties:
                properties = [[]]
                desc = [""]
            relic_sets_doc[set_id] = {
                "id": set_id,
                "name": name,
                "desc": desc,
                "properties": properties,
                "icon": f"icon/relic/{set_id}.png",
            }
            changed_sets = True
            report["relic_sets"].append(set_id)

        if changed_sets:
            await _save(base, local_lang, "relic_sets", relic_sets_doc)

    for k in report:
        report[k] = sorted(set(report[k]))

    return report
