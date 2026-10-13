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

```bash
python3 -m venv .venv
source .venv/bin/activate          # no Windows: .venv\Scripts\activate
pip install -r requirements.txt

export PONTO_ADMIN_PASSWORD='uma-senha-forte'
export PONTO_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
flask --app app run --host 0.0.0.0 --port 5000
```

Acesse `http://<ip-da-maquina>:5000` no computador/tablet que ficará na
entrada da empresa. A área administrativa fica em `/admin`.

Configurações por variável de ambiente:

| Variável | Padrão | Descrição |
|---|---|---|
| `PONTO_ADMIN_PASSWORD` | `admin` | Senha da área administrativa (**troque!**) |
| `PONTO_SECRET_KEY` | valor de desenvolvimento | Chave das sessões (**troque!**) |
| `PONTO_TIMEZONE` | `America/Sao_Paulo` | Fuso horário das marcações |

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
