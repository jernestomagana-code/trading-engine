# Motor de estrés multicuenta v1

## Objetivo

La Etapa 6A añade escenarios deterministas y explicables sobre todas las cuentas
sanitizadas de Control Tower. Su función es responder cuánto podría afectar un
choque a la cartera consolidada, qué cuenta absorbería el mayor impacto y dónde
está la concentración principal.

El motor es exclusivamente diagnóstico. No crea, transmite, modifica ni cancela
órdenes y tampoco autoriza liquidaciones automáticas.

## Escenarios iniciales

- Corrección de mercado: caída lineal de 10% con movimiento moderado en opciones.
- Drawdown severo: caída lineal de 20% con dislocación fuerte en opciones.
- Choque de volatilidad: movimiento adverso de 3% y expansión de primas.

Los shocks se configuran en `config/portfolio_stress_policy.json`. Acciones y
otros instrumentos lineales se calculan sobre su valor; opciones se separan por
lado largo/corto y call/put. Son pruebas de sensibilidad, no predicciones ni VaR.

## Calidad de valoración

El valor de mercado de IBKR es la base preferida. Si no está disponible se usa
cantidad por costo promedio como estimación, sin ocultarlo. La consola muestra
la cobertura exacta y marca el resultado `PARTIAL` cuando queda por debajo de
80%. Posiciones sin valor ni costo se excluyen y generan una advertencia.

## Salidas

`runtime/portfolio_stress_latest.json` contiene:

- impacto y pérdida/NAV consolidados por escenario;
- NAV y exceso de liquidez proyectados por cuenta;
- cuenta más expuesta;
- concentración bruta por ticker;
- cobertura de valor de mercado y advertencias metodológicas;
- guardas explícitas de no ejecución.

La consola expone la vista `/portfolio-stress` y permite recalcularla desde los
snapshots existentes sin consultar ni operar el broker. El refresco completo de
Control Tower también actualiza automáticamente este resultado.
