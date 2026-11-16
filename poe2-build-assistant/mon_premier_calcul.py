import sys
import asyncio
from test_avant_apres import decode_pob_code, read_stats
from pob_mcp.bridge import BridgeError, BridgeManager
from pob_mcp.locate import locate_luajit, locate_pob
from pathlib import Path

async def measure_skill_dps(bridge, group_num, gem):
	params = {"groupIndex": group_num, "gemIndex": gem["index"]}
	await bridge.call("set_gem", {**params, "enabled": False})
	without_gem = await read_stats(bridge)
	await bridge.call("set_gem", {**params, "enabled": True})
	dps_without_gem = without_gem['CombinedDPS']

	return dps_without_gem

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
	gems = []
	for gem in groupe_principal["gems"]:
		gem_id = gem.get("skillId") or ""
		if not gem_id.startswith("Support"):
			continue

		nom = gem.get("nameSpec") or ""
		dps = await measure_skill_dps(bridge, groupe_principal["index"], gem)
		diff_gem = (dps - with_gem['CombinedDPS']) * 100 / with_gem['CombinedDPS']

		dic = {"name": nom, "DPS": dps, "variation": diff_gem}
		gems.append(dic)

	result = sorted(gems, key=lambda small_dic: small_dic["variation"], reverse=True)
	print(f"\n{'Rang':<5}{'Gem':<22}{'DPS sans':>12}{'Variation':>12}")
	for rang, ligne in enumerate(result, 1):
		print(f"{rang:<5}{ligne['name']:<22}{ligne['DPS']:>12,.0f}{ligne['variation']:>+11.1f} %")
		
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

	