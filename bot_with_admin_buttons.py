# -*- coding: utf-8 -*-
import os, sqlite3
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = "party_bot.sqlite3"

def db():
    con=sqlite3.connect(DB_PATH); con.row_factory=sqlite3.Row; return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS tags(user_id INTEGER PRIMARY KEY,tag TEXT NOT NULL,display_name TEXT NOT NULL,updated_at TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS parties(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,channel_id INTEGER NOT NULL,message_id INTEGER,host_id INTEGER NOT NULL,host_name TEXT NOT NULL,tag TEXT NOT NULL,gems INTEGER NOT NULL,event_time TEXT NOT NULL,capacity INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS attendees(party_id INTEGER NOT NULL,user_id INTEGER NOT NULL,display_name TEXT NOT NULL,PRIMARY KEY(party_id,user_id))""")

def user_tag(uid):
    with db() as con: row=con.execute("SELECT tag FROM tags WHERE user_id=?",(uid,)).fetchone()
    return row["tag"] if row else None

def party_embed(pid):
    with db() as con:
        p=con.execute("SELECT * FROM parties WHERE id=?",(pid,)).fetchone()
        people=con.execute("SELECT display_name,user_id FROM attendees WHERE party_id=? ORDER BY rowid",(pid,)).fetchall()
    if not p: return None
    status="🟢 مفتوحة للتسجيل" if p["status"]=="open" else "🔴 مغلقة"
    e=discord.Embed(title=f"💎 حفلة {p['gems']} جوهرة",color=0x625BEE)
    e.add_field(name="👑 الهوست",value=f"<@{p['host_id']}>",inline=True)
    e.add_field(name="🏷️ التاق",value=p["tag"],inline=True)
    e.add_field(name="🗓️ الموعد",value=p["event_time"],inline=False)
    e.add_field(name="📌 الحالة",value=status,inline=True)
    e.add_field(name="🪑 الأماكن المتبقية",value=str(max(0,p["capacity"]-len(people))),inline=True)
    names="\n".join(f"{i}. {discord.utils.escape_markdown(x['display_name'])} · <@{x['user_id']}>" for i,x in enumerate(people,1))
    e.add_field(name=f"✅ المسجلون ({len(people)}/{p['capacity']})",value=names or "لا يوجد مسجلون بعد.",inline=False)
    e.set_footer(text=f"رقم الحفلة: {pid} • للتسجيل اضغط زر انضمام")
    return e

async def refresh_party(bot,pid):
    with db() as con: p=con.execute("SELECT channel_id,message_id FROM parties WHERE id=?",(pid,)).fetchone()
    if not p or not p["message_id"]: return
    ch=bot.get_channel(p["channel_id"])
    if not ch: return
    try:
        msg=await ch.fetch_message(p["message_id"])
        await msg.edit(embed=party_embed(pid),view=PartyView(pid))
    except (discord.NotFound,discord.Forbidden): pass

class TagModal(discord.ui.Modal,title="تسجيل التاق"):
    tag=discord.ui.TextInput(label="اكتب تاقك داخل اللعبة",placeholder="مثال: u6c8x",min_length=2,max_length=24)
    async def on_submit(self,interaction):
        val=str(self.tag).strip()
        with db() as con:
            con.execute("""INSERT INTO tags(user_id,tag,display_name,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET tag=excluded.tag,display_name=excluded.display_name,updated_at=excluded.updated_at""",
            (interaction.user.id,val,interaction.user.display_name,datetime.now(timezone.utc).isoformat()))
        await interaction.response.send_message(f"✅ تم تسجيل تاقك: **{discord.utils.escape_markdown(val)}**",ephemeral=True)

class TagPanel(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🏷️ سجّل تاقك",style=discord.ButtonStyle.success,custom_id="tag:register")
    async def register(self,interaction,button): await interaction.response.send_modal(TagModal())
    @discord.ui.button(label="📋 كل التاقات",style=discord.ButtonStyle.primary,custom_id="tag:list")
    async def list_tags(self,interaction,button):
        with db() as con: rows=con.execute("SELECT display_name,tag FROM tags ORDER BY display_name COLLATE NOCASE").fetchall()
        if not rows: msg="ما في تاقات مسجلة لحد الآن."
        else:
            msg="\n".join(f"• **{discord.utils.escape_markdown(r['display_name'])}** — `{r['tag']}`" for r in rows[:50])
            if len(rows)>50: msg+=f"\n… وغيرهم {len(rows)-50}."
        await interaction.response.send_message(msg,ephemeral=True)



def is_party_admin(interaction):
    return interaction.guild is not None and interaction.user.guild_permissions.manage_guild

class EditPartyModal(discord.ui.Modal, title="تعديل الحفلة"):
    gems = discord.ui.TextInput(label="الجواهر (200 أو 400 أو 600)", max_length=3)
    event_time = discord.ui.TextInput(label="الموعد", max_length=100)
    tag = discord.ui.TextInput(label="تاق الهوست", max_length=24)
    capacity = discord.ui.TextInput(label="السعة", max_length=3)

    def __init__(self, party_id):
        super().__init__()
        self.party_id = party_id
        with db() as con:
            p = con.execute("SELECT gems,event_time,tag,capacity FROM parties WHERE id=?", (party_id,)).fetchone()
        if p:
            self.gems.default = str(p["gems"])
            self.event_time.default = p["event_time"]
            self.tag.default = p["tag"]
            self.capacity.default = str(p["capacity"])

    async def on_submit(self, interaction):
        if not is_party_admin(interaction):
            return await interaction.response.send_message("هذا الزر للمشرفين فقط.", ephemeral=True)
        try:
            gems_value = int(str(self.gems.value).strip())
            capacity_value = int(str(self.capacity.value).strip())
            tag_value = str(self.tag.value).strip()
            time_value = str(self.event_time.value).strip()
            if gems_value not in (200, 400, 600) or not 1 <= capacity_value <= 99 or not tag_value or not time_value:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("تأكدي من البيانات: الجواهر 200 أو 400 أو 600، والسعة من 1 إلى 99.", ephemeral=True)
        with db() as con:
            con.execute("UPDATE parties SET gems=?,event_time=?,tag=?,capacity=? WHERE id=?",
                        (gems_value, time_value, tag_value, capacity_value, self.party_id))
        await interaction.response.send_message("تم تعديل الحفلة بنجاح. ✅", ephemeral=True)
        await refresh_party(interaction.client, self.party_id)

class ManageAttendeeModal(discord.ui.Modal):
    user_id = discord.ui.TextInput(label="معرّف العضو (User ID)", placeholder="مثال: 123456789012345678", min_length=17, max_length=20)

    def __init__(self, party_id, action):
        super().__init__(title="إضافة شخص للحفلة" if action == "add" else "حذف شخص من الحفلة")
        self.party_id = party_id
        self.action = action

    async def on_submit(self, interaction):
        if not is_party_admin(interaction):
            return await interaction.response.send_message("هذا الزر للمشرفين فقط.", ephemeral=True)
        try:
            uid = int(str(self.user_id.value).strip())
        except ValueError:
            return await interaction.response.send_message("معرّف العضو غير صحيح.", ephemeral=True)
        member = interaction.guild.get_member(uid)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(uid)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return await interaction.response.send_message("لم أجد هذا العضو في السيرفر.", ephemeral=True)
        with db() as con:
            p = con.execute("SELECT status,capacity FROM parties WHERE id=? AND guild_id=?",
                            (self.party_id, interaction.guild_id)).fetchone()
            if not p:
                return await interaction.response.send_message("لم يتم العثور على الحفلة.", ephemeral=True)
            if self.action == "add":
                count = con.execute("SELECT COUNT(*) AS n FROM attendees WHERE party_id=?", (self.party_id,)).fetchone()["n"]
                if p["status"] != "open":
                    return await interaction.response.send_message("لا يمكن الإضافة: الحفلة مغلقة.", ephemeral=True)
                if count >= p["capacity"]:
                    return await interaction.response.send_message("لا توجد أماكن متبقية.", ephemeral=True)
                con.execute("INSERT OR IGNORE INTO attendees(party_id,user_id,display_name) VALUES(?,?,?)",
                            (self.party_id, member.id, member.display_name))
            else:
                con.execute("DELETE FROM attendees WHERE party_id=? AND user_id=?", (self.party_id, member.id))
        result = "تمت إضافة" if self.action == "add" else "تم حذف"
        await interaction.response.send_message(f"{result} {member.mention} {'إلى' if self.action == 'add' else 'من'} الحفلة. ✅", ephemeral=True)
        await refresh_party(interaction.client, self.party_id)


class PartyView(discord.ui.View):
    def __init__(self,pid):
        super().__init__(timeout=None); self.party_id=pid
        self.join.custom_id=f"party:{pid}:join"; self.leave.custom_id=f"party:{pid}:leave"
        self.edit_party.custom_id=f"party:{pid}:edit"
        self.add_person.custom_id=f"party:{pid}:add"
        self.remove_person.custom_id=f"party:{pid}:remove"
    @discord.ui.button(label="✅ انضمام",style=discord.ButtonStyle.success)
    async def join(self,interaction,button):
        with db() as con:
            p=con.execute("SELECT * FROM parties WHERE id=?",(self.party_id,)).fetchone()
            n=con.execute("SELECT COUNT(*) n FROM attendees WHERE party_id=?",(self.party_id,)).fetchone()["n"]
            if not p or p["status"]!="open": return await interaction.response.send_message("هذه الحفلة مغلقة.",ephemeral=True)
            if n>=p["capacity"]: return await interaction.response.send_message("عذراً، اكتملت الأماكن.",ephemeral=True)
            if not user_tag(interaction.user.id): return await interaction.response.send_message("سجّل تاقك أولاً من لوحة التاقات.",ephemeral=True)
            con.execute("INSERT OR IGNORE INTO attendees(party_id,user_id,display_name) VALUES(?,?,?)",(self.party_id,interaction.user.id,interaction.user.display_name))
        await interaction.response.send_message("تم تسجيلك بالحفلة بنجاح! 🎉",ephemeral=True)
        await refresh_party(interaction.client,self.party_id)
    @discord.ui.button(label="↩️ إلغاء التسجيل",style=discord.ButtonStyle.secondary)
    async def leave(self,interaction,button):
        with db() as con: con.execute("DELETE FROM attendees WHERE party_id=? AND user_id=?",(self.party_id,interaction.user.id))
        await interaction.response.send_message("تم إلغاء تسجيلك.",ephemeral=True)
        await refresh_party(interaction.client,self.party_id)


    @discord.ui.button(label="✏️ تعديل الحفلة", style=discord.ButtonStyle.primary, row=1)
    async def edit_party(self, interaction, button):
        if not is_party_admin(interaction):
            return await interaction.response.send_message("هذا الزر للمشرفين فقط.", ephemeral=True)
        await interaction.response.send_modal(EditPartyModal(self.party_id))

    @discord.ui.button(label="➕ إضافة شخص", style=discord.ButtonStyle.success, row=1)
    async def add_person(self, interaction, button):
        if not is_party_admin(interaction):
            return await interaction.response.send_message("هذا الزر للمشرفين فقط.", ephemeral=True)
        await interaction.response.send_modal(ManageAttendeeModal(self.party_id, "add"))

    @discord.ui.button(label="➖ حذف شخص", style=discord.ButtonStyle.danger, row=1)
    async def remove_person(self, interaction, button):
        if not is_party_admin(interaction):
            return await interaction.response.send_message("هذا الزر للمشرفين فقط.", ephemeral=True)
        await interaction.response.send_modal(ManageAttendeeModal(self.party_id, "remove"))

class PartyBot(commands.Bot):
    async def setup_hook(self):
        init_db(); self.add_view(TagPanel())
        with db() as con: ids=con.execute("SELECT id FROM parties WHERE status='open'").fetchall()
        for r in ids: self.add_view(PartyView(r["id"]))
        await self.tree.sync()

bot=PartyBot(command_prefix="!",intents=discord.Intents.default())
@bot.event
async def on_ready(): print(f"تم تشغيل البوت: {bot.user}")

@bot.tree.command(name="لوحة_التاقات",description="إرسال لوحة تسجيل وعرض التاقات")
@app_commands.checks.has_permissions(manage_guild=True)
async def tags_panel(interaction):
    e=discord.Embed(title="🏷️ لوحة التاقات",description="سجّل تاقك داخل اللعبة أو اعرض التاقات المسجلة.\nيمكنك تحديث تاقك في أي وقت.",color=0x625BEE)
    await interaction.channel.send(embed=e,view=TagPanel())
    await interaction.response.send_message("تم إرسال لوحة التاقات.",ephemeral=True)

@bot.tree.command(name="حفلة",description="إنشاء حفلة جديدة")
@app_commands.describe(gems="عدد الجواهر",الموعد="اكتب التاريخ والوقت، مثال: 24/11/2026 - 4:30 مساءً")
@app_commands.choices(gems=[app_commands.Choice(name="200 جوهرة",value=200),app_commands.Choice(name="400 جوهرة",value=400),app_commands.Choice(name="600 جوهرة",value=600)])
@app_commands.checks.has_permissions(manage_guild=True)
async def create_party(interaction,gems:app_commands.Choice[int],الموعد:str):
    tag=user_tag(interaction.user.id)
    if not tag: return await interaction.response.send_message("سجّل تاقك أولاً باستخدام /لوحة_التاقات.",ephemeral=True)
    with db() as con:
        cur=con.execute("INSERT INTO parties(guild_id,channel_id,host_id,host_name,tag,gems,event_time,capacity,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (interaction.guild_id,interaction.channel_id,interaction.user.id,interaction.user.display_name,tag,gems.value,الموعد,20,"open",datetime.now(timezone.utc).isoformat()))
        pid=cur.lastrowid
    msg=await interaction.channel.send(embed=party_embed(pid),view=PartyView(pid))
    with db() as con: con.execute("UPDATE parties SET message_id=? WHERE id=?",(msg.id,pid))
    await interaction.response.send_message(f"تم إنشاء الحفلة رقم {pid}. 🎉",ephemeral=True)

@bot.tree.command(name="إغلاق_حفلة",description="إغلاق حفلة ومنع التسجيل")
@app_commands.describe(رقم="رقم الحفلة")
@app_commands.checks.has_permissions(manage_guild=True)
async def close_party(interaction,رقم:int):
    with db() as con:
        p=con.execute("SELECT id FROM parties WHERE id=? AND guild_id=?",(رقم,interaction.guild_id)).fetchone()
        if not p: return await interaction.response.send_message("لم يتم العثور على الحفلة.",ephemeral=True)
        con.execute("UPDATE parties SET status='closed' WHERE id=?",(رقم,))
    await refresh_party(bot,رقم)
    await interaction.response.send_message("🔒 تم إغلاق الحفلة.",ephemeral=True)

@bot.tree.command(name="تنبيه_الحفلة",description="إرسال تنبيه للمسجلين في حفلة")
@app_commands.describe(رقم="رقم الحفلة",رسالة="رسالة التنبيه")
@app_commands.checks.has_permissions(manage_guild=True)
async def notify_party(interaction,رقم:int,رسالة:str):
    with db() as con:
        p=con.execute("SELECT id FROM parties WHERE id=? AND guild_id=?",(رقم,interaction.guild_id)).fetchone()
        people=con.execute("SELECT user_id FROM attendees WHERE party_id=?",(رقم,)).fetchall()
    if not p: return await interaction.response.send_message("لم يتم العثور على الحفلة.",ephemeral=True)
    mentions=" ".join(f"<@{r['user_id']}>" for r in people)
    await interaction.channel.send(f"🔔 تنبيه الحفلة **#{رقم}**\n{mentions}\n{discord.utils.escape_mentions(رسالة)}")
    await interaction.response.send_message("تم إرسال التنبيه.",ephemeral=True)

@bot.tree.error
async def on_error(interaction,error):
    msg="هذا الأمر للمشرفين فقط." if isinstance(error,app_commands.MissingPermissions) else "حدث خطأ أثناء تنفيذ الأمر. تأكد من البيانات وحاول مرة ثانية."
    if interaction.response.is_done(): await interaction.followup.send(msg,ephemeral=True)
    else: await interaction.response.send_message(msg,ephemeral=True)
    if not isinstance(error,app_commands.MissingPermissions): print(repr(error))

if not TOKEN: raise RuntimeError("ضع توكن البوت في متغير البيئة DISCORD_TOKEN")
bot.run(TOKEN)
