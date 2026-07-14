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

# ==========================================
# ⚙️ 設定エリア（公開時は環境変数から読み込みます）
# ==========================================
# 公開用のサーバー（Renderなど）の管理画面から設定するよう、環境変数にします
TOKEN = os.environ.get('DISCORD_TOKEN', '')
CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')

GUILD_ID = 1526575335460573315  # サーバーID（公開されても大丈夫です）
ROLE_ID = 1526589486207733770   # ロールID（公開されても大丈夫です）
CLIENT_ID = '1526464758927200326' # クライアントID（公開されても大丈夫です）

# 公開用のドメインが決まったらここに書き換えます（まずはlocalhostのままでOK）
REDIRECT_URI = 'http://localhost:5000/callback'

# ==========================================
# 🤖 Discord Bot 側の設定
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # メンバーを操作するために必要
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
        print(f"同期エラー: {e}")

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

# セッション管理用の辞書
quiz_sessions = {}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇𝖾 . Official</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #f7f5f0;     /* 優しい生成り色 */
            --main-color: #e8a7a1;   /* ゆるいアッシュピンク */
            --text-color: #4a4a4a;   /* 柔らかいダークグレー */
            --card-bg: #ffffff;      /* 純白 */
            --accent-color: #ebd3c8; /* 薄いベージュ */
        }

        body {
            font-family: 'Shippori Mincho', serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        header {
            margin-top: 50px;
            text-align: center;
        }

        h1 {
            font-size: 2.8rem;
            margin-bottom: 5px;
            letter-spacing: 0.15em;
            color: var(--text-color);
        }

        .subtitle {
            font-size: 0.95rem;
            color: #888;
            letter-spacing: 0.05em;
        }

        /* 👑 タブメニュー */
        .tab-menu {
            display: flex;
            background-color: #e2dfd8;
            padding: 6px;
            border-radius: 30px;
            margin: 35px 0;
            box-shadow: inset 0 2px 5px rgba(0,0,0,0.03);
            flex-wrap: wrap;
            justify-content: center;
        }

        .tab-btn {
            font-family: 'Shippori Mincho', serif;
            background: none;
            border: none;
            padding: 10px 24px;
            font-size: 1rem;
            cursor: pointer;
            color: var(--text-color);
            border-radius: 25px;
            transition: all 0.3s ease;
        }

        .tab-btn.active {
            background-color: var(--main-color);
            color: white;
            font-weight: bold;
        }

        /* 📦 コンテンツエリア */
        .container {
            width: 90%;
            max-width: 750px;
            margin-bottom: 60px;
        }

        .tab-content {
            display: none;
            background-color: var(--card-bg);
            padding: 45px;
            border-radius: 28px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.02);
            line-height: 1.9;
        }

        .tab-content.active {
            display: block;
            animation: fadeIn 0.4s ease;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        h2 {
            font-size: 1.6rem;
            border-bottom: 2px solid var(--accent-color);
            padding-bottom: 10px;
            margin-top: 0;
            margin-bottom: 25px;
            color: #3a3a3a;
        }

        h3 {
            font-size: 1.2rem;
            margin-top: 30px;
            margin-bottom: 10px;
            color: #5a5a5a;
        }

        p {
            margin: 15px 0;
            font-size: 1.05rem;
        }

        ul, ol {
            padding-left: 20px;
        }

        li {
            margin-bottom: 10px;
        }

        /* 💡 特徴カード */
        .feature-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 25px;
        }

        @media (max-width: 600px) {
            .feature-grid { grid-template-columns: 1fr; }
        }

        .feature-card {
            background-color: var(--bg-color);
            padding: 20px;
            border-radius: 18px;
            border: 1px solid rgba(0,0,0,0.03);
        }

        .feature-card strong {
            color: var(--main-color);
            font-size: 1.1rem;
        }

        /* 🛠️ クイズエリア */
        .quiz-container {
            background: #fffafa;
            padding: 30px;
            border-radius: 20px;
            margin-top: 25px;
            text-align: center;
            border: 2px dashed var(--main-color);
        }

        .quiz-input {
            font-family: monospace;
            font-size: 1.4rem;
            padding: 8px;
            width: 100px;
            text-align: center;
            border-radius: 12px;
            border: 2px solid var(--accent-color);
            outline: none;
            margin-bottom: 15px;
        }

        .quiz-input:focus {
            border-color: var(--main-color);
        }

        .btn-submit {
            display: block;
            margin: 10px auto 0 auto;
            background-color: var(--main-color);
            color: white;
            border: none;
            padding: 12px 35px;
            border-radius: 25px;
            cursor: pointer;
            font-family: 'Shippori Mincho', serif;
            font-weight: bold;
            font-size: 1rem;
            transition: background 0.2s;
        }

        .btn-submit:hover {
            background-color: #df9690;
        }

        .code-block {
            background: #fdfaf6;
            padding: 20px;
            border-radius: 16px;
            border-left: 4px solid var(--main-color);
            font-family: monospace;
            font-size: 0.95rem;
            overflow-x: auto;
        }
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
            <p>「𝖼𝗁illis 𝗓𝗈𝗇𝖾 .」は、中学生、高校生、そして未来に向かってひたむきに励む受験生が、それぞれのペースで勉強や作業を進めるためのコミュニティです。</p>
            <p>派手な雑談や騒がしい空気はありません。ただ静かに集中したい夜も、誰かの頑張る気配を感じながらモチベーションを保ちたい放課後も。いつでもあなたの作業机が、ここに用意されています。</p>
            
            <h3>🌿 𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇𝖾 . の3つの過ごし方</h3>
            <div class="feature-grid">
                <div class="feature-card">
                    <p><strong>01. 音のない集中スペース</strong></p>
                    <p style="font-size:0.95rem;">カメラ配信やマイクでの会話を必要としない、文字とタイマーだけの静かな部屋。自分の世界に没頭できます。</p>
                </div>
                <div class="feature-card">
                    <p><strong>02. 気配を感じる作業VC</strong></p>
                    <p style="font-size:0.95rem;">BGMを流したり、キーボードの打鍵音やペンを走らせる音だけがかすかに聞こえる、自習室のような空間です。</p>
                </div>
                <div class="feature-card">
                    <p><strong>03. 積み重ねを記録する</strong></p>
                    <p style="font-size:0.95rem;">毎日の勉強時間を自作のBotが正確に自動計測。頑張った成果が目に見える形でグラフやランキングに残ります。</p>
                </div>
                <div class="feature-card">
                    <p><strong>04. 同じ目標を持つ仲間</strong></p>
                    <p style="font-size:0.95rem;">定期テスト、高校入試、大学共通テストなど、同じ壁に立ち向かう同世代とそっと励まし合える環境です。</p>
                </div>
            </div>
        </div>

        <div id="rules" class="tab-content">
            <h2>コミュニティのたいせつな約束</h2>
            <p>みんなが安心して、それぞれの目標に集中できる空間を維持するために、以下のガイドラインを設けています。入室前にご一読ください。</p>
            
            <h3>✅ 守ってほしいこと</h3>
            <ul>
                <li><strong>思いやりのある言葉遣い</strong>：画面の向こうには一人の人間がいます。敬意を持った優しいコミュニケーションを心がけましょう。</li>
                <li><strong>個人情報の保護</strong>：ネットの安全のため、本名、学校名、顔写真、具体的な最寄り駅などの情報は教え合わないようにしてください。</li>
                <li><strong>目的の尊重</strong>：ここは作業と勉強の場所です。過度な雑談で他の方の集中の妨げにならないよう配慮をお願いします。</li>
            </ul>

            <h3>❌ 禁止していること</h3>
            <ul>
                <li>許可のない外部サーバーの宣伝、勧誘、広告行為。</li>
                <li>特定のメンバーに対する誹謗中傷、荒らし行為、嫌がらせ。</li>
                <li>出会いを目的とした利用、および個別DM（ダイレクトメッセージ）での迷惑な付きまとわり。</li>
            </ul>
            <p style="font-size:0.9rem; color:#888;">※ルールに違反した場合、運営判断によりサーバーから退出（キック・BAN）の処置を取る場合があります。</p>
        </div>

        <div id="contact" class="tab-content">
            <h2>困ったとき・お問い合わせ</h2>
            <p>サーバーを利用していて困ったことや、バグの報告、ルール違反を見かけた場合は、以下のいずれかの方法で運営チームへご連絡ください。</p>
            
            <h3>📥 1. Discord内での報告</h3>
            <p>サーバー内にある「<code>📨｜お問い合わせ窓口</code>」チャンネルにて、運営宛てにメッセージを送信してください。管理人（aki-f）およびモデレーターにのみ内容が届く安全な部屋が作成されます。</p>
            
            <h3>🌐 2. 匿名意見箱（Googleフォーム）</h3>
            <p>「直接話すのは少し緊張する…」という場合は、匿名の意見箱フォームを用意しています。完全匿名で、要望や改善アイデアを送信することができます。</p>
            <p style="text-align: center; margin-top: 25px;">
                <span style="background: var(--main-color); color:white; padding: 10px 25px; border-radius: 50px; font-weight: bold; cursor:pointer;">意見箱フォームを開く（準備中）</span>
            </p>
        </div>

        <div id="commands" class="tab-content">
            <h2>自作Time Tracker コマンドガイド</h2>
            <p>「𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇𝖾 .」専用のオリジナル計測システムです。ボイスチャンネルに滞在した時間が秒単位で記録され、以下のコマンドでいつでも確認できます。</p>
            
            <h3>📊 主要コマンド一覧</h3>
            <div class="code-block">
                <strong>/status</strong><br>
                ➔ 自分のこれまでの合計勉強時間、今週の作業時間、平均活動時間のデータを綺麗に確認できます。<br><br>
                <strong>/ranking</strong><br>
                ➔ サーバー内で今週もっとも勉強を頑張っているメンバーのランキングをTOP10まで表示します。
            </div>

            <h3>💡 計測のコツ</h3>
            <p>勉強を始めるときは、<code>🔊｜勉強机-1</code> などの作業ボイスチャンネルに入るだけで自動的にタイマーがスタートします。特別な開始コマンドを打つ必要はありません。退出時に自動で時間が保存されます。</p>
        </div>

        <div id="verify" class="tab-content">
            <h2>🔒 サーバー認証テスト</h2>
            {% if user_id %}
                <p>こんにちは、<b>{{ username }}</b> さん。スパムBotによる荒らしを防止するため、以下の計算問題を解いてください。</p>
                
                <form action="/submit-quiz" method="POST" class="quiz-container">
                    <input type="hidden" name="user_id" value="{{ user_id }}">
                    <p style="font-size: 1.8rem; font-weight: bold; letter-spacing: 0.05em; color: var(--main-color);"> {{ num1 }} + {{ num2 }} = ？ </p>
                    <input type="number" name="answer" class="quiz-input" placeholder="答え" required autofocus><br>
                    <button type="submit" class="btn-submit">送信して認証を完了する</button>
                    {% if msg %}
                        <p style="margin-top: 20px; font-weight: bold; color: {{ msg_color }};">{{ msg }}</p>
                    {% endif %}
                </form>
            {% else %}
                <p style="color: red; font-weight: bold; text-align: center; margin-top: 30px;">
                    {{ msg }}
                </p>
            {% endif %}
        </div>

    </div>

    <script>
        function openTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            const targetContent = document.getElementById(tabId);
            if(targetContent) {
                targetContent.classList.add('active');
            }
            // タブボタンのアクティブ化
            const targetBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick').includes(tabId));
            if(targetBtn) targetBtn.classList.add('active');
        }

        // 初期状態でクイズ用のデータがある場合は認証タブを強制的に開く
        {% if user_id and msg != "Discordから認証ボタンを押してアクセスしてください。" %}
            openTab('verify');
        {% endif %}
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="", num1=5, num2=8, msg="Discordの認証パネルにあるボタンを押してアクセスしてください。", msg_color="red")

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return redirect(url_for('index'))
    
    # 1. アクセストークンの取得
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

    # 2. ユーザー情報の取得
    user_headers = {'Authorization': f'Bearer {access_token}'}
    user_r = requests.get('https://discord.com/api/users/@me', headers=user_headers)
    user_json = user_r.json()
    
    discord_id = user_json.get('id')
    discord_username = user_json.get('username')
    
    # 🎲 ランダムな問題を生成（1〜20の数字）
    n1 = random.randint(1, 20)
    n2 = random.randint(1, 20)
    
    if discord_id:
        quiz_sessions[str(discord_id)] = {
            'correct_answer': n1 + n2,
            'username': discord_username,
            'num1': n1,
            'num2': n2
        }
    
    return render_template_string(HTML_TEMPLATE, username=discord_username, user_id=discord_id, num1=n1, num2=n2, msg=None)

@app.route('/submit-quiz', methods=['POST'])
def submit_quiz():
    user_id = request.form.get('user_id')
    user_answer = request.form.get('answer')
    
    session_data = quiz_sessions.get(str(user_id))
    
    if not session_data:
        return render_template_string(HTML_TEMPLATE, username="エラー", user_id=user_id, num1=0, num2=0, msg="タイムアウトしました。もう一度Discordのボタンからやり直してください。", msg_color="red")
    
    try:
        if int(user_answer) == session_data['correct_answer']:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                try:
                    # 💡 スレッドセーフにBot側の非同期処理（fetch_member）を実行
                    coro_member = guild.fetch_member(int(user_id))
                    future_member = asyncio.run_coroutine_threadsafe(coro_member, bot.loop)
                    member = future_member.result(timeout=10)

                    if member:
                        role = guild.get_role(ROLE_ID)
                        if role:
                            # 💡 スレッドセーフにロール付与（add_roles）を実行
                            coro_role = member.add_roles(role)
                            asyncio.run_coroutine_threadsafe(coro_role, bot.loop).result(timeout=10)
                            
                            # 成功したらセッションを削除
                            quiz_sessions.pop(str(user_id), None)
                            
                            return render_template_string(HTML_TEMPLATE, username="認証完了", user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg="✨ 正解です！認証が完了し、ロールが付与されました！Discordの画面に戻ってください。", msg_color="green")
                        else:
                            return render_template_string(HTML_TEMPLATE, username="エラー", user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg="❌ 設定されたロールIDがサーバー内に見つかりません。", msg_color="red")
                except Exception as e:
                    print(f"ロール付与エラー: {e}")
                    return render_template_string(HTML_TEMPLATE, username="エラー", user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg=f"❌ ロール付与に失敗しました。\n(Botのロール順位が低い可能性があります)", msg_color="red")
            else:
                return render_template_string(HTML_TEMPLATE, username="エラー", user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg="❌ サーバーが見つかりませんでした。", msg_color="red")
    except ValueError:
        pass
        
    return render_template_string(HTML_TEMPLATE, username=session_data['username'], user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg="❌ 答えが違います。もう一度計算してみてください。", msg_color="red")

# ==========================================
# 🚀 同時起動の処理
# ==========================================
def run_flask():
    app.run(port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    t = threading.Thread(target=run_flask)
    t.start()
    bot.run(TOKEN)