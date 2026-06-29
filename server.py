#!/usr/bin/env python3
"""
MCP Server — QuintoAndar Scraper

Expõe cinco tools para uso em assistentes compatíveis com MCP:
  • buscar_imovel          — busca um imóvel específico por ID ou URL
  • buscar_imoveis         — busca imóveis por cidade com filtros detalhados
  • buscar_lote            — busca vários imóveis por lista de IDs/URLs de uma vez
  • listar_imoveis_salvos  — lista todos os imóveis já baixados no output/
  • ler_imovel             — lê dados e retorna fotos (base64) de um imóvel salvo

Iniciar o servidor:
    python server.py
    uv run server.py        (se usar uv)

Configurar no claude_desktop_config.json:
    {
      "mcpServers": {
        "quintoandar": {
          "command": "python",
          "args": ["C:/Users/thiag/Downloads/quintoandar_mcp/server.py"]
        }
      }
    }
"""

import base64
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.transport_security import TransportSecuritySettings

from scraper import (
    buscar_imovel_por_id,
    buscar_imoveis as _buscar_imoveis,
    buscar_lote as _buscar_lote,
    extract_id,
)

def _default_output() -> Path:
    # Resolve em runtime para não vazar o caminho absoluto no schema do MCP.
    return Path(__file__).parent / "output"

mcp = FastMCP(
    name="quintoandar",
    instructions=(
        "Ferramentas para buscar imóveis do QuintoAndar via API interna.\n"
        "REQUISITO CRÍTICO DE EXIBIÇÃO DE FOTOS:\n"
        "1. O servidor MCP roda remotamente e o usuário possui bloqueios de firewall. NUNCA tente exibir fotos usando a sintaxe "
        "Markdown padrão `![Legenda](url)`, pois as imagens aparecerão quebradas para o usuário. Além disso, o caminho `localPath` "
        "aponta para o disco do servidor remoto, não para a máquina local do usuário.\n"
        "2. Para efetivamente mostrar as fotos de um imóvel no chat, você DEVE SEMPRE chamar a tool `ler_imovel` (passando o ID do imóvel). "
        "A tool `ler_imovel` retorna as fotos nativamente em base64, o que bypassa qualquer firewall e garante a exibição visual.\n"
        "3. Use `buscar_imoveis` para encontrar imóveis. Use `buscar_imovel` para metadados de um imóvel específico e `buscar_lote` para listas.\n"
        "RESUMO DO FLUXO: Ao consultar um imóvel, chame `buscar_imovel` para ver os dados, e LOGO EM SEGUIDA chame `ler_imovel` para mostrar as fotos!"
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    ),
)

@mcp.tool()
async def buscar_imovel(
    id_ou_url: str,
    pasta_saida: str | None = None,
) -> dict:
    """
    Busca dados completos de um imóvel específico do QuintoAndar, incluindo
    endereço, preços, características e download de todas as fotos.

    Args:
        id_ou_url: ID numérico do imóvel (ex: "894340784") ou URL completa
                   (ex: "https://www.quintoandar.com.br/imovel/894340784/...").
        pasta_saida: Caminho da pasta onde salvar o imovel.json e as fotos.
                     Padrão: pasta output/ dentro do diretório do projeto.

    Returns:
        Dicionário com todos os dados do imóvel: id, endereço, preços,
        quartos, banheiros, área, fotos (com caminhos locais) e URL de origem.
        Em caso de erro, retorna {"erro": "<mensagem>"}.
    """
    import anyio
    try:
        pid = extract_id(id_ou_url)
        out = (Path(pasta_saida) if pasta_saida else _default_output()) / pid
        result = await anyio.to_thread.run_sync(buscar_imovel_por_id, pid, out)
        return result
    except Exception as e:  # noqa: BLE001
        return {"erro": str(e)}



@mcp.tool()
def buscar_imoveis(
    cidade: str,
    pasta_saida: str | None = None,
    paginas: int = 2,
    modalidade: str = "aluguel",
    quartos: list[int] | None = None,
    banheiros: list[int] | None = None,
    vagas_minimas: int | None = None,
    area_minima_m2: float | None = None,
    area_maxima_m2: float | None = None,
    aluguel_minimo: float | None = None,
    aluguel_maximo: float | None = None,
    custo_total_minimo: float | None = None,
    custo_total_maximo: float | None = None,
    apenas_mobiliados: bool = False,
    aceita_pet: bool = False,
    proximo_metro: bool = False,
    tipos: list[str] | None = None,
    baixar_fotos: bool = False,
    limite: int | None = None,
) -> dict:
    """
    Busca imóveis disponíveis em uma cidade usando a API interna do QuintoAndar,
    com suporte a filtros detalhados de preço, tamanho e características.

    Os dados de cada imóvel são salvos localmente. As fotos só são baixadas se
    baixar_fotos=True — omitir acelera muito a busca em massa. Para baixar as
    fotos de um imóvel específico depois, use ler_imovel ou buscar_imovel.

    Args:
        cidade: Nome da cidade para busca. Ex: "São Paulo", "São Caetano do Sul",
                "Campinas", "Rio de Janeiro".
        pasta_saida: Pasta raiz onde criar subpastas por imóvel. Padrão: pasta output/ dentro do diretório do projeto.
        paginas: Número de páginas da API a buscar (100 imóveis/página). Padrão: 2.
        modalidade: "aluguel" ou "venda". Padrão: "aluguel".
        quartos: Lista de quantidades aceitas de quartos. Ex: [2, 3] busca imóveis
                 com 2 OU 3 quartos. None = qualquer quantidade.
        banheiros: Lista de quantidades aceitas de banheiros. Ex: [1, 2].
        vagas_minimas: Número mínimo de vagas de garagem. Ex: 1.
        area_minima_m2: Área mínima do imóvel em m². Ex: 45.0.
        area_maxima_m2: Área máxima do imóvel em m². Ex: 120.0.
        aluguel_minimo: Valor mínimo de aluguel em R$. Ex: 1500.0.
        aluguel_maximo: Valor máximo de aluguel em R$. Ex: 3000.0.
        custo_total_minimo: Custo total mínimo em R$ (aluguel + condomínio + IPTU).
        custo_total_maximo: Custo total máximo em R$.
        apenas_mobiliados: Se True, retorna apenas imóveis mobiliados.
        aceita_pet: Se True, retorna apenas imóveis que aceitam animais de estimação.
        proximo_metro: Se True, retorna apenas imóveis próximos a estações de metrô.
        tipos: Lista de tipos aceitos. Ex: ["apartamento", "casa", "studio"].
        baixar_fotos: Se True, baixa todas as fotos de cada imóvel durante a busca.
                      Padrão False — deixa a busca rápida e baixa fotos sob demanda via ler_imovel.
        limite: Quantidade máxima de imóveis a retornar e processar. Útil para buscas rápidas.

    Returns:
        Dicionário com:
          - "total": número de imóveis encontrados
          - "cidade": cidade buscada
          - "filtros_aplicados": resumo dos filtros usados
          - "imoveis": lista com dados de cada imóvel (id, endereço, preços,
            características, contagem de fotos, URL)
          - "pasta_saida": caminho onde os dados foram salvos
    """
    ctx = "SALE" if modalidade.lower() == "venda" else "RENT"
    out = Path(pasta_saida) if pasta_saida else _default_output()

    filtros_aplicados = {k: v for k, v in {
        "quartos": quartos,
        "banheiros": banheiros,
        "vagas_minimas": vagas_minimas,
        "area": f"{area_minima_m2}–{area_maxima_m2} m²" if (area_minima_m2 or area_maxima_m2) else None,
        "aluguel": f"R$ {aluguel_minimo}–{aluguel_maximo}" if (aluguel_minimo or aluguel_maximo) else None,
        "custo_total": f"R$ {custo_total_minimo}–{custo_total_maximo}" if (custo_total_minimo or custo_total_maximo) else None,
        "apenas_mobiliados": apenas_mobiliados or None,
        "aceita_pet": aceita_pet or None,
        "proximo_metro": proximo_metro or None,
        "tipos": tipos,
        "limite": limite,
    }.items() if v is not None}

    try:
        results = _buscar_imoveis(
            cidade=cidade,
            pasta_saida=out,
            paginas=paginas,
            business_context=ctx,
            quartos=quartos,
            banheiros=banheiros,
            vagas_min=vagas_minimas,
            area_min=area_minima_m2,
            area_max=area_maxima_m2,
            aluguel_min=aluguel_minimo,
            aluguel_max=aluguel_maximo,
            total_min=custo_total_minimo,
            total_max=custo_total_maximo,
            mobiliado=apenas_mobiliados,
            aceita_pet=aceita_pet,
            perto_metro=proximo_metro,
            tipos=tipos,
            baixar_fotos=baixar_fotos,
            limite=limite,
        )

        imoveis_resumo = []
        for r in results:
            if "erro" in r:
                imoveis_resumo.append(r)
            else:
                imoveis_resumo.append({
                    "id": r.get("id"),
                    "url": r.get("sourceUrl"),
                    "endereco": r.get("address"),
                    "bairro": r.get("neighbourhood") or r.get("regionName"),
                    "tipo": r.get("type"),
                    "quartos": r.get("bedrooms"),
                    "banheiros": r.get("bathrooms"),
                    "vagas": r.get("parkingSpaces"),
                    "area_m2": r.get("area"),
                    "aluguel": r.get("rent"),
                    "custo_total": r.get("totalCost"),
                    "preco_venda": r.get("salePrice"),
                    "mobiliado": r.get("isFurnished"),
                    "fotos": r.get("photosCount", 0),
                    "photos": r.get("photos", []),
                    "suites": r.get("suites"),
                    "iptu": r.get("iptu"),
                    "amenities": r.get("amenities", []),
                })

        return {
            "total": len(results),
            "cidade": cidade,
            "modalidade": modalidade,
            "filtros_aplicados": filtros_aplicados,
            "imoveis": imoveis_resumo,
            "pasta_saida": str(out.resolve()),
        }

    except Exception as e:  # noqa: BLE001
        return {"erro": str(e)}


@mcp.tool()
async def buscar_lote(
    ids_ou_urls: list[str],
    pasta_saida: str | None = None,
    segundos_entre_requisicoes: float = 2.0,
) -> dict:
    """
    Busca dados e fotos de vários imóveis do QuintoAndar de uma vez,
    a partir de uma lista de IDs numéricos ou URLs.

    Útil quando o usuário tem uma lista de imóveis previamente selecionados
    e quer baixar todos os dados e fotos em lote.

    Args:
        ids_ou_urls: Lista de IDs numéricos ou URLs dos imóveis.
                     Podem ser misturados. Ex:
                     ["894340784", "https://www.quintoandar.com.br/imovel/893000001/..."]
        pasta_saida: Pasta raiz onde criar subpastas por imóvel. Padrão: pasta output/ dentro do diretório do projeto.
        segundos_entre_requisicoes: Pausa em segundos entre cada requisição para
                                    não sobrecarregar a API. Padrão: 2.0.

    Returns:
        Dicionário com:
          - "total": número de itens processados
          - "sucesso": quantidade de imóveis obtidos com êxito
          - "erros": quantidade de falhas
          - "resultados": lista com o resultado de cada item (dados do imóvel ou erro)
          - "pasta_saida": caminho onde os dados foram salvos
    """
    import anyio
    out = Path(pasta_saida) if pasta_saida else _default_output()
    try:
        results = await anyio.to_thread.run_sync(
            _buscar_lote, ids_ou_urls, out, segundos_entre_requisicoes
        )
        sucessos = [r for r in results if "erro" not in r]
        falhas = [r for r in results if "erro" in r]
        return {
            "total": len(results),
            "sucesso": len(sucessos),
            "erros": len(falhas),
            "resultados": results,
            "pasta_saida": str(out.resolve()),
        }
    except Exception as e:  # noqa: BLE001
        return {"erro": str(e)}



@mcp.tool()
def listar_imoveis_salvos(pasta_saida: str | None = None) -> dict:
    """
    Lista todos os imóveis já baixados na pasta de output local, sem fazer
    nenhuma requisição à internet. Útil para ver o que já está disponível
    antes de buscar novamente.

    Args:
        pasta_saida: Pasta raiz onde os imóveis foram salvos. Padrão: output/ do projeto.

    Returns:
        Dicionário com:
          - "total": número de imóveis salvos
          - "pasta_saida": caminho absoluto da pasta
          - "imoveis": lista com resumo de cada imóvel (id, endereço, preços,
            quartos, área, fotos disponíveis localmente)
    """
    out = Path(pasta_saida) if pasta_saida else _default_output()
    if not out.exists():
        return {"total": 0, "pasta_saida": str(out.resolve()), "imoveis": []}

    imoveis = []
    for json_path in sorted(out.glob("*/imovel.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            fotos_locais = sum(
                1 for p in data.get("photos", []) if p.get("localPath")
            )
            imoveis.append({
                "id": data.get("id"),
                "url": data.get("sourceUrl"),
                "endereco": data.get("address"),
                "bairro": data.get("neighbourhood") or data.get("regionName"),
                "tipo": data.get("type"),
                "quartos": data.get("bedrooms"),
                "banheiros": data.get("bathrooms"),
                "vagas": data.get("parkingSpaces"),
                "area_m2": data.get("area"),
                "aluguel": data.get("rent"),
                "custo_total": data.get("totalCost"),
                "mobiliado": data.get("isFurnished"),
                "fotos_salvas": fotos_locais,
                "pasta": str(json_path.parent),
            })
        except Exception as e:  # noqa: BLE001
            imoveis.append({"pasta": str(json_path.parent), "erro": str(e)})

    return {
        "total": len(imoveis),
        "pasta_saida": str(out.resolve()),
        "imoveis": imoveis,
    }


@mcp.tool()
def ler_imovel(
    id_imovel: str,
    pasta_saida: str | None = None,
    max_fotos: int = 5,
) -> list:
    """
    Lê os dados completos e as fotos de um imóvel salvo localmente,
    retornando o JSON de detalhes seguido das imagens em base64 para
    visualização direta no assistente.

    Se as fotos ainda não foram baixadas (busca feita sem baixar_fotos=True),
    esta tool as baixa automaticamente da internet antes de retornar.

    Args:
        id_imovel: ID numérico do imóvel (ex: "894340784").
        pasta_saida: Pasta raiz onde o imóvel foi salvo. Padrão: output/ do projeto.
        max_fotos: Número máximo de fotos a retornar. Padrão: 5.
                   Use 0 para retornar apenas os dados sem imagens.

    Returns:
        Lista de conteúdo com:
          - Primeiro item: dicionário com todos os dados do imóvel
          - Itens seguintes: imagens JPEG das fotos (até max_fotos)
        Em caso de erro, retorna lista com um item de texto descrevendo o erro.
    """
    import requests as _requests
    from scraper import IMG_HEADERS

    imovel_dir = (Path(pasta_saida) if pasta_saida else _default_output()) / id_imovel
    json_path = imovel_dir / "imovel.json"

    if not json_path.exists():
        return [{"type": "text", "text": f"Imóvel {id_imovel} não encontrado em {imovel_dir}. Use buscar_imovel para baixá-lo primeiro."}]

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [{"type": "text", "text": f"Erro ao ler imovel.json: {e}"}]

    resumo = {k: v for k, v in data.items() if k != "photos"}
    resumo["total_fotos"] = data.get("photosCount", 0)
    content: list = [resumo]

    if max_fotos <= 0:
        return content

    session = _requests.Session()
    img_dir = imovel_dir / "images"
    img_dir.mkdir(exist_ok=True)

    entregues = 0
    for idx, photo in enumerate(data.get("photos", [])):
        if entregues >= max_fotos:
            break

        img_bytes: bytes | None = None

        # 1. Tenta ler do disco
        local = photo.get("localPath")
        if local:
            p = Path(local)
            if p.exists():
                try:
                    img_bytes = p.read_bytes()
                except Exception:
                    pass

        # 2. Se não tem local, baixa da URL e salva para próximas chamadas
        if img_bytes is None:
            purl = photo.get("url")
            if not purl:
                continue
            try:
                r = session.get(purl, headers=IMG_HEADERS, timeout=30)
                r.raise_for_status()
                img_bytes = r.content
                # Persiste no disco e atualiza o JSON
                file_name = f"{idx:03d}_{purl.split('/')[-1][:40]}.jpg"
                dest = img_dir / file_name
                dest.write_bytes(img_bytes)
                photo["localPath"] = str(dest)
            except Exception:  # noqa: BLE001
                continue

        if img_bytes:
            content.append(Image(data=img_bytes, format="jpeg"))
            entregues += 1

    # Persiste localPaths recém-preenchidos
    data_atualizado = {**data, "photos": data.get("photos", [])}
    json_path.write_text(json.dumps(data_atualizado, ensure_ascii=False, indent=2), encoding="utf-8")

    return content


if __name__ == "__main__":
    import os
    import sys

    # Se a variável PORT estiver presente (como no Railway) ou se for passado '--sse'
    if "PORT" in os.environ or "--sse" in sys.argv:
        port = int(os.environ.get("PORT", 8000))
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        mcp.run(transport="sse")
    else:
        mcp.run()
