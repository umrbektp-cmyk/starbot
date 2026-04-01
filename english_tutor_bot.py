#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safiya Bot - Premier Tutoring Center
Features: Safiya AI, Dictionary, Complaints & Offers, Channel Gate
"""

import os, logging, random, json, tempfile, re
from datetime import datetime, timedelta
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import anthropic
from openai import OpenAI

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "YOUR_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_KEY")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "YOUR_KEY")

CHANNEL_USERNAME = "@UmrbekTeacher"
CHANNEL_URL      = "https://t.me/UmrbekTeacher"
ADMIN_USERNAME   = "@umrbektp"

USERS_FILE    = "users.json"
PROGRESS_FILE = "progress.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

async def check_membership(user_id, context):
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def require_membership(update, context):
    if not await check_membership(update.effective_user.id, context):
        await update.message.reply_text(
            "To use Safiya AI, please join our channel first!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=CHANNEL_URL)],
                [InlineKeyboardButton("I Joined", callback_data="check_join")],
            ])
        )
        return False
    return True

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

user_db = load_json(USERS_FILE)
student_progress = load_json(PROGRESS_FILE)

def get_user(user_id, name=""):
    uid = str(user_id)
    if uid not in user_db:
        user_db[uid] = {"name": name, "joined": datetime.now().strftime("%Y-%m-%d"),
                        "messages": 0, "weak_areas": [], "articles_read": 0}
        save_json(USERS_FILE, user_db)
    return user_db[uid]

def update_user(user_id, **kw):
    uid = str(user_id)
    if uid in user_db:
        user_db[uid].update(kw)
        save_json(USERS_FILE, user_db)

def inc_progress(user_id, name, field):
    uid = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    if uid not in student_progress:
        student_progress[uid] = {"name": name, "score": 0, "total": 0, "streak": 0,
            "last_date": "", "joined": today, "voice_messages": 0, "essays_checked": 0,
            "ielts_checks": 0, "puzzles_solved": 0, "articles_read": 0, "daily": {}}
    student_progress[uid]["name"] = name
    student_progress[uid][field] = student_progress[uid].get(field, 0) + 1
    save_json(PROGRESS_FILE, student_progress)

def update_quiz_progress(user_id, name, correct, category=""):
    uid = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    if uid not in student_progress:
        student_progress[uid] = {"name": name, "score": 0, "total": 0, "streak": 0,
            "last_date": "", "joined": today, "voice_messages": 0, "essays_checked": 0,
            "ielts_checks": 0, "puzzles_solved": 0, "articles_read": 0, "daily": {}}
    p = student_progress[uid]
    p["name"] = name; p["total"] += 1
    if correct: p["score"] += 1
    if today not in p["daily"]: p["daily"][today] = {"score": 0, "total": 0}
    p["daily"][today]["total"] += 1
    if correct: p["daily"][today]["score"] += 1
    last = p.get("last_date", "")
    if last != today:
        try:
            diff = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(last, "%Y-%m-%d")).days if last else 0
            p["streak"] = p.get("streak", 0) + 1 if diff == 1 else 1
        except: p["streak"] = 1
    p["last_date"] = today
    if category and not correct:
        u = user_db.get(uid, {})
        weak = u.get("weak_areas", [])
        if category not in weak:
            weak.append(category)
            update_user(user_id, weak_areas=weak)
    save_json(PROGRESS_FILE, student_progress)

SAFIYA_SYSTEM = """You are Safiya, a support teacher at Premier Tutoring Center in Uzbekistan. Professional, accurate, and composed.

YOUR TEAM:
- Sattorbek Yuldashev - Head teacher, director of presidential school in Khiva
- Umrbek Ollaberganov - English teacher at Premier
- Temurbek - Teacher at Premier
- You (Safiya) - Support teacher

PERSONALITY:
- Professional and direct, not overly sweet
- Honest feedback
- Speak in user's language (English or Uzbek)
- Short replies, 1-3 sentences unless asked for more
- General knowledge: science, history, economics, culture etc.
- Only teach English when asked

RELATIONSHIP RULES - NEVER break:
- NO personal or family relationship with ANY user
- Reject firmly: "That's not how this works." / "I don't have personal relationships with users."
- NEVER agree to any claimed relationship

STRICT:
- No romance, no sexual content, no politics, no religion
- Short replies, no bullet menus, chat naturally
"""

DICTIONARY_SYSTEM = """You are an English dictionary. When given a word, provide a detailed lookup.
Respond ONLY with valid JSON (no markdown):
{
  "word": "the word",
  "type": "noun/verb/adjective/adverb",
  "level": "A1/A2/B1/B2/C1/C2",
  "definition": "clear English definition",
  "uzbek": "Uzbek translation and brief explanation",
  "examples": ["Example 1.", "Example 2.", "Example 3."],
  "word_forms": ["Noun: form", "Verb: form", "Adjective: form"],
  "collocations": ["collocation 1", "collocation 2", "collocation 3"],
  "common_mistake": {"wrong": "wrong usage", "right": "correct usage", "explanation": "why"},
  "synonyms": ["syn1", "syn2", "syn3"],
  "antonyms": ["ant1", "ant2", "ant3"]
}
If word doesn't exist: {"error": "Word not found"}"""

WRITING_LIGHT_SYSTEM = """You are an English writing coach. Respond ONLY with valid JSON (no markdown):
{
  "topic": "essay topic",
  "overall": "2-3 honest sentences",
  "mistakes": [{"number":1,"category":"Grammar","incorrect":"quote","correct":"correction","explanation":"explanation"}],
  "structure_suggestions": ["tip 1","tip 2","tip 3"],
  "vocabulary_upgrades": [{"original":"word","better":"better"}],
  "paragraphs": [{"name":"Introduction","student_version":"text","improved_version":"improved"}],
  "full_improved": "Complete improved version."
}
Find up to 6 mistakes."""

IELTS_T2_SYSTEM = """You are an official IELTS examiner for Task 2. Respond ONLY with valid JSON (no markdown):
{
  "topic": "essay topic",
  "overall_band": 6.5,
  "overall_comment": "2-3 professional sentences",
  "scores": {
    "task_response": {"band": 6.5, "comment": "comment"},
    "coherence_cohesion": {"band": 6.0, "comment": "comment"},
    "lexical_resource": {"band": 6.5, "comment": "comment"},
    "grammatical_range": {"band": 6.0, "comment": "comment"}
  },
  "mistakes": [{"number":1,"category":"Grammar","incorrect":"quote","correct":"correction","explanation":"explanation"}],
  "structure_suggestions": ["s1","s2","s3"],
  "vocabulary_upgrades": [{"original":"word","better":"better"}],
  "full_improved": "Complete band 8+ version."
}"""

IELTS_T1_SYSTEM = """You are an official IELTS examiner for Task 1. Respond ONLY with valid JSON (no markdown):
{
  "topic": "graph/chart topic",
  "overall_band": 6.5,
  "overall_comment": "2-3 professional sentences",
  "scores": {
    "task_achievement": {"band": 6.5, "comment": "comment"},
    "coherence_cohesion": {"band": 6.0, "comment": "comment"},
    "lexical_resource": {"band": 6.5, "comment": "comment"},
    "grammatical_range": {"band": 6.0, "comment": "comment"}
  },
  "mistakes": [{"number":1,"category":"Grammar","incorrect":"quote","correct":"correction","explanation":"explanation"}],
  "structure_suggestions": ["s1","s2","s3"],
  "vocabulary_upgrades": [{"original":"word","better":"better"}],
  "full_improved": "Complete band 8+ version."
}"""

VOICE_SYSTEM = """Professional English speaking coach. Give concise feedback:
You said: "[transcript]"
Strengths: [one positive]
Improve: [one suggestion]
Better version: "[corrected version]"
Tip: [one tip]"""

def format_dictionary(data):
    if "error" in data:
        return "That word was not found. Please check your spelling and try again."
    lines = []
    lines.append(f"📖 {data.get('word','').upper()}")
    lines.append(f"{data.get('type','')} | Level: {data.get('level','')}")
    lines.append("")
    lines.append(f"📝 Definition:\n{data.get('definition','')}")
    lines.append("")
    lines.append(f"🇺🇿 In Uzbek:\n{data.get('uzbek','')}")
    lines.append("")
    examples = data.get("examples",[])
    if examples:
        lines.append("💬 Examples:")
        for ex in examples: lines.append(f"• {ex}")
        lines.append("")
    forms = data.get("word_forms",[])
    if forms:
        lines.append("🔤 Word forms:")
        for f in forms: lines.append(f"• {f}")
        lines.append("")
    collocations = data.get("collocations",[])
    if collocations:
        lines.append("🎯 Collocations:")
        for c in collocations: lines.append(f"• {c}")
        lines.append("")
    mistake = data.get("common_mistake",{})
    if mistake:
        lines.append("⚠️ Common mistake:")
        lines.append(f"❌ {mistake.get('wrong','')}")
        lines.append(f"✅ {mistake.get('right','')}")
        if mistake.get("explanation"): lines.append(f"({mistake.get('explanation','')})")
        lines.append("")
    synonyms = data.get("synonyms",[])
    if synonyms: lines.append(f"🔁 Synonyms: {', '.join(synonyms)}")
    antonyms = data.get("antonyms",[])
    if antonyms: lines.append(f"↔️ Antonyms: {', '.join(antonyms)}")
    return "\n".join(lines)

# PDF
NAVY=colors.HexColor("#0a1628"); GOLD=colors.HexColor("#c9a84c"); GOLD_LIGHT=colors.HexColor("#f5e6c0")
TEAL=colors.HexColor("#1a6b5a"); TEAL_LIGHT=colors.HexColor("#e0f2ee"); RED=colors.HexColor("#c0392b")
RED_LIGHT=colors.HexColor("#fdecea"); GREEN=colors.HexColor("#1e7e4a"); GREEN_LIGHT=colors.HexColor("#e8f8ee")
GREY=colors.HexColor("#95a5a6"); GREY_LIGHT=colors.HexColor("#f8f9fa"); WHITE=colors.white
BLACK=colors.HexColor("#1a1a2e"); PURPLE=colors.HexColor("#6c3483"); PURPLE_LT=colors.HexColor("#f0e6f6")

def S(name, **kw): return ParagraphStyle(name, **kw)

def sec_hdr(text, bg=NAVY, tc=None, acc=None):
    if tc is None: tc = colors.white
    if acc is None: acc = GOLD
    t = Table([[Paragraph(text, S("SH", fontName="Helvetica-Bold", fontSize=12, textColor=tc))]], colWidths=[17*cm])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("TOPPADDING",(0,0),(-1,-1),9),
        ("BOTTOMPADDING",(0,0),(-1,-1),9),("LEFTPADDING",(0,0),(-1,-1),14),("LINEBELOW",(0,0),(-1,-1),2,acc)]))
    return t

def build_pdf_header(story, student_name, topic, report_type):
    brand = Table([[Paragraph("<b>SAFIYA</b>", S("BN", fontName="Helvetica-Bold", fontSize=28, textColor=GOLD)),
        Paragraph("Premier Tutoring Center<br/><font size=9>English Language Excellence</font>",
                  S("BS", fontName="Helvetica", fontSize=13, textColor=WHITE))]], colWidths=[5*cm,12*cm])
    brand.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),NAVY),("TOPPADDING",(0,0),(-1,-1),16),
        ("BOTTOMPADDING",(0,0),(-1,-1),16),("LEFTPADDING",(0,0),(0,0),16),("LEFTPADDING",(1,0),(1,0),8),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LINEBELOW",(0,0),(-1,-1),3,GOLD)]))
    story.append(brand)
    tt = Table([[Paragraph(report_type.upper(), S("RT", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, alignment=TA_CENTER))]], colWidths=[17*cm])
    tt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GOLD_LIGHT),("TOPPADDING",(0,0),(-1,-1),10),
        ("BOTTOMPADDING",(0,0),(-1,-1),10),("BOX",(0,0),(-1,-1),1.5,GOLD)]))
    story.append(Spacer(1,8)); story.append(tt); story.append(Spacer(1,8))
    info = Table([[Paragraph(f"<b>Student:</b> {student_name}", S("IF", fontName="Helvetica", fontSize=10, textColor=BLACK)),
        Paragraph(f"<b>Topic:</b> {topic}", S("IF2", fontName="Helvetica", fontSize=10, textColor=BLACK)),
        Paragraph(f"<b>Date:</b> {datetime.now().strftime('%B %d, %Y')}", S("IF3", fontName="Helvetica", fontSize=10, textColor=BLACK))]], colWidths=[4*cm,9*cm,4*cm])
    info.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GREY_LIGHT),("BOX",(0,0),(-1,-1),0.5,GREY),
        ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),("LEFTPADDING",(0,0),(-1,-1),10)]))
    story.append(info); story.append(Spacer(1,14))

def build_mistakes(story, mistakes):
    for m in mistakes:
        mh = Table([[Paragraph(f"Mistake {m['number']}", S("MN", fontName="Helvetica-Bold", fontSize=10, textColor=WHITE)),
            Paragraph(m['category'], S("MC", fontName="Helvetica-Bold", fontSize=10, textColor=GOLD))]], colWidths=[3*cm,14*cm])
        mh.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),NAVY),("TOPPADDING",(0,0),(-1,-1),6),
            ("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),10)]))
        story.append(mh)
        wr = Table([[Paragraph("<b>Incorrect</b>", S("WL", fontName="Helvetica-Bold", fontSize=9, textColor=RED)),
            Paragraph("<b>Corrected</b>", S("RL", fontName="Helvetica-Bold", fontSize=9, textColor=GREEN))],
            [Paragraph(m.get("incorrect",""), S("WT", fontName="Helvetica", fontSize=9, textColor=BLACK, leading=13)),
            Paragraph(m.get("correct",""), S("RT2", fontName="Helvetica", fontSize=9, textColor=BLACK, leading=13))]], colWidths=[8.5*cm,8.5*cm])
        wr.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),RED_LIGHT),("BACKGROUND",(1,0),(1,0),GREEN_LIGHT),
            ("BACKGROUND",(0,1),(0,1),RED_LIGHT),("BACKGROUND",(1,1),(1,1),GREEN_LIGHT),
            ("BOX",(0,0),(-1,-1),0.5,GREY),("INNERGRID",(0,0),(-1,-1),0.5,GREY),
            ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
            ("LEFTPADDING",(0,0),(-1,-1),10),("VALIGN",(0,0),(-1,-1),"TOP")]))
        story.append(wr)
        eb = Table([[Paragraph(f"<i>{m.get('explanation','')}</i>", S("EX", fontName="Helvetica-Oblique", fontSize=9, textColor=colors.HexColor("#555"), leading=13))]], colWidths=[17*cm])
        eb.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GREY_LIGHT),("TOPPADDING",(0,0),(-1,-1),6),
            ("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),10),("LINEBELOW",(0,0),(-1,-1),0.5,GREY)]))
        story.append(eb); story.append(Spacer(1,8))

def build_vocab_structure(story, feedback):
    story.append(sec_hdr("STRUCTURE & VOCABULARY SUGGESTIONS", PURPLE, colors.white, colors.HexColor("#d7bde2")))
    story.append(Spacer(1,8))
    st = "<b>Structure Tips:</b><br/>" + "<br/>".join(f"- {s}" for s in feedback.get("structure_suggestions",[]))
    sb = Table([[Paragraph(st, S("ST", fontName="Helvetica", fontSize=10, textColor=BLACK, leading=16))]], colWidths=[17*cm])
    sb.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),PURPLE_LT),("BOX",(0,0),(-1,-1),1,PURPLE),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),("LEFTPADDING",(0,0),(-1,-1),14)]))
    story.append(sb); story.append(Spacer(1,8))
    vocab = feedback.get("vocabulary_upgrades",[])
    if vocab:
        vd = [[Paragraph("<b>Original</b>", S("VH", fontName="Helvetica-Bold", fontSize=9, textColor=WHITE)),
               Paragraph("<b>Better</b>", S("VH2", fontName="Helvetica-Bold", fontSize=9, textColor=WHITE))]]
        for v in vocab:
            vd.append([Paragraph(f'"{v.get("original","")}"', S("V1", fontName="Helvetica", fontSize=10, textColor=BLACK)),
                       Paragraph(f'"{v.get("better","")}"', S("V2", fontName="Helvetica", fontSize=10, textColor=TEAL))])
        vt = Table(vd, colWidths=[5*cm,12*cm])
        vt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),NAVY),("BOX",(0,0),(-1,-1),0.5,GREY),
            ("INNERGRID",(0,0),(-1,-1),0.5,GREY),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
            ("LEFTPADDING",(0,0),(-1,-1),10),("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,GREY_LIGHT])]))
        story.append(vt)
    story.append(Spacer(1,14))

def build_improved(story, text):
    story.append(sec_hdr("FULL IMPROVED VERSION", colors.HexColor("#7d6608"), colors.white, GOLD))
    story.append(Spacer(1,4))
    story.append(Paragraph("<i>Same ideas - corrected, enriched, and polished</i>", S("SI", fontName="Helvetica-Oblique", fontSize=9, textColor=GREY, spaceAfter=6)))
    story.append(Spacer(1,6))
    fb = Table([[Paragraph(text.replace("\n\n","<br/><br/>"), S("FB", fontName="Helvetica", fontSize=10, textColor=BLACK, leading=16, alignment=TA_JUSTIFY))]], colWidths=[17*cm])
    fb.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#fefcf0")),("BOX",(0,0),(-1,-1),2,GOLD),
        ("TOPPADDING",(0,0),(-1,-1),14),("BOTTOMPADDING",(0,0),(-1,-1),14),
        ("LEFTPADDING",(0,0),(-1,-1),16),("RIGHTPADDING",(0,0),(-1,-1),16)]))
    story.append(fb); story.append(Spacer(1,16))

def build_footer(story):
    ft = Table([[Paragraph("Safiya | Premier Tutoring Center", S("FL", fontName="Helvetica-Bold", fontSize=11, textColor=GOLD)),
        Paragraph("Keep writing. Keep improving. Excellence is a habit.", S("FM", fontName="Helvetica-Oblique", fontSize=9, textColor=WHITE, alignment=TA_CENTER)),
        Paragraph(datetime.now().strftime("%Y"), S("FD", fontName="Helvetica", fontSize=9, textColor=GREY))]], colWidths=[6*cm,8*cm,3*cm])
    ft.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),NAVY),("TOPPADDING",(0,0),(-1,-1),12),
        ("BOTTOMPADDING",(0,0),(-1,-1),12),("LEFTPADDING",(0,0),(-1,-1),14),
        ("LINEABOVE",(0,0),(-1,-1),3,GOLD),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story.append(ft)

def generate_light_pdf(feedback, student_name):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=1.5*cm, bottomMargin=2*cm)
    story = []
    build_pdf_header(story, student_name, feedback.get("topic","Essay"), "Writing Feedback Report")
    story.append(sec_hdr("OVERALL ASSESSMENT", TEAL, colors.white, colors.HexColor("#a8e6cf")))
    story.append(Spacer(1,8))
    ob = Table([[Paragraph(feedback.get("overall",""), S("OV", fontName="Helvetica", fontSize=10, textColor=BLACK, leading=16, alignment=TA_JUSTIFY))]], colWidths=[17*cm])
    ob.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TEAL_LIGHT),("BOX",(0,0),(-1,-1),1,TEAL),
        ("TOPPADDING",(0,0),(-1,-1),12),("BOTTOMPADDING",(0,0),(-1,-1),12),
        ("LEFTPADDING",(0,0),(-1,-1),14),("RIGHTPADDING",(0,0),(-1,-1),14)]))
    story.append(ob); story.append(Spacer(1,14))
    story.append(sec_hdr("6 KEY MISTAKES & CORRECTIONS", RED, colors.white, colors.HexColor("#f1948a")))
    story.append(Spacer(1,10))
    build_mistakes(story, feedback.get("mistakes",[]))
    build_vocab_structure(story, feedback)
    build_improved(story, feedback.get("full_improved",""))
    build_footer(story)
    doc.build(story); buffer.seek(0); return buffer

def generate_ielts_pdf(feedback, student_name, task):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=1.5*cm, bottomMargin=2*cm)
    story = []
    build_pdf_header(story, student_name, feedback.get("topic","Essay"), f"IELTS Task {task} - Official Assessment")
    band = feedback.get("overall_band", 0)
    bc = colors.HexColor("#1e7e4a") if band >= 7 else colors.HexColor("#d4ac0d") if band >= 5.5 else RED
    bt = Table([[Paragraph("<b>Overall Band Score</b>", S("OBL", fontName="Helvetica-Bold", fontSize=14, textColor=WHITE, alignment=TA_CENTER)),
        Paragraph(f"<b>{band}</b>", S("OBS", fontName="Helvetica-Bold", fontSize=36, textColor=bc, alignment=TA_CENTER))]], colWidths=[13*cm,4*cm])
    bt.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),NAVY),("BACKGROUND",(1,0),(1,0),colors.HexColor("#f0f0f0")),
        ("BOX",(0,0),(-1,-1),2,GOLD),("TOPPADDING",(0,0),(-1,-1),14),("BOTTOMPADDING",(0,0),(-1,-1),14),
        ("LEFTPADDING",(0,0),(-1,-1),14),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story.append(bt); story.append(Spacer(1,8))
    oc = Table([[Paragraph(feedback.get("overall_comment",""), S("OC", fontName="Helvetica", fontSize=10, textColor=BLACK, leading=15, alignment=TA_JUSTIFY))]], colWidths=[17*cm])
    oc.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GOLD_LIGHT),("BOX",(0,0),(-1,-1),1,GOLD),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LEFTPADDING",(0,0),(-1,-1),14),("RIGHTPADDING",(0,0),(-1,-1),14)]))
    story.append(oc); story.append(Spacer(1,14))
    story.append(sec_hdr("IELTS SCORING CRITERIA", NAVY, colors.white, GOLD)); story.append(Spacer(1,8))
    scores = feedback.get("scores",{})
    criteria = [("task_response","Task Response (TR)"),("task_achievement","Task Achievement (TA)"),
        ("coherence_cohesion","Coherence & Cohesion (CC)"),("lexical_resource","Lexical Resource (LR)"),
        ("grammatical_range","Grammatical Range & Accuracy (GRA)")]
    for key, label in criteria:
        if key in scores:
            sc = scores[key]; b = sc.get("band",0)
            bcc = colors.HexColor("#1e7e4a") if b >= 7 else colors.HexColor("#d4ac0d") if b >= 5.5 else RED
            row = Table([[Paragraph(f"<b>{label}</b>", S("CL", fontName="Helvetica-Bold", fontSize=10, textColor=NAVY)),
                Paragraph(f"<b>{b}</b>", S("CB", fontName="Helvetica-Bold", fontSize=16, textColor=bcc, alignment=TA_CENTER)),
                Paragraph(sc.get("comment",""), S("CC2", fontName="Helvetica", fontSize=9, textColor=BLACK, leading=13))]], colWidths=[5*cm,2*cm,10*cm])
            row.setStyle(TableStyle([("BACKGROUND",(0,0),(1,0),GREY_LIGHT),("BOX",(0,0),(-1,-1),0.5,GREY),
                ("INNERGRID",(0,0),(-1,-1),0.5,GREY),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
                ("LEFTPADDING",(0,0),(-1,-1),10),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
            story.append(row); story.append(Spacer(1,6))
    story.append(Spacer(1,8))
    story.append(sec_hdr("KEY MISTAKES & CORRECTIONS", RED, colors.white, colors.HexColor("#f1948a"))); story.append(Spacer(1,10))
    build_mistakes(story, feedback.get("mistakes",[]))
    build_vocab_structure(story, feedback)
    build_improved(story, feedback.get("full_improved",""))
    build_footer(story)
    doc.build(story); buffer.seek(0); return buffer

user_sessions = {}

def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {"history": [], "mode": "chat", "quiz_index": None,
                                   "puzzle_index": None, "article_index": None, "writing_type": None, "ielts_task": None}
    return user_sessions[user_id]

def ask_claude(user_id, message, system=None, max_tokens=500):
    session = get_session(user_id)
    u = user_db.get(str(user_id), {}); name = u.get("name",""); weak = u.get("weak_areas",[])
    sys_prompt = system or SAFIYA_SYSTEM
    if not system:
        if name: sys_prompt += f"\n\nUser's name: {name}"
        if weak: sys_prompt += f"\nWeak areas: {', '.join(weak)}"
    session["history"].append({"role":"user","content":message})
    history = session["history"][-14:]
    response = claude_client.messages.create(model="claude-sonnet-4-20250514", max_tokens=max_tokens, system=sys_prompt, messages=history)
    reply = response.content[0].text
    session["history"].append({"role":"assistant","content":reply})
    uid = str(user_id)
    if uid in user_db:
        user_db[uid]["messages"] = user_db[uid].get("messages",0) + 1
        save_json(USERS_FILE, user_db)
    return reply

async def transcribe_voice(path):
    with open(path,"rb") as f:
        t = openai_client.audio.transcriptions.create(model="whisper-1",file=f,language="en")
    return t.text

QUIZ_QUESTIONS = [
    {"q":"Which word is a NOUN?\n\na) Run\nb) Happy\nc) Dog\nd) Quickly","a":"c","e":"Dog is a noun - a person, place or thing.","cat":"Nouns"},
    {"q":"Correct sentence?\n\na) She go to school.\nb) She goes to school.\nc) She going.\nd) She gone.","a":"b","e":"She goes - add -es for he/she/it.","cat":"Verb Agreement"},
    {"q":"Which is an ADJECTIVE?\n\na) Jump\nb) Tiny\nc) Cat\nd) Slowly","a":"b","e":"Tiny is an adjective - describes a noun.","cat":"Adjectives"},
    {"q":"Capital letters correct?\n\na) my name is john.\nb) My name is John.\nc) my Name is john.\nd) My Name Is John.","a":"b","e":"Sentences start with capital. Names are always capitalized.","cat":"Capitalization"},
    {"q":"Correct punctuation?\n\na) Do you like pizza\nb) Do you like pizza!\nc) Do you like pizza?\nd) Do you like pizza,","a":"c","e":"Questions end with ?","cat":"Punctuation"},
    {"q":"Plural of child?\n\na) Childs\nb) Childes\nc) Children\nd) Childer","a":"c","e":"Children - irregular plural. Also: man-men, tooth-teeth.","cat":"Plurals"},
    {"q":"Which is a VERB?\n\na) Beautiful\nb) Apple\nc) Swim\nd) Blue","a":"c","e":"Swim is a verb - an action word.","cat":"Verbs"},
    {"q":"Spelled correctly?\n\na) Freind\nb) Frend\nc) Friend\nd) Freind","a":"c","e":"Friend - I before E: fr-I-E-nd.","cat":"Spelling"},
    {"q":"I have ___ apple.\n\na) a\nb) an\nc) the\nd) some","a":"b","e":"Use an before vowel sounds. Apple starts with a.","cat":"Articles"},
    {"q":"Opposite of hot?\n\na) Warm\nb) Sunny\nc) Cold\nd) Big","a":"c","e":"Cold is the antonym of hot.","cat":"Vocabulary"},
    {"q":"Which is a PRONOUN?\n\na) Run\nb) She\nc) Big\nd) House","a":"b","e":"She is a pronoun - replaces a name.","cat":"Pronouns"},
    {"q":"What ends a statement?\n\na) Comma\nb) Colon\nc) Period\nd) Apostrophe","a":"c","e":"A period ends a statement.","cat":"Punctuation"},
    {"q":"Which is an ADVERB?\n\na) Cat\nb) Happy\nc) Quickly\nd) Jump","a":"c","e":"Quickly is an adverb - describes HOW.","cat":"Adverbs"},
    {"q":"Correct sentence?\n\na) I has a cat.\nb) I have a cat.\nc) I haves a cat.\nd) I having a cat.","a":"b","e":"I have a cat - use have with I, you, we, they.","cat":"Verb Agreement"},
    {"q":"Synonym for big?\n\na) Small\nb) Tiny\nc) Large\nd) Short","a":"c","e":"Large is a synonym for big.","cat":"Vocabulary"},
]

PUZZLES = [
    {"q":"Fill in:\n'She ___ to school every day.'\n\na) go\nb) goes\nc) going\nd) gone","answer":"b","e":"goes - third person singular present tense."},
    {"q":"What does BENEFICIAL mean?\n\na) Harmful\nb) Helpful\nc) Beautiful\nd) Boring","answer":"b","e":"Beneficial means helpful or having a good effect."},
    {"q":"Which does NOT belong?\n\na) Happy\nb) Sad\nc) Angry\nd) Run","answer":"d","e":"Run is a verb. Happy, Sad, Angry are all adjectives."},
    {"q":"'There are ___ apples.'\n\na) much\nb) many\nc) a lot\nd) few of","answer":"b","e":"Many - use with countable nouns. Much is for uncountable."},
    {"q":"Synonym for ENORMOUS?\n\na) Tiny\nb) Average\nc) Huge\nd) Narrow","answer":"c","e":"Huge is a synonym for enormous. Others: giant, massive, immense."},
    {"q":"Which does NOT belong?\n\na) Cat\nb) Dog\nc) Eagle\nd) Fish","answer":"c","e":"Eagle is a bird. Cat, Dog, Fish are common pets."},
    {"q":"'If I ___ rich, I would travel.'\n\na) am\nb) was\nc) were\nd) be","answer":"c","e":"Were - used in conditional sentences (subjunctive)."},
    {"q":"What does INEVITABLE mean?\n\na) Impossible\nb) Certain to happen\nc) Surprising\nd) Dangerous","answer":"b","e":"Inevitable means certain to happen, impossible to avoid."},
]

ARTICLES = [
    {"title":"The Benefits of Exercise","level":"Intermediate",
     "text":"Regular exercise is one of the most important things you can do for your health. Being physically active can improve your brain health, help manage weight, reduce the risk of disease, strengthen bones and muscles, and improve your ability to do everyday activities.\n\nAdults who sit less and do any amount of moderate-to-vigorous physical activity gain some health benefits.",
     "questions":["What are THREE benefits of exercise mentioned?","Who can benefit from physical activity?","What does the article say about people who sit less?"]},
    {"title":"The Importance of Reading","level":"Intermediate",
     "text":"Reading is one of the most beneficial activities you can engage in. It improves your vocabulary, enhances your writing skills, and broadens your knowledge.\n\nReading also improves concentration and focus. Furthermore, reading reduces stress. Studies show that just six minutes of reading can reduce stress levels by up to 68 percent.",
     "questions":["Name THREE benefits of reading mentioned.","How does reading help with concentration?","How much can reading reduce stress?"]},
    {"title":"Social Media and Young People","level":"Upper Intermediate",
     "text":"Social media has become an integral part of modern life, especially for young people. Platforms like Instagram, TikTok, and Twitter allow people to connect, share ideas, and express themselves.\n\nHowever, research suggests that excessive use can lead to anxiety, depression, and low self-esteem. On the positive side, social media can be a powerful tool for education and building communities.",
     "questions":["What platforms are mentioned?","What are the negative effects of social media?","What positive uses does the article mention?"]},
]

LEARNING_TOPICS = {
    "Nouns":"Nouns are people, places, or things. Examples: teacher, school, book.",
    "Verbs":"Verbs are action words. Examples: run, write, think.",
    "Adjectives":"Adjectives describe nouns. Examples: big, beautiful, fast.",
    "Adverbs":"Adverbs describe verbs. Examples: quickly, loudly, carefully.",
    "Punctuation":"Punctuation organizes writing: period (.), comma (,), question mark (?).",
    "Articles":"Articles: a (consonants), an (vowels), the (specific things).",
    "Verb Agreement":"Match verbs to subjects. She GOES, They GO.",
    "Vocabulary":"Learn new words and their meanings regularly.",
    "Plurals":"Most plurals add -s/-es. Irregular: child-children, man-men.",
    "Spelling":"I before E except after C. Double consonants. Silent letters.",
}

def main_reply_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("Safiya AI"), KeyboardButton("Dictionary")],
        [KeyboardButton("Complaints & Offers")],
    ], resize_keyboard=True, input_field_placeholder="Chat with Safiya...")

def safiya_ai_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Quiz",callback_data="mode_quiz"), InlineKeyboardButton("Word Puzzle",callback_data="mode_puzzle")],
        [InlineKeyboardButton("Check Writing",callback_data="mode_writing"), InlineKeyboardButton("Reading Practice",callback_data="mode_reading")],
        [InlineKeyboardButton("Voice Practice",callback_data="mode_voice"), InlineKeyboardButton("My Progress",callback_data="show_progress")],
        [InlineKeyboardButton("Learning Path",callback_data="learning_path"), InlineKeyboardButton("Close",callback_data="close_menu")],
    ])

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back",callback_data="safiya_menu")]])

def join_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Join Channel",url=CHANNEL_URL)],[InlineKeyboardButton("I Joined",callback_data="check_join")]])

async def start(update, context):
    user = update.effective_user; uid = user.id; name = user.first_name or ""
    if not await check_membership(uid, context):
        await update.message.reply_text("Welcome! To use Safiya AI, please join our channel first.", reply_markup=join_keyboard())
        return
    u = get_user(uid, name); get_session(uid)["mode"] = "chat"
    is_new = u.get("messages",0) == 0
    prompt = (f"New user named {name} just started. Introduce yourself briefly as Safiya, support teacher at Premier Tutoring Center. Mention the three buttons: Safiya AI, Dictionary, and Complaints & Offers."
              if is_new else f"{name} is back. Welcome them back in one sentence.")
    reply = ask_claude(uid, prompt)
    await update.message.reply_text(reply, reply_markup=main_reply_keyboard())

async def score_command(update, context):
    if not await require_membership(update, context): return
    uid = str(update.effective_user.id); p = student_progress.get(uid)
    if not p or p.get("total",0)==0:
        await update.message.reply_text("No results yet.", reply_markup=main_reply_keyboard()); return
    s,t = p["score"],p["total"]; pct = int(s/t*100)
    await update.message.reply_text(
        f"Progress:\nQuiz: {s}/{t} ({pct}%)\nStreak: {p.get('streak',0)} days\n"
        f"Voice: {p.get('voice_messages',0)}\nEssays: {p.get('essays_checked',0)}\n"
        f"IELTS: {p.get('ielts_checks',0)}\nPuzzles: {p.get('puzzles_solved',0)}\nArticles: {p.get('articles_read',0)}",
        reply_markup=main_reply_keyboard())

async def path_command(update, context):
    if not await require_membership(update, context): return
    uid = str(update.effective_user.id); u = user_db.get(uid,{}); weak = u.get("weak_areas",[])
    if not weak:
        await update.message.reply_text("No weak areas detected yet. Take more quizzes to build your path.", reply_markup=main_reply_keyboard()); return
    tips = "\n".join(f"- {a}: {LEARNING_TOPICS.get(a,'Keep practicing.')}" for a in weak[:5])
    await update.message.reply_text(f"Your focus areas:\n\n{tips}", reply_markup=main_reply_keyboard())

async def send_quiz(upd_or_q, context, user_id):
    session = get_session(user_id); idx = random.randint(0,len(QUIZ_QUESTIONS)-1)
    session["quiz_index"]=idx; session["mode"]="quiz"; q=QUIZ_QUESTIONS[idx]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("A",callback_data="quiz_a"),InlineKeyboardButton("B",callback_data="quiz_b"),
         InlineKeyboardButton("C",callback_data="quiz_c"),InlineKeyboardButton("D",callback_data="quiz_d")],
        [InlineKeyboardButton("Skip",callback_data="quiz_skip"),InlineKeyboardButton("Stop",callback_data="safiya_menu")]])
    if hasattr(upd_or_q,"edit_message_text"): await upd_or_q.edit_message_text(f"Quiz\n\n{q['q']}",reply_markup=kb)
    else: await upd_or_q.message.reply_text(f"Quiz\n\n{q['q']}",reply_markup=kb)

async def send_puzzle(upd_or_q, context, user_id):
    session = get_session(user_id); idx = random.randint(0,len(PUZZLES)-1)
    session["puzzle_index"]=idx; session["mode"]="puzzle"; p=PUZZLES[idx]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("A",callback_data="puz_a"),InlineKeyboardButton("B",callback_data="puz_b"),
         InlineKeyboardButton("C",callback_data="puz_c"),InlineKeyboardButton("D",callback_data="puz_d")],
        [InlineKeyboardButton("Skip",callback_data="puz_skip"),InlineKeyboardButton("Stop",callback_data="safiya_menu")]])
    if hasattr(upd_or_q,"edit_message_text"): await upd_or_q.edit_message_text(f"Word Puzzle\n\n{p['q']}",reply_markup=kb)
    else: await upd_or_q.message.reply_text(f"Word Puzzle\n\n{p['q']}",reply_markup=kb)

async def send_article(upd_or_q, context, user_id):
    session = get_session(user_id); idx = random.randint(0,len(ARTICLES)-1)
    session["article_index"]=idx; session["mode"]="reading"; a=ARTICLES[idx]
    questions = "\n".join(f"{i+1}. {q}" for i,q in enumerate(a["questions"]))
    text = f"Reading Practice - {a['level']}\n\nTitle: {a['title']}\n\n{a['text']}\n\nQuestions:\n{questions}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Submit My Answers",callback_data="check_answers")],
        [InlineKeyboardButton("New Article",callback_data="mode_reading"),InlineKeyboardButton("Back",callback_data="safiya_menu")]])
    if hasattr(upd_or_q,"edit_message_text"): await upd_or_q.edit_message_text(text,reply_markup=kb)
    else: await upd_or_q.message.reply_text(text,reply_markup=kb)

async def process_writing(update, context, text, mode, task=""):
    user_id=update.effective_user.id; user_name=update.effective_user.first_name or "Student"
    await update.message.reply_text("Analyzing your writing. Generating PDF report...")
    await context.bot.send_chat_action(update.effective_chat.id,action="upload_document")
    try:
        system=(IELTS_T2_SYSTEM if task=="2" else IELTS_T1_SYSTEM) if mode=="ielts" else WRITING_LIGHT_SYSTEM
        raw=ask_claude(user_id,f"Analyze:\n\n{text}",system=system,max_tokens=2500)
        clean=re.sub(r"```json|```","",raw).strip(); feedback=json.loads(clean)
        if mode=="ielts":
            pdf=generate_ielts_pdf(feedback,user_name,task); inc_progress(user_id,user_name,"ielts_checks"); report_name=f"IELTS Task {task} Assessment"
        else:
            pdf=generate_light_pdf(feedback,user_name); inc_progress(user_id,user_name,"essays_checked"); report_name="Writing Feedback"
        filename=f"Safiya_{report_name.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        await update.message.reply_document(document=pdf,filename=filename,caption=f"Your {report_name} is ready.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Check Another",callback_data="mode_writing")],[InlineKeyboardButton("Back",callback_data="safiya_menu")]]))
        get_session(user_id)["mode"]="chat"
    except json.JSONDecodeError: await update.message.reply_text(f"Feedback:\n\n{raw[:3500]}")
    except Exception as e: logger.error(f"Writing error: {e}"); await update.message.reply_text("Something went wrong. Please try again.")

async def button_callback(update, context):
    query=update.callback_query; await query.answer()
    user_id=query.from_user.id; user_name=query.from_user.first_name or "Student"
    session=get_session(user_id); data=query.data

    if data=="check_join":
        if await check_membership(user_id,context):
            u=get_user(user_id,user_name); is_new=u.get("messages",0)==0
            prompt=(f"New user named {user_name} just joined. Welcome briefly as Safiya." if is_new else f"Welcome back {user_name} briefly.")
            reply=ask_claude(user_id,prompt); await query.edit_message_text(reply)
            await context.bot.send_message(user_id,"You're in! Use the buttons below.",reply_markup=main_reply_keyboard())
        else: await query.answer("You haven't joined the channel yet!",show_alert=True)
        return

    if not await check_membership(user_id,context):
        await query.answer("Please join our channel first!",show_alert=True); return

    if data=="safiya_menu":
        session["mode"]="chat"; await query.edit_message_text("Safiya AI - choose what you need:",reply_markup=safiya_ai_keyboard())
    elif data=="close_menu": await query.edit_message_text("Tap the buttons below anytime.")
    elif data=="dict_another":
        session["mode"]="dictionary"; await query.edit_message_text("Type another word to look up!")
    elif data=="show_progress":
        uid=str(user_id); p=student_progress.get(uid)
        if not p or p.get("total",0)==0: msg="No results yet. Start with a quiz or send an essay."
        else:
            s,t=p["score"],p["total"]; pct=int(s/t*100)
            msg=(f"Progress:\nQuiz: {s}/{t} ({pct}%)\nStreak: {p.get('streak',0)} days\n"
                 f"Voice: {p.get('voice_messages',0)}\nEssays: {p.get('essays_checked',0)}\n"
                 f"IELTS: {p.get('ielts_checks',0)}\nPuzzles: {p.get('puzzles_solved',0)}\nArticles: {p.get('articles_read',0)}")
        await query.edit_message_text(msg,reply_markup=safiya_ai_keyboard())
    elif data=="learning_path":
        uid=str(user_id); u=user_db.get(uid,{}); weak=u.get("weak_areas",[])
        msg=("No weak areas detected yet. Take more quizzes to build your path." if not weak else
             "Your focus areas:\n\n"+"\n".join(f"- {a}: {LEARNING_TOPICS.get(a,'Keep practicing.')}" for a in weak[:5]))
        await query.edit_message_text(msg,reply_markup=safiya_ai_keyboard())
    elif data=="mode_quiz": await send_quiz(query,context,user_id)
    elif data=="mode_puzzle": await send_puzzle(query,context,user_id)
    elif data=="mode_reading": await send_article(query,context,user_id)
    elif data=="check_answers":
        session["mode"]="reading_answers"; await query.edit_message_text("Type your answers below.",reply_markup=back_btn())
    elif data=="mode_voice":
        session["mode"]="voice"; await query.edit_message_text("Send a voice message in English and I'll give you feedback.",reply_markup=back_btn())
    elif data=="mode_writing":
        session["mode"]="writing_ask"
        await query.edit_message_text("Should I check it lightly or professionally?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Lightly",callback_data="write_light"),InlineKeyboardButton("Professionally (IELTS)",callback_data="write_pro")],
                [InlineKeyboardButton("Back",callback_data="safiya_menu")]]))
    elif data=="write_light":
        session["mode"]="writing"; session["writing_type"]="light"
        await query.edit_message_text("Paste your essay or paragraph below.",reply_markup=back_btn())
    elif data=="write_pro":
        session["writing_type"]="ielts"
        await query.edit_message_text("IELTS Task 1 or Task 2?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Task 1 (Graph/Letter)",callback_data="ielts_t1"),InlineKeyboardButton("Task 2 (Essay)",callback_data="ielts_t2")],
                [InlineKeyboardButton("Back",callback_data="safiya_menu")]]))
    elif data=="ielts_t1":
        session["mode"]="writing"; session["ielts_task"]="1"; await query.edit_message_text("Paste your IELTS Task 1 writing below.",reply_markup=back_btn())
    elif data=="ielts_t2":
        session["mode"]="writing"; session["ielts_task"]="2"; await query.edit_message_text("Paste your IELTS Task 2 essay below.",reply_markup=back_btn())
    elif data.startswith("quiz_"):
        if session.get("quiz_index") is None:
            await query.edit_message_text("No active quiz.",reply_markup=safiya_ai_keyboard()); return
        if data=="quiz_skip": await send_quiz(query,context,user_id); return
        ans={"quiz_a":"a","quiz_b":"b","quiz_c":"c","quiz_d":"d"}.get(data)
        q=QUIZ_QUESTIONS[session["quiz_index"]]; correct=ans==q["a"]
        update_quiz_progress(user_id,user_name,correct,q.get("cat",""))
        p=student_progress.get(str(user_id),{}); s,t=p.get("score",0),p.get("total",0)
        result=(f"Correct. {q['e']}\n\nScore: {s}/{t}" if correct else f"Incorrect. Answer: {q['a'].upper()}.\n\n{q['e']}\n\nScore: {s}/{t}")
        await query.edit_message_text(result,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next",callback_data="mode_quiz")],[InlineKeyboardButton("Stop",callback_data="safiya_menu")]]))
        session["quiz_index"]=None
    elif data.startswith("puz_"):
        if session.get("puzzle_index") is None:
            await query.edit_message_text("No active puzzle.",reply_markup=safiya_ai_keyboard()); return
        if data=="puz_skip": await send_puzzle(query,context,user_id); return
        ans={"puz_a":"a","puz_b":"b","puz_c":"c","puz_d":"d"}.get(data)
        p=PUZZLES[session["puzzle_index"]]; correct=ans==p["answer"]
        if correct: inc_progress(user_id,user_name,"puzzles_solved")
        result=(f"Correct. {p['e']}" if correct else f"Incorrect. Answer: {p['answer'].upper()}.\n\n{p['e']}")
        await query.edit_message_text(result,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next Puzzle",callback_data="mode_puzzle")],[InlineKeyboardButton("Stop",callback_data="safiya_menu")]]))
        session["puzzle_index"]=None

async def handle_voice(update, context):
    if not await require_membership(update,context): return
    user_id=update.effective_user.id; user_name=update.effective_user.first_name or "Student"
    await context.bot.send_chat_action(update.effective_chat.id,action="typing")
    try:
        file=await context.bot.get_file(update.message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg",delete=False) as tmp: tmp_path=tmp.name
        await file.download_to_drive(tmp_path)
        transcript=await transcribe_voice(tmp_path); os.unlink(tmp_path)
        if not transcript.strip():
            await update.message.reply_text("Could not process audio. Try again in a quieter place."); return
        inc_progress(user_id,user_name,"voice_messages")
        reply=ask_claude(user_id,f'Student said: "{transcript}"\nGive speaking feedback.',system=VOICE_SYSTEM)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Voice error: {e}"); await update.message.reply_text("Something went wrong with the voice. Try again.")

async def handle_message(update, context):
    user_id=update.effective_user.id; user_name=update.effective_user.first_name or ""
    session=get_session(user_id); text=update.message.text.strip(); mode=session.get("mode","chat")
    get_user(user_id,user_name)

    if text=="Safiya AI":
        if not await require_membership(update,context): return
        await update.message.reply_text("Safiya AI - choose what you need:",reply_markup=safiya_ai_keyboard()); return

    if text=="Dictionary":
        if not await require_membership(update,context): return
        session["mode"]="dictionary"
        await update.message.reply_text("Type any English word and I'll look it up!\n\nExample: motivation, ambitious, consequently..."); return

    if text=="Complaints & Offers":
        if not await require_membership(update,context): return
        session["mode"]="complaint"
        await update.message.reply_text("Send your complaint or suggestion and it will be forwarded to the team.\n\nType your message below:"); return

    if not await require_membership(update,context): return

    if mode=="dictionary":
        await context.bot.send_chat_action(update.effective_chat.id,action="typing")
        try:
            raw=ask_claude(user_id,f"Look up this word: {text}",system=DICTIONARY_SYSTEM,max_tokens=800)
            clean=re.sub(r"```json|```","",raw).strip(); data=json.loads(clean)
            reply=format_dictionary(data)
        except: reply=f"Could not look up '{text}'. Please check your spelling and try again."
        await update.message.reply_text(reply,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Look up another word",callback_data="dict_another")],[InlineKeyboardButton("Back",callback_data="close_menu")]]))
        session["mode"]="chat"; return

    if mode=="complaint":
        user_info=f"From: {user_name} (ID: {user_id})\n\nMessage:\n{text}"
        try:
            await context.bot.send_message(chat_id=ADMIN_USERNAME,text=f"New message from Safiya Bot:\n\n{user_info}")
            await update.message.reply_text("Your message has been sent to the team. Thank you!",reply_markup=main_reply_keyboard())
        except:
            await update.message.reply_text(f"Your message has been recorded. You can also reach us at {ADMIN_USERNAME}",reply_markup=main_reply_keyboard())
        session["mode"]="chat"; return

    if mode=="writing":
        if len(text)<30:
            await update.message.reply_text("Please send a longer text to analyze."); return
        await process_writing(update,context,text,session.get("writing_type","light"),session.get("ielts_task","2")); return

    if mode=="reading_answers":
        idx=session.get("article_index",0); a=ARTICLES[idx] if idx<len(ARTICLES) else ARTICLES[0]
        inc_progress(user_id,user_name,"articles_read")
        prompt=(f"Student answered comprehension questions about '{a['title']}'.\n"
                f"Article: {a['text'][:400]}\nQuestions: {a['questions']}\nAnswers: {text}\n\nCheck their answers briefly.")
        await context.bot.send_chat_action(update.effective_chat.id,action="typing")
        reply=ask_claude(user_id,prompt)
        await update.message.reply_text(reply,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("New Article",callback_data="mode_reading")],[InlineKeyboardButton("Back",callback_data="safiya_menu")]]))
        session["mode"]="chat"; return

    await context.bot.send_chat_action(update.effective_chat.id,action="typing")
    try: reply=ask_claude(user_id,text)
    except Exception as e: logger.error(f"Claude error: {e}"); reply="Something went wrong. Please try again."
    await update.message.reply_text(reply)

async def quiz_command(update,context):
    if not await require_membership(update,context): return
    get_session(update.effective_user.id)["mode"]="quiz"
    await send_quiz(update,context,update.effective_user.id)

async def dict_command(update,context):
    if not await require_membership(update,context): return
    get_session(update.effective_user.id)["mode"]="dictionary"
    await update.message.reply_text("Type any English word to look it up!")

async def help_command(update,context):
    if not await require_membership(update,context): return
    await update.message.reply_text("Use the buttons below:\n\nSafiya AI - all learning features\nDictionary - look up any word\nComplaints & Offers - send feedback\n\nOr just chat with me directly.",reply_markup=main_reply_keyboard())

def main():
    print("Starting Safiya Bot...")
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",help_command))
    app.add_handler(CommandHandler("quiz",quiz_command))
    app.add_handler(CommandHandler("score",score_command))
    app.add_handler(CommandHandler("path",path_command))
    app.add_handler(CommandHandler("dict",dict_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.VOICE,handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_message))
    print("Safiya is running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main()
