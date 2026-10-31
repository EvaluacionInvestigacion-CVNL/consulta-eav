"""HTTP-level smoke tests for the FastAPI endpoints (via TestClient)."""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_questions(client):
    r = client.get("/api/questions")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    sample = data[0]
    assert {"q_id", "q_text", "q_type", "options"} <= sample.keys()


def test_attributes(client):
    r = client.get("/api/attributes")
    assert r.status_code == 200
    names = {a["attribute"] for a in r.json()}
    assert "sexo" in names


def test_cities(client):
    r = client.get("/api/cities")
    assert r.status_code == 200
    data = r.json()
    assert all("city_id" in c and "name" in c for c in data)
    assert any(c["name"] == "Monterrey" for c in data)


def test_dimensions_year_mode_respects_coverage(client):
    r = client.get("/api/dimensions?question_id=p114&wave=2025&mode=year")
    assert r.status_code == 200
    body = r.json()
    assert {"2021", "2022", "2023", "2024", "2025"} <= set(body["member_waves"])
    attributes = {a["attribute"]: a for a in body["attributes"]}
    assert attributes["sexo"]["available"]
    assert not attributes["modo_transporte"]["available"]
    assert "2021" in attributes["modo_transporte"]["missing_waves"]
    # sólo preguntas presentes en todas las olas, nunca la consultada
    assert body["questions"]
    assert all(q["q_id"] != "p114" for q in body["questions"])


def test_dimensions_wave_mode_lists_all_categorical(client):
    body = client.get("/api/dimensions?question_id=p114&wave=2025").json()
    assert body["mode"] == "wave"
    assert all(a["available"] for a in body["attributes"])
    year_body = client.get(
        "/api/dimensions?question_id=p114&wave=2025&mode=year"
    ).json()
    assert len(body["questions"]) > len(year_body["questions"])


def test_dimensions_include_numeric_questions_with_type(client):
    """Las numéricas también son filtros (por rango): la UI necesita `q_type`."""
    for mode in ("wave", "year"):
        body = client.get(
            f"/api/dimensions?question_id=p114&wave=2025&mode={mode}"
        ).json()
        types = {q["q_id"]: q["q_type"] for q in body["questions"]}
        assert types.get("cp4_1") == "numerica"


def test_attributes_flag_numeric_ones(client):
    """La UI filtra la edad por rango y el resto por opciones."""
    body = client.get("/api/attributes?wave=2025").json()
    numeric = {a["attribute"]: a["numeric"] for a in body}
    assert numeric["edad_anos"] is True
    assert numeric["sexo"] is False


def test_dimensions_rejects_bad_mode(client):
    r = client.get("/api/dimensions?question_id=p114&mode=x")
    assert r.status_code == 400


def test_recodes(client):
    r = client.get("/api/recodes")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_presets(client):
    r = client.get("/api/presets")
    assert r.status_code == 200
    assert len(r.json()) > 0


def _sexo_value(presets, key):
    p = next(x for x in presets if x["key"] == key)
    return p["filters"][0]["value"]


def test_presets_translate_sexo_per_wave(client):
    """El preset de MUJERES/HOMBRES debe recodificar sexo a cada ola: 2025 usa
    0=Hombre/1=Mujer, pero 2022 usa 1=Hombre/2=Mujer. Sin traducir, 'mujeres'
    caía en hombres y 'hombres' no devolvía datos (regresión)."""
    p2025 = client.get("/api/presets?wave=2025").json()
    assert _sexo_value(p2025, "respuesta_hombres_por_unidad_geografica") == 0
    assert _sexo_value(p2025, "respuesta_mujeres_por_unidad_geografica") == 1

    p2022 = client.get("/api/presets?wave=2022").json()
    assert _sexo_value(p2022, "respuesta_hombres_por_unidad_geografica") == 1
    assert _sexo_value(p2022, "respuesta_mujeres_por_unidad_geografica") == 2


def test_query_endpoint(client, categorical_qid):
    r = client.post("/api/query", json={"question_id": categorical_qid})
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "flat"
    assert body["rows"]


def test_query_csv_endpoint(client, categorical_qid):
    r = client.post("/api/query/csv", json={"question_id": categorical_qid})
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
    assert len(r.text.splitlines()) > 1  # header + at least one data row


def test_query_unknown_question_returns_404(client):
    r = client.post("/api/query", json={"question_id": "__does_not_exist__"})
    assert r.status_code == 404
