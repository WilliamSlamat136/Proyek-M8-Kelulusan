import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import random
import sqlite3
import config # Mengambil TOKEN dan nama DATABASE dari config.py

# =====================
# DATABASE INITIALIZATION
# =====================
def init_db():
    with sqlite3.connect(config.DATABASE) as conn:
        cursor = conn.cursor()
        # Tabel User: Data utama trainer
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            pokecoins INTEGER DEFAULT 500,
            starter TEXT DEFAULT 'None',
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            energy INTEGER DEFAULT 10,
            bonus_hp INTEGER DEFAULT 0
        )
        """)
        # Migrasi kolom bonus_hp untuk database lama
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN bonus_hp INTEGER DEFAULT 0")
        except:
            pass
            
        # Tabel Inventory: Menyimpan item player
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id TEXT,
            item_name TEXT,
            quantity INTEGER,
            PRIMARY KEY (user_id, item_name)
        )
        """)
        
        # Tabel Global: Untuk Raid Boss HP
        cursor.execute("CREATE TABLE IF NOT EXISTS global_vars (var_name TEXT PRIMARY KEY, val INTEGER)")
        cursor.execute("INSERT OR IGNORE INTO global_vars VALUES ('raid_hp', 5000)")
        conn.commit()

init_db()

# =====================
# GAME DATA & CONSTANTS
# =====================
POKEMON_DB = {
    "pikachu": {"hp": 100, "atk": 20, "emoji": "⚡"},
    "charizard": {"hp": 150, "atk": 35, "emoji": "🔥"},
    "bulbasaur": {"hp": 110, "atk": 18, "emoji": "🍃"},
    "squirtle": {"hp": 115, "atk": 17, "emoji": "💧"}
}

LOCATIONS = {
    "Viridian Forest": {"diff": 1, "mobs": ["caterpie", "weedle", "pikachu"]},
    "Mt. Moon": {"diff": 2, "mobs": ["geodude", "zubat"]},
    "Cerulean Cave": {"diff": 5, "mobs": ["mewtwo", "kadabra"]}
}

SHOP_ITEMS = {
    "potion": {"price": 75, "desc": "Memulihkan status kesehatan."},
    "energy_drink": {"price": 100, "desc": "Memulihkan +5 Energi (Max 10)."},
    "rare_candy": {"price": 500, "desc": "Menaikkan 1 Level secara instan."}
}

# =====================
# HELPERS
# =====================
def get_user(uid):
    with sqlite3.connect(config.DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id=?", (str(uid),))
        res = cursor.fetchone()
        if not res:
            cursor.execute("INSERT INTO users (user_id) VALUES (?)", (str(uid),))
            conn.commit()
            return get_user(uid)
        return res

def update_user(uid, field, val):
    with sqlite3.connect(config.DATABASE) as conn:
        conn.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (val, str(uid)))

def add_inv(uid, item, qty):
    with sqlite3.connect(config.DATABASE) as conn:
        conn.execute("""
            INSERT INTO inventory VALUES (?, ?, ?) 
            ON CONFLICT(user_id, item_name) DO UPDATE SET quantity = quantity + ?
        """, (str(uid), item, qty, qty))

def check_level_up(uid):
    u = get_user(uid)
    xp_now, lvl_now = u[3], u[4]
    xp_needed = lvl_now * 100
    if xp_now >= xp_needed:
        update_user(uid, "level", lvl_now + 1)
        update_user(uid, "xp", xp_now - xp_needed)
        return True
    return False

# =====================
# UI COMPONENTS
# =====================
class BuyModal(Modal, title="🛒 PokeMart Purchase"):
    item_in = TextInput(label="Nama Item", placeholder="Contoh: rare_candy")
    qty_in = TextInput(label="Jumlah", default="1")

    async def on_submit(self, interaction: discord.Interaction):
        item = self.item_in.value.lower().replace(" ", "_")
        if item not in SHOP_ITEMS:
            return await interaction.response.send_message("❌ Item tidak tersedia!", ephemeral=True)
        
        # Validasi Bug: Anti minus, nol, dan desimal
        try:
            qty = int(self.qty_in.value)
            if qty <= 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ Masukkan angka bulat positif!", ephemeral=True)

        u = get_user(interaction.user.id)
        cost = SHOP_ITEMS[item]["price"] * qty
        if u[1] < cost:
            return await interaction.response.send_message(f"💰 Koin tidak cukup! Butuh {cost}", ephemeral=True)
        
        update_user(interaction.user.id, "pokecoins", u[1] - cost)
        add_inv(interaction.user.id, item, qty)
        await interaction.response.send_message(f"✅ Berhasil membeli {qty}x **{item.replace('_',' ').capitalize()}**!", ephemeral=True)

class BattleView(View):
    def __init__(self, ctx, p_stats, e_stats, e_name):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.p_hp, self.p_max = p_stats['hp'], p_stats['hp']
        self.p_atk = p_stats['atk']
        self.e_hp, self.e_max = e_stats['hp'], e_stats['hp']
        self.e_atk = e_stats['atk']
        self.e_name = e_name

    def bar(self, cur, max_v):
        pct = max(0, int((cur/max_v)*10))
        return f"[{'█'*pct}{'░'*(10-pct)}] {cur}/{max_v}"

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def attack(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id != self.ctx.author.id: return
        
        # Player Turn
        dmg = random.randint(self.p_atk-5, self.p_atk+5)
        self.e_hp -= dmg
        
        if self.e_hp <= 0:
            rew, xp = random.randint(30, 60), random.randint(25, 50)
            u = get_user(self.ctx.author.id)
            update_user(self.ctx.author.id, "pokecoins", u[1] + rew)
            update_user(self.ctx.author.id, "xp", u[3] + xp)
            
            msg = f"🏆 **Menang!**\n💰 +{rew} Coins\n📈 +{xp} XP"
            if check_level_up(self.ctx.author.id):
                msg += "\n⭐ **LEVEL UP!** Pokemon kamu semakin kuat!"
            return await interaction.response.edit_message(content=msg, embed=None, view=None)

        # Enemy Turn
        edmg = random.randint(self.e_atk-2, self.e_atk+2)
        self.p_hp -= edmg
        if self.p_hp <= 0:
            return await interaction.response.edit_message(content="💀 Kamu kalah dan pingsan!", embed=None, view=None)
            
        emb = discord.Embed(title="⚔️ BATTLE", color=0xe74c3c)
        emb.add_field(name="🎒 Kamu", value=self.bar(self.p_hp, self.p_max), inline=False)
        emb.add_field(name=f"👾 {self.e_name.upper()}", value=self.bar(self.e_hp, self.e_max), inline=False)
        await interaction.response.edit_message(embed=emb, view=self)

# =====================
# BOT SETUP
# =====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help") # Hapus help default

@bot.event
async def on_ready():
    print(f"✅ Bot {bot.user} Siap Beraksi!")

# =====================
# COMMANDS
# =====================

@bot.command()
async def help(ctx):
    emb = discord.Embed(
        title="📜 PANDUAN LENGKAP TRAINER POKEMON MMO",
        description=(
            "Selamat datang di dunia Pokemon! Di sini kamu bisa bertarung, "
            "mengumpulkan koin, dan memperkuat Pokemonmu hingga level maksimal."
        ),
        color=0x3498db
    )

    # --- Bagian Dasar ---
    emb.add_field(
        name="🟢 MEMULAI PERJALANAN",
        value=(
            "`!start` : Langkah awal untuk mendapatkan Pokemon pertamamu secara acak.\n"
            "`!profile` : Lihat status Pokemon, Level, XP, dan sisa Energi kamu.\n"
            "`!bal` : Cek saldo Pokecoins kamu.\n"
            "`!inventory` : Intip isi tas untuk melihat item yang sudah dibeli."
        ),
        inline=False
    )

    # --- Bagian RPG ---
    emb.add_field(
        name="⚔️ PETUALANGAN & PERTEMPURAN",
        value=(
            "`!hunt` : Jelajahi wilayah liar untuk melawan musuh. Menang akan memberikan **XP** dan **Coins**. (Menggunakan 1 ⚡).\n"
            "`!raid` : Serang Boss Global bersama pemain lain di server. Damage kamu membantu mengurangi HP Boss Dunia!"
        ),
        inline=False
    )

    # --- Bagian Upgrade ---
    emb.add_field(
        name="📈 PERTUMBUHAN & ITEM",
        value=(
            "`!train` : Latihan fisik! Bayar **200 💰** untuk menambah **+20 HP** secara permanen.\n"
            "`!shop` : Buka PokeMart untuk membeli item pendukung.\n"
            "`!use <nama_item>` : Gunakan item dari tasmu. Contoh: `!use rare_candy` untuk naik level instan."
        ),
        inline=False
    )

    # --- Tips ---
    emb.add_field(
        name="💡 TIPS CEPAT",
        value=(
            "• Kehabisan Energi? Beli **energy_drink** di shop!\n"
            "• Ingin HP tebal? Sering-seringlah melakukan **!train**.\n"
            "• Setiap naik Level, Attack dan HP dasar kamu akan otomatis bertambah kuat."
        ),
        inline=False
    )

    emb.set_footer(text="Ketik perintah dengan prefix '!' di depannya.")
    await ctx.send(embed=emb)

@bot.command()
async def start(ctx):
    u = get_user(ctx.author.id)
    if u[2] != "None": return await ctx.send("❌ Kamu sudah punya Pokemon!")
    pick = random.choice(list(POKEMON_DB.keys()))
    update_user(ctx.author.id, "starter", pick)
    await ctx.send(f"🎊 Selamat datang! Kamu memulai dengan **{pick.upper()}**!")

@bot.command()
async def profile(ctx):
    u = get_user(ctx.author.id)
    if u[2] == "None": return await ctx.send("Gunakan `!start` dulu!")
    xp_req = u[4] * 100
    emb = discord.Embed(title=f"👤 Profil {ctx.author.name}", color=0x3498db)
    emb.add_field(name="Pokemon", value=f"{u[2].upper()} {POKEMON_DB.get(u[2], {}).get('emoji', '')}")
    emb.add_field(name="Level", value=f"⭐ {u[4]}")
    emb.add_field(name="XP", value=f"📈 {u[3]}/{xp_req}")
    emb.add_field(name="Pokecoins", value=f"💰 {u[1]}")
    emb.add_field(name="Energi", value=f"⚡ {u[5]}/10")
    emb.add_field(name="Bonus HP", value=f"💖 +{u[6]}")
    await ctx.send(embed=emb)

@bot.command()
async def inventory(ctx):
    with sqlite3.connect(config.DATABASE) as conn:
        items = conn.execute("SELECT item_name, quantity FROM inventory WHERE user_id=?", (str(ctx.author.id),)).fetchall()
    if not items: return await ctx.send("🎒 Tas kamu kosong!")
    msg = "\n".join([f"• **{n.replace('_',' ').capitalize()}**: {q}x" for n, q in items])
    await ctx.send(embed=discord.Embed(title="🎒 Tas Inventori", description=msg, color=0x9b59b6))

@bot.command()
async def shop(ctx):
    emb = discord.Embed(title="🏪 POKEMART", color=0xf1c40f)
    for n, i in SHOP_ITEMS.items():
        emb.add_field(name=n.replace("_"," ").upper(), value=f"💰 {i['price']}\n*{i['desc']}*", inline=False)
    view = View(); btn = Button(label="Beli Item", style=discord.ButtonStyle.success)
    btn.callback = lambda i: i.response.send_modal(BuyModal())
    view.add_item(btn)
    await ctx.send(embed=emb, view=view)

@bot.command()
async def hunt(ctx):
    u = get_user(ctx.author.id)
    if u[2] == "None": return await ctx.send("Gunakan `!start` dulu!")
    if u[5] <= 0: return await ctx.send("🪫 Energi habis! Gunakan `energy_drink`.")
    
    loc = random.choice(list(LOCATIONS.keys()))
    en = random.choice(LOCATIONS[loc]['mobs'])
    diff = LOCATIONS[loc]['diff']
    
    p_base = POKEMON_DB.get(u[2])
    p_stats = {"hp": p_base['hp'] + (u[4]*15) + u[6], "atk": p_base['atk'] + (u[4]*3)}
    e_stats = {"hp": (40*diff) + (u[4]*5), "atk": (8*diff) + (u[4]*2)}
    
    update_user(ctx.author.id, "energy", u[5] - 1)
    await ctx.send(f"📍 Menjelajahi {loc}...", view=BattleView(ctx, p_stats, e_stats, en))

@bot.command()
async def use(ctx, item_name: str):
    uid = str(ctx.author.id)
    item_name = item_name.lower().replace(" ", "_")
    with sqlite3.connect(config.DATABASE) as conn:
        res = conn.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_name=?", (uid, item_name)).fetchone()
    if not res or res[0] <= 0: return await ctx.send("❌ Kamu tidak punya item ini!")

    u = get_user(uid)
    msg = ""
    if item_name == "energy_drink":
        new_en = min(10, u[5] + 5)
        update_user(uid, "energy", new_en)
        msg = f"⚡ Energi bertambah! Sekarang: **{new_en}/10**"
    elif item_name == "rare_candy":
        update_user(uid, "level", u[4] + 1)
        msg = f"🍬 Level naik ke **{u[4]+1}**!"
    elif item_name == "potion":
        msg = "💖 Pokemon kamu pulih!"
    else: return await ctx.send("❌ Item tidak bisa digunakan langsung.")

    with sqlite3.connect(config.DATABASE) as conn:
        conn.execute("UPDATE inventory SET quantity = quantity - 1 WHERE user_id=? AND item_name=?", (uid, item_name))
    await ctx.send(f"✅ Berhasil menggunakan **{item_name}**!\n{msg}")

@bot.command()
async def train(ctx):
    u = get_user(ctx.author.id)
    if u[1] < 200: return await ctx.send("❌ Butuh 200 💰 untuk latihan HP!")
    update_user(ctx.author.id, "pokecoins", u[1] - 200)
    update_user(ctx.author.id, "bonus_hp", u[6] + 20)
    await ctx.send("🏋️ **Latihan Berhasil!** HP bertambah +20 permanen!")

@bot.command()
async def raid(ctx):
    with sqlite3.connect(config.DATABASE) as conn:
        hp = conn.execute("SELECT val FROM global_vars WHERE var_name='raid_hp'").fetchone()[0]
    if hp <= 0: return await ctx.send("🎊 Boss sudah dikalahkan! Tunggu respawn.")
    
    dmg = random.randint(50, 150)
    new_hp = max(0, hp - dmg)
    with sqlite3.connect(config.DATABASE) as conn:
        conn.execute("UPDATE global_vars SET val=? WHERE var_name='raid_hp'", (new_hp,))
    
    emb = discord.Embed(title="🔥 RAID BOSS", description=f"Player menyerang Boss!\n💥 DMG: {dmg}\n❤️ HP Boss: {new_hp}/5000", color=0x000000)
    await ctx.send(embed=emb)

@bot.command()
async def bal(ctx):
    u = get_user(ctx.author.id)
    await ctx.send(f"💰 Saldo Pokecoins kamu: **{u[1]}**")

bot.run(config.TOKEN)