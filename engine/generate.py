"""محرك المحتوى اليومي لحساب @Teacher_Meshal.

يختار ركن المنشور من الخطة، ويكتب مرشّحين بزاويتين، ثم تراجعهما ثلاث عيون
(الدقة، الهوية، الإبداع) وتختار الأفضل وتصقله، ثم يُرسم الإنفوجرافيك ويُرسل
إلى سيدي في تيليجرام لاعتماده.

المتغيرات: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, OWNER_CHAT_ID
اختيارية: MODEL, SLOT (morning|evening), FORCE=1, NOTE, DATE=YYYY-MM-DD,
          DRY_RUN=1 (لا إرسال)، FIXTURE=ملف مرشّح جاهز (لا استدعاء للنموذج)
"""
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys

import requests

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from render import render  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
K = ROOT / "knowledge"
OUT = ROOT / "out"
HISTORY = ROOT / "history" / "posts.jsonl"
MODEL = os.environ.get("MODEL", "claude-opus-5-5")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_AR = {"sun": "الأحد", "mon": "الإثنين", "tue": "الثلاثاء", "wed": "الأربعاء", "thu": "الخميس", "fri": "الجمعة", "sat": "السبت"}
GRADES = ["g4", "g5", "g6"]
GRADE_AR = {"g4": "الرابع", "g5": "الخامس", "g6": "السادس"}


def load(name):
    p = K / name
    return json.loads(p.read_text("utf-8")) if p.suffix == ".json" else p.read_text("utf-8")


def today_riyadh():
    if os.environ.get("DATE"):
        return dt.date.fromisoformat(os.environ["DATE"])
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).date()


def history(n=40):
    if not HISTORY.exists():
        return []
    rows = [json.loads(l) for l in HISTORY.read_text("utf-8").splitlines() if l.strip()]
    return rows[-n:]


# ---------- السياق المدرسي ----------
def school_context(day, plan):
    cal = plan["calendar"]
    d = day.isoformat()
    for b in cal["breaks"]:
        if b["from"] <= d <= b["to"]:
            return {"status": b["name"], "tone": b["tone"], "term": "term1"}
    if d < "2026-12-27":
        start = dt.date.fromisoformat(cal["term1"]["start"])
        week = (day - start).days // 7 + 1
        week -= 1 if day > dt.date(2026, 11, 28) else 0  # أسبوع إجازة الخريف لا يُعد
        return {"status": f"الفصل الأول، قرابة الأسبوع الدراسي {week}", "note": cal["term1"]["_note"], "term": "term1"}
    if d < "2027-01-17":
        return {"status": "موسم المراجعة واختبارات نهاية الفصل الأول", "note": cal["term1_end_note"], "term": "term1"}
    for w in load(cal["term2_weeks_file"]):
        if w["from"] <= d <= (dt.date.fromisoformat(w["to"]) + dt.timedelta(days=2)).isoformat():
            if "off" in w:
                return {"status": w["off"], "term": "term2"}
            return {"status": f"الفصل الثاني، الأسبوع {w['week']}", "this_week_lessons": w["lessons"], "note": w.get("note"), "term": "term2"}
    return {"status": "الفصل الثاني", "term": "term2"}


def pick(day, slot, plan, hist):
    pillar = plan["rhythm"][DAYS[day.weekday()]].get(slot)
    if not pillar and os.environ.get("FORCE"):
        pillar = "lesson_value"
    if not pillar:
        return None, None, None
    done = {h.get("occasion") for h in hist}
    occasion = None
    for o in plan["calendar"]["occasions"]:
        delta = (dt.date.fromisoformat(o["date"]) - day).days
        if 0 <= delta <= o["lead_days"] and o["name"] not in done and pillar != "lab_showcase":
            pillar, occasion = "occasion", o
            break
    grade = None
    if plan["pillars"][pillar]["grade_rotation"]:
        last = {h.get("grade"): i for i, h in enumerate(hist)}
        grade = min(GRADES, key=lambda g: last.get(g, -1))
    return pillar, grade, occasion


# ---------- النموذج ----------
def claude(system, user, max_tokens=4000):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": max_tokens,
              "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
              "messages": [{"role": "user", "content": user}]},
        timeout=300,
    )
    r.raise_for_status()
    data = r.json()
    u = data.get("usage", {})
    print(f"[usage] in={u.get('input_tokens')} cache_read={u.get('cache_read_input_tokens')} out={u.get('output_tokens')}")
    return "".join(b.get("text", "") for b in data["content"])


def as_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("لم يُعد النموذج JSON:\n" + text[:500])
    return json.loads(m.group(0))


SCHEMA = """
أعد JSON فقط بهذا الشكل:
{"candidates":[{
  "angle": "الزاوية في جملة",
  "lesson": "الدرس أو الموضوع كما في الكتاب أو null",
  "x_text": "نص التغريدة كاملًا مع الوسمين في آخره",
  "telegram_text": "نص تيليجرام كاملًا",
  "infographic": {"layout": "...", "grade": "g4|g5|g6|null", "kicker": "اسم الدرس أو الموضوع بكلمتين إلى أربع", "title": "...", "...": "حقول القالب"}
}, {...المرشح الثاني بزاوية مختلفة حقًا...}]}

حقول القوالب:
- concept: big (رمز أو مصطلح قصير جدًا يتصدر البطاقة)، explain (حتى 20 كلمة)، tip (اختياري، نصيحة للمعلم حتى 14 كلمة)
- compare: right {label, points[2]}، left {label, points[2]} (كل نقطة حتى 7 كلمات)، verdict (حتى 14 كلمة)
- steps: steps [3 عناصر {t: حتى 5 كلمات، d: حتى 12 كلمة}]
- mistake: wrong (حتى 14 كلمة)، right (حتى 14 كلمة)، why (حتى 16 كلمة)
- scratch: blocks [2 إلى 6 {cat, text, indent: 0|1|2, hat: false}] (قيم الخانات بين [ ] داخل text)، caption (حتى 18 كلمة)
- statement: title عبارة قوية حتى 12 كلمة، sub حتى 18 كلمة
"""


def write(ctx, voice):
    user = (
        "اكتب منشور اليوم وفق هذا السياق:\n```json\n" + json.dumps(ctx, ensure_ascii=False, indent=1) + "\n```\n"
        "اكتب مرشّحين بزاويتين مختلفتين حقًا (لا إعادة صياغة)، واختر لكل منهما القالب الأنسب من قوالب الركن."
        " ابتعد عن مواضيع المنشورات الأخيرة وعناوينها.\n" + SCHEMA
    )
    return as_json(claude(voice, user, 5000))


REVIEW = """
أنت الآن لجنة مراجعة من ثلاثة لا يثقون بالكاتب:
1) مراجع الدقة والمنهج: يطابق كل مصطلح وكل معلومة مع ملف المنهج ومصطلحات الواجهة وحقائق المعمل حرفيًا، ويحذف كل ما لا دليل عليه.
2) مراجع الهوية والصوت: الخطوط الحمراء، والوسمان، ولا «الرابط في أول رد»، ولا سؤال خفيف، وطول النص، ووضوح الإنفوجرافيك لمن يرى الصورة وحدها.
3) المراجع المبدع: هل يستوقف السطر الأول معلمًا مستعجلًا؟ هل يحفظه المعلم؟ ما اللمسة الواحدة التي تجعله لا يُنسى؟

قيّم المرشّحين، واختر الأقوى، وطبّق عليه كل الإصلاحات والتحسين الإبداعي. ثم ضع درجة من 10 (معيارها: نفع المعلم غدًا، الدقة، قوة الاستيقاف، التميّز). إن قلّت عن 8 فحسّن أضعف نقطة قبل الإعادة.
أعد JSON فقط:
{"chosen": 0|1, "score": 8.5,
 "findings": {"accuracy": "سطر", "brand": "سطر", "creative": "سطر"},
 "final": {...المنشور النهائي بالشكل نفسه: angle, lesson, x_text, telegram_text, infographic...}}
"""


def review(ctx, draft, voice):
    user = ("السياق:\n```json\n" + json.dumps(ctx, ensure_ascii=False) + "\n```\nالمرشّحان:\n```json\n"
            + json.dumps(draft, ensure_ascii=False, indent=1) + "\n```\n" + REVIEW)
    return as_json(claude(voice, user, 5000))


def shorten(post, issues, voice):
    user = ("هذا الإنفوجرافيك فاض عن مساحته عند الرسم: " + "؛ ".join(issues)
            + "\nاختصر نصوصه مع الحفاظ على الفكرة والدقة، وأعد JSON الإنفوجرافيك وحده:\n```json\n"
            + json.dumps(post["infographic"], ensure_ascii=False) + "\n```")
    return as_json(claude(voice, user, 1500))


# ---------- تيليجرام ----------
def tg(method, **kw):
    files = kw.pop("files", None)
    r = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}", data=kw, files=files, timeout=60)
    r.raise_for_status()
    return r.json()["result"]


def send(post, meta, png):
    owner = os.environ["OWNER_CHAT_ID"]
    with open(png, "rb") as f:
        photo = tg("sendPhoto", chat_id=owner, caption=post["telegram_text"][:1024], files={"photo": f})
    f_ = meta["findings"]
    text = (
        f"<b>📌 منشور {meta['label']}</b>\n"
        f"الركن: {meta['pillar_name']}{' · الصف ' + GRADE_AR[meta['grade']] if meta.get('grade') else ''}\n\n"
        f"<b>نص X</b> (المس النص لنسخه، واحفظ الصورة أعلاه):\n<pre>{html.escape(post['x_text'])}</pre>\n\n"
        f"<b>🔎 المراجعون</b> · الدرجة {meta['score']}/10\n"
        f"• الدقة: {html.escape(f_.get('accuracy', ''))}\n"
        f"• الهوية: {html.escape(f_.get('brand', ''))}\n"
        f"• الإبداع: {html.escape(f_.get('creative', ''))}"
    )
    kb = {"inline_keyboard": [[{"text": "✅ انشر الصورة ونصها في القناة", "callback_data": f"pub:{photo['message_id']}"}],
                              [{"text": "🔁 بديل جديد", "callback_data": f"regen:{meta['slot']}"}]]}
    tg("sendMessage", chat_id=owner, text=text[:4096], parse_mode="HTML", reply_markup=json.dumps(kb, ensure_ascii=False))


# ---------- التشغيل ----------
def main():
    plan, voice = load("plan.json"), load("voice.md")
    day, slot = today_riyadh(), os.environ.get("SLOT", "morning")
    hist = history()
    pillar, grade, occasion = pick(day, slot, plan, hist)
    if not pillar:
        print(f"لا منشور مجدول: {day} {slot}")
        return
    sc = school_context(day, plan)
    term = sc["term"]
    cur = load("curriculum.json")[term]
    if grade:
        cur = [g for g in cur if g["grade"] == grade]
    system = voice + "\n\n" + load("terms.md")
    ctx = {
        "date": day.isoformat(), "day": DAY_AR[DAYS[day.weekday()]], "slot": "صباحًا قبل الدوام" if slot == "morning" else "مساءً",
        "pillar": plan["pillars"][pillar], "grade": grade and f"الصف {GRADE_AR[grade]} ({grade})",
        "school": sc, "occasion": occasion, "links": plan["links"],
        "curriculum": cur,
        "lab": load("lab.json") if pillar == "lab_showcase" else None,
        "recent_posts_to_avoid": [f"{h['date']} · {h.get('lesson')} · {h.get('title')}" for h in hist[-25:]],
        "owner_note": os.environ.get("NOTE") or None,
    }
    if os.environ.get("FIXTURE"):
        rev = json.loads(pathlib.Path(os.environ["FIXTURE"]).read_text("utf-8"))
    else:
        draft = write(ctx, system)
        rev = review(ctx, draft, system)
    post = rev["final"]
    ig = post["infographic"]
    ig["grade"] = ig.get("grade") if ig.get("grade") in GRADES else None
    if pillar == "lab_showcase":
        ig["link"] = plan["links"]["lab"]
    OUT.mkdir(exist_ok=True)
    png = str(OUT / f"{day}_{slot}.png")
    for attempt in range(3):
        issues = render(ig, png)
        if not issues:
            break
        if attempt == 2 or os.environ.get("FIXTURE"):
            raise SystemExit("تعذّر احتواء الإنفوجرافيك: " + "؛ ".join(issues))
        ig = shorten(post, issues, system)
        ig["grade"] = ig.get("grade") if ig.get("grade") in GRADES else None
        post["infographic"] = ig
    meta = {"label": f"{DAY_AR[DAYS[day.weekday()]]} {'الصباح' if slot == 'morning' else 'المساء'}",
            "pillar_name": plan["pillars"][pillar]["name"], "grade": grade, "slot": slot,
            "score": rev.get("score"), "findings": rev.get("findings", {})}
    (OUT / f"{day}_{slot}.json").write_text(json.dumps({"meta": meta, "post": post}, ensure_ascii=False, indent=1), "utf-8")
    if not os.environ.get("DRY_RUN"):
        send(post, meta, png)
    HISTORY.parent.mkdir(exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"date": day.isoformat(), "slot": slot, "pillar": pillar, "grade": grade,
                            "occasion": occasion and occasion["name"], "lesson": post.get("lesson"),
                            "title": ig.get("title"), "layout": ig.get("layout")}, ensure_ascii=False) + "\n")
    print("تم:", png)


if __name__ == "__main__":
    main()
