-- =====================================================================
-- Encuesta NL — Esquema multi-año (optimizado para lectura, write-once)
-- =====================================================================

-- Catálogo de conceptos.
-- Un concepto agrupa preguntas equivalentes de distintas olas. TODA fila aquí es
-- comparable entre años por construcción: los pares `decision=exclude` se
-- descartan en build_db.py antes de formar las componentes conexas, así que un
-- concepto no comparable nunca llega a insertarse.
CREATE TABLE concepts (
    concept_id VARCHAR NOT NULL,
    label      VARCHAR,
    q_type     VARCHAR,          -- 'numerica' | 'categorica'
    PRIMARY KEY (concept_id)
);

-- Pares de preguntas que el equipo revisó y declaró NO comparables
-- (`decision=exclude` en concept_equivalences.csv). `reason` es un motivo de un
-- vocabulario cerrado que la UI traduce a texto; la nota técnica no se carga.
CREATE TABLE concept_exclusions (
    wave_a VARCHAR NOT NULL,
    q_a    VARCHAR NOT NULL,
    wave_b VARCHAR NOT NULL,
    q_b    VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    PRIMARY KEY (wave_a, q_a, wave_b, q_b)
);

-- Armonización de opciones entre años.
-- Un `concept_option_id` agrupa opciones equivalentes de distintas olas.
CREATE TABLE concept_options (
    concept_id        VARCHAR NOT NULL,
    concept_option_id VARCHAR NOT NULL,
    label             VARCHAR,
    sort_order        INTEGER,
    PRIMARY KEY (concept_id, concept_option_id)
);

-- Catálogo de olas.
CREATE TABLE waves (
    wave_id       VARCHAR NOT NULL,
    year          INTEGER NOT NULL,
    label         VARCHAR,            -- nombre para mostrar
    n_respondents INTEGER,            -- conteo de respondientes
    notes         VARCHAR,            -- notas metodológicas
    PRIMARY KEY (wave_id)
);

-- Un respondiente por fila.
CREATE TABLE responses (
    wave_id               VARCHAR NOT NULL,
    respondent_id         VARCHAR NOT NULL,   -- id original del año
    is_initial_respondent BOOLEAN,
    nombre                VARCHAR,
    factor_cvnl           DOUBLE,             -- factor de expansión de respondiente
    city_id               BIGINT,             -- municipio de respondiente
    PRIMARY KEY (wave_id, respondent_id)
);

-- El cuestionario de cada ola.
CREATE TABLE questions (
    wave_id    VARCHAR NOT NULL,
    q_id       VARCHAR NOT NULL,   -- id posicional del año
    q_text     VARCHAR,            -- texto tal como se preguntó ese año
    q_section  VARCHAR,
    q_type     VARCHAR,            -- 'numerica' | 'categorica'
    -- Las tres columnas siguientes sólo vienen pobladas en la ola 2025 (la BD
    -- original); los CSV del ETL 2021-2024 no las traen (se insertan NULL).
    q_notes    VARCHAR,            -- nota libre; superconjunto de q_info/q_block
    q_info     VARCHAR,            -- nota de ESTA pregunta: a quién aplica
                                   -- ('CP8 si responde 0 en la CP7') o la fórmula
                                   -- de derivación ('p24 + p25')
    q_block    VARCHAR,            -- texto compartido por un rango consecutivo de
                                   -- preguntas: el encabezado común ('Considera que
                                   -- los habitantes...' en p89_1..p89_9) o la nota
                                   -- de aplicabilidad del bloque; se repite idéntico
                                   -- en cada pregunta del rango
    concept_id VARCHAR,
    PRIMARY KEY (wave_id, q_id)
);

-- Opciones de respuesta de cada pregunta.
CREATE TABLE options (
    wave_id           VARCHAR NOT NULL,
    question_id       VARCHAR NOT NULL,
    option_id         BIGINT  NOT NULL,
    option_label      VARCHAR,
    concept_option_id VARCHAR,
    PRIMARY KEY (wave_id, question_id, option_id)
);

-- Atributos de cruce/filtro por respondiente. `attribute` es el label; 
-- `question_id` es el q_id de origen de ese año.
CREATE TABLE respondent_attributes (
    wave_id       VARCHAR NOT NULL,
    respondent_id VARCHAR NOT NULL,
    question_id   VARCHAR,
    attribute     VARCHAR NOT NULL,
    value         BIGINT,
    PRIMARY KEY (wave_id, respondent_id, attribute)
);

-- Tabla de hechos. 
-- Categóricas: option_id lleno, value NULL.
-- Numéricas: option_id NULL, value lleno.
-- La unicidad de (wave_id, respondent_id, question_id) se valida en build_db.py.
CREATE TABLE answers (
    wave_id       VARCHAR NOT NULL,
    respondent_id VARCHAR NOT NULL,
    question_id   VARCHAR NOT NULL,
    option_id     BIGINT,
    value         DOUBLE
);
