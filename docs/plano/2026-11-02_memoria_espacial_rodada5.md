# Plano — memória espacial, rodada 5: cavas e setores da ETA

Pedido do Caio (02/11/2026): seguir com as cavas e os setores da ETA, que ficaram fora da rodada 24
(`docs/MEMORIA_ESPACIAL.md` §8). O método é o mesmo das rodadas 21 a 24: o gerente (Opus) especifica e decide,
executores Sonnet trabalham em worktrees, cada entrega passa pelo `vcm balanco` e o Fable faz o aceite independente
antes do PR.

Numeração: outra sessão usa "rodada 25" na `main` para geotecnia e obras lineares. Para não colidir, este plano se
chama "memória espacial, rodada 5" (as rodadas 21 a 24 foram as quatro primeiras). A versão é a próxima livre na hora
do PR.

## Desenho (decisões do gerente, fixadas antes)

**Cavas.** O volume de uma cava sai de uma grade: o terreno vem do MDS do drone, o fundo das cotas lidas por OCR nas
plantas de escavação, a região das bases e cristas desenhadas, mais o talude e a folga do MOS
(`escavacao.calcular`). Uma grade não cabe em fato. Por isso:
- **Gaveta nova `superficies`** (`conceitos/gavetas.json`): o terreno, a máscara de válido e a de edificação, com
  `res_m`, `e0` e `n1`, vão para um arquivo `.npz` ao lado da base, e a gaveta guarda o caminho, o **sha256**, o CRS,
  o datum e a evidência (ortofoto e MDS do drone, natureza `observado`). A regra lê o `.npz` e confere o sha256; se
  diferir, o resultado é erro, não um cálculo sobre outro terreno.
- **Objeto `conjunto_cavas`**, um por obra, com os fatos `marcas_cota` (cada marca com o texto do OCR e a prancha),
  `bases`, `cristas` e `superficie_id`, todos `projetado`, com a evidência nas pranchas e nos layers.
  `superficie_id` aponta para a superfície.
- **Regra `cavas`** (`escavacao.quantificar_gavetas`): reconstrói a grade a partir do `.npz` e chama o
  `escavacao.calcular` atual. Devolve, por cava (`C01`, `C02`…), escavação, reaterro e área, que entram na EAP como
  CV.01 a CV.03.
- **Chave do incremental**: a impressão da regra e os dados. O sha256 da superfície entra nos dados, então trocar o
  MDS recalcula.
- **Paridade** com o `escavacao.etapa` atual: os mesmos volumes por cava.

**Setores da ETA (G09).** A obra localizada é dividida em setores. Isso organiza o processamento, a consulta e a EAP;
não muda nenhum cálculo.
- **Setores declarados** no `obra.json` (`gavetas.setores: [{id, nome, coords}]`). Cada um vira objeto `setor`, com
  geometria `poligono`, natureza `decidido` e evidência no obra.json.
- **`gavetas.setor_de(base, ind)`**: cada objeto com geometria cai no setor que contém o seu ponto representativo
  (ponto: o próprio; linha: o meio do comprimento; polígono: `representative_point`). Fora de todos os setores, fica
  "fora dos setores", sem pendência. Dois setores sobrepostos e o objeto nos dois → pendência "setores sobrepostos".
  O resultado é determinístico.
- **EAP por setor**: `eap_html.montar` ganha `setores` (por setor, os nós com o total e a contagem de serviços), e a
  aba EAP mostra uma tabela por setor. O JS só apresenta.
- Não muda nenhuma quantidade: o total de cada nó é a soma dos setores mais o "fora dos setores".

## Critério da rodada (fixado antes)

1. Cavas: paridade 0 (tolerância 0,1 m³ e 0,1 m²) com `escavacao.calcular` sobre a mesma grade, numa grade sintética
   como a de `tests/test_escavacao.py`. Mudar o terreno, ou só um byte do `.npz`, muda a chave e recalcula. Um `.npz`
   com sha256 diferente do registrado é erro.
2. Setores: a soma dos setores mais o "fora dos setores" é igual ao total de cada nó, sem diferença. Cada objeto cai
   em exatamente um setor ou em "fora dos setores", e a sobreposição vira pendência.
3. Os verdes de sempre:
   - `uv run --with pymupdf --with rasterio --with playwright pytest -q` sem falhas;
   - aferição, determinismo, ruff e bandit 0;
   - hash da referência inalterado (ou mudança explicada);
   - `vcm balanco` sem REVERTER e aceite do Fable.

## Entregas

| # | Entrega | Agente | Estado |
|---|---|---|---|
| E1 | Cavas nas gavetas: gaveta `superficies`, `escavacao.quantificar_gavetas`, `extrair_gavetas.de_cavas`, paridade e ligação na etapa | Sonnet A | feito — 14 testes; `.npz` determinístico (zip montado à mão); superfície pela `pasta_base` na `entrada`; a etapa roda também sem planilha, quando há cavas |
| E2 | Setores: `de_setores`, `gavetas.setor_de`, EAP por setor (Python e aba) | Sonnet B (paralelo; não toca `escavacao.py`) | feito — soma por setor conferida (tolerância 0,005 pelo arredondamento de `para_eap`); tabela por setor no Chromium |
| E3 | Integração, `vcm balanco`, aceite do Fable, PR | Opus; Fable | integração feita (0.33.0, L029); falta balanço e aceite |

Contrato já escrito em `conceitos/` pelo gerente:
- gaveta `superficies` e `tipos_superficie`;
- propriedades `marcas_cota`, `bases`, `cristas`, `superficie_id`, `setor` e `nome`;
- de-para 1 "plantas de escavação" e "setores da obra";
- regra `cavas`;
- nós CV.01 a CV.03.

## Emendas
- 02/11, **integração (gerente).**
  - O conjunto de cavas é um objeto só, sem geometria, e todas as cavas caíam em "fora dos setores". Para a ETA isso
    não serve. O gerente acrescentou: `escavacao.quantificar_gavetas` devolve um ponto dentro de cada cava; o
    serviço guarda `ponto`; `gavetas.setor_dos_servicos` põe cada cava no seu setor (o setor do serviço vence o do
    objeto em `para_eap_por_setor`). Teste: `test_cada_cava_cai_no_seu_setor_pelo_ponto_do_servico`.
  - A gaveta `superficies` quebrou a ida e volta da bancada de gavetas, porque o sintético não a trazia. O sintético
    passou a montar todas as gavetas do contrato.
  - Merge da `main`: o PR #18 (EAP codificada, 0.32.0) e a rodada 25 da outra sessão (0.31.0, dimensionador único de
    vala). O hash da referência mudou para `0602c637…` no PR #33 da outra sessão; esta rodada não o muda.
  - Decisões dos executores aceitas:
    - um ponto na divisa de dois setores conta nos dois e vira pendência de sobreposição;
    - o fato `superficie_id` aponta para a evidência da superfície;
    - as marcas guardam `topo`;
    - a etapa roda também sem a planilha de obras lineares, quando há cavas, para a ETA não perder as cavas em
      silêncio.
- 02/11, **1º aceite do Fable: REVISAR** (E1 e o ajuste do gerente foram aceitos). Achados:
  1. **As duas EAP colidiam no build.** A das gavetas ia para `dados["eap"]`, e vinte linhas depois a EAP codificada
     do PR #18 sobrescrevia a mesma chave. A aba das gavetas sumia ou mostrava o formato errado, e a tabela por setor
     não chegava ao HTML real. O teste do Chromium não pegava o problema porque montava `dados` à mão.
  2. O bandit acusava um B324 em `camadas/evidencias.py:79`, que veio do PR #18.

  Riscos também apontados:
  - um ponto na divisa de setores vizinhos virava pendência;
  - a conferência da soma por setor derrubaria a aba numa obra grande;
  - o `onde` da evidência das cavas aparecia em JSON cru.

  Correção do gerente:
  - a EAP das gavetas vai para a chave própria `dados["eap_gavetas"]`, e a aba lê só ela; teste de `_aba_projeto`
    com as duas EAP convivendo, e teste no Chromium com as duas chaves;
  - `usedforsecurity=False` em `evidencias.py`;
  - na divisa, o setor é o 1º declarado, sem pendência; a sobreposição real (`contains` em dois setores) continua
    pendência;
  - a tolerância da soma acompanha o erro máximo do arredondamento (0,0005 × 2 × n de serviços);
  - o critério entra no localizador das cavas.
