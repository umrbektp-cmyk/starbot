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
CHANNEL_USERNAME  = "@UmrbekTeacher"
CHANNEL_URL       = "https://t.me/UmrbekTeacher"
ADMIN_URL         = "https://t.me/umrbektp"
USERS_FILE        = "users.json"
PROGRESS_FILE     = "progress.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

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

def load_json(p):
    if os.path.exists(p):
        try:
            with open(p,"r",encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def save_json(p,d):
    with open(p,"w",encoding="utf-8") as f: json.dump(d,f,indent=2,ensure_ascii=False)

user_db = load_json(USERS_FILE)
student_progress = load_json(PROGRESS_FILE)

def get_user(uid,name=""):
    k=str(uid)
    if k not in user_db:
        user_db[k]={"name":name,"joined":datetime.now().strftime("%Y-%m-%d"),"messages":0,"weak_areas":[]}
        save_json(USERS_FILE,user_db)
    return user_db[k]

def inc_progress(uid,name,field):
    k=str(uid); today=datetime.now().strftime("%Y-%m-%d")
    if k not in student_progress:
        student_progress[k]={"name":name,"score":0,"total":0,"streak":0,"last_date":"","joined":today,"voice_messages":0,"essays_checked":0,"ielts_checks":0,"puzzles_solved":0,"articles_read":0,"daily":{}}
    student_progress[k]["name"]=name
    student_progress[k][field]=student_progress[k].get(field,0)+1
    save_json(PROGRESS_FILE,student_progress)

def update_quiz_progress(uid,name,correct,cat=""):
    k=str(uid); today=datetime.now().strftime("%Y-%m-%d")
    if k not in student_progress:
        student_progress[k]={"name":name,"score":0,"total":0,"streak":0,"last_date":"","joined":today,"voice_messages":0,"essays_checked":0,"ielts_checks":0,"puzzles_solved":0,"articles_read":0,"daily":{}}
    p=student_progress[k]; p["name"]=name; p["total"]+=1
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
    if cat and not correct:
        u=user_db.get(k,{}); w=u.get("weak_areas",[])
        if cat not in w:
            w.append(cat); user_db[k]["weak_areas"]=w; save_json(USERS_FILE,user_db)
    save_json(PROGRESS_FILE,student_progress)

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
             {"statement":"Sara's mother works as a teacher.","answer":"true","explanation":"The text says 'My mother is a teacher.' ✅"},
             {"statement":"The family has a cat.","answer":"false","explanation":"They have a DOG named Max, not a cat."},
             {"statement":"Sara's brother is seven years old.","answer":"true","explanation":"The text says 'My brother is seven years old.' ✅"},
             {"statement":"Sara lives in an apartment.","answer":"false","explanation":"The text says 'We live in a house', not an apartment."},
         ]},
        {"title":"My Day","text":"I wake up at seven o'clock. I eat breakfast with my family. I go to school at eight o'clock. At school, I study English and Math. I eat lunch at twelve o'clock. After school, I play with my friends. I go to bed at nine o'clock.",
         "questions":[
             {"statement":"The person wakes up at six o'clock.","answer":"false","explanation":"They wake up at SEVEN o'clock, not six."},
             {"statement":"The person studies English at school.","answer":"true","explanation":"The text says 'I study English and Math.' ✅"},
             {"statement":"The person eats lunch alone.","answer":"not given","explanation":"The text doesn't say who they eat lunch with."},
             {"statement":"The person goes to bed at nine o'clock.","answer":"true","explanation":"The text says 'I go to bed at nine o'clock.' ✅"},
             {"statement":"The person has three subjects at school.","answer":"false","explanation":"Only two subjects are mentioned: English and Math."},
         ]},
    ],
    "elementary":[
        {"title":"A Trip to the Market","text":"Every Saturday, my mother and I go to the market. The market is very busy in the morning. We buy fresh vegetables and fruit. My mother always buys tomatoes, onions, and apples. Sometimes we buy fish too. The market has many colours and smells. I like going there because it is fun and we meet our neighbours.",
         "questions":[
             {"statement":"They go to the market every Sunday.","answer":"false","explanation":"They go every SATURDAY, not Sunday."},
             {"statement":"The mother always buys tomatoes.","answer":"true","explanation":"The text says 'My mother always buys tomatoes, onions, and apples.' ✅"},
             {"statement":"They always buy fish at the market.","answer":"false","explanation":"The text says 'Sometimes we buy fish' — not always."},
             {"statement":"The writer enjoys going to the market.","answer":"true","explanation":"The text says 'I like going there because it is fun.' ✅"},
             {"statement":"The market is open on weekdays only.","answer":"not given","explanation":"The text doesn't mention weekday opening hours."},
         ]},
        {"title":"Healthy Food","text":"Eating healthy food is very important. Fruit and vegetables give us vitamins. Vitamins help our body to stay strong. Bread and rice give us energy. Milk and cheese are good for our bones. We should drink eight glasses of water every day. Fast food is not healthy because it has too much oil and salt.",
         "questions":[
             {"statement":"Fruit and vegetables give us energy.","answer":"false","explanation":"Fruit gives VITAMINS. Bread and rice give energy."},
             {"statement":"Milk is good for our bones.","answer":"true","explanation":"The text says 'Milk and cheese are good for our bones.' ✅"},
             {"statement":"We should drink ten glasses of water daily.","answer":"false","explanation":"The text says EIGHT glasses, not ten."},
             {"statement":"Fast food contains too much oil and salt.","answer":"true","explanation":"The text says exactly this. ✅"},
             {"statement":"Vegetables are more important than fruit.","answer":"not given","explanation":"The text mentions both equally. No comparison is made!"},
         ]},
    ],
    "pre_intermediate":[
        {"title":"Social Media and Communication","text":"Social media has changed the way people communicate. Platforms like Instagram and Telegram allow people to share photos, news, and ideas instantly. Many people use social media to stay connected with friends and family who live far away. However, some experts believe that too much social media can be harmful. It can reduce face-to-face communication and affect mental health. The key is to use social media in a balanced way.",
         "questions":[
             {"statement":"Instagram and Telegram are mentioned as examples of social media.","answer":"true","explanation":"The text says 'Platforms like Instagram and Telegram.' ✅"},
             {"statement":"All experts agree that social media is harmful.","answer":"false","explanation":"SOME experts believe it can be harmful — not all."},
             {"statement":"Social media can negatively affect mental health.","answer":"true","explanation":"The text says it can 'affect mental health.' ✅"},
             {"statement":"The article recommends deleting all social media apps.","answer":"false","explanation":"The article says to use it in a 'balanced way', not to delete it."},
             {"statement":"More than one billion people use social media.","answer":"not given","explanation":"No statistics about user numbers are mentioned."},
         ]},
        {"title":"The Importance of Sleep","text":"Many people do not get enough sleep. Doctors recommend that adults sleep between seven and nine hours every night. During sleep, our brain processes information from the day and stores memories. Sleep also helps our body repair itself. People who do not sleep enough often feel tired, find it hard to concentrate, and get sick more easily. Good sleep habits include going to bed at the same time each night and avoiding screens before sleep.",
         "questions":[
             {"statement":"Doctors recommend adults sleep at least seven hours.","answer":"true","explanation":"The text says 'between seven and nine hours.' ✅"},
             {"statement":"The brain stores memories during sleep.","answer":"true","explanation":"The text says the brain 'processes information and stores memories.' ✅"},
             {"statement":"Lack of sleep only affects concentration.","answer":"false","explanation":"It causes tiredness, concentration problems, AND getting sick more easily."},
             {"statement":"You should sleep with the lights on.","answer":"false","explanation":"Good habits include avoiding screens — lights are not mentioned."},
             {"statement":"Children need more sleep than adults.","answer":"not given","explanation":"The text only talks about adults. Children are not mentioned."},
         ]},
    ],
    "intermediate":[
        {"title":"Artificial Intelligence in Education","text":"Artificial intelligence is rapidly transforming the field of education. AI-powered tools can now personalise learning for individual students, identifying their strengths and weaknesses and adjusting content accordingly. Virtual tutors are available 24 hours a day, providing instant feedback on exercises and essays. However, educators warn that AI should complement rather than replace human teachers. The emotional connection between teachers and students and the development of social skills are areas where human interaction remains irreplaceable.",
         "questions":[
             {"statement":"AI tools can identify individual students' strengths and weaknesses.","answer":"true","explanation":"The text says AI can personalise learning by 'identifying their strengths and weaknesses.' ✅"},
             {"statement":"Virtual tutors are only available during school hours.","answer":"false","explanation":"Virtual tutors are available '24 hours a day', not just school hours."},
             {"statement":"Educators believe AI should completely replace human teachers.","answer":"false","explanation":"Educators warn AI should 'complement rather than REPLACE' human teachers."},
             {"statement":"Human teachers are better at developing social skills.","answer":"true","explanation":"Social skill development is an area 'where human interaction remains irreplaceable.' ✅"},
             {"statement":"Most schools worldwide have already adopted AI tools.","answer":"not given","explanation":"No statistics about adoption rates are mentioned."},
         ]},
        {"title":"The Psychology of Habits","text":"Habits are automatic behaviours that we perform with little conscious thought. According to researchers, habits are formed through a three-step loop: a cue that triggers the behaviour, the routine itself, and a reward that reinforces it. This is why habits are so powerful — they become wired into our neurology over time. Breaking bad habits requires identifying the cue and replacing the routine with a healthier alternative while maintaining the same reward.",
         "questions":[
             {"statement":"Habits require a lot of conscious thought.","answer":"false","explanation":"The text says habits are performed 'with LITTLE conscious thought.'"},
             {"statement":"The habit loop consists of three steps.","answer":"true","explanation":"The text mentions 'a three-step loop: cue, routine, and reward.' ✅"},
             {"statement":"To break a bad habit, you should eliminate the reward.","answer":"false","explanation":"The text says maintain the same REWARD but replace the ROUTINE."},
             {"statement":"Habits become part of our neurology over time.","answer":"true","explanation":"The text says habits 'become wired into our neurology over time.' ✅"},
             {"statement":"It takes exactly 21 days to form a new habit.","answer":"not given","explanation":"No specific timeframe for habit formation is mentioned."},
         ]},
    ],
    "advanced":[
        {"title":"The Paradox of Choice","text":"Psychologist Barry Schwartz argues that the proliferation of choice in modern society, rather than increasing human freedom and wellbeing, frequently leads to paralysis, anxiety, and dissatisfaction. When faced with an overwhelming number of options, individuals often experience decision fatigue and are more likely to second-guess their choices — a phenomenon Schwartz terms 'the tyranny of choice.' Schwartz advocates for 'satisficing' — settling for a sufficiently good option rather than exhaustively pursuing the optimal one.",
         "questions":[
             {"statement":"Schwartz argues that more choices lead to greater happiness.","answer":"false","explanation":"Schwartz argues more choices lead to 'paralysis, anxiety, and dissatisfaction.'"},
             {"statement":"Decision fatigue can cause people to doubt their choices.","answer":"true","explanation":"The text says people are 'more likely to second-guess their choices.' ✅"},
             {"statement":"Schwartz coined the term 'the tyranny of choice'.","answer":"true","explanation":"The text says 'a phenomenon Schwartz terms the tyranny of choice.' ✅"},
             {"statement":"Satisficing means always choosing the best possible option.","answer":"false","explanation":"Satisficing means settling for a 'sufficiently good option' — NOT the best one."},
             {"statement":"Schwartz's research was conducted over a ten-year period.","answer":"not given","explanation":"The duration of his research is not mentioned anywhere."},
         ]},
        {"title":"Neuroplasticity and the Learning Brain","text":"Contemporary neuroscience has fundamentally revised earlier assumptions about the fixed nature of the adult brain. The concept of neuroplasticity — the brain's capacity to reorganise itself by forming new neural connections throughout life — has profound implications for education. Research demonstrates that deliberate practice, particularly when it involves struggle and error correction, strengthens synaptic connections more effectively than passive review. This phenomenon, called 'desirable difficulty,' explains why effortful learning produces more durable knowledge. Furthermore, sleep is essential in consolidating learning, as the hippocampus replays newly acquired information during slow-wave sleep cycles.",
         "questions":[
             {"statement":"Earlier scientists believed the adult brain could not change.","answer":"true","explanation":"The text says neuroscience 'revised earlier assumptions about the FIXED nature of the adult brain.' ✅"},
             {"statement":"Passive review is more effective than deliberate practice.","answer":"false","explanation":"The text says deliberate practice is 'MORE EFFECTIVE than passive review.'"},
             {"statement":"'Desirable difficulty' refers to effortful learning that produces durable knowledge.","answer":"true","explanation":"The text defines it exactly this way. ✅"},
             {"statement":"The hippocampus is active during slow-wave sleep cycles.","answer":"true","explanation":"The text says 'the hippocampus replays newly acquired information during slow-wave sleep cycles.' ✅"},
             {"statement":"Neuroplasticity only occurs in children under twelve.","answer":"false","explanation":"The brain forms new connections 'THROUGHOUT LIFE' — not just in childhood."},
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
    sess=get_session(uid); u=user_db.get(str(uid),{}); name=u.get("name","")
    sp=system or SAFIYA_SYSTEM
    if not system and name: sp+=f"\n\nUser's name: {name}"
    sess["history"].append({"role":"user","content":msg})
    history=sess["history"][-14:]
    r=claude_client.messages.create(model="claude-sonnet-4-20250514",max_tokens=max_tokens,system=sp,messages=history)
    reply=r.content[0].text; sess["history"].append({"role":"assistant","content":reply})
    k=str(uid)
    if k in user_db:
        user_db[k]["messages"]=user_db[k].get("messages",0)+1; save_json(USERS_FILE,user_db)
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
]

def main_reply_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("Safiya AI"),KeyboardButton("Dictionary")],[KeyboardButton("Skills"),KeyboardButton("Talk to Safiya")],[KeyboardButton("Complaints & Offers")]],resize_keyboard=True,input_field_placeholder="Chat with Safiya...")

def safiya_ai_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎯 Quiz",callback_data="mode_quiz"),InlineKeyboardButton("🧩 Word Puzzle",callback_data="mode_puzzle")],[InlineKeyboardButton("📋 Placement Test",callback_data="placement_start"),InlineKeyboardButton("😂 Memes",callback_data="mode_memes")],[InlineKeyboardButton("Close",callback_data="close_menu")]])

def skills_levels_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Beginner",callback_data="skill_level_beginner")],[InlineKeyboardButton("🔵 Elementary",callback_data="skill_level_elementary")],[InlineKeyboardButton("🟡 Pre-Intermediate",callback_data="skill_level_pre_intermediate")],[InlineKeyboardButton("🟠 Intermediate",callback_data="skill_level_intermediate")],[InlineKeyboardButton("🔴 Advanced",callback_data="skill_level_advanced")],[InlineKeyboardButton("Close",callback_data="close_menu")]])

def skills_menu_keyboard(level):
    return InlineKeyboardMarkup([[InlineKeyboardButton("📖 Reading",callback_data=f"skill_reading_{level}"),InlineKeyboardButton("✍️ Writing Check",callback_data=f"skill_writing_{level}")],[InlineKeyboardButton("Back to Levels",callback_data="skills_back")]])

def talk_levels_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Beginner",callback_data="talk_level_beginner")],[InlineKeyboardButton("🔵 Elementary",callback_data="talk_level_elementary")],[InlineKeyboardButton("🟡 Pre-Intermediate",callback_data="talk_level_pre_intermediate")],[InlineKeyboardButton("🟠 Intermediate",callback_data="talk_level_intermediate")],[InlineKeyboardButton("🔴 Advanced",callback_data="talk_level_advanced")],[InlineKeyboardButton("Close",callback_data="close_menu")]])

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
    u=get_user(uid,name); get_session(uid)["mode"]="chat"; is_new=u.get("messages",0)==0
    prompt=(f"New user named {name} just started. Warmly introduce yourself as Safiya, support teacher at Premier Tutoring Center. Briefly mention the four buttons: Safiya AI for learning tools, Dictionary for word lookups, Skills for level-based practice, and Complaints & Offers to reach the team."
            if is_new else f"Welcome back {name} warmly in one friendly sentence.")
    reply=ask_claude(uid,prompt)
    await update.message.reply_text(reply,reply_markup=main_reply_keyboard())

async def help_command(update,context):
    if not await require_membership(update,context): return
    await update.message.reply_text("Here's what you can do! 😊\n\nSafiya AI — quiz, word puzzle, placement test, memes\nDictionary — look up any English word\nSkills — reading & writing by level\nComplaints & Offers — reach us directly\n\nOr just chat with me anytime!",reply_markup=main_reply_keyboard())

async def score_command(update,context):
    if not await require_membership(update,context): return
    uid=str(update.effective_user.id); p=student_progress.get(uid)
    if not p or p.get("total",0)==0:
        await update.message.reply_text("No results yet — take a quiz to get started! 😊",reply_markup=main_reply_keyboard()); return
    s,t=p["score"],p["total"]; pct=int(s/t*100)
    await update.message.reply_text(f"Your progress:\nQuiz: {s}/{t} ({pct}%)\nStreak: {p.get('streak',0)} days\nEssays: {p.get('essays_checked',0)} | IELTS: {p.get('ielts_checks',0)}\nPuzzles: {p.get('puzzles_solved',0)} | Articles: {p.get('articles_read',0)}\n\nKeep it up! 💪",reply_markup=main_reply_keyboard())

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
        article=articles[idx]; text=build_reading_msg(article,0)
        await query.edit_message_text("Loading your article... 📖")
        await context.bot.send_message(chat_id=query.message.chat_id,text=text,parse_mode="Markdown",reply_markup=tfng_keyboard())
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
        if correct: ft=f"✅ *Correct!*\n\n{q['explanation']}"
        else:
            ad=q["answer"].replace("_"," ").title()
            ft=f"❌ *Incorrect!* The answer is *{ad}*.\n\n{q['explanation']}"
        nl=f"Next Question ({next_idx+1}/{total}) ➡️" if next_idx<total else "See Results 🏆"
        await query.edit_message_text(ft,parse_mode="Markdown",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(nl,callback_data="tfng_next")]]))
    elif data=="tfng_next":
        level=sess.get("article_level","elementary")
        art_idx=sess.get("article_index",0)
        q_idx=sess.get("tfng_question_index",0)
        articles=READING_ARTICLES.get(level,READING_ARTICLES["elementary"])
        article=articles[art_idx]; qs=article["questions"]
        if q_idx>=len(qs):
            score=sess.get("tfng_score",0); total=len(qs); pct=int(score/total*100)
            rm=(f"🎉 *Reading complete!*\n\nYour score: {score}/{total} ({pct}%)\n\n"
                f"{'Excellent work! 🏆' if pct>=80 else 'Good effort! Keep practicing 💪' if pct>=60 else 'Keep reading and you will improve! 😊'}")
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("New Article",callback_data=f"skill_reading_{level}")],[InlineKeyboardButton("Back to Levels",callback_data="skills_back")]])
            await context.bot.send_message(chat_id=query.message.chat_id,text=rm,parse_mode="Markdown",reply_markup=kb)
            sess["mode"]="chat"
        else:
            text=build_reading_msg(article,q_idx)
            await context.bot.send_message(chat_id=query.message.chat_id,text=text,parse_mode="Markdown",reply_markup=tfng_keyboard())
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
        questions=SPEAKING_QUESTIONS.get(level,[])
        q=questions[0]
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
            # Speaking practice mode
            level=sess.get("talk_level","elementary")
            q_idx=sess.get("talk_q_index",0)
            questions=SPEAKING_QUESTIONS.get(level,[])
            current_q=questions[q_idx] if q_idx<len(questions) else ""
            next_idx=q_idx+1
            sess["talk_q_index"]=next_idx

            # Get feedback from Claude
            SPEAK_SYS=f"""You are Safiya, a friendly English speaking coach. A student answered a speaking question.
Question asked: "{current_q}"
Student said: "{transcript}"
Level: {level}

Give SHORT warm feedback (3-4 lines max):
1. What they said (brief)
2. One strength
3. One improvement
4. Score out of 10

Be encouraging and specific. Keep it concise."""
            feedback=ask_claude(uid,f'Question: "{current_q}"\nStudent answer: "{transcript}"',system=SPEAK_SYS,max_tokens=300)

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

    if text=="Safiya AI":
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

    if mode=="writing":
        if len(text)<30:
            await update.message.reply_text("Please send a longer text to analyze! 😊"); return
        await process_writing(update,context,text,sess.get("writing_type","light"),sess.get("ielts_task","2")); return

    await context.bot.send_chat_action(update.effective_chat.id,action="typing")
    try: reply=ask_claude(uid,text)
    except Exception as e: logger.error(f"Claude error: {e}"); reply="Something went wrong — please try again! 😊"
    await update.message.reply_text(reply)

async def quiz_command(u,c):
    if not await require_membership(u,c): return
    get_session(u.effective_user.id)["mode"]="quiz"; await send_quiz(u,c,u.effective_user.id)

async def puzzle_command(u,c):
    if not await require_membership(u,c): return
    get_session(u.effective_user.id)["mode"]="puzzle"; await send_puzzle(u,c,u.effective_user.id)

ADMIN_ID=960055324

async def stats_command(update,context):
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("You are not authorized."); return
    total=len(user_db)
    today=datetime.now().strftime("%Y-%m-%d")
    new_today=sum(1 for u in user_db.values() if u.get("joined","")==today)
    essays=sum(p.get("essays_checked",0) for p in student_progress.values())
    ielts=sum(p.get("ielts_checks",0) for p in student_progress.values())
    quizzes=sum(p.get("total",0) for p in student_progress.values())
    voice=sum(p.get("voice_messages",0) for p in student_progress.values())
    articles=sum(p.get("articles_read",0) for p in student_progress.values())
    puzzles=sum(p.get("puzzles_solved",0) for p in student_progress.values())
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

async def broadcast_command(update,context):
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("You are not authorized."); return
    msg=" ".join(context.args)
    if not msg:
        await update.message.reply_text("Usage: /broadcast your message here"); return
    sent=0; failed=0
   import asyncio
    for uid in user_db.keys():
        try:
            await context.bot.send_message(chat_id=int(uid),text=msg)
            sent+=1
            await asyncio.sleep(0.05)
        except: failed+=1
    await update.message.reply_text(f"Broadcast done!\n\nSent: {sent}\nFailed: {failed}")

def main():
    print("Starting Safiya Bot...")
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",help_command))
    app.add_handler(CommandHandler("quiz",quiz_command))
    app.add_handler(CommandHandler("puzzle",puzzle_command))
    app.add_handler(CommandHandler("score",score_command))
    app.add_handler(CommandHandler("stats",stats_command))
    app.add_handler(CommandHandler("broadcast",broadcast_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.VOICE,handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_message))
    print("Safiya is running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main()
