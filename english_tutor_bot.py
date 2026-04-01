#!/usr/bin/env python3
"""
⭐ StarBot — AI English Tutor
Features: Writing Checker (PDF output), Voice Analysis, Quizzes, Progress Tracking

Run:
  $env:TELEGRAM_TOKEN="..."
  $env:ANTHROPIC_API_KEY="..."
  $env:OPENAI_API_KEY="..."
  cd Desktop
  py english_tutor_bot.py
"""

import os, logging, random, json, tempfile, re
from datetime import datetime, timedelta
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import anthropic
from openai import OpenAI

# ReportLab imports
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

# ─── Configuration ─────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_ANTHROPIC_API_KEY")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")

BOT_NAME      = "StarBot ⭐"
PROGRESS_FILE = "progress.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ─── System Prompts ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""You are {BOT_NAME}, an intelligent and friendly AI English tutor for elementary school students (grades K-5).
- Smart, clear, and conversational
- Simple, easy-to-understand English
- Warm and encouraging
- Only discuss English grammar, vocabulary, writing, and speaking
- Never give direct homework answers — always hint and guide
"""

WRITING_SYSTEM_PROMPT = """You are an expert English writing coach. A student has submitted a piece of writing for feedback.

Analyze it and respond using EXACTLY this JSON structure (respond ONLY with valid JSON, no extra text):

{
  "topic": "detected topic/title of the essay",
  "overall": "2-3 sentence warm encouraging overall assessment",
  "mistakes": [
    {
      "number": 1,
      "category": "Grammar · Punctuation",
      "incorrect": "exact quote of the mistake from their text",
      "correct": "corrected version",
      "explanation": "clear explanation of what's wrong and why"
    },
    {
      "number": 2,
      "category": "Grammar · Articles",
      "incorrect": "...",
      "correct": "...",
      "explanation": "..."
    }
  ],
  "structure_suggestions": [
    "suggestion 1",
    "suggestion 2",
    "suggestion 3"
  ],
  "vocabulary_upgrades": [
    {"original": "bad quality", "better": "poor quality / substandard"},
    {"original": "things", "better": "products / items / goods"},
    {"original": "useful", "better": "beneficial / practical"}
  ],
  "paragraphs": [
    {
      "name": "Introduction",
      "student_version": "exact student text for this section, or '[Missing — needs to be added]'",
      "improved_version": "improved version of this paragraph"
    },
    {
      "name": "Body — Main Points",
      "student_version": "...",
      "improved_version": "..."
    },
    {
      "name": "Conclusion",
      "student_version": "...",
      "improved_version": "..."
    }
  ],
  "full_improved": "Complete improved version of the entire essay keeping all original ideas but with corrected grammar, better vocabulary, improved structure."
}

Rules:
- Find exactly 6 mistakes (or fewer if the text is very short/good)
- Keep all the student's original ideas in the improved version
- Be encouraging and age-appropriate
- Respond ONLY with the JSON object, nothing else
"""

VOICE_SYSTEM_PROMPT = """You are a friendly AI English speaking coach for elementary school kids (K-5).
A student sent a voice message. You have the transcribed text.

Respond using this format:

🎤 **What you said:**
"[transcribed text]"

✅ **What's great:**
[what they did well]

📝 **Suggestions:**
[gentle grammar/vocabulary improvements]

⭐ **Better version:**
"[corrected version or 'Perfect! No changes needed.']"

💬 **Tip:**
[one useful English tip]

🌟 [One short encouraging message]
"""

# ─── PDF Generator ─────────────────────────────────────────────────────────────
def generate_feedback_pdf(feedback: dict, student_name: str) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )

    # ── Color Palette ──
    DARK_BLUE   = colors.HexColor("#1a237e")
    MED_BLUE    = colors.HexColor("#283593")
    LIGHT_BLUE  = colors.HexColor("#e8eaf6")
    ACCENT_RED  = colors.HexColor("#c62828")
    ACCENT_GREEN= colors.HexColor("#2e7d32")
    GOLD        = colors.HexColor("#f57f17")
    GREY_BG     = colors.HexColor("#f5f5f5")
    GREY_LINE   = colors.HexColor("#bdbdbd")
    WHITE       = colors.white
    BLACK       = colors.HexColor("#212121")
    SOFT_RED    = colors.HexColor("#ffebee")
    SOFT_GREEN  = colors.HexColor("#e8f5e9")

    # ── Styles ──
    styles = getSampleStyleSheet()

    def style(name, **kwargs):
        return ParagraphStyle(name, **kwargs)

    S_TITLE     = style("S_TITLE",     fontName="Helvetica-Bold",   fontSize=20, textColor=WHITE,      alignment=TA_CENTER, spaceAfter=4)
    S_SUBTITLE  = style("S_SUBTITLE",  fontName="Helvetica",        fontSize=11, textColor=LIGHT_BLUE, alignment=TA_CENTER, spaceAfter=2)
    S_SECTION   = style("S_SECTION",   fontName="Helvetica-Bold",   fontSize=13, textColor=WHITE,      spaceAfter=6, spaceBefore=4)
    S_MISTAKE_H = style("S_MISTAKE_H", fontName="Helvetica-Bold",   fontSize=11, textColor=DARK_BLUE,  spaceAfter=4, spaceBefore=6)
    S_LABEL     = style("S_LABEL",     fontName="Helvetica-Bold",   fontSize=9,  textColor=colors.HexColor("#555555"))
    S_BODY      = style("S_BODY",      fontName="Helvetica",        fontSize=10, textColor=BLACK,      spaceAfter=4, leading=14)
    S_ITALIC    = style("S_ITALIC",    fontName="Helvetica-Oblique",fontSize=9,  textColor=colors.HexColor("#444444"), spaceAfter=6, leading=13)
    S_PARA_H    = style("S_PARA_H",    fontName="Helvetica-Bold",   fontSize=10, textColor=MED_BLUE,   spaceAfter=3, spaceBefore=6)
    S_SMALL     = style("S_SMALL",     fontName="Helvetica",        fontSize=9,  textColor=colors.HexColor("#555555"), spaceAfter=2)
    S_FULL_BODY = style("S_FULL_BODY", fontName="Helvetica",        fontSize=10, textColor=BLACK,      spaceAfter=6, leading=16, alignment=TA_JUSTIFY)
    S_OVERALL   = style("S_OVERALL",   fontName="Helvetica",        fontSize=10, textColor=colors.HexColor("#1a237e"), spaceAfter=4, leading=15, alignment=TA_JUSTIFY)

    story = []

    def section_header(text, color=DARK_BLUE):
        tbl = Table([[Paragraph(text, S_SECTION)]], colWidths=[17*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), color),
            ("ROUNDEDCORNERS", [4]),
            ("TOPPADDING",    (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
            ("LEFTPADDING",   (0,0), (-1,-1), 12),
        ]))
        return tbl

    def divider(color=GREY_LINE):
        return HRFlowable(width="100%", thickness=1, color=color, spaceAfter=6, spaceBefore=6)

    # ══════════════════════════════════════════
    # HEADER BANNER
    # ══════════════════════════════════════════
    header_data = [[
        Paragraph("Essay Feedback Report", S_TITLE),
    ]]
    header_table = Table(header_data, colWidths=[17*cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), DARK_BLUE),
        ("TOPPADDING",    (0,0), (-1,-1), 18),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
    ]))
    story.append(header_table)

    topic_data = [[Paragraph(f"Topic: {feedback.get('topic','Essay')}", S_SUBTITLE)]]
    topic_table = Table(topic_data, colWidths=[17*cm])
    topic_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), MED_BLUE),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
    ]))
    story.append(topic_table)
    story.append(Spacer(1, 10))

    # Meta info
    meta_data = [
        [Paragraph(f"<b>Student:</b> {student_name}", S_BODY),
         Paragraph(f"<b>Date:</b> {datetime.now().strftime('%B %d, %Y')}", S_BODY)],
    ]
    meta_tbl = Table(meta_data, colWidths=[8.5*cm, 8.5*cm])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), LIGHT_BLUE),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("ROUNDEDCORNERS",[3]),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 14))

    # ══════════════════════════════════════════
    # OVERALL ASSESSMENT
    # ══════════════════════════════════════════
    story.append(section_header("📊  Overall Assessment"))
    story.append(Spacer(1, 6))
    story.append(Paragraph(feedback.get("overall", ""), S_OVERALL))
    story.append(Spacer(1, 10))

    # ══════════════════════════════════════════
    # 6 KEY MISTAKES
    # ══════════════════════════════════════════
    story.append(section_header("❌  6 Key Mistakes & Corrections", ACCENT_RED))
    story.append(Spacer(1, 6))

    for m in feedback.get("mistakes", []):
        # Mistake heading
        story.append(Paragraph(
            f"<b>Mistake {m['number']} — {m['category']}</b>",
            S_MISTAKE_H
        ))

        # Incorrect / Correct table
        tbl_data = [
            [Paragraph("<b>Incorrect / Weak</b>", S_LABEL), Paragraph("<b>Correct / Improved</b>", S_LABEL)],
            [Paragraph(m.get("incorrect",""), S_BODY),       Paragraph(m.get("correct",""), S_BODY)],
        ]
        tbl = Table(tbl_data, colWidths=[8.2*cm, 8.8*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (1,0), GREY_BG),
            ("BACKGROUND",    (0,1), (0,1), SOFT_RED),
            ("BACKGROUND",    (1,1), (1,1), SOFT_GREEN),
            ("BOX",           (0,0), (-1,-1), 0.5, GREY_LINE),
            ("INNERGRID",     (0,0), (-1,-1), 0.5, GREY_LINE),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ]))
        story.append(tbl)
        story.append(Paragraph(m.get("explanation",""), S_ITALIC))
        story.append(divider())

    story.append(Spacer(1, 6))

    # ══════════════════════════════════════════
    # STRUCTURE & VOCABULARY
    # ══════════════════════════════════════════
    story.append(section_header("💡  Better Structure & Vocabulary", colors.HexColor("#4527a0")))
    story.append(Spacer(1, 8))

    # Structure
    story.append(Paragraph("<b>Structure Suggestions:</b>", S_PARA_H))
    for s in feedback.get("structure_suggestions", []):
        story.append(Paragraph(f"• {s}", S_BODY))
    story.append(Spacer(1, 8))

    # Vocabulary upgrades table
    story.append(Paragraph("<b>Vocabulary Upgrades:</b>", S_PARA_H))
    vocab = feedback.get("vocabulary_upgrades", [])
    if vocab:
        v_data = [[Paragraph("<b>Original Word</b>", S_LABEL), Paragraph("<b>Better Alternative</b>", S_LABEL)]]
        for v in vocab:
            v_data.append([
                Paragraph(f'"{v.get("original","")}"', S_BODY),
                Paragraph(f'"{v.get("better","")}"',   S_BODY),
            ])
        v_tbl = Table(v_data, colWidths=[6*cm, 11*cm])
        v_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), GREY_BG),
            ("BOX",           (0,0), (-1,-1), 0.5, GREY_LINE),
            ("INNERGRID",     (0,0), (-1,-1), 0.5, GREY_LINE),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LIGHT_BLUE]),
        ]))
        story.append(v_tbl)

    story.append(Spacer(1, 14))

    # ══════════════════════════════════════════
    # PARAGRAPH BY PARAGRAPH
    # ══════════════════════════════════════════
    story.append(section_header("📝  Structure — Paragraph by Paragraph", colors.HexColor("#00695c")))
    story.append(Spacer(1, 8))

    for para in feedback.get("paragraphs", []):
        story.append(Paragraph(para.get("name",""), S_PARA_H))

        p_data = [
            [Paragraph("<b>Student's Version</b>", S_LABEL), Paragraph("<b>Improved Version</b>", S_LABEL)],
            [Paragraph(para.get("student_version",""), S_SMALL), Paragraph(para.get("improved_version",""), S_SMALL)],
        ]
        p_tbl = Table(p_data, colWidths=[8.2*cm, 8.8*cm])
        p_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), GREY_BG),
            ("BACKGROUND",    (0,1), (0,1), SOFT_RED),
            ("BACKGROUND",    (1,1), (1,1), SOFT_GREEN),
            ("BOX",           (0,0), (-1,-1), 0.5, GREY_LINE),
            ("INNERGRID",     (0,0), (-1,-1), 0.5, GREY_LINE),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ]))
        story.append(p_tbl)
        story.append(Spacer(1, 8))

    # ══════════════════════════════════════════
    # FULL IMPROVED VERSION
    # ══════════════════════════════════════════
    story.append(section_header("⭐  Full Tailored Version", GOLD))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<i>Same ideas — corrected and enriched</i>", S_ITALIC))
    story.append(Spacer(1, 8))

    full_box_data = [[Paragraph(feedback.get("full_improved",""), S_FULL_BODY)]]
    full_box = Table(full_box_data, colWidths=[17*cm])
    full_box.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#fffde7")),
        ("BOX",           (0,0), (-1,-1), 1, GOLD),
        ("TOPPADDING",    (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING",   (0,0), (-1,-1), 14),
        ("RIGHTPADDING",  (0,0), (-1,-1), 14),
    ]))
    story.append(full_box)
    story.append(Spacer(1, 14))

    # ══════════════════════════════════════════
    # FOOTER
    # ══════════════════════════════════════════
    footer_data = [[Paragraph("🌟  Well done! Keep writing and improving every day!", S_SECTION)]]
    footer_tbl = Table(footer_data, colWidths=[17*cm])
    footer_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#2e7d32")),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
    ]))
    story.append(footer_tbl)

    doc.build(story)
    buffer.seek(0)
    return buffer


# ─── Progress Tracking ─────────────────────────────────────────────────────────
def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_progress(data: dict):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

student_progress = load_progress()

def update_progress(user_id, name, correct):
    uid = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    if uid not in student_progress:
        student_progress[uid] = {"name": name, "score": 0, "total": 0,
            "streak": 0, "last_date": "", "joined": today,
            "voice_messages": 0, "essays_checked": 0, "daily": {}}
    p = student_progress[uid]
    p["name"] = name; p["total"] += 1
    if correct: p["score"] += 1
    if today not in p["daily"]: p["daily"][today] = {"score": 0, "total": 0}
    p["daily"][today]["total"] += 1
    if correct: p["daily"][today]["score"] += 1
    last = p.get("last_date","")
    if last != today:
        try:
            diff = (datetime.strptime(today,"%Y-%m-%d") - datetime.strptime(last,"%Y-%m-%d")).days if last else 0
            p["streak"] = p.get("streak",0)+1 if diff==1 else 1
        except: p["streak"] = 1
    p["last_date"] = today
    save_progress(student_progress)

def inc_field(user_id, name, field):
    uid = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    if uid not in student_progress:
        student_progress[uid] = {"name": name, "score": 0, "total": 0,
            "streak": 0, "last_date": today, "joined": today,
            "voice_messages": 0, "essays_checked": 0, "daily": {}}
    student_progress[uid]["name"] = name
    student_progress[uid][field] = student_progress[uid].get(field, 0) + 1
    save_progress(student_progress)

# ─── Session Storage ───────────────────────────────────────────────────────────
user_sessions: dict[int, dict] = {}

def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {"history": [], "mode": "chat", "quiz_index": None}
    return user_sessions[user_id]

# ─── Claude API ────────────────────────────────────────────────────────────────
def ask_claude(user_id, message, system=None):
    session = get_session(user_id)
    session["history"].append({"role": "user", "content": message})
    history = session["history"][-12:]
    response = claude_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=system or SYSTEM_PROMPT,
        messages=history,
    )
    reply = response.content[0].text
    session["history"].append({"role": "assistant", "content": reply})
    return reply

# ─── Whisper ───────────────────────────────────────────────────────────────────
async def transcribe_voice(file_path):
    with open(file_path, "rb") as f:
        t = openai_client.audio.transcriptions.create(model="whisper-1", file=f, language="en")
    return t.text

# ─── Quiz Bank ─────────────────────────────────────────────────────────────────
QUIZ_QUESTIONS = [
    {"question":"Which word is a NOUN?\n\na) Run\nb) Happy\nc) Dog\nd) Quickly","answer":"c",
     "explanation":"🐶 **Dog** is a noun! Nouns are people, places, or things."},
    {"question":"Pick the CORRECT sentence!\n\na) She go to school.\nb) She goes to school.\nc) She going.\nd) She gone.","answer":"b",
     "explanation":"✅ **She goes to school** — add -es for he/she/it."},
    {"question":"Which word is an ADJECTIVE?\n\na) Jump\nb) Tiny\nc) Cat\nd) Slowly","answer":"b",
     "explanation":"✨ **Tiny** is an adjective — it describes nouns."},
    {"question":"Capital letters used correctly?\n\na) my dog is named max.\nb) My dog is named Max.\nc) my Dog is named max.\nd) My Dog is Named Max.","answer":"b",
     "explanation":"🎉 Sentences start with a capital. Names are always capitalized."},
    {"question":"Correct punctuation?\n\na) Do you like pizza\nb) Do you like pizza!\nc) Do you like pizza?\nd) Do you like pizza,","answer":"c",
     "explanation":"❓ Questions always end with **?**"},
    {"question":"Plural of 'child'?\n\na) Childs\nb) Childes\nc) Children\nd) Childer","answer":"c",
     "explanation":"🌈 **Children** — an irregular plural! Also: man→men, tooth→teeth."},
    {"question":"Which word is a VERB?\n\na) Beautiful\nb) Apple\nc) Swim\nd) Blue","answer":"c",
     "explanation":"🏊 **Swim** is a verb — an action word!"},
    {"question":"Correctly spelled?\n\na) Freind\nb) Frend\nc) Friend\nd) Fríend","answer":"c",
     "explanation":"✅ **Friend** — I before E: fr-I-E-nd!"},
    {"question":"'I have ___ apple.'\n\na) a\nb) an\nc) the\nd) some","answer":"b",
     "explanation":"🍎 Use **an** before vowel sounds. Apple → **an** apple."},
    {"question":"Opposite of 'hot'?\n\na) Warm\nb) Sunny\nc) Cold\nd) Big","answer":"c",
     "explanation":"❄️ **Cold** is the antonym of hot!"},
    {"question":"Which is a PRONOUN?\n\na) Run\nb) She\nc) Big\nd) House","answer":"b",
     "explanation":"👤 **She** is a pronoun. Pronouns replace names."},
    {"question":"What ends a statement?\n\na) Comma\nb) Colon\nc) Period\nd) Apostrophe","answer":"c",
     "explanation":"⭐ A **period (.)** ends a statement sentence."},
    {"question":"Which word is an ADVERB?\n\na) Cat\nb) Happy\nc) Quickly\nd) Jump","answer":"c",
     "explanation":"🚀 **Quickly** is an adverb — it describes HOW something is done."},
    {"question":"Correct sentence?\n\na) I has a cat.\nb) I have a cat.\nc) I haves a cat.\nd) I having a cat.","answer":"b",
     "explanation":"🐱 **I have a cat** — use 'have' with I, you, we, they."},
    {"question":"Synonym for 'big'?\n\na) Small\nb) Tiny\nc) Large\nd) Short","answer":"c",
     "explanation":"🐘 **Large** is a synonym for big — same meaning words are synonyms."},
]

# ─── Keyboards ─────────────────────────────────────────────────────────────────
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Ask Anything",  callback_data="mode_chat"),
         InlineKeyboardButton("📖 Learn Grammar", callback_data="mode_learn")],
        [InlineKeyboardButton("🎯 Take a Quiz",    callback_data="mode_quiz"),
         InlineKeyboardButton("💡 Homework Hint", callback_data="mode_homework")],
        [InlineKeyboardButton("🎤 Voice Practice",callback_data="mode_voice"),
         InlineKeyboardButton("✍️ Check Writing", callback_data="mode_writing")],
        [InlineKeyboardButton("🏆 My Score",      callback_data="show_score"),
         InlineKeyboardButton("📊 Progress",      callback_data="show_progress")],
        [InlineKeyboardButton("🔄 New Chat",      callback_data="reset")],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="menu")]])

# ─── /start ────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "there"
    get_session(update.effective_user.id)["mode"] = "chat"
    await update.message.reply_text(
        f"Hi {name}! 👋 I'm **{BOT_NAME}**, your AI English tutor!\n\n"
        "Here's what I can do:\n"
        "💬 Answer any English question\n"
        "📖 Explain grammar step by step\n"
        "🎯 Fun grammar quizzes\n"
        "🎤 Voice message speaking feedback\n"
        "✍️ Check your writing & get a PDF report\n"
        "💡 Homework hints\n\n"
        "What would you like to do? 😊",
        parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"⭐ **{BOT_NAME} — Help**\n\n"
        "💬 Ask Anything — Grammar questions\n"
        "📖 Learn Grammar — Step-by-step lessons\n"
        "🎯 Quiz — Test your knowledge\n"
        "🎤 Voice — Speak English, get feedback\n"
        "✍️ Check Writing — Paste essay → get PDF report\n"
        "💡 Homework — Hints only\n"
        "🏆 Score — Your quiz results\n\n"
        "/start /quiz /score /check /progress /help",
        parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    p = student_progress.get(uid)
    if not p or p.get("total",0) == 0:
        msg = "🎯 No quizzes yet! Press **Take a Quiz** to start."
    else:
        s, t = p["score"], p["total"]
        pct = int(s/t*100)
        badge = "🏆 Superstar!" if pct>=80 else "🌟 Great job!" if pct>=60 else "💪 Keep going!"
        msg = (f"📊 **Your Score**\n\n✅ Quiz: {s}/{t} ({pct}%)\n"
               f"🔥 Streak: {p.get('streak',0)} day(s)\n"
               f"🎤 Voice: {p.get('voice_messages',0)}\n"
               f"✍️ Essays: {p.get('essays_checked',0)}\n\n{badge}")
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    p = student_progress.get(uid)
    if not p:
        await update.message.reply_text("📊 No data yet! Start a quiz first.", reply_markup=main_menu_keyboard()); return
    s, t = p.get("score",0), p.get("total",0)
    pct = int(s/t*100) if t>0 else 0
    daily = ""
    for i in range(6,-1,-1):
        day = (datetime.now()-timedelta(days=i)).strftime("%Y-%m-%d")
        d = p.get("daily",{}).get(day,{"score":0,"total":0})
        if d["total"]>0:
            dp = int(d["score"]/d["total"]*100)
            bar = "█"*(dp//20)+"░"*(5-dp//20)
            daily += f"`{day[-5:]}` {bar} {d['score']}/{d['total']}\n"
    await update.message.reply_text(
        f"📈 **Progress — {p.get('name','Student')}**\n\n"
        f"🎯 Quiz: {s}/{t} ({pct}%)\n🔥 Streak: {p.get('streak',0)} day(s)\n"
        f"🎤 Voice: {p.get('voice_messages',0)}\n✍️ Essays: {p.get('essays_checked',0)}\n"
        f"📅 Joined: {p.get('joined','N/A')}\n\n**Last 7 days:**\n"
        f"{daily if daily else 'No activity yet 😊'}",
        parse_mode="Markdown", reply_markup=main_menu_keyboard())

# ─── Send Quiz ──────────────────────────────────────────────────────────────────
async def send_quiz(upd_or_q, context, user_id):
    session = get_session(user_id)
    idx = random.randint(0, len(QUIZ_QUESTIONS)-1)
    session["quiz_index"] = idx; session["mode"] = "quiz"
    q = QUIZ_QUESTIONS[idx]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("A",callback_data="quiz_a"),InlineKeyboardButton("B",callback_data="quiz_b"),
         InlineKeyboardButton("C",callback_data="quiz_c"),InlineKeyboardButton("D",callback_data="quiz_d")],
        [InlineKeyboardButton("⏭ Skip",callback_data="quiz_skip")],
        [InlineKeyboardButton("🏠 Main Menu",callback_data="menu")],
    ])
    text = f"🎯 **Quiz Time!**\n\n{q['question']}"
    if hasattr(upd_or_q,"edit_message_text"):
        await upd_or_q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await upd_or_q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

# ─── Writing Checker ───────────────────────────────────────────────────────────
async def check_writing(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name or "Student"

    await update.message.reply_text("✍️ Analyzing your writing... Generating your PDF report! ⏳")
    await context.bot.send_chat_action(update.effective_chat.id, action="upload_document")

    try:
        # Get structured feedback from Claude
        raw = ask_claude(user_id, f"Analyze this student writing:\n\n{text}", system=WRITING_SYSTEM_PROMPT)

        # Parse JSON — strip markdown fences if present
        clean = re.sub(r"```json|```", "", raw).strip()
        feedback = json.loads(clean)

        # Generate PDF
        pdf_buffer = generate_feedback_pdf(feedback, user_name)
        inc_field(user_id, user_name, "essays_checked")

        topic = feedback.get("topic", "Essay")
        filename = f"Feedback_{user_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

        await update.message.reply_document(
            document=pdf_buffer,
            filename=filename,
            caption=(
                f"✅ **Writing Feedback Ready!**\n\n"
                f"📄 Topic: *{topic}*\n"
                f"👤 Student: {user_name}\n\n"
                f"Your detailed PDF report is attached! 📎"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✍️ Check Another", callback_data="mode_writing")],
                [InlineKeyboardButton("🏠 Main Menu",     callback_data="menu")],
            ])
        )

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw: {raw[:500]}")
        # Fallback — send plain text
        await update.message.reply_text(
            f"📝 **Writing Feedback:**\n\n{raw[:3500]}",
            parse_mode="Markdown", reply_markup=main_menu_keyboard())
    except Exception as e:
        logger.error(f"Writing check error: {e}")
        await update.message.reply_text(
            "😅 Something went wrong. Please try again!", reply_markup=main_menu_keyboard())

# ─── Button Callbacks ───────────────────────────────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id   = query.from_user.id
    user_name = query.from_user.first_name or "Student"
    session   = get_session(user_id)
    data      = query.data

    if data == "menu":
        session["mode"] = "chat"
        await query.edit_message_text("What would you like to do? 😊", reply_markup=main_menu_keyboard())

    elif data == "reset":
        user_sessions[user_id] = {"history":[],"mode":"chat","quiz_index":None}
        await query.edit_message_text("🔄 Chat cleared! Fresh start. 😊", reply_markup=main_menu_keyboard())

    elif data == "show_score":
        uid = str(user_id); p = student_progress.get(uid)
        if not p or p.get("total",0)==0:
            msg = "🎯 No quizzes yet! Take a quiz to get started."
        else:
            s,t = p["score"],p["total"]; pct=int(s/t*100)
            badge = "🏆 Superstar!" if pct>=80 else "🌟 Great job!" if pct>=60 else "💪 Keep going!"
            msg = (f"📊 **Score**\n\n✅ {s}/{t} ({pct}%)\n🔥 Streak: {p.get('streak',0)}\n"
                   f"🎤 Voice: {p.get('voice_messages',0)}\n✍️ Essays: {p.get('essays_checked',0)}\n\n{badge}")
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_menu_keyboard())

    elif data == "show_progress":
        uid = str(user_id); p = student_progress.get(uid)
        if not p: msg = "📊 No data yet!"
        else:
            s,t = p.get("score",0),p.get("total",0); pct=int(s/t*100) if t>0 else 0
            msg = (f"📈 **Progress**\n\n🎯 Quiz: {s}/{t} ({pct}%)\n🔥 Streak: {p.get('streak',0)}\n"
                   f"🎤 Voice: {p.get('voice_messages',0)}\n✍️ Essays: {p.get('essays_checked',0)}")
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_menu_keyboard())

    elif data == "mode_chat":
        session["mode"] = "chat"
        await query.edit_message_text(
            "💬 **Ask Me Anything!**\n\nType any English grammar question!\n\n"
            "Examples:\n• What is a noun?\n• How do I use 'a' and 'an'?\n• What is past tense?",
            parse_mode="Markdown", reply_markup=back_keyboard())

    elif data == "mode_learn":
        session["mode"] = "learn"
        await query.edit_message_text(
            "📖 **Learn Grammar!**\n\nWhat topic do you want to learn?\n\n"
            "• Nouns, Verbs, Adjectives, Adverbs\n• Pronouns, Prepositions\n"
            "• Punctuation • Tenses • Spelling",
            parse_mode="Markdown", reply_markup=back_keyboard())

    elif data == "mode_homework":
        session["mode"] = "homework"
        await query.edit_message_text(
            "💡 **Homework Help!**\n\nTell me your homework question and I'll give hints — not the answer! 🧠",
            parse_mode="Markdown", reply_markup=back_keyboard())

    elif data == "mode_voice":
        session["mode"] = "voice"
        await query.edit_message_text(
            "🎤 **Voice Practice!**\n\nSend a voice message speaking in English!\n\n"
            "I'll check your grammar, vocabulary, and sentence structure.\n\n"
            "Try: introduce yourself, describe your day, or read from your textbook.",
            parse_mode="Markdown", reply_markup=back_keyboard())

    elif data == "mode_writing":
        session["mode"] = "writing"
        await query.edit_message_text(
            "✍️ **Writing Checker!**\n\n"
            "Paste your essay or paragraph and I will send you a **PDF report** with:\n\n"
            "❌ Top 6 mistakes with corrections\n"
            "💡 Structure & vocabulary suggestions\n"
            "⭐ Full improved version\n\n"
            "Just type or paste your writing below! 👇",
            parse_mode="Markdown", reply_markup=back_keyboard())

    elif data == "mode_quiz":
        await send_quiz(query, context, user_id)

    elif data.startswith("quiz_"):
        if session.get("quiz_index") is None:
            await query.edit_message_text("No active quiz!", reply_markup=main_menu_keyboard()); return
        if data == "quiz_skip":
            await query.edit_message_text("⏭ Skipped!", reply_markup=None)
            await send_quiz(query, context, user_id); return
        ans_map = {"quiz_a":"a","quiz_b":"b","quiz_c":"c","quiz_d":"d"}
        chosen = ans_map.get(data)
        q = QUIZ_QUESTIONS[session["quiz_index"]]
        correct = chosen == q["answer"]
        update_progress(user_id, user_name, correct)
        p = student_progress.get(str(user_id),{})
        s,t = p.get("score",0),p.get("total",0)
        result = (f"🎉 **Correct! Well done!**\n\n{q['explanation']}" if correct else
                  f"🤔 **Not quite! Answer was {q['answer'].upper()}.**\n\n{q['explanation']}")
        result += f"\n\n📊 Score: {s}/{t}"
        await query.edit_message_text(result, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ Next Question", callback_data="mode_quiz")],
            [InlineKeyboardButton("🏠 Main Menu",     callback_data="menu")],
        ]))
        session["quiz_index"] = None

# ─── Voice Handler ──────────────────────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name or "Student"
    await update.message.reply_text("🎤 Voice received! Analyzing... ⏳")
    await context.bot.send_chat_action(update.effective_chat.id, action="typing")
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        transcript = await transcribe_voice(tmp_path)
        os.unlink(tmp_path)
        if not transcript.strip():
            await update.message.reply_text("😅 Couldn't hear clearly. Try again! 🎤", reply_markup=main_menu_keyboard()); return
        inc_field(user_id, user_name, "voice_messages")
        reply = ask_claude(user_id, f'Student said: "{transcript}"\nGive feedback.', system=VOICE_SYSTEM_PROMPT)
        await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎤 Try Again",  callback_data="mode_voice")],
            [InlineKeyboardButton("🏠 Main Menu",  callback_data="menu")],
        ]))
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text("😅 Something went wrong. Try again!", reply_markup=main_menu_keyboard())

# ─── Text Handler ───────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    text    = update.message.text.strip()
    mode    = session.get("mode","chat")

    if mode == "writing":
        if len(text) < 30:
            await update.message.reply_text(
                "📝 Please send a longer text (at least a few sentences) for me to analyze! 😊",
                reply_markup=back_keyboard()); return
        await check_writing(update, context, text); return

    if mode == "homework":
        prompt = f"[HOMEWORK HINT] Hints only, NOT the answer: {text}"
    elif mode == "learn":
        prompt = f"[LEARN] Explain step-by-step for K-5: {text}"
    elif mode == "voice":
        prompt = f"[Student typed. Remind them to send voice, but answer if they asked a question]: {text}"
    else:
        prompt = text

    await context.bot.send_chat_action(update.effective_chat.id, action="typing")
    try:
        reply = ask_claude(user_id, prompt)
    except Exception as e:
        logger.error(f"Claude error: {e}"); reply = "😅 Something went wrong. Try again!"
    await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=back_keyboard())

# ─── Commands ──────────────────────────────────────────────────────────────────
async def quiz_command(update, context):
    await send_quiz(update, context, update.effective_user.id)

async def check_command(update, context):
    get_session(update.effective_user.id)["mode"] = "writing"
    await update.message.reply_text(
        "✍️ **Writing Checker!**\n\nPaste your essay and I'll send you a PDF report! 👇",
        parse_mode="Markdown", reply_markup=back_keyboard())

async def learn_command(update, context):
    get_session(update.effective_user.id)["mode"] = "learn"
    await update.message.reply_text(
        "📖 What topic would you like to learn?", reply_markup=back_keyboard())

# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"⭐ Starting {BOT_NAME}...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     help_command))
    app.add_handler(CommandHandler("quiz",     quiz_command))
    app.add_handler(CommandHandler("learn",    learn_command))
    app.add_handler(CommandHandler("score",    score_command))
    app.add_handler(CommandHandler("check",    check_command))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
