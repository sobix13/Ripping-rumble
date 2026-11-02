"""Lobby controls. After Join, the game and its returns run automatically."""
import discord


class _BaseView(discord.ui.View):
    def disable(self):
        for item in self.children:
            item.disabled = True
        self.stop()

    async def on_error(self, interaction, error, item):
        runner = getattr(self, "runner", None)
        if runner is not None:
            runner.bot.record_error(interaction.guild_id, f"Button error: {type(error).__name__}: {error}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send("Something went wrong with that button.", ephemeral=True)
            else:
                await interaction.response.send_message("Something went wrong with that button.", ephemeral=True)
        except discord.HTTPException:
            pass


class LobbyView(_BaseView):
    def __init__(self, runner, timeout):
        super().__init__(timeout=timeout)
        self.runner = runner

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success, emoji="🏎️")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        policy = await self.runner.bot.db.get_config(interaction.guild_id)
        ok, msg = self.runner.try_join(interaction.user, cfg=policy)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok, msg = self.runner.try_leave(interaction.user)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Start now", style=discord.ButtonStyle.primary)
    async def start_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        policy = await self.runner.bot.db.get_config(interaction.guild_id)
        ok, msg = self.runner.try_start_now(interaction.user, cfg=policy)
        await interaction.followup.send(msg, ephemeral=True)
