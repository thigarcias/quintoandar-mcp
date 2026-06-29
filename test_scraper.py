#!/usr/bin/env python3
"""Teste rápido do scraper com um imóvel específico."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scraper import buscar_imovel_por_id

PROPERTY_ID = "895324932"
OUT_DIR = Path(__file__).parent / "output" / PROPERTY_ID

print(f"==> Testando imóvel {PROPERTY_ID}...")
print(f"    Salvando em: {OUT_DIR}")

result = buscar_imovel_por_id(PROPERTY_ID, OUT_DIR)

print("\n--- DADOS ---")
for k, v in result.items():
    if k == "photos":
        print(f"  photos: {len(v)} foto(s)")
        for p in v[:3]:
            status = "OK" if p.get("localPath") else f"SEM LOCAL — url: {p.get('url','?')[:60]}"
            print(f"    [{status}]")
    else:
        print(f"  {k}: {v}")

print(f"\n==> JSON salvo em: {OUT_DIR / 'imovel.json'}")
