---
name: obra-em-camadas
description: Orquestra uma obra inteira de ponta a ponta — fotos de drone (nadirais + oblíquas) e pasta de projeto no Google Drive até o HTML interativo com ortofoto, 3D, pranchas vetoriais por layer CAD, etapas, escopo de materiais e sondagens. Use quando o usuário pedir "faça o mesmo para a obra X", passar uma pasta do Drive de uma obra nova, ou pedir o HTML em camadas completo. Define a divisão de trabalho Haiku/Sonnet/Opus.
---

# Obra em camadas: do Drive ao HTML

Referência viva: `exemplos/foz/obra.json` e `docs/PLANO_FOZ.md` (ETA Vila C, Foz do Iguaçu).
O pipeline inteiro é `python -m camadas.obra <obra.json>`. Cada etapa grava cache em
`saida/<obra>/`; use `--refazer sfm,pranchas,controle` para refazer.

## Divisão de trabalho (custo × qualidade)

| Quem | Tarefas | Por quê |
|---|---|---|
| **Haiku** (`model: "haiku"`) | inventário recursivo do Drive (só metadados) → CSV; download em massa dos PDFs/fotos e decodificação base64 | mecânico, muitas chamadas, zero julgamento |
| **Sonnet** (`model: "sonnet"`) | ler planilhas de orçamento e extrair escopo/etapas; ler relatórios de sondagem, pranchas de fundação, TR e memoriais e estruturar em JSON; implementar front-end a partir de spec | leitura técnica extensa com regras claras |
| **Opus** (sessão principal) | arquitetura, decisões de engenharia, georreferenciamento (pontos de controle visuais, validação), SfM/ortofoto, revisão dos resultados dos agentes, PR | julgamento, geometria, integração |

Rode os agentes Haiku/Sonnet **em segundo plano e em paralelo**, com prompts autocontidos
(ids do Drive, pasta de saída, formato exato de saída, "não invente"). Nunca deixe dois agentes
varrerem a mesma pasta `tool-results/` (um recolhe os downloads do outro).

## Passos

1. **Inventário (Haiku)** — skill `drive-ingestao`. Saída: CSV com caminho;titulo;id;mime;tamanho.
   Destaque: sondagem, fundação, layout/implantação, memorial, planilha orçamentária, "etapa".
2. **Fotos** — baixe as fotos do drone para `dados/<obra>/foto_drone/` (skill `drive-ingestao`).
3. **3D + ortofoto** — skill `modelo-3d-drone`: `python -m camadas.sfm <fotos> saida/<obra>/sfm --denso --orto 0.04`.
   A classificação nadir/oblíqua sai da pose do SfM (o EXIF do DJI Mini 2 grava pitch 0).
4. **Download dos PDFs (Haiku)** e **leituras técnicas (Sonnet)** em paralelo:
   - orçamento → skill `escopo-etapas` (`camadas/orcamento_sanepar.py`);
   - sondagens/fundação/etapas → JSON (`sondagens.json` com E/N, NSPT, camadas; `fundacoes.json`; `etapas.json`;
     `coordenadas_referencia.json` com qualquer afim pt→UTM obtida de coordenadas topográficas).
5. **Georreferenciar pranchas (Opus)** — skill `georef-pranchas`. Uma prancha base por pontos de
   controle; as demais como "irmãs" (CAD × CAD) ou por afim absoluta. Controle absoluto
   (sondagens locadas por topografia) corrige o viés do GPS do drone.
6. **obra.json** — copie `exemplos/foz/obra.json` e ajuste caminhos, pranchas, etapas, escopo,
   sondagens e `controle_absoluto`. Rode `python -m camadas.obra`.
7. **Visualizador** — `saida/<obra>/visualizador.html` (offline). Teste com
   `python scripts/testar_visualizador.py saida/<obra>/visualizador.html`.
   Para publicar (Artifact, limite 16 MB) use a versão `visualizador_artifact.html` (CDN) e, se
   passar do limite, reduza `max_pontos_3d` e `res_html` no obra.json.
8. **Conferência visual (Opus)** — sobreponha cada prancha aceita à ortofoto em zoom alto; marque
   no obra.json como pendente o que não convencer. Nunca aceite georreferência só pelo número.

## Regras que valem ouro
- **Mantenha o vetor.** PDF de prancha tem layers CAD, textos e quantidades: nada de rasterizar
  para o HTML (`pdf_cad.pacote_vetorial`).
- Coordenadas sempre em SIRGAS 2000 / UTM no Python; o navegador só converte para exibir.
- Dados do cliente (orçamento com preços, PDFs, fotos) ficam em `dados/` (fora do git).
- Relate lacunas explicitamente (ex.: "3ª etapa existe no desenho mas não no TR").
