"""El ciclo de tool use: pregunta → llamadas a `query` → respuesta en español.

El modelo alterna entre pedir datos y redactar. Se le deja hacerlo hasta
`MAX_TOOL_ROUNDS` veces para que pueda encadenar consultas (p. ej. pedir el
total y luego el desglose) sin quedarse en un ciclo infinito si nunca concluye.
En la última ronda el modelo tiene que redactar con lo que ya consultó.
"""

import logging
import re

from services.chat import gemini, prompts, query_tool

logger = logging.getLogger("encuesta.chat")

MAX_TOOL_ROUNDS = 5

NO_ANSWER_REPLY = "No pude completar la consulta. Intenta reformular la pregunta."

MAX_TITLE_CHARS = 60

_TITLE_LINE = re.compile(
    r"\A\s*(?:#+\s*)?\**\s*t[ií]tulo\s*\**\s*:\s*(?P<title>[^\n]*)\n?",
    re.IGNORECASE,
)


def split_title(text: str) -> tuple[str | None, str]:
    match = _TITLE_LINE.match(text or "")
    if not match:
        return None, text or ""
    title = match.group("title").strip().rstrip(".").strip(" *_\"'«»“”").rstrip(".")
    body = text[match.end():].lstrip("\n")
    if len(title) > MAX_TITLE_CHARS:
        title = title[: MAX_TITLE_CHARS - 1].rstrip() + "…"
    return title or None, body


def run_chat(message: str, history: list) -> dict:
    """Responde un mensaje del chat. Devuelve respuesta, consultas, datos y,
    en el primer turno de una conversación, un título para la lista."""
    new_conversation = not history
    instruction = prompts.system_instruction()
    if new_conversation:
        instruction += prompts.NEW_CONVERSATION_RULE
    client = gemini.get_client()
    tools = [query_tool.query_tool_declaration()]
    config = gemini.build_config(system_instruction=instruction, tools=tools)
    final_config = gemini.build_config(
        system_instruction=instruction, tools=tools, allow_tools=False
    )

    contents = gemini.history_to_contents(history)
    contents.append(gemini.user_message(message))

    executed_queries: list = []
    results: list = []  # [{query, result}]
    reply_text = ""

    for round_index in range(MAX_TOOL_ROUNDS):
        last_round = round_index == MAX_TOOL_ROUNDS - 1
        response = gemini.generate(
            client, contents, final_config if last_round else config
        )
        content, function_calls = gemini.function_calls_in(response)

        if not function_calls or last_round:
            try:
                reply_text = response.text or ""
            except Exception:
                reply_text = ""
            break

        # Se registra el turno de herramientas del modelo y luego se contesta
        # cada llamada.
        if content is not None:
            contents.append(content)
        response_parts = []
        for function_call in function_calls:
            if function_call is None:
                continue
            args = dict(function_call.args) if function_call.args else {}
            result, summary, effective_query = query_tool.execute(args)
            # Registramos la consulta EFECTIVA (q_id ya traducido a la ola + año),
            # no los args crudos del modelo, para que la tarjeta del chat sea fiel.
            executed_queries.append(effective_query)
            if result is not None and all(
                r["query"] != effective_query for r in results
            ):
                results.append({"query": effective_query, "result": result})

            tool_name = function_call.name or ""
            response_parts.append(
                gemini.tool_response_part(tool_name, summary)
            )
        contents.append(gemini.tool_response_message(response_parts))

    title, reply_text = split_title(reply_text)
    if not new_conversation:
        title = None
    if not reply_text.strip():
        reply_text = NO_ANSWER_REPLY
    logger.info("chat message=%r tool_calls=%s", message, executed_queries)
    return {
        "reply": reply_text,
        "title": title,
        "tool_calls": executed_queries,
        "data": results,
    }
