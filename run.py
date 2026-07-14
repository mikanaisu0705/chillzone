import os 
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View
from flask import Flask, render_template_string, request, redirect, url_for
import threading
import requests
import json
import random
import asyncio
import time

# ==========================================
# ⚙️ 設定エリア
# ==========================================
TOKEN = os.environ.get('DISCORD_TOKEN', '')
CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')

GUILD_ID = 1526575335460573315  
ROLE_ID = 1526589486207733770   
CLIENT_ID = '1526464758927200326' 
REDIRECT_URI = 'https://chillzone-5oxh.onrender.com/callback'

# ==========================================
# 💾 データ保存用システム（JSON）
# ==========================================
DATA_FILE = "user_stats.json"

def load_stats():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_stats(stats):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=4, ensure_ascii=False)

def calculate_level(total_minutes):
    level = 1
    needed = 10
    left_minutes = total_minutes
    while left_minutes >= needed:
        left_minutes -= needed
        level += 1
        needed = level * 10
    return level, needed - left_minutes

# ==========================================
# 🤖 Discord Bot 側の設定
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
bot = commands.Bot(command_prefix="/", intents=intents)

vc_start_times = {}

class VerificationView(View):
    def __init__(self):
        super().__init__(timeout=None)
        oauth_url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={CLIENT_ID}"
            f"&redirect_uri=https%3A%2F%2Fchillzone-5oxh.onrender.com%2Fcallback"
            f"&response_type=code"
            f"&scope=identify%20guilds.join"
        )
        btn = Button(label="アカウント認証を始める", style=discord.ButtonStyle.link, url=oauth_url)
        self.add_item(btn)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンドを {len(synced)} 個同期しました。")
    except Exception as e:
        print(f"同期エラー: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    user_id = str(member.id)
    if before.channel is None and after.channel is not None:
        vc_start_times[user_id] = time.time()
    elif before.channel is not None and after.channel is None:
        start_time = vc_start_times.pop(user_id, None)
        if start_time:
            duration = time.time() - start_time
            minutes_earned = round(duration / 60, 1)
            if minutes_earned > 0:
                stats = load_stats()
                if user_id not in stats:
                    stats[user_id] = {"username": member.name, "total_minutes": 0.0, "level": 1}
                stats[user_id]["total_minutes"] = round(stats[user_id]["total_minutes"] + minutes_earned, 1)
                stats[user_id]["username"] = member.name
                new_level, _ = calculate_level(int(stats[user_id]["total_minutes"]))
                stats[user_id]["level"] = new_level
                save_stats(stats)
                print(f"【記録】{member.name} が {minutes_earned} 分作業しました。")

@bot.tree.command(name="setup_verify", description="認証パネルを設置します")
@app_commands.checks.has_permissions(administrator=True)
async def setup_verify(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔒 𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇𝖾 . 認証パネル",
        description="下のボタンを押して、Webサイトから認証を完了してください。\n認証が成功すると、自動的にロールが付与されます。",
        color=0xff9966
    )
    await interaction.response.send_message(embed=embed, view=VerificationView())

@bot.tree.command(name="status", description="自分の作業時間とレベルを確認します")
async def status(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    stats = load_stats()
    if user_id not in stats:
        stats[user_id] = {"username": interaction.user.name, "total_minutes": 0.0, "level": 1}
    user_data = stats[user_id]
    total_min = user_data["total_minutes"]
    current_level, next_remain = calculate_level(int(total_min))
    embed = discord.Embed(title=f"📊 {interaction.user.name} さんの作業データ", color=0xe8a7a1)
    embed.add_field(name="👑 現在のレベル", value=f"**Lv. {current_level}**", inline=False)
    embed.add_field(name="⏱️ 合計作業時間", value=f"{total_min} 分", inline=True)
    embed.add_field(name="✨ 次のLvまであと", value=f"{round(next_remain, 1)} 分", inline=True)
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ranking", description="サーバー内の作業時間ランキングTOP10を表示します")
async def ranking(interaction: discord.Interaction):
    stats = load_stats()
    if not stats:
        await interaction.response.send_message("まだ誰の作業時間も記録されていません！")
        return
    sorted_stats = sorted(stats.items(), key=lambda x: x[1]["total_minutes"], reverse=True)[:10]
    embed = discord.Embed(title="🏆 𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇𝖾 . 作業時間ランキング", color=0xe8a7a1)
    ranking_text = ""
    medal = ["🥇", "🥈", "🥉"]
    for i, (uid, data) in enumerate(sorted_stats):
        rank_icon = medal[i] if i < 3 else f"`#{i+1}`"
        ranking_text += f"{rank_icon} **{data['username']}** - Lv.{data.get('level', 1)} ({data['total_minutes']}分)\n"
    embed.description = ranking_text
    await interaction.response.send_message(embed=embed)

# ==========================================
# 🌐 Flask Webサイト 側の設定
# ==========================================
app = Flask(__name__)
app.secret_key = 'chillzone_secret_key_look_at_me'
quiz_sessions = {}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇𝖾 . Official</title>
    <link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root { --bg-color: #f7f5f0; --main-color: #e8a7a1; --text-color: #4a4a4a; --card-bg: #ffffff; --accent-color: #ebd3c8; }
        body { font-family: 'Shippori Mincho', serif; background-color: var(--bg-color); color: var(--text-color); margin: 0; padding: 0; display: flex; flex-direction: column; align-items: center; }
        header { margin-top: 50px; text-align: center; }
        h1 { font-size: 2.8rem; margin-bottom: 5px; letter-spacing: 0.15em; color: var(--text-color); }
        .subtitle { font-size: 0.95rem; color: #888; letter-spacing: 0.05em; }
        .tab-menu { display: flex; background-color: #e2dfd8; padding: 6px; border-radius: 30px; margin: 35px 0; flex-wrap: wrap; justify-content: center; }
        .tab-btn { font-family: 'Shippori Mincho', serif; background: none; border: none; padding: 10px 24px; font-size: 1rem; cursor: pointer; color: var(--text-color); border-radius: 25px; transition: all 0.3s ease; }
        .tab-btn.active { background-color: var(--main-color); color: white; font-weight: bold; }
        .container { width: 90%; max-width: 750px; margin-bottom: 60px; }
        .tab-content { display: none; background-color: var(--card-bg); padding: 45px; border-radius: 28px; box-shadow: 0 10px 40px rgba(0,0,0,0.02); line-height: 1.9; }
        .tab-content.active { display: block; animation: fadeIn 0.4s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        h2 { font-size: 1.6rem; border-bottom: 2px solid var(--accent-color); padding-bottom: 10px; margin-top: 0; margin-bottom: 25px; color: #3a3a3a; }
        p { margin: 15px 0; font-size: 1.05rem; }
        ul { padding-left: 20px; }
        li { margin-bottom: 10px; }
        .feature-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 25px; }
        .feature-card { background-color: var(--bg-color); padding: 20px; border-radius: 18px; border: 1px solid rgba(0,0,0,0.03); }
        .feature-card strong { color: var(--main-color); font-size: 1.1rem; }
        .quiz-container { background: #fffafa; padding: 30px; border-radius: 20px; margin-top: 25px; text-align: center; border: 2px dashed var(--main-color); }
        .quiz-input { font-family: monospace; font-size: 1.4rem; padding: 8px; width: 100px; text-align: center; border-radius: 12px; border: 2px solid var(--accent-color); outline: none; margin-bottom: 15px; }
        .btn-submit { display: block; margin: 10px auto 0 auto; background-color: var(--main-color); color: white; border: none; padding: 12px 35px; border-radius: 25px; cursor: pointer; font-family: 'Shippori Mincho', serif; font-weight: bold; font-size: 1rem; }
        .code-block { background: #fdfaf6; padding: 20px; border-radius: 16px; border-left: 4px solid var(--main-color); font-family: monospace; font-size: 0.95rem; overflow-x: auto; }
    </style>
</head>
<body>
    <header>
        <h1>𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇𝖾 .</h1>
        <p class="subtitle">中高生・受験生のための、ゆるやか作業スペース</p>
    </header>
    <div class="tab-menu">
        <button class="tab-btn active" onclick="openTab('home')">ホーム</button>
        <button class="tab-btn" onclick="openTab('rules')">利用規約</button>
        <button class="tab-btn" onclick="openTab('contact')">問い合わせ</button>
        <button class="tab-btn" onclick="openTab('commands')">コマンド確認</button>
        <button class="tab-btn" id="verify-tab-nav" onclick="openTab('verify')">アカウント認証</button>
    </div>
    <div class="container">
        <div id="home" class="tab-content active">
            <h2>ようこそ、ひと息つける作業場へ。</h2>
            <p>「𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇𝖾 .」は、勉強や作業を進めるためのコミュニティです。</p>
            <div class="feature-grid">
                <div class="feature-card"><p><strong>01. 音のない集中スペース</strong></p><p style="font-size:0.95rem;">文字とタイマーだけの静かな部屋。</p></div>
                <div class="feature-card"><p><strong>02. 気配を感じる作業VC</strong></p><p style="font-size:0.95rem;">作業音がかすかに聞こえる空間です。</p></div>
            </div>
        </div>
        <div id="rules" class="tab-content">
            <h2>コミュニティのたいせつな約束</h2>
            <ul>
                <li>思いやりのある言葉遣い</li>
                <li>個人情報の保護</li>
            </ul>
        </div>
        <div id="contact" class="tab-content"><h2>お問い合わせ</h2><p>サーバー内の窓口チャンネルまでどうぞ。</p></div>
        <div id="commands" class="tab-content">
            <h2>コマンドガイド</h2>
            <div class="code-block">
                <strong>/status</strong> ➔ 自分の現在のレベルや合計時間を確認<br>
                <strong>/ranking</strong> ➔ サーバー内の作業時間ランキングTOP10を表示
            </div>
        </div>
        <div id="verify" class="tab-content">
            <h2>🔒 サーバー認証テスト</h2>
            {% if user_id and user_id != "HOME" %}
                <form action="/submit-quiz" method="POST" class="quiz-container">
                    <input type="hidden" name="user_id" value="{{ user_id }}">
                    <p style="font-size: 1.8rem; font-weight: bold; color: var(--main-color);"> {{ num1 }} + {{ num2 }} = ？ </p>
                    <input type="number" name="answer" class="quiz-input" placeholder="答え" required autofocus><br>
                    <button type="submit" class="btn-submit">送信して認証を完了する</button>
                    {% if msg %} <p style="margin-top: 20px; font-weight: bold; color: {{ msg_color }};">{{ msg }}</p> {% endif %}
                </form>
            {% else %}
                <p style="color: #888; font-weight: bold; text-align: center; margin-top: 30px;">{{ msg }}</p>
            {% endif %}
        </div>
    </div>
    <script>
        function openTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            const targetContent = document.getElementById(tabId);
            if(targetContent) targetContent.classList.add('active');
            const targetBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick').includes(tabId));
            if(targetBtn) targetBtn.classList.add('active');
        }
        {% if user_id and user_id != "HOME" %} openTab('verify'); {% endif %}
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="HOME", num1=0, num2=0, msg="Discordのボタンからアクセスすると、ここにクイズが表示されます。")

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return redirect(url_for('index'))
    data = { 
        'client_id': CLIENT_ID, 
        'client_secret': CLIENT_SECRET, 
        'grant_type': 'authorization_code', 
        'code': code, 
        'redirect_uri': REDIRECT_URI 
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    attempts = 0
    r = None
    while attempts < 3:
        try:
            r = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers, timeout=8)
            if r.status_code == 200:
                break
            elif r.status_code == 429:
                retry_after = r.json().get('retry_after', 5)
                time.sleep(retry_after)
            else:
                time.sleep(3)
        except Exception as e:
            time.sleep(3)
        attempts += 1
    if r is None or r.status_code != 200:
        return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="HOME", num1=0, num2=0, msg="⚠️ 現在Discord側で一時的なアクセス規制が発生しています。5分ほど待ってやり直してください。", msg_color="red")
    try:
        access_token = r.json().get('access_token')
    except:
        return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="HOME", num1=0, num2=0, msg="認証データの解析に失敗しました。", msg_color="red")
    if not access_token:
        return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="HOME", num1=0, num2=0, msg="トークンが空です。", msg_color="red")
    
    user_headers = {'Authorization': f'Bearer {access_token}', 'User-Agent': 'Mozilla/5.0'}
    user_r = requests.get('https://discord.com/api/users/@me', headers=user_headers).json()
    discord_id, discord_username = user_r.get('id'), user_r.get('username')
    n1, n2 = random.randint(1, 20), random.randint(1, 20)
    if discord_id:
        quiz_sessions[str(discord_id)] = { 'correct_answer': n1 + n2, 'username': discord_username, 'num1': n1, 'num2': n2 }
    return render_template_string(HTML_TEMPLATE, username=discord_username, user_id=discord_id, num1=n1, num2=n2, msg=None)

@app.route('/submit-quiz', methods=['POST'])
def submit_quiz():
    user_id = request.form.get('user_id')
    user_answer = request.form.get('answer')
    session_data = quiz_sessions.get(str(user_id))
    if not session_data:
        return render_template_string(HTML_TEMPLATE, username="エラー", user_id=user_id, num1=0, num2=0, msg="タイムアウトしました。", msg_color="red")
    try:
        if int(user_answer) == session_data['correct_answer']:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                try:
                    coro_member = guild.fetch_member(int(user_id))
                    member = asyncio.run_coroutine_threadsafe(coro_member, bot.loop).result(timeout=10)
                    if member:
                        role = guild.get_role(ROLE_ID)
                        if role:
                            asyncio.run_coroutine_threadsafe(member.add_roles(role), bot.loop).result(timeout=10)
                            quiz_sessions.pop(str(user_id), None)
                            return render_template_string(HTML_TEMPLATE, username="認証完了", user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg="✨ 正解です！認証が完了し、ロールが付与されました！", msg_color="green")
                except Exception as e:
                    return render_template_string(HTML_TEMPLATE, username="エラー", user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg=f"❌ 失敗: {e}", msg_color="red")
    except ValueError:
        pass
    return render_template_string(HTML_TEMPLATE, username=session_data['username'], user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg="❌ 答えが違います。", msg_color="red")

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    t = threading.Thread(target=run_flask)
    t.start()
    bot.run(TOKEN)
