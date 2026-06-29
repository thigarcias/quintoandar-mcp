"""
Lógica central do scraper do QuintoAndar.

Busca em massa por cidade: API interna /api/yellow-pages/v2/search (requests).
Busca individual por ID:   Playwright headless (anti-bot bloqueia a API direta).
"""

import json
import re
import time
from pathlib import Path

import requests

BASE = "https://www.quintoandar.com.br"
SEARCH_API = f"{BASE}/api/yellow-pages/v2/search"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/p_click_version.V3.4+p_click_sale_version.V1+json",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "text/plain;charset=UTF-8",
    "Origin": BASE,
    "Referer": BASE + "/",
}
IMG_HEADERS = {
    "User-Agent": UA,
    "Accept": "image/avif,image/webp,*/*;q=0.8",
    "Referer": BASE + "/",
}

API_FIELDS = [
    "id", "type", "forRent", "forSale", "isPrimaryMarket",
    "rent", "totalCost", "salePrice", "iptuPlusCondominium",
    "area", "bedrooms", "bathrooms", "parkingSpaces",
    "address", "regionName", "city", "neighbourhood",
    "isFurnished", "installations", "listingTags",
    "activeSpecialConditions", "categories",
    "coverImage", "imageList", "imageCaptionList",
    "suites", "iptu", "amenities",
]

CITY_BOUNDS = {
    "são paulo":          (-23.326, -23.775, -46.388, -46.878),
    "sao paulo":          (-23.326, -23.775, -46.388, -46.878),
    "são caetano do sul": (-23.596, -23.648, -46.527, -46.592),
    "sao caetano do sul": (-23.596, -23.648, -46.527, -46.592),
    "campinas":           (-22.820, -23.010, -47.000, -47.200),
    "rio de janeiro":     (-22.746, -23.082, -43.101, -43.796),
}
DEFAULT_BOUNDS = (-5.0, -35.0, -32.0, -74.0)


def _absolute_image(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    if url.startswith("http"):
        return url
    
    filename = url
    if "." not in filename:
        filename += ".jpg"
    return f"{BASE}/img/xxl/{filename}"


def _safe(value, fallback: str = "img") -> str:
    s = str(value) if value is not None else ""
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", s)
    return s or fallback


def extract_id(target: str) -> str:
    m = re.search(r"/imovel/(\d+)", target)
    if m:
        return m.group(1)
    if re.match(r"^\d+$", target.strip()):
        return target.strip()
    raise ValueError(f"Não foi possível extrair ID de: {target!r}")


def _build_search_body(
    keyword: str,
    page_index: int = 1,
    page_size: int = 100,
    business_context: str = "RENT",
    extra_filters: dict | None = None,
) -> dict:
    key = keyword.lower().strip()
    bounds = CITY_BOUNDS.get(key, DEFAULT_BOUNDS)
    n, s, e, w = bounds
    offset = (page_index - 1) * page_size
    f: dict = {
        "map": {
            "bounds_north": n, "bounds_south": s,
            "bounds_east": e, "bounds_west": w,
            "center_lat": (n + s) / 2, "center_lng": (e + w) / 2,
        },
        "availability": "any",
        "occupancy": "any",
        "country_code": "BR",
        "keyword_match": [f"city:{keyword}"],
        "sorting": {"criteria": "relevance_rent", "order": "desc"},
        "page_size": page_size,
        "offset": offset,
        "search_dropdown_value": keyword,
    }
    if extra_filters:
        f.update(extra_filters)
    return {
        "filters": f,
        "return": API_FIELDS,
        "business_context": business_context,
        "relax_query": True,
        "force_raw_search": False,
        "search_query_context": "city",
    }


def _download_image(url: str, dest: Path, session: requests.Session) -> None:
    r = session.get(url, headers=IMG_HEADERS, timeout=30)
    r.raise_for_status()
    dest.write_bytes(r.content)


def _process_listing(
    src: dict,
    out_dir: Path,
    session: requests.Session,
    baixar_fotos: bool = True,
    max_fotos_baixar: int | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict = {
        "id": src.get("id"),
        "sourceUrl": f"{BASE}/imovel/{src.get('id')}",
    }
    for f in API_FIELDS:
        if f not in ("imageList", "imageCaptionList", "coverImage") and src.get(f) is not None:
            result[f] = src[f]

    image_list = src.get("imageList") or []
    caption_list = src.get("imageCaptionList") or []
    cover = src.get("coverImage")

    photos_out = []
    for idx, img_hash in enumerate(image_list):
        purl = _absolute_image(img_hash)
        caption = caption_list[idx] if idx < len(caption_list) else None
        entry = {
            "id": img_hash,
            "subtitle": caption,
            "cover": (img_hash == cover),
            "url": purl,
            "localPath": "",
        }
        if baixar_fotos and (max_fotos_baixar is None or idx < max_fotos_baixar):
            img_dir = out_dir / "images"
            img_dir.mkdir(exist_ok=True)
            file_name = f"{idx:03d}_{_safe(img_hash)[:40]}.jpg"
            try:
                _download_image(purl, img_dir / file_name, session)
                entry["localPath"] = str(img_dir / file_name)
            except Exception as e:  # noqa: BLE001
                entry["downloadError"] = str(e)
        photos_out.append(entry)

    result["photos"] = photos_out
    result["photosCount"] = len(photos_out)

    json_path = out_dir / "imovel.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result



# ──────────────────────────────────────────────
# Playwright — browser singleton para busca individual
# ──────────────────────────────────────────────
# JS desabilitado + bloqueio de recursos: ~1.4s/imóvel (vs. API bloqueada por anti-bot).

import threading
import atexit

_pw_storage = threading.local()
_all_instances = []
_instances_lock = threading.Lock()


def _get_pw_page():
    """Retorna (ou cria) uma página Playwright otimizada para scraping."""
    _pw_instance = getattr(_pw_storage, "instance", None)
    _pw_browser = getattr(_pw_storage, "browser", None)
    _pw_context = getattr(_pw_storage, "context", None)
    _pw_page = getattr(_pw_storage, "page", None)

    if _pw_page is not None:
        try:
            _pw_page.url  # verifica se ainda está vivo
            return _pw_page
        except Exception:
            _pw_page = None
            _pw_storage.page = None

    from playwright.sync_api import sync_playwright

    if _pw_instance is None:
        _pw_instance = sync_playwright().start()
        _pw_storage.instance = _pw_instance
        with _instances_lock:
            _all_instances.append(_pw_instance)
    if _pw_browser is None:
        _pw_browser = _pw_instance.chromium.launch(headless=True)
        _pw_storage.browser = _pw_browser
    if _pw_context is None:
        _pw_context = _pw_browser.new_context(java_script_enabled=False)
        _pw_storage.context = _pw_context

    _pw_page = _pw_context.new_page()
    _pw_page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.resource_type == "document"
            else route.abort()
        ),
    )
    _pw_storage.page = _pw_page
    return _pw_page


def fechar_browser() -> None:
    """Fecha o browser Playwright singleton (opcional — chamada na saída)."""
    _pw_instance = getattr(_pw_storage, "instance", None)
    _pw_browser = getattr(_pw_storage, "browser", None)
    _pw_context = getattr(_pw_storage, "context", None)
    _pw_page = getattr(_pw_storage, "page", None)

    for obj in (_pw_page, _pw_context, _pw_browser):
        try:
            if obj is not None:
                obj.close()
        except Exception:
            pass
    if _pw_instance is not None:
        try:
            _pw_instance.stop()
        except Exception:
            pass
        with _instances_lock:
            if _pw_instance in _all_instances:
                _all_instances.remove(_pw_instance)

    _pw_storage.instance = None
    _pw_storage.browser = None
    _pw_storage.context = None
    _pw_storage.page = None


@atexit.register
def _fechar_todos_browsers():
    with _instances_lock:
        for instance in list(_all_instances):
            try:
                instance.stop()
            except Exception:
                pass
        _all_instances.clear()



def _fetch_house_pw(property_id: str) -> dict:
    """
    Busca dados de um imóvel via Playwright (headless, sem JS).
    Extrai __NEXT_DATA__ do HTML e normaliza para o formato padrão.
    """
    page = _get_pw_page()
    url = f"{BASE}/imovel/{property_id}"
    page.goto(url, wait_until="commit", timeout=15000)

    nd = page.query_selector("script#__NEXT_DATA__")
    if nd is None:
        raise RuntimeError(f"__NEXT_DATA__ não encontrado na página do imóvel {property_id}")

    data = json.loads(nd.inner_text())
    hi = (
        data.get("props", {})
        .get("pageProps", {})
        .get("initialState", {})
        .get("house", {})
        .get("houseInfo", {})
    )
    if not hi or not hi.get("id"):
        raise RuntimeError(f"Dados do imóvel {property_id} não encontrados no __NEXT_DATA__")

    return _normalize_house_info(hi)


def _normalize_house_info(hi: dict) -> dict:
    """
    Converte houseInfo do __NEXT_DATA__ para o formato normalizado
    compatível com o JSON gerado pela API de search.
    """
    # Endereço: hi.address é um dict {street, neighborhood, city, ...}
    addr = hi.get("address", {})
    if isinstance(addr, dict):
        address_str = addr.get("street", "")
        neighbourhood = addr.get("neighborhood", "")
        city = addr.get("city", "")
    else:
        address_str = str(addr)
        neighbourhood = ""
        city = hi.get("city", "")

    # Fotos: hi.photos é uma lista de dicts com {url, description, ...}
    raw_photos = hi.get("photos", [])
    image_list = []
    caption_list = []
    for p in raw_photos:
        if isinstance(p, dict):
            image_list.append(p.get("url", ""))
            caption_list.append(p.get("description") or p.get("subtitle") or "")
        elif isinstance(p, str):
            image_list.append(p)
            caption_list.append("")

    # Região
    region = hi.get("region", {})
    region_name = region.get("name", "") if isinstance(region, dict) else str(region)

    src: dict = {
        "id": hi.get("id"),
        "type": hi.get("type"),
        "forRent": hi.get("forRent"),
        "forSale": hi.get("forSale"),
        "isPrimaryMarket": hi.get("isPrimaryMarket", False),
        "rent": hi.get("rentPrice"),
        "totalCost": hi.get("totalCost"),
        "salePrice": hi.get("salePrice", 0),
        "iptuPlusCondominium": (hi.get("iptu", 0) or 0) + (hi.get("condoPrice", 0) or 0),
        "area": hi.get("area"),
        "bedrooms": hi.get("bedrooms"),
        "bathrooms": hi.get("bathrooms"),
        "parkingSpaces": hi.get("parkingSpaces"),
        "address": address_str,
        "regionName": region_name,
        "city": city or hi.get("city", ""),
        "neighbourhood": neighbourhood,
        "isFurnished": hi.get("hasFurniture", False),
        "installations": hi.get("installations", []),
        "listingTags": hi.get("listingTags", []),
        "activeSpecialConditions": hi.get("specialConditions", []),
        "categories": hi.get("categories", []),
        "imageList": image_list,
        "imageCaptionList": caption_list,
        "coverImage": image_list[0] if image_list else None,
        # Campos extras do Playwright (mais ricos que a API)
        "suites": hi.get("suites"),
        "condoPrice": hi.get("condoPrice"),
        "iptu": hi.get("iptu"),
        "amenities": hi.get("amenities", []),
        "remarks": hi.get("remarks"),
        "acceptsPets": hi.get("acceptsPets"),
        "isNearSubway": hi.get("isNearSubway"),
        "status": hi.get("status"),
        "lastPublishedDate": hi.get("lastPublishedDate"),
    }

    # Remove chaves None para manter o JSON limpo
    return {k: v for k, v in src.items() if v is not None}


# ──────────────────────────────────────────────
# Funções públicas (usadas pelo MCP e pelo CLI)
# ──────────────────────────────────────────────

def buscar_imovel_por_id(
    property_id: str,
    out_dir: Path,
    session: requests.Session | None = None,
    baixar_fotos: bool = True,
) -> dict:
    """
    Busca um imóvel específico por ID numérico via Playwright headless.
    Usa browser singleton com JS desabilitado para máxima performance (~1.4s).
    Retorna o dict de resultado (também salvo em out_dir/imovel.json).
    Lança RuntimeError se o imóvel não for encontrado.
    """
    session = session or requests.Session()

    # Método primário: Playwright (extrai __NEXT_DATA__ da página)
    src = _fetch_house_pw(property_id)
    return _process_listing(src, out_dir, session, baixar_fotos=baixar_fotos)


def buscar_imoveis(
    cidade: str,
    pasta_saida: Path,
    *,
    paginas: int = 5,
    business_context: str = "RENT",
    quartos: list[int] | None = None,
    banheiros: list[int] | None = None,
    vagas_min: int | None = None,
    area_min: float | None = None,
    area_max: float | None = None,
    aluguel_min: float | None = None,
    aluguel_max: float | None = None,
    total_min: float | None = None,
    total_max: float | None = None,
    mobiliado: bool = False,
    aceita_pet: bool = False,
    perto_metro: bool = False,
    tipos: list[str] | None = None,
    delay: float = 1.0,
    session: requests.Session | None = None,
    baixar_fotos: bool = False,
    limite: int | None = None,
) -> list[dict]:
    """
    Busca imóveis por cidade usando a API de listagem do QuintoAndar.
    Retorna lista de dicts com os dados de cada imóvel encontrado.
    Cada imóvel é salvo em pasta_saida/{id}/imovel.json com suas fotos.
    """
    session = session or requests.Session()

    extra: dict = {}
    if quartos:
        extra["bedrooms"] = quartos          # API espera lista direta: [2, 3]
    if banheiros:
        extra["bathrooms"] = banheiros
    if vagas_min is not None:
        extra["parking_spaces"] = {"min": vagas_min}
    if area_min is not None or area_max is not None:
        extra["area"] = {k: v for k, v in [("min", area_min), ("max", area_max)] if v is not None}
    if aluguel_min is not None or aluguel_max is not None:
        extra["rent"] = {k: v for k, v in [("min", aluguel_min), ("max", aluguel_max)] if v is not None}
    if total_min is not None or total_max is not None:
        extra["total_cost"] = {k: v for k, v in [("min", total_min), ("max", total_max)] if v is not None}
    if mobiliado:
        extra["is_furnished"] = True
    if aceita_pet:
        extra["accepts_pets"] = True
    if perto_metro:
        extra["is_near_subway"] = True
    if tipos:
        extra["type"] = [t.upper() for t in tipos]   # API espera lista direta também

    all_results: list[dict] = []
    for page in range(1, paginas + 1):
        if limite is not None and len(all_results) >= limite:
            break
        body = _build_search_body(cidade, page_index=page, business_context=business_context, extra_filters=extra)
        r = session.post(SEARCH_API, data=json.dumps(body, ensure_ascii=False), headers=HEADERS, timeout=30)
        r.raise_for_status()
        hits = r.json().get("hits", {}).get("hits", [])
        if not hits:
            break
        for h in hits:
            if limite is not None and len(all_results) >= limite:
                break
            src = h.get("_source", {})
            src["id"] = h.get("_id", src.get("id"))
            pid = str(src["id"])
            try:
                result = _process_listing(src, pasta_saida / pid, session, baixar_fotos=baixar_fotos)
                all_results.append(result)
            except Exception as e:  # noqa: BLE001
                all_results.append({"id": pid, "erro": str(e)})
        if page < paginas:
            if limite is not None and len(all_results) >= limite:
                break
            time.sleep(delay)

    return all_results


def buscar_lote(
    targets: list[str],
    pasta_saida: Path,
    delay: float = 2.0,
    session: requests.Session | None = None,
) -> list[dict]:
    """
    Busca vários imóveis por lista de IDs ou URLs.
    Retorna lista de dicts com resultado ou erro para cada item.
    """
    session = session or requests.Session()
    results = []
    for i, target in enumerate(targets):
        try:
            pid = extract_id(target)
            result = buscar_imovel_por_id(pid, pasta_saida / pid, session)
            results.append(result)
        except Exception as e:  # noqa: BLE001
            results.append({"target": target, "erro": str(e)})
        if i < len(targets) - 1:
            time.sleep(delay)
    return results
