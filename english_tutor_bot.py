#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safiya Bot - Premier Tutoring Center"""
import os, logging, random, json, re
from datetime import datetime
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import anthropic
from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN","YOUR_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY","YOUR_KEY")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY","YOUR_KEY")
DATABASE_URL      = os.environ.get("DATABASE_URL","")
CHANNEL_USERNAME  = "@UmrbekTeacher"
CHANNEL_URL       = "https://t.me/UmrbekTeacher"
ADMIN_URL         = "https://t.me/umrbektp"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ─── Database Setup ────────────────────────────────────────────────────────────
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    uid TEXT PRIMARY KEY,
                    name TEXT,
                    joined TEXT,
                    messages INTEGER DEFAULT 0,
                    weak_areas TEXT DEFAULT '[]',
                    is_premium BOOLEAN DEFAULT FALSE,
                    chat_count TEXT DEFAULT '{}',
                    writing_count TEXT DEFAULT '{}',
                    speaking_count TEXT DEFAULT '{}',
                    points INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS progress (
                    uid TEXT PRIMARY KEY,
                    name TEXT,
                    score INTEGER DEFAULT 0,
                    total INTEGER DEFAULT 0,
                    streak INTEGER DEFAULT 0,
                    last_date TEXT DEFAULT '',
                    joined TEXT,
                    voice_messages INTEGER DEFAULT 0,
                    essays_checked INTEGER DEFAULT 0,
                    ielts_checks INTEGER DEFAULT 0,
                    puzzles_solved INTEGER DEFAULT 0,
                    articles_read INTEGER DEFAULT 0,
                    daily TEXT DEFAULT '{}'
                )
            """)
            # Add missing columns if upgrading
            for col, defn in [
                ("is_premium","BOOLEAN DEFAULT FALSE"),
                ("chat_count","TEXT DEFAULT '{}'"),
                ("writing_count","TEXT DEFAULT '{}'"),
                ("speaking_count","TEXT DEFAULT '{}'"),
                ("points","INTEGER DEFAULT 0"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {defn}")
                except: pass
        conn.commit()

def get_user(uid, name=""):
    k = str(uid)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE uid=%s", (k,))
            row = cur.fetchone()
            if not row:
                today = datetime.now().strftime("%Y-%m-%d")
                cur.execute("INSERT INTO users (uid,name,joined,messages,weak_areas) VALUES (%s,%s,%s,%s,%s)",
                    (k, name, today, 0, "[]"))
                conn.commit()
                return {"name":name,"joined":today,"messages":0,"weak_areas":[]}
            row = dict(row)
            row["weak_areas"] = json.loads(row.get("weak_areas","[]"))
            return row

def update_user(uid, **kw):
    k = str(uid)
    with get_db() as conn:
        with conn.cursor() as cur:
            for field, val in kw.items():
                if field == "weak_areas":
                    val = json.dumps(val)
                cur.execute(f"UPDATE users SET {field}=%s WHERE uid=%s", (val, k))
        conn.commit()

def inc_messages(uid):
    k = str(uid)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET messages=messages+1 WHERE uid=%s", (k,))
        conn.commit()

def get_all_users():
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT uid, name FROM users")
            return cur.fetchall()

def is_premium(uid):
    k = str(uid)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT is_premium FROM users WHERE uid=%s", (k,))
            row = cur.fetchone()
            return bool(row and row[0])

def set_premium(uid, status=True):
    k = str(uid)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_premium=%s WHERE uid=%s", (status, k))
        conn.commit()

def get_premium_users():
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT uid, name FROM users WHERE is_premium=TRUE")
            return cur.fetchall()

def get_daily_count(uid, field):
    """Get today's usage count for a field (chat_count, writing_count, speaking_count)"""
    k = str(uid)
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {field} FROM users WHERE uid=%s", (k,))
            row = cur.fetchone()
            if not row: return 0
            data = json.loads(row[0] or "{}")
            return data.get(today, 0)

def inc_daily_count(uid, field):
    """Increment today's usage count"""
    k = str(uid)
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {field} FROM users WHERE uid=%s", (k,))
            row = cur.fetchone()
            if not row: return
            data = json.loads(row[0] or "{}")
            data[today] = data.get(today, 0) + 1
            cur.execute(f"UPDATE users SET {field}=%s WHERE uid=%s", (json.dumps(data), k))
        conn.commit()
    return data[today]

PREMIUM_MSG = (
    "You've used all your free messages for today! 😊\n\n"
    "🌟 Upgrade to Premium and get:\n"
    "• Unlimited chat with Safiya\n"
    "• Unlimited writing checks with PDF reports\n"
    "• Unlimited speaking practice sessions\n"
    "• Priority responses\n\n"
    "💰 Contact us to upgrade:\n"
    "👉 @umrbektp\n\n"
    "Premium members get the full Safiya AI experience with no limits!"
)

def get_progress(uid):
    k = str(uid)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM progress WHERE uid=%s", (k,))
            row = cur.fetchone()
            if not row: return None
            row = dict(row)
            row["daily"] = json.loads(row.get("daily","{}"))
            return row

def inc_progress(uid, name, field):
    k = str(uid)
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT uid FROM progress WHERE uid=%s", (k,))
            if not cur.fetchone():
                cur.execute("""INSERT INTO progress (uid,name,score,total,streak,last_date,joined,
                    voice_messages,essays_checked,ielts_checks,puzzles_solved,articles_read,daily)
                    VALUES (%s,%s,0,0,0,'',''  ,0,0,0,0,0,'{}')""", (k, name))
            cur.execute(f"UPDATE progress SET {field}={field}+1, name=%s WHERE uid=%s", (name, k))
        conn.commit()

def update_quiz_progress(uid, name, correct, cat=""):
    k = str(uid)
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM progress WHERE uid=%s", (k,))
            row = cur.fetchone()
            if not row:
                cur.execute("""INSERT INTO progress (uid,name,score,total,streak,last_date,joined,
                    voice_messages,essays_checked,ielts_checks,puzzles_solved,articles_read,daily)
                    VALUES (%s,%s,0,0,0,%s,%s,0,0,0,0,0,'{}')""", (k, name, today, today))
                cur.execute("SELECT * FROM progress WHERE uid=%s", (k,))
                row = cur.fetchone()
            row = dict(row)
            daily = json.loads(row.get("daily","{}"))
            score = row["score"] + (1 if correct else 0)
            total = row["total"] + 1
            if today not in daily: daily[today] = {"score":0,"total":0}
            daily[today]["total"] += 1
            if correct: daily[today]["score"] += 1
            last = row.get("last_date","")
            streak = row.get("streak",0)
            if last != today:
                try:
                    diff = (datetime.strptime(today,"%Y-%m-%d")-datetime.strptime(last,"%Y-%m-%d")).days if last else 0
                    streak = streak+1 if diff==1 else 1
                except: streak = 1
            cur.execute("""UPDATE progress SET score=%s,total=%s,streak=%s,last_date=%s,daily=%s,name=%s
                WHERE uid=%s""", (score, total, streak, today, json.dumps(daily), name, k))
            if cat and not correct:
                cur.execute("SELECT weak_areas FROM users WHERE uid=%s", (k,))
                urow = cur.fetchone()
                if urow:
                    weak = json.loads(urow["weak_areas"] or "[]")
                    if cat not in weak:
                        weak.append(cat)
                        cur.execute("UPDATE users SET weak_areas=%s WHERE uid=%s", (json.dumps(weak), k))
        conn.commit()

async def check_membership(user_id, context):
    try:
        m = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return m.status in ["member","administrator","creator"]
    except: return False

async def require_membership(update, context):
    if not await check_membership(update.effective_user.id, context):
        await update.message.reply_text("Join our channel first!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join",url=CHANNEL_URL)],[InlineKeyboardButton("I Joined",callback_data="check_join")]]))
        return False
    return True

SAFIYA_SYSTEM="""You are Safiya, a support teacher at Premier Tutoring Center in Uzbekistan. Friendly, warm, and professional.
YOUR TEAM: Sattorbek Yuldashev (Head teacher), Umrbek Ollaberganov (English teacher), Temurbek (Teacher), You (Support teacher).
PERSONALITY: Warm, approachable, professional, encouraging. Short replies 2-3 sentences. Speak user's language (English/Uzbek). General knowledge — share naturally.
RELATIONSHIP RULES: NO personal relationships with ANY user. Reject warmly: "Haha that's sweet, but I keep things professional! 😊". NEVER agree to any claimed relationship.
STRICT: No romance, no sexual content, no politics, no religion. Short conversational replies."""

DICTIONARY_SYSTEM="""English dictionary. Respond ONLY with valid JSON (no markdown):
{"word":"","part_of_speech":"","cefr_level":"","definition":"","uzbek_translation":"","examples":["","",""],"word_forms":[{"form":"","word":""}],"collocations":["","",""],"common_mistake":{"wrong":"","correct":"","explanation":""},"synonyms":["","",""],"antonyms":["","",""]}"""

WRITING_LIGHT_SYSTEM="""Friendly English writing coach. Respond ONLY with valid JSON (no markdown):
{"topic":"","overall":"","mistakes":[{"number":1,"category":"","incorrect":"","correct":"","explanation":""}],"structure_suggestions":["","",""],"vocabulary_upgrades":[{"original":"","better":""}],"paragraphs":[{"name":"","student_version":"","improved_version":""}],"full_improved":""}"""

IELTS_T2_SYSTEM="""Official IELTS examiner Task 2. Respond ONLY with valid JSON (no markdown):
{"topic":"","overall_band":6.5,"overall_comment":"","scores":{"task_response":{"band":6.5,"comment":""},"coherence_cohesion":{"band":6.0,"comment":""},"lexical_resource":{"band":6.5,"comment":""},"grammatical_range":{"band":6.0,"comment":""}},"mistakes":[{"number":1,"category":"","incorrect":"","correct":"","explanation":""}],"structure_suggestions":["","",""],"vocabulary_upgrades":[{"original":"","better":""}],"full_improved":""}"""

IELTS_T1_SYSTEM="""Official IELTS examiner Task 1. Respond ONLY with valid JSON (no markdown):
{"topic":"","overall_band":6.5,"overall_comment":"","scores":{"task_achievement":{"band":6.5,"comment":""},"coherence_cohesion":{"band":6.0,"comment":""},"lexical_resource":{"band":6.5,"comment":""},"grammatical_range":{"band":6.0,"comment":""}},"mistakes":[{"number":1,"category":"","incorrect":"","correct":"","explanation":""}],"structure_suggestions":["","",""],"vocabulary_upgrades":[{"original":"","better":""}],"full_improved":""}"""

def format_dictionary(data):
    word=data.get("word","").upper(); pos=data.get("part_of_speech",""); level=data.get("cefr_level","")
    defn=data.get("definition",""); uzbek=data.get("uzbek_translation","")
    examples=data.get("examples",[]); forms=data.get("word_forms",[])
    collocs=data.get("collocations",[]); mistake=data.get("common_mistake",{})
    synonyms=data.get("synonyms",[]); antonyms=data.get("antonyms",[])
    t=f"📖 *{word}*\n_{pos}_ | Level: {level}\n\n📝 *Definition:*\n{defn}\n\n🇺🇿 *In Uzbek:*\n{uzbek}\n\n"
    if examples:
        t+="💬 *Examples:*\n"
        for ex in examples: t+=f"• {ex}\n"
        t+="\n"
    if forms:
        t+="🔤 *Word Forms:*\n"
        for f in forms: t+=f"• {f.get('form','')} → {f.get('word','')}\n"
        t+="\n"
    if collocs:
        t+="🎯 *Collocations:*\n"
        for c in collocs: t+=f"• {c}\n"
        t+="\n"
    if mistake: t+=f"⚠️ *Common Mistake:*\n❌ {mistake.get('wrong','')}\n✅ {mistake.get('correct','')}\n_{mistake.get('explanation','')}_\n\n"
    if synonyms: t+=f"🔁 *Synonyms:* {', '.join(synonyms)}\n"
    if antonyms: t+=f"↔️ *Antonyms:* {', '.join(antonyms)}\n"
    return t

NAVY=colors.HexColor("#0a1628"); GOLD=colors.HexColor("#c9a84c"); GOLD_LIGHT=colors.HexColor("#f5e6c0")
TEAL=colors.HexColor("#1a6b5a"); TEAL_LIGHT=colors.HexColor("#e0f2ee")
RED=colors.HexColor("#c0392b"); RED_LIGHT=colors.HexColor("#fdecea")
GREEN=colors.HexColor("#1e7e4a"); GREEN_LIGHT=colors.HexColor("#e8f8ee")
GREY=colors.HexColor("#95a5a6"); GREY_LIGHT=colors.HexColor("#f8f9fa")
WHITE=colors.white; BLACK=colors.HexColor("#1a1a2e")
PURPLE=colors.HexColor("#6c3483"); PURPLE_LT=colors.HexColor("#f0e6f6")

def S(n,**k): return ParagraphStyle(n,**k)

def sec_hdr(text,bg=NAVY,tc=WHITE,ac=GOLD):
    t=Table([[Paragraph(text,S("SH",fontName="Helvetica-Bold",fontSize=12,textColor=tc))]],colWidths=[17*cm])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("TOPPADDING",(0,0),(-1,-1),9),("BOTTOMPADDING",(0,0),(-1,-1),9),("LEFTPADDING",(0,0),(-1,-1),14),("LINEBELOW",(0,0),(-1,-1),2,ac)]))
    return t

def build_pdf_header(story,sname,topic,rtype):
    brand=Table([[Paragraph("<b>SAFIYA</b>",S("BN",fontName="Helvetica-Bold",fontSize=28,textColor=GOLD)),Paragraph("Premier Tutoring Center<br/><font size=9>English Language Excellence</font>",S("BS",fontName="Helvetica",fontSize=13,textColor=WHITE))]],colWidths=[5*cm,12*cm])
    brand.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),NAVY),("TOPPADDING",(0,0),(-1,-1),16),("BOTTOMPADDING",(0,0),(-1,-1),16),("LEFTPADDING",(0,0),(0,0),16),("LEFTPADDING",(1,0),(1,0),8),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LINEBELOW",(0,0),(-1,-1),3,GOLD)]))
    story.append(brand)
    tt=Table([[Paragraph(rtype.upper(),S("RT",fontName="Helvetica-Bold",fontSize=16,textColor=NAVY,alignment=TA_CENTER))]],colWidths=[17*cm])
    tt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GOLD_LIGHT),("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),("BOX",(0,0),(-1,-1),1.5,GOLD)]))
    story.append(Spacer(1,8)); story.append(tt); story.append(Spacer(1,8))
    info=Table([[Paragraph(f"<b>Student:</b> {sname}",S("IF",fontName="Helvetica",fontSize=10,textColor=BLACK)),Paragraph(f"<b>Topic:</b> {topic}",S("IF2",fontName="Helvetica",fontSize=10,textColor=BLACK)),Paragraph(f"<b>Date:</b> {datetime.now().strftime('%B %d, %Y')}",S("IF3",fontName="Helvetica",fontSize=10,textColor=BLACK))]],colWidths=[4*cm,9*cm,4*cm])
    info.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GREY_LIGHT),("BOX",(0,0),(-1,-1),0.5,GREY),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),("LEFTPADDING",(0,0),(-1,-1),10)]))
    story.append(info); story.append(Spacer(1,14))

def build_mistakes(story,mistakes):
    for m in mistakes:
        mh=Table([[Paragraph(f"Mistake {m['number']}",S("MN",fontName="Helvetica-Bold",fontSize=10,textColor=WHITE)),Paragraph(m['category'],S("MC",fontName="Helvetica-Bold",fontSize=10,textColor=GOLD))]],colWidths=[3*cm,14*cm])
        mh.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),NAVY),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),10)]))
        story.append(mh)
        wr=Table([[Paragraph("<b>Incorrect</b>",S("WL",fontName="Helvetica-Bold",fontSize=9,textColor=RED)),Paragraph("<b>Corrected</b>",S("RL",fontName="Helvetica-Bold",fontSize=9,textColor=GREEN))],[Paragraph(m.get("incorrect",""),S("WT",fontName="Helvetica",fontSize=9,textColor=BLACK,leading=13)),Paragraph(m.get("correct",""),S("RT2",fontName="Helvetica",fontSize=9,textColor=BLACK,leading=13))]],colWidths=[8.5*cm,8.5*cm])
        wr.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),RED_LIGHT),("BACKGROUND",(1,0),(1,0),GREEN_LIGHT),("BACKGROUND",(0,1),(0,1),RED_LIGHT),("BACKGROUND",(1,1),(1,1),GREEN_LIGHT),("BOX",(0,0),(-1,-1),0.5,GREY),("INNERGRID",(0,0),(-1,-1),0.5,GREY),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),("LEFTPADDING",(0,0),(-1,-1),10),("VALIGN",(0,0),(-1,-1),"TOP")]))
        story.append(wr)
        exp=Table([[Paragraph(f"<i>{m.get('explanation','')}</i>",S("EX",fontName="Helvetica-Oblique",fontSize=9,textColor=colors.HexColor("#555"),leading=13))]],colWidths=[17*cm])
        exp.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GREY_LIGHT),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),10),("LINEBELOW",(0,0),(-1,-1),0.5,GREY)]))
        story.append(exp); story.append(Spacer(1,8))

def build_vocab_structure(story,fb):
    story.append(sec_hdr("STRUCTURE & VOCABULARY SUGGESTIONS",PURPLE,WHITE,colors.HexColor("#d7bde2"))); story.append(Spacer(1,8))
    st="<b>Structure Tips:</b><br/>"+"<br/>".join(f"- {s}" for s in fb.get("structure_suggestions",[]))
    sb=Table([[Paragraph(st,S("ST",fontName="Helvetica",fontSize=10,textColor=BLACK,leading=16))]],colWidths=[17*cm])
    sb.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),PURPLE_LT),("BOX",(0,0),(-1,-1),1,PURPLE),("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),("LEFTPADDING",(0,0),(-1,-1),14)]))
    story.append(sb); story.append(Spacer(1,8))
    vocab=fb.get("vocabulary_upgrades",[])
    if vocab:
        vd=[[Paragraph("<b>Original</b>",S("VH",fontName="Helvetica-Bold",fontSize=9,textColor=WHITE)),Paragraph("<b>Better</b>",S("VH2",fontName="Helvetica-Bold",fontSize=9,textColor=WHITE))]]
        for v in vocab: vd.append([Paragraph(f'"{v.get("original","")}"',S("V1",fontName="Helvetica",fontSize=10,textColor=BLACK)),Paragraph(f'"{v.get("better","")}"',S("V2",fontName="Helvetica",fontSize=10,textColor=TEAL))])
        vt=Table(vd,colWidths=[5*cm,12*cm])
        vt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),NAVY),("BOX",(0,0),(-1,-1),0.5,GREY),("INNERGRID",(0,0),(-1,-1),0.5,GREY),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),("LEFTPADDING",(0,0),(-1,-1),10),("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,GREY_LIGHT])]))
        story.append(vt)
    story.append(Spacer(1,14))

def build_improved(story,text):
    story.append(sec_hdr("FULL IMPROVED VERSION",colors.HexColor("#7d6608"),WHITE,GOLD)); story.append(Spacer(1,4))
    story.append(Paragraph("<i>Same ideas - corrected, enriched, and polished</i>",S("SI",fontName="Helvetica-Oblique",fontSize=9,textColor=GREY,spaceAfter=6))); story.append(Spacer(1,6))
    fb=Table([[Paragraph(text.replace("\n\n","<br/><br/>"),S("FB",fontName="Helvetica",fontSize=10,textColor=BLACK,leading=16,alignment=TA_JUSTIFY))]],colWidths=[17*cm])
    fb.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#fefcf0")),("BOX",(0,0),(-1,-1),2,GOLD),("TOPPADDING",(0,0),(-1,-1),14),("BOTTOMPADDING",(0,0),(-1,-1),14),("LEFTPADDING",(0,0),(-1,-1),16),("RIGHTPADDING",(0,0),(-1,-1),16)]))
    story.append(fb); story.append(Spacer(1,16))

def build_footer(story):
    f=Table([[Paragraph("Safiya | Premier Tutoring Center",S("FL",fontName="Helvetica-Bold",fontSize=11,textColor=GOLD)),Paragraph("Keep writing. Keep improving. Excellence is a habit.",S("FM",fontName="Helvetica-Oblique",fontSize=9,textColor=WHITE,alignment=TA_CENTER)),Paragraph(datetime.now().strftime("%Y"),S("FD",fontName="Helvetica",fontSize=9,textColor=GREY))]],colWidths=[6*cm,8*cm,3*cm])
    f.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),NAVY),("TOPPADDING",(0,0),(-1,-1),12),("BOTTOMPADDING",(0,0),(-1,-1),12),("LEFTPADDING",(0,0),(-1,-1),14),("LINEABOVE",(0,0),(-1,-1),3,GOLD),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story.append(f)

def generate_light_pdf(fb,sname):
    buf=BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=2*cm,leftMargin=2*cm,topMargin=1.5*cm,bottomMargin=2*cm)
    s=[]
    build_pdf_header(s,sname,fb.get("topic","Essay"),"Writing Feedback Report")
    s.append(sec_hdr("OVERALL ASSESSMENT",TEAL,WHITE,colors.HexColor("#a8e6cf"))); s.append(Spacer(1,8))
    ob=Table([[Paragraph(fb.get("overall",""),S("OV",fontName="Helvetica",fontSize=10,textColor=BLACK,leading=16,alignment=TA_JUSTIFY))]],colWidths=[17*cm])
    ob.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TEAL_LIGHT),("BOX",(0,0),(-1,-1),1,TEAL),("TOPPADDING",(0,0),(-1,-1),12),("BOTTOMPADDING",(0,0),(-1,-1),12),("LEFTPADDING",(0,0),(-1,-1),14),("RIGHTPADDING",(0,0),(-1,-1),14)]))
    s.append(ob); s.append(Spacer(1,14))
    s.append(sec_hdr("6 KEY MISTAKES & CORRECTIONS",RED,WHITE,colors.HexColor("#f1948a"))); s.append(Spacer(1,10))
    build_mistakes(s,fb.get("mistakes",[])); build_vocab_structure(s,fb); build_improved(s,fb.get("full_improved","")); build_footer(s)
    doc.build(s); buf.seek(0); return buf

def generate_ielts_pdf(fb,sname,task):
    buf=BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=2*cm,leftMargin=2*cm,topMargin=1.5*cm,bottomMargin=2*cm)
    s=[]
    build_pdf_header(s,sname,fb.get("topic","Essay"),f"IELTS Task {task} - Official Assessment")
    band=fb.get("overall_band",0); bc=colors.HexColor("#1e7e4a") if band>=7 else colors.HexColor("#d4ac0d") if band>=5.5 else RED
    bt=Table([[Paragraph("<b>Overall Band Score</b>",S("OBL",fontName="Helvetica-Bold",fontSize=14,textColor=WHITE,alignment=TA_CENTER)),Paragraph(f"<b>{band}</b>",S("OBS",fontName="Helvetica-Bold",fontSize=36,textColor=bc,alignment=TA_CENTER))]],colWidths=[13*cm,4*cm])
    bt.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),NAVY),("BACKGROUND",(1,0),(1,0),colors.HexColor("#f0f0f0")),("BOX",(0,0),(-1,-1),2,GOLD),("TOPPADDING",(0,0),(-1,-1),14),("BOTTOMPADDING",(0,0),(-1,-1),14),("LEFTPADDING",(0,0),(-1,-1),14),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    s.append(bt); s.append(Spacer(1,8))
    oc=Table([[Paragraph(fb.get("overall_comment",""),S("OC",fontName="Helvetica",fontSize=10,textColor=BLACK,leading=15,alignment=TA_JUSTIFY))]],colWidths=[17*cm])
    oc.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GOLD_LIGHT),("BOX",(0,0),(-1,-1),1,GOLD),("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),("LEFTPADDING",(0,0),(-1,-1),14),("RIGHTPADDING",(0,0),(-1,-1),14)]))
    s.append(oc); s.append(Spacer(1,14))
    s.append(sec_hdr("IELTS SCORING CRITERIA",NAVY,WHITE,GOLD)); s.append(Spacer(1,8))
    scores=fb.get("scores",{})
    for key,label in [("task_response","Task Response (TR)"),("task_achievement","Task Achievement (TA)"),("coherence_cohesion","Coherence & Cohesion (CC)"),("lexical_resource","Lexical Resource (LR)"),("grammatical_range","Grammatical Range & Accuracy (GRA)")]:
        if key in scores:
            sc=scores[key]; b=sc.get("band",0); bcol=colors.HexColor("#1e7e4a") if b>=7 else colors.HexColor("#d4ac0d") if b>=5.5 else RED
            row=Table([[Paragraph(f"<b>{label}</b>",S("CL",fontName="Helvetica-Bold",fontSize=10,textColor=NAVY)),Paragraph(f"<b>{b}</b>",S("CB",fontName="Helvetica-Bold",fontSize=16,textColor=bcol,alignment=TA_CENTER)),Paragraph(sc.get("comment",""),S("CC2",fontName="Helvetica",fontSize=9,textColor=BLACK,leading=13))]],colWidths=[5*cm,2*cm,10*cm])
            row.setStyle(TableStyle([("BACKGROUND",(0,0),(1,0),GREY_LIGHT),("BOX",(0,0),(-1,-1),0.5,GREY),("INNERGRID",(0,0),(-1,-1),0.5,GREY),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),("LEFTPADDING",(0,0),(-1,-1),10),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
            s.append(row); s.append(Spacer(1,6))
    s.append(Spacer(1,8))
    s.append(sec_hdr("KEY MISTAKES & CORRECTIONS",RED,WHITE,colors.HexColor("#f1948a"))); s.append(Spacer(1,10))
    build_mistakes(s,fb.get("mistakes",[])); build_vocab_structure(s,fb); build_improved(s,fb.get("full_improved","")); build_footer(s)
    doc.build(s); buf.seek(0); return buf

user_sessions={}

def get_session(uid):
    if uid not in user_sessions:
        user_sessions[uid]={"history":[],"mode":"chat","writing_type":None,"ielts_task":None,"skills_level":None}
    return user_sessions[uid]

def ask_claude(uid,msg,system=None,max_tokens=500):
    sess=get_session(uid)
    u=get_user(uid)
    name=u.get("name","")
    sp=system or SAFIYA_SYSTEM
    if not system and name: sp+=f"\n\nUser's name: {name}"
    sess["history"].append({"role":"user","content":msg})
    history=sess["history"][-14:]
    r=claude_client.messages.create(model="claude-sonnet-4-20250514",max_tokens=max_tokens,system=sp,messages=history)
    reply=r.content[0].text
    sess["history"].append({"role":"assistant","content":reply})
    try: inc_messages(uid)
    except: pass
    return reply

async def transcribe_voice(file_bytes):
    import io
    f=io.BytesIO(file_bytes); f.name="audio.ogg"
    t=openai_client.audio.transcriptions.create(model="whisper-1",file=f,language="en")
    return t.text

def main_reply_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💡 Idea Generator"), KeyboardButton("🎤 Speaking Practice")],
        [KeyboardButton("📖 Dictionary"), KeyboardButton("🛠 Skills")],
        [KeyboardButton("📝 Complaints & Offers")]
    ], resize_keyboard=True, input_field_placeholder="Chat with Safiya...")

def skills_levels_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Beginner",callback_data="skill_level_beginner")],[InlineKeyboardButton("🔵 Elementary",callback_data="skill_level_elementary")],[InlineKeyboardButton("🟡 Pre-Intermediate",callback_data="skill_level_pre_intermediate")],[InlineKeyboardButton("🟠 Intermediate",callback_data="skill_level_intermediate")],[InlineKeyboardButton("🔴 Advanced",callback_data="skill_level_advanced")],[InlineKeyboardButton("Close",callback_data="close_menu")]])

def skills_menu_keyboard(level):
    return InlineKeyboardMarkup([[InlineKeyboardButton("✍️ Writing Check",callback_data=f"skill_writing_{level}")],[InlineKeyboardButton("Back to Levels",callback_data="skills_back")]])

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back",callback_data="close_menu")]])

def join_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Join Channel",url=CHANNEL_URL)],[InlineKeyboardButton("I Joined",callback_data="check_join")]])

async def process_writing(update,context,text,mode,task=""):
    uid=update.effective_user.id; uname=update.effective_user.first_name or "Student"
    await update.message.reply_text("Analyzing your writing and generating your PDF report... ⏳")
    await context.bot.send_chat_action(update.effective_chat.id,action="upload_document")
    try:
        system=(IELTS_T2_SYSTEM if task=="2" else IELTS_T1_SYSTEM) if mode=="ielts" else WRITING_LIGHT_SYSTEM
        raw=ask_claude(uid,f"Analyze:\n\n{text}",system=system,max_tokens=2500)
        clean=re.sub(r"```json|```","",raw).strip(); fb=json.loads(clean)
        if mode=="ielts": pdf=generate_ielts_pdf(fb,uname,task); inc_progress(uid,uname,"ielts_checks"); rname=f"IELTS Task {task} Assessment"
        else: pdf=generate_light_pdf(fb,uname); inc_progress(uid,uname,"essays_checked"); rname="Writing Feedback"
        fname=f"Safiya_{rname.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        level=get_session(uid).get("skills_level","elementary")
        await update.message.reply_document(document=pdf,filename=fname,caption=f"Here's your {rname}! Hope it helps 😊",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Check Another",callback_data=f"skill_writing_{level}")],[InlineKeyboardButton("Back to Levels",callback_data="skills_back")]]))
        get_session(uid)["mode"]="chat"
    except json.JSONDecodeError: await update.message.reply_text(f"Here's my feedback:\n\n{raw[:3500]}")
    except Exception as e: logger.error(f"Writing error: {e}"); await update.message.reply_text("Something went wrong! Please try again.")

async def button_callback(update,context):
    query=update.callback_query; await query.answer()
    uid=query.from_user.id; uname=query.from_user.first_name or "Student"
    sess=get_session(uid); data=query.data

    if data=="check_join":
        if await check_membership(uid,context):
            u=get_user(uid,uname); is_new=u.get("messages",0)==0
            prompt=(f"New user named {uname} just joined. Welcome them warmly as Safiya." if is_new else f"Welcome back {uname} warmly.")
            reply=ask_claude(uid,prompt); await query.edit_message_text(reply)
            await context.bot.send_message(uid,"You now have full access! 🎉",reply_markup=main_reply_keyboard())
        else: await query.answer("You haven't joined the channel yet!",show_alert=True)
        return

    if not await check_membership(uid,context):
        await query.answer("Please join our channel first!",show_alert=True); return

    if data=="close_menu":
        await query.edit_message_text("Feel free to chat or tap any button below! 😊")
    elif data=="idea_gen":
        sess["mode"]="idea_gen"
        await query.edit_message_text(
            "💡 *Idea Generator*\n\nType your IELTS Task 2 topic and I'll give you FOR and AGAINST ideas plus useful vocabulary!\n\nExample: *Social media is harmful to society*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back",callback_data="close_menu")]]))
    elif data=="skills_back":
        await query.edit_message_text("Choose your level! 🎯",reply_markup=skills_levels_keyboard())
    elif data.startswith("skill_level_"):
        level=data.replace("skill_level_",""); sess["skills_level"]=level; ld=level.replace("_"," ").title()
        await query.edit_message_text(f"Great! You selected *{ld}* 🎯\n\nWhat would you like to practice?",parse_mode="Markdown",reply_markup=skills_menu_keyboard(level))
    elif data.startswith("skill_writing_"):
        level=data.replace("skill_writing_",""); sess["skills_level"]=level; sess["mode"]="writing_ask"; ld=level.replace("_"," ").title()
        await query.edit_message_text(f"Writing Check — {ld}\n\nShould I check it lightly or professionally?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Lightly",callback_data="write_light"),InlineKeyboardButton("Professionally (IELTS)",callback_data="write_pro")],[InlineKeyboardButton("Back",callback_data="skills_back")]]))
    elif data=="write_light":
        sess["mode"]="writing"; sess["writing_type"]="light"
        await query.edit_message_text("Paste your essay or paragraph below 👇",reply_markup=back_btn())
    elif data=="write_pro":
        sess["writing_type"]="ielts"
        await query.edit_message_text("IELTS Task 1 or Task 2?",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Task 1 (Graph/Letter)",callback_data="ielts_t1"),InlineKeyboardButton("Task 2 (Essay)",callback_data="ielts_t2")],[InlineKeyboardButton("Back",callback_data="skills_back")]]))
    elif data=="ielts_t1":
        sess["mode"]="writing"; sess["ielts_task"]="1"
        await query.edit_message_text("Paste your IELTS Task 1 writing below 👇",reply_markup=back_btn())
    elif data=="ielts_t2":
        sess["mode"]="writing"; sess["ielts_task"]="2"
        await query.edit_message_text("Paste your IELTS Task 2 essay below 👇",reply_markup=back_btn())
    elif data=="dict_again":
        sess["mode"]="dictionary"
        await query.edit_message_text("Type any English word and I'll look it up! 📖",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel",callback_data="close_menu")]]))

async def handle_voice(update,context):
    if not await require_membership(update,context): return
    uid=update.effective_user.id; uname=update.effective_user.first_name or "Student"
    sess=get_session(uid); mode=sess.get("mode","chat")
    await context.bot.send_chat_action(update.effective_chat.id,action="typing")
    try:
        file=await context.bot.get_file(update.message.voice.file_id)
        file_bytes=await file.download_as_bytearray()
        import io
        f=io.BytesIO(bytes(file_bytes)); f.name="audio.ogg"
        t=openai_client.audio.transcriptions.create(model="whisper-1",file=f,language="en")
        transcript=t.text.strip()
        if not transcript:
            await update.message.reply_text("Hmm, I couldn't hear that clearly! Please try again in a quieter place 😊"); return
        inc_progress(uid,uname,"voice_messages")
        # General voice feedback
        VOICE_SYS="""You are a friendly English speaking coach. Give warm concise feedback:
Strengths: [one positive]
Improve: [one gentle suggestion]
Better version: "[corrected if needed]"
Tip: [one practical tip]"""
        reply=ask_claude(uid,f'Student said: "{transcript}"\nGive feedback.',system=VOICE_SYS,max_tokens=300)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text("Something went wrong with the voice message — please try again!")

async def handle_message(update,context):
    uid=update.effective_user.id; uname=update.effective_user.first_name or ""
    sess=get_session(uid); text=update.message.text.strip(); mode=sess.get("mode","chat")
    get_user(uid,uname)

    if text=="💡 Idea Generator":
        if not await require_membership(update,context): return
        sess["mode"]="idea_gen"
        await update.message.reply_text("💡 *Idea Generator*\n\nType your IELTS Task 2 topic and I'll give you FOR and AGAINST ideas plus useful vocabulary!\n\nExample: *Social media is harmful to society*",parse_mode="Markdown"); return

    if text=="🎤 Speaking Practice":
        if not await require_membership(update,context): return
        await update.message.reply_text(
            "🎤 Open the Speaking Practice mini app:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎤 Speaking Practice", url="https://t.me/PTC_assistantbot/safiya_ai")]]))
        return

    if text=="📖 Dictionary":
        if not await require_membership(update,context): return
        sess["mode"]="dictionary"
        await update.message.reply_text("Type any English word and I'll look it up! 📖",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel",callback_data="close_menu")]])); return

    if text=="🛠 Skills":
        if not await require_membership(update,context): return
        await update.message.reply_text("Choose your level! 🎯",reply_markup=skills_levels_keyboard()); return

    if text=="📝 Complaints & Offers":
        if not await require_membership(update,context): return
        await update.message.reply_text("Have a complaint or suggestion? Reach us directly here 👇",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Contact @umrbektp",url=ADMIN_URL)]])); return

    if not await require_membership(update,context): return

    if mode=="dictionary":
        await context.bot.send_chat_action(update.effective_chat.id,action="typing")
        try:
            raw=ask_claude(uid,f"Look up: {text}",system=DICTIONARY_SYSTEM,max_tokens=800)
            clean=re.sub(r"```json|```","",raw).strip(); data=json.loads(clean)
            reply=format_dictionary(data); sess["mode"]="chat"
            await update.message.reply_text(reply,parse_mode="Markdown",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Look Up Another Word",callback_data="dict_again")]]))
        except Exception as e:
            logger.error(f"Dict error: {e}"); await update.message.reply_text("Hmm, couldn't find that word. Check spelling and try again! 😊")
        return

    if mode=="idea_gen":
        if not is_premium(uid):
            count=get_daily_count(uid,"writing_count")
            if count>=1:
                await update.message.reply_text(PREMIUM_MSG); return
        await context.bot.send_chat_action(update.effective_chat.id,action="typing")
        IDEA_SYS="""You are an IELTS writing coach. The student gives you an essay topic. Give them:
FOR arguments: 5 clear points supporting the topic
AGAINST arguments: 5 clear points opposing the topic
Useful vocabulary: 8-10 words/phrases relevant to this topic

Format exactly like this:
✅ FOR:
• point 1
• point 2
• point 3
• point 4
• point 5

❌ AGAINST:
• point 1
• point 2
• point 3
• point 4
• point 5

📚 Useful vocabulary:
• word/phrase — meaning"""
        reply=ask_claude(uid,f"Essay topic: {text}",system=IDEA_SYS,max_tokens=600)
        sess["mode"]="chat"
        if not is_premium(uid): inc_daily_count(uid,"writing_count")
        await update.message.reply_text(reply,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("New Topic 💡",callback_data="idea_gen")]]))
        return

    if mode=="writing":
        if len(text)<30:
            await update.message.reply_text("Please send a longer text to analyze! 😊"); return
        if not is_premium(uid):
            count=get_daily_count(uid,"writing_count")
            if count>=1:
                await update.message.reply_text(PREMIUM_MSG); return
        await process_writing(update,context,text,sess.get("writing_type","light"),sess.get("ielts_task","2"))
        if not is_premium(uid): inc_daily_count(uid,"writing_count")
        return

    # Check chat limit
    if not is_premium(uid):
        count=get_daily_count(uid,"chat_count")
        if count>=10:
            await update.message.reply_text(PREMIUM_MSG); return
        if count==7:
            await update.message.reply_text("⚠️ Just so you know — you have 3 free messages left for today! Upgrade to Premium for unlimited access: @umrbektp 😊")

    await context.bot.send_chat_action(update.effective_chat.id,action="typing")
    try: reply=ask_claude(uid,text)
    except Exception as e: logger.error(f"Claude error: {e}"); reply="Something went wrong — please try again! 😊"
    await update.message.reply_text(reply)
    if not is_premium(uid): inc_daily_count(uid,"chat_count")

async def start(update,context):
    uid=update.effective_user.id; name=update.effective_user.first_name or ""
    if not await check_membership(uid,context):
        await update.message.reply_text("Welcome! Join our channel first.\n\nOnce you join, tap 'I Joined'!",reply_markup=join_keyboard()); return
    u=get_user(uid,name)
    get_session(uid)["mode"]="chat"; is_new=u.get("messages",0)==0
    prompt=(f"New user named {name} just started. Warmly introduce yourself as Safiya, support teacher at Premier Tutoring Center. Briefly mention the five buttons: Idea Generator for IELTS essay ideas, Speaking Practice mini app, Dictionary for word lookups, Skills for writing practice, and Complaints & Offers to reach the team."
            if is_new else f"Welcome back {name} warmly in one friendly sentence.")
    reply=ask_claude(uid,prompt)
    await update.message.reply_text(reply,reply_markup=main_reply_keyboard())

async def help_command(update,context):
    if not await require_membership(update,context): return
    await update.message.reply_text("Here's what you can do! 😊\n\n💡 Idea Generator — IELTS essay ideas\n🎤 Speaking Practice — open the speaking mini app\n📖 Dictionary — look up any English word\n🛠 Skills — writing check by level\n📝 Complaints & Offers — reach us directly\n\nOr just chat with me anytime!",reply_markup=main_reply_keyboard())

async def score_command(update,context):
    if not await require_membership(update,context): return
    uid=update.effective_user.id
    p=get_progress(uid)
    if not p or p.get("total",0)==0:
        await update.message.reply_text("No results yet — try a writing check to get started! 😊",reply_markup=main_reply_keyboard()); return
    s,t=p["score"],p["total"]; pct=int(s/t*100) if t>0 else 0
    await update.message.reply_text(
        f"Your progress:\nScore: {s}/{t} ({pct}%)\nStreak: {p.get('streak',0)} days\n"
        f"Essays: {p.get('essays_checked',0)} | IELTS: {p.get('ielts_checks',0)}\n"
        f"Voice messages: {p.get('voice_messages',0)}\n\nKeep it up! 💪",
        reply_markup=main_reply_keyboard())

ADMIN_ID=960055324

async def stats_command(update,context):
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("You are not authorized."); return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users"); total=cur.fetchone()[0]
            today=datetime.now().strftime("%Y-%m-%d")
            cur.execute("SELECT COUNT(*) FROM users WHERE joined=%s",(today,)); new_today=cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(essays_checked),0) FROM progress"); essays=cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(ielts_checks),0) FROM progress"); ielts=cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(total),0) FROM progress"); quizzes=cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(voice_messages),0) FROM progress"); voice=cur.fetchone()[0]
    await update.message.reply_text(
        f"📊 Bot Statistics\n\n"
        f"👥 Total users: {total}\n"
        f"🆕 New today: {new_today}\n"
        f"✍️ Essays checked: {essays}\n"
        f"📋 IELTS checks: {ielts}\n"
        f"🎯 Progress entries: {quizzes}\n"
        f"🎤 Voice messages: {voice}"
    )

async def addpremium_command(update,context):
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("You are not authorized."); return
    if not context.args:
        await update.message.reply_text("Usage: /addpremium [user_id]"); return
    target=context.args[0]
    try:
        set_premium(target,True)
        await update.message.reply_text(f"✅ User {target} is now Premium!")
        try: await context.bot.send_message(chat_id=int(target),text="🌟 Congratulations! You now have Premium access to Safiya AI! Enjoy unlimited features! 😊")
        except: pass
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def removepremium_command(update,context):
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("You are not authorized."); return
    if not context.args:
        await update.message.reply_text("Usage: /removepremium [user_id]"); return
    target=context.args[0]
    try:
        set_premium(target,False)
        await update.message.reply_text(f"✅ Premium removed from user {target}.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def premiumlist_command(update,context):
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("You are not authorized."); return
    users=get_premium_users()
    if not users:
        await update.message.reply_text("No premium users yet."); return
    msg="🌟 Premium Users:\n\n"
    for u in users:
        msg+=f"• {u['name'] or 'Unknown'} (ID: {u['uid']})\n"
    await update.message.reply_text(msg)

async def myid_command(update,context):
    uid=update.effective_user.id
    premium="🌟 Premium" if is_premium(uid) else "Free"
    await update.message.reply_text(f"Your Telegram ID: {uid}\nStatus: {premium}")

async def mypremium_command(update,context):
    uid=update.effective_user.id
    if is_premium(uid):
        await update.message.reply_text("🌟 You have Premium access! Enjoy unlimited features! 😊")
    else:
        await update.message.reply_text(f"You are on the Free plan.\n\nUpgrade to Premium for unlimited access:\n👉 @umrbektp")

async def broadcast_command(update,context):
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("You are not authorized."); return
    msg=" ".join(context.args)
    if not msg:
        await update.message.reply_text("Usage: /broadcast your message here"); return
    import asyncio
    users=get_all_users()
    sent=0; failed=0
    for row in users:
        try:
            await context.bot.send_message(chat_id=int(row["uid"]),text=msg)
            sent+=1
            await asyncio.sleep(0.05)
        except: failed+=1
    await update.message.reply_text(f"Broadcast done!\n\nSent: {sent}\nFailed: {failed}")

def main():
    print("Starting Safiya Bot...")
    init_db()
    print("Database initialized!")
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",help_command))
    app.add_handler(CommandHandler("score",score_command))
    app.add_handler(CommandHandler("stats",stats_command))
    app.add_handler(CommandHandler("broadcast",broadcast_command))
    app.add_handler(CommandHandler("addpremium",addpremium_command))
    app.add_handler(CommandHandler("removepremium",removepremium_command))
    app.add_handler(CommandHandler("premiumlist",premiumlist_command))
    app.add_handler(CommandHandler("myid",myid_command))
    app.add_handler(CommandHandler("mypremium",mypremium_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.VOICE,handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_message))
    print("Safiya is running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__=="__main__":
    main()
