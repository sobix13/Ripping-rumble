"""Read-only member and administrator guides inside Discord."""
import discord

from .perms import is_admin, is_host
from .ui.panel import PanelBase, PanelHome, BackButton

USER_GUIDE = (
    "Press **Join** before the lobby closes. After the start, watch the bot run every scene and choose the winner. "
    "No extra player click, wallet connection, signature or purchase is needed.\n\n"
    "**Out** lists eliminated members. **Back in** lists returns. **Still in** shows the small remaining field. "
    "**Holding** names fictional story items. A holder loses an item on elimination.\n\n"
    "Automatic Second Chance chooses an eligible fallen member when its window opens. Each member returns "
    "at most once. Some games have no suitable window.\n\n"
    "Use **/rumble leaderboard** and **/rumble stats** for results. The final post includes the full ranking, "
    "inline or as an attached file.\n\n"
    "Scenes use models from across Hot Wheels history and collector culture. A scene does not claim RipCars "
    "inventory or a real item prize. This is an independent community game."
)

ADMIN_GUIDE = (
    "Run **/rumble setup** for the game channel, host/player roles, optional winner role, defaults and private reports. "
    "Use **/rumble panel** for all later settings. Hosts run and schedule games. Admins change configuration.\n\n"
    "**Maintenance** shows operational status and creates a verified database backup. **Diagnostics** checks "
    "permissions, loops, pending results and role delivery. Private reports stop if their channel loses privacy.\n\n"
    "**Scenario text** exports the text list and edits a stable line ID after placeholder and writing checks. A blank replacement resets that "
    "line. Existing games keep their start-time snapshot. Changes affect future games. Item and victim roles stay fixed.\n\n"
    "The base pause is a minimum. Dense laps receive reading time up to 30 seconds. A larger configured minimum "
    "still applies. Test the pace with your members.\n\n"
    "For deployment, backups, restore and uncertain-delivery reconciliation, follow **docs/DEPLOYMENT.md** and "
    "the release README. Restore is an offline operator action. Review **docs/LIVE_ACCEPTANCE.md** before "
    "a public event. Local checks do not certify real Discord delivery."
)


class GuideView(PanelBase):
    title = "User Guide"

    def __init__(self, bot, user, cfg, admin=False):
        super().__init__(bot, user, cfg)
        self.admin_only = admin
        self.title = "Admin Guide" if admin else "User Guide"
        self.btn_admin.disabled = not is_admin(user, cfg)
        if is_host(user, cfg):
            self.add_item(BackButton(PanelHome, row=1))

    def require_access(self, interaction, cfg, admin_only=None):
        if self.admin_only or admin_only:
            return super().require_access(interaction, cfg, admin_only=True)
        if interaction.guild_id != self.cfg.guild_id or interaction.user.id != self.user.id:
            raise PermissionError("This guide belongs to another member or server. Open /rumble guide.")
        if self.is_finished() or getattr(self.bot, "closing", False):
            raise PermissionError("This guide expired. Open /rumble guide again.")

    async def render(self, guild):
        if self.admin_only and not is_admin(self.user, self.cfg):
            raise PermissionError("The admin guide is for admins.")
        return self.base_embed(ADMIN_GUIDE if self.admin_only else USER_GUIDE)

    @discord.ui.button(label="User Guide", style=discord.ButtonStyle.secondary, row=0)
    async def btn_user(self, interaction, button):
        if not await self.authorize(interaction):
            return
        await self.go(interaction, GuideView, admin=False)

    @discord.ui.button(label="Admin Guide", style=discord.ButtonStyle.secondary, row=0)
    async def btn_admin(self, interaction, button):
        if not await self.authorize(interaction, admin_only=True):
            return
        await self.go(interaction, GuideView, admin=True)
