import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import random
import sqlite3
import config 

# =====================
# 1. DATABASE INITIALIZATION
# =====================
def init_db():
    with sqlite3.connect(config.DATABASE) as conn:
        cursor = conn.cursor()
        # Tabel User: Data utama player
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
        # Tabel Inventory: Menyimpan item (potion, candy, dll)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id TEXT, item_name TEXT, quantity INTEGER,
            PRIMARY KEY (user_id, item_name)
        )
        """)
        # Tabel Pokedex: Mencatat koleksi pokemon
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pokedex (
            user_id TEXT, pokemon_name TEXT,
            PRIMARY KEY (user_id, pokemon_name)
        )
        """)
        # Tabel Global Vars: Untuk Raid Boss HP
        cursor.execute("CREATE TABLE IF NOT EXISTS global_vars (var_name TEXT PRIMARY KEY, val INTEGER)")
        cursor.execute("INSERT OR IGNORE INTO global_vars VALUES ('raid_hp', 5000)")
        conn.commit()

init_db()

# =====================
# 2. GAME DATA & CONSTANTS
# =====================
POKEMON_DB = {
    "caterpie": {"hp": 40, "atk": 5, "emoji": "🐛", "color": 0x2ecc71},
    "weedle": {"hp": 40, "atk": 6, "emoji": "🐛", "color": 0x2ecc71},
    "pikachu": {"hp": 80, "atk": 15, "emoji": "⚡", "color": 0xf1c40f},
    "geodude": {"hp": 100, "atk": 12, "emoji": "🪨", "color": 0x95a5a6},
    "zubat": {"hp": 50, "atk": 10, "emoji": "🦇", "color": 0x9b59b6},
    "magikarp": {"hp": 30, "atk": 2, "emoji": "🐟", "color": 0x3498db},
    "bulbasaur": {"hp": 110, "atk": 18, "emoji": "🍃", "color": 0x2ecc71},
    "squirtle": {"hp": 115, "atk": 17, "emoji": "💧", "color": 0x3498db},
    "charmander": {"hp": 105, "atk": 22, "emoji": "🔥", "color": 0xe67e22}
}

# Lokasi map dengan terrain visual dan peluang muncul (weight)
LOCATIONS = {
    "Viridian Forest": {
        "color": 0x2ecc71, "bg": "🌿🌳🌿", 
        "mobs": [("caterpie", 45), ("weedle", 45), ("pikachu", 10)] 
    },
    "Mt. Moon": {
        "color": 0x7f8c8d, "bg": "🧱🌑🧱", 
        "mobs": [("geodude", 60), ("zubat", 40)]
    },
    "Sea Route": {
        "color": 0x3498db, "bg": "🌊🌊🌊", 
        "mobs": [("magikarp", 90), ("pikachu", 10)]
    }
}

SHOP_ITEMS = {
    "potion": {"price": 75, "desc": "Pulihkan HP saat battle (+40 HP)."},
    "energy_drink": {"price": 100, "desc": "Pulihkan +5 Energi (Max 10)."},
    "rare_candy": {"price": 500, "desc": "Naik 1 Level secara instan."}
}

# =====================
# 3. HELPER FUNCTIONS
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

def add_to_pokedex(uid, poke_name):
    with sqlite3.connect(config.DATABASE) as conn:
        conn.execute("INSERT OR IGNORE INTO pokedex VALUES (?, ?)", (str(uid), poke_name))

def check_level_up(uid):
    u = get_user(uid)
    xp_needed = u[4] * 100
    if u[3] >= xp_needed:
        update_user(uid, "level", u[4] + 1)
        update_user(uid, "xp", u[3] - xp_needed)
        return True
    return False

# =====================
# 4. UI COMPONENTS (SHOP & BATTLE)
# =====================
class BuyModal(Modal, title="🛒 PokeMart Purchase"):
    item_in = TextInput(label="Nama Item", placeholder="Contoh: potion")
    qty_in = TextInput(label="Jumlah", default="1")

    async def on_submit(self, interaction: discord.Interaction):
        item = self.item_in.value.lower().strip().replace(" ", "_")
        if item not in SHOP_ITEMS:
            return await interaction.response.send_message("❌ Item tidak tersedia!", ephemeral=True)
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
        with sqlite3.connect(config.DATABASE) as conn:
            conn.execute("INSERT INTO inventory VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET quantity = quantity + ?", (str(interaction.user.id), item, qty, qty))
        await interaction.response.send_message(f"✅ Berhasil membeli {qty}x **{item.replace('_',' ').capitalize()}**!", ephemeral=True)

class StarterSelection(View):
    def __init__(self, ctx):
        super().__init__(timeout=120)
        self.ctx = ctx

    async def choose_starter(self, interaction: discord.Interaction, pokemon: str):
        # Mencegah orang lain menekan tombol milikmu
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message("❌ Ini bukan menu milikmu!", ephemeral=True)
        
        uid = str(interaction.user.id)
        u = get_user(uid)
        
        # Validasi ganda jika mereka sudah punya starter
        if u[2] != "None":
            return await interaction.response.send_message("❌ Kamu sudah memilih starter sebelumnya!", ephemeral=True)

        # Update database
        update_user(uid, "starter", pokemon)
        add_to_pokedex(uid, pokemon)
        
        # Hapus tombol dan berikan pesan sukses
        await interaction.response.edit_message(
            content=f"🎊 Selamat! Kamu telah memilih **{pokemon.upper()}** sebagai partner pertamamu!",
            embed=None,
            view=None
        )

    @discord.ui.button(label="Bulbasaur", style=discord.ButtonStyle.success, emoji="🍃")
    async def btn_bulba(self, interaction: discord.Interaction, button: Button):
        await self.choose_starter(interaction, "bulbasaur")

    @discord.ui.button(label="Charmander", style=discord.ButtonStyle.danger, emoji="🔥")
    async def btn_char(self, interaction: discord.Interaction, button: Button):
        await self.choose_starter(interaction, "charmander")

    @discord.ui.button(label="Squirtle", style=discord.ButtonStyle.primary, emoji="💧")
    async def btn_squir(self, interaction: discord.Interaction, button: Button):
        await self.choose_starter(interaction, "squirtle")

    @discord.ui.button(label="Pikachu", style=discord.ButtonStyle.secondary, emoji="⚡")
    async def btn_pika(self, interaction: discord.Interaction, button: Button):
        await self.choose_starter(interaction, "pikachu")

class RaidView(View):
    def __init__(self, ctx, boss_max_hp):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.boss_max_hp = boss_max_hp

    def get_boss_hp(self):
        with sqlite3.connect(config.DATABASE) as conn:
            return conn.execute("SELECT val FROM global_vars WHERE var_name='raid_hp'").fetchone()[0]

    def make_embed(self, boss_hp, status="Siap menyerang Boss?"):
        emb = discord.Embed(title="🔥 WORLD RAID BOSS APPEARED", color=0xff0000)
        emb.description = f"**Status:** {status}"
        
        # Progress Bar Boss
        pct = max(0, int(boss_hp / self.boss_max_hp * 10))
        hp_bar = f"[{'🔴' * pct}{'⚪' * (10 - pct)}] {boss_hp}/{self.boss_max_hp} HP"
        emb.add_field(name="👹 Raid Boss Health", value=hp_bar, inline=False)
        emb.set_footer(text="Semua pemain bisa menyerang bersama-sama!")
        return emb

    @discord.ui.button(label="ATTACK BOSS!", style=discord.ButtonStyle.danger, emoji="💥")
    async def attack_button(self, interaction: discord.Interaction, button: Button):
        uid = str(interaction.user.id)
        u = get_user(uid)
        
        # Ambil HP terbaru dari DB
        current_hp = self.get_boss_hp()
        if current_hp <= 0:
            return await interaction.response.edit_message(content="🎊 Boss sudah kalah!", embed=None, view=None)

        # Hitung Damage Player
        base_dmg = random.randint(50, 120)
        bonus_dmg = u[4] * 10 # Level berpengaruh
        final_dmg = base_dmg + bonus_dmg
        
        # Boss Balas Serang (Visual/Logic)
        boss_dmg = random.randint(10, 30)
        
        # Update HP Boss di DB
        new_hp = max(0, current_hp - final_dmg)
        with sqlite3.connect(config.DATABASE) as conn:
            conn.execute("UPDATE global_vars SET val=? WHERE var_name='raid_hp'", (new_hp,))
        
        # Reward kecil per hit
        update_user(uid, "pokecoins", u[1] + 20)

        status_msg = f"**{interaction.user.name}** memberikan {final_dmg} DMG!\n👹 Boss membalas serangan sebesar {boss_dmg} DMG ke area!"
        
        if new_hp <= 0:
            update_user(uid, "pokecoins", u[1] + 1000) # Bonus Last Hit
            return await interaction.response.edit_message(content=f"🏆 **BOSS TUMBANG!** {interaction.user.name} memberikan serangan terakhir!", embed=None, view=None)

        await interaction.response.edit_message(embed=self.make_embed(new_hp, status_msg), view=self)

class BattleView(View):
    def __init__(self, ctx, p_stats, e_stats, e_data, loc_data):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.p_hp, self.p_max = p_stats['hp'], p_stats['hp']
        self.p_atk = p_stats['atk']
        self.e_hp, self.e_max = e_stats['hp'], e_stats['hp']
        self.e_atk = e_stats['atk']
        self.e_name, self.e_emoji = e_data['name'], e_data['emoji']
        self.loc_data = loc_data

    def make_embed(self, status="Giliranmu!"):
        emb = discord.Embed(title=f"⚔️ Battle: {self.loc_data['name']}", description=f"{self.loc_data['bg']}\n**{status}**", color=self.loc_data['color'])
        p_pct = max(0, int(self.p_hp/self.p_max*10))
        e_pct = max(0, int(self.e_hp/self.e_max*10))
        emb.add_field(name="🎒 Kamu (Trainer)", value=f"[{'█'*p_pct}{'░'*(10-p_pct)}] {self.p_hp}/{self.p_max} HP", inline=False)
        emb.add_field(name=f"{self.e_emoji} {self.e_name.upper()}", value=f"[{'█'*e_pct}{'░'*(10-e_pct)}] {self.e_hp}/{self.e_max} HP", inline=False)
        return emb

    @discord.ui.button(label="Fight", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def attack(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id != self.ctx.author.id: return
        
        dmg = random.randint(self.p_atk-3, self.p_atk+3)
        self.e_hp = max(0, self.e_hp - dmg)
        
        if self.e_hp <= 0:
            add_to_pokedex(self.ctx.author.id, self.e_name)
            rew, xp = random.randint(40, 80), random.randint(30, 50)
            u = get_user(self.ctx.author.id)
            update_user(self.ctx.author.id, "pokecoins", u[1] + rew)
            update_user(self.ctx.author.id, "xp", u[3] + xp)
            msg = f"🏆 **Menang!** +{rew} 💰 +{xp} XP\n📖 **{self.e_name.upper()}** tercatat di Pokedex!"
            if check_level_up(self.ctx.author.id): msg += "\n⭐ **LEVEL UP!**"
            return await interaction.response.edit_message(content=msg, embed=None, view=None)

        edmg = random.randint(self.e_atk-2, self.e_atk+2)
        self.p_hp = max(0, self.p_hp - edmg)
        if self.p_hp <= 0:
            return await interaction.response.edit_message(content="💀 Kamu pingsan! Bawa Pokemonmu ke PokeCenter.", embed=None, view=None)
        
        await interaction.response.edit_message(embed=self.make_embed(f"Kamu menyerang {dmg} DMG! Musuh membalas {edmg} DMG."), view=self)

    @discord.ui.button(label="Power Up", style=discord.ButtonStyle.success, emoji="💊")
    async def powerup(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id != self.ctx.author.id: return
        with sqlite3.connect(config.DATABASE) as conn:
            res = conn.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_name='potion'", (str(self.ctx.author.id),)).fetchone()
        
        if not res or res[0] <= 0:
            return await interaction.response.send_message("❌ Kamu tidak punya Potion!", ephemeral=True)
        
        self.p_hp = min(self.p_max, self.p_hp + 40)
        with sqlite3.connect(config.DATABASE) as conn:
            conn.execute("UPDATE inventory SET quantity = quantity - 1 WHERE user_id=? AND item_name='potion'", (str(self.ctx.author.id),))
        
        edmg = random.randint(self.e_atk, self.e_atk+2)
        self.p_hp = max(0, self.p_hp - edmg)
        await interaction.response.edit_message(embed=self.make_embed(f"💊 Pakai Potion (+40 HP)! Musuh tetap menyerang {edmg} DMG."), view=self)

    @discord.ui.button(label="Run", style=discord.ButtonStyle.secondary, emoji="🏃")
    async def run_away(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id != self.ctx.author.id: return
        # Peluang kabur 60%
        if random.random() < 0.6:
            await interaction.response.edit_message(content="💨 Berhasil kabur dengan selamat!", embed=None, view=None)
        else:
            edmg = random.randint(self.e_atk, self.e_atk+5)
            self.p_hp = max(0, self.p_hp - edmg)
            if self.p_hp <= 0:
                return await interaction.response.edit_message(content="💀 Gagal kabur dan pingsan!", embed=None, view=None)
            await interaction.response.edit_message(embed=self.make_embed("⚠️ Gagal kabur! Musuh menyerangmu saat lengah!"), view=self)

# =====================
# 5. BOT SETUP & EVENTS
# =====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

@bot.event
async def on_ready():
    print(f"Bot run as {bot.user}")

# =====================
# 6. COMMANDS
# =====================
@bot.command()
async def help(ctx):
    emb = discord.Embed(
        title="📜 PANDUAN LENGKAP TRAINER POKEMON MMO",
        description="Selamat datang di dunia Pokemon! Di sini kamu bisa bertarung, mengumpulkan koleksi, dan memperkuat Pokemonmu hingga level maksimal.",
        color=0x3498db
    )
    emb.add_field(
        name="🟢 MEMULAI & STATUS",
        value=(
            "`!start` : Langkah awal mendapatkan Pokemon partner secara acak.\n"
            "`!profile` : Lihat status Pokemon, Level, XP, dan sisa Energi kamu.\n"
            "`!bal` : Cek saldo Pokecoins kamu.\n"
            "`!inventory` : Lihat isi tas (Potion, Energy Drink, dll).\n"
            "`!pokedex` : Lihat daftar koleksi Pokemon yang sudah kamu kalahkan."
        ),
        inline=False
    )
    emb.add_field(
        name="⚔️ PETUALANGAN & PERTEMPURAN",
        value=(
            "`!hunt` : Cari Pokemon liar! Menang akan memberi **XP**, **Coins**, dan entri **Pokedex**.\n"
            "`!raid` : Serang Boss Global bersama-sama pemain lain di server ini."
        ),
        inline=False
    )
    emb.add_field(
        name="📈 PERTUMBUHAN & ITEM",
        value=(
            "`!train` : Latihan fisik (200 💰) untuk menambah **+20 HP** permanen.\n"
            "`!shop` : Buka PokeMart untuk membeli item pendukung.\n"
            "`!use <item>` : Gunakan item dari tas. Contoh: `!use rare_candy`."
        ),
        inline=False
    )
    emb.set_footer(text="Gunakan prefix '!' sebelum mengetik perintah.")
    await ctx.send(embed=emb)

@bot.command()
async def start(ctx):
    u = get_user(ctx.author.id)
    if u[2] != "None": 
        return await ctx.send("❌ Kamu sudah memiliki partner, petualanganmu sudah dimulai!")
    
    emb = discord.Embed(
        title="🌟 Pilih Pokemon Pertamamu!",
        description="Profesor telah menyiapkan 4 Pokemon untukmu. Tekan tombol di bawah untuk memilih partner yang akan menemani perjalananmu!",
        color=0xf1c40f
    )
    
    # Memanggil UI Menu yang baru kita buat
    view = StarterSelection(ctx)
    await ctx.send(embed=emb, view=view)

@bot.command()
async def profile(ctx):
    u = get_user(ctx.author.id)
    if u[2] == "None": return await ctx.send("❌ Gunakan `!start` dulu!")
    emb = discord.Embed(title=f"👤 Profil {ctx.author.name}", color=0x3498db)
    emb.add_field(name="Partner", value=u[2].upper(), inline=True)
    emb.add_field(name="Level", value=f"⭐ {u[4]} (XP: {u[3]}/{u[4]*100})", inline=True)
    emb.add_field(name="Energi", value=f"⚡ {u[5]}/10", inline=True)
    emb.add_field(name="Pokecoins", value=f"💰 {u[1]}", inline=True)
    emb.add_field(name="Bonus HP", value=f"💖 +{u[6]}", inline=True)
    await ctx.send(embed=emb)

@bot.command()
async def pokedex(ctx):
    with sqlite3.connect(config.DATABASE) as conn:
        res = conn.execute("SELECT pokemon_name FROM pokedex WHERE user_id=?", (str(ctx.author.id),)).fetchall()
    discovered = [r[0] for r in res]
    
    msg = ""
    for name, data in POKEMON_DB.items():
        status = f"✅ {data['emoji']} {name.capitalize()}" if name in discovered else f"❌ ????"
        msg += f"{status}\n"
    
    emb = discord.Embed(title=f"📖 Pokedex: {ctx.author.name}", description=f"Koleksi: {len(discovered)}/{len(POKEMON_DB)}\n\n{msg}", color=0xe74c3c)
    await ctx.send(embed=emb)

@bot.command()
async def bal(ctx):
    u = get_user(ctx.author.id)
    await ctx.send(f"💰 Saldo Pokecoins: **{u[1]}**")

@bot.command()
async def inventory(ctx):
    with sqlite3.connect(config.DATABASE) as conn:
        items = conn.execute("SELECT item_name, quantity FROM inventory WHERE user_id=?", (str(ctx.author.id),)).fetchall()
    msg = "\n".join([f"• **{n.replace('_',' ').capitalize()}**: {q}x" for n, q in items]) if items else "Tas kosong."
    await ctx.send(embed=discord.Embed(title="🎒 INVENTORY", description=msg, color=0x9b59b6))

@bot.command()
async def shop(ctx):
    emb = discord.Embed(title="🏪 POKEMART", color=0xf1c40f)
    for n, i in SHOP_ITEMS.items():
        emb.add_field(name=n.replace("_"," ").upper(), value=f"💰 {i['price']} | {i['desc']}", inline=False)
    view = View(); btn = Button(label="Beli Item", style=discord.ButtonStyle.success)
    btn.callback = lambda i: i.response.send_modal(BuyModal()); view.add_item(btn)
    await ctx.send(embed=emb, view=view)

@bot.command()
async def use(ctx, item_name: str):
    uid = str(ctx.author.id)
    item_name = item_name.lower().replace(" ", "_")
    with sqlite3.connect(config.DATABASE) as conn:
        res = conn.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_name=?", (uid, item_name)).fetchone()
    
    if not res or res[0] <= 0: return await ctx.send("❌ Kamu tidak punya item ini!")

    u = get_user(uid)
    if item_name == "energy_drink":
        new_en = min(10, u[5] + 5)
        update_user(uid, "energy", new_en)
        msg = f"⚡ Energi bertambah! Sekarang: **{new_en}/10**"
    elif item_name == "rare_candy":
        update_user(uid, "level", u[4] + 1)
        msg = f"🍬 Level naik ke **{u[4]+1}**!"
    elif item_name == "potion":
        msg = "💖 Pokemon kamu membaik! (Disarankan pakai ini via tombol di dalam pertempuran)."
    else: return await ctx.send("❌ Item ini tidak bisa digunakan di luar pertempuran.")

    with sqlite3.connect(config.DATABASE) as conn:
        conn.execute("UPDATE inventory SET quantity = quantity - 1 WHERE user_id=? AND item_name=?", (uid, item_name))
    await ctx.send(f"✅ Berhasil menggunakan **{item_name.replace('_',' ')}**!\n{msg}")

@bot.command()
async def train(ctx):
    u = get_user(ctx.author.id)
    if u[1] < 200: return await ctx.send("❌ Butuh 200 💰 untuk latihan!")
    update_user(ctx.author.id, "pokecoins", u[1] - 200)
    update_user(ctx.author.id, "bonus_hp", u[6] + 20)
    await ctx.send("🏋️ Latihan selesai! **HP +20** permanen!")

@bot.command()
async def hunt(ctx):
    u = get_user(ctx.author.id)
    if u[2] == "None": return await ctx.send("❌ Gunakan `!start` dulu!")
    if u[5] <= 0: return await ctx.send("🪫 Energi habis! Beli `energy_drink` di `!shop`.")

    loc_name = random.choice(list(LOCATIONS.keys()))
    loc = LOCATIONS[loc_name]; loc['name'] = loc_name
    
    mobs = [m[0] for m in loc['mobs']]
    weights = [m[1] for m in loc['mobs']]
    en_id = random.choices(mobs, weights=weights, k=1)[0]
    en_data = POKEMON_DB[en_id]; en_data['name'] = en_id

    p_base = POKEMON_DB.get(u[2])
    p_stats = {"hp": p_base['hp'] + (u[4]*15) + u[6], "atk": p_base['atk'] + (u[4]*3)}
    e_stats = {"hp": en_data['hp'] + (u[4]*5), "atk": en_data['atk'] + (u[4]*2)}

    update_user(ctx.author.id, "energy", u[5] - 1)
    view = BattleView(ctx, p_stats, e_stats, en_data, loc)
    await ctx.send(embed=view.make_embed(f"Wild {en_id.upper()} appeared!"), view=view)

@bot.command()
async def raid(ctx):
    # Pastikan data boss ada
    with sqlite3.connect(config.DATABASE) as conn:
        hp_boss = conn.execute("SELECT val FROM global_vars WHERE var_name='raid_hp'").fetchone()[0]

    if hp_boss <= 0:
        return await ctx.send("🎊 **Raid Boss telah dikalahkan!** Gunakan `!respawn_boss` (Admin) untuk memunculkan kembali.")

    # Tampilkan UI Raid
    view = RaidView(ctx, 5000) # 5000 adalah Max HP
    await ctx.send(embed=view.make_embed(hp_boss), view=view)

@bot.command()
@commands.has_permissions(administrator=True)
async def respawn_boss(ctx, hp: int = 5000):
    with sqlite3.connect(config.DATABASE) as conn:
        conn.execute("UPDATE global_vars SET val=? WHERE var_name='raid_hp'", (hp,))
    await ctx.send(f"✅ **Raid Boss telah di-respawn** dengan {hp} HP!")

# =====================
# START BOT
# =====================
bot.run(config.TOKEN)