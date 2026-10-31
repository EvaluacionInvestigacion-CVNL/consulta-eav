"""Consultas sobre el instrumento: olas, preguntas y opciones."""


def fetch_waves(conn) -> list[tuple]:
    """(wave_id, year, label, n_respondents) de todas las olas, más reciente primero."""
    return conn.execute(
        "SELECT wave_id, year, label, n_respondents FROM waves "
        "ORDER BY year DESC, wave_id DESC"
    ).fetchall()


def fetch_wave_ids(conn) -> list[str]:
    """Todos los `wave_id` presentes en la base (para validación)."""
    return [r[0] for r in conn.execute("SELECT wave_id FROM waves").fetchall()]


def fetch_latest_wave_id(conn) -> str | None:
    """`wave_id` de la ola más reciente, o None si la base no tiene olas."""
    row = conn.execute(
        "SELECT wave_id FROM waves ORDER BY year DESC, wave_id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def fetch_questions(conn, wave: str) -> list[tuple]:
    """(q_id, q_text, q_section, q_type, q_info, q_block, concept_id) de una ola."""
    return conn.execute(
        """
        SELECT q.q_id, q.q_text, q.q_section, q.q_type, q.q_info,
               q.q_block, q.concept_id
        FROM questions q
        WHERE q.wave_id = ?
        ORDER BY q.q_id
        """,
        [wave],
    ).fetchall()


def fetch_options(conn, wave: str, question_id: str) -> list[tuple]:
    """(option_id, option_label) de una pregunta categórica."""
    return conn.execute(
        """
        SELECT option_id, option_label FROM options
        WHERE wave_id = ? AND question_id = ? ORDER BY option_id
        """,
        [wave, question_id],
    ).fetchall()


def fetch_categorical_question_ids(conn, wave: str) -> list[str]:
    """`q_id`s de las preguntas no numéricas de una ola."""
    rows = conn.execute(
        "SELECT q_id FROM questions WHERE wave_id = ? AND q_type != 'numerica'",
        [wave],
    ).fetchall()
    return [r[0] for r in rows]


def fetch_concept_option_id(conn, wave: str, question_id: str, option_id):
    """Opción canónica (`concept_option_id`) de una opción concreta de una ola."""
    row = conn.execute(
        "SELECT concept_option_id FROM options "
        "WHERE wave_id = ? AND question_id = ? AND option_id = ?",
        [wave, question_id, option_id],
    ).fetchone()
    return row[0] if row else None


def fetch_option_id_by_concept(conn, wave: str, question_id: str, concept_option_id):
    """Inverso de `fetch_concept_option_id`: baja una opción canónica a una ola."""
    row = conn.execute(
        "SELECT option_id FROM options "
        "WHERE wave_id = ? AND question_id = ? AND concept_option_id = ?",
        [wave, question_id, concept_option_id],
    ).fetchone()
    return row[0] if row else None


def fetch_question_type_and_text(conn, wave: str, question_id: str) -> tuple | None:
    """(q_type, q_text) de una pregunta, o None si no existe en esa ola."""
    return conn.execute(
        "SELECT q_type, q_text FROM questions WHERE wave_id = ? AND q_id = ?",
        [wave, question_id],
    ).fetchone()


def fetch_question_concept_and_text(conn, wave: str, question_id: str) -> tuple | None:
    """(concept_id, q_text) de una pregunta, o None si no existe en esa ola."""
    return conn.execute(
        "SELECT concept_id, q_text FROM questions WHERE wave_id = ? AND q_id = ?",
        [wave, question_id],
    ).fetchone()


def fetch_option_labels_in_code_order(conn, wave: str, question_id: str) -> list[str]:
    """Etiquetas de una pregunta ordenadas por `option_id` (no alfabéticamente)."""
    rows = conn.execute(
        "SELECT option_label FROM options "
        "WHERE wave_id = ? AND question_id = ? ORDER BY option_id",
        [wave, question_id],
    ).fetchall()
    return [r[0] for r in rows]


def fetch_concept_option_map(conn, concept_id: str) -> list[tuple]:
    """(wave_id, option_id, concept_option_id) de TODAS las preguntas del concepto.

    De un golpe en vez de una consulta por ola: la vista Año necesita el mapa
    completo para alinear las opciones entre años.
    """
    return conn.execute(
        """
        SELECT o.wave_id, o.option_id, o.concept_option_id
        FROM options o
        JOIN questions q ON q.wave_id = o.wave_id AND q.q_id = o.question_id
        WHERE q.concept_id = ?
        """,
        [concept_id],
    ).fetchall()


def fetch_wave_sample_sizes(conn) -> list[tuple]:
    """(wave_id, label, entrevistas, personas, poblacion) de cada ola.

    `entrevistas` son los respondientes iniciales (quienes contestaron el
    cuestionario completo); `personas` incluye a los demás integrantes del
    hogar; `poblacion` es la suma de sus factores de expansión.
    """
    return conn.execute(
        """
            SELECT w.wave_id,
                   w.label,
                   COUNT(*) FILTER (WHERE r.is_initial_respondent)        AS entrevistas,
                   COUNT(*)                                               AS personas,
                   ROUND(SUM(r.factor_cvnl)
                         FILTER (WHERE r.is_initial_respondent))          AS poblacion
            FROM waves w
            JOIN responses r ON r.wave_id = w.wave_id
            GROUP BY 1, 2
            ORDER BY 1 DESC
            """
    ).fetchall()


def fetch_question_id_for_concept(conn, wave: str, concept_id: str) -> str | None:
    """El `q_id` que representa a un concepto en una ola concreta."""
    row = conn.execute(
        "SELECT q_id FROM questions WHERE wave_id = ? AND concept_id = ?",
        [wave, concept_id],
    ).fetchone()
    return row[0] if row else None


def fetch_question_concept_id(conn, wave: str, question_id: str) -> str | None:
    """El `concept_id` de una pregunta, o None si no está armonizada."""
    row = conn.execute(
        "SELECT concept_id FROM questions WHERE wave_id = ? AND q_id = ?",
        [wave, question_id],
    ).fetchone()
    return row[0] if row else None


def fetch_all_questions_with_concept(conn) -> list[tuple]:
    """(wave_id, q_id, q_type, concept_id, q_text) de TODAS las olas.

    El catálogo de filtros entre olas lo necesita completo (~2,600 filas):
    resolver la pregunta equivalente de cada ola con un lookup por filtro
    haría una consulta de una fila por (ola, filtro).
    """
    return conn.execute(
        "SELECT wave_id, q_id, q_type, concept_id, q_text FROM questions "
        "ORDER BY wave_id, q_id"
    ).fetchall()


def fetch_all_option_concepts(conn) -> list[tuple]:
    """(wave_id, question_id, option_id, concept_option_id) de las opciones
    armonizadas de TODAS las olas (~12,000 filas, se cachean una vez)."""
    return conn.execute(
        """
        SELECT wave_id, question_id, option_id, concept_option_id FROM options
        WHERE concept_option_id IS NOT NULL
        ORDER BY wave_id, question_id, option_id
        """
    ).fetchall()
