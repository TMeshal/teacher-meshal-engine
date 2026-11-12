"""يحوّل مواصفة الإنفوجرافيك (JSON) إلى صورة PNG بمقاس 1080×1350 (تُصدَّر بضعف الدقة).

الاستعمال: python engine/render.py spec.json out.png
يعيد رمز خروج 3 إن فاض المحتوى عن البطاقة، مع وصف الفيض، ليختصره المولّد.
"""
import json, sys, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "card.html"

CHECK = """() => {
  const r = document.getElementById('root');
  const issues = [];
  if (r.scrollHeight > r.clientHeight + 2) issues.push('المحتوى أطول من البطاقة بـ ' + (r.scrollHeight - r.clientHeight) + 'px');
  document.querySelectorAll('.blk,.big,.chip').forEach(e => { if (e.scrollWidth > e.clientWidth + 2 || e.getBoundingClientRect().left < 40) issues.push('عنصر أعرض من مساحته: ' + e.textContent.slice(0, 40)); });
  return issues;
}"""


def render(spec: dict, out: str, scale: float = 2) -> list:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=scale)
        pg.add_init_script(f"window.DATA = {json.dumps(spec, ensure_ascii=False)};")
        pg.goto(TEMPLATE.as_uri())
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(250)
        issues = pg.evaluate(CHECK)
        pg.screenshot(path=out, type="png")
        b.close()
    return issues


if __name__ == "__main__":
    spec = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    problems = render(spec, sys.argv[2])
    if problems:
        print("\n".join(problems))
        sys.exit(3)
    print("ok")
