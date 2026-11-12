"""Quel support (gem de soutien) améliorerait mon sort principal ?

Aucune IA ici : le moteur de Path of Building 2 calcule tout.

Méthode, en deux phases :
  1. Dépistage : on ajoute un par un chaque support valide pour ton sort (en plus des
     tiens, sans limite d'emplacements) et on mesure le gain de DPS.
  2. Vérification : pour les meilleurs candidats, on teste de vrais remplacements
     (candidat à la place d'un de tes supports actuels) et on mesure DPS, vie et
     résistances, car un gain de DPS qui casse tes résistances n'est pas un vrai gain.

Usage (depuis le dossier pob-mcp) :
    .venv\\Scripts\\python meilleur_support.py mon_build.txt        -> 5 meilleurs candidats vérifiés
    .venv\\Scripts\\python meilleur_support.py mon_build.txt 8      -> 8 meilleurs candidats vérifiés

Ce script a besoin de test_avant_apres.py (même dossier).
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from pob_mcp.bridge import BridgeError, BridgeManager
from pob_mcp.locate import locate_luajit, locate_pob
from test_avant_apres import decode_pob_code, pct, read_stats

RESISTS = ["FireResist", "ColdResist", "LightningResist", "ChaosResist"]


def label(gem: dict) -> str:
    return gem.get("nameSpec") or gem.get("gemId") or gem.get("skillId") or "?"


async def load(bridge, source: str) -> None:
    path = Path(source)
    if path.suffix.lower() == ".txt" and path.is_file():
        source = path.read_text(encoding="utf-8").strip()
    xml = source if source.lstrip().startswith(("<?xml", "<PathOfBuilding")) else decode_pob_code(source)
    await bridge.call("load_build_xml", {"xml": xml, "name": "mon-build"})


async def run(bridge, source: str, top_n: int) -> None:
    print("Chargement du build...")
    await load(bridge, source)

    character = await bridge.call("get_character")
    print(
        f"Niveau {character.get('level')} - {character.get('className', '?')}"
        f" / {character.get('ascendClassName', 'sans ascendance')}"
    )

    skills = await bridge.call("get_skills")
    main_index = skills.get("mainSocketGroup")
    group = next((g for g in skills["socketGroups"] if g["index"] == main_index), None)
    if group is None:
        print("Aucun sort principal trouvé dans ce build.")
        return

    # Quels gems sont des supports ? On compare par identifiant et par nom.
    all_supports = await bridge.call("list_gems", {"onlySupports": True, "limit": 5000})
    support_ids = {g["gemId"] for g in all_supports["gems"]}
    support_names = {g["name"].lower() for g in all_supports["gems"]}

    def is_support(gem: dict) -> bool:
        return gem.get("gemId") in support_ids or str(gem.get("nameSpec") or "").lower() in support_names

    current = [g for g in group["gems"] if g["enabled"] and is_support(g)]
    active = [g for g in group["gems"] if g["enabled"] and not is_support(g)]
    print(f"\nSort principal : {label(active[0]) if active else '?'}")
    print("Supports actuels : " + (", ".join(label(g) for g in current) or "aucun"))
    if not current:
        print("Aucun support à remplacer : rien à comparer.")
        return

    present_ids = {g.get("gemId") for g in group["gems"]}
    present_names = {str(g.get("nameSpec") or "").lower() for g in group["gems"]}
    valid = await bridge.call("list_valid_supports", {"groupIndex": main_index})
    candidates = [
        s
        for s in valid["supports"]
        if s["gemId"] not in present_ids and s["name"].lower() not in present_names
    ]
    if not candidates:
        print("Aucun autre support valide pour ce sort.")
        return

    base = await read_stats(bridge)
    print(f"DPS actuel : {base['CombinedDPS']:,.1f}")

    # ---- Phase 1 : dépistage -------------------------------------------------
    print(f"\nPhase 1 : test de {len(candidates)} supports (ça peut prendre un moment)...")
    started = time.time()
    screened = []
    for i, cand in enumerate(candidates, 1):
        added = await bridge.call("add_gem", {"groupIndex": main_index, "gemId": cand["gemId"], "level": 1})
        stats = await read_stats(bridge)
        await bridge.call("remove_gem", {"groupIndex": main_index, "gemIndex": added["gemIndex"]})
        screened.append((cand, stats))
        if i % 10 == 0 or i == len(candidates):
            print(f"  {i}/{len(candidates)} testés ({time.time() - started:.0f} s)", flush=True)

    screened.sort(key=lambda item: item[1]["CombinedDPS"], reverse=True)
    gainers = [(c, s) for c, s in screened if s["CombinedDPS"] > base["CombinedDPS"]]

    print("\nMeilleurs ajouts (en plus de tes supports actuels, sans limite d'emplacements) :")
    if not gainers:
        print("  aucun support n'augmente le DPS.")
        return
    for cand, stats in gainers[:10]:
        print(f"  {cand['name']:<30} DPS {stats['CombinedDPS']:>12,.1f}  ({pct(base['CombinedDPS'], stats['CombinedDPS'])})")

    # ---- Phase 2 : vrais remplacements --------------------------------------
    finalists = gainers[:top_n]
    total = len(finalists) * len(current)
    print(f"\nPhase 2 : {total} remplacements testés pour de vrai...")
    swaps = []
    for cand, _ in finalists:
        for old in current:
            params = {"groupIndex": main_index, "gemIndex": old["index"]}
            await bridge.call("set_gem", {**params, "enabled": False})
            added = await bridge.call(
                "add_gem",
                {"groupIndex": main_index, "gemId": cand["gemId"], "level": int(old.get("level") or 1)},
            )
            stats = await read_stats(bridge)
            await bridge.call("remove_gem", {"groupIndex": main_index, "gemIndex": added["gemIndex"]})
            await bridge.call("set_gem", {**params, "enabled": True})
            swaps.append((label(old), cand["name"], stats))

    swaps.sort(key=lambda item: item[2]["CombinedDPS"], reverse=True)
    print("\nMeilleurs remplacements :")
    for old_name, new_name, stats in swaps[:10]:
        if stats["CombinedDPS"] <= base["CombinedDPS"]:
            continue
        notes = []
        if stats["Life"] != base["Life"]:
            notes.append(f"vie {stats['Life'] - base['Life']:+,.0f}")
        if stats["TotalEHP"] != base["TotalEHP"]:
            notes.append(f"EHP {pct(base['TotalEHP'], stats['TotalEHP'])}")
        if any(stats[r] < base[r] for r in RESISTS):
            notes.append("ATTENTION : resistances en baisse")
        print(
            f"  {old_name} -> {new_name}\n"
            f"      DPS {base['CombinedDPS']:,.1f} -> {stats['CombinedDPS']:,.1f}"
            f"  ({pct(base['CombinedDPS'], stats['CombinedDPS'])})"
            + (f"   [{' ; '.join(notes)}]" if notes else "")
        )
    if not any(s["CombinedDPS"] > base["CombinedDPS"] for _, _, s in swaps):
        print("  aucun remplacement n'augmente le DPS : tes supports actuels sont déjà les meilleurs.")

    check = await read_stats(bridge)
    if abs(check["CombinedDPS"] - base["CombinedDPS"]) > 1e-6 * max(1.0, abs(base["CombinedDPS"])):
        print("\nAttention : le build n'est pas revenu exactement à son état de départ.")
    else:
        print("\nBuild remis à son état de départ (vérifié).")
    print(f"Durée totale : {time.time() - started:.0f} s")
    print("Rappel : ce sont des chiffres de PoB avec la configuration enregistrée dans ton build.")


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage : python meilleur_support.py mon_build.txt [nombre_de_candidats]")
        sys.exit(1)
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    pob = locate_pob()
    luajit = locate_luajit()
    manager = BridgeManager(pob, luajit)
    try:
        bridge = await manager.primary()
        await run(bridge, sys.argv[1], top_n)
    except BridgeError as exc:
        print(f"\nErreur du pont PoB : {exc}")
        sys.exit(1)
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
