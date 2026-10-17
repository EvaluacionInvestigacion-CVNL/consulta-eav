"""Consultas sobre los respondientes: atributos demográficos y ciudades."""


def fetch_attribute_values(conn, wave: str) -> list[tuple]:
    """(attribute, value, option_label) de los atributos demográficos de una ola.

    `respondent_attributes.value` es un `option_id`, así que la etiqueta sale de
    un LEFT JOIN contra `options` por (wave_id, question_id, option_id).
    """
    return conn.execute(
        """
        SELECT ra.attribute, ra.value, o.option_label
        FROM (
            SELECT DISTINCT question_id, attribute, value
            FROM respondent_attributes WHERE wave_id = ?
        ) ra
        LEFT JOIN options o ON o.wave_id = ? AND o.question_id = ra.question_id
            AND o.option_id = ra.value
        ORDER BY ra.attribute, ra.value
        """,
        [wave, wave],
    ).fetchall()


def fetch_attribute_question_id(conn, wave: str, attribute: str) -> str | None:
    """La pregunta que respalda un atributo amigable (`sexo` → `p3`)."""
    row = conn.execute(
        "SELECT DISTINCT question_id FROM respondent_attributes "
        "WHERE wave_id = ? AND attribute = ?",
        [wave, attribute],
    ).fetchone()
    return row[0] if row else None


def fetch_city_ids(conn, wave: str) -> list[int]:
    """`city_id`s distintos con respondientes en una ola."""
    rows = conn.execute(
        """
        SELECT DISTINCT city_id FROM responses
        WHERE city_id IS NOT NULL AND wave_id = ? ORDER BY city_id
        """,
        [wave],
    ).fetchall()
    return [r[0] for r in rows]


def fetch_attribute_questions(conn) -> list[tuple]:
    """(wave_id, attribute, question_id): qué pregunta respalda cada atributo
    amigable en cada ola (`sexo` → `cp2` en 2025, `genero` en 2016)."""
    return conn.execute(
        """
        SELECT DISTINCT wave_id, attribute, question_id
        FROM respondent_attributes
        ORDER BY wave_id, attribute
        """
    ).fetchall()
