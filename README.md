# Ponto — registro de ponto de funcionários

Sistema web simples para registrar a jornada dos funcionários e gerar o
espelho de ponto mensal. Feito em Python (Flask) com banco SQLite — não
precisa de servidor de banco de dados.

## Funcionalidades

- **Tela de registro (quiosque)**: o funcionário informa matrícula e PIN e
  o sistema grava o horário do servidor (o funcionário não escolhe a hora).
  A marcação é identificada automaticamente como Entrada, Saída intervalo,
  Retorno intervalo ou Saída, e é exibido um comprovante.
- **Proteção contra duplicidade**: bloqueia nova marcação em menos de 1 minuto.
- **Marcações imutáveis**: o banco impede alterar ou apagar marcações
  (triggers no SQLite). Correções entram como novas marcações manuais, com
  justificativa obrigatória, e aparecem destacadas no espelho.
- **Administração** (protegida por senha):
  - cadastro de funcionários (matrícula, nome, PIN e horas de trabalho em
    cada dia da semana, de segunda a domingo);
  - cadastro de feriados, com inclusão automática dos feriados nacionais
    (e, opcionalmente, Carnaval e Corpus Christi);
  - ativar/desativar funcionário e trocar PIN;
  - histórico de jornadas: ao mudar a jornada, escolhe-se a data a partir
    da qual ela vale; os dias anteriores mantêm a jornada da época;
  - relatório de horas por período (data inicial e final) para os
    funcionários escolhidos ou todos, com horas trabalhadas, esperadas,
    horas extras, horas faltando, saldo e faltas (com CSV);
  - espelho de ponto mensal com horas trabalhadas, esperadas e saldo por dia;
  - indicação, por funcionário, se a jornada tem intervalo (4 marcações:
    entrada, saída intervalo, retorno intervalo e saída) ou não (entrada e
    saída);
  - tela de cada dia (clique na data no espelho de ponto) para corrigir o
    horário de uma marcação, desconsiderar uma marcação errada ou incluir
    uma esquecida, sempre com justificativa. A marcação original nunca é
    apagada: fica registrada, riscada, com o motivo;
  - tela Aparência para escolher as cores e enviar o logotipo da empresa;
  - exportação do espelho em CSV (abre no Excel).

## Como rodar

1. Instale o Python 3 (https://www.python.org/downloads/). No Windows,
   marque **"Add Python to PATH"** na instalação.
2. Baixe esta pasta do projeto.
3. Dê dois cliques em:
   - **Windows:** `iniciar.bat`
   - **Mac/Linux:** `iniciar.sh` (ou rode `./iniciar.sh` no Terminal)

Na primeira vez o programa instala o que precisa e pede a senha da área
administrativa. Depois mostra os endereços para abrir no navegador, por
exemplo `http://localhost:5000`. Deixe a janela aberta enquanto o sistema
estiver em uso.

A senha fica em `instance/config.py`. Para trocá-la, apague esse arquivo e
inicie o programa de novo.

Opcionalmente, o fuso horário pode ser alterado pela variável de ambiente
`PONTO_TIMEZONE` (padrão `America/Sao_Paulo`).

O banco fica em `instance/ponto.sqlite3`. Faça backup desse arquivo.

Para produção, use um servidor WSGI (ex.: `pip install waitress` e
`waitress-serve --port 5000 app:app`) atrás de HTTPS.

## Cores e logotipo

Na área administrativa, menu **Aparência**: escolha a cor principal, as
cores da barra do topo e envie o logotipo (PNG, JPG ou WEBP). Tudo fica
salvo na pasta `instance`, junto com os dados.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

## Regras de cálculo

- As marcações do dia são pareadas em ordem: (entrada, saída), (entrada, saída)...
- Número ímpar de marcações → dia sinalizado como "marcação faltando".
- A jornada esperada de cada dia vem da escala semanal que estava em vigor
  naquele dia (dias sem horas são folga). Dias anteriores ao cadastro do
  funcionário e dias futuros não contam.
- Em feriados a jornada esperada é zero; horas trabalhadas no feriado
  entram como saldo positivo.
- Mudanças de jornada só valem da data escolhida em diante (hoje ou uma
  data futura); mudanças programadas podem ser canceladas antes de começar.
- Horas extras = soma dos saldos positivos de cada dia; horas faltando =
  soma dos saldos negativos. O saldo do mês é a diferença entre os dois.

## Aviso legal

Este projeto é uma base para controle interno. No Brasil, o registro
eletrônico de ponto é regulado pela **Portaria MTP nº 671/2021**; o uso
como sistema oficial (REP-P) exige, entre outros requisitos, registro do
programa no INPI, geração dos arquivos AFD/AEJ, comprovante assinado
digitalmente e atestado técnico. Consulte um contador ou advogado
trabalhista antes de usá-lo como controle oficial.

## Próximos passos sugeridos

- Escalas que não se repetem toda semana (ex.: 12x36).
- Banco de horas acumulado entre meses.
- Banco de horas acumulado e cálculo de horas extras / adicional noturno.
- Relatório em PDF com assinatura do funcionário.
- Vários usuários administradores com log de auditoria.
- Restrição do registro a IPs/dispositivos da empresa ou geolocalização.
