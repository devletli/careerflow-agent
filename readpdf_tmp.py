from PyPDF2 import PdfReader
for name in ["real_cv.pdf", "real_cl.pdf"]:
    r = PdfReader(f"C:\\Users\\Admin\\AppData\\Local\\Temp\\opencode\\{name}")
    print("=" * 30, name, f"{len(r.pages)} page(s)")
    print(r.pages[0].extract_text())
