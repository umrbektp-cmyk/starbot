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
                    invite_count INTEGER DEFAULT 0,
                    invited_by TEXT DEFAULT '',
                    points INTEGER DEFAULT 0,
                    challenges_won INTEGER DEFAULT 0,
                    challenges_played INTEGER DEFAULT 0
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS challenges (
                    id SERIAL PRIMARY KEY,
                    challenger_id TEXT,
                    challenger_name TEXT,
                    opponent_id TEXT DEFAULT '',
                    opponent_name TEXT DEFAULT '',
                    level TEXT,
                    questions TEXT DEFAULT '[]',
                    challenger_score INTEGER DEFAULT -1,
                    opponent_score INTEGER DEFAULT -1,
                    status TEXT DEFAULT 'waiting',
                    created_at TEXT
                )
            """)
            # Add missing columns if upgrading
            for col, defn in [
                ("is_premium","BOOLEAN DEFAULT FALSE"),
                ("chat_count","TEXT DEFAULT '{}'"),
                ("writing_count","TEXT DEFAULT '{}'"),
                ("speaking_count","TEXT DEFAULT '{}'"),
                ("invite_count","INTEGER DEFAULT 0"),
                ("invited_by","TEXT DEFAULT ''"),
                ("points","INTEGER DEFAULT 0"),
                ("challenges_won","INTEGER DEFAULT 0"),
                ("challenges_played","INTEGER DEFAULT 0"),
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

# ─── Challenge Functions ───────────────────────────────────────────────────────
def create_challenge(challenger_id, challenger_name, level, questions):
    k = str(challenger_id)
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO challenges (challenger_id,challenger_name,level,questions,status,created_at)
                VALUES (%s,%s,%s,%s,'waiting',%s) RETURNING id""",
                (k, challenger_name, level, json.dumps(questions), today))
            cid = cur.fetchone()[0]
        conn.commit()
    return cid

def get_active_challenge():
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM challenges WHERE status='waiting' ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None

def get_ongoing_challenge():
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM challenges WHERE status='ongoing' ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None

def accept_challenge(challenge_id, opponent_id, opponent_name):
    k = str(opponent_id)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE challenges SET opponent_id=%s,opponent_name=%s,status='ongoing' WHERE id=%s",
                (k, opponent_name, challenge_id))
        conn.commit()

def submit_challenge_score(challenge_id, uid, score):
    k = str(uid)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM challenges WHERE id=%s", (challenge_id,))
            ch = dict(cur.fetchone())
            if ch["challenger_id"] == k:
                cur.execute("UPDATE challenges SET challenger_score=%s WHERE id=%s", (score, challenge_id))
            else:
                cur.execute("UPDATE challenges SET opponent_score=%s WHERE id=%s", (score, challenge_id))
            # Check if both done
            cur.execute("SELECT * FROM challenges WHERE id=%s", (challenge_id,))
            ch = dict(cur.fetchone())
            if ch["challenger_score"] >= 0 and ch["opponent_score"] >= 0:
                cur.execute("UPDATE challenges SET status='finished' WHERE id=%s", (challenge_id,))
        conn.commit()
    return ch

def get_recent_challenges(limit=5):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM challenges WHERE status='finished' ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]

def add_points(uid, pts):
    k = str(uid)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET points=points+%s WHERE uid=%s", (pts, k))
        conn.commit()

def update_challenge_stats(uid, won):
    k = str(uid)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET challenges_played=challenges_played+1 WHERE uid=%s", (k,))
            if won:
                cur.execute("UPDATE users SET challenges_won=challenges_won+1 WHERE uid=%s", (k,))
        conn.commit()

def get_leaderboard(limit=10):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT uid,name,points,challenges_won,challenges_played FROM users ORDER BY points DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]

# ─── Invite Functions ──────────────────────────────────────────────────────────
def register_invite(new_uid, referrer_uid):
    k = str(new_uid); r = str(referrer_uid)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET invited_by=%s WHERE uid=%s AND (invited_by='' OR invited_by IS NULL)", (r, k))
            cur.execute("UPDATE users SET invite_count=invite_count+1 WHERE uid=%s", (r,))
            cur.execute("SELECT invite_count FROM users WHERE uid=%s", (r,))
            row = cur.fetchone()
        conn.commit()
    if row and row[0] >= 30:
        set_premium(r, True)
        return True  # earned premium
    return False

def get_invite_count(uid):
    k = str(uid)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT invite_count FROM users WHERE uid=%s", (k,))
            row = cur.fetchone()
            return row[0] if row else 0

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

PLACEMENT_TEST=[
    {"q":"___ you interested in sport?","options":["A) Be","B) Am","C) Is","D) Are"],"answer":"D"},
    {"q":"My ___ is a writer and his books are very popular.","options":["A) aunt","B) uncle","C) sister","D) mother"],"answer":"B"},
    {"q":"We live in the city centre and our house ___ have a big garden.","options":["A) doesn't","B) isn't","C) aren't","D) don't"],"answer":"A"},
    {"q":"There ___ a lot of people outside the school. What's the problem?","options":["A) are","B) is","C) be","D) am"],"answer":"A"},
    {"q":"Cathy ___ a game on her computer at the moment.","options":["A) plays","B) is playing","C) to play","D) play"],"answer":"B"},
    {"q":"Paul is very ___. He doesn't go out a lot.","options":["A) bored","B) confident","C) angry","D) shy"],"answer":"D"},
    {"q":"___ you like to come out with us tonight?","options":["A) Do","B) Would","C) Are","D) Will"],"answer":"B"},
    {"q":"Dad's ___ work right now. He's a teacher.","options":["A) on","B) at","C) for","D) by"],"answer":"B"},
    {"q":"Did you ___ shopping after school yesterday?","options":["A) went","B) goed","C) going","D) go"],"answer":"D"},
    {"q":"There wasn't ___ milk for breakfast this morning.","options":["A) a","B) some","C) the","D) any"],"answer":"D"},
    {"q":"I ___ five emails before school today.","options":["A) sent","B) sended","C) did send","D) was send"],"answer":"A"},
    {"q":"Turn ___ and you'll see the museum on the left.","options":["A) on the right","B) rightly","C) by the right","D) right"],"answer":"D"},
    {"q":"The beach was very crowded ___ Monday.","options":["A) in","B) on","C) at","D) to"],"answer":"B"},
    {"q":"I ___ the new Batman film yet. Is it any good?","options":["A) haven't seen","B) didn't see","C) don't see","D) am not seen"],"answer":"A"},
    {"q":"Tom got the ___ marks in the class for his homework.","options":["A) worse","B) worst","C) baddest","D) most bad"],"answer":"B"},
    {"q":"You ___ eat all that cake! It isn't good for you.","options":["A) don't","B) may not","C) should not","D) will not"],"answer":"C"},
    {"q":"How ___ time have we got to do this exercise?","options":["A) long","B) many","C) much","D) quick"],"answer":"C"},
    {"q":"Don't forget to get ___ the bus at Station Road.","options":["A) out","B) off","C) over","D) down"],"answer":"B"},
    {"q":"Our teacher speaks English to us ___ so that we can understand her.","options":["A) slow","B) slower","C) more slow","D) slowly"],"answer":"D"},
    {"q":"My sister ___ speak French when she was only six years old.","options":["A) was","B) should","C) could","D) had"],"answer":"C"},
    {"q":"I really enjoy ___ new languages and I'd like to learn Italian soon.","options":["A) to learn","B) learning","C) learn","D) learned"],"answer":"B"},
    {"q":"My father has been a pilot ___ twenty years.","options":["A) since","B) for","C) until","D) by"],"answer":"B"},
    {"q":"Quick – get the food inside! It ___ any moment.","options":["A) rains","B) is raining","C) is going to rain","D) can rain"],"answer":"C"},
    {"q":"Sam asked me if I ___ a lift home after the concert.","options":["A) had wanted","B) wanted","C) would want","D) want"],"answer":"B"},
    {"q":"Which train ___ for when I saw you on the platform on Sunday?","options":["A) did you wait","B) were you waiting","C) have you waited","D) are you waiting"],"answer":"B"},
    {"q":"I ___ not be home this evening. Phone me on my mobile.","options":["A) can","B) could","C) may","D) should"],"answer":"C"},
    {"q":"I hope you ___ a good time at the moment in Greece!","options":["A) are having","B) have","C) have had","D) had"],"answer":"A"},
    {"q":"If we ___ in the countryside, we'd have much better views.","options":["A) lived","B) were live","C) would live","D) live"],"answer":"A"},
    {"q":"By the time we arrived at the station, the train ___.","options":["A) already left","B) has already left","C) had already left","D) was already leaving"],"answer":"C"},
    {"q":"She suggested ___ to the new restaurant near the park.","options":["A) to go","B) going","C) that we go","D) both B and C"],"answer":"D"},
]

def get_placement_level(score):
    if score<=6: return "🟢 Beginner","You are at the Beginner level. Focus on basic grammar and vocabulary. Premier Tutoring Center's Beginner course is perfect for you!"
    elif score<=12: return "🔵 Elementary","You are at the Elementary level. You know the basics but need to build confidence. Premier's Elementary course will help you grow!"
    elif score<=18: return "🟡 Pre-Intermediate","You are at the Pre-Intermediate level. You have a good foundation. Premier's Pre-Intermediate course will take you to the next level!"
    elif score<=24: return "🟠 Intermediate","You are at the Intermediate level. You communicate well but need to refine your skills. Premier's Intermediate course is ideal for you!"
    else: return "🔴 Advanced","You are at the Advanced level. Excellent English! Premier's Advanced course will help you achieve fluency and master complex structures!"

MEMES=[
    "😂 English spelling rule:\n\"I before E except after C\"\n\nExcept in: weird, their, foreign, science...\n\nJust kidding, there are NO rules 😭",
    "😂 Teacher: Use 'defeat', 'defence' and 'detail' in one sentence.\nStudent: De feet of de cat went over de tail into de fence 💀",
    "😂 English: \"gh\" can be silent → night, though\nAlso English: \"gh\" sounds like F → enough, laugh\nAlso English: \"gh\" sounds like G → ghost\n\nEnglish: I do what I want 😤",
    "😂 Me before learning English:\n\"How hard can it be?\"\n\nEnglish:\nRead = Reed\nRead = Red\nSame word. Different pronunciation. 😶",
    "😂 Student: Can I go to the bathroom?\nTeacher: I don't know, CAN you?\nStudent: *slowly sits back down* 😤",
    "😂 How to write in English:\nStep 1: Write\nStep 2: Delete\nStep 3: Write again\nStep 4: Delete again\nStep 5: Cry\nStep 6: Submit anyway 😭",
    "😂 The word 'queue' is just the letter Q followed by 4 silent letters that do absolutely nothing 💀",
    "😂 Me learning a new English word:\nDay 1: I will never forget this!\nDay 2: What was that word again? 🤔",
    "😂 'Dreamt' is the only English word that ends in 'mt'.\n\nYou're welcome. Now you'll never forget it 😄",
    "😂 English student life:\nMonday: I'm going to study hard!\nTuesday: Maybe tomorrow\nWednesday: Netflix first\nThursday-Sunday: *exists*\nMonday: I'm going to study hard! 😭",
    "😂 Interviewer: What's your greatest weakness?\nStudent: English\nInterviewer: Can you elaborate?\nStudent: No 😐",
    "😂 The word 'colonel' is pronounced 'kernel'.\n\nWho hurt you, English? 😢",
    "😂 Fun fact: 'Dreamt' is the only English word ending in 'mt'. Also 'undreamt'. English surprises you every day 😂",
    "😂 English: 'w' is silent in 'write' and 'wrong'\nAlso English: 'w' is NOT silent in 'war'\n\nWhy? Because English said so 😂",
    "😂 English has 26 letters but somehow makes 44 different sounds.\n\nMathematics has left the chat 📉",
]

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

READING_ARTICLES={
    "beginner":[
        {"title":"My Family","text":"My name is Sara. I have a small family. I have a mother, a father, and one brother. My mother is a teacher. My father is a doctor. My brother is seven years old. We live in a house. We have a dog. His name is Max. I love my family.",
         "questions":[
             {"statement":"Sara has two brothers.","answer":"false","explanation":"Sara has ONE brother, not two."},
             {"statement":"Sara's mother works as a teacher.","answer":"true","explanation":"The text says My mother is a teacher. ✅"},
             {"statement":"The family has a cat.","answer":"false","explanation":"They have a DOG named Max, not a cat."},
             {"statement":"Sara's brother is seven years old.","answer":"true","explanation":"The text says My brother is seven years old. ✅"},
             {"statement":"Sara lives in an apartment.","answer":"false","explanation":"The text says We live in a house, not an apartment."},
         ]},
        {"title":"My Day","text":"I wake up at seven o'clock. I eat breakfast with my family. I go to school at eight o'clock. At school, I study English and Math. I eat lunch at twelve o'clock. After school, I play with my friends. I go to bed at nine o'clock.",
         "questions":[
             {"statement":"The person wakes up at six o'clock.","answer":"false","explanation":"They wake up at SEVEN o'clock, not six."},
             {"statement":"The person studies English at school.","answer":"true","explanation":"The text says I study English and Math. ✅"},
             {"statement":"The person eats lunch alone.","answer":"not given","explanation":"The text doesn't say who they eat lunch with."},
             {"statement":"The person goes to bed at nine o'clock.","answer":"true","explanation":"The text says I go to bed at nine o'clock. ✅"},
             {"statement":"The person has three subjects at school.","answer":"false","explanation":"Only two subjects are mentioned: English and Math."},
         ]},
        {"title":"The Weather","text":"Today is a sunny day. The sky is blue and there are no clouds. It is warm outside. The temperature is 25 degrees. Children are playing in the park. Birds are singing in the trees. I like sunny days because I can play outside. Tomorrow, the weather will be cloudy and cold.",
         "questions":[
             {"statement":"Today is a rainy day.","answer":"false","explanation":"Today is a sunny day, not rainy."},
             {"statement":"Children are playing in the park.","answer":"true","explanation":"The text says children are playing in the park. ✅"},
             {"statement":"The temperature is 30 degrees today.","answer":"false","explanation":"The temperature is 25 degrees, not 30."},
             {"statement":"Tomorrow will be warm and sunny.","answer":"false","explanation":"Tomorrow will be cloudy and cold."},
             {"statement":"The writer lives near a park.","answer":"not given","explanation":"The text does not say where the writer lives."},
         ]},
        {"title":"My School","text":"I go to a big school. There are five hundred students in my school. My school has thirty classrooms. We have a library, a gym, and a cafeteria. My favourite class is English. My teacher's name is Mr. Smith. He is a kind teacher. School starts at eight in the morning and finishes at three in the afternoon.",
         "questions":[
             {"statement":"The school has five hundred students.","answer":"true","explanation":"The text says there are five hundred students. ✅"},
             {"statement":"The school has a swimming pool.","answer":"not given","explanation":"A swimming pool is not mentioned in the text."},
             {"statement":"The writer's favourite class is Math.","answer":"false","explanation":"The writer's favourite class is English, not Math."},
             {"statement":"Mr. Smith is the English teacher.","answer":"true","explanation":"The text says the teacher is Mr. Smith and the favourite class is English. ✅"},
             {"statement":"School finishes at four in the afternoon.","answer":"false","explanation":"School finishes at three in the afternoon, not four."},
         ]},
        {"title":"Food I Like","text":"I like many different foods. For breakfast, I eat bread and eggs. I drink milk or orange juice. For lunch, I usually eat rice and vegetables. I also like chicken and fish. My favourite fruit is apple. I do not like spicy food. In the evening, my family eats dinner together. We often have soup and salad.",
         "questions":[
             {"statement":"The writer eats bread and eggs for breakfast.","answer":"true","explanation":"The text says for breakfast, I eat bread and eggs. ✅"},
             {"statement":"The writer's favourite fruit is banana.","answer":"false","explanation":"The writer's favourite fruit is apple, not banana."},
             {"statement":"The writer likes spicy food.","answer":"false","explanation":"The text says I do not like spicy food."},
             {"statement":"The family eats dinner together.","answer":"true","explanation":"The text says my family eats dinner together. ✅"},
             {"statement":"The writer drinks coffee for breakfast.","answer":"false","explanation":"The writer drinks milk or orange juice, not coffee."},
         ]},
        {"title":"My Bedroom","text":"My bedroom is small but comfortable. I have a bed, a desk, and a wardrobe. My bed is next to the window. I have a bookshelf with many books. My favourite colour is blue, so my walls are blue. I have a computer on my desk. I do my homework at my desk every evening. I keep my room clean and tidy.",
         "questions":[
             {"statement":"The bedroom is large.","answer":"false","explanation":"The text says the bedroom is small."},
             {"statement":"The bed is next to the window.","answer":"true","explanation":"The text says my bed is next to the window. ✅"},
             {"statement":"The walls are painted green.","answer":"false","explanation":"The walls are blue, not green."},
             {"statement":"The writer has a computer in the bedroom.","answer":"true","explanation":"The text says I have a computer on my desk. ✅"},
             {"statement":"The writer has a television in the bedroom.","answer":"not given","explanation":"A television is not mentioned in the text."},
         ]},
        {"title":"My Hobby","text":"My hobby is drawing. I draw every day after school. I use pencils, pens, and colours. I like to draw animals and people. My favourite animal to draw is a horse. I have three sketchbooks full of my drawings. My mother says I am a good artist. One day, I want to be a professional artist.",
         "questions":[
             {"statement":"The writer's hobby is painting.","answer":"false","explanation":"The writer's hobby is drawing, not painting."},
             {"statement":"The writer draws every day after school.","answer":"true","explanation":"The text says I draw every day after school. ✅"},
             {"statement":"The writer's favourite animal to draw is a cat.","answer":"false","explanation":"The favourite animal to draw is a horse, not a cat."},
             {"statement":"The writer has three sketchbooks.","answer":"true","explanation":"The text says I have three sketchbooks. ✅"},
             {"statement":"The writer's father says they are a good artist.","answer":"false","explanation":"It is the writer's mother, not father, who says this."},
         ]},
        {"title":"Going to the Market","text":"On Saturdays, my family goes to the market. The market is near our house. We buy fruit, vegetables, and meat. My mother always makes a shopping list. My father carries the bags. I help my mother choose the best vegetables. The market is very busy in the morning. We always go early to get fresh food.",
         "questions":[
             {"statement":"The family goes to the market on Sundays.","answer":"false","explanation":"The family goes on Saturdays, not Sundays."},
             {"statement":"The market is near their house.","answer":"true","explanation":"The text says the market is near our house. ✅"},
             {"statement":"The mother makes a shopping list.","answer":"true","explanation":"The text says my mother always makes a shopping list. ✅"},
             {"statement":"The family goes to the market in the evening.","answer":"false","explanation":"They go in the morning, not the evening."},
             {"statement":"The writer helps choose the vegetables.","answer":"true","explanation":"The text says I help my mother choose the best vegetables. ✅"},
         ]},
        {"title":"My Best Friend","text":"My best friend's name is Ali. He is twelve years old. We go to the same school. Ali is funny and kind. He likes football and video games. We play football together every weekend. Ali is good at Math. He always helps me with my homework. I am lucky to have such a good friend.",
         "questions":[
             {"statement":"Ali is thirteen years old.","answer":"false","explanation":"Ali is twelve years old, not thirteen."},
             {"statement":"Ali and the writer go to the same school.","answer":"true","explanation":"The text says we go to the same school. ✅"},
             {"statement":"Ali likes basketball.","answer":"false","explanation":"Ali likes football, not basketball."},
             {"statement":"Ali helps the writer with homework.","answer":"true","explanation":"The text says he always helps me with my homework. ✅"},
             {"statement":"The writer helps Ali with English.","answer":"not given","explanation":"The text does not say what subject the writer helps Ali with."},
         ]},
        {"title":"Seasons","text":"There are four seasons in a year: spring, summer, autumn, and winter. In spring, flowers grow and birds sing. In summer, it is hot and sunny. Children swim in the sea. In autumn, leaves fall from the trees. The weather becomes cool. In winter, it is cold and sometimes it snows. People wear warm clothes. My favourite season is summer.",
         "questions":[
             {"statement":"There are four seasons in a year.","answer":"true","explanation":"The text says there are four seasons. ✅"},
             {"statement":"Leaves fall from trees in spring.","answer":"false","explanation":"Leaves fall in autumn, not spring."},
             {"statement":"Children swim in the sea in summer.","answer":"true","explanation":"The text says children swim in the sea in summer. ✅"},
             {"statement":"The writer's favourite season is winter.","answer":"false","explanation":"The writer's favourite season is summer, not winter."},
             {"statement":"It always snows in winter.","answer":"false","explanation":"The text says sometimes it snows — not always."},
         ]},
    ],
    "elementary":[
        {"title":"A Trip to the Market","text":"Every Saturday, my mother and I go to the market. The market is very busy in the morning. We buy fresh vegetables and fruit. My mother always buys tomatoes, onions, and apples. Sometimes we buy fish too. The market has many colours and smells. I like going there because it is fun and we meet our neighbours.",
         "questions":[
             {"statement":"They go to the market every Sunday.","answer":"false","explanation":"They go every SATURDAY, not Sunday."},
             {"statement":"The mother always buys tomatoes.","answer":"true","explanation":"The text says my mother always buys tomatoes, onions, and apples. ✅"},
             {"statement":"They always buy fish at the market.","answer":"false","explanation":"The text says sometimes we buy fish — not always."},
             {"statement":"The writer enjoys going to the market.","answer":"true","explanation":"The text says I like going there because it is fun. ✅"},
             {"statement":"The market is open on weekdays only.","answer":"not given","explanation":"The text doesn't mention weekday opening hours."},
         ]},
        {"title":"Healthy Food","text":"Eating healthy food is very important. Fruit and vegetables give us vitamins. Vitamins help our body to stay strong. Bread and rice give us energy. Milk and cheese are good for our bones. We should drink eight glasses of water every day. Fast food is not healthy because it has too much oil and salt.",
         "questions":[
             {"statement":"Fruit and vegetables give us energy.","answer":"false","explanation":"Fruit gives VITAMINS. Bread and rice give energy."},
             {"statement":"Milk is good for our bones.","answer":"true","explanation":"The text says milk and cheese are good for our bones. ✅"},
             {"statement":"We should drink ten glasses of water daily.","answer":"false","explanation":"The text says EIGHT glasses, not ten."},
             {"statement":"Fast food contains too much oil and salt.","answer":"true","explanation":"The text says exactly this. ✅"},
             {"statement":"Vegetables are more important than fruit.","answer":"not given","explanation":"The text mentions both equally. No comparison is made!"},
         ]},
        {"title":"A Day at the Zoo","text":"Last Sunday, my family visited the zoo. We saw many different animals. There were lions, elephants, giraffes, and monkeys. The lions were sleeping when we arrived. The giraffes were eating leaves from tall trees. My favourite animals were the monkeys because they were very funny. We also watched a dolphin show. We spent four hours at the zoo. It was a wonderful day.",
         "questions":[
             {"statement":"The family visited the zoo on Saturday.","answer":"false","explanation":"They visited on Sunday, not Saturday."},
             {"statement":"The lions were sleeping when the family arrived.","answer":"true","explanation":"The text says the lions were sleeping when we arrived. ✅"},
             {"statement":"The writer's favourite animals were the elephants.","answer":"false","explanation":"The writer's favourite animals were the monkeys, not elephants."},
             {"statement":"The family watched a dolphin show.","answer":"true","explanation":"The text says we also watched a dolphin show. ✅"},
             {"statement":"The family spent six hours at the zoo.","answer":"false","explanation":"They spent four hours at the zoo, not six."},
         ]},
        {"title":"Learning English","text":"English is an important language. Many people around the world speak English. It is useful for travel, business, and study. Learning English is not easy, but it is possible. You need to practise every day. Reading books and watching films in English helps a lot. Speaking with native speakers is also very helpful. I have been learning English for two years. Now I can understand and speak basic English.",
         "questions":[
             {"statement":"English is useful for travel and business.","answer":"true","explanation":"The text says English is useful for travel, business, and study. ✅"},
             {"statement":"Learning English is easy.","answer":"false","explanation":"The text says learning English is not easy."},
             {"statement":"The writer has been learning English for three years.","answer":"false","explanation":"The writer has been learning for two years, not three."},
             {"statement":"Watching films in English does not help learning.","answer":"false","explanation":"The text says watching films in English helps a lot."},
             {"statement":"The writer can now speak advanced English.","answer":"false","explanation":"The writer can understand and speak basic English, not advanced."},
         ]},
        {"title":"My Neighbourhood","text":"I live in a quiet neighbourhood. There are many trees and gardens. My street has fifteen houses. There is a small park near my house where children play after school. There is also a bakery and a small supermarket on my street. My neighbours are friendly and helpful. We often help each other. I like living in my neighbourhood because it is peaceful and safe.",
         "questions":[
             {"statement":"The writer's street has twenty houses.","answer":"false","explanation":"The street has fifteen houses, not twenty."},
             {"statement":"There is a park near the writer's house.","answer":"true","explanation":"The text says there is a small park near my house. ✅"},
             {"statement":"There is a hospital on the writer's street.","answer":"not given","explanation":"A hospital is not mentioned in the text."},
             {"statement":"The writer's neighbours are friendly.","answer":"true","explanation":"The text says my neighbours are friendly and helpful. ✅"},
             {"statement":"The writer finds their neighbourhood noisy.","answer":"false","explanation":"The writer describes their neighbourhood as quiet and peaceful."},
         ]},
        {"title":"A Birthday Party","text":"Last week, I went to my friend's birthday party. Her name is Lola. She turned eleven years old. There were fifteen children at the party. We played games and danced. There was a big chocolate cake with candles. We sang Happy Birthday to Lola. She got many presents including books, toys, and clothes. The party finished at eight o'clock. It was a very enjoyable evening.",
         "questions":[
             {"statement":"Lola turned twelve years old.","answer":"false","explanation":"Lola turned eleven, not twelve."},
             {"statement":"There were fifteen children at the party.","answer":"true","explanation":"The text says there were fifteen children. ✅"},
             {"statement":"The cake was vanilla flavoured.","answer":"false","explanation":"The cake was chocolate, not vanilla."},
             {"statement":"Lola received books as presents.","answer":"true","explanation":"The text says she got books, toys, and clothes. ✅"},
             {"statement":"The party finished at nine o'clock.","answer":"false","explanation":"The party finished at eight o'clock, not nine."},
         ]},
        {"title":"Sports and Exercise","text":"Exercise is very important for our health. There are many types of sport. Football, basketball, and tennis are popular sports. Swimming is also very good for the body. You should exercise at least three times a week. Exercise makes you stronger and healthier. It also helps you feel happy. Many people go to the gym. Others prefer to exercise outside in the park. I play football with my friends every weekend.",
         "questions":[
             {"statement":"Football, basketball, and tennis are mentioned as popular sports.","answer":"true","explanation":"The text lists all three as popular sports. ✅"},
             {"statement":"You should exercise every day.","answer":"false","explanation":"The text says at least three times a week, not every day."},
             {"statement":"Exercise makes you feel happy.","answer":"true","explanation":"The text says exercise also helps you feel happy. ✅"},
             {"statement":"The writer swims every weekend.","answer":"false","explanation":"The writer plays football every weekend, not swimming."},
             {"statement":"Going to the gym is the best way to exercise.","answer":"not given","explanation":"The text does not say which method is best."},
         ]},
        {"title":"My Favourite Season","text":"My favourite season is spring. In spring, the weather is warm and sunny. Flowers start to grow and trees become green. Birds sing in the morning. Children play outside after school. In spring, we celebrate Navruz in Uzbekistan. We make special food and wear colourful clothes. Spring makes everyone happy.",
         "questions":[
             {"statement":"The writer's favourite season is summer.","answer":"false","explanation":"The writer's favourite season is spring, not summer."},
             {"statement":"Flowers grow in spring.","answer":"true","explanation":"The text says flowers start to grow in spring. ✅"},
             {"statement":"Navruz is celebrated in spring in Uzbekistan.","answer":"true","explanation":"The text says we celebrate Navruz in spring. ✅"},
             {"statement":"Children stay indoors in spring.","answer":"false","explanation":"The text says children play outside after school in spring."},
             {"statement":"Special food is eaten during Navruz.","answer":"true","explanation":"The text says we make special food during Navruz. ✅"},
         ]},
        {"title":"My Pet","text":"I have a pet cat. Her name is Mimi. She is two years old. She is white with black spots. Mimi likes to sleep and eat. Her favourite food is fish. Every morning, I give her food and water. She sleeps on my bed at night. She is very soft and friendly. Sometimes she plays with a ball of wool. I love Mimi very much.",
         "questions":[
             {"statement":"The pet's name is Mimi.","answer":"true","explanation":"The text says her name is Mimi. ✅"},
             {"statement":"The cat is black with white spots.","answer":"false","explanation":"The cat is white with black spots, not black with white spots."},
             {"statement":"Mimi's favourite food is chicken.","answer":"false","explanation":"Mimi's favourite food is fish, not chicken."},
             {"statement":"Mimi sleeps on the writer's bed.","answer":"true","explanation":"The text says she sleeps on my bed at night. ✅"},
             {"statement":"The cat is three years old.","answer":"false","explanation":"The cat is two years old, not three."},
         ]},
        {"title":"A Visit to the Doctor","text":"Last Monday, I did not feel well. I had a headache and a sore throat. My mother took me to the doctor. The doctor's name was Dr. Karimov. He checked my temperature. My temperature was 38 degrees. The doctor said I had a cold. He gave me some medicine and told me to rest. He said I should drink lots of water. After three days, I felt much better.",
         "questions":[
             {"statement":"The writer visited the doctor on Tuesday.","answer":"false","explanation":"The visit was on Monday, not Tuesday."},
             {"statement":"The writer had a headache and sore throat.","answer":"true","explanation":"The text says I had a headache and a sore throat. ✅"},
             {"statement":"The doctor's name was Dr. Karimov.","answer":"true","explanation":"The text says the doctor's name was Dr. Karimov. ✅"},
             {"statement":"The doctor said the writer had flu.","answer":"false","explanation":"The doctor said the writer had a cold, not flu."},
             {"statement":"The writer recovered after three days.","answer":"true","explanation":"The text says after three days, I felt much better. ✅"},
         ]},
    ],
    "pre_intermediate":[
        {"title":"Social Media and Communication","text":"Social media has changed the way people communicate. Platforms like Instagram and Telegram allow people to share photos, news, and ideas instantly. Many people use social media to stay connected with friends and family who live far away. However, some experts believe that too much social media can be harmful. It can reduce face-to-face communication and affect mental health. The key is to use social media in a balanced way.",
         "questions":[
             {"statement":"Instagram and Telegram are mentioned as examples of social media.","answer":"true","explanation":"The text says platforms like Instagram and Telegram. ✅"},
             {"statement":"All experts agree that social media is harmful.","answer":"false","explanation":"SOME experts believe it can be harmful — not all."},
             {"statement":"Social media can negatively affect mental health.","answer":"true","explanation":"The text says it can affect mental health. ✅"},
             {"statement":"The article recommends deleting all social media apps.","answer":"false","explanation":"The article says to use it in a balanced way, not to delete it."},
             {"statement":"More than one billion people use social media.","answer":"not given","explanation":"No statistics about user numbers are mentioned."},
         ]},
        {"title":"The Importance of Sleep","text":"Many people do not get enough sleep. Doctors recommend that adults sleep between seven and nine hours every night. During sleep, our brain processes information from the day and stores memories. Sleep also helps our body repair itself. People who do not sleep enough often feel tired, find it hard to concentrate, and get sick more easily. Good sleep habits include going to bed at the same time each night and avoiding screens before sleep.",
         "questions":[
             {"statement":"Doctors recommend adults sleep at least seven hours.","answer":"true","explanation":"The text says between seven and nine hours. ✅"},
             {"statement":"The brain stores memories during sleep.","answer":"true","explanation":"The text says the brain processes information and stores memories. ✅"},
             {"statement":"Lack of sleep only affects concentration.","answer":"false","explanation":"It causes tiredness, concentration problems, AND getting sick more easily."},
             {"statement":"You should sleep with the lights on.","answer":"false","explanation":"Good habits include avoiding screens — lights are not mentioned."},
             {"statement":"Children need more sleep than adults.","answer":"not given","explanation":"The text only talks about adults. Children are not mentioned."},
         ]},
        {"title":"Online Shopping","text":"Online shopping has become very popular in recent years. You can buy almost anything from your phone or computer without leaving home. The main advantages are convenience and saving time. You can compare prices easily and find discounts. However, there are some disadvantages. You cannot see or touch products before buying. Delivery can take several days. Sometimes products arrive damaged or different from the pictures. Despite these problems, more and more people prefer to shop online.",
         "questions":[
             {"statement":"Online shopping allows you to compare prices easily.","answer":"true","explanation":"The text says you can compare prices easily. ✅"},
             {"statement":"You can always see products before buying online.","answer":"false","explanation":"The text says you cannot see or touch products before buying."},
             {"statement":"Delivery always takes one day.","answer":"false","explanation":"The text says delivery can take several days, not always one day."},
             {"statement":"Online shopping is becoming less popular.","answer":"false","explanation":"The text says more and more people prefer to shop online."},
             {"statement":"All online products arrive in perfect condition.","answer":"false","explanation":"The text says sometimes products arrive damaged or different from the pictures."},
         ]},
        {"title":"Environmental Problems","text":"Our planet faces many serious environmental problems. Air pollution from factories and cars causes breathing problems for millions of people. Plastic waste is filling our oceans and harming sea animals. Forests are being cut down to make space for farms and buildings. This destroys the homes of many animals. Global temperatures are rising because of greenhouse gases. Governments and individuals both need to take action to protect our environment before it is too late.",
         "questions":[
             {"statement":"Air pollution comes only from factories.","answer":"false","explanation":"The text says pollution comes from factories AND cars."},
             {"statement":"Plastic waste is harming sea animals.","answer":"true","explanation":"The text says plastic waste is filling our oceans and harming sea animals. ✅"},
             {"statement":"Forests are being cut down for farms and buildings.","answer":"true","explanation":"The text says forests are being cut down to make space for farms and buildings. ✅"},
             {"statement":"Only governments need to take action on the environment.","answer":"false","explanation":"The text says governments AND individuals both need to take action."},
             {"statement":"The article was written by an environmental scientist.","answer":"not given","explanation":"The author's identity is not mentioned anywhere."},
         ]},
        {"title":"City Life vs Village Life","text":"Many people today face the choice between living in a city or a village. Cities offer many advantages such as better jobs, hospitals, schools, and entertainment. Public transport is also more convenient in cities. However, city life can be stressful and expensive. Noise, pollution, and traffic are common problems. Village life, on the other hand, is quieter and more relaxed. The air is cleaner and people are generally friendlier. However, there are fewer job opportunities and services in villages.",
         "questions":[
             {"statement":"Cities offer better hospitals and schools than villages.","answer":"true","explanation":"The text lists hospitals and schools as city advantages. ✅"},
             {"statement":"City life is described as relaxed.","answer":"false","explanation":"The text says city life can be stressful. Village life is described as relaxed."},
             {"statement":"The air is cleaner in villages than in cities.","answer":"true","explanation":"The text says the air is cleaner in villages. ✅"},
             {"statement":"Villages have more job opportunities than cities.","answer":"false","explanation":"The text says there are fewer job opportunities in villages."},
             {"statement":"The writer prefers to live in a village.","answer":"not given","explanation":"The writer does not state a personal preference."},
         ]},
        {"title":"The Benefits of Reading","text":"Reading is one of the best habits you can develop. It improves your vocabulary and helps you learn new things every day. Reading fiction helps you understand other people's feelings and perspectives. Non-fiction books teach you about science, history, and the world. Reading also reduces stress. Studies show that just six minutes of reading can reduce stress by up to 68 percent. People who read regularly tend to have better concentration and memory. Reading before bed can also help you sleep better.",
         "questions":[
             {"statement":"Reading improves vocabulary.","answer":"true","explanation":"The text says reading improves your vocabulary. ✅"},
             {"statement":"Only non-fiction books are beneficial for readers.","answer":"false","explanation":"The text says both fiction and non-fiction have benefits."},
             {"statement":"Six minutes of reading can reduce stress by up to 68 percent.","answer":"true","explanation":"The text states this directly. ✅"},
             {"statement":"Reading before bed makes it harder to sleep.","answer":"false","explanation":"The text says reading before bed can help you sleep better."},
             {"statement":"The article recommends reading for at least one hour daily.","answer":"not given","explanation":"No daily time recommendation is given in the text."},
         ]},
        {"title":"Travel and Culture","text":"Travelling to different countries is one of the best ways to learn about the world. When you travel, you see new places, meet new people, and experience different cultures. You try new food and hear new languages. Travelling can change the way you think about life. It makes you more open-minded and tolerant. However, travel can be expensive. Budget airlines and cheap accommodation have made travel more accessible for many people. Even travelling to a nearby city or town can broaden your horizons.",
         "questions":[
             {"statement":"Travelling helps you become more open-minded.","answer":"true","explanation":"The text says travelling makes you more open-minded and tolerant. ✅"},
             {"statement":"Travel is now free for everyone.","answer":"false","explanation":"The text says travel can be expensive, though budget options have made it more accessible."},
             {"statement":"You can only benefit from international travel.","answer":"false","explanation":"The text says even travelling to a nearby city can broaden your horizons."},
             {"statement":"Budget airlines have made travel more accessible.","answer":"true","explanation":"The text explicitly states this. ✅"},
             {"statement":"The article was written by a professional travel writer.","answer":"not given","explanation":"The author's profession is not mentioned."},
         ]},
        {"title":"Technology in Daily Life","text":"Technology has changed almost every aspect of our daily lives. Smartphones allow us to communicate, shop, and access information at any time. Smart home devices can control heating, lighting, and security. Online banking means we no longer need to visit a bank. However, technology also brings problems. Too much screen time affects our health and sleep. Children who spend too much time on devices may struggle with social skills. Cybercrime and privacy issues are also growing concerns. Finding the right balance with technology is essential.",
         "questions":[
             {"statement":"Smartphones allow us to shop and access information.","answer":"true","explanation":"The text says smartphones allow us to communicate, shop, and access information. ✅"},
             {"statement":"Online banking requires visiting a bank.","answer":"false","explanation":"The text says online banking means we no longer need to visit a bank."},
             {"statement":"Too much screen time affects health and sleep.","answer":"true","explanation":"The text says too much screen time affects our health and sleep. ✅"},
             {"statement":"Technology has no negative effects on children.","answer":"false","explanation":"The text says children may struggle with social skills from too much device use."},
             {"statement":"All cybercrime problems have been solved.","answer":"not given","explanation":"The text mentions cybercrime as a growing concern but does not say it has been solved."},
         ]},
        {"title":"A Healthy Lifestyle","text":"Living a healthy lifestyle is important for both body and mind. A balanced diet with plenty of fruit, vegetables, and protein helps your body function well. Regular exercise — at least 30 minutes a day — keeps your heart and muscles strong. Getting enough sleep is also essential for good health. Stress management is another important factor. Meditation, hobbies, and spending time with friends can help reduce stress. Avoiding smoking and drinking too much alcohol also contributes to a longer, healthier life.",
         "questions":[
             {"statement":"A balanced diet should include fruit, vegetables, and protein.","answer":"true","explanation":"The text says a balanced diet with fruit, vegetables, and protein is important. ✅"},
             {"statement":"You should exercise for at least one hour a day.","answer":"false","explanation":"The text recommends at least 30 minutes a day, not one hour."},
             {"statement":"Meditation can help reduce stress.","answer":"true","explanation":"The text lists meditation as one way to help reduce stress. ✅"},
             {"statement":"Drinking a little alcohol is healthy.","answer":"not given","explanation":"The text says avoiding too much alcohol contributes to health, but does not say a little is healthy."},
             {"statement":"Sleep is not important for a healthy lifestyle.","answer":"false","explanation":"The text says getting enough sleep is essential for good health."},
         ]},
        {"title":"Volunteering","text":"Volunteering means giving your time to help others without being paid. Many people volunteer at hospitals, schools, animal shelters, and community centres. Volunteering has many benefits. It helps the community and those in need. It also benefits the volunteer. People who volunteer report feeling happier and more satisfied with their lives. Volunteering helps you develop new skills and make new friends. Young people who volunteer often find it easier to get jobs later because employers value community service. Even a few hours a month can make a real difference.",
         "questions":[
             {"statement":"Volunteering involves being paid for your work.","answer":"false","explanation":"The text says volunteering means giving your time without being paid."},
             {"statement":"People who volunteer often feel happier.","answer":"true","explanation":"The text says people who volunteer report feeling happier. ✅"},
             {"statement":"Volunteering can help young people find jobs.","answer":"true","explanation":"The text says employers value community service when hiring. ✅"},
             {"statement":"You need to volunteer every day to make a difference.","answer":"false","explanation":"The text says even a few hours a month can make a real difference."},
             {"statement":"Volunteering only benefits the people being helped.","answer":"false","explanation":"The text says it also benefits the volunteer."},
         ]},
    ],
    "intermediate":[
        {"title":"Artificial Intelligence in Education","text":"Artificial intelligence is rapidly transforming the field of education. AI-powered tools can now personalise learning for individual students, identifying their strengths and weaknesses and adjusting content accordingly. Virtual tutors are available 24 hours a day, providing instant feedback on exercises and essays. However, educators warn that AI should complement rather than replace human teachers. The emotional connection between teachers and students and the development of social skills are areas where human interaction remains irreplaceable.",
         "questions":[
             {"statement":"AI tools can identify individual students' strengths and weaknesses.","answer":"true","explanation":"The text says AI can personalise learning by identifying their strengths and weaknesses. ✅"},
             {"statement":"Virtual tutors are only available during school hours.","answer":"false","explanation":"Virtual tutors are available 24 hours a day, not just school hours."},
             {"statement":"Educators believe AI should completely replace human teachers.","answer":"false","explanation":"Educators warn AI should complement rather than REPLACE human teachers."},
             {"statement":"Human teachers are better at developing social skills.","answer":"true","explanation":"Social skill development is an area where human interaction remains irreplaceable. ✅"},
             {"statement":"Most schools worldwide have already adopted AI tools.","answer":"not given","explanation":"No statistics about adoption rates are mentioned."},
         ]},
        {"title":"The Psychology of Habits","text":"Habits are automatic behaviours that we perform with little conscious thought. According to researchers, habits are formed through a three-step loop: a cue that triggers the behaviour, the routine itself, and a reward that reinforces it. This is why habits are so powerful — they become wired into our neurology over time. Breaking bad habits requires identifying the cue and replacing the routine with a healthier alternative while maintaining the same reward.",
         "questions":[
             {"statement":"Habits require a lot of conscious thought.","answer":"false","explanation":"The text says habits are performed with LITTLE conscious thought."},
             {"statement":"The habit loop consists of three steps.","answer":"true","explanation":"The text mentions a three-step loop: cue, routine, and reward. ✅"},
             {"statement":"To break a bad habit, you should eliminate the reward.","answer":"false","explanation":"The text says maintain the same REWARD but replace the ROUTINE."},
             {"statement":"Habits become part of our neurology over time.","answer":"true","explanation":"The text says habits become wired into our neurology over time. ✅"},
             {"statement":"It takes exactly 21 days to form a new habit.","answer":"not given","explanation":"No specific timeframe for habit formation is mentioned."},
         ]},
        {"title":"The Gig Economy","text":"The gig economy refers to a labour market characterised by short-term contracts and freelance work rather than permanent employment. Platforms such as Uber, Airbnb, and Upwork have accelerated this shift, enabling workers to offer services directly to consumers through digital marketplaces. Proponents argue that gig work offers flexibility and autonomy that traditional employment cannot provide. Critics, however, highlight the lack of job security, employee benefits, and legal protections for gig workers. The rise of the gig economy has prompted governments worldwide to reconsider labour laws designed for an era of permanent employment.",
         "questions":[
             {"statement":"Uber and Airbnb are mentioned as examples of gig economy platforms.","answer":"true","explanation":"Both are explicitly mentioned in the text. ✅"},
             {"statement":"Gig work provides more job security than traditional employment.","answer":"false","explanation":"Critics highlight the lack of job security for gig workers."},
             {"statement":"Supporters of the gig economy value its flexibility.","answer":"true","explanation":"The text says proponents argue gig work offers flexibility and autonomy. ✅"},
             {"statement":"All countries have already updated their labour laws for the gig economy.","answer":"false","explanation":"The text says governments have been prompted to reconsider laws, not that they have already done so."},
             {"statement":"The gig economy is more common in developing countries.","answer":"not given","explanation":"No comparison between developed and developing countries is made."},
         ]},
        {"title":"Memory and Learning","text":"Understanding how memory works can significantly improve the way we learn. Cognitive psychologists distinguish between short-term memory, which holds a limited amount of information for a brief period, and long-term memory, where information can be stored indefinitely. The process of moving information from short-term to long-term memory is called consolidation. Research shows that spaced repetition — reviewing information at increasing intervals — is far more effective for long-term retention than cramming. Sleep also plays a critical role, as memories are consolidated during slow-wave sleep cycles.",
         "questions":[
             {"statement":"Short-term memory can hold information for a long time.","answer":"false","explanation":"Short-term memory holds a limited amount of information for a BRIEF period."},
             {"statement":"Moving information from short-term to long-term memory is called consolidation.","answer":"true","explanation":"The text explicitly defines consolidation this way. ✅"},
             {"statement":"Cramming is more effective than spaced repetition for long-term retention.","answer":"false","explanation":"The text says spaced repetition is far more effective than cramming."},
             {"statement":"Sleep helps consolidate memories.","answer":"true","explanation":"The text says memories are consolidated during sleep cycles. ✅"},
             {"statement":"Long-term memory has a limited storage capacity.","answer":"false","explanation":"The text says long-term memory can store information indefinitely."},
         ]},
        {"title":"Renewable Energy","text":"The transition from fossil fuels to renewable energy sources represents one of the most significant challenges of the twenty-first century. Solar and wind power have become increasingly cost-competitive with coal and natural gas, driven by technological advances and economies of scale. However, the intermittent nature of renewable energy — the sun does not always shine and the wind does not always blow — poses significant challenges for grid stability. Energy storage technologies, particularly battery systems, are developing rapidly to address this problem. Many governments have set ambitious targets for renewable energy as part of their commitments to reduce carbon emissions.",
         "questions":[
             {"statement":"Solar and wind power are now cost-competitive with fossil fuels.","answer":"true","explanation":"The text says they have become increasingly cost-competitive with coal and natural gas. ✅"},
             {"statement":"Renewable energy sources produce energy consistently at all times.","answer":"false","explanation":"The text says renewable energy is intermittent — the sun and wind are not always available."},
             {"statement":"Battery technology is being developed to store renewable energy.","answer":"true","explanation":"The text says energy storage technologies, particularly battery systems, are developing rapidly. ✅"},
             {"statement":"All governments have already met their renewable energy targets.","answer":"false","explanation":"The text says governments have set targets, not that they have met them."},
             {"statement":"Nuclear energy is mentioned as an alternative to fossil fuels.","answer":"not given","explanation":"Nuclear energy is not mentioned in the text."},
         ]},
        {"title":"Emotional Intelligence","text":"Emotional intelligence, often abbreviated as EQ, refers to the ability to recognise, understand, and manage one's own emotions and those of others. Psychologist Daniel Goleman popularised the concept in the 1990s, arguing that EQ was a stronger predictor of professional and personal success than cognitive intelligence alone. The components of emotional intelligence include self-awareness, self-regulation, motivation, empathy, and social skills. Research in organisational psychology suggests that leaders with high EQ tend to create more positive work environments, manage conflict more effectively, and inspire greater loyalty among their teams.",
         "questions":[
             {"statement":"EQ stands for emotional intelligence.","answer":"true","explanation":"The text says emotional intelligence is often abbreviated as EQ. ✅"},
             {"statement":"Daniel Goleman developed the concept of emotional intelligence in the 1980s.","answer":"false","explanation":"Goleman popularised the concept in the 1990s, not the 1980s."},
             {"statement":"Goleman argued that EQ was more important than cognitive intelligence for success.","answer":"true","explanation":"The text says Goleman argued EQ was a stronger predictor of success than cognitive intelligence. ✅"},
             {"statement":"Empathy is one of the components of emotional intelligence.","answer":"true","explanation":"The text lists empathy as one of the five components of EQ. ✅"},
             {"statement":"High EQ leaders always earn higher salaries.","answer":"not given","explanation":"Salary is not mentioned anywhere in the text."},
         ]},
        {"title":"Globalisation and Culture","text":"Globalisation has facilitated the unprecedented exchange of goods, ideas, and cultural practices across national borders. Critics argue that this process has led to cultural homogenisation — the gradual erosion of local traditions and languages as global brands, English-language media, and Western lifestyle standards spread worldwide. Defenders of globalisation counter that cultural exchange enriches societies, enables innovation through the mixing of ideas, and gives individuals access to a wider range of cultural products. The reality is likely somewhere between these positions: globalisation simultaneously creates new hybrid cultures and threatens the survival of indigenous ones.",
         "questions":[
             {"statement":"Globalisation has increased the exchange of goods and cultural practices.","answer":"true","explanation":"The text says globalisation has facilitated the unprecedented exchange of goods, ideas, and cultural practices. ✅"},
             {"statement":"All scholars agree that globalisation is harmful to culture.","answer":"false","explanation":"The text presents both critical and supportive views of globalisation."},
             {"statement":"Cultural homogenisation refers to the spread of diverse local cultures.","answer":"false","explanation":"Cultural homogenisation refers to the erosion of local traditions as global standards spread."},
             {"statement":"The article concludes that globalisation is purely negative.","answer":"false","explanation":"The article says the reality is likely between positive and negative positions."},
             {"statement":"The author believes indigenous cultures will definitely survive globalisation.","answer":"not given","explanation":"The author says globalisation threatens indigenous cultures but does not predict the outcome."},
         ]},
        {"title":"The Science of Happiness","text":"Positive psychology, a relatively recent branch of the discipline, focuses on the scientific study of wellbeing and the factors that enable individuals and communities to flourish. Research has consistently identified several key contributors to subjective wellbeing: meaningful relationships, a sense of purpose, engagement in activities that produce a state of flow, regular physical exercise, and gratitude practices. Interestingly, studies suggest that beyond a moderate income threshold, additional wealth has diminishing returns on happiness. This finding challenges the common assumption that financial success is the primary route to a fulfilling life.",
         "questions":[
             {"statement":"Positive psychology focuses on the study of mental illness.","answer":"false","explanation":"Positive psychology focuses on wellbeing and what enables people to flourish."},
             {"statement":"Meaningful relationships contribute to subjective wellbeing.","answer":"true","explanation":"The text lists meaningful relationships as a key contributor to wellbeing. ✅"},
             {"statement":"More money always leads to greater happiness.","answer":"false","explanation":"The text says beyond a moderate income, additional wealth has diminishing returns on happiness."},
             {"statement":"Physical exercise is mentioned as a contributor to wellbeing.","answer":"true","explanation":"The text lists regular physical exercise as a key contributor. ✅"},
             {"statement":"The research on happiness was conducted in one country only.","answer":"not given","explanation":"The text does not specify where the research was conducted."},
         ]},
        {"title":"Media Literacy","text":"In an era of information overload, media literacy — the ability to critically evaluate and interpret media messages — has become an essential skill. The proliferation of digital platforms has made it increasingly difficult to distinguish credible journalism from misinformation, propaganda, and sponsored content. Media literate individuals question the source of information, consider the perspective and potential bias of the author, and verify claims through multiple independent sources. Schools in many countries have begun incorporating media literacy into their curricula, recognising that the ability to navigate information critically is as fundamental as reading and writing.",
         "questions":[
             {"statement":"Media literacy involves critically evaluating media messages.","answer":"true","explanation":"The text defines media literacy as the ability to critically evaluate and interpret media messages. ✅"},
             {"statement":"Digital platforms have made it easier to identify misinformation.","answer":"false","explanation":"The text says digital platforms have made it increasingly difficult to distinguish credible information from misinformation."},
             {"statement":"Media literate people verify claims through multiple sources.","answer":"true","explanation":"The text says they verify claims through multiple independent sources. ✅"},
             {"statement":"All schools worldwide now teach media literacy.","answer":"false","explanation":"The text says schools in many countries have begun incorporating it — not all schools worldwide."},
             {"statement":"Media literacy is more important than mathematics in the curriculum.","answer":"not given","explanation":"No comparison with other subjects is made in the text."},
         ]},
        {"title":"Food Security","text":"Food security exists when all people have reliable access to sufficient, safe, and nutritious food. Despite significant advances in agricultural productivity, an estimated 800 million people worldwide remain chronically undernourished. The causes of food insecurity are complex and interconnected: poverty, conflict, climate change, and inefficient food distribution systems all contribute to the problem. Paradoxically, food waste represents a significant challenge in many wealthy nations, where roughly one third of all food produced is lost or discarded. Addressing food insecurity requires both technological innovation and fundamental changes in how food systems are organised and governed.",
         "questions":[
             {"statement":"Approximately 800 million people are chronically undernourished.","answer":"true","explanation":"The text states this figure directly. ✅"},
             {"statement":"Climate change is one cause of food insecurity.","answer":"true","explanation":"The text lists climate change as one of the contributing causes. ✅"},
             {"statement":"Food waste is only a problem in developing countries.","answer":"false","explanation":"The text says food waste is a significant challenge in many wealthy nations."},
             {"statement":"About one third of food produced globally is lost or discarded.","answer":"true","explanation":"The text says roughly one third of all food produced is lost or discarded. ✅"},
             {"statement":"The article proposes a specific policy solution to food insecurity.","answer":"false","explanation":"The article calls for technological innovation and systemic changes but proposes no specific policy."},
         ]},
    ],
    "advanced":[
        {"title":"The Paradox of Choice","text":"Psychologist Barry Schwartz argues that the proliferation of choice in modern society, rather than increasing human freedom and wellbeing, frequently leads to paralysis, anxiety, and dissatisfaction. When faced with an overwhelming number of options, individuals often experience decision fatigue and are more likely to second-guess their choices — a phenomenon Schwartz terms 'the tyranny of choice.' Schwartz advocates for 'satisficing' — settling for a sufficiently good option rather than exhaustively pursuing the optimal one.",
         "questions":[
             {"statement":"Schwartz argues that more choices lead to greater happiness.","answer":"false","explanation":"Schwartz argues more choices lead to paralysis, anxiety, and dissatisfaction."},
             {"statement":"Decision fatigue can cause people to doubt their choices.","answer":"true","explanation":"The text says people are more likely to second-guess their choices. ✅"},
             {"statement":"Schwartz coined the term 'the tyranny of choice'.","answer":"true","explanation":"The text says 'a phenomenon Schwartz terms the tyranny of choice.' ✅"},
             {"statement":"Satisficing means always choosing the best possible option.","answer":"false","explanation":"Satisficing means settling for a sufficiently good option — NOT the best one."},
             {"statement":"Schwartz's research was conducted over a ten-year period.","answer":"not given","explanation":"The duration of his research is not mentioned anywhere."},
         ]},
        {"title":"Neuroplasticity and the Learning Brain","text":"Contemporary neuroscience has fundamentally revised earlier assumptions about the fixed nature of the adult brain. The concept of neuroplasticity — the brain's capacity to reorganise itself by forming new neural connections throughout life — has profound implications for education. Research demonstrates that deliberate practice, particularly when it involves struggle and error correction, strengthens synaptic connections more effectively than passive review. This phenomenon, called 'desirable difficulty,' explains why effortful learning produces more durable knowledge. Furthermore, sleep is essential in consolidating learning, as the hippocampus replays newly acquired information during slow-wave sleep cycles.",
         "questions":[
             {"statement":"Earlier scientists believed the adult brain could not change.","answer":"true","explanation":"The text says neuroscience revised earlier assumptions about the fixed nature of the adult brain. ✅"},
             {"statement":"Passive review is more effective than deliberate practice.","answer":"false","explanation":"The text says deliberate practice is MORE EFFECTIVE than passive review."},
             {"statement":"Desirable difficulty refers to effortful learning that produces durable knowledge.","answer":"true","explanation":"The text defines it exactly this way. ✅"},
             {"statement":"The hippocampus is active during slow-wave sleep cycles.","answer":"true","explanation":"The text says the hippocampus replays newly acquired information during slow-wave sleep cycles. ✅"},
             {"statement":"Neuroplasticity only occurs in children under twelve.","answer":"false","explanation":"The brain forms new connections throughout life — not just in childhood."},
         ]},
        {"title":"The Ethics of Artificial Intelligence","text":"As artificial intelligence systems become increasingly integrated into critical decision-making processes — from judicial sentencing to medical diagnosis — the ethical implications demand urgent attention. Algorithmic bias, wherein AI systems perpetuate or amplify existing societal inequalities, represents one of the most pressing concerns. When training data reflects historical discrimination, the resulting models may systematically disadvantage marginalised groups. Proponents of AI governance argue that transparent, accountable systems with robust human oversight are essential to ensuring that technological progress serves rather than undermines democratic values.",
         "questions":[
             {"statement":"AI systems are currently used in judicial sentencing and medical diagnosis.","answer":"true","explanation":"The text mentions both judicial sentencing and medical diagnosis as areas of AI integration. ✅"},
             {"statement":"Algorithmic bias occurs when AI systems are programmed intentionally to discriminate.","answer":"false","explanation":"The text says bias occurs when training data reflects historical discrimination — not intentional programming."},
             {"statement":"All AI researchers support the implementation of governance frameworks.","answer":"not given","explanation":"The text mentions proponents of AI governance but does not say all researchers support it."},
             {"statement":"Marginalised groups may be disadvantaged by biased AI systems.","answer":"true","explanation":"The text says models may systematically disadvantage marginalised groups. ✅"},
             {"statement":"The article concludes that AI development should be halted.","answer":"false","explanation":"The article advocates for transparent and accountable systems, not halting development."},
         ]},
        {"title":"The Economics of Attention","text":"In the digital age, attention has become one of the most valuable and contested resources. Technology companies have engineered platforms specifically designed to maximise engagement, deploying sophisticated psychological mechanisms — variable reward schedules, social validation loops, and algorithmically curated content — to capture and hold user attention for as long as possible. Critics argue that this attention economy externalises significant social costs, including diminished capacity for deep work, increased rates of anxiety and depression among adolescents, and the erosion of civic discourse through the prioritisation of emotionally provocative content over substantive information.",
         "questions":[
             {"statement":"Technology companies deliberately design platforms to maximise user engagement.","answer":"true","explanation":"The text says platforms are specifically designed to maximise engagement. ✅"},
             {"statement":"Variable reward schedules are a psychological mechanism used by social media platforms.","answer":"true","explanation":"The text explicitly lists variable reward schedules as one of the mechanisms used. ✅"},
             {"statement":"The attention economy has no negative social consequences.","answer":"false","explanation":"The text lists several negative consequences including anxiety, depression, and erosion of civic discourse."},
             {"statement":"The article argues that social media should be banned for users under eighteen.","answer":"not given","explanation":"No age restriction recommendation is made in the text."},
             {"statement":"Emotionally provocative content is prioritised over substantive information on many platforms.","answer":"true","explanation":"The text says civic discourse erodes through the prioritisation of emotionally provocative content. ✅"},
         ]},
        {"title":"Post-Colonial Identity and Literature","text":"Post-colonial literature occupies a unique space in the global literary canon, grappling with the enduring psychological and cultural consequences of colonial rule. Writers such as Chinua Achebe and Frantz Fanon examined how colonialism not only extracted material wealth but systematically dismantled indigenous knowledge systems, languages, and self-conception. The concept of hybridity — the blending of coloniser and colonised cultures to produce something new and contested — has become central to post-colonial theory. Contemporary scholars debate whether cultural hybridity represents creative synthesis or the continued subordination of indigenous identities to dominant Western frameworks.",
         "questions":[
             {"statement":"Chinua Achebe and Frantz Fanon are mentioned as post-colonial writers.","answer":"true","explanation":"Both writers are explicitly named in the text. ✅"},
             {"statement":"Colonialism only affected the economic wealth of colonised nations.","answer":"false","explanation":"The text says colonialism also dismantled knowledge systems, languages, and self-conception."},
             {"statement":"Hybridity refers to the complete replacement of indigenous culture by colonial culture.","answer":"false","explanation":"Hybridity is described as the blending of both cultures to produce something new."},
             {"statement":"All post-colonial scholars view cultural hybridity positively.","answer":"false","explanation":"The text says scholars debate whether it represents creative synthesis OR continued subordination."},
             {"statement":"Post-colonial literature is more popular than Western literature globally.","answer":"not given","explanation":"No comparison of popularity between literary traditions is made in the text."},
         ]},
        {"title":"The Philosophy of Free Will","text":"The debate between determinism and free will represents one of philosophy's most enduring controversies. Hard determinists contend that every human action is the inevitable product of prior causes — neurological, environmental, and genetic — leaving no genuine space for autonomous choice. Compatibilists, by contrast, argue that free will and determinism are not mutually exclusive: meaningful freedom consists not in the absence of causal influences but in acting in accordance with one's own desires and reasoning without external compulsion. This distinction carries profound implications for moral responsibility, criminal justice, and our understanding of human agency.",
         "questions":[
             {"statement":"Hard determinists believe humans have complete freedom of choice.","answer":"false","explanation":"Hard determinists believe every action is the inevitable product of prior causes, leaving no space for autonomous choice."},
             {"statement":"Compatibilists argue that free will and determinism can coexist.","answer":"true","explanation":"The text says compatibilists argue free will and determinism are not mutually exclusive. ✅"},
             {"statement":"The debate about free will has implications for criminal justice.","answer":"true","explanation":"The text says this debate has profound implications for moral responsibility and criminal justice. ✅"},
             {"statement":"The article concludes that compatibilism is the correct position.","answer":"not given","explanation":"The article presents both positions without reaching a conclusion."},
             {"statement":"According to compatibilists, freedom means acting without any causal influences.","answer":"false","explanation":"Compatibilists say freedom means acting in accordance with one's desires without external compulsion — not without causal influences."},
         ]},
        {"title":"Urbanisation and Mental Health","text":"The rapid urbanisation of the twenty-first century has generated significant scholarly interest in the relationship between urban environments and psychological wellbeing. Research consistently demonstrates that urban residents exhibit higher rates of anxiety, depression, and schizophrenia compared to rural populations, a disparity attributed to factors including chronic noise exposure, social anonymity, reduced access to natural environments, and the psychological burden of inequality made visible through spatial proximity. However, cities also offer concentrations of cultural resources, social diversity, and economic opportunity that can serve as protective factors against isolation and stagnation.",
         "questions":[
             {"statement":"Urban residents have higher rates of anxiety and depression than rural residents.","answer":"true","explanation":"The text says research consistently demonstrates this disparity. ✅"},
             {"statement":"Noise exposure is one factor contributing to poor mental health in cities.","answer":"true","explanation":"Chronic noise exposure is explicitly listed as one of the contributing factors. ✅"},
             {"statement":"Cities offer no benefits to psychological wellbeing.","answer":"false","explanation":"The text mentions cultural resources, social diversity, and economic opportunity as protective factors."},
             {"statement":"The article recommends that people move from cities to rural areas.","answer":"not given","explanation":"No such recommendation is made in the text."},
             {"statement":"Social anonymity in cities can negatively affect mental health.","answer":"true","explanation":"Social anonymity is listed as one of the factors attributed to higher rates of mental health issues. ✅"},
         ]},
        {"title":"The Science of Climate Tipping Points","text":"Climate scientists have identified a series of potential tipping points — thresholds beyond which self-reinforcing feedback loops could drive irreversible changes in Earth's climate system. The collapse of the West Antarctic Ice Sheet, the dieback of the Amazon rainforest, and the thawing of Arctic permafrost each represent tipping elements that, once triggered, could accelerate warming independently of human emissions. Recent research suggests that some of these tipping points may be closer than previously estimated, and that crossing one may increase the likelihood of triggering others in a cascading sequence that would fundamentally alter conditions for human civilisation.",
         "questions":[
             {"statement":"Climate tipping points can trigger self-reinforcing feedback loops.","answer":"true","explanation":"The text describes tipping points as thresholds beyond which self-reinforcing feedback loops are driven. ✅"},
             {"statement":"The Amazon rainforest is mentioned as a climate tipping element.","answer":"true","explanation":"The dieback of the Amazon rainforest is explicitly listed as a tipping element. ✅"},
             {"statement":"Scientists believe all climate tipping points have already been triggered.","answer":"false","explanation":"The text says some tipping points may be closer than estimated, not that they have been triggered."},
             {"statement":"Crossing one tipping point has no effect on others.","answer":"false","explanation":"The text says crossing one may increase the likelihood of triggering others in a cascade."},
             {"statement":"Human emissions would stop after tipping points are crossed.","answer":"not given","explanation":"The text does not discuss what happens to human emissions after tipping points are crossed."},
         ]},
        {"title":"The Sociology of Inequality","text":"Contemporary sociologists distinguish between inequality of opportunity and inequality of outcome. While the former refers to differential access to education, healthcare, and social networks based on circumstances of birth, the latter describes the unequal distribution of income, wealth, and status across society. Meritocratic ideology — the belief that success reflects individual talent and effort — has been critiqued for obscuring structural barriers that systematically advantage those born into privileged circumstances. Research in social mobility consistently finds that parental socioeconomic status remains the strongest predictor of a child's future economic outcomes across most industrialised nations.",
         "questions":[
             {"statement":"Inequality of opportunity refers to unequal distribution of income and wealth.","answer":"false","explanation":"That is inequality of outcome. Inequality of opportunity refers to differential access to education, healthcare, and social networks."},
             {"statement":"Meritocratic ideology has been criticised by some sociologists.","answer":"true","explanation":"The text says meritocratic ideology has been critiqued for obscuring structural barriers. ✅"},
             {"statement":"Parental socioeconomic status is a strong predictor of children's future outcomes.","answer":"true","explanation":"The text says it remains the strongest predictor of future economic outcomes. ✅"},
             {"statement":"Social mobility is higher in industrialised nations than in developing nations.","answer":"not given","explanation":"No comparison between industrialised and developing nations on social mobility is made."},
             {"statement":"Meritocracy holds that success reflects individual talent and effort.","answer":"true","explanation":"The text defines meritocratic ideology as the belief that success reflects individual talent and effort. ✅"},
         ]},
        {"title":"Language and Thought","text":"The Sapir-Whorf hypothesis, also known as linguistic relativity, proposes that the language one speaks influences or determines the way one thinks and perceives the world. Strong versions of the hypothesis, now largely discredited, claimed that thought was impossible without language. Weaker versions, supported by contemporary cognitive research, suggest that language shapes certain aspects of cognition — studies have shown, for instance, that speakers of languages with more colour terms make finer colour distinctions, and that grammatical gender affects how speakers conceptualise inanimate objects. The relationship between language and thought remains an active and contested area of cognitive science.",
         "questions":[
             {"statement":"The Sapir-Whorf hypothesis is also called linguistic relativity.","answer":"true","explanation":"The text explicitly states this alternative name. ✅"},
             {"statement":"The strong version of the Sapir-Whorf hypothesis is widely accepted today.","answer":"false","explanation":"The text says strong versions are now largely discredited."},
             {"statement":"Speakers of languages with more colour terms make finer colour distinctions.","answer":"true","explanation":"This is explicitly stated as evidence for the weak version of the hypothesis. ✅"},
             {"statement":"The relationship between language and thought is now fully understood.","answer":"false","explanation":"The text says it remains an active and contested area of cognitive science."},
             {"statement":"The weak version of the hypothesis claims thought is impossible without language.","answer":"false","explanation":"That is the strong version. The weak version says language shapes certain aspects of cognition."},
         ]},
    ],
}

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
        user_sessions[uid]={"history":[],"mode":"chat","quiz_index":None,"puzzle_index":None,"article_index":None,"article_level":None,"tfng_question_index":None,"tfng_score":0,"writing_type":None,"ielts_task":None,"skills_level":None,"placement_index":None,"placement_score":0}
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

QUIZ_QUESTIONS=[
    {"q":"Which word is a NOUN?\n\na) Run\nb) Happy\nc) Dog\nd) Quickly","a":"c","e":"Dog is a noun — a person, place or thing.","cat":"Nouns"},
    {"q":"Correct sentence?\n\na) She go to school.\nb) She goes to school.\nc) She going.\nd) She gone.","a":"b","e":"She goes — add -es for he/she/it.","cat":"Verb Agreement"},
    {"q":"Which is an ADJECTIVE?\n\na) Jump\nb) Tiny\nc) Cat\nd) Slowly","a":"b","e":"Tiny is an adjective — describes a noun.","cat":"Adjectives"},
    {"q":"Capital letters correct?\n\na) my name is john.\nb) My name is John.\nc) my Name is john.\nd) My Name Is John.","a":"b","e":"Sentences start with capital. Names are always capitalized.","cat":"Capitalization"},
    {"q":"Correct punctuation?\n\na) Do you like pizza\nb) Do you like pizza!\nc) Do you like pizza?\nd) Do you like pizza,","a":"c","e":"Questions end with ?","cat":"Punctuation"},
    {"q":"Plural of child?\n\na) Childs\nb) Childes\nc) Children\nd) Childer","a":"c","e":"Children — irregular plural.","cat":"Plurals"},
    {"q":"Which is a VERB?\n\na) Beautiful\nb) Apple\nc) Swim\nd) Blue","a":"c","e":"Swim is a verb — an action word.","cat":"Verbs"},
    {"q":"Spelled correctly?\n\na) Freind\nb) Frend\nc) Friend\nd) Freind","a":"c","e":"Friend — I before E: fr-I-E-nd.","cat":"Spelling"},
    {"q":"I have ___ apple.\n\na) a\nb) an\nc) the\nd) some","a":"b","e":"Use an before vowel sounds.","cat":"Articles"},
    {"q":"Opposite of hot?\n\na) Warm\nb) Sunny\nc) Cold\nd) Big","a":"c","e":"Cold is the antonym of hot.","cat":"Vocabulary"},
    {"q":"Which is a PRONOUN?\n\na) Run\nb) She\nc) Big\nd) House","a":"b","e":"She is a pronoun — replaces a name.","cat":"Pronouns"},
    {"q":"What ends a statement?\n\na) Comma\nb) Colon\nc) Period\nd) Apostrophe","a":"c","e":"A period ends a statement.","cat":"Punctuation"},
    {"q":"Which is an ADVERB?\n\na) Cat\nb) Happy\nc) Quickly\nd) Jump","a":"c","e":"Quickly is an adverb — describes HOW.","cat":"Adverbs"},
    {"q":"Correct sentence?\n\na) I has a cat.\nb) I have a cat.\nc) I haves a cat.\nd) I having a cat.","a":"b","e":"I have a cat — use have with I, you, we, they.","cat":"Verb Agreement"},
    {"q":"Synonym for big?\n\na) Small\nb) Tiny\nc) Large\nd) Short","a":"c","e":"Large is a synonym for big.","cat":"Vocabulary"},
    {"q":"She ___ TV every evening.\n\na) watch\nb) watches\nc) watching\nd) watched","a":"b","e":"watches — third person singular present simple.","cat":"Verb Agreement"},
    {"q":"Which is the correct past tense of 'go'?\n\na) Goed\nb) Gone\nc) Went\nd) Going","a":"c","e":"Went is the irregular past tense of go.","cat":"Verbs"},
    {"q":"___ you ever been to London?\n\na) Did\nb) Have\nc) Has\nd) Do","a":"b","e":"Have you ever — present perfect tense.","cat":"Tenses"},
    {"q":"She is ___ than her sister.\n\na) tall\nb) more tall\nc) taller\nd) tallest","a":"c","e":"Taller — comparative adjective for short adjectives add -er.","cat":"Adjectives"},
    {"q":"Which word means the same as 'angry'?\n\na) Happy\nb) Furious\nc) Tired\nd) Bored","a":"b","e":"Furious is a synonym for angry.","cat":"Vocabulary"},
    {"q":"I ___ my homework yesterday.\n\na) do\nb) does\nc) did\nd) done","a":"c","e":"Did — simple past tense.","cat":"Tenses"},
    {"q":"Which is a CONJUNCTION?\n\na) Quickly\nb) Beautiful\nc) Because\nd) Table","a":"c","e":"Because is a conjunction — it connects two clauses.","cat":"Conjunctions"},
    {"q":"The cat sat ___ the mat.\n\na) in\nb) on\nc) at\nd) by","a":"b","e":"On — we sit on a surface.","cat":"Prepositions"},
    {"q":"Which sentence is correct?\n\na) He don't like coffee.\nb) He doesn't likes coffee.\nc) He doesn't like coffee.\nd) He not like coffee.","a":"c","e":"He doesn't like — negative with he/she/it uses doesn't.","cat":"Verb Agreement"},
    {"q":"Opposite of 'ancient'?\n\na) Old\nb) Modern\nc) Huge\nd) Narrow","a":"b","e":"Modern is the antonym of ancient.","cat":"Vocabulary"},
    {"q":"Which is spelled correctly?\n\na) Beutiful\nb) Beautiful\nc) Beautifull\nd) Beautifol","a":"b","e":"Beautiful — b-e-a-u-t-i-f-u-l.","cat":"Spelling"},
    {"q":"We ___ to the cinema last night.\n\na) go\nb) goes\nc) went\nd) gone","a":"c","e":"Went — past tense of go.","cat":"Tenses"},
    {"q":"Which word is a PREPOSITION?\n\na) Run\nb) Under\nc) Happy\nd) Slowly","a":"b","e":"Under is a preposition — shows position.","cat":"Prepositions"},
    {"q":"She has ___ umbrella.\n\na) a\nb) an\nc) the\nd) some","a":"b","e":"An — umbrella starts with a vowel sound.","cat":"Articles"},
    {"q":"Which is the superlative of 'good'?\n\na) Gooder\nb) Better\nc) Best\nd) Most good","a":"c","e":"Best — irregular superlative of good.","cat":"Adjectives"},
    {"q":"I ___ English for 3 years.\n\na) study\nb) studied\nc) have studied\nd) am studying","a":"c","e":"Have studied — present perfect for a period up to now.","cat":"Tenses"},
    {"q":"Which word does NOT belong?\n\na) Happy\nb) Sad\nc) Angry\nd) Run","a":"d","e":"Run is a verb. Happy, Sad, Angry are all adjectives.","cat":"Adjectives"},
    {"q":"___ is your name?\n\na) Who\nb) Which\nc) What\nd) Where","a":"c","e":"What is your name — asking for a name.","cat":"Questions"},
    {"q":"The plural of 'tooth' is?\n\na) Tooths\nb) Teeth\nc) Teethes\nd) Toothes","a":"b","e":"Teeth — irregular plural of tooth.","cat":"Plurals"},
    {"q":"Which sentence uses the present continuous?\n\na) She reads books.\nb) She is reading a book.\nc) She read a book.\nd) She has read a book.","a":"b","e":"Is reading — present continuous = is/am/are + verb-ing.","cat":"Tenses"},
]

PUZZLES=[
    {"q":"'She ___ to school every day.'\n\na) go\nb) goes\nc) going\nd) gone","answer":"b","e":"goes — third person singular present tense."},
    {"q":"What does BENEFICIAL mean?\n\na) Harmful\nb) Helpful\nc) Beautiful\nd) Boring","answer":"b","e":"Beneficial means helpful or having a good effect."},
    {"q":"Which word does NOT belong?\n\na) Happy\nb) Sad\nc) Angry\nd) Run","answer":"d","e":"Run is a verb. Happy, Sad, Angry are all adjectives."},
    {"q":"'There are ___ apples.'\n\na) much\nb) many\nc) a lot\nd) few of","answer":"b","e":"Many — use with countable nouns."},
    {"q":"Synonym for ENORMOUS?\n\na) Tiny\nb) Average\nc) Huge\nd) Narrow","answer":"c","e":"Huge is a synonym for enormous."},
    {"q":"Which does NOT belong?\n\na) Cat\nb) Dog\nc) Eagle\nd) Fish","answer":"c","e":"Eagle is a bird. Cat, Dog, Fish are common pets."},
    {"q":"'If I ___ rich, I would travel.'\n\na) am\nb) was\nc) were\nd) be","answer":"c","e":"Were — always used in conditional sentences."},
    {"q":"What does INEVITABLE mean?\n\na) Impossible\nb) Certain to happen\nc) Surprising\nd) Dangerous","answer":"b","e":"Inevitable means certain to happen."},
    {"q":"What does ELOQUENT mean?\n\na) Quiet\nb) Fluent and expressive\nc) Confused\nd) Angry","answer":"b","e":"Eloquent means speaking clearly and expressively."},
    {"q":"'By the time I arrived, she ___ left.'\n\na) has\nb) have\nc) had\nd) was","answer":"c","e":"Had left — past perfect tense for something that happened before another past event."},
    {"q":"Which word means 'to make better'?\n\na) Worsen\nb) Improve\nc) Ignore\nd) Delay","answer":"b","e":"Improve means to make something better."},
    {"q":"What does AMBIGUOUS mean?\n\na) Clear\nb) Having two meanings\nc) Very large\nd) Very small","answer":"b","e":"Ambiguous means having more than one possible meaning."},
    {"q":"Which is the odd one out?\n\na) Violin\nb) Guitar\nc) Piano\nd) Trumpet","answer":"d","e":"Trumpet is a wind instrument. Violin, Guitar, Piano are string instruments."},
    {"q":"'She ___ here since 2020.'\n\na) lives\nb) lived\nc) has lived\nd) is living","answer":"c","e":"Has lived — present perfect for an action that started in the past and continues now."},
    {"q":"What does CONCISE mean?\n\na) Long and detailed\nb) Brief and clear\nc) Confusing\nd) Repetitive","answer":"b","e":"Concise means expressing things briefly and clearly."},
    {"q":"Which word is a SYNONYM of 'begin'?\n\na) End\nb) Stop\nc) Start\nd) Pause","answer":"c","e":"Start is a synonym of begin."},
    {"q":"'I wish I ___ fly.'\n\na) can\nb) could\nc) will\nd) would","answer":"b","e":"Could — use could after wish for present/future wishes."},
    {"q":"What does TRANSPARENT mean?\n\na) Opaque\nb) Colorful\nc) See-through\nd) Heavy","answer":"c","e":"Transparent means you can see through it. Also means honest and open."},
    {"q":"Which is correct?\n\na) I am agree\nb) I am agreed\nc) I agree\nd) I agreeing","answer":"c","e":"I agree — agree is not used with 'am/is/are'."},
    {"q":"What does PERSEVERE mean?\n\na) Give up\nb) Continue despite difficulties\nc) Complain\nd) Celebrate","answer":"b","e":"Persevere means to keep going despite challenges."},
]

def main_reply_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("Tools"),KeyboardButton("Dictionary")],[KeyboardButton("Skills"),KeyboardButton("Talk to Safiya")],[KeyboardButton("🎁 Invite & Earn"),KeyboardButton("Complaints & Offers")]],resize_keyboard=True,input_field_placeholder="Chat with Safiya...")

def safiya_ai_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎯 Quiz",callback_data="mode_quiz"),InlineKeyboardButton("🧩 Word Puzzle",callback_data="mode_puzzle")],[InlineKeyboardButton("📋 Placement Test",callback_data="placement_start"),InlineKeyboardButton("😂 Memes",callback_data="mode_memes")],[InlineKeyboardButton("⚔️ Vocabulary Challenge",callback_data="challenge_menu"),InlineKeyboardButton("💡 Idea Generator",callback_data="idea_gen")],[InlineKeyboardButton("Close",callback_data="close_menu")]])

def skills_levels_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Beginner",callback_data="skill_level_beginner")],[InlineKeyboardButton("🔵 Elementary",callback_data="skill_level_elementary")],[InlineKeyboardButton("🟡 Pre-Intermediate",callback_data="skill_level_pre_intermediate")],[InlineKeyboardButton("🟠 Intermediate",callback_data="skill_level_intermediate")],[InlineKeyboardButton("🔴 Advanced",callback_data="skill_level_advanced")],[InlineKeyboardButton("Close",callback_data="close_menu")]])

def skills_menu_keyboard(level):
    return InlineKeyboardMarkup([[InlineKeyboardButton("📖 Reading",callback_data=f"skill_reading_{level}"),InlineKeyboardButton("✍️ Writing Check",callback_data=f"skill_writing_{level}")],[InlineKeyboardButton("Back to Levels",callback_data="skills_back")]])

def talk_levels_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Beginner",callback_data="talk_level_beginner")],[InlineKeyboardButton("🔵 Elementary",callback_data="talk_level_elementary")],[InlineKeyboardButton("🟡 Pre-Intermediate",callback_data="talk_level_pre_intermediate")],[InlineKeyboardButton("🟠 Intermediate",callback_data="talk_level_intermediate")],[InlineKeyboardButton("🔴 Advanced",callback_data="talk_level_advanced")],[InlineKeyboardButton("Close",callback_data="close_menu")]])

def challenge_levels_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Beginner",callback_data="chal_level_beginner")],[InlineKeyboardButton("🔵 Elementary",callback_data="chal_level_elementary")],[InlineKeyboardButton("🟡 Pre-Intermediate",callback_data="chal_level_pre_intermediate")],[InlineKeyboardButton("🟠 Intermediate",callback_data="chal_level_intermediate")],[InlineKeyboardButton("🔴 Advanced",callback_data="chal_level_advanced")],[InlineKeyboardButton("Back",callback_data="safiya_menu")]])

# Vocabulary questions per level for challenges
VOCAB_QUESTIONS={
    "beginner":[
        {"q":"We pick things up with our ______.\n\na) arms\nb) hands\nc) hair\nd) heads","a":"b","e":"We pick things up with our hands. ✅"},
        {"q":"I lick an ice-cream with my ______.\n\na) knee\nb) chest\nc) lips\nd) tongue","a":"d","e":"We lick with our tongue. ✅"},
        {"q":"To eat something I put it in my ______.\n\na) mouth\nb) elbow\nc) nose\nd) neck","a":"a","e":"We put food in our mouth. ✅"},
        {"q":"We comb and brush our ______.\n\na) fingers\nb) shoulder\nc) hair\nd) sole","a":"c","e":"We comb and brush our hair. ✅"},
        {"q":"I brush my ______ regularly, especially after eating.\n\na) waist\nb) lips\nc) teeth\nd) thumb","a":"c","e":"We brush our teeth regularly. ✅"},
        {"q":"I sometimes go to school ______ bus.\n\na) in\nb) at\nc) to\nd) by","a":"d","e":"We travel by bus, by car, by train. ✅"},
        {"q":"I watch ______ while I am sitting on the sofa.\n\na) television\nb) picture\nc) radio\nd) tape","a":"a","e":"We watch television. ✅"},
        {"q":"I sometimes listen to the ______.\n\na) television\nb) radio\nc) type\nd) film","a":"b","e":"We listen to the radio. ✅"},
        {"q":"We get wet when it ______.\n\na) freezes\nb) blows\nc) shines\nd) rains","a":"d","e":"We get wet when it rains. ✅"},
        {"q":"When it is very cold, everything ______.\n\na) rains\nb) freezes\nc) blows\nd) snows","a":"b","e":"When it is very cold, everything freezes. ✅"},
    ],
    "elementary":[
        {"q":"Could you ______ me the way to the town hall?\n\na) let\nb) put\nc) talk\nd) tell","a":"d","e":"Tell me the way — tell is used for directions. ✅"},
        {"q":"There are eleven players in a football ______.\n\na) game\nb) pitch\nc) team\nd) group","a":"c","e":"Eleven players make a football team. ✅"},
        {"q":"My car won't start. Could you give me a ______ to town?\n\na) bus\nb) car\nc) hand\nd) lift","a":"d","e":"Give me a lift means a ride in a car. ✅"},
        {"q":"The mechanic hopes to ______ our car by this evening.\n\na) make\nb) renew\nc) repair\nd) wander","a":"c","e":"Mechanics repair cars. ✅"},
        {"q":"Can you ______ a photo of me in front of this building?\n\na) check\nb) make\nc) paint\nd) take","a":"d","e":"We take a photo. ✅"},
        {"q":"The plane ______ late because of the terrible weather.\n\na) blew up\nb) grew up\nc) went on\nd) took off","a":"d","e":"Planes take off — phrasal verb for departure. ✅"},
        {"q":"Which do you ______ cream or milk?\n\na) rather\nb) eat\nc) prefer\nd) wear","a":"c","e":"We prefer one thing over another. ✅"},
        {"q":"I've put on ______. I eat too many cakes.\n\na) gloves\nb) mixture\nc) waist\nd) weight","a":"d","e":"Put on weight means to become heavier. ✅"},
        {"q":"The bus was so ______ that we couldn't all get on.\n\na) crowded\nb) deep\nc) thick\nd) various","a":"a","e":"A crowded bus has too many people. ✅"},
        {"q":"Can you ______ me the time, please?\n\na) say\nb) tell\nc) speak\nd) talk","a":"b","e":"Tell me the time — we tell the time. ✅"},
    ],
    "pre_intermediate":[
        {"q":"My friend ______ his exams. He is sad.\n\na) stayed\nb) passed\nc) won\nd) failed","a":"d","e":"Failed his exams means he did not pass. ✅"},
        {"q":"When did you ______ smoking?\n\na) cut off\nb) give up\nc) make up\nd) throw away","a":"b","e":"Give up smoking means to stop smoking. ✅"},
        {"q":"We had to ______ the match because of the bad weather.\n\na) call back\nb) call off\nc) think over\nd) find out","a":"b","e":"Call off means to cancel. ✅"},
        {"q":"I'd like to ______ this cheque, please.\n\na) cash\nb) change\nc) pay for\nd) spend","a":"a","e":"Cash a cheque means to exchange it for money. ✅"},
        {"q":"Take your overcoat with you ______ it gets cold.\n\na) although\nb) in case\nc) unless\nd) until","a":"b","e":"In case means as a precaution. ✅"},
        {"q":"Thanks very much! I'm very ______ for your help.\n\na) generous\nb) grateful\nc) full\nd) sorry","a":"b","e":"Grateful means thankful. ✅"},
        {"q":"You mustn't be angry with her. It wasn't her ______ that she was late.\n\na) blame\nb) error\nc) mistake\nd) fault","a":"d","e":"It wasn't her fault — fault means responsibility. ✅"},
        {"q":"Don't ______ my speech when I am talking.\n\na) cut\nb) interrupt\nc) divide\nd) separate","a":"b","e":"Interrupt means to break into someone's speech. ✅"},
        {"q":"Anyone who gets free rides in other people's cars is called ______.\n\na) passenger\nb) traveller\nc) goner\nd) hitchhiker","a":"d","e":"A hitchhiker gets free rides. ✅"},
        {"q":"Most banks will ______ people money to buy a house.\n\na) lend\nb) borrow\nc) give\nd) take","a":"a","e":"Banks lend money — give temporarily. ✅"},
    ],
    "intermediate":[
        {"q":"He's not very quick on the uptake. It takes him a while to ______ new ideas.\n\na) on to a good thing\nb) take on board\nc) bullish\nd) breathing down","a":"b","e":"Take on board means to understand and accept new ideas. ✅"},
        {"q":"My boss never gives me any freedom. She's always ______ my neck.\n\na) broke the news\nb) brief\nc) breathing down\nd) back to the drawing board","a":"c","e":"Breathing down someone's neck means watching too closely. ✅"},
        {"q":"We need a name for our new brand. The best thing is to get people together and ______ a name.\n\na) brief\nb) on to a good thing\nc) broke the news\nd) brainstorm","a":"d","e":"Brainstorm means to generate ideas as a group. ✅"},
        {"q":"Whatever we do, we are going to come out badly. It's a ______ situation.\n\na) a can of worms\nb) carry the can\nc) chicken\nd) can't win","a":"d","e":"Can't win means there is no good outcome possible. ✅"},
        {"q":"I reckon we owe each other the same. Why don't we just ______?\n\na) call his bluff\nb) called it a day\nc) calls the shots\nd) call it quits","a":"d","e":"Call it quits means to agree that neither owes the other. ✅"},
        {"q":"We've been working on this for fourteen hours. Isn't it time we ______?\n\na) called it a day\nb) call it quits\nc) calls the shots\nd) chicken","a":"a","e":"Called it a day means to stop work for the day. ✅"},
        {"q":"She always likes to think things through very carefully. She likes to ______.\n\na) chicken and egg\nb) chicken\nc) chew things over\nd) call his bluff","a":"c","e":"Chew things over means to think carefully. ✅"},
        {"q":"I'm very happy with our sales prospects. I'm feeling really ______.\n\na) bullish\nb) back to the drawing board\nc) broke the news\nd) on to a good thing","a":"a","e":"Bullish means optimistic about prospects. ✅"},
        {"q":"We'll have to start again on this one. It's time to go ______.\n\na) blow-by-blow\nb) blew it\nc) black economy\nd) back to the drawing board","a":"d","e":"Back to the drawing board means start again from scratch. ✅"},
        {"q":"Production cannot keep pace with demand. We must eliminate the ______.\n\na) blow-by-blow\nb) back to the drawing board\nc) blew it\nd) bottlenecks","a":"d","e":"Bottlenecks are obstacles that slow down production. ✅"},
    ],
    "advanced":[
        {"q":"Losing the contract was ___ to swallow.\n\na) bottom line\nb) blue collar\nc) a bitter pill\nd) back to the drawing board","a":"c","e":"A bitter pill means something unpleasant that must be accepted. ✅"},
        {"q":"You really ___, didn't you? We lost the contract thanks to your incompetence.\n\na) back to the drawing board\nb) bottlenecks\nc) bottom line\nd) blew it","a":"d","e":"Blew it means completely failed or ruined something. ✅"},
        {"q":"The product sold really well in England. As they say there, it ______.\n\na) back to the drawing board\nb) bottlenecks\nc) bottom line\nd) went like a bomb","a":"d","e":"Went like a bomb means it was very successful in British English. ✅"},
        {"q":"He used to work on the factory floor. He really started as a ______ worker.\n\na) blue collar\nb) back to the drawing board\nc) bottlenecks\nd) bottom line","a":"a","e":"Blue collar refers to manual or factory workers. ✅"},
        {"q":"There are many reasons but the ______ is that it has been a big flop.\n\na) bottom line\nb) back to the drawing board\nc) bottlenecks\nd) blow-by-blow","a":"a","e":"The bottom line means the most important conclusion. ✅"},
        {"q":"Don't leave out any details. I want a full ______ account of the meeting.\n\na) blow-by-blow\nb) blew it\nc) black economy\nd) bombed","a":"a","e":"Blow-by-blow means describing every detail in sequence. ✅"},
        {"q":"At the start everybody was quiet but he told jokes to ______.\n\na) across the board\nb) break the ice\nc) broke the news\nd) back to the drawing board","a":"b","e":"Break the ice means to make people feel more relaxed. ✅"},
        {"q":"We're going to reduce budgets in every department. There will be ______ cuts.\n\na) back to the drawing board\nb) brief\nc) on to a good thing\nd) across the board","a":"d","e":"Across the board means affecting everyone equally. ✅"},
        {"q":"I've heard all about it. Sally ______ to me.\n\na) brainstorm\nb) on to a good thing\nc) back to the drawing board\nd) broke the news","a":"d","e":"Broke the news means told someone important information first. ✅"},
        {"q":"This market study shows nobody wants our product. It's ______ for us.\n\na) back to the drawing board\nb) brainstorm\nc) breathing down\nd) across the board","a":"a","e":"Back to the drawing board means start planning again from scratch. ✅"},
    ],
}

SPEAKING_QUESTIONS={
    "beginner":[
        "What is your name?",
        "How old are you?",
        "Where are you from?",
        "Do you have any brothers or sisters?",
        "What is your favourite colour?",
        "What food do you like?",
        "Do you have a pet?",
        "What time do you wake up?",
        "Do you like school?",
        "What is your favourite animal?",
        "What is the weather like today?",
        "What did you eat for breakfast?",
        "Do you like music? What kind?",
        "How do you come to school?",
        "What is your favourite sport?",
        "Do you have a mobile phone?",
        "What is your favourite subject?",
        "Who is your favourite teacher?",
        "What do you do after school?",
        "Describe your bedroom.",
    ],
    "elementary":[
        "Can you describe your daily routine?",
        "What do you usually do on weekends?",
        "Tell me about your best friend.",
        "What is your favourite subject at school and why?",
        "Describe your home.",
        "What sport or hobby do you enjoy?",
        "Tell me about a place you like to visit.",
        "What did you do last weekend?",
        "What kind of music do you like?",
        "Describe your favourite meal.",
        "What are your plans for this weekend?",
        "Tell me about a film you enjoyed.",
        "What do you like about your neighbourhood?",
        "How do you usually spend your evenings?",
        "Tell me about your family.",
        "What is your favourite season and why?",
        "Describe your school.",
        "What new skill would you like to learn?",
        "Tell me about a holiday you remember.",
        "What do you find difficult about learning English?",
    ],
    "pre_intermediate":[
        "Describe your hometown. What do you like about it?",
        "Talk about a memorable trip or holiday you have had.",
        "What are your plans for the future?",
        "Tell me about someone you admire and why.",
        "How has technology changed our lives?",
        "Describe a typical day at school or work.",
        "What are the advantages of learning English?",
        "Talk about a film or book you have enjoyed recently.",
        "How important is family in your culture?",
        "What would you do if you had one million dollars?",
        "Describe the most beautiful place you have ever visited.",
        "What are the biggest problems in your city?",
        "How do you usually deal with stress?",
        "Talk about a person who has influenced you greatly.",
        "What do you think is the most important invention?",
        "How has your life changed in the last five years?",
        "What are the advantages and disadvantages of social media?",
        "Describe your ideal job and why.",
        "What would you change about your education system?",
        "How important is it to speak a foreign language today?",
    ],
    "intermediate":[
        "Do you think social media has a positive or negative effect on society? Why?",
        "Compare city life and village life. Which do you prefer?",
        "How important is it to protect the environment? What can individuals do?",
        "Talk about a challenge you have faced and how you overcame it.",
        "Do you think gap years are beneficial for students? Why or why not?",
        "How has your country changed in the last 20 years?",
        "What qualities make a good teacher?",
        "Should university education be free? Discuss.",
        "How do you think artificial intelligence will change our lives?",
        "Is it better to work for yourself or for a company? Why?",
        "How do you think education will change in the next 20 years?",
        "Is it important to preserve traditional culture in a globalised world?",
        "What are the main causes of inequality in society?",
        "Should governments control the internet? Discuss.",
        "How does where you grow up affect who you become?",
        "Is it possible to achieve a work-life balance today?",
        "What responsibilities do wealthy countries have towards poorer ones?",
        "How important is creativity in modern education?",
        "Should animals be used in scientific research? Why or why not?",
        "What makes a city a good place to live?",
    ],
    "advanced":[
        "To what extent do you agree that globalisation has done more harm than good?",
        "Discuss the ethical implications of genetic engineering.",
        "How should governments balance economic growth with environmental protection?",
        "Critically evaluate the role of social media in modern politics.",
        "Is it possible to achieve true gender equality? Discuss the challenges.",
        "To what extent is poverty a result of individual choices rather than systemic factors?",
        "Discuss the advantages and disadvantages of a cashless society.",
        "How has the rise of artificial intelligence affected the job market?",
        "Should wealthy nations have an obligation to accept refugees? Why or why not?",
        "Evaluate the impact of colonialism on the developing world today.",
        "To what extent do media organisations have a responsibility to present balanced views?",
        "Discuss the ethical implications of mass surveillance for national security.",
        "Is democracy the most effective form of government? Discuss.",
        "How should society respond to the challenge of an ageing population?",
        "To what extent should personal freedom be limited for the collective good?",
        "Discuss the relationship between economic development and environmental sustainability.",
        "Is meritocracy a myth? Evaluate the concept critically.",
        "How has the definition of privacy changed in the digital age?",
        "To what extent is language a reflection of cultural identity?",
        "Discuss the moral obligations of scientists regarding the application of their discoveries.",
    ],
}

def tfng_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ True",callback_data="tfng_true"),InlineKeyboardButton("❌ False",callback_data="tfng_false"),InlineKeyboardButton("❓ Not Given",callback_data="tfng_not_given")]])

def placement_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("A",callback_data="pt_A"),InlineKeyboardButton("B",callback_data="pt_B"),InlineKeyboardButton("C",callback_data="pt_C"),InlineKeyboardButton("D",callback_data="pt_D")]])

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back",callback_data="safiya_menu")]])

def join_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Join Channel",url=CHANNEL_URL)],[InlineKeyboardButton("I Joined",callback_data="check_join")]])

def build_reading_msg(article,q_idx):
    qs=article["questions"]; total=len(qs); q=qs[q_idx]
    return (f"📖 *{article['title']}*\n\n{article['text']}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"❓ *Statement {q_idx+1}/{total}:*\n\n\"{q['statement']}\"\n\n"
            f"Is this True, False, or Not Given based on the text above?")

async def send_reading_question(upd_or_q,context,uid,edit=True):
    sess=get_session(uid); level=sess.get("article_level","elementary")
    art_idx=sess.get("article_index",0); q_idx=sess.get("tfng_question_index",0)
    articles=READING_ARTICLES.get(level,READING_ARTICLES["elementary"]); article=articles[art_idx]; qs=article["questions"]
    if q_idx>=len(qs):
        score=sess.get("tfng_score",0); total=len(qs); pct=int(score/total*100)
        rm=(f"🎉 *Reading complete!*\n\nYour score: {score}/{total} ({pct}%)\n\n"
            f"{'Excellent work! 🏆' if pct>=80 else 'Good effort! Keep practicing 💪' if pct>=60 else 'Keep reading and you will improve! 😊'}")
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("New Article",callback_data=f"skill_reading_{level}")],[InlineKeyboardButton("Back to Levels",callback_data="skills_back")]])
        chat_id=upd_or_q.message.chat_id if hasattr(upd_or_q,"message") else upd_or_q.effective_chat.id
        await context.bot.send_message(chat_id=chat_id,text=rm,parse_mode="Markdown",reply_markup=kb)
        sess["mode"]="chat"; return
    text=build_reading_msg(article,q_idx)
    chat_id=upd_or_q.message.chat_id if hasattr(upd_or_q,"message") else upd_or_q.effective_chat.id
    await context.bot.send_message(chat_id=chat_id,text=text,parse_mode="Markdown",reply_markup=tfng_keyboard())

def build_placement_msg(q_idx):
    q=PLACEMENT_TEST[q_idx]; total=len(PLACEMENT_TEST); opts="\n".join(q["options"])
    return f"📋 *Placement Test — Question {q_idx+1}/{total}*\n\n{q['q']}\n\n{opts}"

async def send_placement_question(upd_or_q,context,uid,edit=True):
    sess=get_session(uid); q_idx=sess.get("placement_index",0)
    if q_idx>=len(PLACEMENT_TEST):
        score=sess.get("placement_score",0); level,desc=get_placement_level(score)
        result=(f"🎓 *Placement Test Complete!*\n\nYour score: {score}/{len(PLACEMENT_TEST)}\n\nYour level: *{level}*\n\n{desc}\n\n📞 Contact us at {ADMIN_URL} to enroll!")
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("Take Again",callback_data="placement_start")],[InlineKeyboardButton("Back",callback_data="safiya_menu")]])
        if edit and hasattr(upd_or_q,"edit_message_text"): await upd_or_q.edit_message_text(result,parse_mode="Markdown",reply_markup=kb)
        else: await upd_or_q.message.reply_text(result,parse_mode="Markdown",reply_markup=kb)
        sess["mode"]="chat"; return
    text=build_placement_msg(q_idx)
    if edit and hasattr(upd_or_q,"edit_message_text"): await upd_or_q.edit_message_text(text,parse_mode="Markdown",reply_markup=placement_keyboard())
    else: await upd_or_q.message.reply_text(text,parse_mode="Markdown",reply_markup=placement_keyboard())

async def start(update,context):
    uid=update.effective_user.id; name=update.effective_user.first_name or ""
    if not await check_membership(uid,context):
        await update.message.reply_text("Welcome! Join our channel first.\n\nOnce you join, tap 'I Joined'!",reply_markup=join_keyboard()); return
    u=get_user(uid,name)
    # Handle referral
    if context.args and context.args[0].startswith("ref_"):
        referrer_id=context.args[0].replace("ref_","")
        if referrer_id!=str(uid):
            earned=register_invite(uid,referrer_id)
            if earned:
                try: await context.bot.send_message(chat_id=int(referrer_id),text="🎉 Congratulations! You invited 30 friends and earned FREE Premium! Enjoy unlimited access! 🌟")
                except: pass
            else:
                count=get_invite_count(referrer_id)
                try: await context.bot.send_message(chat_id=int(referrer_id),text=f"🎁 A new friend joined using your link! You have {count}/30 invites. Keep sharing! 😊")
                except: pass
    get_session(uid)["mode"]="chat"; is_new=u.get("messages",0)==0
    prompt=(f"New user named {name} just started. Warmly introduce yourself as Safiya, support teacher at Premier Tutoring Center. Briefly mention the buttons available."
            if is_new else f"Welcome back {name} warmly in one friendly sentence.")
    reply=ask_claude(uid,prompt)
    await update.message.reply_text(reply,reply_markup=main_reply_keyboard())

async def help_command(update,context):
    if not await require_membership(update,context): return
    await update.message.reply_text("Here's what you can do! 😊\n\nSafiya AI — quiz, word puzzle, placement test, memes\nDictionary — look up any English word\nSkills — reading & writing by level\nComplaints & Offers — reach us directly\n\nOr just chat with me anytime!",reply_markup=main_reply_keyboard())

async def score_command(update,context):
    if not await require_membership(update,context): return
    uid=update.effective_user.id
    p=get_progress(uid)
    if not p or p.get("total",0)==0:
        await update.message.reply_text("No results yet — take a quiz to get started! 😊",reply_markup=main_reply_keyboard()); return
    s,t=p["score"],p["total"]; pct=int(s/t*100)
    pts=0
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT points,challenges_won,challenges_played FROM users WHERE uid=%s",(str(uid),))
                row=cur.fetchone()
                if row: pts,cw,cp=row[0] or 0,row[1] or 0,row[2] or 0
                else: cw,cp=0,0
    except: cw,cp=0,0
    await update.message.reply_text(
        f"Your progress:\nQuiz: {s}/{t} ({pct}%)\nStreak: {p.get('streak',0)} days\n"
        f"Essays: {p.get('essays_checked',0)} | IELTS: {p.get('ielts_checks',0)}\n"
        f"Puzzles: {p.get('puzzles_solved',0)} | Articles: {p.get('articles_read',0)}\n"
        f"⚔️ Challenges: {cw} won / {cp} played | 🏆 Points: {pts}\n\nKeep it up! 💪",
        reply_markup=main_reply_keyboard())

async def send_quiz(uoq,context,uid):
    sess=get_session(uid); idx=random.randint(0,len(QUIZ_QUESTIONS)-1); sess["quiz_index"]=idx; sess["mode"]="quiz"; q=QUIZ_QUESTIONS[idx]
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("A",callback_data="quiz_a"),InlineKeyboardButton("B",callback_data="quiz_b"),InlineKeyboardButton("C",callback_data="quiz_c"),InlineKeyboardButton("D",callback_data="quiz_d")],[InlineKeyboardButton("Skip",callback_data="quiz_skip"),InlineKeyboardButton("Stop",callback_data="safiya_menu")]])
    if hasattr(uoq,"edit_message_text"): await uoq.edit_message_text(f"Quiz time! 🎯\n\n{q['q']}",reply_markup=kb)
    else: await uoq.message.reply_text(f"Quiz time! 🎯\n\n{q['q']}",reply_markup=kb)

async def send_puzzle(uoq,context,uid):
    sess=get_session(uid); idx=random.randint(0,len(PUZZLES)-1); sess["puzzle_index"]=idx; sess["mode"]="puzzle"; p=PUZZLES[idx]
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("A",callback_data="puz_a"),InlineKeyboardButton("B",callback_data="puz_b"),InlineKeyboardButton("C",callback_data="puz_c"),InlineKeyboardButton("D",callback_data="puz_d")],[InlineKeyboardButton("Skip",callback_data="puz_skip"),InlineKeyboardButton("Stop",callback_data="safiya_menu")]])
    if hasattr(uoq,"edit_message_text"): await uoq.edit_message_text(f"Word Puzzle! 🧩\n\n{p['q']}",reply_markup=kb)
    else: await uoq.message.reply_text(f"Word Puzzle! 🧩\n\n{p['q']}",reply_markup=kb)

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

    if data=="safiya_menu":
        sess["mode"]="chat"; await query.edit_message_text("What would you like to do? 😊",reply_markup=safiya_ai_keyboard())
    elif data=="close_menu":
        await query.edit_message_text("Feel free to chat or tap any button below! 😊")
    elif data=="idea_gen":
        sess["mode"]="idea_gen"
        await query.edit_message_text(
            "💡 *Idea Generator*\n\nType your IELTS Task 2 topic and I'll give you FOR and AGAINST ideas plus useful vocabulary!\n\nExample: *Social media is harmful to society*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back",callback_data="safiya_menu")]]))
    elif data=="challenge_menu":
        if not CHALLENGE_ENABLED:
            await query.edit_message_text("⚔️ Vocabulary Challenge is temporarily unavailable. Check back soon! 😊",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back",callback_data="safiya_menu")]])); return
        lb=get_leaderboard(5); recent=get_recent_challenges(3)
        active=get_active_challenge(); ongoing=get_ongoing_challenge()
        text="⚔️ *Vocabulary Challenge*\n\n"
        if lb:
            text+="🏆 *Leaderboard:*\n"
            medals=["🥇","🥈","🥉","4️⃣","5️⃣"]
            for i,u in enumerate(lb):
                wr=f"{int(u['challenges_won']/u['challenges_played']*100)}%" if u['challenges_played']>0 else "0%"
                text+=f"{medals[i]} {u['name'] or 'User'} — {u['points']}pts ({wr} win rate)\n"
            text+="\n"
        if recent:
            text+="⚔️ *Recent Battles:*\n"
            for b in recent:
                winner=b['challenger_name'] if b['challenger_score']>b['opponent_score'] else b['opponent_name']
                text+=f"• {b['challenger_name']} vs {b['opponent_name']} → {winner} won!\n"
            text+="\n"
        if active:
            text+=f"🔥 *Active challenge by {active['challenger_name']}* — Level: {active['level'].replace('_',' ').title()}\n\n"
        elif ongoing:
            text+=f"⚔️ Battle in progress: {ongoing['challenger_name']} vs {ongoing['opponent_name']}\n\n"
        kb_rows=[]
        if active:
            kb_rows.append([InlineKeyboardButton(f"⚔️ Accept {active['challenger_name']}'s Challenge!",callback_data=f"chal_accept_{active['id']}")])
        if is_premium(uid):
            kb_rows.append([InlineKeyboardButton("🔥 Start a Challenge",callback_data="chal_start")])
        else:
            kb_rows.append([InlineKeyboardButton("🌟 Premium Only — Upgrade to Challenge",callback_data="close_menu")])
        kb_rows.append([InlineKeyboardButton("Back",callback_data="safiya_menu")])
        await query.edit_message_text(text,parse_mode="Markdown",reply_markup=InlineKeyboardMarkup(kb_rows))
    elif data=="chal_start":
        await query.edit_message_text("Choose your challenge level! ⚔️",reply_markup=challenge_levels_keyboard())
    elif data.startswith("chal_level_"):
        level=data.replace("chal_level_","")
        questions=random.sample(VOCAB_QUESTIONS.get(level,[]),min(10,len(VOCAB_QUESTIONS.get(level,[]))))
        cid=create_challenge(uid,uname,level,[{"q":q["q"],"a":q["a"],"e":q["e"]} for q in questions])
        sess["challenge_id"]=cid; sess["challenge_q_idx"]=0; sess["challenge_score"]=0
        sess["challenge_questions"]=questions; sess["challenge_role"]="challenger"
        # Broadcast to all users
        import asyncio
        all_users=get_all_users(); ld=level.replace("_"," ").title()
        msg=(f"⚔️ *{uname}* has challenged everyone to a Vocabulary Battle!\n\n"
             f"Level: *{ld}*\n\nFirst to accept gets to fight! 🔥")
        for row in all_users:
            if int(row["uid"])!=uid:
                try:
                    # Skip users currently in a battle
                    u_sess=get_session(int(row["uid"]))
                    if u_sess.get("challenge_id") and u_sess.get("challenge_q_idx",0)<10:
                        continue
                    await context.bot.send_message(chat_id=int(row["uid"]),text=msg,parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ Accept Challenge!",callback_data=f"chal_accept_{cid}")]]))
                    await asyncio.sleep(0.05)
                except: pass
        # Start challenger's quiz
        q=questions[0]
        await query.edit_message_text(
            f"⚔️ Challenge started! Waiting for an opponent...\n\nMeanwhile answer your questions!\n\n*Question 1/10:*\n\n{q['q']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("A",callback_data="chal_a"),InlineKeyboardButton("B",callback_data="chal_b"),InlineKeyboardButton("C",callback_data="chal_c"),InlineKeyboardButton("D",callback_data="chal_d")]]))
        add_points(uid,1)  # +1 for challenging
    elif data.startswith("chal_accept_"):
        cid=int(data.replace("chal_accept_",""))
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM challenges WHERE id=%s",(cid,)); ch=cur.fetchone()
        if not ch:
            await query.answer("Challenge not found!",show_alert=True); return
        ch=dict(ch)
        if ch["status"]=="finished":
            await query.answer("This challenge is already finished!",show_alert=True); return
        if ch["status"]=="ongoing":
            c_name=ch["challenger_name"]; o_name=ch["opponent_name"]
            await query.edit_message_text(
                f"⚔️ Too late! The battle between *{c_name}* and *{o_name}* has already begun!\n\nWant to start your own challenge?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔥 Start My Challenge",callback_data="chal_start")],[InlineKeyboardButton("Back",callback_data="challenge_menu")]]))
            return
        if ch["challenger_id"]==str(uid):
            await query.answer("You can't accept your own challenge!",show_alert=True); return
        accept_challenge(cid,uid,uname)
        questions=json.loads(ch["questions"])
        sess["challenge_id"]=cid; sess["challenge_q_idx"]=0; sess["challenge_score"]=0
        sess["challenge_questions"]=questions; sess["challenge_role"]="opponent"
        q=questions[0]
        await query.edit_message_text(
            f"⚔️ You accepted *{ch['challenger_name']}'s* challenge!\n\nLevel: {ch['level'].replace('_',' ').title()}\n\n*Question 1/10:*\n\n{q['q']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("A",callback_data="chal_a"),InlineKeyboardButton("B",callback_data="chal_b"),InlineKeyboardButton("C",callback_data="chal_c"),InlineKeyboardButton("D",callback_data="chal_d")]]))
        try: await context.bot.send_message(chat_id=int(ch["challenger_id"]),text=f"⚔️ *{uname}* accepted your challenge! The battle has begun! Answer fast! 🔥",parse_mode="Markdown")
        except: pass
    elif data.startswith("chal_"):
        if not sess.get("challenge_id"): return
        ans={"chal_a":"a","chal_b":"b","chal_c":"c","chal_d":"d"}.get(data)
        if not ans: return
        questions=sess.get("challenge_questions",[])
        q_idx=sess.get("challenge_q_idx",0)
        if q_idx>=len(questions): return
        q=questions[q_idx]
        correct=ans==q["a"]
        if correct: sess["challenge_score"]=sess.get("challenge_score",0)+1
        sess["challenge_q_idx"]=q_idx+1
        next_idx=q_idx+1
        if next_idx>=len(questions):
            # Done — submit score
            score=sess["challenge_score"]; cid=sess["challenge_id"]
            ch=submit_challenge_score(cid,uid,score)
            ch_score=ch.get("challenger_score",-1); op_score=ch.get("opponent_score",-1)
            if ch_score>=0 and op_score>=0:
                # Both done — show results ONLY to the two fighters
                c_name=ch["challenger_name"]; o_name=ch["opponent_name"]
                if ch_score>op_score: winner=c_name; loser=o_name; w_id=ch["challenger_id"]; l_id=ch["opponent_id"]
                elif op_score>ch_score: winner=o_name; loser=c_name; w_id=ch["opponent_id"]; l_id=ch["challenger_id"]
                else: winner=None; w_id=None; l_id=None
                result=(f"🏆 *Battle Results!*\n\n⚔️ {c_name} vs {o_name}\n\n"
                        f"{c_name}: {ch_score}/10\n{o_name}: {op_score}/10\n\n")
                if winner: result+=f"🥇 *{winner} wins!*"
                else: result+="🤝 *It's a draw!*"
                kb=InlineKeyboardMarkup([[InlineKeyboardButton("New Challenge",callback_data="chal_start")],[InlineKeyboardButton("Back",callback_data="challenge_menu")]])
                # Add points
                if w_id:
                    add_points(int(w_id),10); update_challenge_stats(w_id,True)
                    add_points(int(l_id),3); update_challenge_stats(l_id,False)
                    if ch_score==10: add_points(int(ch["challenger_id"]),5)
                    if op_score==10: add_points(int(ch["opponent_id"]),5)
                # Show results ONLY to both fighters
                await query.edit_message_text(result,parse_mode="Markdown",reply_markup=kb)
                try:
                    other_id=ch["opponent_id"] if str(uid)==ch["challenger_id"] else ch["challenger_id"]
                    await context.bot.send_message(chat_id=int(other_id),text=result,parse_mode="Markdown",reply_markup=kb)
                except: pass
            else:
                await query.edit_message_text(f"✅ You answered {score}/10! Waiting for your opponent to finish... ⏳")
        else:
            next_q=questions[next_idx]
            fb="✅ Correct!" if correct else f"❌ Incorrect! Answer: {q['a'].upper()}"
            await query.edit_message_text(
                f"{fb}\n\n*Question {next_idx+1}/10:*\n\n{next_q['q']}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("A",callback_data="chal_a"),InlineKeyboardButton("B",callback_data="chal_b"),InlineKeyboardButton("C",callback_data="chal_c"),InlineKeyboardButton("D",callback_data="chal_d")]]))
    elif data=="skills_back":
        await query.edit_message_text("Choose your level! 🎯",reply_markup=skills_levels_keyboard())
    elif data=="mode_memes":
        meme=random.choice(MEMES)
        await query.edit_message_text(meme,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("😂 Another Meme",callback_data="mode_memes")],[InlineKeyboardButton("Back",callback_data="safiya_menu")]]))
    elif data=="placement_start":
        sess["placement_index"]=0; sess["placement_score"]=0; sess["mode"]="placement"
        await query.edit_message_text("📋 *Placement Test*\n\nThis test has 30 questions to find your English level.\n\n• Choose the best answer for each question\n• One correct answer per question\n• Your result shows your level and class recommendation\n\nGood luck! 🍀",parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Start ▶️",callback_data="placement_next")]]))
    elif data=="placement_next":
        q_idx=sess.get("placement_index",0)
        if q_idx>=len(PLACEMENT_TEST):
            score=sess.get("placement_score",0); level,desc=get_placement_level(score)
            result=f"🎓 Placement Test Complete!\n\nYour score: {score}/{len(PLACEMENT_TEST)}\n\nYour level: {level}\n\n{desc}\n\nContact us at {ADMIN_URL} to enroll!"
            await query.edit_message_text(result,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Take Again",callback_data="placement_start")],[InlineKeyboardButton("Back",callback_data="safiya_menu")]]))
            sess["mode"]="chat"
        else:
            q=PLACEMENT_TEST[q_idx]; opts="\n".join(q["options"])
            text=f"📋 Question {q_idx+1}/{len(PLACEMENT_TEST)}\n\n{q['q']}\n\n{opts}"
            await query.edit_message_text(text,reply_markup=placement_keyboard())
    elif data.startswith("pt_"):
        chosen=data.replace("pt_",""); q_idx=sess.get("placement_index",0)
        if sess.get("mode")!="placement":
            sess["mode"]="placement"
        q=PLACEMENT_TEST[q_idx]
        if chosen==q["answer"]: sess["placement_score"]=sess.get("placement_score",0)+1
        sess["placement_index"]=q_idx+1
        next_idx=sess["placement_index"]
        if next_idx>=len(PLACEMENT_TEST):
            score=sess.get("placement_score",0); level,desc=get_placement_level(score)
            result=f"🎓 Placement Test Complete!\n\nYour score: {score}/{len(PLACEMENT_TEST)}\n\nYour level: {level}\n\n{desc}\n\nContact us at {ADMIN_URL} to enroll!"
            await query.edit_message_text(result,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Take Again",callback_data="placement_start")],[InlineKeyboardButton("Back",callback_data="safiya_menu")]]))
            sess["mode"]="chat"
        else:
            q=PLACEMENT_TEST[next_idx]; opts="\n".join(q["options"])
            text=f"📋 Question {next_idx+1}/{len(PLACEMENT_TEST)}\n\n{q['q']}\n\n{opts}"
            await query.edit_message_text(text,reply_markup=placement_keyboard())
    elif data.startswith("skill_level_"):
        level=data.replace("skill_level_",""); sess["skills_level"]=level; ld=level.replace("_"," ").title()
        await query.edit_message_text(f"Great! You selected *{ld}* 🎯\n\nWhat would you like to practice?",parse_mode="Markdown",reply_markup=skills_menu_keyboard(level))
    elif data.startswith("skill_reading_"):
        level=data.replace("skill_reading_",""); articles=READING_ARTICLES.get(level,READING_ARTICLES["elementary"])
        idx=random.randint(0,len(articles)-1)
        sess["article_index"]=idx; sess["article_level"]=level; sess["tfng_question_index"]=0; sess["tfng_score"]=0; sess["mode"]="tfng"
        article=articles[idx]
        await query.answer()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=build_reading_msg(article,0),
            parse_mode="Markdown",
            reply_markup=tfng_keyboard())
    elif data.startswith("tfng_"):
        if sess.get("mode")!="tfng":
            await query.answer("No active reading session!",show_alert=True); return
        ua=data.replace("tfng_","").replace("_"," ")
        level=sess.get("article_level","elementary"); art_idx=sess.get("article_index",0); q_idx=sess.get("tfng_question_index",0)
        articles=READING_ARTICLES.get(level,READING_ARTICLES["elementary"]); article=articles[art_idx]; qs=article["questions"]; q=qs[q_idx]
        correct=ua==q["answer"]
        if correct: sess["tfng_score"]=sess.get("tfng_score",0)+1
        sess["tfng_question_index"]=q_idx+1
        total=len(qs); score=sess.get("tfng_score",0); next_idx=q_idx+1
        if correct: ft=f"✅ Correct!\n\n{q['explanation']}"
        else:
            ad=q["answer"].replace("_"," ").title()
            ft=f"❌ Incorrect! The answer is {ad}.\n\n{q['explanation']}"
        # Send feedback first
        await context.bot.send_message(chat_id=query.message.chat_id,text=ft)
        # Then immediately send next question with full article
        if next_idx<total:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=build_reading_msg(article,next_idx),
                parse_mode="Markdown",
                reply_markup=tfng_keyboard())
        else:
            pct=int(score/total*100)
            rm=(f"🎉 Reading complete!\n\nYour score: {score}/{total} ({pct}%)\n\n"
                f"{'Excellent work! 🏆' if pct>=80 else 'Good effort! Keep practicing 💪' if pct>=60 else 'Keep reading — you will improve! 😊'}")
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("New Article",callback_data=f"skill_reading_{level}")],[InlineKeyboardButton("Back to Levels",callback_data="skills_back")]])
            await context.bot.send_message(chat_id=query.message.chat_id,text=rm,reply_markup=kb)
            sess["mode"]="chat"
    elif data.startswith("talk_level_"):
        level=data.replace("talk_level_",""); sess["talk_level"]=level; sess["talk_q_index"]=0
        ld=level.replace("_"," ").title()
        await query.edit_message_text(
            f"Great choice! 🎤 *{ld}* level selected.\n\nI'll ask you 10 speaking questions one by one. After each answer, I'll give you feedback and move to the next question.\n\nAre you ready?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("I'm Ready! 🚀",callback_data="talk_start")],[InlineKeyboardButton("Back",callback_data="talk_menu")]]))
    elif data=="talk_menu":
        await query.edit_message_text("Choose your level for speaking practice! 🎤",reply_markup=talk_levels_keyboard())
    elif data=="talk_start":
        level=sess.get("talk_level","elementary"); sess["mode"]="speaking"; sess["talk_q_index"]=0
        all_questions=SPEAKING_QUESTIONS.get(level,[])
        # Pick 10 random questions for this session
        session_questions=random.sample(all_questions,min(10,len(all_questions)))
        sess["talk_questions"]=session_questions
        q=session_questions[0]
        await query.edit_message_text(
            f"🎤 *Question 1/10:*\n\n{q}\n\nSend me a voice message with your answer!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("End Session",callback_data="talk_end")]]))
    elif data=="talk_end":
        sess["mode"]="chat"
        await query.edit_message_text("Great session! Come back anytime to practice more. 😊")
    elif data.startswith("skill_writing_"):
        level=data.replace("skill_writing_",""); sess["skills_level"]=level; sess["mode"]="writing_ask"; ld=level.replace("_"," ").title()
        await query.edit_message_text(f"Writing Check — {ld}\n\nShould I check it lightly or professionally?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Lightly",callback_data="write_light"),InlineKeyboardButton("Professionally (IELTS)",callback_data="write_pro")],[InlineKeyboardButton("Back",callback_data="skills_back")]]))
    elif data=="mode_quiz": await send_quiz(query,context,uid)
    elif data=="mode_puzzle": await send_puzzle(query,context,uid)
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
    elif data.startswith("quiz_"):
        if sess.get("quiz_index") is None:
            await query.edit_message_text("No active quiz!",reply_markup=safiya_ai_keyboard()); return
        if data=="quiz_skip": await send_quiz(query,context,uid); return
        ans={"quiz_a":"a","quiz_b":"b","quiz_c":"c","quiz_d":"d"}.get(data)
        q=QUIZ_QUESTIONS[sess["quiz_index"]]; correct=ans==q["a"]
        update_quiz_progress(uid,uname,correct,q.get("cat",""))
        p=student_progress.get(str(uid),{}); s,t=p.get("score",0),p.get("total",0)
        result=(f"Correct! Well done 🎉\n\n{q['e']}\n\nScore: {s}/{t}" if correct else f"Not quite! The answer was {q['a'].upper()}.\n\n{q['e']}\n\nScore: {s}/{t}")
        await query.edit_message_text(result,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next Question",callback_data="mode_quiz")],[InlineKeyboardButton("Stop",callback_data="safiya_menu")]]))
        sess["quiz_index"]=None
    elif data.startswith("puz_"):
        if sess.get("puzzle_index") is None:
            await query.edit_message_text("No active puzzle!",reply_markup=safiya_ai_keyboard()); return
        if data=="puz_skip": await send_puzzle(query,context,uid); return
        ans={"puz_a":"a","puz_b":"b","puz_c":"c","puz_d":"d"}.get(data)
        p=PUZZLES[sess["puzzle_index"]]; correct=ans==p["answer"]
        if correct: inc_progress(uid,uname,"puzzles_solved")
        result=(f"Correct! 🎉\n\n{p['e']}" if correct else f"Not quite! The answer was {p['answer'].upper()}.\n\n{p['e']}")
        await query.edit_message_text(result,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next Puzzle",callback_data="mode_puzzle")],[InlineKeyboardButton("Stop",callback_data="safiya_menu")]]))
        sess["puzzle_index"]=None

async def handle_voice(update,context):
    if not await require_membership(update,context): return
    uid=update.effective_user.id; uname=update.effective_user.first_name or "Student"
    sess=get_session(uid); mode=sess.get("mode","chat")
    await context.bot.send_chat_action(update.effective_chat.id,action="typing")
    try:
        # Download and transcribe
        file=await context.bot.get_file(update.message.voice.file_id)
        file_bytes=await file.download_as_bytearray()
        import io
        f=io.BytesIO(bytes(file_bytes)); f.name="audio.ogg"
        t=openai_client.audio.transcriptions.create(model="whisper-1",file=f,language="en")
        transcript=t.text.strip()
        if not transcript:
            await update.message.reply_text("Hmm, I couldn't hear that clearly! Please try again in a quieter place 😊"); return
        inc_progress(uid,uname,"voice_messages")

        if mode=="speaking":
            # Check speaking limit
            if not is_premium(uid):
                count=get_daily_count(uid,"speaking_count")
                if count>=5:
                    await update.message.reply_text(PREMIUM_MSG); return
                inc_daily_count(uid,"speaking_count")

            level=sess.get("talk_level","elementary")
            q_idx=sess.get("talk_q_index",0)
            questions=sess.get("talk_questions",SPEAKING_QUESTIONS.get(level,[]))
            current_q=questions[q_idx] if q_idx<len(questions) else ""
            next_idx=q_idx+1
            sess["talk_q_index"]=next_idx

            SPEAK_SYS=f"""You are Safiya, a friendly English speaking coach. A student answered a speaking question.
Question asked: "{current_q}"
Student said: "{transcript}"
Level: {level}

Give warm feedback in this format:
What you said: [brief summary of their answer]
Strength: [one positive point]
Improve: [one specific suggestion]
Ideal answer: [write an ideal model answer to the question in 2-3 sentences]
Score: [X/10]

Be encouraging and specific. Keep it concise."""
            feedback=ask_claude(uid,f'Question: "{current_q}"\nStudent answer: "{transcript}"',system=SPEAK_SYS,max_tokens=350)

            if next_idx>=10 or next_idx>=len(questions):
                # Session complete
                await update.message.reply_text(
                    f"{feedback}\n\n🎉 *Amazing! You completed all 10 questions!*\n\nYour speaking is improving with every practice. Take a rest and come back tomorrow for another session! 😊",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Practice Again",callback_data=f"talk_level_{level}")],[InlineKeyboardButton("Main Menu",callback_data="close_menu")]]))
                sess["mode"]="chat"
            else:
                next_q=questions[next_idx]
                await update.message.reply_text(
                    f"{feedback}\n\n━━━━━━━━━━━━━━━━━━━━\n🎤 *Question {next_idx+1}/10:*\n\n{next_q}\n\nSend me your voice answer!",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("End Session",callback_data="talk_end")]]))
        else:
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

    if text=="Tools":
        if not await require_membership(update,context): return
        await update.message.reply_text("What would you like to do? 😊",reply_markup=safiya_ai_keyboard()); return
    if text=="Dictionary":
        if not await require_membership(update,context): return
        sess["mode"]="dictionary"
        await update.message.reply_text("Type any English word and I'll look it up! 📖",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel",callback_data="close_menu")]])); return
    if text=="Skills":
        if not await require_membership(update,context): return
        await update.message.reply_text("Choose your level! 🎯",reply_markup=skills_levels_keyboard()); return
    if text=="Talk to Safiya":
        if not await require_membership(update,context): return
        await update.message.reply_text("Choose your speaking level! 🎤",reply_markup=talk_levels_keyboard()); return
    if text=="🎁 Invite & Earn":
        if not await require_membership(update,context): return
        bot_username=(await context.bot.get_me()).username
        invite_link=f"https://t.me/{bot_username}?start=ref_{uid}"
        count=get_invite_count(uid)
        remaining=max(0,30-count)
        premium="🌟 You already have Premium!" if is_premium(uid) else f"Invite {remaining} more friends to earn FREE Premium!"
        await update.message.reply_text(
            f"🎁 *Invite & Earn FREE Premium!*\n\n"
            f"Invite 30 friends → get 1 month Premium FREE!\n\n"
            f"Your progress: {count}/30 friends invited 🔥\n\n"
            f"{premium}\n\n"
            f"Your personal link:\n{invite_link}\n\n"
            f"Share this link with your friends. When they join using your link it counts as 1 invite!",
            parse_mode="Markdown"); return
    if text=="Complaints & Offers":
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
        await update.message.reply_text(reply,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("New Topic 💡",callback_data="idea_gen")],[InlineKeyboardButton("Back to Tools",callback_data="safiya_menu")]]))
        return

    if mode=="writing":
        if len(text)<30:
            await update.message.reply_text("Please send a longer text to analyze! 😊"); return
        # Check writing limit
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

async def quiz_command(u,c):
    if not await require_membership(u,c): return
    get_session(u.effective_user.id)["mode"]="quiz"; await send_quiz(u,c,u.effective_user.id)

async def puzzle_command(u,c):
    if not await require_membership(u,c): return
    get_session(u.effective_user.id)["mode"]="puzzle"; await send_puzzle(u,c,u.effective_user.id)

ADMIN_ID=960055324
CHALLENGE_ENABLED=True

async def togglechallenge_command(update,context):
    global CHALLENGE_ENABLED
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("You are not authorized."); return
    CHALLENGE_ENABLED=not CHALLENGE_ENABLED
    status="✅ Enabled" if CHALLENGE_ENABLED else "❌ Disabled"
    await update.message.reply_text(f"Vocabulary Challenge is now: {status}")

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
            cur.execute("SELECT COALESCE(SUM(articles_read),0) FROM progress"); articles=cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(puzzles_solved),0) FROM progress"); puzzles=cur.fetchone()[0]
    await update.message.reply_text(
        f"📊 Bot Statistics\n\n"
        f"👥 Total users: {total}\n"
        f"🆕 New today: {new_today}\n"
        f"✍️ Essays checked: {essays}\n"
        f"📋 IELTS checks: {ielts}\n"
        f"🎯 Quiz questions: {quizzes}\n"
        f"🎤 Voice messages: {voice}\n"
        f"📖 Articles read: {articles}\n"
        f"🧩 Puzzles solved: {puzzles}"
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
            # Skip users currently in a battle
            u_sess=get_session(int(row["uid"]))
            if u_sess.get("challenge_id") and u_sess.get("challenge_q_idx",0)<10:
                continue
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
    app.add_handler(CommandHandler("quiz",quiz_command))
    app.add_handler(CommandHandler("puzzle",puzzle_command))
    app.add_handler(CommandHandler("score",score_command))
    app.add_handler(CommandHandler("stats",stats_command))
    app.add_handler(CommandHandler("broadcast",broadcast_command))
    app.add_handler(CommandHandler("togglechallenge",togglechallenge_command))
    app.add_handler(CommandHandler("addpremium",addpremium_command))
    app.add_handler(CommandHandler("removepremium",removepremium_command))
    app.add_handler(CommandHandler("premiumlist",premiumlist_command))
    app.add_handler(CommandHandler("myid",myid_command))
    app.add_handler(CommandHandler("mypremium",mypremium_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.VOICE,handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_message))
    print("Safiya is running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main()
