from datapass_runtime.main import app
from datapass_runtime.pipeline_compiler import compile_response


assert app.title == "Datapass Runtime"

source = """pipeline("ci")
a = sql("a", "SELECT 1")
b = quality("b", "SELECT 1 WHERE FALSE")
a >> b
"""
compiled = compile_response(source)
assert compiled["valid"], compiled
assert compiled["ir"] is not None
assert len(compiled["ir"]["tasks"]) == 2
assert len(compiled["ir"]["edges"]) == 1
assert compiled["ir"]["edges"][0] == {"source": "a", "target": "b"}

print("Datapass runtime smoke passed.")
