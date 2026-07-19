# Sistema de Irrigação Inteligente com Raspberry Pi 3

## Objetivo

Criar um sistema de irrigação para pequenas e médias plantações (feijão, milho, macaxeira, hortas, frutíferas, etc.) utilizando um Raspberry Pi 3 como controlador central.

O sistema permitirá:

- Irrigação automática por horário
- Irrigação baseada em sensores
- Controle remoto via navegador
- Histórico de irrigações
- Monitoramento de consumo de água
- Monitoramento de sensores
- Expansão futura

---

# Arquitetura

```text
                   Internet (Opcional)
                          │
                  Interface Web
                          │
──────────────────────────────────────────
            Raspberry Pi 3
──────────────────────────────────────────
        │
        ├── Sensores
        ├── Módulos MOSFET
        ├── Válvulas
        ├── Sensor de Vazão
        ├── Sensor de Chuva
        └── Sensor de Nível
```

---

# Lista de Compras

## Controlador

| Item | Quantidade |
|-------|-----------:|
| Raspberry Pi 3 | 1 |
| Fonte Raspberry 5V 3A | 1 |
| Cartão MicroSD 32GB Classe 10 | 1 |

---

## Caixa

| Item | Quantidade |
|-------|-----------:|
| Caixa IP65 | 1 |
| Trilho DIN | 1 |

---

## Alimentação

| Item | Quantidade |
|-------|-----------:|
| Fonte 12V 10A | 1 |
| Conversor Step Down 12V → 5V 5A | 1 |
| Chave liga/desliga | 1 |
| Fusível geral 10A | 1 |
| Porta-fusível | 1 |

---

## Acionamento

| Item | Quantidade |
|-------|-----------:|
| Módulo MOSFET 30A (1 canal) | 8 |

ou

| Item | Quantidade |
|-------|-----------:|
| Placa MOSFET 8 canais | 1 |

---

## Proteção

| Item | Quantidade |
|-------|-----------:|
| Fusível 2A | 8 |
| Porta-fusível | 8 |

---

## Válvulas

| Item | Quantidade |
|-------|-----------:|
| Válvula Solenoide 12V DC 1" | Conforme os setores (6~8) |

Exemplo:

- Setor 1 → Feijão
- Setor 2 → Milho
- Setor 3 → Macaxeira
- Setor 4 → Horta
- Setor 5 → Frutíferas
- Setor 6 → Reserva

---

## Sensores

### Umidade

| Item | Quantidade |
|-------|-----------:|
| Sensor Capacitivo de Umidade | 1 por setor |

---

### Conversor Analógico

Como o Raspberry Pi não possui entradas analógicas:

| Item | Quantidade |
|-------|-----------:|
| ADS1115 (4 canais) | 2 |

---

### Chuva

| Item | Quantidade |
|-------|-----------:|
| Sensor de chuva | 1 |

---

### Vazão

| Item | Quantidade |
|-------|-----------:|
| Sensor de Vazão YF-S201 | 1 |

---

### Caixa d'água

| Item | Quantidade |
|-------|-----------:|
| Sensor de nível tipo boia | 1 |

---

### Temperatura

| Item | Quantidade |
|-------|-----------:|
| BME280 | 1 |

---

## Organização

| Item | Quantidade |
|-------|-----------:|
| Bornes | 20 |
| Conectores WAGO | 20 |
| Prensa-cabos IP68 | 10 |
| Canaletas | Conforme necessidade |

---

## Cabos

- Cabo PP 2x1,5 mm²
- Cabo para sensores
- Terminais tubulares
- Abraçadeiras

---

# Exemplo de Montagem

> **Convenção obrigatória de pinos:** o software e o painel aceitam somente o
> número do **pino físico (BOARD)** do conector de 40 pinos. Nomes como `GPIO23`
> são identificadores BCM e são ambíguos sem conversão. Nos exemplos abaixo a
> equivalência aparece apenas para ajudar a ler diagramas antigos; cadastre o
> número físico e confira o pinout do modelo exato do Raspberry Pi. Os pinos são
> exemplos, não uma recomendação de instalação, e podem conflitar com bomba ou
> válvulas já cadastradas.

## Alimentação

```text
Tomada 127/220V

        │

        ▼

Fonte 12V

        │

        ├─────────────► Conversor 12V → 5V

        │                      │

        │                      ▼

        │                 Raspberry Pi

        │

        └─────────────► MOSFETs
```

---

## Raspberry Pi

```text
Pino físico 11 (BCM17) ─────► MOSFET 1

Pino físico 12 (BCM18) ─────► MOSFET 2

Pino físico 35 (BCM19) ─────► MOSFET 3

Pino físico 38 (BCM20) ─────► MOSFET 4

Pino físico 40 (BCM21) ─────► MOSFET 5

Pino físico 15 (BCM22) ─────► MOSFET 6
```

---

## MOSFET

Cada MOSFET controla uma válvula.

```text
GPIO

↓

MOSFET

↓

Válvula
```

---

## Válvula

```text
+12V

↓

Válvula

↓

MOSFET

↓

GND
```

---

## Sensor de Umidade

Como o Raspberry não possui entrada analógica:

```text
Sensor

↓

ADS1115

↓

I²C

↓

Raspberry Pi
```

---

## Sensor de Chuva

```text
Sensor

↓

Pino físico 16 (BCM23)
```

---

## Sensor de Vazão

```text
Sensor

↓

Pino físico 18 (BCM24)
```

---

## Sensor de Nível

```text
Boia

↓

Pino físico 22 (BCM25)
```

---

## Esquema Geral

```text
Tomada

   │

   ▼

Fonte 12V

   │

   ├──────────────┐

   │              │

   ▼              ▼

Conversor      MOSFET

12→5V             │

   │              │

   ▼              ▼

Raspberry      Válvulas

   │

   ├──────── ADS1115

   │           │

   │           ├── Sensor Umidade 1

   │           ├── Sensor Umidade 2

   │           ├── Sensor Umidade 3

   │           ├── Sensor Umidade 4

   │           ├── Sensor Umidade 5

   │           └── Sensor Umidade 6

   │

   ├── Sensor Chuva

   ├── Sensor Vazão

   └── Sensor Nível
```

---

# Organização da Caixa

```text
┌────────────────────────────────────────────┐

 Fonte 12V

──────────────────────────────────────────────

 Conversor 12V → 5V

──────────────────────────────────────────────

 Raspberry Pi

──────────────────────────────────────────────

 ADS1115

──────────────────────────────────────────────

 MOSFET 1

 MOSFET 2

 MOSFET 3

 MOSFET 4

 MOSFET 5

 MOSFET 6

──────────────────────────────────────────────

 Bornes

──────────────────────────────────────────────

 Entrada dos Cabos

└────────────────────────────────────────────┘
```

---

# Funcionamento

Atualmente, `Configurações > Sensores` cadastra apenas a identidade e mostra o
último estado comum dos tipos nível do reservatório, vazão, umidade do solo,
pressão da linha e chuva. Esse cadastro não instala o componente, não valida a
fiação e ainda não altera decisões de irrigação. Leitura real, calibração e
regras de segurança passam a existir somente depois da implementação do driver
específico correspondente.

1. Raspberry Pi verifica sensores.
2. Se um setor precisar irrigar:
   - Liga a válvula correspondente.
   - Monitora a vazão.
   - Aguarda o tempo configurado.
   - Fecha a válvula.
3. Registra a irrigação.
4. Atualiza o painel web.

---

# Melhorias Futuras

- Painel Solar
- ESP32 para tempo real
- Módulo LoRa
- Câmera IP
- Atualizações OTA
- Previsão do tempo
- Fertirrigação
- Controle de bombas
- Aplicativo PWA
- Notificações por WhatsApp
- Dashboard em nuvem
