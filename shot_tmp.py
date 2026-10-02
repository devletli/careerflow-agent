import time
from playwright.sync_api import sync_playwright

OUT = r"C:\Users\Admin\AppData\Local\Temp\opencode\audit"
TABS = ["Overview", "Jobs", "Documents", "Applications", "Events", "Settings"]

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    for w, h in [(1440, 900), (1280, 800), (1024, 768)]:
        pg = b.new_page(viewport={"width": w, "height": h})
        errors = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto("http://localhost:3000", wait_until="networkidle")
        pg.wait_for_timeout(12000)
        for tab in TABS:
            pg.get_by_role("button", name=tab, exact=True).click()
            pg.wait_for_timeout(2500)
            pg.screenshot(path=f"{OUT}\\{w}x{h}-{tab}.png")
        print(w, h, "console errors:", errors if errors else "none")
        pg.close()
    # mobile: overview + jobs only
    pg = b.new_page(viewport={"width": 390, "height": 844})
    pg.goto("http://localhost:3000", wait_until="networkidle")
    pg.wait_for_timeout(12000)
    for tab in ["Overview", "Jobs", "Applications"]:
        pg.get_by_role("button", name=tab, exact=True).click()
        pg.wait_for_timeout(2500)
        pg.screenshot(path=f"{OUT}\\390x844-{tab}.png")
    pg.close()
    b.close()
print("done")
