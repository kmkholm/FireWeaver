"""Capture the running GNS3 project from the GNS3 Web UI (served by the GNS3 VM) at high resolution with headless Chrome.
usage: python gns3_screenshot.py <project_id> <out.png> [inspect]"""
import sys, time
from playwright.sync_api import sync_playwright

UI = "http://192.168.56.101/static/web-ui"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def main(pid, out, inspect=False):
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = b.new_page(viewport={"width": 2400, "height": 1400}, device_scale_factor=2)
        pg.goto(UI + "/servers"); time.sleep(3)
        if inspect:
            pg.get_by_text("Add server").click(); time.sleep(2)
            print([ (e.get_attribute("formcontrolname"), e.get_attribute("placeholder"), e.evaluate("e=>e.tagName")) for e in pg.query_selector_all("input, mat-select, select")])
            pg.screenshot(path=out); b.close(); return
        pg.get_by_text("Add server").click(); time.sleep(1.5)
        pg.fill("input[formcontrolname=name]", "GNS3 VM")
        pg.click("mat-select[formcontrolname=location]"); time.sleep(0.5); pg.get_by_role("option", name="Remote").click(); time.sleep(0.5)
        pg.fill("input[formcontrolname=host]", "192.168.56.101"); pg.fill("input[formcontrolname=port]", "80")
        pg.get_by_role("button", name="Add").click(); time.sleep(2)
        pg.goto(UI + "/server/1/project/" + pid); time.sleep(12)
        pg.screenshot(path=out, full_page=False)
        b.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], len(sys.argv) > 3)
