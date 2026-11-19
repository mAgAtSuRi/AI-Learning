import sys
import asyncio
import time
from itertools import combinations
from test_avant_apres import decode_pob_code, read_stats
from pob_mcp.bridge import BridgeError, BridgeManager
from pob_mcp.locate import locate_luajit, locate_pob
from pathlib import Path

async def measure_skill_dps(bridge, group_num, gem_list):
	"""measure dps of a gem list by deactivatinbg and reactivating the gem"""
	for gem in gem_list:
		params = {"groupIndex": group_num, "gemIndex": gem["index"]}
		await bridge.call("set_gem", {**params, "enabled": False})

	without_gem = await read_stats(bridge)
	for gem in gem_list:
		params = {"groupIndex": group_num, "gemIndex": gem["index"]}
		await bridge.call("set_gem", {**params, "enabled": True})

	dps_without_gem = without_gem['CombinedDPS']
	return dps_without_gem

async def change_gem(bridge, group_num, old_gem, new_gem):
	"""Change a gem by another one and return the new dps"""
	params = {"groupIndex": group_num, "gemIndex": old_gem["index"]}
	await bridge.call("set_gem", {**params, "enabled": False})

	ajout = await bridge.call("add_gem", {"groupIndex": group_num, "gemId": new_gem["gemId"]})
	new_dps = await read_stats(bridge)

	await bridge.call("remove_gem", {"groupIndex": group_num, "gemIndex": ajout["gemIndex"]})
	await bridge.call("set_gem", {**params, "enabled": True})
	return new_dps["CombinedDPS"]

async def analyse_build(bridge, source):
	path = Path(source)
	if path.suffix.lower() == ".txt" and path.is_file():
		source = path.read_text(encoding="utf-8").strip()

	print("Chargement du build...")
	xml = source if source.lstrip().startswith(("<?xml", "<PathOfBuilding")) else decode_pob_code(source)
	await bridge.call("load_build_xml", {"xml": xml, "name": "mon-build"})

	await bridge.call("set_config", {"var": "conditionFullMana", "value": True})
	await bridge.call("set_config", {"var": "multiplierNonInstantSpellCastRecently", "value": 3})

	skills = await bridge.call("get_skills")

	#1 Trouver le groupe principal
	groupe_principal = None
	for groupe in skills["socketGroups"]:
		if groupe["index"] == skills["mainSocketGroup"]:
			groupe_principal = groupe
	if groupe_principal is None:
		print(f"Groupe principal non trouvé")
		return
	
	with_gem = await read_stats(bridge)
	print("DPS actuel :", with_gem['CombinedDPS'])
	# 2 Trouver la gem dans ce groupe
	# gems = []
	# for gem in groupe_principal["gems"]:
	# 	gem_id = gem.get("skillId") or ""
	# 	if not gem_id.startswith("Support"):
	# 		continue

	# 	nom = gem.get("nameSpec") or ""
	# 	dps = await measure_skill_dps(bridge, groupe_principal["index"], gem)
	# 	diff_gem = (dps - with_gem['CombinedDPS']) * 100 / with_gem['CombinedDPS']

	# 	dic = {"name": nom, "DPS": dps, "variation": diff_gem}
	# 	gems.append(dic)

	# result = sorted(gems, key=lambda small_dic: small_dic["variation"], reverse=True)
	# print(f"\n{'Rang':<5}{'Gem':<22}{'DPS sans':>12}{'Variation':>12}")
	# for rang, ligne in enumerate(result, 1):
	# 	print(f"{rang:<5}{ligne['name']:<22}{ligne['DPS']:>12,.0f}{ligne['variation']:>+11.1f} %")
	gem_id_used = set()
	for gem in groupe_principal["gems"]:
		gem_id_used.add(gem["gemId"])

	all_valid_gems = await bridge.call("list_valid_supports", {"groupIndex": groupe_principal["index"]})
	gem_available = []
	for gem in all_valid_gems["supports"]:
		if gem["gemId"] not in gem_id_used:
			gem_available.append(gem)
	print(f'10 first gems available:\n {gem_available[:10]}, {len(gem_available)}')

	# Store all gems used
	gems = []
	for gem in groupe_principal["gems"]:
		gem_id = gem.get("skillId") or ""
		if not gem_id.startswith("Support"):
			continue
		gems.append(gem)
	
	# Dic storing value of dps without the corresponding gem
	dps_without_gem = {}
	for gem in gems:
		dps = await measure_skill_dps(bridge, groupe_principal["index"], [gem])
		dps_without_gem[gem["nameSpec"]] = dps
	print(dps_without_gem)


	# List for dps change by removing pairs of gems
	# gems_pairs_dps = []
	# for a, b in combinations(gems, 2):
	# 	dps_without_pair = await measure_skill_dps(bridge, groupe_principal["index"], [a, b])
	# 	dps_without_pair_expected = dps_without_gem[a.get("nameSpec")] * dps_without_gem[b.get("nameSpec")] / with_gem['CombinedDPS']
	# 	dps_gap = (dps_without_pair - dps_without_pair_expected) * 100 / dps_without_pair_expected
	# 	dic = {"name": f'{a["nameSpec"]} / {b["nameSpec"]}"',
	# 			"Real DPS": dps_without_pair,
	# 			"Expected DPS": dps_without_pair_expected,
	# 			"DPS gap": dps_gap
	# 	}
	# 	gems_pairs_dps.append(dic)
	# sorted_pairs = sorted(gems_pairs_dps, key=lambda gem: gem["DPS gap"])
	# for rang, ligne in enumerate(sorted_pairs, 1):
	# 	print(f"{rang:<5}{ligne['name']:<40}{ligne['Real DPS']:>12,.0f}{ligne['Expected DPS']:>11.1f}{ligne['DPS gap']:>+11.1f} %")

	# List of all dps change for available gems instead of chaos
	all_combinaison = []
	old_gem = None
	old_time = time.time()

	for gem in groupe_principal["gems"]:
		if gem["nameSpec"] == "Chaos Mastery":
			old_gem = gem
	if old_gem is None:
			print("old or new gem is none")
			return

	for gem in gem_available:
		new_dps = await change_gem(bridge, groupe_principal["index"], old_gem, gem)	
		diff_gem_dps = (new_dps - with_gem['CombinedDPS']) * 100 / with_gem['CombinedDPS']
		dic = {"name": gem["name"], "DPS": new_dps, "variation": diff_gem_dps}
		all_combinaison.append(dic)

	new_time = time.time()
	print(f"Durée: {new_time - old_time}")

	sorted_all_combinaison = sorted(all_combinaison, key=lambda gem: gem["DPS"], reverse=True)
	for rang, ligne in enumerate(sorted_all_combinaison[:15], 1):
		print(f"{rang:<5}{ligne['name']:<40}{ligne['DPS']:>12,.0f}{ligne['variation']:>+11.1f} %")

	check = await read_stats(bridge)
	if abs(check["CombinedDPS"] - with_gem["CombinedDPS"]) < 1e-6 * max(1.0, abs(with_gem["CombinedDPS"])):
		print("Build remis à son état de départ")
	else:
		print("Build pas réinitialisé")

async def calcul_dps(file):
	pob = locate_pob()
	luajit = locate_luajit()
	manager = BridgeManager(pob, luajit)
	try:
		bridge = await manager.primary()
		await analyse_build(bridge, file)
	except BridgeError as exc:
		print(f"\nErreur du pont PoB : {exc}")
		sys.exit(1)
	finally:
		await manager.close()

if __name__ == "__main__":
	asyncio.run(calcul_dps(sys.argv[1]))

	