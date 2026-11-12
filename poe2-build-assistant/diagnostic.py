"""Diagnostic : pourquoi mes chiffres ne sont-ils pas ceux de mon PoB2 ?

Affiche tout ce qu'il faut pour comparer le calcul du script avec ce que PoB2 montre
à l'écran : version de PoB, gems (avec leurs identifiants), configuration enregistrée
dans le build, et plusieurs stats de DPS dans trois situations
(build actuel, sans un gem, avec Unleash ajouté).

Usage (depuis le dossier pob-mcp) :
    .venv\\Scripts\\python diagnostic.py mon_build.txt
    .venv\\Scripts\\python diagnostic.py mon_build.txt "Zenith II" "Rapid Casting III"

Les noms après le fichier sont les gems à retirer pour la comparaison
(par défaut : Zenith II). Ce script a besoin de test_avant_apres.py (même dossier).
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from pob_mcp.bridge import BridgeError, BridgeManager
from pob_mcp.locate import locate_luajit, locate_pob
from test_avant_apres import decode_pob_code

STATS = [
    "TotalDPS",
    "CombinedDPS",
    "FullDPS",
    "AverageDamage",
    "Speed",
    "HitChance",
    "CritChance",
    "CritMultiplier",
    "Repeats",
    "WithPoisonDPS",
    "WithIgniteDPS",
    "WithBleedDPS",
    "TotalDotDPS",
    "ManaCost",
]


def fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    return f"{value:,.2f}"


def label(gem: dict) -> str:
    return gem.get("nameSpec") or gem.get("gemId") or gem.get("skillId") or "?"


async def read_stats(bridge) -> dict:
    return (await bridge.call("get_stats", {"fields": STATS}))["stats"]


def print_table(columns: list[tuple[str, dict]]) -> None:
    print(f"  {'stat':<16}" + "".join(f"{name[:21]:>23}" for name, _ in columns))
    for key in STATS:
        print(f"  {key:<16}" + "".join(f"{fmt(stats.get(key)):>23}" for _, stats in columns))


def pob_version(src_dir: Path) -> str:
    manifest = src_dir / "manifest.xml"
    try:
        match = re.search(r'<Version number="([^"]+)"', manifest.read_text(encoding="utf-8", errors="replace"))
        return match.group(1) if match else "introuvable dans manifest.xml"
    except OSError:
        return "manifest.xml illisible"


async def run(bridge, pob, source: str, remove_names: list[str]) -> None:
    path = Path(source)
    if path.suffix.lower() == ".txt" and path.is_file():
        source = path.read_text(encoding="utf-8").strip()
    xml = source if source.lstrip().startswith(("<?xml", "<PathOfBuilding")) else decode_pob_code(source)
    await bridge.call("load_build_xml", {"xml": xml, "name": "diagnostic"})

    print(f"PoB2 utilisé par le script : version {pob_version(pob.src_dir)}")
    print(f"Dossier : {pob.src_dir}")

    character = await bridge.call("get_character")
    print(f"\nPersonnage : niveau {character.get('level')} - {character.get('className', '?')}"
          f" / {character.get('ascendClassName', 'sans ascendance')}")

    skills = await bridge.call("get_skills")
    main_index = skills.get("mainSocketGroup")
    print(f"\nGroupes de sorts (principal = groupe {main_index}) :")
    for group in skills["socketGroups"]:
        flags = []
        if group["index"] == main_index:
            flags.append("PRINCIPAL")
        if not group["enabled"]:
            flags.append("désactivé")
        print(f"  Groupe {group['index']} {group.get('label') or ''} {' '.join(flags)}")
        for gem in group["gems"]:
            print(
                f"    {gem['index']}. {label(gem):<26} niveau {gem.get('level')}, qualité {gem.get('quality')},"
                f" {'actif' if gem['enabled'] else 'désactivé'}"
                f"   [gemId={gem.get('gemId')} skillId={gem.get('skillId')}]"
            )

    config = (await bridge.call("get_config"))["config"]
    print(f"\nConfiguration enregistrée dans le build ({len(config)} réglages) :")
    for key in sorted(config):
        print(f"  {key} = {config[key]}")
    if not config:
        print("  (aucun réglage : PoB utilise ses valeurs par défaut)")

    group = next((g for g in skills["socketGroups"] if g["index"] == main_index), None)
    if group is None:
        print("\nAucun sort principal.")
        return

    columns: list[tuple[str, dict]] = [("actuel", await read_stats(bridge))]

    for name in remove_names:
        gem = next((g for g in group["gems"] if label(g).lower() == name.lower()), None)
        if gem is None:
            print(f"\n(Gem '{name}' introuvable dans le groupe principal, ignoré.)")
            continue
        params = {"groupIndex": main_index, "gemIndex": gem["index"]}
        await bridge.call("set_gem", {**params, "enabled": False})
        columns.append((f"sans {label(gem)}", await read_stats(bridge)))
        await bridge.call("set_gem", {**params, "enabled": True})

    valid = await bridge.call("list_valid_supports", {"groupIndex": main_index})
    unleash = next((s for s in valid["supports"] if s["name"].lower() == "unleash"), None)
    if unleash is None:
        print("\n(Unleash n'est pas dans la liste des supports valides pour ce sort.)")
    else:
        added = await bridge.call("add_gem", {"groupIndex": main_index, "gemId": unleash["gemId"], "level": 1})
        columns.append(("avec Unleash (ajout)", await read_stats(bridge)))
        await bridge.call("remove_gem", {"groupIndex": main_index, "gemIndex": added["gemIndex"]})

    print("\nStats de dégâts du sort principal selon le scénario :")
    print_table(columns)

    final = await read_stats(bridge)
    if final.get("CombinedDPS") != columns[0][1].get("CombinedDPS"):
        print("\nAttention : le build n'est pas revenu à son état de départ.")
    print("\nÀ comparer avec la colonne de gauche de PoB2 (DPS, vitesse d'incantation, dégâts moyens).")


async def main() -> None:
    if len(sys.argv) < 2:
        print('Usage : python diagnostic.py mon_build.txt ["Zenith II" ...]')
        sys.exit(1)
    remove_names = sys.argv[2:] or ["Zenith II"]
    pob = locate_pob()
    luajit = locate_luajit()
    manager = BridgeManager(pob, luajit)
    try:
        bridge = await manager.primary()
        await run(bridge, pob, sys.argv[1], remove_names)
    except BridgeError as exc:
        print(f"\nErreur du pont PoB : {exc}")
        sys.exit(1)
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
