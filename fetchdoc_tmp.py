import httpx

docs = httpx.get("http://localhost:8000/api/v1/documents?limit=100", timeout=30).json()
print("total docs:", len(docs))
by_type = {}
for d in docs:
    by_type.setdefault(d["type"], []).append(d)
for t, items in by_type.items():
    print(t, len(items))

cv = next(d for d in docs if d["type"] == "cv" and d["mime_type"] == "application/pdf")
cl = next(d for d in docs if d["type"] == "cover_letter")
print("CV:", cv["id"], cv["metadata"].get("company"), cv["metadata"].get("title"), cv["download_url"])
print("CL:", cl["id"], cl["metadata"].get("company"), cl["metadata"].get("title"), cl["download_url"])

for doc, name in [(cv, "real_cv.pdf"), (cl, "real_cl.pdf")]:
    r = httpx.get(f"http://localhost:8000{doc['download_url']}", timeout=60)
    print(name, r.status_code, r.headers.get("content-type"), len(r.content), "bytes")
    open(f"C:\\Users\\Admin\\AppData\\Local\\Temp\\opencode\\{name}", "wb").write(r.content)
