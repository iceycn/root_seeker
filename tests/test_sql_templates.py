from root_seeker.sql_templates import SqlTemplate, SqlTemplateRegistry


def test_registry_and_render():
    reg = SqlTemplateRegistry([SqlTemplate(query_key="k1", query="a={a} b={b}")])
    t = reg.get("k1")
    assert t.render({"a": 1, "b": "x"}) == "a=1 b=x"
