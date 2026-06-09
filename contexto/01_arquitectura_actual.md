# Arquitectura actual

Stock Ultimus es un trading engine hibrido local/cloud.

## Local

`ibkr_bridge.py` se conecta a Interactive Brokers mediante `ib_insync`. Lee precios, posiciones y cadenas de opciones, evalua estrategias Naked Put y Covered Call, y publica snapshots hacia Render.

## Cloud

`app/main.py` corre en Render con FastAPI. Recibe snapshots por endpoints POST, los guarda temporalmente en `runtime/*.json`, y expone endpoints GET para estado, dashboards HTML y decisiones por ticker consumibles por GPT.

## TradingView

TradingView se integra mediante alertas webhook que pueden enviar snapshots tecnicos a Render. Esas senales se guardan como JSON y pueden combinarse con datos de IBKR por el motor de decision.

## Estado V29.1

V29.1 corrige la prioridad de bloqueadores:

- si el tecnico esta confirmado pero faltan datos ejecutables del contrato, la decision debe ser `WAIT_OPTIONS_DATA`;
- no debe degradarse incorrectamente a `WAIT_TECHNICAL`.

## Regla operativa

El sistema funciona como asistente de decision y validacion manual. No debe ejecutar operaciones automaticamente.
