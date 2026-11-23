import sys
import asyncio
import time
from test_avant_apres import decode_pob_code, read_stats
from pob_mcp.bridge import BridgeError, BridgeManager
from pob_mcp.locate import locate_luajit, locate_pob
from pathlib import Path

def find_gem(liste, champ, nom):
	for dic in liste:
		if dic.get(champ) == nom:
			return dic
	return None

def find_groupe_principal(skills):
	"""Trouver le groupe principal"""
	for groupe in skills["socketGroups"]:
		if groupe["index"] == skills["mainSocketGroup"]:
			groupe_principal = groupe
			return groupe_principal
	print('groupe not found')
	return None


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

async def test_independance(bridge, groupe_principal, gems, candidates, dps_without_gem, with_gem):
	"""Build a table for each candidate showing change of dps for gems already used"""
	resultats = {}
	for candidate in candidates:
		resultats[candidate["name"]] = {}
		for old_gem in gems:
			new_dps = await change_gem(bridge, groupe_principal["index"], old_gem, candidate)
			r = new_dps / dps_without_gem[old_gem["nameSpec"]]
			resultats[candidate["name"]][old_gem["nameSpec"]] = r
	print(f'résultats : {resultats}')

	check = await read_stats(bridge)
	if abs(check["CombinedDPS"] - with_gem["CombinedDPS"]) < 1e-6 * max(1.0, abs(with_gem["CombinedDPS"])):
		print("Build remis à son état de départ")
	else:
		print("Build pas réinitialisé")


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

	groupe_principal = find_groupe_principal(skills)
	
	with_gem = await read_stats(bridge)
	print("DPS actuel :", with_gem['CombinedDPS'])

	gem_id_used = set()
	for gem in groupe_principal["gems"]:
		gem_id_used.add(gem["gemId"])

	all_valid_gems = await bridge.call("list_valid_supports", {"groupIndex": groupe_principal["index"]})
	gem_available = []
	for gem in all_valid_gems["supports"]:
		if gem["gemId"] not in gem_id_used:
			gem_available.append(gem)	


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

	# All candidates
	for gem in gem_available:
		new_dps = await change_gem(bridge, groupe_principal["index"], old_gem, gem)	
		# diff_gem_dps = (new_dps - with_gem['CombinedDPS']) * 100 / with_gem['CombinedDPS']
		m = new_dps / dps_without_gem[old_gem["nameSpec"]]
		dic = {"name": gem["name"], "m": m, "gemId": gem["gemId"], "present": False}
		all_combinaison.append(dic)

	# Add the m for the 5 gems already used
	for gem in gems:
		m = with_gem['CombinedDPS'] / dps_without_gem[gem["nameSpec"]]
		all_combinaison.append(({"name": gem["nameSpec"], "m": m, "gemId": gem["gemId"], "present": True}))
	
	m_list = []
	for dic in all_combinaison:
		if dic["present"]:
			m_list.append(dic["m"])
	k = await measure_skill_dps(bridge, groupe_principal["index"], gems)

	total_dps = k
	for mult in m_list:
		total_dps *= mult
	print(f'Base dps K: {k}')
	print(f'total dps: {total_dps}')

	new_time = time.time()
	print(f"Durée: {new_time - old_time}")

	sorted_all_combinaison = sorted(all_combinaison, key=lambda gem: gem["m"], reverse=True)
	for rang, ligne in enumerate(sorted_all_combinaison[:15], 1):
		print(f"{rang:<5}{ligne['name']:<40}{ligne['m']:>12,.3f}")


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

	