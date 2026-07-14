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
import os  # 環境変数用に追加

# ==========================================
# ⚙️ 設定エリア（公開用に環境変数化しました！）
# ==========================================
# GitHubに直接載せないよう、Render側の設定から読み込みます
TOKEN = os.environ.get('DISCORD_TOKEN', '')
CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')

GUILD_ID = 1526575335460573315  # あなたのサーバーID
ROLE_ID = 1526589486207733770   # 付与したい「認証済」ロールのID
CLIENT_ID = '1526464758927200326'

# ⚠️ Renderなどで公開URLが決まったら、ここを「https://〇〇.onrender.com/callback」に書き換えます
REDIRECT_URI = 'http://localhost:5000/callback'

# ==========================================
# 🤖 Discord Bot 側の設定
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
bot = commands.Bot(command_prefix="/", intents=intents)

class VerificationView(View):
    def __init__(self):
        super().__init__(timeout=None)
        oauth_url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={CLIENT_ID}"
            f"&redirect_uri=http%3A%2F%2Flocalhost%3A5000%2Fcallback"
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
        print(f"{e}")

@bot.tree.command(name="setup_verify", description="認証パネルを設置します")
@app_commands.checks.has_permissions(administrator=True)
async def setup_verify(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔒 𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇𝖾 . 認証パネル",
        description="下のボタンを押して、Webサイトから認証を完了してください。\n認証が成功すると、自動的にロールが付与されます。",
        color=0xff9966
    )
    await interaction.response.send_message(embed=embed, view=VerificationView())

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
        h3 { font-size: 1.2rem; margin-top: 30px; margin-bottom: 10px; color: #5a5a5a; }
        p { margin: 15px 0; font-size: 1.05rem; }
        ul, ol { padding-left: 20px; }
        li { margin-bottom: 10px; }
        .feature-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 25px; }
        @media (max-width: 600px) { .feature-grid { grid-template-columns: 1fr; } }
        .feature-card { background-color: var(--bg-color); padding: 20px; border-radius: 18px; border: 1px solid rgba(0,0,0,0.03); }
        .feature-card strong { color: var(--main-color); font-size: 1.1rem; }
        .quiz-container { background: #fffafa; padding: 30px; border-radius: 20px; margin-top: 25px; text-align: center; border: 2px dashed var(--main-color); }
        .quiz-input { font-family: monospace; font-size: 1.4rem; padding: 8px; width: 100px; text-align: center; border-radius: 12px; border: 2px solid var(--accent-color); outline: none; margin-bottom: 15px; }
        .quiz-input:focus { border-color: var(--main-color); }
        .btn-submit { display: block; margin: 10px auto 0 auto; background-color: var(--main-color); color: white; border: none; padding: 12px 35px; border-radius: 25px; cursor: pointer; font-family: 'Shippori Mincho', serif; font-weight: bold; font-size: 1rem; transition: background 0.2s; }
        .btn-submit:hover { background-color: #df9690; }
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
            <p>「𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇𝖾 .」は、中学生、高校生、そして未来に向かってひたむきに励む受験生が、それぞれのペースで勉強や作業を進めるためのコミュニティです。</p>
            <div class="feature-grid">
                <div class="feature-card"><p><strong>01. 音のない集中スペース</strong></p><p style="font-size:0.95rem;">文字とタイマーだけの静かな部屋。自分の世界に没頭できます。</p></div>
                <div class="feature-card"><p><strong>02. 気配を感じる作業VC</strong></p><p style="font-size:0.95rem;">キーボードの打鍵音やペンを走らせる音だけがかすかに聞こえる自習室空間です。</p></div>
            </div>
        </div>

        <div id="rules" class="tab-content">
            <h2>コミュニティのたいせつな約束</h2>
            <p>みんなが安心して目標に集中できる空間を維持するためのガイドラインです。</p>
            <ul>
                <li><strong>思いやりのある言葉遣い</strong>：敬意を持った優しいコミュニケーションを。</li>
                <li><strong>個人情報の保護</strong>：本名や学校名は教え合わないようにしてください。</li>
            </ul>
        </div>

        <div id="contact" class="tab-content">
            <h2>困ったとき・お問い合わせ</h2>
            <p>不具合の報告や荒らしの報告は、サーバー内の窓口チャンネル、または運営宛てにお問い合わせください。</p>
        </div>

        <div id="commands" class="tab-content">
            <h2>自作Time Tracker コマンドガイド</h2>
            <p>ボイスチャンネルの滞在時間が自動で記録されるシステムです。</p>
            <div class="code-block"><strong>/status</strong> ➔ 自分の合計勉強時間などを確認できます。</div>
        </div>

        <div id="verify" class="tab-content">
            <h2>🔒 サーバー認証テスト</h2>
            {% if user_id %}
                <p>こんにちは、<b>{{ username }}</b> さん。スパムBot防止のため、以下の計算問題を解いてください。</p>
                <form action="/submit-quiz" method="POST" class="quiz-container">
                    <input type="hidden" name="user_id" value="{{ user_id }}">
                    <p style="font-size: 1.8rem; font-weight: bold; color: var(--main-color);"> {{ num1 }} + {{ num2 }} = ？ </p>
                    <input type="number" name="answer" class="quiz-input" placeholder="答え" required autofocus><br>
                    <button type="submit" class="btn-submit">送信して認証を完了する</button>
                    {% if msg %}
                        <p style="margin-top: 20px; font-weight: bold; color: {{ msg_color }};">{{ msg }}</p>
                    {% endif %}
                </form>
            {% else %}
                <p style="color: red; font-weight: bold; text-align: center; margin-top: 30px;">{{ msg }}</p>
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
        {% if user_id and msg != "Discordの認証パネルにあるボタンを押してアクセスしてください。" %}
            openTab('verify');
        {% endif %}
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    # user_id を "HOME" にすることで、エラーにならず「ホーム」タブが最初に開くようになります！
    return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="HOME", num1=0, num2=0, msg="Discordのボタンからアクセスすると、ここにクイズが表示されます。")

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code: return redirect(url_for('index'))
    
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    r = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
    token_json = r.json()
    access_token = token_json.get('access_token')
    
    if not access_token:
        return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="", num1=0, num2=0, msg="Discordの認証に失敗しました。もう一度お試しください。", msg_color="red")

    user_headers = {'Authorization': f'Bearer {access_token}'}
    user_r = requests.get('https://discord.com/api/users/@me', headers=user_headers)
    user_json = user_r.json()
    
    discord_id = user_json.get('id')
    discord_username = user_json.get('username')
    
    n1 = random.randint(1, 20)
    n2 = random.randint(1, 20)
    
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
                    future_member = asyncio.run_coroutine_threadsafe(coro_member, bot.loop)
                    member = future_member.result(timeout=10)

                    if member:
                        role = guild.get_role(ROLE_ID)
                        if role:
                            coro_role = member.add_roles(role)
                            asyncio.run_coroutine_threadsafe(coro_role, bot.loop).result(timeout=10)
                            quiz_sessions.pop(str(user_id), None)
                            return render_template_string(HTML_TEMPLATE, username="認証完了", user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg="✨ 正解です！認証が完了し、ロールが付与されました！", msg_color="green")
                except Exception as e:
                    return render_template_string(HTML_TEMPLATE, username="エラー", user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg=f"❌ ロール付与失敗: {e}", msg_color="red")
    except ValueError:
        pass
    return render_template_string(HTML_TEMPLATE, username=session_data['username'], user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg="❌ 答えが違います。", msg_color="red")

def run_flask():
    # host='0.0.0.0' を足すことで、Renderが外からのアクセスをしっかり繋いでくれるようになります！
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    t = threading.Thread(target=run_flask)
    t.start()
    bot.run(TOKEN)
