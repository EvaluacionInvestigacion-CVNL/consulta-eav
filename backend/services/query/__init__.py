"""Motor de consultas: valida la petición, compone el SQL y arma la tabla.

Es el único subsistema que arma SQL en tiempo de ejecución, así que no pasa por
`repositories/` para sus consultas compuestas (las fijas y parametrizadas sí
viven ahí). Los identificadores que llegan del usuario —`question_id`,
`group_by`, `attribute`— se validan contra allowlists derivadas de la propia
base ANTES de interpolarse: ése es el patrón de builder SQL seguro.

    models.py            QueryRequest, el contrato de entrada
    runner.py            run_query: validación + las cuatro formas de salida
    year_comparison.py   la quinta forma: group_by="year"
    sql_builder.py       fragmentos de SQL compuestos (scope, group, filtros)
    numeric_bins.py      rangos para cruzar por una pregunta numérica
    sentinels.py         qué códigos son "No sabe/No contesta" y no datos
    pivot.py             armado de las tablas de conteos y porcentajes

Nada se re-exporta aquí: cada consumidor importa del módulo dueño del símbolo.
"""
