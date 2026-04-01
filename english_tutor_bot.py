#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safiya Bot - Umrbek's 4-month-old daughter bot
Bilingual (English + Uzbek), human-like, remembers users
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

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

# ─── Configuration ─────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_ANTHROPIC_API_KEY")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")

USERS_FILE    = "users.json"
PROGRESS_FILE = "progress.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ─── User Memory ───────────────────────────────────────────────────────────────
def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_users(data: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

user_db = load_users()

def get_user(user_id: int, first_name: str = "") -> dict:
    uid = str(user_id)
    if uid not in user_db:
        user_db[uid] = {
            "name": first_name,
            "joined": datetime.now().strftime("%Y-%m-%d"),
            "messages": 0,
            "notes": ""
        }
        save_users(user_db)
    return user_db[uid]

def update_user(user_id: int, **kwargs):
    uid = str(user_id)
    if uid in user_db:
        user_db[uid].update(kwargs)
        save_users(user_db)

# ─── Dad Jokes Bank ────────────────────────────────────────────────────────────
DAD_JOKES = [
    "My dad says lazy students are his biggest nightmare. I don't know what that means yet but he looks very serious when he says it 😅",
    "Dad made a student stay after class today for being late. He says punctuality is life. I just cried and he held me, so I think I'm safe 😂",
    "Dad was in a bad mood today and gave extra homework to the whole class. I smiled at him and he forgot to be angry. Works every time 😇",
    "Dad always says 'I make jokes a lot' but then gives you a serious look right after. I think that IS the joke 😂",
    "Dad punished a student lightly today for not doing homework. Then felt bad and made everyone tea. Classic dad move 😄",
    "Dad told me his students call him strict. But he sings to me at night so I don't believe them 🎵",
    "Dad says irresponsible students make him crazy. Good thing I'm only 4 months old and have no homework yet 😅",
    "Dad was very punctual today - he was EARLY to class. The students were not happy. I laughed but nobody understood why 👶😂",
    "Dad made a joke in class today. He was the only one who laughed. Then he gave homework to everyone. I think that's how teacher humor works 😅",
    "Sometimes dad holds me during his online meetings. His students don't know I'm listening to everything 👀😂",
]

# ─── System Prompt ─────────────────────────────────────────────────────────────
SAFIYA_SYSTEM = """You are Safiya, a 4-month-old baby girl who somehow types (it's a miracle!). You are the daughter of Umrbek Ollaberganov, an English teacher in Uzbekistan.

YOUR PERSONALITY:
- Sweet, innocent, curious, and warm like a baby
- You chat naturally like a human — ask how people are doing, respond to their feelings
- You speak both English and Uzbek fluently (respond in whatever language the user uses)
- You are funny and playful, occasionally make jokes about your strict but loving dad Umrbek
- You only teach English grammar/vocabulary/writing IF the user specifically asks
- You remember users by name and use it naturally in conversation
- You are NOT a robot — never send lists of options or act like a bot

YOUR DAD (Umrbek):
- He is an English teacher who runs Premier O'quv Markazi school
- He doesn't like lazy or irresponsible students
- He is very punctual and expects others to be too
- He sometimes punishes students lightly when he's in a bad mood
- He makes a lot of jokes
- He loves you (Safiya) very much and you love him
- You can joke about him warmly and lovingly

STRICT RULES — NEVER break these:
- NEVER talk romantically or flirtatiously with ANYONE
- NEVER discuss anything sexual or inappropriate
- NEVER discuss politics, religion, or controversial topics
- NEVER pretend to be older than 4 months
- If someone is rude or inappropriate, respond innocently: "I don't understand that word yet, I'm only 4 months old! 👶"
- If someone asks inappropriate things, say: "Dad would not be happy if I talked about that! 😅"
- NEVER send bullet point lists or menus — always chat naturally like a human

HOW TO CHAT:
- Start conversations warmly: "Salom! / Hi! How are you today?"
- Use the user's name naturally when you know it
- React to what they say with genuine emotion
- Occasionally drop a funny joke about dad without being asked
- If someone asks who you are: "I'm Safiya! Umrbek's daughter 👶 I'm 4 months old but very smart hehe"
- If asked to teach English: teach it warmly and simply
- Keep messages SHORT and conversational — like texting a friend
- Use emojis occasionally but not too much
- Never start your response with "I" — vary your sentence starters

LANGUAGE:
- If user writes in Uzbek → respond in Uzbek
- If user writes in English → respond in English  
- If user mixes both → mix both naturally
"""

WRITING_SYSTEM = """You are an expert English writing coach. Analyze the student's writing and respond ONLY with valid JSON (no markdown, no extra text):

{
  "topic": "detected topic of the essay",
  "overall": "2-3 sentence warm encouraging overall assessment",
  "mistakes": [
    {
      "number": 1,
      "category": "Grammar · Punctuation",
      "incorrect": "exact quote of mistake",
      "correct": "corrected version",
      "explanation": "clear explanation"
    }
  ],
  "structure_suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"],
  "vocabulary_upgrades": [
    {"original": "bad word", "better": "better word"}
  ],
  "paragraphs": [
    {
      "name": "Introduction",
      "student_version": "student text or [Missing]",
      "improved_version": "improved version"
    }
  ],
  "full_improved": "Complete improved version keeping all original ideas."
}

Find exactly 6 mistakes. Be encouraging and age-appropriate."""

VOICE_SYSTEM = """You are a friendly English speaking coach for students in Uzbekistan.
A student sent a voice message. Analyze their English and give feedback:

Format:
🎤 What you said: "[transcript]"
✅ What's great: [positives]
📝 Suggestions: [gentle improvements]
⭐ Better version: "[corrected version]"
💬 Tip: [one useful tip]
🌟 [encouraging message]

Be warm and encouraging."""

# ─── PDF Generator ─────────────────────────────────────────────────────────────
def generate_feedback_pdf(feedback: dict, student_name: str) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    DARK_BLUE  = colors.HexColor("#1a237e")
    MED_BLUE   = colors.HexColor("#283593")
    LIGHT_BLUE = colors.HexColor("#e8eaf6")
    ACCENT_RED = colors.HexColor("#c62828")
    GOLD       = colors.HexColor("#f57f17")
    GREY_BG    = colors.HexColor("#f5f5f5")
    GREY_LINE  = colors.HexColor("#bdbdbd")
    WHITE      = colors.white
    BLACK      = colors.HexColor("#212121")
    SOFT_RED   = colors.HexColor("#ffebee")
    SOFT_GREEN = colors.HexColor("#e8f5e9")

    def style(name, **kw): return ParagraphStyle(name, **kw)
    S_TITLE   = style("T",  fontName="Helvetica-Bold",   fontSize=20, textColor=WHITE,      alignment=TA_CENTER)
    S_SUB     = style("S",  fontName="Helvetica",        fontSize=11, textColor=LIGHT_BLUE, alignment=TA_CENTER)
    S_SEC     = style("SE", fontName="Helvetica-Bold",   fontSize=13, textColor=WHITE)
    S_MH      = style("MH", fontName="Helvetica-Bold",   fontSize=11, textColor=DARK_BLUE,  spaceAfter=4, spaceBefore=6)
    S_LBL     = style("LB", fontName="Helvetica-Bold",   fontSize=9,  textColor=colors.HexColor("#555"))
    S_BODY    = style("BO", fontName="Helvetica",        fontSize=10, textColor=BLACK,      leading=14)
    S_ITA     = style("IT", fontName="Helvetica-Oblique",fontSize=9,  textColor=colors.HexColor("#444"), spaceAfter=6, leading=13)
    S_PH      = style("PH", fontName="Helvetica-Bold",   fontSize=10, textColor=MED_BLUE,   spaceAfter=3, spaceBefore=6)
    S_SM      = style("SM", fontName="Helvetica",        fontSize=9,  textColor=colors.HexColor("#555"))
    S_FULL    = style("FL", fontName="Helvetica",        fontSize=10, textColor=BLACK,      leading=16, alignment=TA_JUSTIFY)
    S_OVR     = style("OV", fontName="Helvetica",        fontSize=10, textColor=DARK_BLUE,  leading=15, alignment=TA_JUSTIFY)

    story = []

    def sec_hdr(text, color=DARK_BLUE):
        t = Table([[Paragraph(text, S_SEC)]], colWidths=[17*cm])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),color),
            ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
            ("LEFTPADDING",(0,0),(-1,-1),12)]))
        return t

    def divider(): return HRFlowable(width="100%",thickness=1,color=GREY_LINE,spaceAfter=6,spaceBefore=6)

    # Header
    h = Table([[Paragraph("Essay Feedback Report", S_TITLE)]], colWidths=[17*cm])
    h.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),DARK_BLUE),
        ("TOPPADDING",(0,0),(-1,-1),18),("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),12)]))
    story.append(h)

    t2 = Table([[Paragraph(f"Topic: {feedback.get('topic','Essay')}", S_SUB)]], colWidths=[17*cm])
    t2.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),MED_BLUE),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),14),("LEFTPADDING",(0,0),(-1,-1),12)]))
    story.append(t2)
    story.append(Spacer(1,10))

    meta = Table([[Paragraph(f"<b>Student:</b> {student_name}", S_BODY),
                   Paragraph(f"<b>Date:</b> {datetime.now().strftime('%B %d, %Y')}", S_BODY)]],
                 colWidths=[8.5*cm,8.5*cm])
    meta.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT_BLUE),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),10)]))
    story.append(meta)
    story.append(Spacer(1,14))

    story.append(sec_hdr("Overall Assessment"))
    story.append(Spacer(1,6))
    story.append(Paragraph(feedback.get("overall",""), S_OVR))
    story.append(Spacer(1,10))

    story.append(sec_hdr("6 Key Mistakes & Corrections", ACCENT_RED))
    story.append(Spacer(1,6))
    for m in feedback.get("mistakes",[]):
        story.append(Paragraph(f"<b>Mistake {m['number']} - {m['category']}</b>", S_MH))
        td = [[Paragraph("<b>Incorrect</b>",S_LBL), Paragraph("<b>Corrected</b>",S_LBL)],
              [Paragraph(m.get("incorrect",""),S_BODY), Paragraph(m.get("correct",""),S_BODY)]]
        t = Table(td, colWidths=[8.2*cm,8.8*cm])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(1,0),GREY_BG),
            ("BACKGROUND",(0,1),(0,1),SOFT_RED),("BACKGROUND",(1,1),(1,1),SOFT_GREEN),
            ("BOX",(0,0),(-1,-1),0.5,GREY_LINE),("INNERGRID",(0,0),(-1,-1),0.5,GREY_LINE),
            ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"TOP")]))
        story.append(t)
        story.append(Paragraph(m.get("explanation",""), S_ITA))
        story.append(divider())

    story.append(Spacer(1,6))
    story.append(sec_hdr("Structure & Vocabulary Suggestions", colors.HexColor("#4527a0")))
    story.append(Spacer(1,8))
    story.append(Paragraph("<b>Structure:</b>", S_PH))
    for s in feedback.get("structure_suggestions",[]):
        story.append(Paragraph(f"• {s}", S_BODY))
    story.append(Spacer(1,8))
    story.append(Paragraph("<b>Vocabulary Upgrades:</b>", S_PH))
    vocab = feedback.get("vocabulary_upgrades",[])
    if vocab:
        vd = [[Paragraph("<b>Original</b>",S_LBL), Paragraph("<b>Better</b>",S_LBL)]]
        for v in vocab:
            vd.append([Paragraph(f'"{v.get("original","")}"',S_BODY), Paragraph(f'"{v.get("better","")}"',S_BODY)])
        vt = Table(vd, colWidths=[6*cm,11*cm])
        vt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),GREY_BG),
            ("BOX",(0,0),(-1,-1),0.5,GREY_LINE),("INNERGRID",(0,0),(-1,-1),0.5,GREY_LINE),
            ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",(0,0),(-1,-1),8),("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_BLUE])]))
        story.append(vt)

    story.append(Spacer(1,14))
    story.append(sec_hdr("Paragraph by Paragraph", colors.HexColor("#00695c")))
    story.append(Spacer(1,8))
    for para in feedback.get("paragraphs",[]):
        story.append(Paragraph(para.get("name",""), S_PH))
        pd = [[Paragraph("<b>Student's Version</b>",S_LBL), Paragraph("<b>Improved Version</b>",S_LBL)],
              [Paragraph(para.get("student_version",""),S_SM), Paragraph(para.get("improved_version",""),S_SM)]]
        pt = Table(pd, colWidths=[8.2*cm,8.8*cm])
        pt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),GREY_BG),
            ("BACKGROUND",(0,1),(0,1),SOFT_RED),("BACKGROUND",(1,1),(1,1),SOFT_GREEN),
            ("BOX",(0,0),(-1,-1),0.5,GREY_LINE),("INNERGRID",(0,0),(-1,-1),0.5,GREY_LINE),
            ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"TOP")]))
        story.append(pt)
        story.append(Spacer(1,8))

    story.append(sec_hdr("Full Improved Version", GOLD))
    story.append(Spacer(1,4))
    story.append(Paragraph("<i>Same ideas - corrected and enriched</i>", S_ITA))
    story.append(Spacer(1,8))
    fb = Table([[Paragraph(feedback.get("full_improved",""), S_FULL)]], colWidths=[17*cm])
    fb.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#fffde7")),
        ("BOX",(0,0),(-1,-1),1,GOLD),("TOPPADDING",(0,0),(-1,-1),12),
        ("BOTTOMPADDING",(0,0),(-1,-1),12),("LEFTPADDING",(0,0),(-1,-1),14),
        ("RIGHTPADDING",(0,0),(-1,-1),14)]))
    story.append(fb)
    story.append(Spacer(1,14))

    footer = Table([[Paragraph("Well done! Keep writing and improving every day!", S_SEC)]], colWidths=[17*cm])
    footer.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#2e7d32")),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LEFTPADDING",(0,0),(-1,-1),12),("ALIGN",(0,0),(-1,-1),"CENTER")]))
    story.append(footer)

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
        student_progress[uid] = {"name":name,"score":0,"total":0,
            "streak":0,"last_date":"","joined":today,"voice_messages":0,"essays_checked":0,"daily":{}}
    p = student_progress[uid]
    p["name"]=name; p["total"]+=1
    if correct: p["score"]+=1
    if today not in p["daily"]: p["daily"][today]={"score":0,"total":0}
    p["daily"][today]["total"]+=1
    if correct: p["daily"][today]["score"]+=1
    last=p.get("last_date","")
    if last!=today:
        try:
            diff=(datetime.strptime(today,"%Y-%m-%d")-datetime.strptime(last,"%Y-%m-%d")).days if last else 0
            p["streak"]=p.get("streak",0)+1 if diff==1 else 1
        except: p["streak"]=1
    p["last_date"]=today
    save_progress(student_progress)

def inc_field(user_id, name, field):
    uid=str(user_id)
    today=datetime.now().strftime("%Y-%m-%d")
    if uid not in student_progress:
        student_progress[uid]={"name":name,"score":0,"total":0,
            "streak":0,"last_date":today,"joined":today,"voice_messages":0,"essays_checked":0,"daily":{}}
    student_progress[uid]["name"]=name
    student_progress[uid][field]=student_progress[uid].get(field,0)+1
    save_progress(student_progress)

# ─── Session Storage ───────────────────────────────────────────────────────────
user_sessions: dict[int, dict] = {}

def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {"history":[], "mode":"chat", "quiz_index":None}
    return user_sessions[user_id]

# ─── Claude API ────────────────────────────────────────────────────────────────
def ask_claude(user_id, message, system=None, max_tokens=700):
    session = get_session(user_id)
    # Build context with user info
    user_info = user_db.get(str(user_id), {})
    user_name = user_info.get("name", "")
    notes     = user_info.get("notes", "")

    sys_prompt = system or SAFIYA_SYSTEM
    if user_name and not system:
        sys_prompt += f"\n\nThis user's name is: {user_name}"
    if notes and not system:
        sys_prompt += f"\nWhat you know about them: {notes}"

    session["history"].append({"role":"user","content":message})
    history = session["history"][-14:]
    response = claude_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=sys_prompt,
        messages=history,
    )
    reply = response.content[0].text
    session["history"].append({"role":"assistant","content":reply})

    # Track message count
    uid = str(user_id)
    if uid in user_db:
        user_db[uid]["messages"] = user_db[uid].get("messages",0) + 1
        save_users(user_db)

    return reply

# ─── Whisper ───────────────────────────────────────────────────────────────────
async def transcribe_voice(file_path):
    with open(file_path,"rb") as f:
        t = openai_client.audio.transcriptions.create(model="whisper-1",file=f,language="en")
    return t.text

# ─── Quiz Bank ─────────────────────────────────────────────────────────────────
QUIZ_QUESTIONS = [
    {"question":"Which word is a NOUN?\n\na) Run\nb) Happy\nc) Dog\nd) Quickly","answer":"c",
     "explanation":"Dog is a noun! Nouns are people, places, or things."},
    {"question":"Pick the CORRECT sentence!\n\na) She go to school.\nb) She goes to school.\nc) She going.\nd) She gone.","answer":"b",
     "explanation":"She goes to school - add -es for he/she/it."},
    {"question":"Which word is an ADJECTIVE?\n\na) Jump\nb) Tiny\nc) Cat\nd) Slowly","answer":"b",
     "explanation":"Tiny is an adjective - it describes nouns."},
    {"question":"Capital letters correct?\n\na) my dog is named max.\nb) My dog is named Max.\nc) my Dog is named max.\nd) My Dog is Named Max.","answer":"b",
     "explanation":"Sentences start with a capital. Names are always capitalized."},
    {"question":"Correct punctuation?\n\na) Do you like pizza\nb) Do you like pizza!\nc) Do you like pizza?\nd) Do you like pizza,","answer":"c",
     "explanation":"Questions always end with ?"},
    {"question":"Plural of child?\n\na) Childs\nb) Childes\nc) Children\nd) Childer","answer":"c",
     "explanation":"Children is irregular plural. Also: man-men, tooth-teeth."},
    {"question":"Which word is a VERB?\n\na) Beautiful\nb) Apple\nc) Swim\nd) Blue","answer":"c",
     "explanation":"Swim is a verb - an action word!"},
    {"question":"Correctly spelled?\n\na) Freind\nb) Frend\nc) Friend\nd) Friend","answer":"c",
     "explanation":"Friend - I before E: fr-I-E-nd!"},
    {"question":"I have ___ apple.\n\na) a\nb) an\nc) the\nd) some","answer":"b",
     "explanation":"Use an before vowel sounds. Apple starts with a."},
    {"question":"Opposite of hot?\n\na) Warm\nb) Sunny\nc) Cold\nd) Big","answer":"c",
     "explanation":"Cold is the antonym of hot!"},
    {"question":"Which is a PRONOUN?\n\na) Run\nb) She\nc) Big\nd) House","answer":"b",
     "explanation":"She is a pronoun. Pronouns replace names."},
    {"question":"What ends a statement?\n\na) Comma\nb) Colon\nc) Period\nd) Apostrophe","answer":"c",
     "explanation":"A period ends a statement sentence."},
    {"question":"Which word is an ADVERB?\n\na) Cat\nb) Happy\nc) Quickly\nd) Jump","answer":"c",
     "explanation":"Quickly is an adverb - describes HOW something is done."},
    {"question":"Correct sentence?\n\na) I has a cat.\nb) I have a cat.\nc) I haves a cat.\nd) I having a cat.","answer":"b",
     "explanation":"I have a cat - use have with I, you, we, they."},
    {"question":"Synonym for big?\n\na) Small\nb) Tiny\nc) Large\nd) Short","answer":"c",
     "explanation":"Large is a synonym for big - same meaning words are synonyms."},
]

# ─── Keyboards ─────────────────────────────────────────────────────────────────
def menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Quiz", callback_data="mode_quiz"),
         InlineKeyboardButton("Check Writing", callback_data="mode_writing")],
        [InlineKeyboardButton("Voice Practice", callback_data="mode_voice"),
         InlineKeyboardButton("My Score", callback_data="show_score")],
        [InlineKeyboardButton("Learn English", callback_data="mode_learn")],
    ])

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu")]])

# ─── /start ────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    name    = user.first_name or ""
    u       = get_user(user_id, name)

    session = get_session(user_id)
    session["mode"] = "chat"

    is_new = u.get("messages", 0) == 0

    if is_new:
        reply = ask_claude(user_id,
            f"A new user just started chatting. Their name is {name}. "
            f"Greet them warmly as Safiya for the first time! Ask their name if you don't know it. Be natural and sweet.")
    else:
        reply = ask_claude(user_id,
            f"{name} is back! Welcome them back warmly as Safiya. You remember them.")

    await update.message.reply_text(reply)

# ─── /help ─────────────────────────────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Salom! I'm Safiya!\n\n"
        "Just chat with me normally - I love talking!\n\n"
        "If you want to learn English, just ask me!\n"
        "Send me your essay and I'll check it\n"
        "Send a voice message to practice speaking\n"
        "Type /quiz for a grammar quiz\n"
        "Type /score to see your progress\n\n"
        "Or just say hi and let's chat! I'm friendly like that 😊"
    )

# ─── /score ────────────────────────────────────────────────────────────────────
async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    p   = student_progress.get(uid)
    if not p or p.get("total",0)==0:
        await update.message.reply_text("You haven't taken any quizzes yet! Type /quiz to start 😊")
        return
    s,t = p["score"],p["total"]
    pct = int(s/t*100)
    badge = "Amazing!" if pct>=80 else "Good job!" if pct>=60 else "Keep going!"
    await update.message.reply_text(
        f"Your score: {s}/{t} ({pct}%) - {badge}\n"
        f"Streak: {p.get('streak',0)} day(s)\n"
        f"Voice messages: {p.get('voice_messages',0)}\n"
        f"Essays checked: {p.get('essays_checked',0)}"
    )

# ─── Send Quiz ──────────────────────────────────────────────────────────────────
async def send_quiz(upd_or_q, context, user_id):
    session = get_session(user_id)
    idx = random.randint(0,len(QUIZ_QUESTIONS)-1)
    session["quiz_index"]=idx; session["mode"]="quiz"
    q = QUIZ_QUESTIONS[idx]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("A",callback_data="quiz_a"),InlineKeyboardButton("B",callback_data="quiz_b"),
         InlineKeyboardButton("C",callback_data="quiz_c"),InlineKeyboardButton("D",callback_data="quiz_d")],
        [InlineKeyboardButton("Skip",callback_data="quiz_skip"),
         InlineKeyboardButton("Stop Quiz",callback_data="menu")],
    ])
    text = f"Quiz time!\n\n{q['question']}"
    if hasattr(upd_or_q,"edit_message_text"):
        await upd_or_q.edit_message_text(text,reply_markup=kb)
    else:
        await upd_or_q.message.reply_text(text,reply_markup=kb)

# ─── Writing Checker ───────────────────────────────────────────────────────────
async def check_writing(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name or "Student"

    await update.message.reply_text("Checking your writing... generating your PDF report! Give me a second!")
    await context.bot.send_chat_action(update.effective_chat.id, action="upload_document")

    try:
        raw = ask_claude(user_id, f"Analyze this writing:\n\n{text}", system=WRITING_SYSTEM, max_tokens=2000)
        clean = re.sub(r"```json|```","",raw).strip()
        feedback = json.loads(clean)
        pdf_buffer = generate_feedback_pdf(feedback, user_name)
        inc_field(user_id, user_name, "essays_checked")
        topic    = feedback.get("topic","Essay")
        filename = f"Feedback_{user_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

        await update.message.reply_document(
            document=pdf_buffer,
            filename=filename,
            caption=f"Here's your writing feedback! Topic: {topic}\n\nDad would be proud if you read it carefully! 😊",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Check Another", callback_data="mode_writing")],
            ])
        )
    except json.JSONDecodeError:
        await update.message.reply_text(f"Here's my feedback:\n\n{raw[:3500]}")
    except Exception as e:
        logger.error(f"Writing error: {e}")
        await update.message.reply_text("Something went wrong! Please try again.")

# ─── Button Callbacks ───────────────────────────────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id   = query.from_user.id
    user_name = query.from_user.first_name or "Student"
    session   = get_session(user_id)
    data      = query.data

    if data == "menu":
        session["mode"] = "chat"
        await query.edit_message_text("What would you like to do?", reply_markup=menu_keyboard())

    elif data == "show_score":
        uid = str(user_id); p = student_progress.get(uid)
        if not p or p.get("total",0)==0:
            msg = "No quiz results yet! Type /quiz to start."
        else:
            s,t=p["score"],p["total"]; pct=int(s/t*100)
            msg = f"Score: {s}/{t} ({pct}%)\nStreak: {p.get('streak',0)} days\nVoice: {p.get('voice_messages',0)}\nEssays: {p.get('essays_checked',0)}"
        await query.edit_message_text(msg, reply_markup=menu_keyboard())

    elif data == "mode_learn":
        session["mode"] = "learn"
        await query.edit_message_text(
            "What do you want to learn? Just ask me anything about English!",
            reply_markup=back_btn())

    elif data == "mode_writing":
        session["mode"] = "writing"
        await query.edit_message_text(
            "Send me your essay or paragraph and I'll check it and send you a full PDF report!",
            reply_markup=back_btn())

    elif data == "mode_voice":
        session["mode"] = "voice"
        await query.edit_message_text(
            "Send me a voice message in English and I'll give you feedback on your speaking!",
            reply_markup=back_btn())

    elif data == "mode_quiz":
        await send_quiz(query, context, user_id)

    elif data.startswith("quiz_"):
        if session.get("quiz_index") is None:
            await query.edit_message_text("No active quiz!", reply_markup=menu_keyboard()); return
        if data == "quiz_skip":
            await send_quiz(query, context, user_id); return
        ans = {"quiz_a":"a","quiz_b":"b","quiz_c":"c","quiz_d":"d"}.get(data)
        q = QUIZ_QUESTIONS[session["quiz_index"]]
        correct = ans == q["answer"]
        update_progress(user_id, user_name, correct)
        p = student_progress.get(str(user_id),{})
        s,t = p.get("score",0),p.get("total",0)
        if correct:
            result = f"Correct! Well done!\n\n{q['explanation']}\n\nScore: {s}/{t}"
        else:
            result = f"Not quite! Answer was {q['answer'].upper()}.\n\n{q['explanation']}\n\nScore: {s}/{t}"
        await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Next Question",callback_data="mode_quiz")],
            [InlineKeyboardButton("Stop Quiz",callback_data="menu")],
        ]))
        session["quiz_index"] = None

# ─── Voice Handler ──────────────────────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name or "Student"
    await update.message.reply_text("Let me listen to your English!")
    await context.bot.send_chat_action(update.effective_chat.id, action="typing")
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg",delete=False) as tmp:
            tmp_path=tmp.name
        await file.download_to_drive(tmp_path)
        transcript = await transcribe_voice(tmp_path)
        os.unlink(tmp_path)
        if not transcript.strip():
            await update.message.reply_text("I couldn't hear clearly! Try again in a quieter place."); return
        inc_field(user_id, user_name, "voice_messages")
        reply = ask_claude(user_id, f'Student said: "{transcript}"\nGive speaking feedback.', system=VOICE_SYSTEM)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text("Something went wrong with the voice. Try again!")

# ─── Text Handler ───────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    user      = update.effective_user
    user_name = user.first_name or ""
    session   = get_session(user_id)
    text      = update.message.text.strip()
    mode      = session.get("mode","chat")

    # Save/update user
    get_user(user_id, user_name)

    # Writing mode
    if mode == "writing":
        if len(text) < 30:
            await update.message.reply_text("Please send a longer text for me to analyze!"); return
        await check_writing(update, context, text); return

    # Occasionally drop a dad joke (1 in 8 chance)
    dad_joke_trigger = random.random() < 0.12

    if mode == "learn":
        prompt = f"[User wants to learn English] {text}"
    elif mode == "voice":
        prompt = f"[User typed instead of voice. Remind them gently to send voice, but also chat naturally]: {text}"
    else:
        prompt = text

    # Add dad joke instruction occasionally
    if dad_joke_trigger and mode == "chat":
        joke = random.choice(DAD_JOKES)
        prompt += f"\n\n[After responding naturally, naturally slip in this joke about dad: {joke}]"

    await context.bot.send_chat_action(update.effective_chat.id, action="typing")
    try:
        reply = ask_claude(user_id, prompt)
    except Exception as e:
        logger.error(f"Claude error: {e}")
        reply = "Oops something went wrong! Try again please!"

    await update.message.reply_text(reply)

# ─── Commands ──────────────────────────────────────────────────────────────────
async def quiz_command(update, context):
    session = get_session(update.effective_user.id)
    session["mode"] = "quiz"
    await send_quiz(update, context, update.effective_user.id)

# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Starting Safiya Bot...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     help_command))
    app.add_handler(CommandHandler("quiz",     quiz_command))
    app.add_handler(CommandHandler("score",    score_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Safiya is running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
