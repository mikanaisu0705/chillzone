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

# 📢 【追加】お疲れ様メッセージを自動送信するテキストチャンネルのID
# ※お疲れ様通知を送りたいテキストチャンネルのIDに書き換えてください。
CONGRATS_CHANNEL_ID = 1526575335460573315 # デフォルトではサーバーのシステム等に合わせるか、適宜書き換えてください

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
bot = commands.Bot(command_prefix="/", intents=intents)

vc_start_times = {}
room_counter = 1      
active_rooms = {}     

active_bump_timers = {}
active_pomo_timers = {}

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

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    bot.add_view(PrivateRoomView()) 
    bot.loop.create_task(check_room_expiry()) 
    
    if not update_status_loop.is_running():
        update_status_loop.start()
        
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
    
    # 1. VCに参加した時刻を記録
    if before.channel is None and after.channel is not None:
        vc_start_times[user_id] = time.time()
        
    # 2. VCから退出（または完全に切断）した時の計算
    elif before.channel is not None and after.channel is None:
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
                    # 昨日やっていて、今日初めての勉強ならストリーク+1
                    if current_streak == 0:
                        user_data["streak"] = 1
                    else:
                        user_data["streak"] += 1
                elif last_active == today_str:
                    # すでに今日勉強している場合はストリーク維持
                    pass
                else:
                    # 昨日やっていなければストリークは1にリセット（初めての場合は1）
                    user_data["streak"] = 1
                
                user_data["last_active_date"] = today_str
                
                # レベルの再計算
                new_level, _ = calculate_level(int(user_data["total_minutes"]))
                user_data["level"] = new_level
                
                save_stats(stats)
                print(f"【記録】{member.name} が {minutes_earned} 分作業しました。（本日累計: {user_data['today_minutes']} 分）")
                
                # 🎉 【追加機能】お疲れ様お祝いメッセージの自動送信
                congrats_channel = bot.get_channel(CONGRATS_CHANNEL_ID)
                if congrats_channel:
                    goal_min = user_data.get("daily_goal", 0)
                    today_total = user_data["today_minutes"]
                    
                    # 目標を達成したかどうかの判定
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

# 📊 【大幅強化版】ステータス確認（1週間グラフ & ストリーク追加）
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
    
    # 連続自習ストリークのチェック（昨日・今日ともやっていなければ0日にリセット表示するロジック）
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    last_active = user_data.get("last_active_date", "")
    
    if last_active != today_str and last_active != yesterday_str:
        streak_days = 0
    else:
        streak_days = user_data.get("streak", 0)
        
    # 基本情報
    embed.add_field(name="👑 現在のレベル", value=f"**Lv. {current_level}**", inline=True)
    embed.add_field(name="🔥 連続自習記録", value=f"**{streak_days} 日連続**", inline=True)
    embed.add_field(name="⏱️ 累計作業時間", value=f"**{total_min} 分**", inline=True)
    embed.add_field(name="✨ 次のLvまであと", value=f"`{round(next_remain, 1)}` 分", inline=True)
    
    # 🎯 今日の目標進捗の表示
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
    
    # 📅 直近1週間の簡易グラフ（weekly_logから生成）
    weekly_log = user_data.get("weekly_log", {})
    graph_text = ""
    weekday_labels = ["月", "火", "水", "木", "金", "土", "日"]
    
    # 直近7日間の日付を取得
    today = datetime.now()
    for i in range(6, -1, -1):
        target_date = today - timedelta(days=i)
        date_key = target_date.strftime("%Y-%m-%d")
        wday_label = weekday_labels[target_date.weekday()]
        
        minutes_done = weekly_log.get(date_key, 0.0)
        
        # グラフ用の絵文字ゲージの数（例: 30分ごとに🟩1個、最大5個まで）
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
    
    embed = discord.Embed(title="📈 𝖼𝗁𝗂𝗅𝗅 𝗓𝗈𝗇 . サーバー統計", color=0x4ab3e3)
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
# ⏱️ ポモドーロタイマー（集中モード・ニックネーム連携）
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
                await response_msg.edit(embed=finish_focus_embed)
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
                    await response_msg.edit(embed=updated_embed)
                except discord.NotFound:
                    return

            await change_user_nickname(interaction.user, None)

            all_done_embed = discord.Embed(
                title="🔔 ポモドーロ完了！",
                description=f"{interaction.user.mention} さん、1サイクル（30分）がすべて終了しました！✨\n\n次のサイクルに進むか、一度しっかり休憩をとってくださいね。",
                color=0xff9966
            )
            try:
                await response_msg.edit(embed=all_done_embed)
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
                await response_msg.edit(embed=cancel_embed)
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
    <title>𝖼𝗁𝗂𝗅𝗅 𝗓𝗈 . Official</title>
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
        h3 { font-size: 1.25rem; color: var(--main-color); margin-top: 30px; margin-bottom: 10px; }
        p { margin: 15px 0; font-size: 1.05rem; text-align: justify; }
        ul, ol { padding-left: 20px; }
        li { margin-bottom: 12px; font-size: 1.02rem; }
        .feature-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 25px; }
        .feature-card { background-color: var(--bg-color); padding: 20px; border-radius: 18px; border: 1px solid rgba(0,0,0,0.03); }
        .feature-card strong { color: var(--main-color); font-size: 1.1rem; }
        .quiz-container { background: #fffafa; padding: 30px; border-radius: 20px; margin-top: 25px; text-align: center; border: 2px dashed var(--main-color); }
        .quiz-input { font-family: monospace; font-size: 1.4rem; padding: 8px; width: 100px; text-align: center; border-radius: 12px; border: 2px solid var(--accent-color); outline: none; margin-bottom: 15px; }
        .btn-submit { display: block; margin: 10px auto 0 auto; background-color: var(--main-color); color: white; border: none; padding: 12px 35px; border-radius: 25px; cursor: pointer; font-family: 'Shippori Mincho', serif; font-weight: bold; font-size: 1rem; }
        .code-block { background: #fdfaf6; padding: 20px; border-radius: 16px; border-left: 4px solid var(--main-color); font-family: monospace; font-size: 0.95rem; overflow-x: auto; line-height: 1.7; }
        .faq-item { margin-bottom: 25px; border-bottom: 1px dashed var(--accent-color); padding-bottom: 15px; }
        .faq-question { font-weight: bold; color: var(--text-color); font-size: 1.1rem; margin-bottom: 5px; }
        .faq-answer { color: #666; font-size: 1rem; }
    </style>
</head>
<body>
    <header>
        <h1>𝖼𝗁𝗂𝗅𝗅 𝗓𝗈 .</h1>
        <p class="subtitle">中高生・受験生のための、ゆるやかオンライン自習室</p>
    </header>
    <div class="tab-menu">
        <button class="tab-btn active" onclick="openTab('home')">コンセプト</button>
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
                    <p style="font-size:0.95rem; line-height:1.6;">ボイスチャンネルに接続するだけで、Botがあなたの作業時間を1分単位で自動的に記録・計測します。日々の努力の積み重ねがレベルという形で可視化されます。</p>
                </div>
                <div class="feature-card">
                    <p><strong>🚪 集中を邪魔しない個室制度</strong></p>
                    <p style="font-size:0.95rem; line-height:1.6;">ボタン1つで「自分専用の作業VC（カフェルーム）」を設置できます。不要になったら自動で消滅するため、面倒な設定や誰かとバッティングする心配もありません。</p>
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
            <div class="code-block">
                <strong>💡 /status （ステータス確認）</strong><br>
                ➔ 合計作業時間、現在のレベル、本日の学習目標進捗、さらに【🔥連続自習日数】と【📊直近1週間のグラフ】を表示します。<br><br>
                <strong>🎯 /goal [分] （本日の目標設定）</strong><br>
                ➔ 今日の勉強目標時間を設定します。目標に対する％ゲージが `/status` に反映されます。<br><br>
                <strong>🏆 /ranking （ランキング表示）</strong><br>
                ➔ 作業時間が長いユーザー上位10名を表示します。<br><br>
                <strong>🔔 /bump （バンプ通知タイマー）</strong><br>
                ➔ 2時間後に自動で「BUMPの時間だよ！」とお知らせします。<br><br>
                <strong>⏱️ /pomodoro （ポモドーロ開始）</strong><br>
                ➔ 25分集中＆5分休憩のタイマー。ニックネームに自動で `[✍️集中中]` などのタグが付与されます。<br><br>
                <strong>⏹️ /pomo_stop （ポモドーロ停止）</strong><br>
                ➔ 実行中のポモドーロタイマーを強制終了し、ニックネームを元の名前に戻します。<br><br>
                <strong>💬 /addword [言葉] [返答] （単語登録）</strong><br>
                ➔ チャットでその言葉が送信されたとき、Botが自動で反応してメッセージを返します。<br><br>
                <strong>💬 /worda （単語一覧）</strong><br>
                ➔ 現在登録されている自動返答ワードの一覧をカードで表示します。<br><br>
                <strong>🚨 /report [理由] [対象者(任意)] （管理者へ通報）</strong><br>
                ➔ 荒らし行為やバグなど、サーバーの管理者全員にDMで通報を送ることができます。<br><br>
                <strong>📊 /server_stats （サーバー統計）</strong><br>
                ➔ サーバー全体の登録人数や累計勉強時間を確認できます。<br><br>
                <strong>🎲 /dice （サイコロ）</strong><br>
                ➔ 息抜きや、勉強の目標ページを決める際にサイコロを振ることができます。
            </div>
        </div>
        <div id="faq" class="tab-content">
            <h2>❓ よくある質問（FAQ）</h2>
            <div class="faq-item">
                <p class="faq-question">Q. ボイスチャンネルに入っても作業時間が記録されません。</p>
                <p class="faq-answer">A. 接続から切断までの差分を計測しています。1分未満の短い接続は記録されません。</p>
            </div>
            <div class="faq-item">
                <p class="faq-question">Q. カフェルーム（個室）は自動で消えますか？</p>
                <p class="faq-answer">A. はい、全員が退出して0人になると自動消滅します。また、作成から24時間経過した部屋も自動で消去されます。</p>
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
    return render_template_string(HTML_TEMPLATE, username="ゲスト", user_id="HOME", num1=0, num2=0, msg="Discordの認証パネルのボタンからアクセスすると、ここに計算クイズが表示されます。")

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
