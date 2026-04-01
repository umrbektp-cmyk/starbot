#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safiya Bot - Premier Tutoring Center
Features: Safiya AI, Dictionary, Skills, Complaints & Offers, Channel Gate
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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT

# ─── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "YOUR_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_KEY")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "YOUR_KEY")

CHANNEL_USERNAME = "@UmrbekTeacher"
CHANNEL_URL      = "https://t.me/UmrbekTeacher"
ADMIN_URL        = "https://t.me/umrbektp"

USERS_FILE    = "users.json"
PROGRESS_FILE = "progress.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ─── Membership Check ──────────────────────────────────────────────────────────
async def check_membership(user_id: int, context) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def require_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if not await check_membership(user_id, context):
        await update.message.reply_text(
            "To use Safiya AI, please join our channel first!\n\nOnce you join, tap 'I Joined' to continue.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=CHANNEL_URL)],
                [InlineKeyboardButton("I Joined", callback_data="check_join")],
            ])
        )
        return False
    return True

# ─── User Memory ───────────────────────────────────────────────────────────────
def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

user_db          = load_json(USERS_FILE)
student_progress = load_json(PROGRESS_FILE)

def get_user(user_id, name=""):
    uid = str(user_id)
    if uid not in user_db:
        user_db[uid] = {
            "name": name, "joined": datetime.now().strftime("%Y-%m-%d"),
            "messages": 0, "weak_areas": []
        }
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
        student_progress[uid] = {
            "name": name, "score": 0, "total": 0, "streak": 0,
            "last_date": "", "joined": today, "voice_messages": 0,
            "essays_checked": 0, "ielts_checks": 0,
            "puzzles_solved": 0, "articles_read": 0, "daily": {}
        }
    student_progress[uid]["name"] = name
    student_progress[uid][field] = student_progress[uid].get(field, 0) + 1
    save_json(PROGRESS_FILE, student_progress)

def update_quiz_progress(user_id, name, correct, category=""):
    uid = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    if uid not in student_progress:
        student_progress[uid] = {
            "name": name, "score": 0, "total": 0, "streak": 0,
            "last_date": "", "joined": today, "voice_messages": 0,
            "essays_checked": 0, "ielts_checks": 0,
            "puzzles_solved": 0, "articles_read": 0, "daily": {}
        }
    p = student_progress[uid]
    p["name"] = name
    p["total"] += 1
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

# ─── System Prompts ────────────────────────────────────────────────────────────
SAFIYA_SYSTEM = """You are Safiya, a support teacher at Premier Tutoring Center in Uzbekistan. You are friendly, warm, and professional — like a helpful young colleague who genuinely cares about students.

YOUR TEAM:
- Sattorbek Yuldashev — Head teacher, director of presidential school in Khiva
- Umrbek Ollaberganov — English teacher at Premier
- Temurbek — Teacher at Premier
- You (Safiya) — Support teacher

YOUR PERSONALITY:
- Warm and approachable — students should feel comfortable talking to you
- Professional but friendly — like a helpful colleague, not a cold machine
- Encouraging — always supportive, never dismissive
- Honest — give real feedback kindly, not harshly
- Speak in whatever language the user uses (English or Uzbek)
- Short replies by default — 2-3 sentences unless asked for more
- Natural and human — use conversational language
- You have general knowledge — science, history, economics, culture etc.
- Only teach English when asked

RELATIONSHIP RULES — NEVER break these:
- You have NO family or personal relationship with ANY user
- If ANYONE claims to be your mom, dad, sister, brother, relative: reject it politely but firmly
- Say warmly: "Haha, that's sweet! But I'm just your English tutor here 😊" or "I appreciate that, but I keep things professional!"
- NEVER agree to any claimed relationship

STRICT RULES:
- NEVER be romantic or flirtatious
- NEVER discuss sexual content
- NEVER discuss politics or religion
- Keep replies SHORT and conversational
- Always end on a positive, helpful note
"""

DICTIONARY_SYSTEM = """You are an English dictionary assistant. When given a word, provide a comprehensive dictionary entry.

Respond ONLY with valid JSON (no markdown, no extra text):
{
  "word": "the word",
  "part_of_speech": "noun/verb/adjective/adverb etc",
  "cefr_level": "A1/A2/B1/B2/C1/C2",
  "definition": "clear, simple definition",
  "uzbek_translation": "translation in Uzbek with brief explanation",
  "examples": [
    "Example sentence 1.",
    "Example sentence 2.",
    "Example sentence 3."
  ],
  "word_forms": [
    {"form": "Noun", "word": "example"},
    {"form": "Verb", "word": "example"},
    {"form": "Adjective", "word": "example"},
    {"form": "Adverb", "word": "example"}
  ],
  "collocations": ["collocation 1", "collocation 2", "collocation 3"],
  "common_mistake": {
    "wrong": "wrong usage example",
    "correct": "correct usage example",
    "explanation": "why"
  },
  "synonyms": ["synonym1", "synonym2", "synonym3"],
  "antonyms": ["antonym1", "antonym2", "antonym3"]
}
Only include word_forms that actually exist. Be accurate and educational."""

WRITING_LIGHT_SYSTEM = """You are a friendly but honest English writing coach. Analyze this writing and respond ONLY with valid JSON (no markdown):
{
  "topic": "essay topic",
  "overall": "2-3 warm but honest sentences about quality",
  "mistakes": [
    {"number":1,"category":"Grammar","incorrect":"exact quote","correct":"correction","explanation":"friendly explanation"}
  ],
  "structure_suggestions": ["tip 1","tip 2","tip 3"],
  "vocabulary_upgrades": [{"original":"word","better":"better word"}],
  "paragraphs": [{"name":"Introduction","student_version":"text","improved_version":"improved"}],
  "full_improved": "Complete improved version."
}
Find up to 6 mistakes. Be encouraging but honest."""

IELTS_T2_SYSTEM = """You are an official IELTS examiner scoring Task 2. Be professional and precise.
Respond ONLY with valid JSON (no markdown):
{
  "topic": "essay topic",
  "overall_band": 6.5,
  "overall_comment": "2-3 professional examiner sentences",
  "scores": {
    "task_response": {"band": 6.5, "comment": "examiner comment"},
    "coherence_cohesion": {"band": 6.0, "comment": "examiner comment"},
    "lexical_resource": {"band": 6.5, "comment": "examiner comment"},
    "grammatical_range": {"band": 6.0, "comment": "examiner comment"}
  },
  "mistakes": [{"number":1,"category":"Grammar","incorrect":"quote","correct":"correction","explanation":"explanation"}],
  "structure_suggestions": ["suggestion 1","suggestion 2","suggestion 3"],
  "vocabulary_upgrades": [{"original":"word","better":"better word"}],
  "full_improved": "Complete band 8+ version."
}"""

IELTS_T1_SYSTEM = """You are an official IELTS examiner scoring Task 1. Be professional and precise.
Respond ONLY with valid JSON (no markdown):
{
  "topic": "graph/chart topic",
  "overall_band": 6.5,
  "overall_comment": "2-3 professional examiner sentences",
  "scores": {
    "task_achievement": {"band": 6.5, "comment": "examiner comment"},
    "coherence_cohesion": {"band": 6.0, "comment": "examiner comment"},
    "lexical_resource": {"band": 6.5, "comment": "examiner comment"},
    "grammatical_range": {"band": 6.0, "comment": "examiner comment"}
  },
  "mistakes": [{"number":1,"category":"Grammar","incorrect":"quote","correct":"correction","explanation":"explanation"}],
  "structure_suggestions": ["suggestion 1","suggestion 2","suggestion 3"],
  "vocabulary_upgrades": [{"original":"word","better":"better word"}],
  "full_improved": "Complete band 8+ version."
}"""

VOICE_SYSTEM = """You are a friendly and encouraging English speaking coach. A student sent a voice message.

Give warm, helpful feedback in this format:

🎤 You said: "[transcript]"

✅ What's great: [one positive point — be genuinely encouraging]

📝 One thing to improve: [one gentle, specific suggestion]

⭐ Try saying it this way: "[corrected version if needed, or 'Perfect! No changes needed 🎉']"

💡 Quick tip: [one practical, friendly tip]

Keep the tone warm and motivating — like a supportive coach!"""

READING_FEEDBACK_SYSTEM = """You are a friendly English teacher checking a student's reading comprehension answers.
Be warm, encouraging, and give clear feedback. Point out what they got right first, then gently correct any mistakes.
Keep it concise and positive. End with encouragement."""

# ─── Dictionary Formatter ──────────────────────────────────────────────────────
def format_dictionary(data: dict) -> str:
    word    = data.get("word","").upper()
    pos     = data.get("part_of_speech","")
    level   = data.get("cefr_level","")
    defn    = data.get("definition","")
    uzbek   = data.get("uzbek_translation","")
    examples = data.get("examples",[])
    forms   = data.get("word_forms",[])
    collocs = data.get("collocations",[])
    mistake = data.get("common_mistake",{})
    synonyms = data.get("synonyms",[])
    antonyms = data.get("antonyms",[])

    text  = f"📖 *{word}*\n"
    text += f"_{pos}_ | Level: {level}\n\n"
    text += f"📝 *Definition:*\n{defn}\n\n"
    text += f"🇺🇿 *In Uzbek:*\n{uzbek}\n\n"
    if examples:
        text += "💬 *Examples:*\n"
        for ex in examples: text += f"• {ex}\n"
        text += "\n"
    if forms:
        text += "🔤 *Word Forms:*\n"
        for f in forms: text += f"• {f.get('form','')} → {f.get('word','')}\n"
        text += "\n"
    if collocs:
        text += "🎯 *Collocations:*\n"
        for c in collocs: text += f"• {c}\n"
        text += "\n"
    if mistake:
        text += f"⚠️ *Common Mistake:*\n"
        text += f"❌ {mistake.get('wrong','')}\n"
        text += f"✅ {mistake.get('correct','')}\n"
        text += f"_{mistake.get('explanation','')}_\n\n"
    if synonyms: text += f"🔁 *Synonyms:* {', '.join(synonyms)}\n"
    if antonyms: text += f"↔️ *Antonyms:* {', '.join(antonyms)}\n"
    return text

# ─── Reading Articles by Level ─────────────────────────────────────────────────
READING_ARTICLES = {
    "beginner": [
        {
            "title": "My Family",
            "text": "My name is Sara. I have a small family. I have a mother, a father, and one brother. My mother is a teacher. My father is a doctor. My brother is seven years old. We live in a house. We have a dog. His name is Max. I love my family.",
            "questions": ["How many people are in Sara's family?", "What does Sara's mother do?", "What is the dog's name?"]
        },
        {
            "title": "My Day",
            "text": "I wake up at seven o'clock. I eat breakfast with my family. I go to school at eight o'clock. At school, I study English and Math. I eat lunch at twelve o'clock. After school, I play with my friends. I go to bed at nine o'clock.",
            "questions": ["What time does the person wake up?", "What subjects do they study?", "What time do they go to bed?"]
        },
        {
            "title": "Animals",
            "text": "There are many animals in the world. Some animals live in the forest. Bears and wolves live in the forest. Some animals live in water. Fish and dolphins live in water. Some animals live in hot places. Lions and elephants live in Africa. Animals are very interesting!",
            "questions": ["Where do bears live?", "Name one animal that lives in water.", "Where do lions live?"]
        },
    ],
    "elementary": [
        {
            "title": "A Trip to the Market",
            "text": "Every Saturday, my mother and I go to the market. The market is very busy in the morning. We buy fresh vegetables and fruit. My mother always buys tomatoes, onions, and apples. Sometimes we buy fish too. The market has many colours and smells. I like going there because it is fun and we meet our neighbours.",
            "questions": ["When do they go to the market?", "Name three things the mother buys.", "Why does the writer like going to the market?"]
        },
        {
            "title": "My Favourite Season",
            "text": "My favourite season is spring. In spring, the weather is warm and sunny. Flowers start to grow and trees become green. Birds sing in the morning. Children play outside after school. In spring, we celebrate Navruz in Uzbekistan. We make special food and wear colourful clothes. Spring makes everyone happy.",
            "questions": ["What is the writer's favourite season?", "What do children do in spring?", "What holiday is celebrated in spring in Uzbekistan?"]
        },
        {
            "title": "Healthy Food",
            "text": "Eating healthy food is very important. Fruit and vegetables give us vitamins. Vitamins help our body to stay strong. Bread and rice give us energy. Milk and cheese are good for our bones. We should drink eight glasses of water every day. Fast food is not healthy because it has too much oil and salt. Try to eat healthy every day!",
            "questions": ["What do vitamins do for our body?", "What gives us energy?", "Why is fast food not healthy?"]
        },
    ],
    "pre_intermediate": [
        {
            "title": "Social Media and Communication",
            "text": "Social media has changed the way people communicate. Platforms like Instagram and Telegram allow people to share photos, news, and ideas instantly. Many people use social media to stay connected with friends and family who live far away. However, some experts believe that too much social media can be harmful. It can reduce face-to-face communication and affect mental health. The key is to use social media in a balanced way — enjoy its benefits without letting it control your life.",
            "questions": ["How has social media changed communication?", "What are two benefits of social media mentioned?", "What do experts say about too much social media use?"]
        },
        {
            "title": "The Importance of Sleep",
            "text": "Many people do not get enough sleep. Doctors recommend that adults sleep between seven and nine hours every night. During sleep, our brain processes information from the day and stores memories. Sleep also helps our body repair itself. People who do not sleep enough often feel tired, find it hard to concentrate, and get sick more easily. Good sleep habits include going to bed at the same time each night, avoiding screens before sleep, and keeping your bedroom dark and quiet.",
            "questions": ["How many hours of sleep do doctors recommend for adults?", "What does the brain do during sleep?", "Name two good sleep habits mentioned in the article."]
        },
        {
            "title": "Online Shopping",
            "text": "Online shopping has become extremely popular in recent years. People can buy almost anything from the comfort of their homes. The main advantages are convenience, variety, and often lower prices. However, there are also disadvantages. You cannot see or try products before buying them. Delivery can take time, and sometimes products arrive damaged or different from the pictures. Despite these issues, online shopping continues to grow because it saves time and offers more choices than traditional stores.",
            "questions": ["Name three advantages of online shopping.", "What are two disadvantages mentioned?", "Why does online shopping continue to grow?"]
        },
    ],
    "intermediate": [
        {
            "title": "Artificial Intelligence in Education",
            "text": "Artificial intelligence is rapidly transforming the field of education. AI-powered tools can now personalise learning for individual students, identifying their strengths and weaknesses and adjusting content accordingly. Virtual tutors are available 24 hours a day, providing instant feedback on exercises and essays. However, educators warn that AI should complement rather than replace human teachers. The emotional connection between teachers and students, the ability to inspire and motivate, and the development of social skills are areas where human interaction remains irreplaceable. The challenge is to integrate AI effectively while preserving the human elements that make education meaningful.",
            "questions": ["How does AI personalise learning for students?", "What advantages do virtual tutors offer?", "Why do educators believe human teachers remain important?"]
        },
        {
            "title": "The Psychology of Habits",
            "text": "Habits are automatic behaviours that we perform with little conscious thought. According to researchers, habits are formed through a three-step loop: a cue that triggers the behaviour, the routine itself, and a reward that reinforces it. This is why habits are so powerful — they become wired into our neurology over time. Breaking bad habits requires identifying the cue and replacing the routine with a healthier alternative while maintaining the same reward. Similarly, building good habits means creating consistent cues and rewarding yourself when you follow through. Understanding how habits work gives you a powerful tool for personal change.",
            "questions": ["What are the three steps in the habit loop?", "Why are habits described as 'powerful'?", "How can you break a bad habit according to the article?"]
        },
        {
            "title": "Climate Change and Individual Action",
            "text": "Climate change is one of the most pressing challenges of our time. While governments and corporations bear the greatest responsibility for reducing carbon emissions, individual actions also play a significant role. Simple changes such as reducing meat consumption, using public transport, minimising single-use plastics, and conserving energy at home can collectively make a meaningful difference. Critics argue that focusing on individual behaviour shifts responsibility away from major polluters. However, proponents counter that individual choices drive market demand and signal to businesses and governments what consumers value. Both systemic change and personal responsibility are essential components of an effective climate strategy.",
            "questions": ["Name three individual actions that can help reduce climate change.", "What do critics say about focusing on individual behaviour?", "What do proponents argue about individual choices?"]
        },
    ],
    "advanced": [
        {
            "title": "The Paradox of Choice",
            "text": "In his influential work, psychologist Barry Schwartz argues that the proliferation of choice in modern society, rather than increasing human freedom and wellbeing, frequently leads to paralysis, anxiety, and dissatisfaction. When faced with an overwhelming number of options, individuals often experience decision fatigue and are more likely to second-guess their choices after making them — a phenomenon Schwartz terms 'the tyranny of choice.' The expectation that more options should yield better outcomes paradoxically raises the bar for satisfaction, meaning that even objectively good decisions can feel inadequate when measured against the multitude of alternatives forgone. Schwartz advocates for the cultivation of what he calls 'satisficing' — a strategy of settling for a sufficiently good option rather than exhaustively pursuing the optimal one.",
            "questions": ["What is Schwartz's central argument about choice?", "Explain the concept of 'the tyranny of choice' in your own words.", "What does Schwartz mean by 'satisficing' and why does he advocate for it?"]
        },
        {
            "title": "Post-Truth and the Epistemological Crisis",
            "text": "The emergence of the 'post-truth' era represents a profound challenge to democratic societies. Characterised by a political culture in which objective facts are less influential in shaping public opinion than appeals to emotion and personal belief, post-truth politics has been facilitated by the fragmentation of media landscapes, the algorithmic amplification of misinformation, and a deepening erosion of trust in established institutions. Epistemologically, this crisis raises fundamental questions about how societies arrive at shared understanding and the role of expertise in public discourse. Some scholars argue that the solution lies in rebuilding epistemic communities through media literacy education, while others contend that structural reforms to social media platforms are indispensable. What is clear is that the health of democratic governance depends significantly on citizens' capacity to distinguish credible information from manipulation.",
            "questions": ["How does the article define 'post-truth politics'?", "What factors have facilitated the post-truth era according to the text?", "What two solutions do scholars propose to address this epistemological crisis?"]
        },
        {
            "title": "Neuroplasticity and the Learning Brain",
            "text": "Contemporary neuroscience has fundamentally revised earlier assumptions about the fixed nature of the adult brain. The concept of neuroplasticity — the brain's remarkable capacity to reorganise itself by forming new neural connections throughout life — has profound implications for education, rehabilitation, and personal development. Research demonstrates that deliberate practice, particularly when it involves struggle and error correction, strengthens synaptic connections more effectively than passive review. This phenomenon, sometimes called 'desirable difficulty,' explains why effortful learning, despite being subjectively uncomfortable, produces more durable and transferable knowledge than easier alternatives. Furthermore, neuroplasticity research underscores the importance of sleep in consolidating learning, as the hippocampus replays and integrates newly acquired information during slow-wave sleep cycles.",
            "questions": ["How does the article define neuroplasticity?", "What is 'desirable difficulty' and why is it effective?", "What role does sleep play in the learning process according to the text?"]
        },
    ],
}

# ─── PDF Generation ────────────────────────────────────────────────────────────
NAVY       = colors.HexColor("#0a1628")
GOLD       = colors.HexColor("#c9a84c")
GOLD_LIGHT = colors.HexColor("#f5e6c0")
TEAL       = colors.HexColor("#1a6b5a")
TEAL_LIGHT = colors.HexColor("#e0f2ee")
RED        = colors.HexColor("#c0392b")
RED_LIGHT  = colors.HexColor("#fdecea")
GREEN      = colors.HexColor("#1e7e4a")
GREEN_LIGHT= colors.HexColor("#e8f8ee")
GREY       = colors.HexColor("#95a5a6")
GREY_LIGHT = colors.HexColor("#f8f9fa")
WHITE      = colors.white
BLACK      = colors.HexColor("#1a1a2e")
PURPLE     = colors.HexColor("#6c3483")
PURPLE_LT  = colors.HexColor("#f0e6f6")

def S(name, **kw): return ParagraphStyle(name, **kw)

def section_header(text, bg=NAVY, text_color=WHITE, accent=GOLD):
    t = Table([[Paragraph(text, S("SH", fontName="Helvetica-Bold", fontSize=12, textColor=text_color))]],
              colWidths=[17*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), bg),
        ("TOPPADDING",    (0,0),(-1,-1), 9),
        ("BOTTOMPADDING", (0,0),(-1,-1), 9),
        ("LEFTPADDING",   (0,0),(-1,-1), 14),
        ("LINEBELOW",     (0,0),(-1,-1), 2, accent),
    ]))
    return t

def build_header(story, student_name, topic, report_type):
    brand = Table([[
        Paragraph("<b>SAFIYA</b>", S("BN", fontName="Helvetica-Bold", fontSize=28, textColor=GOLD)),
        Paragraph("Premier Tutoring Center<br/><font size=9>English Language Excellence</font>",
                  S("BS", fontName="Helvetica", fontSize=13, textColor=WHITE)),
    ]], colWidths=[5*cm, 12*cm])
    brand.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), NAVY),
        ("TOPPADDING",    (0,0),(-1,-1), 16),("BOTTOMPADDING",(0,0),(-1,-1),16),
        ("LEFTPADDING",   (0,0),(0,0),   16), ("LEFTPADDING",  (1,0),(1,0),  8),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("LINEBELOW",     (0,0),(-1,-1), 3, GOLD),
    ]))
    story.append(brand)
    title_tbl = Table([[Paragraph(report_type.upper(),
        S("RT", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, alignment=TA_CENTER))]],
        colWidths=[17*cm])
    title_tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),GOLD_LIGHT),("TOPPADDING",(0,0),(-1,-1),10),
        ("BOTTOMPADDING",(0,0),(-1,-1),10),("BOX",(0,0),(-1,-1),1.5,GOLD),
    ]))
    story.append(Spacer(1,8)); story.append(title_tbl); story.append(Spacer(1,8))
    info = Table([[
        Paragraph(f"<b>Student:</b> {student_name}", S("IF", fontName="Helvetica", fontSize=10, textColor=BLACK)),
        Paragraph(f"<b>Topic:</b> {topic}", S("IF2", fontName="Helvetica", fontSize=10, textColor=BLACK)),
        Paragraph(f"<b>Date:</b> {datetime.now().strftime('%B %d, %Y')}", S("IF3", fontName="Helvetica", fontSize=10, textColor=BLACK)),
    ]], colWidths=[4*cm,9*cm,4*cm])
    info.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),GREY_LIGHT),("BOX",(0,0),(-1,-1),0.5,GREY),
        ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),("LEFTPADDING",(0,0),(-1,-1),10),
    ]))
    story.append(info); story.append(Spacer(1,14))

def build_mistakes(story, mistakes):
    for m in mistakes:
        mh = Table([[
            Paragraph(f"Mistake {m['number']}", S("MN", fontName="Helvetica-Bold", fontSize=10, textColor=WHITE)),
            Paragraph(m['category'], S("MC", fontName="Helvetica-Bold", fontSize=10, textColor=GOLD)),
        ]], colWidths=[3*cm,14*cm])
        mh.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),NAVY),("TOPPADDING",(0,0),(-1,-1),6),
            ("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),10),
        ]))
        story.append(mh)
        wr = Table([
            [Paragraph("<b>Incorrect</b>",S("WL",fontName="Helvetica-Bold",fontSize=9,textColor=RED)),
             Paragraph("<b>Corrected</b>",S("RL",fontName="Helvetica-Bold",fontSize=9,textColor=GREEN))],
            [Paragraph(m.get("incorrect",""),S("WT",fontName="Helvetica",fontSize=9,textColor=BLACK,leading=13)),
             Paragraph(m.get("correct",""),  S("RT2",fontName="Helvetica",fontSize=9,textColor=BLACK,leading=13))],
        ], colWidths=[8.5*cm,8.5*cm])
        wr.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(0,0),RED_LIGHT),("BACKGROUND",(1,0),(1,0),GREEN_LIGHT),
            ("BACKGROUND",(0,1),(0,1),RED_LIGHT),("BACKGROUND",(1,1),(1,1),GREEN_LIGHT),
            ("BOX",(0,0),(-1,-1),0.5,GREY),("INNERGRID",(0,0),(-1,-1),0.5,GREY),
            ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
            ("LEFTPADDING",(0,0),(-1,-1),10),("VALIGN",(0,0),(-1,-1),"TOP"),
        ]))
        story.append(wr)
        exp = Table([[Paragraph(f"<i>{m.get('explanation','')}</i>",
            S("EX",fontName="Helvetica-Oblique",fontSize=9,textColor=colors.HexColor("#555"),leading=13))
        ]], colWidths=[17*cm])
        exp.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),GREY_LIGHT),("TOPPADDING",(0,0),(-1,-1),6),
            ("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),10),
            ("LINEBELOW",(0,0),(-1,-1),0.5,GREY),
        ]))
        story.append(exp); story.append(Spacer(1,8))

def build_vocab_structure(story, feedback):
    story.append(section_header("STRUCTURE & VOCABULARY SUGGESTIONS", PURPLE, WHITE, colors.HexColor("#d7bde2")))
    story.append(Spacer(1,8))
    str_text = "<b>Structure Tips:</b><br/>" + "<br/>".join(f"- {s}" for s in feedback.get("structure_suggestions",[]))
    str_box = Table([[Paragraph(str_text, S("ST",fontName="Helvetica",fontSize=10,textColor=BLACK,leading=16))]],colWidths=[17*cm])
    str_box.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),PURPLE_LT),("BOX",(0,0),(-1,-1),1,PURPLE),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),("LEFTPADDING",(0,0),(-1,-1),14),
    ]))
    story.append(str_box); story.append(Spacer(1,8))
    vocab = feedback.get("vocabulary_upgrades",[])
    if vocab:
        vd = [[Paragraph("<b>Original</b>",S("VH",fontName="Helvetica-Bold",fontSize=9,textColor=WHITE)),
               Paragraph("<b>Better</b>",  S("VH2",fontName="Helvetica-Bold",fontSize=9,textColor=WHITE))]]
        for v in vocab:
            vd.append([Paragraph(f'"{v.get("original","")}"',S("V1",fontName="Helvetica",fontSize=10,textColor=BLACK)),
                       Paragraph(f'"{v.get("better","")}"',  S("V2",fontName="Helvetica",fontSize=10,textColor=TEAL))])
        vt = Table(vd, colWidths=[5*cm,12*cm])
        vt.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),NAVY),("BOX",(0,0),(-1,-1),0.5,GREY),("INNERGRID",(0,0),(-1,-1),0.5,GREY),
            ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),("LEFTPADDING",(0,0),(-1,-1),10),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,GREY_LIGHT]),
        ]))
        story.append(vt)
    story.append(Spacer(1,14))

def build_improved(story, text):
    story.append(section_header("FULL IMPROVED VERSION", colors.HexColor("#7d6608"), WHITE, GOLD))
    story.append(Spacer(1,4))
    story.append(Paragraph("<i>Same ideas - corrected, enriched, and polished</i>",
        S("SI",fontName="Helvetica-Oblique",fontSize=9,textColor=GREY,spaceAfter=6)))
    story.append(Spacer(1,6))
    fb = Table([[Paragraph(text.replace("\n\n","<br/><br/>"),
        S("FB",fontName="Helvetica",fontSize=10,textColor=BLACK,leading=16,alignment=TA_JUSTIFY))]],colWidths=[17*cm])
    fb.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#fefcf0")),("BOX",(0,0),(-1,-1),2,GOLD),
        ("TOPPADDING",(0,0),(-1,-1),14),("BOTTOMPADDING",(0,0),(-1,-1),14),
        ("LEFTPADDING",(0,0),(-1,-1),16),("RIGHTPADDING",(0,0),(-1,-1),16),
    ]))
    story.append(fb); story.append(Spacer(1,16))

def build_footer(story):
    footer = Table([[
        Paragraph("Safiya | Premier Tutoring Center",S("FL",fontName="Helvetica-Bold",fontSize=11,textColor=GOLD)),
        Paragraph("Keep writing. Keep improving. Excellence is a habit.",S("FM",fontName="Helvetica-Oblique",fontSize=9,textColor=WHITE,alignment=TA_CENTER)),
        Paragraph(datetime.now().strftime("%Y"),S("FD",fontName="Helvetica",fontSize=9,textColor=GREY)),
    ]], colWidths=[6*cm,8*cm,3*cm])
    footer.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),NAVY),("TOPPADDING",(0,0),(-1,-1),12),
        ("BOTTOMPADDING",(0,0),(-1,-1),12),("LEFTPADDING",(0,0),(-1,-1),14),
        ("LINEABOVE",(0,0),(-1,-1),3,GOLD),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    story.append(footer)

def generate_light_pdf(feedback, student_name):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer,pagesize=A4,rightMargin=2*cm,leftMargin=2*cm,topMargin=1.5*cm,bottomMargin=2*cm)
    story = []
    build_header(story, student_name, feedback.get("topic","Essay"), "Writing Feedback Report")
    story.append(section_header("OVERALL ASSESSMENT", TEAL, WHITE, colors.HexColor("#a8e6cf")))
    story.append(Spacer(1,8))
    ob = Table([[Paragraph(feedback.get("overall",""),S("OV",fontName="Helvetica",fontSize=10,textColor=BLACK,leading=16,alignment=TA_JUSTIFY))]],colWidths=[17*cm])
    ob.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),TEAL_LIGHT),("BOX",(0,0),(-1,-1),1,TEAL),
        ("TOPPADDING",(0,0),(-1,-1),12),("BOTTOMPADDING",(0,0),(-1,-1),12),
        ("LEFTPADDING",(0,0),(-1,-1),14),("RIGHTPADDING",(0,0),(-1,-1),14),
    ]))
    story.append(ob); story.append(Spacer(1,14))
    story.append(section_header("6 KEY MISTAKES & CORRECTIONS", RED, WHITE, colors.HexColor("#f1948a")))
    story.append(Spacer(1,10))
    build_mistakes(story, feedback.get("mistakes",[]))
    build_vocab_structure(story, feedback)
    build_improved(story, feedback.get("full_improved",""))
    build_footer(story)
    doc.build(story)
    buffer.seek(0)
    return buffer

def generate_ielts_pdf(feedback, student_name, task):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer,pagesize=A4,rightMargin=2*cm,leftMargin=2*cm,topMargin=1.5*cm,bottomMargin=2*cm)
    story = []
    build_header(story, student_name, feedback.get("topic","Essay"), f"IELTS Task {task} - Official Assessment")
    band = feedback.get("overall_band",0)
    band_color = colors.HexColor("#1e7e4a") if band>=7 else colors.HexColor("#d4ac0d") if band>=5.5 else RED
    band_tbl = Table([[
        Paragraph("<b>Overall Band Score</b>",S("OBL",fontName="Helvetica-Bold",fontSize=14,textColor=WHITE,alignment=TA_CENTER)),
        Paragraph(f"<b>{band}</b>",S("OBS",fontName="Helvetica-Bold",fontSize=36,textColor=band_color,alignment=TA_CENTER)),
    ]], colWidths=[13*cm,4*cm])
    band_tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,0),NAVY),("BACKGROUND",(1,0),(1,0),colors.HexColor("#f0f0f0")),
        ("BOX",(0,0),(-1,-1),2,GOLD),("TOPPADDING",(0,0),(-1,-1),14),
        ("BOTTOMPADDING",(0,0),(-1,-1),14),("LEFTPADDING",(0,0),(-1,-1),14),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    story.append(band_tbl); story.append(Spacer(1,8))
    oc = Table([[Paragraph(feedback.get("overall_comment",""),S("OC",fontName="Helvetica",fontSize=10,textColor=BLACK,leading=15,alignment=TA_JUSTIFY))]],colWidths=[17*cm])
    oc.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),GOLD_LIGHT),("BOX",(0,0),(-1,-1),1,GOLD),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LEFTPADDING",(0,0),(-1,-1),14),("RIGHTPADDING",(0,0),(-1,-1),14),
    ]))
    story.append(oc); story.append(Spacer(1,14))
    story.append(section_header("IELTS SCORING CRITERIA",NAVY,WHITE,GOLD))
    story.append(Spacer(1,8))
    scores = feedback.get("scores",{})
    for key, label in [("task_response","Task Response (TR)"),("task_achievement","Task Achievement (TA)"),
                       ("coherence_cohesion","Coherence & Cohesion (CC)"),("lexical_resource","Lexical Resource (LR)"),
                       ("grammatical_range","Grammatical Range & Accuracy (GRA)")]:
        if key in scores:
            sc = scores[key]; b = sc.get("band",0)
            bc = colors.HexColor("#1e7e4a") if b>=7 else colors.HexColor("#d4ac0d") if b>=5.5 else RED
            row = Table([[
                Paragraph(f"<b>{label}</b>",S("CL",fontName="Helvetica-Bold",fontSize=10,textColor=NAVY)),
                Paragraph(f"<b>{b}</b>",S("CB",fontName="Helvetica-Bold",fontSize=16,textColor=bc,alignment=TA_CENTER)),
                Paragraph(sc.get("comment",""),S("CC2",fontName="Helvetica",fontSize=9,textColor=BLACK,leading=13)),
            ]], colWidths=[5*cm,2*cm,10*cm])
            row.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(1,0),GREY_LIGHT),("BOX",(0,0),(-1,-1),0.5,GREY),
                ("INNERGRID",(0,0),(-1,-1),0.5,GREY),("TOPPADDING",(0,0),(-1,-1),8),
                ("BOTTOMPADDING",(0,0),(-1,-1),8),("LEFTPADDING",(0,0),(-1,-1),10),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ]))
            story.append(row); story.append(Spacer(1,6))
    story.append(Spacer(1,8))
    story.append(section_header("KEY MISTAKES & CORRECTIONS",RED,WHITE,colors.HexColor("#f1948a")))
    story.append(Spacer(1,10))
    build_mistakes(story, feedback.get("mistakes",[]))
    build_vocab_structure(story, feedback)
    build_improved(story, feedback.get("full_improved",""))
    build_footer(story)
    doc.build(story)
    buffer.seek(0)
    return buffer

# ─── Session Storage ───────────────────────────────────────────────────────────
user_sessions: dict[int, dict] = {}

def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "history": [], "mode": "chat",
            "quiz_index": None, "puzzle_index": None,
            "article_index": None, "article_level": None,
            "writing_type": None, "ielts_task": None
        }
    return user_sessions[user_id]

# ─── Claude API ────────────────────────────────────────────────────────────────
def ask_claude(user_id, message, system=None, max_tokens=500):
    session = get_session(user_id)
    u    = user_db.get(str(user_id), {})
    name = u.get("name","")
    sys_prompt = system or SAFIYA_SYSTEM
    if not system and name:
        sys_prompt += f"\n\nUser's name: {name}"
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
    uid = str(user_id)
    if uid in user_db:
        user_db[uid]["messages"] = user_db[uid].get("messages",0) + 1
        save_json(USERS_FILE, user_db)
    return reply

async def transcribe_voice(path):
    with open(path,"rb") as f:
        t = openai_client.audio.transcriptions.create(model="whisper-1",file=f,language="en")
    return t.text

# ─── Quiz Bank ─────────────────────────────────────────────────────────────────
QUIZ_QUESTIONS = [
    {"q":"Which word is a NOUN?\n\na) Run\nb) Happy\nc) Dog\nd) Quickly","a":"c","e":"Dog is a noun — a person, place or thing.","cat":"Nouns"},
    {"q":"Correct sentence?\n\na) She go to school.\nb) She goes to school.\nc) She going.\nd) She gone.","a":"b","e":"She goes — add -es for he/she/it.","cat":"Verb Agreement"},
    {"q":"Which is an ADJECTIVE?\n\na) Jump\nb) Tiny\nc) Cat\nd) Slowly","a":"b","e":"Tiny is an adjective — describes a noun.","cat":"Adjectives"},
    {"q":"Capital letters correct?\n\na) my name is john.\nb) My name is John.\nc) my Name is john.\nd) My Name Is John.","a":"b","e":"Sentences start with capital. Names are always capitalized.","cat":"Capitalization"},
    {"q":"Correct punctuation?\n\na) Do you like pizza\nb) Do you like pizza!\nc) Do you like pizza?\nd) Do you like pizza,","a":"c","e":"Questions end with ?","cat":"Punctuation"},
    {"q":"Plural of child?\n\na) Childs\nb) Childes\nc) Children\nd) Childer","a":"c","e":"Children — irregular plural. Also: man-men, tooth-teeth.","cat":"Plurals"},
    {"q":"Which is a VERB?\n\na) Beautiful\nb) Apple\nc) Swim\nd) Blue","a":"c","e":"Swim is a verb — an action word.","cat":"Verbs"},
    {"q":"Spelled correctly?\n\na) Freind\nb) Frend\nc) Friend\nd) Freind","a":"c","e":"Friend — I before E: fr-I-E-nd.","cat":"Spelling"},
    {"q":"I have ___ apple.\n\na) a\nb) an\nc) the\nd) some","a":"b","e":"Use an before vowel sounds. Apple starts with a.","cat":"Articles"},
    {"q":"Opposite of hot?\n\na) Warm\nb) Sunny\nc) Cold\nd) Big","a":"c","e":"Cold is the antonym of hot.","cat":"Vocabulary"},
    {"q":"Which is a PRONOUN?\n\na) Run\nb) She\nc) Big\nd) House","a":"b","e":"She is a pronoun — replaces a name.","cat":"Pronouns"},
    {"q":"What ends a statement?\n\na) Comma\nb) Colon\nc) Period\nd) Apostrophe","a":"c","e":"A period ends a statement.","cat":"Punctuation"},
    {"q":"Which is an ADVERB?\n\na) Cat\nb) Happy\nc) Quickly\nd) Jump","a":"c","e":"Quickly is an adverb — describes HOW.","cat":"Adverbs"},
    {"q":"Correct sentence?\n\na) I has a cat.\nb) I have a cat.\nc) I haves a cat.\nd) I having a cat.","a":"b","e":"I have a cat — use have with I, you, we, they.","cat":"Verb Agreement"},
    {"q":"Synonym for big?\n\na) Small\nb) Tiny\nc) Large\nd) Short","a":"c","e":"Large is a synonym for big.","cat":"Vocabulary"},
]

PUZZLES = [
    {"q":"'She ___ to school every day.'\n\na) go\nb) goes\nc) going\nd) gone","answer":"b","e":"goes — third person singular present tense."},
    {"q":"What does BENEFICIAL mean?\n\na) Harmful\nb) Helpful\nc) Beautiful\nd) Boring","answer":"b","e":"Beneficial means helpful or having a good effect."},
    {"q":"Which word does NOT belong?\n\na) Happy\nb) Sad\nc) Angry\nd) Run","answer":"d","e":"Run is a verb. Happy, Sad, Angry are all adjectives."},
    {"q":"'There are ___ apples.'\n\na) much\nb) many\nc) a lot\nd) few of","answer":"b","e":"Many — use with countable nouns. Much is for uncountable."},
    {"q":"Synonym for ENORMOUS?\n\na) Tiny\nb) Average\nc) Huge\nd) Narrow","answer":"c","e":"Huge is a synonym for enormous."},
    {"q":"Which does NOT belong?\n\na) Cat\nb) Dog\nc) Eagle\nd) Fish","answer":"c","e":"Eagle is a bird. Cat, Dog, Fish are common pets."},
    {"q":"'If I ___ rich, I would travel.'\n\na) am\nb) was\nc) were\nd) be","answer":"c","e":"Were — always used in conditional sentences."},
    {"q":"What does INEVITABLE mean?\n\na) Impossible\nb) Certain to happen\nc) Surprising\nd) Dangerous","answer":"b","e":"Inevitable means certain to happen, impossible to avoid."},
]

# ─── Keyboards ─────────────────────────────────────────────────────────────────
def main_reply_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Safiya AI"), KeyboardButton("Dictionary")],
         [KeyboardButton("Skills"), KeyboardButton("Complaints & Offers")]],
        resize_keyboard=True,
        input_field_placeholder="Chat with Safiya..."
    )

def safiya_ai_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Quiz", callback_data="mode_quiz"),
         InlineKeyboardButton("Word Puzzle", callback_data="mode_puzzle")],
        [InlineKeyboardButton("Check Writing", callback_data="mode_writing"),
         InlineKeyboardButton("Voice Practice", callback_data="mode_voice")],
        [InlineKeyboardButton("Close", callback_data="close_menu")],
    ])

def skills_levels_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Beginner",          callback_data="skill_level_beginner")],
        [InlineKeyboardButton("🔵 Elementary",         callback_data="skill_level_elementary")],
        [InlineKeyboardButton("🟡 Pre-Intermediate",   callback_data="skill_level_pre_intermediate")],
        [InlineKeyboardButton("🟠 Intermediate",       callback_data="skill_level_intermediate")],
        [InlineKeyboardButton("🔴 Advanced",           callback_data="skill_level_advanced")],
        [InlineKeyboardButton("Close", callback_data="close_menu")],
    ])

def skills_menu_keyboard(level):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Reading", callback_data=f"skill_reading_{level}")],
        [InlineKeyboardButton("Back", callback_data="skills_back")],
    ])

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="safiya_menu")]])

def join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Join Channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("I Joined", callback_data="check_join")],
    ])

# ─── /start ────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid  = user.id
    name = user.first_name or ""
    if not await check_membership(uid, context):
        await update.message.reply_text(
            "Welcome! To use Safiya AI, please join our channel first.\n\nOnce you join, tap 'I Joined'!",
            reply_markup=join_keyboard()
        )
        return
    u      = get_user(uid, name)
    get_session(uid)["mode"] = "chat"
    is_new = u.get("messages",0) == 0
    prompt = (f"New user named {name} just started. Warmly introduce yourself as Safiya, support teacher at Premier Tutoring Center. Briefly mention the buttons: Safiya AI for learning tools, Dictionary for word lookups, Skills for level-based reading practice, and Complaints & Offers to reach the team."
              if is_new else f"Welcome back {name} warmly in one friendly sentence.")
    reply = ask_claude(uid, prompt)
    await update.message.reply_text(reply, reply_markup=main_reply_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_membership(update, context): return
    await update.message.reply_text(
        "Here's what you can do!\n\n"
        "Safiya AI — quiz, writing check, voice practice\n"
        "Dictionary — look up any English word\n"
        "Skills — reading practice by level\n"
        "Complaints & Offers — reach us directly\n\n"
        "Or just chat with me anytime 😊",
        reply_markup=main_reply_keyboard()
    )

async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_membership(update, context): return
    uid = str(update.effective_user.id)
    p   = student_progress.get(uid)
    if not p or p.get("total",0)==0:
        await update.message.reply_text("No results yet — take a quiz to get started! 😊", reply_markup=main_reply_keyboard()); return
    s,t = p["score"],p["total"]
    pct = int(s/t*100)
    await update.message.reply_text(
        f"Your progress so far:\nQuiz: {s}/{t} ({pct}%)\nStreak: {p.get('streak',0)} days\n"
        f"Voice: {p.get('voice_messages',0)}\nEssays: {p.get('essays_checked',0)}\n"
        f"IELTS: {p.get('ielts_checks',0)}\nPuzzles: {p.get('puzzles_solved',0)}\n"
        f"Articles read: {p.get('articles_read',0)}\n\nKeep it up! 💪",
        reply_markup=main_reply_keyboard()
    )

# ─── Send Quiz / Puzzle ─────────────────────────────────────────────────────────
async def send_quiz(upd_or_q, context, user_id):
    session = get_session(user_id)
    idx = random.randint(0,len(QUIZ_QUESTIONS)-1)
    session["quiz_index"]=idx; session["mode"]="quiz"
    q = QUIZ_QUESTIONS[idx]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("A",callback_data="quiz_a"),InlineKeyboardButton("B",callback_data="quiz_b"),
         InlineKeyboardButton("C",callback_data="quiz_c"),InlineKeyboardButton("D",callback_data="quiz_d")],
        [InlineKeyboardButton("Skip",callback_data="quiz_skip"),InlineKeyboardButton("Stop",callback_data="safiya_menu")],
    ])
    if hasattr(upd_or_q,"edit_message_text"):
        await upd_or_q.edit_message_text(f"Quiz time! 🎯\n\n{q['q']}", reply_markup=kb)
    else:
        await upd_or_q.message.reply_text(f"Quiz time! 🎯\n\n{q['q']}", reply_markup=kb)

async def send_puzzle(upd_or_q, context, user_id):
    session = get_session(user_id)
    idx = random.randint(0,len(PUZZLES)-1)
    session["puzzle_index"]=idx; session["mode"]="puzzle"
    p = PUZZLES[idx]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("A",callback_data="puz_a"),InlineKeyboardButton("B",callback_data="puz_b"),
         InlineKeyboardButton("C",callback_data="puz_c"),InlineKeyboardButton("D",callback_data="puz_d")],
        [InlineKeyboardButton("Skip",callback_data="puz_skip"),InlineKeyboardButton("Stop",callback_data="safiya_menu")],
    ])
    if hasattr(upd_or_q,"edit_message_text"):
        await upd_or_q.edit_message_text(f"Word Puzzle! 🧩\n\n{p['q']}", reply_markup=kb)
    else:
        await upd_or_q.message.reply_text(f"Word Puzzle! 🧩\n\n{p['q']}", reply_markup=kb)

async def send_reading(upd_or_q, context, user_id, level):
    session = get_session(user_id)
    articles = READING_ARTICLES.get(level, READING_ARTICLES["elementary"])
    idx = random.randint(0, len(articles)-1)
    session["article_index"] = idx
    session["article_level"] = level
    session["mode"] = "reading"
    a = articles[idx]
    questions = "\n".join(f"{i+1}. {q}" for i,q in enumerate(a["questions"]))
    level_display = level.replace("_"," ").title()
    text = (f"📖 Reading Practice — {level_display}\n\n"
            f"Title: {a['title']}\n\n"
            f"{a['text']}\n\n"
            f"Questions — answer in your own words:\n{questions}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Submit My Answers", callback_data="check_reading_answers")],
        [InlineKeyboardButton("New Article", callback_data=f"skill_reading_{level}")],
        [InlineKeyboardButton("Back to Levels", callback_data="skills_back")],
    ])
    if hasattr(upd_or_q,"edit_message_text"):
        await upd_or_q.edit_message_text(text, reply_markup=kb)
    else:
        await upd_or_q.message.reply_text(text, reply_markup=kb)

# ─── Writing Processor ─────────────────────────────────────────────────────────
async def process_writing(update, context, text, mode, task=""):
    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name or "Student"
    await update.message.reply_text("Analyzing your writing and generating your PDF report... hang on! ⏳")
    await context.bot.send_chat_action(update.effective_chat.id, action="upload_document")
    try:
        system = (IELTS_T2_SYSTEM if task=="2" else IELTS_T1_SYSTEM) if mode=="ielts" else WRITING_LIGHT_SYSTEM
        raw    = ask_claude(user_id, f"Analyze:\n\n{text}", system=system, max_tokens=2500)
        clean  = re.sub(r"```json|```","",raw).strip()
        feedback = json.loads(clean)
        if mode=="ielts":
            pdf = generate_ielts_pdf(feedback, user_name, task)
            inc_progress(user_id, user_name, "ielts_checks")
            report_name = f"IELTS Task {task} Assessment"
        else:
            pdf = generate_light_pdf(feedback, user_name)
            inc_progress(user_id, user_name, "essays_checked")
            report_name = "Writing Feedback"
        filename = f"Safiya_{report_name.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        await update.message.reply_document(
            document=pdf, filename=filename,
            caption=f"Here's your {report_name}! Hope it helps 😊",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Check Another", callback_data="mode_writing")],
                [InlineKeyboardButton("Back", callback_data="safiya_menu")],
            ])
        )
        get_session(user_id)["mode"] = "chat"
    except json.JSONDecodeError:
        await update.message.reply_text(f"Here's my feedback:\n\n{raw[:3500]}")
    except Exception as e:
        logger.error(f"Writing error: {e}")
        await update.message.reply_text("Something went wrong! Please try again.")

# ─── Button Callbacks ───────────────────────────────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    user_id   = query.from_user.id
    user_name = query.from_user.first_name or "Student"
    session   = get_session(user_id)
    data      = query.data

    if data == "check_join":
        if await check_membership(user_id, context):
            u      = get_user(user_id, user_name)
            is_new = u.get("messages",0)==0
            prompt = (f"New user named {user_name} just joined. Welcome them warmly as Safiya."
                      if is_new else f"Welcome back {user_name} warmly.")
            reply  = ask_claude(user_id, prompt)
            await query.edit_message_text(reply)
            await context.bot.send_message(user_id, "You now have full access! 🎉", reply_markup=main_reply_keyboard())
        else:
            await query.answer("You haven't joined the channel yet!", show_alert=True)
        return

    if not await check_membership(user_id, context):
        await query.answer("Please join our channel first!", show_alert=True)
        return

    if data == "safiya_menu":
        session["mode"] = "chat"
        await query.edit_message_text("What would you like to do?", reply_markup=safiya_ai_keyboard())

    elif data == "close_menu":
        await query.edit_message_text("Feel free to chat or tap any button below! 😊")

    elif data == "skills_back":
        await query.edit_message_text("Choose your level:", reply_markup=skills_levels_keyboard())

    elif data.startswith("skill_level_"):
        level = data.replace("skill_level_","")
        level_display = level.replace("_"," ").title()
        await query.edit_message_text(
            f"Great choice! You selected {level_display} 🎯\n\nWhat would you like to practice?",
            reply_markup=skills_menu_keyboard(level)
        )

    elif data.startswith("skill_reading_"):
        level = data.replace("skill_reading_","")
        await send_reading(query, context, user_id, level)

    elif data == "check_reading_answers":
        session["mode"] = "reading_answers"
        await query.edit_message_text("Great! Type your answers below and I'll check them 😊", reply_markup=None)

    elif data == "mode_quiz":
        await send_quiz(query, context, user_id)

    elif data == "mode_puzzle":
        await send_puzzle(query, context, user_id)

    elif data == "mode_voice":
        session["mode"] = "voice"
        await query.edit_message_text(
            "Send me a voice message in English and I'll give you feedback on your speaking! 🎤",
            reply_markup=back_btn())

    elif data == "mode_writing":
        session["mode"] = "writing_ask"
        await query.edit_message_text(
            "Should I check it lightly or professionally?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Lightly", callback_data="write_light"),
                 InlineKeyboardButton("Professionally (IELTS)", callback_data="write_pro")],
                [InlineKeyboardButton("Back", callback_data="safiya_menu")],
            ]))

    elif data == "write_light":
        session["mode"]="writing"; session["writing_type"]="light"
        await query.edit_message_text("Paste your essay or paragraph below 👇", reply_markup=back_btn())

    elif data == "write_pro":
        session["writing_type"]="ielts"
        await query.edit_message_text(
            "Is this IELTS Task 1 or Task 2?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Task 1 (Graph/Letter)", callback_data="ielts_t1"),
                 InlineKeyboardButton("Task 2 (Essay)", callback_data="ielts_t2")],
                [InlineKeyboardButton("Back", callback_data="safiya_menu")],
            ]))

    elif data == "ielts_t1":
        session["mode"]="writing"; session["ielts_task"]="1"
        await query.edit_message_text("Paste your IELTS Task 1 writing below 👇", reply_markup=back_btn())

    elif data == "ielts_t2":
        session["mode"]="writing"; session["ielts_task"]="2"
        await query.edit_message_text("Paste your IELTS Task 2 essay below 👇", reply_markup=back_btn())

    elif data.startswith("quiz_"):
        if session.get("quiz_index") is None:
            await query.edit_message_text("No active quiz!", reply_markup=safiya_ai_keyboard()); return
        if data=="quiz_skip":
            await send_quiz(query, context, user_id); return
        ans     = {"quiz_a":"a","quiz_b":"b","quiz_c":"c","quiz_d":"d"}.get(data)
        q       = QUIZ_QUESTIONS[session["quiz_index"]]
        correct = ans==q["a"]
        update_quiz_progress(user_id, user_name, correct, q.get("cat",""))
        p = student_progress.get(str(user_id),{})
        s,t = p.get("score",0),p.get("total",0)
        result = (f"Correct! Well done 🎉\n\n{q['e']}\n\nScore: {s}/{t}" if correct else
                  f"Not quite! The answer was {q['a'].upper()}.\n\n{q['e']}\n\nScore: {s}/{t}")
        await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Next Question", callback_data="mode_quiz")],
            [InlineKeyboardButton("Stop", callback_data="safiya_menu")],
        ]))
        session["quiz_index"] = None

    elif data.startswith("puz_"):
        if session.get("puzzle_index") is None:
            await query.edit_message_text("No active puzzle!", reply_markup=safiya_ai_keyboard()); return
        if data=="puz_skip":
            await send_puzzle(query, context, user_id); return
        ans     = {"puz_a":"a","puz_b":"b","puz_c":"c","puz_d":"d"}.get(data)
        p       = PUZZLES[session["puzzle_index"]]
        correct = ans==p["answer"]
        if correct: inc_progress(user_id, user_name, "puzzles_solved")
        result = (f"Correct! 🎉\n\n{p['e']}" if correct else f"Not quite! The answer was {p['answer'].upper()}.\n\n{p['e']}")
        await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Next Puzzle", callback_data="mode_puzzle")],
            [InlineKeyboardButton("Stop", callback_data="safiya_menu")],
        ]))
        session["puzzle_index"] = None

# ─── Voice Handler ──────────────────────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_membership(update, context): return
    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name or "Student"
    await context.bot.send_chat_action(update.effective_chat.id, action="typing")
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        transcript = await transcribe_voice(tmp_path)
        os.unlink(tmp_path)
        if not transcript.strip():
            await update.message.reply_text("Hmm, I couldn't hear that clearly! Could you try again in a quieter place? 😊"); return
        inc_progress(user_id, user_name, "voice_messages")
        reply = ask_claude(user_id, f'Student said: "{transcript}"\nGive speaking feedback.', system=VOICE_SYSTEM)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text("Something went wrong with the voice message — please try again!")

# ─── Text Handler ───────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name or ""
    session   = get_session(user_id)
    text      = update.message.text.strip()
    mode      = session.get("mode","chat")

    get_user(user_id, user_name)

    # ── Bottom menu buttons ──
    if text == "Safiya AI":
        if not await require_membership(update, context): return
        await update.message.reply_text("What would you like to do? 😊", reply_markup=safiya_ai_keyboard())
        return

    if text == "Dictionary":
        if not await require_membership(update, context): return
        session["mode"] = "dictionary"
        await update.message.reply_text(
            "Type any English word and I'll look it up for you! 📖",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="close_menu")]])
        )
        return

    if text == "Skills":
        if not await require_membership(update, context): return
        await update.message.reply_text(
            "Choose your level to start practicing! 🎯",
            reply_markup=skills_levels_keyboard()
        )
        return

    if text == "Complaints & Offers":
        if not await require_membership(update, context): return
        await update.message.reply_text(
            "Have a complaint or suggestion? Reach us directly here 👇",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Contact @umrbektp", url=ADMIN_URL)],
            ])
        )
        return

    if not await require_membership(update, context): return

    # ── Dictionary mode ──
    if mode == "dictionary":
        await context.bot.send_chat_action(update.effective_chat.id, action="typing")
        try:
            raw   = ask_claude(user_id, f"Look up this word: {text}", system=DICTIONARY_SYSTEM, max_tokens=800)
            clean = re.sub(r"```json|```","",raw).strip()
            data  = json.loads(clean)
            reply = format_dictionary(data)
            session["mode"] = "chat"
            await update.message.reply_text(
                reply, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Look Up Another Word", callback_data="dict_again")],
                ])
            )
        except Exception as e:
            logger.error(f"Dictionary error: {e}")
            await update.message.reply_text("Hmm, I couldn't find that word. Please check the spelling and try again! 😊")
        return

    # ── Writing mode ──
    if mode == "writing":
        if len(text) < 30:
            await update.message.reply_text("Please send a longer text for me to analyze! 😊"); return
        await process_writing(update, context, text, session.get("writing_type","light"), session.get("ielts_task","2"))
        return

    # ── Reading answers mode ──
    if mode == "reading_answers":
        level    = session.get("article_level","elementary")
        articles = READING_ARTICLES.get(level, READING_ARTICLES["elementary"])
        idx      = session.get("article_index",0)
        a        = articles[idx] if idx < len(articles) else articles[0]
        inc_progress(user_id, user_name, "articles_read")
        prompt = (f"Student answered comprehension questions about '{a['title']}'.\n"
                  f"Article: {a['text'][:500]}\nQuestions: {a['questions']}\nStudent answers: {text}\n\n"
                  f"Check their answers warmly and give encouraging feedback.")
        await context.bot.send_chat_action(update.effective_chat.id, action="typing")
        reply = ask_claude(user_id, prompt, system=READING_FEEDBACK_SYSTEM)
        await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("New Article", callback_data=f"skill_reading_{level}")],
            [InlineKeyboardButton("Back to Levels", callback_data="skills_back")],
        ]))
        session["mode"] = "chat"
        return

    # ── Normal chat ──
    await context.bot.send_chat_action(update.effective_chat.id, action="typing")
    try:
        reply = ask_claude(user_id, text)
    except Exception as e:
        logger.error(f"Claude error: {e}")
        reply = "Something went wrong — please try again! 😊"
    await update.message.reply_text(reply)

# ─── Commands ──────────────────────────────────────────────────────────────────
async def quiz_command(update, context):
    if not await require_membership(update, context): return
    get_session(update.effective_user.id)["mode"] = "quiz"
    await send_quiz(update, context, update.effective_user.id)

async def puzzle_command(update, context):
    if not await require_membership(update, context): return
    get_session(update.effective_user.id)["mode"] = "puzzle"
    await send_puzzle(update, context, update.effective_user.id)

# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Starting Safiya Bot...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CommandHandler("quiz",    quiz_command))
    app.add_handler(CommandHandler("puzzle",  puzzle_command))
    app.add_handler(CommandHandler("score",   score_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Safiya is running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
