import os 
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Button, View
from flask import Flask, render_template_string, request, redirect, url_for
import threading
import requests
import json
import random
import asyncio
import time
from datetime import datetime, timedelta

# ==========================================
# ⚙️ 設定エリア
# ==========================================
TOKEN = os.environ.get('DISCORD_TOKEN', '')
CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')

GUILD_ID = 1526575335460573315  
ROLE_ID = 1526589486207733770   
CLIENT_ID = '1526464758927200326' 
REDIRECT_URI = 'https://chillzone-5oxh.onrender.com/callback'

# 📂 専用個室を作るカテゴリのID
CATEGORY_ID = 1526720938517856297  

# 📢 各種チャンネルのID（ご指定通りに設定済み）
CONGRATS_CHANNEL_ID = 1526576980198428715  # 退出ログの送信先
WEEKLY_RANKING_CHANNEL_ID = 1526576085444071495  # 頑張り屋表彰のお知らせ先

# ==========================================
# 💾 データ保存用システム（JSON）
# ==========================================
DATA_FILE = "user_stats.json"
RESPONSES_FILE = "auto_responses.json"

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

def load_responses():
    if os.path.exists(RESPONSES_FILE):
        try:
            with open(RESPONSES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_responses(responses):
    with open(RESPONSES_FILE, "w", encoding="utf-8") as f:
        json.dump(responses, f, indent=4, ensure_ascii=False)

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
intents.voice_states = True
bot = commands.Bot(command_prefix="/", intents=intents)

vc_start_times = {}
room_counter = 1      
active_rooms = {}     

active_bump_timers = {}
active_pomo_timers = {}
afk_trackers = {}  # 居眠り防止用の放置時間記録

# ⏱️ Bot起動時刻の記録
bot_start_time = datetime.now()

# 🔑 認証用View
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

# 🚪 個室作成用View
class PrivateRoomView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="自分の作業部屋を開放", style=discord.ButtonStyle.success, custom_id="create_private_room")
    async def create_room_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global room_counter
        guild = interaction.guild
        category = guild.get_channel(CATEGORY_ID)
        
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("❌ カテゴリの設定が正しくありません。管理者に連絡してください。", ephemeral=True)
            return
            
        for r_id, info in active_rooms.items():
            if info["owner_id"] == interaction.user.id:
                existing_room = guild.get_channel(r_id)
                if existing_room:
                    await interaction.response.send_message(f"❌ すでにあなたの部屋 {existing_room.mention} が存在します。", ephemeral=True)
                    return

        numbers = ["⓪", "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳"]
        num_str = numbers[room_counter] if room_counter < len(numbers) else f" {room_counter}"
        room_name = f"カフェルーム{num_str}"
        room_counter += 1
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False), 
            interaction.user: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True), 
            guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True) 
        }
        
        new_channel = await guild.create_voice_channel(name=room_name, category=category, overwrites=overwrites)
        active_rooms[new_channel.id] = {
            "owner_id": interaction.user.id,
            "created_at": datetime.now()
        }
        
        await interaction.response.send_message(f"✨ 専用の作業部屋を作成しました！➔ {new_channel.mention}\n※退出するか、24時間経過すると自動で削除されます。", ephemeral=True)

# 🔄 ステータスを30秒周期で交互に切り替えるループタスク
@tasks.loop(seconds=30)
async def update_status_loop():
    await bot.wait_until_ready()
    current_time = int(time.time())
    
    working_users = 0
    guild = bot.get_guild(GUILD_ID)
    if guild:
        for vc in guild.voice_channels:
            working_users += len([m for m in vc.members if not m.bot])

    uptime = datetime.now() - bot_start_time
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)
    
    if hours > 0:
        uptime_str = f"起動中: {hours}時間{minutes}分"
    else:
        uptime_str = f"起動中: {minutes}分"

    if (current_time // 30) % 2 == 0:
        activity = discord.Activity(type=discord.ActivityType.playing, name=f"{working_users}人が作業中 ✍️")
    else:
        activity = discord.Activity(type=discord.ActivityType.watching, name=uptime_str)
        
    await bot.change_presence(activity=activity)

# 💤 居眠り・放置防止ループ（1分ごとに巡回）
@tasks.loop(minutes=1)
async def check_afk_loop():
    await bot.wait_until_ready()
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
        
    now = time.time()
    for vc in guild.voice_channels:
        for member in vc.members:
            if member.bot:
                continue
                
            # マイクミュートかつスピーカーミュート（フルミュート）状態かチェック
            if member.voice.self_mute and member.voice.self_deaf:
                user_id = str(member.id)
                if user_id not in afk_trackers:
                    afk_trackers[user_id] = now
                elif now - afk_trackers[user_id] >= 900:  # 15分（900秒）以上経過
                    try:
                        await member.move_to(None, reason="居眠り・放置防止による自動切断")
                        afk_trackers.pop(user_id, None)
                        
                        # ログ用チャンネルへ通知
                        log_channel = bot.get_channel(CONGRATS_CHANNEL_ID)
                        if log_channel:
                            await log_channel.send(f"💤 {member.mention} さんが15分以上無反応（フルミュート）だったため、接続を切断しました。体調に合わせてゆっくり休んでくださいね。")
                    except Exception as e:
                        print(f"AFK自動切断に失敗: {e}")
            else:
                # ミュートが解除されたら放置タイマーをリセット
                afk_trackers.pop(str(member.id), None)

# 👑 週刊頑張り屋表彰ループ（毎週月曜日 AM 7:00）
@tasks.loop(time=datetime.strptime("07:00", "%H:%M").time())
async def weekly_ranking_loop():
    await bot.wait_until_ready()
    # 月曜日(0)のときだけ実行
    if datetime.now().weekday() != 0:
        return
        
    ranking_channel = bot.get_channel(WEEKLY_RANKING_CHANNEL_ID)
    if not ranking_channel:
        return
        
    stats = load_stats()
    if not stats:
        return
        
    # 直近1週間のweekly_logを元に合計時間を集計
    user_weekly_totals = []
    today = datetime.now()
    past_7_days = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    
    for uid, data in stats.items():
        weekly_log = data.get("weekly_log", {})
        weekly_sum = sum(weekly_log.get(day, 0.0) for day in past_7_days)
        if weekly_sum > 0:
            user_weekly_totals.append((data.get("username", "不明なユーザー"), weekly_sum))
            
    if not user_weekly_totals:
        return
        
    # 上位3名をソートして抽出
    user_weekly_totals.sort(key=lambda x: x[1], reverse=True)
    top_3 = user_weekly_totals[:3]
    
    embed = discord.Embed(
        title="🏆 週刊『頑張り屋』表彰式 🏆",
        description="先週1週間で、最も素晴らしい集中力を見せてくれたメンバーの発表です！👏",
        color=0xffd700
    )
    
    medals = ["🥇 最優秀頑張り屋", "🥈 優秀頑張り屋", "🥉 頑張り屋"]
    for i, (username, total_m) in enumerate(top_3):
        embed.add_field(
            name=medals[i], 
            value=f"**{username}** さん\n┗ 先週の作業時間: **{round(total_m, 1)} 分**", 
            inline=False
        )
        
    embed.set_footer(text="今週もそれぞれのペースで、コツコツ積み重ねていきましょう！✨")
    await ranking_channel.send(embed=embed)
    
    # 次の週のために、全ユーザーのweekly_logを綺麗に掃除（初期化はせず古いものとして維持）
    save_stats(stats)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    bot.add_view(PrivateRoomView()) 
    bot.loop.create_task(check_room_expiry()) 
    
    if not update_status_loop.is_running():
        update_status_loop.start()
    if not check_afk_loop.is_running():
        check_afk_loop.start()
    if not weekly_ranking_loop.is_running():
        weekly_ranking_loop.start()
        
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンドを {len(synced)} 個同期しました。")
    except Exception as e:
        print(f"同期エラー: {e}")

# 💬 自動返答とコマンド処理
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)
    responses = load_responses()
    content = message.content.strip()
    if content in responses:
        await message.channel.send(responses[content])

# 📝 チャンネル作成のログ
@bot.event
async def on_guild_channel_create(channel):
    if channel.category_id == CATEGORY_ID and isinstance(channel, discord.VoiceChannel):
        print(f"【ログ】ボイスチャンネルが作成されました: {channel.name} (ID: {channel.id})")

# ⏰ ボイスステート監視（作業時間集計 & お疲れ様メッセージ送信 & 継続日数管理）
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    user_id = str(member.id)
    
    # VCに入ったとき、またはフルミュートが解除されたときに放置状態をクリア
    if after.channel is not None:
        if not (member.voice.self_mute and member.voice.self_deaf):
            afk_trackers.pop(user_id, None)
            
    # 1. VCに参加した時刻を記録
    if before.channel is None and after.channel is not None:
        vc_start_times[user_id] = time.time()
        
    # 2. VCから退出（または完全に切断）した時の計算
    elif before.channel is not None and after.channel is None:
        afk_trackers.pop(user_id, None)  # 完全に退出したら放置トラッカーを消去
        start_time = vc_start_times.pop(user_id, None)
        if start_time:
            duration = time.time() - start_time
            minutes_earned = round(duration / 60, 1)
            
            # 1分以上の作業のみ記録
            if minutes_earned >= 1.0:
                stats = load_stats()
                
                # 新規ユーザーデータ初期化
                if user_id not in stats:
                    stats[user_id] = {
                        "username": member.name, 
                        "total_minutes": 0.0, 
                        "level": 1,
                        "streak": 0,
                        "last_active_date": "",
                        "weekly_log": {}
                    }
                
                user_data = stats[user_id]
                today_str = datetime.now().strftime("%Y-%m-%d")
                yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                
                # 累計時間の加算
                user_data["total_minutes"] = round(user_data["total_minutes"] + minutes_earned, 1)
                user_data["username"] = member.name
                
                # 今日の目標用の本日の時間更新
                if user_data.get("last_active_date") != today_str:
                    user_data["today_minutes"] = 0.0
                user_data["today_minutes"] = round(user_data.get("today_minutes", 0.0) + minutes_earned, 1)
                
                # 📅 直近1週間の学習ログ（weekly_log）の更新
                if "weekly_log" not in user_data:
                    user_data["weekly_log"] = {}
                user_data["weekly_log"][today_str] = round(user_data["weekly_log"].get(today_str, 0.0) + minutes_earned, 1)
                
                # 1週間以上前の古いログをJSON肥大化防止のため削除
                cutoff_date = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
                user_data["weekly_log"] = {d: m for d, m in user_data["weekly_log"].items() if d >= cutoff_date}
                
                # 🔥 連続自習ストリーク（ログイン日数）の計算
                last_active = user_data.get("last_active_date", "")
                current_streak = user_data.get("streak", 0)
                
                if last_active == yesterday_str:
                    if current_streak == 0:
                        user_data["streak"] = 1
                    else:
                        user_data["streak"] += 1
                elif last_active == today_str:
                    pass
                else:
                    user_data["streak"] = 1
                
                user_data["last_active_date"] = today_str
                
                # レベルの再計算
                new_level, _ = calculate_level(int(user_data["total_minutes"]))
                user_data["level"] = new_level
                
                save_stats(stats)
                print(f"【記録】{member.name} が {minutes_earned} 分作業しました。（本日累計: {user_data['today_minutes']} 分）")
                
                # 🎉 お疲れ様お祝いメッセージの自動送信（ご指定のログチャンネルへ）
                congrats_channel = bot.get_channel(CONGRATS_CHANNEL_ID)
                if congrats_channel:
                    goal_min = user_data.get("daily_goal", 0)
                    today_total = user_data["today_minutes"]
                    
                    is_goal_achieved = goal_min > 0 and today_total >= goal_min
                    
                    embed = discord.Embed(
                        title="📝 ワークスペース退出ログ",
                        description=f"{member.mention} さん、作業お疲れ様でした！✨",
                        color=0x4ab3e3 if is_goal_achieved else 0xe8a7a1
                    )
                    embed.add_field(name="⏱️ 今回の作業時間", value=f"**{minutes_earned} 分**", inline=True)
                    embed.add_field(name="📅 本日の累計", value=f"**{today_total} 分**", inline=True)
                    embed.add_field(name="🔥 連続継続日数", value=f"**{user_data['streak']} 日連続**", inline=True)
                    
                    if is_goal_achieved:
                        embed.add_field(
                            name="🎉 目標達成！", 
                            value=f"本日の目標（{goal_min}分）を見事突破しました！素晴らしい集中力です！👏", 
                            inline=False
                        )
                    elif goal_min > 0:
                        embed.add_field(
                            name="🎯 今日の目標まであと", 
                            value=f"残り **{round(max(0.0, goal_min - today_total), 1)} 分** です！自分のペースで進めましょう。", 
                            inline=False
                        )
                        
                    embed.set_thumbnail(url=member.display_avatar.url)
                    await congrats_channel.send(embed=embed)

    # 3. 誰もいなくなった個室（カフェルーム）の自動削除
    if before.channel and before.channel.id in active_rooms:
        if len(before.channel.members) == 0:
            try:
                channel_id = before.channel.id
                await before.channel.delete()
                active_rooms.pop(channel_id, None)
                print(f"【削除】誰もいなくなったため、{before.channel.name} を削除しました。")
            except Exception as e:
                print(f"部屋の自動削除に失敗: {e}")

async def check_room_expiry():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.now()
        to_delete = []
        for r_id, info in list(active_rooms.items()):
            if now - info["created_at"] >= timedelta(hours=24):
                to_delete.append(r_id)
        for r_id in to_delete:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                channel = guild.get_channel(r_id)
                if channel:
                    try:
                        await channel.delete()
                        print(f"【時間切れ削除】24時間経過したため {channel.name} を削除しました。")
                    except Exception as e:
                        print(f"時間切れ削除に失敗: {e}")
            active_rooms.pop(r_id, None)
        await asyncio.sleep(60)

# 📢 BUMP通知コマンド
@bot.tree.command(name="bump", description="BUMPの2時間後通知タイマーをセットします")
async def bump(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id in active_bump_timers:
        await interaction.response.send_message("⚠️ このチャンネルでは既にBUMPタイマーが作動中です！", ephemeral=True)
        return
    
    await interaction.response.send_message("BUMPタイマーをセットしました！", ephemeral=True)
    
    embed = discord.Embed(
        title="🔔 BUMPタイマー始動",
        description="BUMPの実行を検知しました！\nこれより**2時間後（120分後）**に自動でこのチャンネルにお知らせします。",
        color=0x4ab3e3
    )
    await interaction.channel.send(embed=embed)
    
    async def bump_timer(cid):
        await asyncio.sleep(7200)
        channel = bot.get_channel(cid)
        if channel:
            await channel.send("⏳ BUMPの時間だよ！")
        active_bump_timers.pop(cid, None)
            
    task = bot.loop.create_task(bump_timer(channel_id))
    active_bump_timers[channel_id] = task

@bot.tree.command(name="setup_verify", description="認証パネルを設置します")
@app_commands.checks.has_permissions(administrator=True)
async def setup_verify(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔒 𝖼𝗁𝗂𝗅𝗅 𝗓𝗈 ... 認証パネル",
        description="下のボタンを押して、Webサイトから認証を完了してください。\n認証が成功すると、自動的にロールが付与されます。",
        color=0xff9966
    )
    await interaction.response.send_message(embed=embed, view=VerificationView())

@bot.tree.command(name="setup_room", description="個室作成パネルを設置します")
@app_commands.checks.has_permissions(administrator=True)
async def setup_room(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🚪 自分専用 of 作業部屋を開放",
        description="下のボタンを押すと、あなたと管理者だけが見える専用ボイスチャンネル『カフェルーム①〜』が自動作成されます。\n\n・勉強が終わって全員が退出すると自動で消滅します。\n・作成から24時間が経過すると自動で強制削除されます。",
        color=0xe8a7a1
    )
    await interaction.response.send_message(embed=embed, view=PrivateRoomView())

# 🎯 目標時間設定コマンド
@bot.tree.command(name="goal", description="今日の作業目標時間（分）を設定します")
@app_commands.describe(minutes="今日の目標時間を分単位で設定（例: 120）")
async def goal(interaction: discord.Interaction, minutes: int):
    if minutes <= 0:
        await interaction.response.send_message("❌ 目標時間は1分以上に設定してください。", ephemeral=True)
        return
        
    user_id = str(interaction.user.id)
    stats = load_stats()
    
    if user_id not in stats:
        stats[user_id] = {
            "username": interaction.user.name, 
            "total_minutes": 0.0, 
            "level": 1,
            "streak": 0,
            "last_active_date": "",
            "weekly_log": {}
        }
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    stats[user_id]["daily_goal"] = minutes
    stats[user_id]["last_active_date"] = today_str
    if "today_minutes" not in stats[user_id]:
        stats[user_id]["today_minutes"] = 0.0
        
    save_stats(stats)
    await interaction.response.send_message(f"🎯 今日の作業目標を **{minutes}分** に設定しました！無理せず自分のペースで頑張りましょう！")

# 📊 ステータス確認（1週間グラフ & ストリーク追加）
@bot.tree.command(name="status", description="自分の作業時間、目標達成率、1週間のグラフと継続日数を確認します")
async def status(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    stats = load_stats()
    
    if user_id not in stats:
        stats[user_id] = {
            "username": interaction.user.name, 
            "total_minutes": 0.0, 
            "level": 1,
            "streak": 0,
            "last_active_date": "",
            "weekly_log": {}
        }
        
    user_data = stats[user_id]
    total_min = user_data["total_minutes"]
    current_level, next_remain = calculate_level(int(total_min))
    
    embed = discord.Embed(title=f"📊 {interaction.user.name} さんの作業スタッツ", color=0xe8a7a1)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    last_active = user_data.get("last_active_date", "")
    
    if last_active != today_str and last_active != yesterday_str:
        streak_days = 0
    else:
        streak_days = user_data.get("streak", 0)
        
    embed.add_field(name="👑 現在のレベル", value=f"**Lv. {current_level}**", inline=True)
    embed.add_field(name="🔥 連続自習記録", value=f"**{streak_days} 日連続**", inline=True)
    embed.add_field(name="⏱️ 累計作業時間", value=f"**{total_min} 分**", inline=True)
    embed.add_field(name="✨ 次のLvまであと", value=f"`{round(next_remain, 1)}` 分", inline=True)
    
    goal_min = user_data.get("daily_goal", 0)
    if user_data.get("last_active_date") != today_str:
        today_done = 0.0
    else:
        today_done = user_data.get("today_minutes", 0.0)
        
    if goal_min > 0:
        percent = min(round((today_done / goal_min) * 100), 100)
        bar = make_progress_bar(percent)
        goal_text = f"**{today_done}分** / **{goal_min}分**\n{bar} ({percent}%)"
    else:
        goal_text = "未設定（`/goal` でセットできます）"
        
    embed.add_field(name="🎯 本日の学習目標", value=goal_text, inline=False)
    
    weekly_log = user_data.get("weekly_log", {})
    graph_text = ""
    weekday_labels = ["月", "火", "水", "木", "金", "土", "日"]
    
    today = datetime.now()
    for i in range(6, -1, -1):
        target_date = today - timedelta(days=i)
        date_key = target_date.strftime("%Y-%m-%d")
        wday_label = weekday_labels[target_date.weekday()]
        
        minutes_done = weekly_log.get(date_key, 0.0)
        block_count = min(int(minutes_done // 30), 5)
        blocks = "🟩" * block_count if block_count > 0 else "⬜"
        
        graph_text += f"`{target_date.strftime('%m/%d')}({wday_label})` : {blocks} *({minutes_done}分)*\n"
        
    embed.add_field(name="📊 直近1週間の作業推移 (30分=🟩)", value=graph_text, inline=False)
    
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ranking", description="サーバー内の作業時間ランキングTOP10を表示します")
async def ranking(interaction: discord.Interaction):
    stats = load_stats()
    if not stats:
        await interaction.response.send_message("まだ誰の作業時間も記録されていません！")
        return
    sorted_stats = sorted(stats.items(), key=lambda x: x[1]["total_minutes"], reverse=True)[:10]
    embed = discord.Embed(title="🏆 𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇 . 作業時間ランキング", color=0xe8a7a1)
    ranking_text = ""
    medal = ["🥇", "🥈", "🥉"]
    for i, (uid, data) in enumerate(sorted_stats):
        rank_icon = medal[i] if i < 3 else f"`#{i+1}`"
        ranking_text += f"{rank_icon} **{data['username']}** - Lv.{data.get('level', 1)} ({data['total_minutes']}分)\n"
    embed.description = ranking_text
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="server_stats", description="サーバー全体の作業統計データを表示します")
async def server_stats(interaction: discord.Interaction):
    stats = load_stats()
    total_users = len(stats)
    total_minutes = sum(data.get("total_minutes", 0.0) for data in stats.values())
    
    uptime = datetime.now() - bot_start_time
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)
    
    embed = discord.Embed(title="📈 𝖼𝗁𝗂𝗅𝗅 𝗓ον . サーバー統計", color=0x4ab3e3)
    embed.add_field(name="👥 登録作業メンバー数", value=f"{total_users} 人", inline=True)
    embed.add_field(name="⏱️ 累計作業時間", value=f"{round(total_minutes, 1)} 分", inline=True)
    embed.add_field(name="🤖 Botの連続稼働時間", value=f"{hours}時間{minutes}分", inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clean_rooms", description="【管理者専用】作成されたカフェルームを一括ですべて削除します")
@app_commands.checks.has_permissions(administrator=True)
async def clean_rooms(interaction: discord.Interaction):
    global active_rooms
    guild = interaction.guild
    category = guild.get_channel(CATEGORY_ID)
    
    if not category:
        await interaction.response.send_message("❌ 指定のカテゴリが見つかりません。", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True)
    
    deleted_count = 0
    for vc in category.voice_channels:
        if vc.name.startswith("カフェルーム"):
            try:
                await vc.delete()
                deleted_count += 1
            except Exception as e:
                print(f"お掃除中のチャンネル削除失敗: {e}")
                
    active_rooms.clear()
    await interaction.followup.send(f"🧹 お掃除が完了しました！計 {deleted_count} 個のカフェルームを消去しました。", ephemeral=True)

@bot.tree.command(name="dice", description="指定した数と面のサイコロを振ります (例: 個数=2, 面数=6)")
@app_commands.describe(amount="サイコロの個数 (最大10)", sides="サイコロの面数 (最大100)")
async def dice(interaction: discord.Interaction, amount: int = 1, sides: int = 6):
    if amount < 1 or amount > 10:
        await interaction.response.send_message("❌ 個数は 1〜10個 の間で指定してください。", ephemeral=True)
        return
    if sides < 2 or sides > 100:
        await interaction.response.send_message("❌ 面数は 2〜100面 の間で指定してください。", ephemeral=True)
        return
        
    results = [random.randint(1, sides) for _ in range(amount)]
    total = sum(results)
    
    embed = discord.Embed(
        title="🎲 サイコロを振りました！",
        description=f"**{amount}個**の**{sides}面ダイス**を振った結果はこちらです。",
        color=0xe8a7a1
    )
    embed.add_field(name="🔢 出目", value=f"`{' , '.join(map(str, results))}`", inline=False)
    embed.add_field(name="🎯 合計値", value=f"**{total}**", inline=False)
    
    await interaction.response.send_message(embed=embed)

# 🚨 管理者への通報システム
@bot.tree.command(name="report", description="不適切な行為や不具合などを管理者にDMで通報します")
@app_commands.describe(reason="通報の内容・理由を入力してください", user="対象のユーザー（いる場合のみ指定）")
async def report(interaction: discord.Interaction, reason: str, user: discord.Member = None):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ このコマンドはサーバー内でのみ使用可能です。", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True)
    admins = [m for m in guild.members if m.guild_permissions.administrator and not m.bot]
    
    if not admins:
        await interaction.followup.send("❌ このサーバーに管理者が見つかりませんでした。", ephemeral=True)
        return
        
    embed = discord.Embed(
        title="🚨 【通報】𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇 . 管理者通知",
        description="サーバー内で通報が行われました。内容を確認してください。",
        color=0xff0000,
        timestamp=datetime.now()
    )
    embed.add_field(name="👤 送信者", value=f"{interaction.user.mention} ({interaction.user.name})", inline=True)
    if user:
        embed.add_field(name="🎯 対象ユーザー", value=f"{user.mention} ({user.name})", inline=True)
    embed.add_field(name="📄 内容・理由", value=reason, inline=False)
    embed.set_footer(text=f"送信元サーバー: {guild.name}")
    
    sent_count = 0
    for admin in admins:
        try:
            await admin.send(embed=embed)
            sent_count += 1
        except discord.Forbidden:
            pass
            
    if sent_count > 0:
        await interaction.followup.send("🚨 管理者への通報を完了しました。ご報告ありがとうございます！", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ 管理者にDMを送信できませんでした。管理者のDM受信設定が閉じられている可能性があります。", ephemeral=True)

# 💬 自動返答の追加コマンド
@bot.tree.command(name="addword", description="自動返答するワードを追加します")
@app_commands.describe(trigger="反応する言葉", response="Botが返す言葉")
async def addword(interaction: discord.Interaction, trigger: str, response: str):
    responses = load_responses()
    responses[trigger] = response
    save_responses(responses)
    
    embed = discord.Embed(
        title="✅ 自動返答を設定しました！",
        description=f"これより、メンバーが「**{trigger}**」と打つと、Botが自動で「**{response}**」と返答するようになります。",
        color=0x4ab3e3
    )
    await interaction.response.send_message(embed=embed)

# 💬 登録された自動返答ワードの一覧表示
@bot.tree.command(name="worda", description="現在登録されている自動返答ワードをすべて確認します")
async def worda(interaction: discord.Interaction):
    responses = load_responses()
    if not responses:
        await interaction.response.send_message("📭 現在登録されている自動返答ワードはありません。", ephemeral=True)
        return
        
    embed = discord.Embed(title="💬 登録済み自動返答ワード一覧", color=0xe8a7a1)
    
    list_text = ""
    for trigger, response in responses.items():
        list_text += f"• **{trigger}** ➔ {response}\n"
        
    if len(list_text) > 4000:
        list_text = list_text[:4000] + "\n...他多数"
        
    embed.description = list_text
    await interaction.response.send_message(embed=embed)

# ==========================================
# ⏱️ ポモドーロタイマー
# ==========================================

def make_progress_bar(percent, size=10):
    filled = int(round(size * percent / 100))
    bar = "🟥" * filled + "⬜" * (size - filled)
    return bar

async def change_user_nickname(member, suffix):
    try:
        base_name = member.display_name
        for tag in [" [✍️集中中]", " [💤休憩中]"]:
            if base_name.endswith(tag):
                base_name = base_name[:-len(tag)]
        
        if suffix:
            new_nick = f"{base_name} {suffix}"
            if len(new_nick) > 32:
                new_nick = base_name[:(32 - len(suffix) - 1)] + f" {suffix}"
            await member.edit(nick=new_nick)
        else:
            await member.edit(nick=base_name)
    except discord.Forbidden:
        pass

@bot.tree.command(name="pomodoro", description="ポモドーロタイマーを開始します")
async def pomodoro(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in active_pomo_timers:
        await interaction.response.send_message("⚠️ すでにあなたのポモドーロタイマーが作動中です！", ephemeral=True)
        return
        
    original_nick = interaction.user.display_name
    await change_user_nickname(interaction.user, "[✍️集中中]")
    
    initial_embed = discord.Embed(
        title="⏱️ ポモドーロタイマー始動",
        description=f"{interaction.user.mention} さんのタイマーをセットしました！\n\n**🎯 集中フェーズ (25分間)** がスタートします！",
        color=0xe8a7a1
    )
    initial_embed.add_field(name="⏱️ 残り時間", value="`25:00`", inline=True)
    initial_embed.add_field(name="📊 進捗", value="⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ (0%)", inline=False)
    
    await interaction.response.send_message(embed=initial_embed)
    response_msg = await interaction.original_response()
    
    async def pomo_timer_task():
        try:
            total_focus = 1500
            interval = 10
            
            for elapsed in range(0, total_focus, interval):
                await asyncio.sleep(interval)
                remaining = total_focus - (elapsed + interval)
                rem_min, rem_sec = divmod(remaining, 60)
                percent = min(round(((elapsed + interval) / total_focus) * 100), 100)
                
                updated_embed = discord.Embed(
                    title="⏱️ ポモドーロタイマー（集中フェーズ）",
                    description=f"{interaction.user.mention} さん、集中して作業に取り組みましょう！✍️",
                    color=0xe8a7a1
                )
                updated_embed.add_field(name="⏱️ 残り時間", value=f"`{rem_min:02d}:{rem_sec:02d}`", inline=True)
                updated_embed.add_field(name="📊 進捗", value=f"{make_progress_bar(percent)} ({percent}%)", inline=False)
                
                try:
                    await response_msg.edit(embed=updated_embed)
                except discord.NotFound:
                    return

            await change_user_nickname(interaction.user, "[💤休憩中]")

            finish_focus_embed = discord.Embed(
                title="☕ 集中終了！お疲れ様でした",
                description=f"{interaction.user.mention} さん、25分間の集中タイムが終了しました！🎉\n\n💤 **休憩フェーズ (5分間)** がスタートします。",
                color=0x4ab3e3
            )
            finish_focus_embed.add_field(name="⏱️ 残り時間", value="`05:00`", inline=True)
            finish_focus_embed.add_field(name="📊 進捗", value="⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ (0%)", inline=False)
            
            try:
                await response_msg.edit(finish_focus_embed)
                await interaction.channel.send(content=f"🔔 {interaction.user.mention} 集中フェーズが終了しました！休憩を取りましょう！")
            except discord.NotFound:
                pass

            total_break = 300
            for elapsed in range(0, total_break, interval):
                await asyncio.sleep(interval)
                remaining = total_break - (elapsed + interval)
                rem_min, rem_sec = divmod(remaining, 60)
                percent = min(round(((elapsed + interval) / total_break) * 100), 100)
                
                updated_embed = discord.Embed(
                    title="☕ ポモドーロタイマー（休憩フェーズ）",
                    description=f"{interaction.user.mention} さん、目を休めたり、ストレッチをしましょう！💤",
                    color=0x4ab3e3
                )
                updated_embed.add_field(name="⏱️ 残り時間", value=f"`{rem_min:02d}:{rem_sec:02d}`", inline=True)
                updated_embed.add_field(name="📊 進捗", value=f"{make_progress_bar(percent)} ({percent}%)", inline=False)
                
                try:
                    await response_msg.edit(updated_embed)
                except discord.NotFound:
                    return

            await change_user_nickname(interaction.user, None)

            all_done_embed = discord.Embed(
                title="🔔 ポモドーロ完了！",
                description=f"{interaction.user.mention} さん、1サイクル（30分）がすべて終了しました！✨\n\n次のサイクルに進むか、一度しっかり休憩をとってくださいね。",
                color=0xff9966
            )
            try:
                await response_msg.edit(all_done_embed)
                await interaction.channel.send(content=f"⏰ {interaction.user.mention} 休憩フェーズが終了しました！お疲れ様でした！")
            except discord.NotFound:
                pass
                
        except asyncio.CancelledError:
            await change_user_nickname(interaction.user, None)
            cancel_embed = discord.Embed(
                title="⏹️ タイマー停止",
                description=f"{interaction.user.mention} さんのポモドーロタイマーは強制停止されました。",
                color=0x666666
            )
            try:
                await response_msg.edit(cancel_embed)
            except discord.NotFound:
                pass
        finally:
            active_pomo_timers.pop(user_id, None)

    task = bot.loop.create_task(pomo_timer_task())
    active_pomo_timers[user_id] = {
        "task": task,
        "message": response_msg,
        "original_nick": original_nick
    }

@bot.tree.command(name="pomo_stop", description="現在実行中のポモドーロタイマーを強制終了します")
async def pomo_stop(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id not in active_pomo_timers:
        await interaction.response.send_message("❌ 現在実行中のポモドーロタイマーはありません。", ephemeral=True)
        return
        
    pomo_info = active_pomo_timers.pop(user_id)
    pomo_info["task"].cancel()
    await interaction.response.send_message("⏹️ ポモドーロタイマーを停止させました。ゆっくり体を休めてくださいね！")

# ==========================================
# 🌐 Flask Webサイト 側の設定 (デザイン・グラフ強化)
# ==========================================
app = Flask(__name__)
app.secret_key = 'chillzone_secret_key_look_at_me'
quiz_sessions = {}

# デザインを大幅リファインした新テンプレート
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>𝖼𝗁𝗂𝗅𝗅 𝗓𝗈 . Official</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&family=Shippori+Mincho:wght@400;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { 
            --bg-color: #FAF6F0;       /* より柔らかいミルクホワイト */
            --main-color: #E8A7A1;     /* メインのくすみピンク */
            --sub-color: #4AB3E3;      /* アクセントの涼しいブルー */
            --text-color: #443F3F;     /* 優しいココアブラウン */
            --card-bg: #FFFFFF; 
            --accent-color: #F3ECE2;   /* さらに柔らかいベージュ */
            --shadow-smooth: 0 12px 40px rgba(180, 165, 150, 0.08); /* 滑らかな陰影 */
        }
        
        * { box-sizing: border-box; }
        
        body { 
            font-family: 'Noto Sans JP', sans-serif; 
            background-color: var(--bg-color); 
            color: var(--text-color); 
            margin: 0; 
            padding: 0; 
            display: flex; 
            flex-direction: column; 
            align-items: center; 
            min-height: 100vh;
        }
        
        header { 
            margin-top: 60px; 
            text-align: center; 
            padding: 0 20px;
        }
        
        header h1 { 
            font-family: 'Shippori Mincho', serif;
            font-size: 3.5rem; 
            margin: 0; 
            letter-spacing: 0.18em; 
            color: var(--text-color); 
            font-weight: 700;
        }
        
        .subtitle { 
            font-size: 1.05rem; 
            color: #A39696; 
            letter-spacing: 0.08em; 
            margin-top: 8px;
            font-weight: 400;
        }
        
        /* タブメニューデザイン */
        .tab-menu { 
            display: flex; 
            background-color: #EFEBE4; 
            padding: 6px; 
            border-radius: 40px; 
            margin: 40px 0; 
            flex-wrap: wrap; 
            justify-content: center;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.02);
        }
        
        .tab-btn { 
            font-family: 'Noto Sans JP', sans-serif; 
            background: none; 
            border: none; 
            padding: 12px 28px; 
            font-size: 0.95rem; 
            cursor: pointer; 
            color: var(--text-color); 
            border-radius: 30px; 
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1); 
            font-weight: 500;
            letter-spacing: 0.03em;
        }
        
        .tab-btn.active { 
            background-color: var(--main-color); 
            color: white; 
            font-weight: 700;
            box-shadow: 0 4px 15px rgba(232, 167, 161, 0.4);
        }
        
        .container { 
            width: 90%; 
            max-width: 850px; 
            margin-bottom: 80px; 
        }
        
        /* メインコンテンツカード */
        .tab-content { 
            display: none; 
            background-color: var(--card-bg); 
            padding: 50px; 
            border-radius: 36px; 
            box-shadow: var(--shadow-smooth); 
            line-height: 2.0; 
            border: 1px solid rgba(255, 255, 255, 0.6);
        }
        
        .tab-content.active { 
            display: block; 
            animation: cubic-bezier(0.16, 1, 0.3, 1) 0.6s forwards showUp; 
        }
        
        @keyframes showUp {
            from { opacity: 0; transform: translateY(15px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        h2 { 
            font-family: 'Shippori Mincho', serif;
            font-size: 1.8rem; 
            border-bottom: 2px solid var(--accent-color); 
            padding-bottom: 12px; 
            margin-top: 0; 
            margin-bottom: 30px; 
            color: #3C3535;
            letter-spacing: 0.05em;
        }
        
        h3 { 
            font-family: 'Shippori Mincho', serif;
            font-size: 1.35rem; 
            color: var(--main-color); 
            margin-top: 35px; 
            margin-bottom: 15px; 
            letter-spacing: 0.05em;
        }
        
        p { 
            margin: 18px 0; 
            font-size: 1.05rem; 
            text-align: justify; 
            color: #5C5555;
        }
        
        ul, ol { padding-left: 24px; color: #5C5555; }
        li { margin-bottom: 15px; font-size: 1.02rem; }
        
        /* グリッドレイアウト */
        .feature-grid { 
            display: grid; 
            grid-template-columns: 1fr 1fr; 
            gap: 25px; 
            margin-top: 30px; 
        }
        
        .feature-card { 
            background-color: #FDFCFB; 
            padding: 25px; 
            border-radius: 24px; 
            border: 1px solid #F5EFE6; 
            transition: all 0.3s ease;
        }
        
        .feature-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px rgba(220, 200, 190, 0.15);
            border-color: var(--main-color);
        }
        
        .feature-card strong { 
            color: var(--main-color); 
            font-size: 1.15rem; 
            font-family: 'Shippori Mincho', serif;
        }
        
        /* グラフ＆統計ボードデザイン */
        .stats-dashboard {
            display: flex;
            align-items: center;
            justify-content: space-around;
            flex-wrap: wrap;
            gap: 30px;
            background-color: #FDFCFB;
            padding: 30px;
            border-radius: 28px;
            border: 1px solid #F5EFE6;
            margin-top: 30px;
        }
        
        .chart-box {
            width: 280px;
            height: 280px;
            position: relative;
        }
        
        .stats-summary {
            flex: 1;
            min-width: 250px;
        }
        
        .stat-item {
            margin-bottom: 20px;
        }
        
        .stat-number {
            font-size: 2.2rem;
            font-weight: 700;
            color: var(--main-color);
            font-family: 'Shippori Mincho', serif;
        }
        
        /* コマンドカード */
        .cmd-box {
            background-color: #FAF8F5;
            border-radius: 20px;
            padding: 20px;
            margin-bottom: 20px;
            border-left: 5px solid var(--main-color);
            transition: all 0.2s ease;
        }
        
        .cmd-box:hover {
            background-color: #FFF;
            box-shadow: 0 5px 15px rgba(0,0,0,0.03);
            transform: translateX(5px);
        }
        
        .cmd-title {
            font-family: monospace;
            font-size: 1.1rem;
            font-weight: 700;
            color: #3C3535;
        }
        
        .cmd-desc {
            font-size: 0.95rem;
            color: #726A6A;
            margin: 5px 0 0 0;
            line-height: 1.6;
        }
        
        /* クイズ・認証用 */
        .quiz-container { 
            background: #FFFBFB; 
            padding: 40px; 
            border-radius: 28px; 
            margin-top: 30px; 
            text-align: center; 
            border: 2px dashed var(--main-color); 
        }
        
        .quiz-input { 
            font-family: monospace; 
            font-size: 1.8rem; 
            padding: 10px; 
            width: 130px; 
            text-align: center; 
            border-radius: 16px; 
            border: 2px solid var(--main-color); 
            outline: none; 
            margin-bottom: 20px; 
            color: var(--text-color);
            background-color: #FFF;
        }
        
        .btn-submit { 
            display: inline-block; 
            margin-top: 10px; 
            background-color: var(--main-color); 
            color: white; 
            border: none; 
            padding: 14px 45px; 
            border-radius: 30px; 
            cursor: pointer; 
            font-family: 'Noto Sans JP', sans-serif; 
            font-weight: 700; 
            font-size: 1rem; 
            box-shadow: 0 5px 15px rgba(232, 167, 161, 0.3);
            transition: all 0.3s ease;
        }
        
        .btn-submit:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(232, 167, 161, 0.4);
        }
        
        /* FAQアコーディオン風 */
        .faq-card {
            background-color: #FAF8F5;
            padding: 25px;
            border-radius: 20px;
            margin-bottom: 20px;
            border: 1px solid #EFECE6;
        }
        
        .faq-q {
            font-weight: 700;
            font-size: 1.1rem;
            color: var(--text-color);
            margin: 0 0 8px 0;
            display: flex;
            align-items: center;
        }
        
        .faq-q::before {
            content: "Q.";
            color: var(--main-color);
            font-size: 1.4rem;
            margin-right: 10px;
            font-family: 'Shippori Mincho', serif;
        }
        
        .faq-a {
            font-size: 1rem;
            color: #6E6666;
            margin: 0;
            line-height: 1.8;
        }

        /* レスポンシブ対応 */
        @media (max-width: 768px) {
            .feature-grid { grid-template-columns: 1fr; }
            .stats-dashboard { flex-direction: column; text-align: center; }
            header h1 { font-size: 2.6rem; }
            .tab-content { padding: 30px 20px; }
        }
    </style>
</head>
<body>
    <header>
        <h1>𝖼𝗁𝗂𝗅𝗅 𝗓𝗈 .</h1>
        <p class="subtitle">中高生・受験生のための、ゆるやかオンライン自習室</p>
    </header>
    <div class="tab-menu">
        <button class="tab-btn active" onclick="openTab('home')">コンセプト</button>
        <button class="tab-btn" onclick="openTab('stats')">サーバー統計＆グラフ</button>
        <button class="tab-btn" onclick="openTab('rules')">利用規約</button>
        <button class="tab-btn" onclick="openTab('commands')">コマンド解説</button>
        <button class="tab-btn" onclick="openTab('faq')">よくある質問</button>
        <button class="tab-btn" id="verify-tab-nav" onclick="openTab('verify')">アカウント認証</button>
    </div>
    <div class="container">
        <div id="home" class="tab-content active">
            <h2>ようこそ、ひと息つける、あなたの作業場へ。</h2>
            <p>「𝖼𝗁𝗂𝗅𝗅 𝗓𝗈 .」は、日々の勉強や創作、日課 of 作業など、それぞれの目標に向かって進む人たちのための、静かで温かいオンライン自習室です。</p>
            <p>1人だとなかなか集中が続かない、だけど誰かと賑やかに話しながらだと手が止まってしまう。そんな中高生や受験生の皆さんが、お互いの静かな気配を感じながら、適度な距離感でモチベーションを維持できる場所を目指しています。</p>
            <h3>🌱 空間のこだわり</h3>
            <div class="feature-grid">
                <div class="feature-card">
                    <p><strong>🕒 自分のペースで、着実に</strong></p>
                    <p style="font-size:0.95rem; line-height:1.7;">ボイスチャンネルに接続するだけで、Botがあなたの作業時間を1分単位で自動的に記録・計測します。日々の努力の積み重ねがレベルという形で可視化されます。</p>
                </div>
                <div class="feature-card">
                    <p><strong>🚪 集中を邪魔しない個室制度</strong></p>
                    <p style="font-size:0.95rem; line-height:1.7;">ボタン1つで「自分専用の作業VC（カフェルーム）」を設置できます。不要になったら自動で消滅するため、面倒な設定や誰かとバッティングする心配もありません。</p>
                </div>
            </div>
        </div>

        <div id="stats" class="tab-content">
            <h2>📈 サーバー統計 ＆ 頑張り屋割合</h2>
            <p>サーバー全体の累積データと、現在上位のメンバーによる作業時間の割合グラフです！一緒にモチベーションを共有して、みんなで高め合いましょう。🔥</p>
            
            <div class="stats-dashboard">
                <div class="stats-summary">
                    <div class="stat-item">
                        <div style="font-size:0.9rem; color:#888;">登録されている作業メンバー数</div>
                        <div class="stat-number">{{ total_users }} <span style="font-size:1.1rem; color:#555;">人</span></div>
                    </div>
                    <div class="stat-item">
                        <div style="font-size:0.9rem; color:#888;">サーバー全体での総作業時間</div>
                        <div class="stat-number">{{ total_minutes }} <span style="font-size:1.1rem; color:#555;">分</span></div>
                    </div>
                </div>
                <div class="chart-box">
                    <canvas id="timeRatioChart"></canvas>
                </div>
            </div>
        </div>

        <div id="rules" class="tab-content">
            <h2>📜 コミュニティ・ガイドライン（利用規約）</h2>
            <p>すべてのメンバーが心地よく、安心して勉強や作業に集中できるよう、以下のルールを定めています。</p>
            <h3>第1条（基本の心がけ）</h3>
            <p>お互いに高め合いながら作業を行う場所です。他人の勉強や集中を妨げる行為、相手を不快にさせる言葉遣いは慎み、常に思いやりを持って行動してください。</p>
            <h3>第2条（禁止事項）</h3>
            <ul>
                <li><strong>スパムおよび荒らし行為：</strong> 同一または類似するテキストの連投、ボイスチャンネルへの執拗な出入り、Botへの過剰負荷。</li>
                <li><strong>他者への迷惑行為：</strong> 勉強中のユーザーに対する無理な雑談の強要、マイクを通じた不快な生活音・雑音の垂れ流し。</li>
                <li><strong>安全を脅かす行為：</strong> 個人情報（本名、学校名、住所等）の公開や聞き出し、他者への誹謗中傷。</li>
            </ul>
        </div>

        <div id="commands" class="tab-content">
            <h2>⌨️ 搭載機能＆コマンドガイド</h2>
            <p>Discordサーバー内で、いつでも以下のスラッシュコマンドを実行してスタッツ確認やタイマー操作を行えます。</p>
            
            <div class="cmd-box">
                <div class="cmd-title">/status</div>
                <p class="cmd-desc">本日の勉強目標への％進捗バー、現在のレベル、そして【🔥連続自習継続日数】と【📊直近1週間の作業グラフ】を表示します。</p>
            </div>
            <div class="cmd-box">
                <div class="cmd-title">/goal [分]</div>
                <p class="cmd-desc">今日の作業目標時間を分単位で設定します。設定した内容は `/status` にリアルタイムに反映されます。</p>
            </div>
            <div class="cmd-box">
                <div class="cmd-title">/pomodoro</div>
                <p class="cmd-desc">25分集中＆5分休憩タイマーを作動させます。ニックネームに自動で [✍️集中中] 等のタグが付与されます。</p>
            </div>
            <div class="cmd-box">
                <div class="cmd-title">/pomo_stop</div>
                <p class="cmd-desc">現在作動しているポモドーロタイマーを終了させ、ニックネームを元の名前に戻します。</p>
            </div>
            <div class="cmd-box">
                <div class="cmd-title">/ranking</div>
                <p class="cmd-desc">サーバー内で作業時間が長いユーザー上位10名を表示します。</p>
            </div>
            <div class="cmd-box">
                <div class="cmd-title">/bump</div>
                <p class="cmd-desc">BUMPを実行したタイミングでセットすると、2時間後にBotがお知らせを送信します。</p>
            </div>
            <div class="cmd-box">
                <div class="cmd-title">/addword [トリガー] [返答]</div>
                <p class="cmd-desc">特定の言葉にBotが自動でメッセージを返すよう、言葉のペアを登録します。</p>
            </div>
            <div class="cmd-box">
                <div class="cmd-title">/worda</div>
                <p class="cmd-desc">現在登録されている自動返答ワードの一覧をカード形式で一覧表示します。</p>
            </div>
            <div class="cmd-box">
                <div class="cmd-title">/report [理由] [対象ユーザー(任意)]</div>
                <p class="cmd-desc">不具合や荒らし行為を管理者のDMに瞬時に通報します。</p>
            </div>
        </div>

        <div id="faq" class="tab-content">
            <h2>❓ よくある質問（FAQ）</h2>
            <div class="faq-card">
                <p class="faq-q">ボイスチャンネルに入っても作業時間が記録されません。</p>
                <p class="faq-a">接続から切断までの差分を計測しています。1分未満の短い接続はカウント対象外となります。</p>
            </div>
            <div class="faq-card">
                <p class="faq-q">カフェルーム（個室）は自動で消えますか？</p>
                <p class="faq-a">はい、全員が退出して0人になると自動消滅します。また、作成から24時間が経過した場合も安全のため自動で消去されます。</p>
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
        
        // --- 📊 円グラフの描画システム (Chart.js) ---
        const ctx = document.getElementById('timeRatioChart').getContext('2d');
        
        // サーバーから渡されたデータをJavaScriptに変換
        const chartLabels = {{ chart_labels | tojson }};
        const chartData = {{ chart_data | tojson }};
        
        const timeRatioChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: chartLabels,
                datasets: [{
                    data: chartData,
                    backgroundColor: [
                        '#E8A7A1', // くすみピンク
                        '#4AB3E3', // ライトブルー
                        '#EBD3C8', // ミルクティーベージュ
                        '#A2D2FF', // パステルブルー
                        '#D8B4F8', // ラベンダー
                        '#E2DFD8'  // その他
                    ],
                    borderWidth: 2,
                    borderColor: '#FFFFFF'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            font: {
                                family: 'Noto Sans JP',
                                size: 11
                            },
                            color: '#443F3F',
                            boxWidth: 12
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return ` ${context.label}: ${context.raw} 分`;
                            }
                        }
                    }
                },
                cutout: '65%' // 中央の穴のサイズ（ドーナツ型）
            }
        });
    </script>
</body>
</html>
"""

# ランキングデータなどからグラフ用データを抽出する補助関数
def get_chart_data():
    stats = load_stats()
    if not stats:
        return ["登録なし"], [100]
        
    # 総時間を計算しつつ降順ソート
    sorted_users = sorted(stats.items(), key=lambda x: x[1].get("total_minutes", 0.0), reverse=True)
    
    labels = []
    data_values = []
    
    # 上位5名分
    top_5 = sorted_users[:5]
    for uid, udata in top_5:
        total_m = udata.get("total_minutes", 0.0)
        if total_m > 0:
            labels.append(udata.get("username", "不明なユーザー"))
            data_values.append(round(total_m, 1))
            
    # 6位以下のメンバーを「その他」に合算
    other_minutes = sum(udata.get("total_minutes", 0.0) for uid, udata in sorted_users[5:])
    if other_minutes > 0:
        labels.append("その他")
        data_values.append(round(other_minutes, 1))
        
    if not labels:
        return ["記録なし"], [1]
        
    return labels, data_values

@app.route('/')
def index():
    stats = load_stats()
    total_users = len(stats)
    total_minutes = round(sum(data.get("total_minutes", 0.0) for data in stats.values()), 1)
    
    labels, data_vals = get_chart_data()
    
    return render_template_string(
        HTML_TEMPLATE, 
        username="ゲスト", 
        user_id="HOME", 
        num1=0, 
        num2=0, 
        msg="Discordの認証パネルのボタンからアクセスすると、ここに計算クイズが表示されます。",
        total_users=total_users,
        total_minutes=total_minutes,
        chart_labels=labels,
        chart_data=data_vals
    )

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
        'User-Agent': 'Mozilla/5.0'
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
        
    stats = load_stats()
    total_users = len(stats)
    total_minutes = round(sum(data.get("total_minutes", 0.0) for data in stats.values()), 1)
    labels, data_vals = get_chart_data()

    if r is None or r.status_code != 200:
        return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="HOME", num1=0, num2=0, msg="⚠️ 現在Discord側で一時的なアクセス規制が発生しています。5分ほど待ってやり直してください。", msg_color="red", total_users=total_users, total_minutes=total_minutes, chart_labels=labels, chart_data=data_vals)
    try:
        access_token = r.json().get('access_token')
    except:
        return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="HOME", num1=0, num2=0, msg="認証データの解析に失敗しました。", msg_color="red", total_users=total_users, total_minutes=total_minutes, chart_labels=labels, chart_data=data_vals)
    if not access_token:
        return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="HOME", num1=0, num2=0, msg="トークンが空です。", msg_color="red", total_users=total_users, total_minutes=total_minutes, chart_labels=labels, chart_data=data_vals)
    
    user_headers = {'Authorization': f'Bearer {access_token}', 'User-Agent': 'Mozilla/5.0'}
    user_r = requests.get('https://discord.com/api/users/@me', headers=user_headers).json()
    discord_id, discord_username = user_r.get('id'), user_r.get('username')
    n1, n2 = random.randint(1, 20), random.randint(1, 20)
    if discord_id:
        quiz_sessions[str(discord_id)] = { 'correct_answer': n1 + n2, 'username': discord_username, 'num1': n1, 'num2': n2 }
    return render_template_string(HTML_TEMPLATE, username=discord_username, user_id=discord_id, num1=n1, num2=n2, msg=None, total_users=total_users, total_minutes=total_minutes, chart_labels=labels, chart_data=data_vals)

@app.route('/submit-quiz', methods=['POST'])
def submit_quiz():
    user_id = request.form.get('user_id')
    user_answer = request.form.get('answer')
    session_data = quiz_sessions.get(str(user_id))
    
    stats = load_stats()
    total_users = len(stats)
    total_minutes = round(sum(data.get("total_minutes", 0.0) for data in stats.values()), 1)
    labels, data_vals = get_chart_data()

    if not session_data:
        return render_template_string(HTML_TEMPLATE, username="エラー", user_id=user_id, num1=0, num2=0, msg="タイムアウトしました。", msg_color="red", total_users=total_users, total_minutes=total_minutes, chart_labels=labels, chart_data=data_vals)
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
                            return render_template_string(HTML_TEMPLATE, username="認証完了", user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg="✨ 正解です！認証が完了し、ロールが付与されました！", msg_color="green", total_users=total_users, total_minutes=total_minutes, chart_labels=labels, chart_data=data_vals)
                except Exception as e:
                    return render_template_string(HTML_TEMPLATE, username="エラー", user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg=f"❌ 失敗: {e}", msg_color="red", total_users=total_users, total_minutes=total_minutes, chart_labels=labels, chart_data=data_vals)
    except ValueError:
        pass
    return render_template_string(HTML_TEMPLATE, username=session_data['username'], user_id=user_id, num1=session_data['num1'], num2=session_data['num2'], msg="❌ 答えが違います。", msg_color="red", total_users=total_users, total_minutes=total_minutes, chart_labels=labels, chart_data=data_vals)

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    t = threading.Thread(target=run_flask)
    t.start()
    bot.run(TOKEN)
