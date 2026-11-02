# Admin Guide

The member experience remains Join-only. Administration takes place before or outside the active game.

## Setup and access

Run `/rumble setup`. Its six steps cover the game channel, host roles, player roles, optional winner role, defaults and an optional private report channel. Settings save as you go. The final screen shows local checks. A completed wizard does not certify real Discord behavior.

Use `/rumble panel` for later changes. Hosts start, stop and schedule games. Admins configure the bot. Manage Server or configured admin roles grant admin access. Award-role selection additionally requires Manage Roles and suitable hierarchy. The prize role must remain dedicated and separate from access roles.

Panels belong to the member who opened them and to that server. Every change checks the current policy. Panels expire after fifteen minutes of inactivity. Open a fresh panel after an expiry, restart or access change.

The member and admin guides are read-only. Ordinary members receive no configuration controls from opening their guide.

## Private reports

Choose the destination in Setup or Settings → Private reports. Hide it from @everyone. Remove explicit viewing grants for unrelated members or roles. Admins, hosts, the guild owner and the bot are the intended audience. The bot needs View Channel, Send Messages and Embed Links.

Privacy is checked again before delivery. Reporting stops if the channel becomes public or its audience changes. It never falls back to the game channel. Clear the destination to disable channel reporting. Runtime logs remain available to the operator.

## Scenario text

Settings → Scenario text provides **Download scenario texts** with stable IDs and current wording inside Discord. Enter an ID and a replacement of up to 240 characters. A blank replacement resets that ID to its shipped text. Placeholder roles, item contracts, writing rules and world boundaries remain fixed. Validate the meaning of any edit before a public event.

Edits affect future games. Active games keep their starting snapshot. Scenario names are drawn from the wider Hot Wheels hobby and do not claim platform inventory or real prizes. This editor changes text only. It does not add branching story logic.

## Maintenance and diagnosis

Maintenance shows runtime and latest verified-backup status. Create verified backup makes a database checkpoint without posting the file to Discord. Backup failure stays a failure and is reported through Diagnostics.

Leaderboard reset waits until that server has no active rumble, takes a verified backup and checks admin access again before deleting its stats. A failed backup leaves the leaderboard intact.

Diagnostics checks the game channel, roles, loops, pending result announcements, pending role grants and recent errors. A healthy process is different from a working Discord connection. Use the operational health signal described in `DEPLOYMENT.md` for external monitoring.

For uncertain delivery, inspect the channel and follow the reconciliation procedure in the release README. Delivery repair must not recount the win. Do not blindly resend an uncertain announcement.

## Deployment, updates and acceptance

Follow `DEPLOYMENT.md` for staging, backups, install/update, code rollback and offline restore. Restore is an operator action. A code rollback must preserve current data and credentials.

Run the private acceptance procedure before a public event. Check normal members without Administrator, two- and small-member games, your usual lobby capacity, mobile reading, images, role hierarchy, permission changes, restart and failed delivery. Local tests do not certify the real Discord API or the VPS.
