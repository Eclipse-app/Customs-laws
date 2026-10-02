import json, random, time, pathlib, html, re, datetime as dt, hashlib, secrets
import streamlit as st
import streamlit.components.v1 as components
import os
import requests
from html.parser import HTMLParser

st.set_page_config(page_title="Customs Laws", page_icon="⚖️", layout="wide")
B = pathlib.Path(__file__).parent
DF = B / "documents.json"
PF = B / "progress.json"
AF = B / "analysis.json"
ADMIN_PASSWORD = "1111"

TUR = {"VM": "Vazirlar Mahkamasi qarori", "AV": "Adliya vazirligi buyrug'i", "PQ": "Prezident qarori",
       "PF": "Prezident farmoni", "BQ": "Bojxona qo'mitasi qarori", "BK": "Bojxona kodeksi", "Q": "Qonun"}
COL = {"Vazirlar Mahkamasi qarori": "#6366f1", "Adliya vazirligi buyrug'i": "#0ea5e9", "Prezident qarori": "#f59e0b",
       "Prezident farmoni": "#ef4444", "Bojxona qo'mitasi qarori": "#10b981", "Bojxona kodeksi": "#8b5cf6",
       "Qonun": "#ec4899", "Boshqa": "#64748b"}
ORGAN = {
    "Qonun": ("Oliy Majlis Qonunchilik palatasi / Prezident imzosi", "Eng yuqori kuch (Konstitutsiyadan keyin)"),
    "Prezident farmoni": ("O'zbekiston Respublikasi Prezidenti", "Qonundan quyi, hukumat qarorlaridan yuqori"),
    "Prezident qarori": ("O'zbekiston Respublikasi Prezidenti", "Farmon bilan bir darajada, aniq chora-tadbirlar uchun"),
    "Vazirlar Mahkamasi qarori": ("O'zbekiston Respublikasi Vazirlar Mahkamasi", "Prezident hujjatlaridan quyi"),
    "Adliya vazirligi buyrug'i": ("Vazirlik/idora buyrug'i (Adliya vazirligida ro'yxatdan o'tgan)", "Idoraviy me'yoriy hujjat, eng quyi daraja"),
    "Bojxona qo'mitasi qarori": ("Davlat bojxona qo'mitasi", "Idoraviy hujjat"),
    "Bojxona kodeksi": ("Kodeks (qonun kuchiga ega)", "Qonun darajasida"),
}

def derive_tur(raqam):
    r = (raqam or "").strip()
    if not r: return "Boshqa"
    if r[0].upper() == "O" and "RQ" in r.upper(): return TUR["Q"]
    return TUR.get(r[:2].upper(), "Boshqa")

def derive_yil(sana):
    s = (sana or "").strip()[-4:]
    return int(s) if s.isdigit() else 0

def load_documents():
    raw = json.loads(DF.read_text(encoding="utf-8")) if DF.exists() else []
    for d in raw:
        d.setdefault("n", "")
        d["tur"] = derive_tur(d.get("raqam", ""))
        d["yil"] = derive_yil(d.get("sana", ""))
        d["key"] = d.get("raqam", "") + "|" + d.get("sana", "")
        d["nom"] = d.get("mazmun", "")
    return raw

def save_documents(docs):
    clean = [{"n": d.get("n", ""), "raqam": d["raqam"], "sana": d["sana"], "mazmun": d["mazmun"], "link": d.get("link", "")} for d in docs]
    DF.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")

DOCS = load_documents()
BYK = {d["key"]: d for d in DOCS}

# ---------- TAHLIL FUNKSIYALARI (Google Gemini — bepul) ----------
MODEL = "gemini-flash-latest"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

def doc_info(d):
    o, k = ORGAN.get(d["tur"], ("—", "—"))
    return {"Qabul qilgan organ": o, "Yuridik kuchi": k, "Qabul qilingan": d["sana"],
            "Hujjat yoshi": f"{dt.date.today().year - d['yil']} yil" if d["yil"] else "—"}

class _PageTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "header", "footer"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "header", "footer"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

def fetch_text(url, limit=45000):
    if not url or "/pdfs/" in url: return None
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        parser = _PageTextParser()
        parser.feed(r.text)
        txt = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
        return txt[:limit] if len(txt) > 500 else None
    except Exception:
        return None

def _gemini(key, prompt, max_tokens=2500):
    r = requests.post(
        GEMINI_URL,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"maxOutputTokens": max_tokens}},
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Gemini xatosi {r.status_code}: {r.text[:300]}")
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError(f"Gemini bo'sh javob qaytardi: {json.dumps(data, ensure_ascii=False)[:300]}")
    parts = cands[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts).strip()

def analyze(d, key, text=None):
    text = text or fetch_text(d.get("link"))
    src = f"HUJJAT MATNI:\n{text}" if text else "Hujjat matni olinmadi. Faqat quyidagi ma'lumotlarga tayan va buni 'ogohlantirish' maydonida ayt."
    p = f"""Sen O'zbekiston bojxona va tashqi savdo huquqi bo'yicha ekspertsan. Quyidagi hujjatni tahlil qil.
Hujjat: {d['tur']} {d['raqam']}, {d['sana']}. Qisqa mazmuni (foydalanuvchi yozgan): {d['mazmun']}
{src}
Faqat matnda bor narsaga tayan, o'ylab topma. Faqat JSON qaytar (izohsiz, ``` belgisiz), kalitlar:
"nima_haqida" (2-3 jumla), "maqsad", "asosiy_qoidalar" (5-8 ta punkt, aniq raqam/muddat/stavkalar bilan),
"kimlarga_tegishli", "amaliy_ahamiyat" (bojxona amaliyotida nima o'zgaradi), "muhim_raqamlar_muddatlar" (ro'yxat),
"boglangan_hujjatlar" (matnda tilga olingan), "xavf_va_nuanslar", "yodlash_maslahati" (qisqa mnemonika), "ogohlantirish" (matn olinmagan bo'lsa yoki noaniq joylar)"""
    raw = _gemini(key, p).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
    return json.loads(raw)

def load_analysis(): return json.loads(AF.read_text(encoding="utf-8")) if AF.exists() else {}
def store_analysis(k, v): a = load_analysis(); a[k] = v; AF.write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")

def relevant(q, docs, an, n=6):
    w = {x for x in re.findall(r"\w{4,}", q.lower())}
    def sc(d):
        t = (d["mazmun"] + " " + json.dumps(an.get(d["key"], {}), ensure_ascii=False)).lower()
        return sum(x[:5] in t for x in w)
    return [d for d in sorted(docs, key=sc, reverse=True)[:n] if sc(d) > 0]

def suggest(q, docs, an, key):
    ctx = ""
    for d in docs:
        a = an.get(d["key"])
        ctx += f"\n### {d['raqam']} ({d['sana']}) {d['mazmun']}\n" + (json.dumps(a, ensure_ascii=False) if a else (fetch_text(d.get("link"), 12000) or "matn yo'q")) + "\n"
    p = f"""Sen O'zbekiston bojxona va tashqi savdo huquqi bo'yicha maslahatchisan. Quyidagi hujjatlar asosida savolga javob ber.
SAVOL/VAZIYAT: {q}
HUJJATLAR:{ctx}
Javobni o'zbek tilida, shu bo'limlar bilan ber: 1) Qaysi hujjatlar qo'llanadi va nega (raqami bilan), 2) Amaliy qadamlar,
3) Hujjatlardagi bo'shliq yoki o'zaro nomuvofiqliklar, 4) Takomillashtirish bo'yicha aniq takliflar, 5) Xavflar.
Har bir fikrni qaysi hujjatga asoslanganingni ko'rsat. Bilmagan narsangni 'aniqlashtirish kerak' deb yoz. Oxirida: bu yuridik maslahat emas, rasmiy matnni lex.uz'da tekshiring."""
    return _gemini(key, p, 3500)

# ---------- FOYDALANUVCHI HISOBLARI (shaxsiy kabinet) ----------
USERS_FILE = B / "users.json"

def load_users():
    return json.loads(USERS_FILE.read_text(encoding="utf-8")) if USERS_FILE.exists() else {}

def save_users(u): USERS_FILE.write_text(json.dumps(u, ensure_ascii=False, indent=1), encoding="utf-8")

def hash_pw(password, salt): return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def empty_progress(): return {"box": {}, "fav": [], "notes": {}, "xp": 0, "hist": [], "days": {}}

def load_all_progress():
    return json.loads(PF.read_text(encoding="utf-8")) if PF.exists() else {}

def save_all_progress(d): PF.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

# ---------- holat ----------
S = st.session_state
if "init" not in S:
    S.update(init=True, user=None, P=None, score=0, streak=0, Q={}, qidc=0, card=0, flip=False, t0=None, ex=None,
             section="👥 Foydalanuvchi", page="🏠 Bosh sahifa", is_admin=False)
P = S.P
today = str(dt.date.today())

def save():
    if not S.user: return
    allp = load_all_progress(); allp[S.user] = P; save_all_progress(allp)
def box(d): return P["box"].get(d["key"], 0)
def learned(d): return box(d) >= 4
def short(t, n=80): return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"
def level(): return P["xp"] // 150 + 1
TITLES = ["Yangi boshlovchi", "Izlanuvchi", "Bilimdon", "Tajribali", "Mutaxassis", "Ekspert", "Usta", "Afsona"]

def answer(ok, d, mult=1):
    S.streak = S.streak + 1 if ok else 0
    if ok: pts = (10 + min(S.streak, 8) * 2) * mult; S.score += pts; P["xp"] += pts
    P["box"][d["key"]] = min(box(d) + 1, 5) if ok else 1
    P["days"][today] = P["days"].get(today, 0) + 1
    save()

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif}
#MainMenu,footer{visibility:hidden}.block-container{padding-top:1.5rem;max-width:1200px}
.hero{background:linear-gradient(135deg,#4f46e5,#7c3aed 55%,#ec4899);color:#fff;border-radius:22px;padding:28px 32px;margin-bottom:18px;
box-shadow:0 10px 30px rgba(79,70,229,.35)}.hero h1{margin:0;font-size:2rem;font-weight:800;color:#fff}.hero p{margin:6px 0 0;opacity:.9}
.card{border:1px solid rgba(128,128,128,.25);border-left:6px solid var(--c);border-radius:16px;padding:14px 16px;margin:8px 0;
background:rgba(128,128,128,.06);transition:.2s}.card:hover{transform:translateY(-3px);box-shadow:0 8px 22px rgba(0,0,0,.15)}
.tag{background:var(--c);color:#fff;border-radius:20px;padding:2px 10px;font-size:.72rem;font-weight:600}
.meta{opacity:.65;font-size:.8rem;margin-left:8px}.no{font-size:1.15rem;font-weight:800;margin:6px 0 2px}.tx{opacity:.9;font-size:.93rem}
.stat{border-radius:18px;padding:16px;text-align:center;background:rgba(99,102,241,.1);border:1px solid rgba(99,102,241,.25)}
.stat b{display:block;font-size:1.8rem}.stat span{opacity:.7;font-size:.8rem}
.flash{min-height:230px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;border-radius:24px;
padding:30px;background:linear-gradient(135deg,rgba(99,102,241,.18),rgba(236,72,153,.15));border:1px solid rgba(128,128,128,.3);font-size:1.35rem;font-weight:600}
.q{font-size:1.25rem;font-weight:700;padding:18px;border-radius:16px;background:rgba(99,102,241,.1);margin-bottom:12px}
.stButton>button{border-radius:12px;font-weight:600}
.adminbox{border:2px dashed #f59e0b;border-radius:16px;padding:18px;background:rgba(245,158,11,.08)}
</style>""", unsafe_allow_html=True)

def card(d):
    tur = d.get("tur", "Boshqa")
    color = COL.get(tur, COL["Boshqa"])
    fl = ("⭐ " if d["key"] in P["fav"] else "") + ("✅ " if learned(d) else "")
    return (f"<div class='card' style='--c:{color}'><span class='tag'>{tur}</span><span class='meta'>{d['sana']}</span>"
            f"<div class='no'>{fl}{html.escape(d['raqam'])}</div><div class='tx'>{html.escape(d['mazmun'])}</div></div>")

def linkbtn(d):
    if d.get("link"): st.link_button("Lex.uz'da ochish ↗", d["link"], use_container_width=True)
    else: st.caption("Havola yo'q")

# ============================================================
# SIDEBAR: FOYDALANUVCHI / ADMIN TANLOVI
# ============================================================
st.sidebar.title("⚖️ Customs Laws")
S.section = st.sidebar.radio("Kirish turi", ["👥 Foydalanuvchi", "🔑 Admin"],
                              index=["👥 Foydalanuvchi", "🔑 Admin"].index(S.section))

# ============================================================
# ADMIN QISMI
# ============================================================
if S.section == "🔑 Admin":
    st.sidebar.divider()
    if not S.is_admin:
        st.title("🔑 Admin kirish")
        st.info("Yangi qonun hujjat qo'shish va tahrirlash faqat administrator uchun.")
        pw = st.text_input("Parolni kiriting", type="password")
        if st.button("Kirish", type="primary"):
            if pw == ADMIN_PASSWORD:
                S.is_admin = True; st.rerun()
            else:
                st.error("❌ Parol noto'g'ri.")
    else:
        st.sidebar.success("🔓 Admin sifatida kirdingiz")
        if st.sidebar.button("🚪 Chiqish"): S.is_admin = False; st.rerun()

        st.title("🔑 Admin panel")
        st.caption(f"Jami hujjatlar: {len(DOCS)}")
        at = st.tabs(["➕ Yangi hujjat qo'shish", "✏️ Tahrirlash / O'chirish", "📤 Faylni yuklab olish"])

        with at[0]:
            st.markdown("<div class='adminbox'>", unsafe_allow_html=True)
            st.subheader("Yangi normativ-huquqiy hujjat qo'shish")
            c1, c2 = st.columns(2)
            raqam = c1.text_input("Hujjat raqami *", placeholder="masalan: VM-120")
            sana = c2.text_input("Qabul qilingan sana *", placeholder="masalan: 15.03.2026")
            mazmun = st.text_area("Hujjat nomi / mazmuni *", placeholder="Hujjatning qisqacha mazmuni yoki to'liq nomi")
            link = st.text_input("Lex.uz havolasi", placeholder="https://lex.uz/docs/...")
            if raqam:
                st.caption(f"Aniqlangan turi: **{derive_tur(raqam)}**")
            if st.button("✅ Hujjatni qo'shish", type="primary"):
                if not raqam or not sana or not mazmun:
                    st.error("Raqam, sana va mazmun maydonlari majburiy.")
                elif any(d["raqam"].replace(" ", "") == raqam.replace(" ", "") and d["sana"] == sana for d in DOCS):
                    st.error("Bunday raqam va sanadagi hujjat allaqachon mavjud.")
                else:
                    new_doc = {"n": str(len(DOCS) + 1), "raqam": raqam.strip(), "sana": sana.strip(),
                               "mazmun": mazmun.strip(), "link": link.strip()}
                    DOCS.append(new_doc)
                    save_documents(DOCS)
                    st.success(f"✅ {raqam} muvaffaqiyatli qo'shildi!")
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        with at[1]:
            st.subheader("Mavjud hujjatni tahrirlash yoki o'chirish")
            if not DOCS:
                st.info("Hozircha hujjatlar yo'q.")
            else:
                sel = st.selectbox("Hujjatni tanlang", DOCS, format_func=lambda x: f"{x['raqam']} — {short(x['mazmun'], 70)}")
                idx = DOCS.index(sel)
                c1, c2 = st.columns(2)
                e_raqam = c1.text_input("Raqami", sel["raqam"], key="e_raqam")
                e_sana = c2.text_input("Sanasi", sel["sana"], key="e_sana")
                e_mazmun = st.text_area("Mazmuni", sel["mazmun"], key="e_mazmun")
                e_link = st.text_input("Lex.uz havolasi", sel.get("link", ""), key="e_link")
                b1, b2 = st.columns(2)
                if b1.button("💾 Saqlash", type="primary", use_container_width=True):
                    DOCS[idx] = {"n": sel.get("n", str(idx + 1)), "raqam": e_raqam.strip(), "sana": e_sana.strip(),
                                 "mazmun": e_mazmun.strip(), "link": e_link.strip()}
                    save_documents(DOCS)
                    st.success("✅ O'zgarishlar saqlandi.")
                    st.rerun()
                if b2.button("🗑 O'chirish", use_container_width=True):
                    DOCS.pop(idx)
                    save_documents(DOCS)
                    st.success("🗑 Hujjat o'chirildi.")
                    st.rerun()

        with at[2]:
            st.subheader("Faylni yuklab olish")
            st.warning("⚠️ Streamlit Cloud'dagi fayllar vaqtinchalik: ilova qayta ishga tushirilsa (reboot) yoki qayta joylansa, "
                       "shu yerda qilgan o'zgarishlar yo'qolishi mumkin. O'zgarishlarni doimiy saqlash uchun yangilangan "
                       "`documents.json` faylini yuklab oling va uni GitHub repozitoriyingizga qayta yuklang (commit qiling).")
            st.download_button("⬇️ documents.json yuklab olish", DF.read_text(encoding="utf-8"),
                                "documents.json", use_container_width=True)
            st.dataframe([{"Raqam": d["raqam"], "Sana": d["sana"], "Mazmun": short(d["mazmun"], 60)} for d in DOCS],
                         use_container_width=True, height=350)

# ============================================================
# FOYDALANUVCHI QISMI
# ============================================================
else:
    # ---------- KIRISH / RO'YXATDAN O'TISH ----------
    if not S.user:
        st.markdown("<div class='hero'><h1>⚖️ Customs Laws</h1><p>Shaxsiy kabinetingizga kiring — testlar, o'yinlar va natijalaringiz saqlanib boradi</p></div>", unsafe_allow_html=True)
        tL, tR = st.tabs(["🔑 Kirish", "🆕 Ro'yxatdan o'tish"])
        with tL:
            with st.form("login_form"):
                lu = st.text_input("Foydalanuvchi nomi")
                lp = st.text_input("Parol", type="password")
                if st.form_submit_button("Kirish", type="primary", use_container_width=True):
                    uname = lu.strip().lower()
                    users = load_users()
                    rec = users.get(uname)
                    if rec and rec["hash"] == hash_pw(lp, rec["salt"]):
                        S.user = uname
                        S.P = load_all_progress().get(uname, empty_progress())
                        S.score = 0; S.streak = 0; S.Q = {}
                        st.rerun()
                    else:
                        st.error("❌ Foydalanuvchi nomi yoki parol noto'g'ri.")
        with tR:
            with st.form("register_form"):
                ru = st.text_input("Foydalanuvchi nomi (lotin harf/raqam)", placeholder="masalan: ali_2026")
                rp = st.text_input("Parol (kamida 4 belgi)", type="password")
                rp2 = st.text_input("Parolni takrorlang", type="password")
                if st.form_submit_button("Ro'yxatdan o'tish", type="primary", use_container_width=True):
                    uname = re.sub(r"[^a-z0-9_]", "", ru.strip().lower())
                    users = load_users()
                    if not uname or not rp:
                        st.error("Barcha maydonlarni to'ldiring.")
                    elif uname != ru.strip().lower():
                        st.error("Foydalanuvchi nomida faqat lotin harflari, raqam va pastki chiziq bo'lishi mumkin.")
                    elif uname in users:
                        st.error("Bu foydalanuvchi nomi band, boshqa nom tanlang.")
                    elif len(rp) < 4:
                        st.error("Parol kamida 4 ta belgidan iborat bo'lsin.")
                    elif rp != rp2:
                        st.error("Parollar bir xil emas.")
                    else:
                        salt = secrets.token_hex(8)
                        users[uname] = {"hash": hash_pw(rp, salt), "salt": salt, "created": today}
                        save_users(users)
                        allp = load_all_progress(); allp[uname] = empty_progress(); save_all_progress(allp)
                        S.user = uname; S.P = empty_progress(); S.score = 0; S.streak = 0; S.Q = {}
                        st.success("✅ Ro'yxatdan o'tdingiz! Endi kirdingiz.")
                        st.rerun()
        st.stop()

    P = S.P
    st.sidebar.success(f"👤 {S.user}")
    if st.sidebar.button("🚪 Chiqish", key="user_logout"):
        S.user = None; S.P = None; st.rerun()
    st.sidebar.divider()

    PAGES = ["🏠 Bosh sahifa", "📖 Ro'yxat", "🃏 Flashcards", "🎮 O'yinlar", "📊 Statistika", "🔍 Tahlil", "💡 Takliflar"]
    S.page = st.sidebar.radio("Bo'lim", PAGES, index=PAGES.index(S.page) if S.page in PAGES else 0)
    st.sidebar.markdown(f"**{level()}-daraja · {TITLES[min(level() - 1, 7)]}**")
    st.sidebar.progress((P["xp"] % 150) / 150, text=f"{P['xp']} XP")
    lc = sum(learned(d) for d in DOCS)
    st.sidebar.progress(lc / max(len(DOCS), 1), text=f"O'zlashtirildi {lc}/{len(DOCS)}")
    st.sidebar.metric("Sessiya ball", S.score, f"🔥 {S.streak} seriya")

    # ---------- savol generatori ----------
    MODES = {"Nom → Raqam": ("nom", "raqam"), "Raqam → Nom": ("raqam", "nom"), "Raqam → Sana": ("raqam", "sana"), "Nom → Tur": ("nom", "tur")}
    def fmt(d, f): return short(d[f], 75) if f == "nom" else d[f]
    def gen(mode, pool=None):
        a, b = MODES[mode]
        pool = pool or DOCS
        d = random.choice(pool)
        ok = fmt(d, b)
        ds = list({fmt(x, b) for x in DOCS if fmt(x, b) != ok})
        op = random.sample(ds, min(3, len(ds))) + [ok]; random.shuffle(op)
        lab = {"nom": "Hujjat nomi", "raqam": "Hujjat raqami", "sana": "Sanasi", "tur": "Turi"}
        return dict(d=d, q=f"<b>{lab[a]}:</b> {html.escape(str(d[a]))}<br><small>Toping → {lab[b]}</small>", ok=ok, op=op, done=None)

    def weak_pool(): return [d for d in DOCS if box(d) < 3] or DOCS

    def quiz(qkey, modes, pool=None, mult=1):
        """Har bir o'yin bo'limi o'zining mustaqil savol holatiga ega (S.Q[qkey])."""
        if S.Q.get(qkey) is None:
            q = gen(random.choice(modes), pool)
            q["qid"] = S.qidc; S.qidc += 1
            S.Q[qkey] = q
        q = S.Q[qkey]
        st.markdown(f"<div class='q'>{q['q']}</div>", unsafe_allow_html=True)
        cols = st.columns(2)
        for i, o in enumerate(q["op"]):
            if cols[i % 2].button(o, key=f"{qkey}_{q['qid']}_{i}", use_container_width=True, disabled=q["done"] is not None):
                q["done"] = o; answer(o == q["ok"], q["d"], mult); st.rerun()
        if q["done"] is None: return False
        st.success("✅ To'g'ri!") if q["done"] == q["ok"] else st.error(f"❌ To'g'ri javob: {q['ok']}")
        st.markdown(card(q["d"]), unsafe_allow_html=True)
        return True

    if not DOCS:
        st.warning("Hozircha hech qanday hujjat yo'q. Admin bo'limidan hujjat qo'shing.")
        st.stop()

    # ================= BOSH SAHIFA =================
    if S.page == PAGES[0]:
        st.markdown("<div class='hero'><h1>⚖️ Customs Laws</h1><p>Normativ-huquqiy hujjatlarni o'ynab, oson va tez yodlang</p></div>", unsafe_allow_html=True)
        n = P["days"].get(today, 0)
        c = st.columns(4)
        for col, (v, l) in zip(c, [(len(DOCS), "Jami hujjat"), (lc, "O'zlashtirilgan"), (f"{n}/20", "Bugungi maqsad"), (level(), "Daraja")]):
            col.markdown(f"<div class='stat'><b>{v}</b><span>{l}</span></div>", unsafe_allow_html=True)
        st.progress(min(n / 20, 1.0), text="Kunlik maqsad: 20 ta javob")
        a, b = st.columns(2)
        dd = random.Random(today).choice(DOCS)
        with a:
            st.subheader("📅 Kunlik hujjat"); st.markdown(card(dd), unsafe_allow_html=True); linkbtn(dd)
        with b:
            st.subheader("🚀 Tez boshlash")
            for lbl, pg in [("🃏 Qiynalgan hujjatlarni takrorlash", 2), ("🎮 O'yin o'ynash", 3), ("📖 Hujjatlar ro'yxati", 1)]:
                if st.button(lbl, use_container_width=True, key="qs_" + lbl): S.page = PAGES[pg]; st.rerun()
            if st.button("🎲 Tasodifiy hujjat", use_container_width=True, key="qs_random"):
                r = random.choice(DOCS); st.markdown(card(r), unsafe_allow_html=True); linkbtn(r)

    # ================= RO'YXAT =================
    elif S.page == PAGES[1]:
        st.title("📖 Hujjatlar kutubxonasi")
        c = st.columns([3, 2, 2])
        qs = c[0].text_input("🔎 Qidiruv", placeholder="raqam, nom, yil: valyuta, VM-55, 2025")
        tu = c[1].multiselect("Turi", sorted({d["tur"] for d in DOCS}))
        srt = c[2].selectbox("Saralash", ["Raqam bo'yicha", "Yangi → eski", "Eski → yangi", "Qiyinlari birinchi"])
        y0, y1 = min(d["yil"] for d in DOCS), max(d["yil"] for d in DOCS)
        yr = st.slider("Qabul qilingan yil", y0, y1, (y0, y1)) if y0 != y1 else (y0, y1)
        f = st.columns(4)
        fav = f[0].toggle("⭐ Sevimlilar")
        hard = f[1].toggle("😅 Qiyinlari")
        nol = f[2].toggle("🔗 Havolasizlar")
        hammasi = f[3].toggle("📋 Hammasini bitta sahifada")
        res = [d for d in DOCS if (not qs or qs.lower() in (d["raqam"] + d["mazmun"] + d["sana"]).lower()) and (not tu or d["tur"] in tu)
               and yr[0] <= d["yil"] <= yr[1] and (not fav or d["key"] in P["fav"]) and (not hard or box(d) < 3) and (not nol or not d.get("link"))]
        res.sort(key={"Yangi → eski": lambda d: -d["yil"], "Eski → yangi": lambda d: d["yil"], "Qiyinlari birinchi": box}.get(srt, lambda d: 0))
        st.caption(f"🔎 Jami topildi: **{len(res)}** ta hujjat (kutubxonada jami {len(DOCS)} ta)")
        if hammasi:
            shown = res
        else:
            per = 20
            pages = max(1, -(-len(res) // per))
            pg = st.number_input(f"Sahifa (1 dan {pages} gacha)", 1, pages, 1) - 1
            shown = res[pg * per:(pg + 1) * per]
        cols = st.columns(2)
        for i, d in enumerate(shown):
            with cols[i % 2]:
                st.markdown(card(d), unsafe_allow_html=True)
                b1, b2 = st.columns(2)
                with b1: linkbtn(d)
                if b2.button("★ Sevimli" if d["key"] not in P["fav"] else "☆ Olib tashlash", key="f" + d["key"], use_container_width=True):
                    P["fav"].remove(d["key"]) if d["key"] in P["fav"] else P["fav"].append(d["key"]); save(); st.rerun()
                with st.expander("📝 Mening eslatmam (mnemonika)"):
                    t = st.text_area("Eslatma", P["notes"].get(d["key"], ""), key="n" + d["key"], label_visibility="collapsed")
                    if t != P["notes"].get(d["key"], ""): P["notes"][d["key"]] = t; save()

    # ================= FLASHCARDS =================
    elif S.page == PAGES[2]:
        st.title("🃏 Flashcards (Leytner takrorlash tizimi)")
        m = st.radio("Yo'nalish", ["Nom → Raqam", "Raqam → Nom"], horizontal=True)
        if "cd" not in S: S.cd = None
        if S.cd is None:
            S.cd = random.choices(DOCS, weights=[6 - box(d) for d in DOCS])[0]; S.flip = False
        d = S.cd
        front, back = (d["nom"], d["raqam"]) if m == "Nom → Raqam" else (d["raqam"], d["nom"])
        txt = f"{html.escape(back)}<br><small style='opacity:.7'>{d['tur']} · {d['sana']}</small>" if S.flip else html.escape(front)
        st.markdown(f"<div class='flash'>{txt}</div>", unsafe_allow_html=True)
        st.caption(f"Bilim darajasi: {'🟩' * box(d)}{'⬜' * (5 - box(d))}")
        c = st.columns(5)
        if c[0].button("🔄 Aylantirish", use_container_width=True, key="fc_flip"): S.flip = not S.flip; st.rerun()
        if c[1].button("✅ Bilaman", use_container_width=True, key="fc_know"): answer(True, d); S.cd = None; st.rerun()
        if c[2].button("😅 Qiyin", use_container_width=True, key="fc_hard"): answer(False, d); S.cd = None; st.rerun()
        if c[3].button("⏭ O'tkazish", use_container_width=True, key="fc_skip"): S.cd = None; st.rerun()
        with c[4]: linkbtn(d)
        components.html(f"<button onclick=\"var u=new SpeechSynthesisUtterance({json.dumps(d['nom'])});u.lang='ru-RU';speechSynthesis.speak(u)\" "
                        "style='padding:8px 16px;border-radius:10px;border:1px solid #888;cursor:pointer'>🔊 Ovozli o'qish</button>", height=50)
        if P["notes"].get(d["key"]): st.info("📝 " + P["notes"][d["key"]])

    # ================= O'YINLAR =================
    elif S.page == PAGES[3]:
        st.title("🎮 O'yinlar")
        t = st.tabs(["❓ Viktorina", "✍️ Yozma", "🔗 Juftlash", "⏱ Vaqtga qarshi", "🎓 Imtihon", "🎯 Xatolar ustida"])
        with t[0]:
            ms = st.multiselect("Savol turlari", list(MODES), default=list(MODES)[:2], key="viktorina_modes") or list(MODES)
            if quiz("v", ms) and st.button("Keyingi ➡️", type="primary", key="nv"): S.Q["v"] = None; st.rerun()
        with t[1]:
            if "w" not in S: S.w = random.choice(DOCS)
            d = S.w
            st.markdown(f"<div class='q'><b>Hujjat nomi:</b> {html.escape(d['nom'])}<br><small>Uning raqamini yozing (masalan VM-55)</small></div>", unsafe_allow_html=True)
            ans = st.text_input("Raqam", key="wi" + str(S.get("wn", 0)))
            norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower().replace("ʻ", "").replace("‘", "").replace("'", ""))
            if st.button("Tekshirish", type="primary", key="w_check") and ans:
                ok = norm(ans) == norm(d["raqam"]); answer(ok, d, 2)
                st.success("✅ To'g'ri! +2x ball") if ok else st.error(f"❌ To'g'ri javob: {d['raqam']}")
                st.markdown(card(d), unsafe_allow_html=True)
            if st.button("Keyingi ➡️", key="nw"): S.w = random.choice(DOCS); S.wn = S.get("wn", 0) + 1; st.rerun()
        with t[2]:
            rev = st.radio("Yo'nalish", ["Nom → Raqam", "Raqam → Nom"], horizontal=True, key="pair_dir")
            if "pairs" not in S: S.pairs = random.sample(DOCS, min(6, len(DOCS))); S.pk = 0
            L, R = ("nom", "raqam") if rev == "Nom → Raqam" else ("raqam", "nom")
            opts = [fmt(d, R) for d in S.pairs]; random.Random(S.pk).shuffle(opts)
            sel = {}
            for d in S.pairs:
                a, b = st.columns([1, 1])
                a.markdown(f"**{fmt(d, L)}**")
                sel[d["key"]] = b.selectbox("j", ["—"] + opts, key=f"m{S.pk}{d['key']}", label_visibility="collapsed")
            c = st.columns(2)
            if c[0].button("Tekshirish", type="primary", key="pair_check"):
                n = 0
                for d in S.pairs:
                    ok = sel[d["key"]] == fmt(d, R); n += ok; answer(ok, d)
                    st.write(("✅ " if ok else f"❌ → {fmt(d, R)} | ") + fmt(d, L))
                st.success(f"Natija: {n}/{len(S.pairs)}")
            if c[1].button("🔄 Yangi to'plam", key="pair_new"):
                del S["pairs"]; S.pk += 1; st.rerun()
        with t[3]:
            if S.t0 is None:
                st.info("60 soniyada iloji boricha ko'p to'g'ri javob bering. Ball ×2!")
                if st.button("▶️ Boshlash", type="primary", key="timer_start"):
                    S.t0 = time.time(); S.s0 = S.score; S.Q["t"] = None; st.rerun()
            else:
                left = 60 - (time.time() - S.t0)
                if left <= 0:
                    st.balloons(); pts = S.score - S.s0; st.success(f"Vaqt tugadi! Ball: {pts}")
                    P["hist"].append({"sana": today, "rejim": "Vaqtga qarshi", "ball": pts}); save()
                    S.t0 = None; S.Q["t"] = None
                    if st.button("Yana o'ynash", key="timer_again"): st.rerun()
                else:
                    st.progress(max(left, 0) / 60, text=f"⏳ {int(left)} soniya")
                    if quiz("t", list(MODES), mult=2):
                        if st.button("Keyingi ➡️", type="primary", key="nt"): S.Q["t"] = None; st.rerun()
                    else:
                        time.sleep(1); st.rerun()
        with t[4]:
            N = st.select_slider("Savollar soni", [10, 20, 30, 50], 20, key="exam_n")
            if S.ex is None:
                if st.button("🎓 Imtihonni boshlash", type="primary", key="exam_start"):
                    S.ex = dict(qs=[gen(random.choice(list(MODES))) for _ in range(N)], i=0, ok=0, bad=[]); st.rerun()
            else:
                e = S.ex
                if e["i"] >= len(e["qs"]):
                    pc = round(100 * e["ok"] / len(e["qs"])); st.metric("Natija", f"{pc}%", f"{e['ok']}/{len(e['qs'])}")
                    st.success("A'lo! 🏆") if pc >= 85 else st.warning("Yana takrorlang 💪")
                    for d in e["bad"]: st.markdown(card(d), unsafe_allow_html=True)
                    if not e.get("saved"):
                        P["hist"].append({"sana": today, "rejim": "Imtihon", "ball": pc}); save(); e["saved"] = True
                    if st.button("Yangi imtihon", key="exam_new"): S.ex = None; st.rerun()
                else:
                    q = e["qs"][e["i"]]; st.progress(e["i"] / len(e["qs"]), text=f"Savol {e['i'] + 1}/{len(e['qs'])}")
                    st.markdown(f"<div class='q'>{q['q']}</div>", unsafe_allow_html=True)
                    for i, o in enumerate(q["op"]):
                        if st.button(o, key=f"e{e['i']}{i}", use_container_width=True):
                            ok = o == q["ok"]; e["ok"] += ok; answer(ok, q["d"])
                            if not ok: e["bad"].append(q["d"])
                            e["i"] += 1; st.rerun()
        with t[5]:
            st.caption("Faqat 3-qutidan past (qiynalgan) hujjatlar chiqadi")
            if quiz("w2", list(MODES), weak_pool()) and st.button("Keyingi ➡️", type="primary", key="nx"): S.Q["w2"] = None; st.rerun()

    # ================= STATISTIKA =================
    elif S.page == PAGES[4]:
        st.title("📊 Statistika va yutuqlar")
        c = st.columns(4)
        for col, (v, l) in zip(c, [(P["xp"], "Jami XP"), (level(), "Daraja"), (len(P["fav"]), "Sevimlilar"), (sum(P["days"].values()), "Jami javoblar")]):
            col.markdown(f"<div class='stat'><b>{v}</b><span>{l}</span></div>", unsafe_allow_html=True)
        a, b = st.columns(2)
        with a:
            st.subheader("Tur bo'yicha o'zlashtirish, %")
            data = {t: round(100 * sum(learned(d) for d in DOCS if d["tur"] == t) / max(sum(d["tur"] == t for d in DOCS), 1))
                    for t in COL if any(d["tur"] == t for d in DOCS)}
            if data: st.bar_chart(data)
        with b:
            st.subheader("Yillar bo'yicha hujjatlar soni")
            yc = {}
            for d in DOCS: yc[str(d["yil"])] = yc.get(str(d["yil"]), 0) + 1
            st.bar_chart(dict(sorted(yc.items())))
        st.subheader("🏅 Yutuqlar")
        bd = [(lc >= 10, "🥉 10 ta hujjat"), (lc >= 30, "🥈 30 ta hujjat"), (lc >= 60, "🥇 60 ta hujjat"), (lc >= len(DOCS), "🏆 Hammasi!"),
              (P["xp"] >= 1000, "💎 1000 XP"), (any(h["ball"] >= 90 for h in P["hist"] if h["rejim"] == "Imtihon"), "🎓 Imtihon 90%+"), (len(P["days"]) >= 7, "📆 7 kun faol")]
        st.write(" · ".join(("✅ " if o else "🔒 ") + n for o, n in bd))
        st.subheader("😅 Eng qiyin 10 ta hujjat")
        for d in sorted(DOCS, key=box)[:10]: st.markdown(card(d), unsafe_allow_html=True)
        if P["hist"]: st.subheader("Natijalar tarixi"); st.dataframe(P["hist"][::-1], use_container_width=True)
        st.download_button("⬇️ Progressni yuklab olish", json.dumps(P, ensure_ascii=False), f"progress_{S.user}.json")
        if st.button("🗑 Progressni tozalash"):
            S.P = empty_progress()
            allp = load_all_progress(); allp[S.user] = S.P; save_all_progress(allp)
            st.rerun()

    # ================= TAHLIL =================
    elif S.page == PAGES[5]:
        st.title("🔍 Hujjat tahlili")
        KEY = os.environ.get("GEMINI_API_KEY") or st.sidebar.text_input("Gemini API kaliti", type="password", help="Bepul kalitni aistudio.google.com dan oling")
        AN = load_analysis()
        d = st.selectbox("Hujjatni tanlang", DOCS, format_func=lambda x: f"{x['raqam']} — {short(x['mazmun'], 70)}")
        st.markdown(card(d), unsafe_allow_html=True); linkbtn(d)
        for k, v in doc_info(d).items(): st.write(f"**{k}:** {v}")
        a = AN.get(d["key"])
        if not a:
            st.info("Chuqur tahlil hali yo'q. U hujjatning lex.uz'dagi matniga asoslanib tayyorlanadi.")
            man = st.text_area("Matn olinmasa, hujjat matnini shu yerga qo'ying (ixtiyoriy)")
            if st.button("🧠 Chuqur tahlil qilish", type="primary"):
                if not KEY: st.error("Yon panelda API kalitini kiriting.")
                else:
                    with st.spinner("Hujjat o'qilmoqda..."):
                        try: store_analysis(d["key"], analyze(d, KEY, man or None)); st.rerun()
                        except Exception as e: st.error(f"Xato: {e}")
        else:
            if a.get("ogohlantirish"): st.warning(a["ogohlantirish"])
            L = {"nima_haqida": "📌 Nima haqida", "maqsad": "🎯 Maqsadi", "asosiy_qoidalar": "📋 Asosiy qoidalar", "kimlarga_tegishli": "👥 Kimlarga tegishli",
                 "amaliy_ahamiyat": "🛠 Amaliy ahamiyati", "muhim_raqamlar_muddatlar": "🔢 Muhim raqam va muddatlar", "boglangan_hujjatlar": "🔗 Bog'liq hujjatlar",
                 "xavf_va_nuanslar": "⚠️ Xavf va nuanslar", "yodlash_maslahati": "🧠 Yodlash maslahati"}
            for k, tt in L.items():
                v = a.get(k)
                if v: st.subheader(tt); [st.write("• " + str(x)) for x in v] if isinstance(v, list) else st.write(v)
            if st.button("🔄 Qayta tahlil qilish", key="reanalyze") and KEY: store_analysis(d["key"], analyze(d, KEY)); st.rerun()
        st.caption(f"Tahlil qilingan hujjatlar: {len(AN)}/{len(DOCS)}")
        if st.button("⚙️ Qolgan hujjatlarni ketma-ket tahlil qilish (uzoq davom etadi)", key="analyze_all") and KEY:
            todo = [x for x in DOCS if x["key"] not in AN]; bar = st.progress(0)
            for i, x in enumerate(todo, 1):
                try: store_analysis(x["key"], analyze(x, KEY))
                except Exception as e: st.warning(f"{x['raqam']}: {e}")
                bar.progress(i / len(todo), text=f"{i}/{len(todo)} — {x['raqam']}")
            st.rerun()

    # ================= TAKLIFLAR =================
    else:
        st.title("💡 Takliflar va huquqiy tahlil")
        KEY = os.environ.get("GEMINI_API_KEY") or st.sidebar.text_input("Gemini API kaliti", type="password", help="Bepul kalitni aistudio.google.com dan oling")
        AN = load_analysis()
        q = st.text_area("Vaziyat, muammo yoki mavzuni yozing", placeholder="Masalan: jismoniy shaxs 6 oyda ikkinchi marta avtomobil ehtiyot qismlarini olib kirmoqchi. Qanday tartib va bojlar qo'llanadi? Qonunchilikda qanday bo'shliqlar bor?")
        auto = relevant(q, DOCS, AN) if q else []
        sel = st.multiselect("Tahlilga olinadigan hujjatlar (avtomatik tanlanadi, o'zgartirishingiz mumkin)", DOCS, default=auto, format_func=lambda x: f"{x['raqam']} — {short(x['mazmun'], 60)}")
        st.caption(f"Chuqur tahlili tayyor hujjatlar: {sum(x['key'] in AN for x in sel)}/{len(sel)} — tahlil qancha ko'p bo'lsa, javob shuncha aniq.")
        if st.button("💡 Takliflar tayyorlash", type="primary", disabled=not (q and sel)):
            if not KEY: st.error("Yon panelda API kalitini kiriting.")
            else:
                with st.spinner("Hujjatlar tahlil qilinmoqda..."):
                    try: st.markdown(suggest(q, sel, AN, KEY))
                    except Exception as e: st.error(f"Xato: {e}")
        for x in sel: st.markdown(card(x), unsafe_allow_html=True)
