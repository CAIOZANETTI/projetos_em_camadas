---
name: eap-evidencias
description: Lê edital, termo de referência, memorial ou laudo e preenche a EAP com evidências de IA, sem nunca pôr número sem citação conferida ("a IA propõe, o código confere") — gera o roteiro de leitura por item da EAP, escreve uma linha JSON por afirmação com o trecho copiado literalmente e roda `python -m camadas.evidencias conferir`. Use quando o usuário pedir para ler documentos de texto (edital, TR, memorial descritivo, laudo) e levar quantidades e menções para a EAP, ou para conferir evidências propostas por IA.
---

# Ler documentos para a EAP: a IA propõe, o código confere

A IA não é fonte de número. Ela **localiza** onde o documento diz algo e **copia** a linha. O código confere que a
linha existe no documento e que o número está nela (`conferir_citacao`). Só o que passa entra na EAP.

## Passo a passo
1. **Roteiro** — o que procurar em cada documento, por item da EAP geral:
   ```bash
   uv run python -m camadas.evidencias roteiro --escopo esgoto --obra localizada --saida saida/<obra>/roteiro.md
   ```
   Cada item traz código, nome, termos de busca (com sinônimos), serviços admitidos e unidades aceitas.
2. **Ler cada documento**, página por página (`camadas.evidencias.paginas_pdf(pdf)` devolve o texto por página).
   Percorra o roteiro item a item; procure os termos e os serviços.
3. **Escrever uma linha JSON por afirmação** em `saida/<obra>/ia.jsonl`, com:
   - `metodo: "ia"` e `documento.tipo: "ia"`; `documento.id` = nome do arquivo (`memorial_fundacoes.pdf`);
   - `trecho`: **copiado literalmente** do documento, a linha onde está o número (nunca resumido nem refeito), com
     pelo menos 3 palavras ou 15 caracteres; palavra do trecho não pode ser só parte de outra ("250" não está em
     "1250"). Copie sem quebra de linha nem hífen de fim de linha (`fun-` / `dações` não casa com `fundações`);
   - `localizador`: `"p. N"`;
   - `valor` e `unidade` normalizada, uma das do vocabulário (`un`, `m`, `m²`, `m³`, `kg`, `t`, `vb`, `cj`, `m³xkm`,
     `h`, `dia`; as mesmas que o roteiro lista); `valor` nunca negativo; `valor: null` e `unidade: null` quando o
     trecho só cita o item, sem número (menção). O par (`valor`, `unidade`) tem de ser o que o próprio trecho diz
     ("250 estacas" → 250 `un`; "20 m²" → 20 `m²`); outro número do trecho (o 400 de "diâmetro 400 mm") é recusado;
   - `codigo` da EAP, com `*` no segmento que o documento não diz (`U1.*.GEO.FUN.EST`: estacas da U1, sistema não
     dito); `servico` = id do banco de serviços ou `""` para o próprio item;
   - `parcela`: `true` se o número é parte que se soma no documento; `false` se é o total.
4. **Conferir**:
   ```bash
   uv run python -m camadas.evidencias conferir saida/<obra>/ia.jsonl --pdf dados/<obra>/memorial_fundacoes.pdf \
       --texto dados/<obra>/laudo.txt --saida saida/<obra>/ia_aceitas.jsonl
   ```
   O relatório diz quantas foram aceitas e, de cada recusada, o motivo: schema inválido, documento não fornecido,
   trecho não encontrado, valor não está no trecho. O código de saída é 0 mesmo com recusas (é relatório); 2 se o
   arquivo de entrada não existe. O arquivo `--saida` leva só as aceitas, com `citacao: "conferida"`.
5. **Recusada volta para a escada** (Sonnet relê o documento; persistindo, o humano). Ela **nunca** é corrigida à mão
   no número: ou o trecho copiado passa a ser o do documento, ou a afirmação sai.
6. **Aceitas entram no build**: aponte `evidencias.ia` do `obra.json` **só** para `ia_aceitas.jsonl` (nunca para o
   `ia.jsonl` cru). O build **reconfere** cada linha contra os documentos de `evidencias.documentos` e não confia no
   selo `citacao` do arquivo: sem o documento, a linha fica registrada com o motivo e não entra nos fatos. A leitura
   da IA é afirmação própria (`documento.id` = `ia:<arquivo>`), nunca soma com a do regex no mesmo documento, e também
   não aumenta a `forca`: IA e regex no mesmo arquivo são uma fonte só (concordam: fonte única; divergem: conflito).

## Exemplo de linha válida (uma linha do JSONL)
```json
{"codigo": "U1.*.GEO.FUN.EST", "servico": "", "unidade": "un", "valor": 250, "parcela": false, "documento": {"id": "memorial_fundacoes.pdf", "tipo": "ia"}, "localizador": "p. 4", "metodo": "ia", "trecho": "Serão executadas 250 estacas hélice contínua, diâmetro 400 mm."}
```
`id` (hash) e `regra` ("leitura por IA") ausentes são completados pelo `conferir`; não calcule hash.

## Regras
- **A mesma linha.** O número, a unidade e o termo do item têm de estar na mesma linha do documento, a no máximo 8
  palavras um do outro (o trecho pode ocupar mais linhas, nunca mais de uma página). Em tabela, copie a linha inteira
  ("Estaca hélice contínua Ø40 un 250"), não o número de uma linha com o nome de outra.
- **Item e serviço existem.** `codigo` com o item da EAP geral (`*` só em unidade e sistema), `servico` admitido pelo
  item (ou `""`) e `unidade` aceita por eles; o roteiro lista tudo. `localizador` "p. N" tem de ser a página do trecho.
- **Parcelas iguais.** Duas parcelas com o mesmo valor no mesmo documento contam uma vez: para somar quantidades iguais,
  cite o total (`parcela: false`).
- **Nunca inventar número.** Sem número no trecho, `valor: null` (menção).
- **Uma linha por afirmação.** Duas quantidades na mesma frase são duas linhas (com o mesmo trecho).
- **Não somar no texto.** Duas parcelas em linhas diferentes são duas evidências `parcela: true`; quem soma é o código.
- O `valor` tem de ser um número escrito no trecho (`1.200,5` no texto vira `1200.5`). Não converta unidade: se o
  trecho diz "2,5 t", são `2.5` e `t`.
- O documento citado em `documento.id` tem de ser um dos fornecidos a `conferir`.
- Texto puro (`--texto`): as páginas são separadas por quebra de página (`\f`); sem ela, é uma página só.
- `id`, `citacao`, `derivada`, `autor` e `justificativa` são do código: se vierem na linha, são descartados e `id` é
  recalculado. `documento.id` com caminho vira o nome do arquivo.
- Documento escaneado (sem texto) não serve para `conferir`: peça OCR antes (escada: Haiku/Sonnet).
