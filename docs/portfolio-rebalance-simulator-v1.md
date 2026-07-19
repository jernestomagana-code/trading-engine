# Simulador de rebalanceo y asignación v1

## Propósito

La Etapa 6C compara la cartera actual con copias virtuales modificadas. Permite
medir el efecto potencial de reducir concentración, mejorar el colchón de
liquidez o reducir la sensibilidad de opciones antes de una decisión humana.

El simulador nunca crea órdenes. Todas las acciones contienen `virtual_only`,
`order_created: false` y las salidas globales mantienen ejecución y rebalanceo
automático desautorizados.

## Alternativas automáticas

- Reducción gradual de la mayor concentración, limitada por rotación/NAV.
- Mejora de liquidez para cuentas bajo el colchón mínimo configurado.
- Reducción virtual de contratos completos para acercar dollar delta de opciones
  al límite definido.
- Combinación de concentración y sensibilidad cuando ambas aplican.

La consola permite además elegir un ticker y un porcentaje para una simulación
personalizada. El cambio se aplica a una copia en memoria y se persiste solamente
el resultado diagnóstico.

## Comparación

Cada alternativa vuelve a ejecutar los motores de estrés y factores para mostrar:

- peor pérdida bajo estrés;
- volatilidad y pérdida histórica de cola;
- concentración principal y factor dominante;
- colchón mínimo de exceso de liquidez;
- dollar delta de opciones;
- rotación virtual requerida.

El `model_score` sirve únicamente para ordenar compromisos matemáticos. La etiqueta
`MEJOR_EQUILIBRIO_MODELADO` no constituye una recomendación ni instrucción.

## Limitaciones

La simulación marcada a mercado no incorpora impuestos, deslizamiento, comisiones,
impacto de mercado ni todas las reglas de margen de IBKR. Las mejoras de margen y
liquidez usan los coeficientes conservadores configurados en
`config/portfolio_rebalance_policy.json`.

La salida se guarda en `runtime/portfolio_rebalance_latest.json` y la API local se
expone en `/portfolio-rebalance`.
