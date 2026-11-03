# Decisão da iteração e8c9cac → 6b393eb (conferência das cavas, 0.53.0, depois de 3 aceites do Fable)

- **Proposta pelo balanço:** DECISAO_HUMANA
- **Registrada:** MANTER, pelo gerente. O Caio autorizou "pode seguir até o merge" nesta rodada; o precedente é a
  rodada 21. A troca fica explícita para a revisão dele no PR.
- **Troca:**
  - **Piorou:** linhas por função 12,983 → 13,415 (+3,3 %), pelos dois módulos novos (`secoes_corte.py` e
    `conferencia_cavas.py`, que leem geometria de CAD e OCR).
  - **Melhorou:** complexidade média 6,348 → 6,194 (−2,4 %); entram 62 testes (1 015 → 1 077); tempo de referência
    igual (−2,5 %) e pico de RAM igual (+0,1 %).
  - **Sem mudança:** determinismo (1), testes falhando (1, o mesmo OCR local de `test_lineares::test_ler_perfil_ocr`,
    pulado no CI), 0 alertas de segurança, cobertura 81 % e hash da referência.
  - Todas as funções ficam abaixo de 60 linhas (aferição ok).
- **Justificativa:** a rodada criou a primeira testemunha independente das cavas (seções de corte e cotas escritas).
  A conferência mostrou o que a conciliação circular escondia:
  - o fundo do modelo bate em 5 de 7 seções;
  - a área difere sobretudo pelo terreno (o MDS fica até 0,6 m abaixo da topografia do projeto no trecho do corte), como corrigido
    no aceite do Fable.

  O custo em tamanho é o de dois leitores novos de prancha, sem aumento de complexidade.
