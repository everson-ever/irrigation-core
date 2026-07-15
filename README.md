# Sistema de irrigação automatizado

Sistema de irrigação para Raspberry Pi com agendamentos, acionamento manual,
histórico e painel web no Node-RED.

A aplicação atual foi reestruturada com uma arquitetura em camadas, código
testável e dependências invertidas. Os diretórios históricos das versões
anteriores foram removidos da árvore principal; a versão que deve ser instalada
e executada está na raiz deste repositório.

Classes, métodos, funções, variáveis e comandos principais seguem nomenclatura
em inglês. Os nomes dos arquivos e campos JSON foram mantidos para preservar a
compatibilidade com o dashboard e dados existentes.

## Funcionalidades

- Cadastro, edição, ativação, desativação e remoção de agendamentos.
- Acionamento automático das eletroválvulas.
- Retomada de uma irrigação interrompida enquanto o agendamento ainda é válido.
- Início atrasado quando o sistema volta durante a janela de irrigação.
- Acionamento e desligamento manual.
- Tempo configurável para o desligamento automático no modo manual.
- Registro e pesquisa do histórico por dia ou intervalo de datas.
- Visualização do estado das válvulas no dashboard do Node-RED.
- Suporte a agendamentos que atravessam a meia-noite.
- Driver GPIO simulado para desenvolvimento sem Raspberry Pi.

## Arquitetura

```text
.
├── data/                         # Dados persistidos em JSON Lines
├── deploy/systemd/               # Serviço do scheduler e override do Node-RED
├── node-red/flows.json           # Dashboard e integração atualizados
├── scripts/instalar-raspberry.sh # Instalação automatizada no Raspberry Pi
├── src/irrigacao/
│   ├── application/              # Casos de uso e orquestração
│   ├── domain/                   # Entidades, regras e contratos
│   ├── infrastructure/           # JSON Lines, GPIO e relógio
│   ├── bootstrap.py              # Injeção das dependências
│   └── cli.py                    # Interface usada pelo systemd e Node-RED
├── tests/                        # Testes unitários
└── pyproject.toml                # Pacote, dependências e ferramentas
```

As responsabilidades foram separadas seguindo SOLID:

- As entidades validam apenas regras do domínio.
- Cada serviço representa um conjunto coeso de casos de uso.
- Persistência, relógio e GPIO são contratos injetados nos serviços.
- O driver real pode ser substituído pelo simulado sem alterar as regras.
- A interface do Node-RED chama uma CLI fina; ela não contém regras de negócio.

Os arquivos continuam no formato JSON Lines (um objeto JSON por linha),
compatível com os nós de leitura do fluxo original. As gravações agora usam
lock e substituição atômica para reduzir o risco de corrupção quando Node-RED e
scheduler acessam os dados simultaneamente.

## Hardware padrão

O projeto usa a numeração física dos pinos (`GPIO.BOARD`). A configuração
inicial em [`data/valvulas.json`](data/valvulas.json) é:

| Função | Pino físico |
|---|---:|
| Eletroválvula da Seção 1 | 13 |
| Eletroválvula da Seção 2 | 11 |
| Bomba | 15 |

Adapte `data/valvulas.json` e `IRRIGATION_PUMP_PIN` à instalação real. Use
módulos relé/transistor adequados: os GPIOs não devem alimentar diretamente
bomba ou eletroválvulas. Confirme ainda a lógica elétrica do seu relé antes de
energizar o circuito; esta implementação considera nível alto como ligado.

## Requisitos

- Raspberry Pi com Raspberry Pi OS e Python 3.10 ou superior.
- Acesso aos pinos GPIO.
- Node-RED para usar o painel web.
- O módulo `node-red-dashboard` para importar o dashboard existente.

## Instalação no Raspberry Pi

Clone o repositório e execute o instalador:

```bash
git clone <URL-DESTE-REPOSITORIO>
cd Sistema-de-irriga-o
sudo ./scripts/instalar-raspberry.sh
```

O script:

1. instala Python, `venv` e `pip` pelo sistema;
2. cria `.venv` e instala o projeto com o driver `RPi.GPIO`;
3. inclui o usuário no grupo `gpio`;
4. instala e inicia o serviço `irrigacao.service`;
5. configura o diretório e o `PATH` do serviço Node-RED, quando ele existe.

Depois da primeira instalação, reinicie a sessão ou o Raspberry Pi para que a
alteração do grupo `gpio` tenha efeito:

```bash
sudo reboot
```

### Configurar o Node-RED

Se o dashboard ainda não estiver instalado, execute com o usuário que roda o
Node-RED:

```bash
cd ~/.node-red
npm install node-red-dashboard
```

No editor do Node-RED:

1. abra o menu **Import**;
2. selecione [`node-red/flows.json`](node-red/flows.json);
3. confirme o deploy;
4. abra `http://IP_DO_RASPBERRY:1880/ui`.

O fluxo usa os comandos instalados no `.venv` e lê os arquivos em `data/`. O
scheduler não é iniciado pelo fluxo: ele é mantido pelo `systemd` para reiniciar
automaticamente em caso de falha ou reboot.

## Operação do serviço

```bash
sudo systemctl status irrigacao
sudo systemctl restart irrigacao
sudo systemctl stop irrigacao
journalctl -u irrigacao -f
```

Para alterar a configuração sem editar o código, crie
`/etc/default/sistema-irrigacao`:

```bash
IRRIGATION_DATA_DIR=/caminho/absoluto/para/data
IRRIGATION_GPIO_DRIVER=rpi
IRRIGATION_PUMP_PIN=15
IRRIGATION_POLL_INTERVAL=2
```

Após a alteração, reinicie o serviço.

## Desenvolvimento sem Raspberry Pi

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export IRRIGATION_GPIO_DRIVER=mock
```

Comandos úteis:

```bash
# Executar o scheduler em primeiro plano
irrigacao run

# Cadastrar: horário,duração em minutos,pino físico
irrigacao schedule create '06:30,15,13'

# Editar: id,horário,duração,pino
irrigacao schedule update '1,07:00,10,13'

# Desativar ou reativar
irrigacao schedule enabled '1,0'
irrigacao schedule enabled '1,1'

# Remover
irrigacao schedule delete 1

# Acionamento manual
irrigacao valve '13,on'
irrigacao valve '13,off'

# Alterar o tempo padrão manual
irrigacao settings 5

# Pesquisar histórico
irrigacao history 'day,,'
irrigacao history 'range,2026-07-01,2026-07-31'
```

No modo manual, o comando `on` permanece ativo até o tempo padrão terminar
ou outro comando `off` desligar a válvula. Isso mantém o comportamento esperado
pelo nó `exec` do Node-RED.

Os comandos antigos em português continuam aceitos como aliases de
compatibilidade, mas a documentação e os fluxos novos usam a CLI em inglês.

## Testes e qualidade

```bash
source .venv/bin/activate
pytest
ruff check src tests
ruff format --check src tests
```

Os testes não acessam GPIO real. Eles verificam validação, compatibilidade com
o campo legado `led`, persistência, início atrasado, reinício, desligamento,
agendamento desativado e intervalo que atravessa a meia-noite.

## Dados e migração da Parte 7

Os arquivos operacionais ficam em `data/`:

- `agendamentos.json`: agendamentos e seu estado de execução;
- `valvulas.json`: pinos, seções e estados;
- `configuracoes.json`: tempo padrão do acionamento manual;
- `historico.json`: log de acionamentos;
- `pesquisaHistoricoResultado.json`: resultado consumido pelo dashboard.

A instalação nova começa sem agendamentos. Para migrar cadastros da versão final
anterior, informe no comando uma cópia externa do diretório legado
`Parte - 7/projeto`:

```bash
sudo systemctl stop irrigacao
cp -a data "data.backup.$(date +%Y%m%d-%H%M%S)"
source .venv/bin/activate
irrigacao migrate-part-7 --source /caminho/para/Parte\ -\ 7/projeto
sudo systemctl start irrigacao
```

O migrador converte o campo antigo `led` para `valvula`, mantém IDs e dados e
zera os estados de execução, evitando reativar uma irrigação antiga. O leitor
Python aceita ambos durante a transição, mas o dashboard novo espera `valvula`.

Antes de substituir dados em produção, faça uma cópia de segurança e deixe os
campos `status` com valor `0`, evitando interpretar como ativa uma execução
interrompida há muito tempo.

## Telas

| Agendamentos | Novo agendamento |
|---|---|
| ![Agendamentos](screenshot%20application/agendamentos.png) | ![Cadastro](screenshot%20application/cadastro%20agendamentos.png) |

| Válvulas | Tempo padrão | Logs |
|---|---|---|
| ![Válvulas](screenshot%20application/valvulas.png) | ![Tempo padrão](screenshot%20application/tempo%20padrao.png) | ![Logs](screenshot%20application/logs.png) |

## Estrutura limpa

Os diretórios `Parte - 1` a `Parte - 7`, caches locais e artefatos gerados foram
removidos porque não fazem parte da aplicação refatorada. A árvore ativa é
composta por `src/`, `data/`, `node-red/`, `deploy/`, `scripts/`, `tests/` e os
arquivos de configuração da raiz.
