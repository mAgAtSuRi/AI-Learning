"""Quels passifs ajouter (ou retirer) pour améliorer mon build ?

Aucune IA ici : le moteur de Path of Building 2 calcule tout.

  A. Meilleurs ajouts : pour chaque notable / keystone de l'arbre principal pas encore pris
     et atteignable en peu de points, on l'alloue (avec le chemin pour y arriver), on mesure
     DPS / vie / EHP / résistances, puis on remet l'arbre comme avant.
     Classement par gain de DPS PAR POINT dépensé.
  B. Passifs les moins utiles : pour chaque notable / keystone que tu as déjà, on le retire
     et on mesure ce que tu perds. Un faible impact DPS peut cacher un rôle défensif ou utilitaire :
     regarde aussi les colonnes vie / EHP.

Usage (depuis le dossier pob-mcp) :
    .\\.venv\\Scripts\\python meilleurs_passifs2.py mon_build.txt
    .\\.venv\\Scripts\\python meilleurs_passifs2.py mon_build.txt conditionFullMana=true multiplierNonInstantSpellCastRecently=1
    .\\.venv\\Scripts\\python meilleurs_passifs2.py mon_build.txt conditionFullMana=true --cout 4 --top 15

Options :
  nom=valeur   réglages de conditions PoB (comme calibrage.py) : à mettre AVANT de comparer
  --cout N     coût maximal en points pour un ajout (défaut 3)
  --top N      nombre de lignes affichées par classement (défaut 12)

Ce script a besoin de test_avant_apres.py et calibrage.py (même dossier).
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from calibrage import parse_value
from pob_mcp.bridge import BridgeError, BridgeManager
from pob_mcp.locate import locate_luajit, locate_pob
from test_avant_apres import decode_pob_code, pct, read_stats

RESISTS = ["FireResist", "ColdResist", "LightningResist", "ChaosResist"]


async def snapshot(bridge) -> set[int]:
    return set((await bridge.call("get_tree_state"))["allocatedNodes"])


async def restore(bridge, target: set[int]) -> None:
    """Remet exactement les mêmes nœuds alloués qu'au départ."""
    for _ in range(50):
        current = await snapshot(bridge)
        extra = current - target
        if not extra:
            break
        await bridge.call("dealloc_node", {"id": sorted(extra)[0]})
    current = await snapshot(bridge)
    for node_id in sorted(target - current):
        await bridge.call("alloc_node", {"id": node_id})


def same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * max(1.0, abs(a))


def notes(base: dict, stats: dict) -> str:
    out = []
    if stats["Life"] != base["Life"]:
        out.append(f"vie {stats['Life'] - base['Life']:+,.0f}")
    if stats["TotalEHP"] != base["TotalEHP"]:
        out.append(f"EHP {pct(base['TotalEHP'], stats['TotalEHP'])}")
    if any(stats[r] < base[r] for r in RESISTS):
        out.append("ATTENTION : résistances en baisse")
    return " ; ".join(out)


def describe(node: dict) -> str:
    stats = " / ".join(node.get("stats") or [])
    return f"{node['name']} ({stats[:90]})" if stats else str(node["name"])


async def run(bridge, source: str, settings: dict, max_cost: int, top: int) -> None:
    path = Path(source)
    if path.suffix.lower() == ".txt" and path.is_file():
        source = path.read_text(encoding="utf-8").strip()
    xml = source if source.lstrip().startswith(("<?xml", "<PathOfBuilding")) else decode_pob_code(source)

    async def reset() -> None:
        """Recharge le build et les réglages : seul moyen sûr de revenir exactement au départ."""
        await bridge.call("load_build_xml", {"xml": xml, "name": "passifs"})
        for var, value in settings.items():
            await bridge.call("set_config", {"var": var, "value": value})

    await reset()

    character = await bridge.call("get_character")
    print(f"Niveau {character.get('level')} - {character.get('className', '?')} / {character.get('ascendClassName', 'sans ascendance')}")
    if settings:
        print("Réglages : " + ", ".join(f"{k}={v}" for k, v in settings.items()))

    base = await read_stats(bridge)
    target = await snapshot(bridge)
    print(f"DPS actuel : {base['CombinedDPS']:,.1f}   ({len(target)} nœuds alloués)")

    found = await bridge.call(
        "search_tree", {"ascendancyName": False, "limit": 20000}
    )
    nodes = [n for n in found["nodes"] if n["type"] in ("Notable", "Keystone")]
    adds = [n for n in nodes if not n["allocated"] and n.get("pathCost") is not None and 0 < n["pathCost"] <= max_cost]
    owned = [n for n in nodes if n["allocated"]]
    print(f"{len(adds)} ajouts possibles (coût <= {max_cost} points) et {len(owned)} passifs déjà pris à tester.")

    # ---- A. ajouts -------------------------------------------------------------
    started = time.time()
    results = []
    drifts = 0
    for i, node in enumerate(adds, 1):
        await bridge.call("alloc_node", {"id": node["id"]})
        stats = await read_stats(bridge)
        used = len(await snapshot(bridge) - target)
        results.append((node, used, stats))
        await restore(bridge, target)
        if not same((await read_stats(bridge))["CombinedDPS"], base["CombinedDPS"]):
            drifts += 1
            await reset()
        if i % 20 == 0 or i == len(adds):
            print(f"  ajouts : {i}/{len(adds)} ({time.time() - started:.0f} s)", flush=True)

    if drifts:
        print(f"\n({drifts} fois l'arbre n'est pas revenu exactement au départ : il a été rechargé à chaque fois.)")

    scored = [(n, used, s) for n, used, s in results if used > 0 and s["CombinedDPS"] > base["CombinedDPS"]]
    scored.sort(key=lambda r: (r[2]["CombinedDPS"] - base["CombinedDPS"]) / r[1], reverse=True)
    print(f"\nA. Meilleurs ajouts (gain de DPS par point) :")
    if not scored:
        print("  aucun ajout dans ce rayon n'augmente le DPS.")
    previous = None
    for node, used, stats in scored[:top]:
        twin = previous is not None and same(stats["CombinedDPS"], previous)
        previous = stats["CombinedDPS"]
        gain = pct(base["CombinedDPS"], stats["CombinedDPS"])
        per_point = (stats["CombinedDPS"] - base["CombinedDPS"]) / base["CombinedDPS"] * 100 / used
        extra = notes(base, stats)
        print(f"  {describe(node)}\n      {used} pt : DPS {stats['CombinedDPS']:,.1f} ({gain}, {per_point:+.1f} %/pt)"
              + (f"   [{extra}]" if extra else "")
              + ("\n      (même DPS que la ligne précédente : le gain vient probablement d'un nœud du chemin, pas du notable)" if twin else ""))

    # ---- B. retraits -----------------------------------------------------------
    started = time.time()
    removals = []
    for i, node in enumerate(owned, 1):
        await bridge.call("dealloc_node", {"id": node["id"]})
        stats = await read_stats(bridge)
        lost = len(target - await snapshot(bridge))
        removals.append((node, lost, stats))
        await reset()
        if i % 20 == 0 or i == len(owned):
            print(f"  retraits : {i}/{len(owned)} ({time.time() - started:.0f} s)", flush=True)

    removals.sort(key=lambda r: r[2]["CombinedDPS"], reverse=True)
    print(f"\nB. Passifs que tu as déjà et qui rapportent le moins de DPS (retrait testé) :")
    for node, lost, stats in removals[:top]:
        extra = notes(base, stats)
        print(f"  {describe(node)}\n      sans lui ({lost} nœud(s) retiré(s)) : DPS {stats['CombinedDPS']:,.1f}"
              f" ({pct(base['CombinedDPS'], stats['CombinedDPS'])})" + (f"   [autres effets du retrait : {extra}]" if extra else ""))

    await reset()
    check = await read_stats(bridge)
    if same(check["CombinedDPS"], base["CombinedDPS"]):
        print("\nArbre remis à son état de départ (vérifié).")
    else:
        print("\nAttention : l'arbre n'est pas revenu exactement à son état de départ.")
    print("Rappel : chiffres de PoB avec les réglages ci-dessus. Les nœuds d'ascendance ne sont pas testés.")


async def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    source, rest = args[0], args[1:]
    max_cost, top = 3, 12
    settings: dict = {}
    i = 0
    while i < len(rest):
        item = rest[i]
        if item == "--cout" and i + 1 < len(rest):
            max_cost, i = int(rest[i + 1]), i + 2
        elif item == "--top" and i + 1 < len(rest):
            top, i = int(rest[i + 1]), i + 2
        elif "=" in item:
            var, _, value = item.partition("=")
            settings[var.strip()] = parse_value(value.strip())
            i += 1
        else:
            print(f"Argument ignoré : {item}")
            i += 1

    pob = locate_pob()
    luajit = locate_luajit()
    manager = BridgeManager(pob, luajit)
    try:
        bridge = await manager.primary()
        await run(bridge, source, settings, max_cost, top)
    except BridgeError as exc:
        print(f"\nErreur du pont PoB : {exc}")
        sys.exit(1)
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
