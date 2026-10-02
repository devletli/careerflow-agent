import importlib.util
for mod in ["reportlab", "docx", "PyPDF2"]:
    print(mod, "OK" if importlib.util.find_spec(mod) else "MISSING")
