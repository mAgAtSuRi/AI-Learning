"""Calibration : le DPS de PoB colle-t-il à celui du jeu quand on règle les conditions ?

PoB ne devine pas ton état réel (mana plein, sorts lancés récemment, buffs...). Ce script
mesure le DPS du sort principal dans deux situations :
  1. configuration par défaut du build,
  2. avec les réglages que tu lui donnes (ex. mana plein, 3 sorts différents lancés).
Pour chaque situation, il retire aussi les gems demandés pour voir leur vraie contribution.

Usage (depuis le dossier pob-mcp) :
    .\\.venv\\Scripts\\python calibrage.py mon_build.txt
    .\\.venv\\Scripts\\python calibrage.py mon_build.txt conditionFullMana=true multiplierNonInstantSpellCastRecently=3
    .\\.venv\\Scripts\\python calibrage.py mon_build.txt conditionFullMana=true --sans "Zenith II" "Rapid Casting III"

Réglages : nom=valeur (true/false pour une case, un nombre pour un compteur).
Par défaut, les gems retirés sont "Zenith II" et "Rapid Casting III".
Ce script a besoin de test_avant_apres.py (même dossier).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pob_mcp.bridge import BridgeError, BridgeManager
from pob_mcp.locate import locate_luajit, locate_pob
from test_avant_apres import decode_pob_code, pct


def label(gem: dict) -> str:
    return gem.get("nameSpec") or gem.get("gemId") or gem.get("skillId") or "?"


def parse_value(text: str):
    low = text.lower()
    if low in ("true", "vrai", "oui"):
        return True
    if low in ("false", "faux", "non"):
        return False
    try:
        return int(text)
    except ValueError:
        return float(text)


async def dps(bridge) -> float:
    stats = (await bridge.call("get_stats", {"fields": ["CombinedDPS"]}))["stats"]
    return float(stats.get("CombinedDPS") or 0)


async def measure(bridge, group: dict, main_index: int, names: list[str]) -> tuple[float, dict[str, float]]:
    base = await dps(bridge)
    without: dict[str, float] = {}
    for name in names:
        gem = next((g for g in group["gems"] if label(g).lower() == name.lower()), None)
        if gem is None:
            continue
        params = {"groupIndex": main_index, "gemIndex": gem["index"]}
        await bridge.call("set_gem", {**params, "enabled": False})
        without[label(gem)] = await dps(bridge)
        await bridge.call("set_gem", {**params, "enabled": True})
    return base, without


def report(title: str, base: float, without: dict[str, float]) -> None:
    print(f"\n{title}")
    print(f"  DPS du sort principal : {base:>12,.1f}")
    for name, value in without.items():
        print(f"  sans {name:<22} {value:>12,.1f}  ({pct(base, value)})")


async def run(bridge, source: str, settings: dict, names: list[str]) -> None:
    path = Path(source)
    if path.suffix.lower() == ".txt" and path.is_file():
        source = path.read_text(encoding="utf-8").strip()
    xml = source if source.lstrip().startswith(("<?xml", "<PathOfBuilding")) else decode_pob_code(source)
    await bridge.call("load_build_xml", {"xml": xml, "name": "calibrage"})

    skills = await bridge.call("get_skills")
    main_index = skills.get("mainSocketGroup")
    group = next((g for g in skills["socketGroups"] if g["index"] == main_index), None)
    if group is None:
        print("Aucun sort principal trouvé.")
        return

    base, without = await measure(bridge, group, main_index, names)
    report("1. Configuration par défaut du build", base, without)

    if not settings:
        print("\nAucun réglage donné : relance avec par exemple  conditionFullMana=true")
        return

    for var, value in settings.items():
        await bridge.call("set_config", {"var": var, "value": value})
    print("\nRéglages appliqués : " + ", ".join(f"{k}={v}" for k, v in settings.items()))
    base2, without2 = await measure(bridge, group, main_index, names)
    report("2. Avec tes réglages", base2, without2)
    print(f"\nVariation du DPS de base grâce aux réglages : {pct(base, base2)}")
    print("Compare avec ton DPS en jeu (ex. 90k) : si l'écart est de quelques % seulement, la calibration est bonne.")


async def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    source, rest = args[0], args[1:]
    names = ["Zenith II", "Rapid Casting III"]
    if "--sans" in rest:
        cut = rest.index("--sans")
        names = rest[cut + 1 :] or names
        rest = rest[:cut]
    settings = {}
    for item in rest:
        if "=" not in item:
            print(f"Réglage ignoré (format nom=valeur attendu) : {item}")
            continue
        var, _, value = item.partition("=")
        settings[var.strip()] = parse_value(value.strip())

    pob = locate_pob()
    luajit = locate_luajit()
    manager = BridgeManager(pob, luajit)
    try:
        bridge = await manager.primary()
        await run(bridge, source, settings, names)
    except BridgeError as exc:
        print(f"\nErreur du pont PoB : {exc}")
        sys.exit(1)
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
