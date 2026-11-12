"""Comment dépenser N points de passifs au mieux ?

Aucune IA ici : le moteur de Path of Building 2 calcule tout.

Méthode (glouton, sans respec) : à chaque étape, on teste chaque notable / keystone de l'arbre
principal atteignable avec les points qu'il reste (chemin compris), on garde celui qui rapporte
le plus de DPS PAR POINT, on l'alloue pour de bon, puis on recommence avec le budget restant.
Les gains sont recalculés à chaque étape : un nœud peut valoir plus après un autre
(ex. chance de critique, puis dégâts critiques).

Usage (depuis le dossier pob-mcp) :
    .\\.venv\\Scripts\\python optimiser_arbre.py mon_build.txt --points 8
    .\\.venv\\Scripts\\python optimiser_arbre.py mon_build.txt --points 8 conditionFullMana=true multiplierNonInstantSpellCastRecently=1

Options :
  --points N       budget de points à dépenser (obligatoire)
  nom=valeur       réglages de conditions PoB (comme calibrage.py) : à mettre pour comparer juste
  --cout-max N     coût maximal d'un seul nœud testé, pour limiter le temps (défaut 6)
  --ehp-perte P    refuse un ajout qui ferait perdre plus de P % d'EHP au total (défaut 5)

Ce script a besoin de test_avant_apres.py et calibrage.py (même dossier).
Limites : pas de respec (on n'enlève rien), nœuds d'ascendance non testés, glouton = pas un optimum garanti.
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


def same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * max(1.0, abs(a))


async def snapshot(bridge) -> set[int]:
    return set((await bridge.call("get_tree_state"))["allocatedNodes"])


async def restore(bridge, target: set[int]) -> None:
    for _ in range(50):
        extra = (await snapshot(bridge)) - target
        if not extra:
            break
        await bridge.call("dealloc_node", {"id": sorted(extra)[0]})
    for node_id in sorted(target - await snapshot(bridge)):
        await bridge.call("alloc_node", {"id": node_id})


def describe(node: dict) -> str:
    stats = " / ".join(node.get("stats") or [])
    return f"{node['name']} ({stats[:90]})" if stats else str(node["name"])


async def run(bridge, source: str, settings: dict, budget: int, max_cost: int, ehp_loss: float) -> None:
    path = Path(source)
    if path.suffix.lower() == ".txt" and path.is_file():
        source = path.read_text(encoding="utf-8").strip()
    xml = source if source.lstrip().startswith(("<?xml", "<PathOfBuilding")) else decode_pob_code(source)

    committed: list[int] = []  # nœuds choisis jusqu'ici, pour pouvoir recharger l'état exact

    async def reset() -> None:
        await bridge.call("load_build_xml", {"xml": xml, "name": "optimiser"})
        for var, value in settings.items():
            await bridge.call("set_config", {"var": var, "value": value})
        for node_id in committed:
            await bridge.call("alloc_node", {"id": node_id})

    await reset()
    character = await bridge.call("get_character")
    print(f"Niveau {character.get('level')} - {character.get('className', '?')} / {character.get('ascendClassName', 'sans ascendance')}")
    if settings:
        print("Réglages : " + ", ".join(f"{k}={v}" for k, v in settings.items()))

    start = await read_stats(bridge)
    print(f"DPS de départ : {start['CombinedDPS']:,.1f}   Budget : {budget} point(s)")
    ehp_floor = start["TotalEHP"] * (1 - ehp_loss / 100)

    remaining = budget
    plan: list[tuple[dict, int, dict]] = []
    t0 = time.time()
    step = 0
    while remaining > 0:
        step += 1
        current = await read_stats(bridge)
        target = await snapshot(bridge)
        found = await bridge.call("search_tree", {"ascendancyName": False, "limit": 20000})
        candidates = [
            n for n in found["nodes"]
            if n["type"] in ("Notable", "Keystone") and not n["allocated"]
            and n.get("pathCost") is not None and 0 < n["pathCost"] <= min(remaining, max_cost)
        ]
        if not candidates:
            print(f"\nÉtape {step} : plus aucun nœud atteignable avec {remaining} point(s).")
            break
        print(f"\nÉtape {step} : {len(candidates)} candidats, {remaining} point(s) restant(s)...", flush=True)

        best = None
        for node in candidates:
            await bridge.call("alloc_node", {"id": node["id"]})
            stats = await read_stats(bridge)
            used = len((await snapshot(bridge)) - target)
            await restore(bridge, target)
            if not same((await read_stats(bridge))["CombinedDPS"], current["CombinedDPS"]):
                await reset()
            if used == 0 or used > remaining:
                continue
            gain = stats["CombinedDPS"] - current["CombinedDPS"]
            if gain <= 0 or stats["TotalEHP"] < ehp_floor:
                continue
            if any(stats[r] < current[r] for r in RESISTS):
                continue
            score = gain / used
            if best is None or score > best[0]:
                best = (score, node, used, stats)

        if best is None:
            print("  aucun nœud ne fait monter le DPS dans les limites fixées : arrêt.")
            break
        _, node, used, stats = best
        await bridge.call("alloc_node", {"id": node["id"]})
        committed.append(node["id"])
        remaining -= used
        plan.append((node, used, stats))
        print(f"  -> {describe(node)}\n     {used} pt : DPS {current['CombinedDPS']:,.1f} -> {stats['CombinedDPS']:,.1f}"
              f" ({pct(current['CombinedDPS'], stats['CombinedDPS'])})   [reste {remaining} pt, {time.time() - t0:.0f} s]", flush=True)

    print("\n=== Résultat ===")
    if not plan:
        print("Aucun ajout recommandé avec ces réglages.")
        return
    final = await read_stats(bridge)
    spent = budget - remaining
    for i, (node, used, stats) in enumerate(plan, 1):
        print(f"  {i}. {describe(node)}  ({used} pt, DPS cumulé {stats['CombinedDPS']:,.1f})")
    print(f"\nPoints dépensés : {spent}/{budget}")
    print(f"DPS : {start['CombinedDPS']:,.1f} -> {final['CombinedDPS']:,.1f} ({pct(start['CombinedDPS'], final['CombinedDPS'])})")
    print(f"Vie : {start['Life']:,.0f} -> {final['Life']:,.0f}   EHP : {pct(start['TotalEHP'], final['TotalEHP'])}")
    print("Identifiants des nœuds principaux choisis : " + ", ".join(str(n["id"]) for n, _, _ in plan))
    print("Rappel : estimation PoB avec les réglages ci-dessus ; vérifie en jeu avant de dépenser tes points.")


async def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    source, rest = args[0], args[1:]
    budget = None
    max_cost, ehp_loss = 6, 5.0
    settings: dict = {}
    i = 0
    while i < len(rest):
        item = rest[i]
        if item == "--points" and i + 1 < len(rest):
            budget, i = int(rest[i + 1]), i + 2
        elif item == "--cout-max" and i + 1 < len(rest):
            max_cost, i = int(rest[i + 1]), i + 2
        elif item == "--ehp-perte" and i + 1 < len(rest):
            ehp_loss, i = float(rest[i + 1]), i + 2
        elif "=" in item:
            var, _, value = item.partition("=")
            settings[var.strip()] = parse_value(value.strip())
            i += 1
        else:
            print(f"Argument ignoré : {item}")
            i += 1
    if not budget or budget < 1:
        print("Il faut indiquer le budget : --points N (par exemple --points 8)")
        sys.exit(1)

    pob = locate_pob()
    luajit = locate_luajit()
    manager = BridgeManager(pob, luajit)
    try:
        bridge = await manager.primary()
        await run(bridge, source, settings, budget, max_cost, ehp_loss)
    except BridgeError as exc:
        print(f"\nErreur du pont PoB : {exc}")
        sys.exit(1)
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
