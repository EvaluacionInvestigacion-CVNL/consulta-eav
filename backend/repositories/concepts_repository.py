"""Consultas sobre la capa de conceptos."""


def fetch_concept(conn, concept_id: str) -> tuple | None:
    """(label, q_type) de un concepto, o None si no existe."""
    return conn.execute(
        "SELECT label, q_type FROM concepts WHERE concept_id = ?",
        [concept_id],
    ).fetchone()


def fetch_concept_members(conn, concept_id: str) -> list[tuple]:
    """(wave_id, q_id, q_text) de cada pregunta que pertenece al concepto.

    La redacción viaja aquí y no en una consulta por ola: la vista Año necesita
    las dos cosas y el predicado es el mismo.
    """
    return conn.execute(
        "SELECT wave_id, q_id, q_text FROM questions "
        "WHERE concept_id = ? ORDER BY wave_id",
        [concept_id],
    ).fetchall()


def fetch_concept_options(conn, concept_id: str) -> list[tuple]:
    """(concept_option_id, label, sort_order) del catálogo canónico de opciones."""
    return conn.execute(
        "SELECT concept_option_id, label, sort_order FROM concept_options "
        "WHERE concept_id = ? ORDER BY sort_order",
        [concept_id],
    ).fetchall()


def fetch_exclusions(conn) -> list[tuple]:
    """(wave_a, q_a, wave_b, q_b, reason): pares declarados NO comparables."""
    return conn.execute(
        "SELECT wave_a, q_a, wave_b, q_b, reason FROM concept_exclusions"
    ).fetchall()
