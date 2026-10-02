import importlib.util
import sys
from pathlib import Path

ROOT = Path("D:/ProjAI/ai-job-agent")
sys.path.insert(0, str(ROOT / "services" / "cv-generator"))
spec = importlib.util.spec_from_file_location(
    "careerflow_docgen", ROOT / "services" / "cv-generator" / "app" / "generator.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["careerflow_docgen"] = mod
try:
    spec.loader.exec_module(mod)
    print("generator import OK")
except ImportError as e:
    print("MISSING DEP:", e)
    sys.exit(2)

from shared.profile.loader import load_canonical_profile
profile = load_canonical_profile()
print("name:", profile.name, "| email:", repr(profile.email), "| phone fact:", repr(profile.facts.get("phone")))
gen = mod.DocumentGenerator.__new__(mod.DocumentGenerator)  # skip MinIO init
tailoring = {"skills": ["Python", "Software Development", "DevOps"], "keywords": ["AI", "Automation"], "target_role": "Applied AI Engineer"}

cv = gen._build_pdf_cv(profile, "Openai", "Applied AI Engineer, Codex", "en", tailoring)
cl = gen._build_pdf_cover_letter(profile, "Openai", "Applied AI Engineer, Codex", "en", tailoring)
docx_bytes = gen._build_docx_cv(profile, "Openai", "Applied AI Engineer, Codex", "en", tailoring)
print("pdf cv bytes:", len(cv), "| cover pdf bytes:", len(cl), "| docx bytes:", len(docx_bytes))
Path("C:/Users/Admin/AppData/Local/Temp/opencode/new_cv.pdf").write_bytes(cv)
Path("C:/Users/Admin/AppData/Local/Temp/opencode/new_cl.pdf").write_bytes(cl)

from PyPDF2 import PdfReader
import io
for label, data in [("CV", cv), ("CL", cl)]:
    print("=" * 25, label)
    print(PdfReader(io.BytesIO(data)).pages[0].extract_text())
