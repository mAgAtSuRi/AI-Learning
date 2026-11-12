import sys
import asyncio
import json
from test_avant_apres import decode_pob_code, read_stats
from pob_mcp.bridge import BridgeError, BridgeManager
from pob_mcp.locate import locate_luajit, locate_pob
from pathlib import Path

async def analyse_build(bridge, source, nom_gem):
	path = Path(source)
	if path.suffix.lower() == ".txt" and path.is_file():
		source = path.read_text(encoding="utf-8").strip()

	print("Chargement du build...")
	xml = source if source.lstrip().startswith(("<?xml", "<PathOfBuilding")) else decode_pob_code(source)
	await bridge.call("load_build_xml", {"xml": xml, "name": "mon-build"})

	skills = await bridge.call("get_skills")

	#1 Trouver le groupe principal
	groupe_principal = None
	for groupe in skills["socketGroups"]:
		if groupe["index"] == skills["mainSocketGroup"]:
			groupe_principal = groupe
			if groupe_principal is None:
				print(f"Groupe principal non trouvé")
				return
	
	#2 Trouver la gem dans ce groupe
	trouve = None
	for gem in groupe_principal["gems"]:
		nom = gem.get("nameSpec") or ""
		if nom.lower() == nom_gem.lower():
			trouve = gem
	
	#3 Afficher le resultat
	if trouve is None:
		print(f"Gem non trouvée: {nom_gem}")
		return
	print(f"Gem trouvée : {nom_gem} (index {trouve['index']}, niveau {trouve['level']})")
	stats = await read_stats(bridge)
	print(f"DPS actuel : {stats['CombinedDPS']}")

	# label = nom_gem.get("nameSpec") or nom_gem.get("gemId") or nom_gem.get("skillId") or "?"
	# etat = "actif" if nom_gem["enabled"] else "désactivé"
	# print(f"  {nom_gem['index']}. {label} (niveau {nom_gem.get('level')}, {etat})")


async def calcul_dps(file, gem):
	pob = locate_pob()
	luajit = locate_luajit()
	manager = BridgeManager(pob, luajit)
	try:
		bridge = await manager.primary()
		await analyse_build(bridge, file, gem)
	except BridgeError as exc:
		print(f"\nErreur du pont PoB : {exc}")
		sys.exit(1)
	finally:
		await manager.close()

if __name__ == "__main__":
	asyncio.run(calcul_dps(sys.argv[1], sys.argv[2]))

	