---
name: drive-ingestao
description: Inventaria e baixa pastas de obra do Google Drive pelo conector (metadados recursivos, download base64 em lote, decodificação) para dados/<obra>/. Use quando o usuário passar um link de pasta do Drive com fotos de drone, PDFs de projeto ou planilhas, ou pedir para baixar/organizar arquivos do Drive. Tarefa ideal para um agente Haiku.
---

# Ingestão do Google Drive

## Inventário (agente Haiku, segundo plano)
`mcp__Google_Drive__search_files` com `parentId = '<id>'`, `pageSize 100`, `excludeContentSnippets true`,
paginando `pageToken`; desça em cada `application/vnd.google-apps.folder`. Grave CSV
`caminho;titulo;id;mimeType;extensao;tamanho_bytes;modificado`. Só metadados.

## Download
- `mcp__Google_Drive__download_file_content(fileId)` devolve base64. Resultados grandes são gravados em
  `~/.claude/projects/<proj>/<sessão>/tool-results/mcp-Google_Drive-download_file_content-*.txt`
  (JSON `{content, title, id, mimeType}`); decodifique com Python **sem ler o base64 no contexto**
  e apague o .txt.
- **Limites do conector**: > 10 MB é recusado; ~5,5–10 MB costuma derrubar a conexão ("message too
  large"). Liste esses arquivos para o usuário baixar manualmente (ou subir em partes).
- Só **um** processo varre `tool-results/` por vez (agentes paralelos roubam os arquivos uns dos outros).
- Fotos do drone: `dados/<obra>/foto_drone/`; projeto: `dados/<obra>/projeto/<caminho do Drive>/`.
  `dados/` está no `.gitignore` (material do cliente).

## Depois de baixar
- confira `%PDF` / tamanho; registre `_baixados.csv`;
- PDFs: `pdf_cad.layers_pdf` (tem layers?) e `get_text` (tem texto ou é curva?) — isso decide
  extração vetorial e busca de texto no visualizador.

## Inventário determinístico (nada some)
A listagem do conector (CSV acima, copiado para `dados/<obra>/projeto/_listagem_drive.csv`) é a referência. No
`obra.json`: `"inventario": {"listagem", "baixados", "pasta", "fonte"}`; `camadas/inventario.py` dá a **cada PDF
da listagem** uma linha com situação (no disco / mesmo nome em outra pasta / falhou no download / não tentado),
formato da folha (A0–A4, estendido), código Sanepar, carimbo lido no canto inferior direito (texto, fonte ArialMT
reparada ou OCR) e tipo planta × detalhe × documento (`conceitos/tipos_prancha.json`). Confira: nº de linhas =
nº de PDFs da listagem e nenhum PDF do disco fora dela. Rode avulso com `python -m camadas.inventario
exemplos/<obra>/obra.json`. Os "não tentados" e os que falharam são a lista de download pendente.
