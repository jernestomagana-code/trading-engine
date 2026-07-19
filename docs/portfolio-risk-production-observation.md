# Activación y observación de riesgo de cartera

## Estado de activación

Activado localmente el 18 de julio de 2026 en modo silencioso.

- Tres cuentas IBKR leídas correctamente y sin identificadores reales en los artefactos.
- Control Tower: `READY`, 3/3 cuentas listas, 0 fallidas y 0 vencidas en el ciclo de validación.
- Riesgo: `ACTION_REQUIRED`, score 87, siete alertas abiertas.
- Tres jobs registrados y ejecutados por `launchd`: monitor, preflight y digest.
- Los tres jobs terminaron su prueba de arranque con código 0.
- Notificaciones locales desactivadas.
- Notificaciones externas desactivadas.
- Sin ejecución de órdenes ni liquidación automática.

## Arquitectura activa

Los jobs se ejecutan desde un runner mínimo instalado en `~/Library/Application Support/Stock Ultimus/Launchd`. El runner entrega el trabajo a la consola local por `127.0.0.1:8765`, espera el resultado y registra `DONE` o el error correspondiente. Esto evita el bloqueo de privacidad de macOS sobre `Documents` y conserva un solo runtime operativo.

## Periodo de observación recomendado

Mantener las notificaciones apagadas durante cinco sesiones hábiles. Revisar cada día:

1. que Control Tower reporte todas las cuentas como `READY`;
2. que monitor, preflight y digest terminen con código 0;
3. que no se creen duplicados en el outbox;
4. que confirmar, silenciar y reabrir alertas respeten sus vencimientos;
5. que un cambio de severidad vuelva a abrir una alerta confirmada;
6. que los artefactos sigan excluyendo identificadores reales y secretos;
7. que ninguna ruta autorice órdenes o liquidaciones.

El digest de lunes a viernes registra estas comprobaciones de manera idempotente en `runtime/portfolio_risk_observation.json`. Una repetición del mismo día reemplaza la sesión en vez de aumentar el contador. Los fines de semana no se programan y tampoco cuentan si el digest se ejecuta manualmente. El archivo sólo cambia a `READY_TO_ENABLE_LOCAL_NOTIFICATIONS` cuando las últimas cinco sesiones registradas son limpias; la activación sigue requiriendo una decisión humana explícita.

## Criterio para activar avisos locales

Activarlos sólo después de cinco sesiones limpias, sin falsos positivos críticos, sin duplicados y con horarios correctos. La activación es explícita:

```bash
python3 scripts/install_portfolio_risk_launchd.py --install --enable-local-notifications
```

No activar canales externos hasta completar una fase separada de diseño, límites, deduplicación y prueba de entrega.
