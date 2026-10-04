"""task1 D3: engine.py'de kullanilan DB model adlari importlu olmali.

Canli browser-agent `name 'Job' is not defined` ile dusuyordu; bu yol
unit testlerin DB'li kisimlarinda kapsanmiyor. AST ile tekrarini engelle.
"""
import ast
from pathlib import Path

ENGINE = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "browser-agent"
    / "app"
    / "engine.py"
)


def test_engine_model_names_imported():
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "shared.db.models":
            imported.update(a.asname or a.name for a in node.names)
    used: set[str] = set()
    models = {
        "Job",
        "Application",
        "ApplicationAnswer",
        "ApplicationQuestion",
        "AutomationRun",
        "JobMatch",
        "Document",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in models:
            used.add(node.id)
    missing = used - imported
    assert not missing, f"import edilmeyen model adlari: {missing}"
