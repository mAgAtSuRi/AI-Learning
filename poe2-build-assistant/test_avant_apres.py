"""Test avant/après avec le vrai moteur de Path of Building 2, via le pont de pob-mcp.

Aucune IA ici : on charge un build, on lit les stats calculées par PoB, on change
quelque chose, on relit les stats et on affiche la différence.

Usage (depuis le dossier pob-mcp) :
    .venv\\Scripts\\python test_avant_apres.py                 -> mode démo (build vide + 1 gem)
    .venv\\Scripts\\python test_avant_apres.py mon_build.txt   -> ton build (fichier texte contenant le code PoB2)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import sys
import zlib
from pathlib import Path

from pob_mcp.bridge import BridgeError, BridgeManager
from pob_mcp.locate import locate_luajit, locate_pob

# Le pont affiche des lignes de chargement qui ne sont pas du JSON : on masque ces avertissements.
logging.basicConfig(level=logging.ERROR)
logging.getLogger("pob_mcp").setLevel(logging.ERROR)


def decode_pob_code(code: str) -> str:
    """Transforme un code de partage PoB en XML, avec le zlib de Python.

    On le fait ici plutôt que dans le pont : sur ta machine, la décompression zlib
    de PoB ne répond pas, alors que celle de Python marche.
    """
    cleaned = re.sub(r"\s+", "", code).replace("-", "+").replace("_", "/")
    cleaned += "=" * (-len(cleaned) % 4)
    try:
        return zlib.decompress(base64.b64decode(cleaned)).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - on veut un message clair quelle que soit la cause
        raise BridgeError(f"code PoB illisible ({exc}) : est-il complet ?") from exc

KEYS = [
    "CombinedDPS",
    "Life",
    "EnergyShield",
    "TotalEHP",
    "FireResist",
    "ColdResist",
    "LightningResist",
    "ChaosResist",
]


async def read_stats(bridge) -> dict[str, float]:
    result = await bridge.call("get_stats", {"fields": KEYS})
    # PoB renvoie null pour une stat absente : on la traite comme 0.
    return {key: float(result["stats"].get(key) or 0) for key in KEYS}


def show(title: str, stats: dict[str, float]) -> None:
    print(f"\n{title}")
    for key in KEYS:
        print(f"  {key:<16} {stats[key]:>14,.1f}")


def pct(before: float, after: float) -> str:
    if before == 0:
        return "n/a" if after == 0 else "(depuis 0)"
    return f"{(after - before) / before * 100:+.1f} %"


def show_diff(before: dict[str, float], after: dict[str, float]) -> None:
    print(f"\n  {'stat':<16} {'avant':>14} {'après':>14}   variation")
    for key in KEYS:
        b, a = before[key], after[key]
        if b != a:
            print(f"  {key:<16} {b:>14,.1f} {a:>14,.1f}   {pct(b, a)}")
    if all(before[k] == after[k] for k in KEYS):
        print("  (aucune stat suivie n'a changé)")


async def demo(bridge) -> None:
    """Build vide : on ajoute un sort puis on monte son niveau, et on regarde la différence."""
    print("Mode démo : build vide + un sort (Fireball).")
    await bridge.call("new_build", {"name": "Demo"})

    found = await bridge.call("list_gems", {"query": "fireball", "onlySupports": False, "limit": 10})
    gem = next((g for g in found["gems"] if g["name"].lower() == "fireball"), None)
    if gem is None:
        names = ", ".join(g["name"] for g in found["gems"]) or "aucun résultat"
        print(f"Gem 'Fireball' introuvable. Résultats de la recherche : {names}")
        return
    print(f"Gem trouvée : {gem['name']} ({gem['gemId']})")

    group = await bridge.call("add_socket_group", {"label": "Demo"})
    group_index = group["groupIndex"]
    added = await bridge.call("add_gem", {"groupIndex": group_index, "gemId": gem["gemId"], "level": 1})
    gem_index = added["gemIndex"]

    before = await read_stats(bridge)
    show("Stats avec la gem au niveau 1 :", before)

    await bridge.call("set_gem", {"groupIndex": group_index, "gemIndex": gem_index, "level": 10})
    after = await read_stats(bridge)

    print("\nAprès passage de la gem au niveau 10 :")
    show_diff(before, after)
    if before["CombinedDPS"] == 0 and after["CombinedDPS"] == 0:
        print("\nLe DPS reste à 0 : le moteur n'a pas résolu la gem. Colle-moi cette sortie, on regardera.")


async def analyse_build(bridge, source: str) -> None:
    """Ton build : on mesure ce que chaque gem du sort principal apporte (on la coupe puis on la remet)."""
    path = Path(source)
    if path.suffix.lower() == ".txt" and path.is_file():
        source = path.read_text(encoding="utf-8").strip()

    print("Chargement du build...")
    xml = source if source.lstrip().startswith(("<?xml", "<PathOfBuilding")) else decode_pob_code(source)
    await bridge.call("load_build_xml", {"xml": xml, "name": "mon-build"})

    character = await bridge.call("get_character")
    print(
        f"Niveau {character.get('level')} - {character.get('className', '?')}"
        f" / {character.get('ascendClassName', 'sans ascendance')}"
    )

    base = await read_stats(bridge)
    show("Stats actuelles :", base)

    skills = await bridge.call("get_skills")
    main_index = skills.get("mainSocketGroup")
    group = next((g for g in skills["socketGroups"] if g["index"] == main_index), None)
    if group is None:
        print("\nAucun sort principal trouvé dans ce build.")
        return

    print(f"\nSort principal (groupe {main_index}) :")
    for gem in group["gems"]:
        label = gem.get("nameSpec") or gem.get("gemId") or gem.get("skillId") or "?"
        etat = "actif" if gem["enabled"] else "désactivé"
        print(f"  {gem['index']}. {label} (niveau {gem.get('level')}, {etat})")

    print("\nImpact de chaque gem (DPS sans elle, par rapport à maintenant) :")
    for gem in group["gems"]:
        if not gem["enabled"]:
            continue
        label = gem.get("nameSpec") or gem.get("gemId") or gem.get("skillId") or "?"
        params = {"groupIndex": main_index, "gemIndex": gem["index"]}
        await bridge.call("set_gem", {**params, "enabled": False})
        without = await read_stats(bridge)
        await bridge.call("set_gem", {**params, "enabled": True})
        print(
            f"  sans {label:<30} DPS {without['CombinedDPS']:>12,.1f}"
            f"  ({pct(base['CombinedDPS'], without['CombinedDPS'])})"
        )

    check = await read_stats(bridge)
    if abs(check["CombinedDPS"] - base["CombinedDPS"]) > 1e-6 * max(1.0, abs(base["CombinedDPS"])):
        print("\nAttention : le build n'est pas revenu exactement à son état de départ.")
    else:
        print("\nBuild remis à son état de départ (vérifié).")


async def main() -> None:
    pob = locate_pob()
    luajit = locate_luajit()
    manager = BridgeManager(pob, luajit)
    try:
        bridge = await manager.primary()
        if len(sys.argv) > 1:
            await analyse_build(bridge, sys.argv[1])
        else:
            await demo(bridge)
    except BridgeError as exc:
        print(f"\nErreur du pont PoB : {exc}")
        sys.exit(1)
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
