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
  - cadastro de funcionários (matrícula, nome, PIN, jornada diária);
  - ativar/desativar funcionário e trocar PIN;
  - espelho de ponto mensal com horas trabalhadas, esperadas e saldo por dia;
  - inclusão de marcação esquecida com justificativa;
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

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

## Regras de cálculo

- As marcações do dia são pareadas em ordem: (entrada, saída), (entrada, saída)...
- Número ímpar de marcações → dia sinalizado como "marcação faltando".
- A jornada esperada vale de segunda a sexta, até o dia de hoje; sábados,
  domingos e dias futuros não contam. Feriados ainda não são considerados.

## Aviso legal

Este projeto é uma base para controle interno. No Brasil, o registro
eletrônico de ponto é regulado pela **Portaria MTP nº 671/2021**; o uso
como sistema oficial (REP-P) exige, entre outros requisitos, registro do
programa no INPI, geração dos arquivos AFD/AEJ, comprovante assinado
digitalmente e atestado técnico. Consulte um contador ou advogado
trabalhista antes de usá-lo como controle oficial.

## Próximos passos sugeridos

- Cadastro de feriados e escalas diferentes por funcionário (ex.: 6x1, 12x36).
- Banco de horas acumulado e cálculo de horas extras / adicional noturno.
- Relatório em PDF com assinatura do funcionário.
- Vários usuários administradores com log de auditoria.
- Restrição do registro a IPs/dispositivos da empresa ou geolocalização.
