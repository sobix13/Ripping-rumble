"""Generic scenario bank, shared by every world.

Placeholders
  {A}            the ripper who acts (kills, wipes out, finds, survives, revives, wins)
  {B} {C}        rippers who go out (or the second ripper in a moment / double KO)
  {H}            a ripper still holding an item from an earlier lap
  {item}         what {H} holds
  {grail}        the world's top chase      {model}  a random Hot Wheels from the world pool
  {pack}         what you open in the world {names}  a list of rippers (hazards only)

Vibes:  slap (slapstick), col (collector), race, heist, degen, surreal, warm, cine (cinematic), meta
Tags:   onchain (wallets, links, floors: only in worlds that allow it), rc (gacha garage, claw, waffles, buyback)
"""


def L(text, vibe="slap", *tags, **extra):
    d = {"text": text, "vibe": vibe, "tags": list(tags)}
    d.update(extra)
    return d


KILL = [
    # slapstick
    L('{A} hit {B} with a {model}. Die-cast, full swing. Goodnight, {B}.', 'slap'),
    L('{A} pushed {B} into the gacha garage. The claw kept {B} as a prize.', 'slap', 'rc'),
    L('{A} sold {B} a fake {grail}. {B} found out in front of the whole server and evaporated.', 'slap', 'modern'),
    L('{A} told {B} the {grail} restock was live. {B} ran out the door and is still running.', 'slap'),
    L("{A} pulled a {grail} right next to {B}. {B}'s heart stopped from pure envy.", 'slap'),
    L("{A} hid a {model} in {B}'s cereal. Crunch. {B} is out.", 'slap'),
    L('{A} launched {B} off the top of a track loop. {B} has not landed yet.', 'slap'),
    L('{A} sealed {B} in a blister and put {B} on a supermarket peg. {B} is still waiting for someone to buy them.', 'slap'),
    L("{A} sneezed on {B}'s mint card. {B} fainted and never woke up.", 'col'),
    L('{A} outbid {B} by one dollar. {B} turned to dust.', 'col'),
    L("{A} left a {model} on {B}'s chair. {B} sat down, shot through the ceiling and left the rumble.", 'slap'),
    L('{A} rolls a decoy {model} down the exit ramp. {B} follows it through the shutter and misses the restart. Out.', 'heist'),
    L("{A} rolled a {model} under {B}'s foot at the top of the stairs. Gravity did the rest.", 'slap'),
    L('{A} paid the claw to grab {B}. The claw dropped {B} in a different server.', 'slap', 'rc', 'modern'),
    L('{A} and {B} reached for the last {model} on the peg. {A} left with it. {B} left in an ambulance.', 'col'),
    L('{A} told {B} their {grail} was a reproduction. {B} crumbled like an old card.', 'col'),
    L('{A} rolled the gacha garage downhill. {B} was standing at the bottom.', 'slap', 'rc'),
    L('{A} threw a 50-pack at {B}. Direct hit. {B} is out.', 'slap'),
    L('{A} buries {B} under a stack of collector catalogues. By the time {B} crawls out, their heat is over.', 'slap'),
    L("{A} hid {B}'s favorite {model}. {B} is still looking. The rumble moved on.", 'slap'),
    L('{A} mailed {B} to a collector in a bubble mailer. Tracking says delivered. {B} says help.', 'slap'),
    L('{A} drop-kicked {B} into the dump bin. Lost forever among 400 commons.', 'slap'),
    L("{A} opened {B}'s carded {grail} to play with it. {B}'s soul left the building.", 'col'),
    L('{A} flicked a {model} across the table and hit {B} right in the forehead. Clean elimination.', 'slap'),
    L('{A} pretended to be a mod and banned {B}. Not even a real mod. Still worked.', 'meta', 'modern'),
    L('{A} gave {B} a free pack. The pack had teeth. It ate {B}.', 'surreal'),
    L("{A} stuck a magnet on {B}'s belt. The claw grabbed {B} and never let go.", 'slap', 'rc'),
    L("{A} tied {B}'s shoelaces to the track launcher and hit the switch.", 'slap'),
    L('{A} let {B} hold a {grail} for one second. {B} dropped it. The crowd carried {B} away.', 'col'),
    L('{A} dared {B} to open a sealed {grail}. {B} did it. The collectors are still chasing {B}.', 'col'),
    L("{A} swapped {B}'s glasses for 1:64 scale glasses. {B} walked straight into a display case.", 'slap'),
    L("{A} wrote {B}'s name on the return label. {B} got shipped back to the factory.", 'slap'),
    L("{A} spilled soda on {B}'s card. Soggy corners. {B} is gone.", 'col'),
    L('{A} beat {B} in a rip battle, 10 pulls to zero. {B} sold the account and moved to the woods.', 'slap', 'modern'),
    L('{A} challenged {B} to a staring contest over a {grail}. {B} blinked first and turned to dust.', 'slap'),
    L("{A} made {B}'s worst pull the server banner. {B} left and changed their name.", 'meta', 'modern'),
    L('{A} faked a {grail} restock in general chat. {B} sprinted to the store and hit the doors before they opened.', 'slap', 'modern'),
    L('{A} put {B} in the buyback queue. {B} came out as 90% of a person.', 'slap', 'rc'),
    L('{A} told {B} the claw was friendly. {B} tried to pet it.', 'slap', 'rc'),
    L("{A} put a 'FREE {grail}' sign on a trapdoor. {B} stepped right on it.", 'slap'),
    # race
    L('{A} took the inside line at the last corner. {B} took the wall.', 'race'),
    L("{A} pulls out of {B}'s slipstream on the deciding straight. {B} crosses second and leaves the elimination heat.", 'race', 'modern'),
    L("Commentary box: '{A} goes for the gap, and {B} is in the gravel!' Unbelievable scenes.", 'race'),
    L('{A} brake-checked {B} on the main straight. {B} is a wall decoration now.', 'race'),
    L('{A} makes the tyre stop. {B} stays out until a puncture ends their race.', 'race'),
    L("{A}'s pit crew finishes the stop. {B}'s jack jams, and their entry misses the elimination restart.", 'race'),
    L('{A} sends it down the inside from three rows back. {B} slides into the gravel and retires from the heat.', 'race'),
    L('{A} and {B} went into Turn 1 side by side. Only {A} came out of it.', 'race'),
    # heist
    L("{A} wins the shelf-side race by a wheel. {B}'s display entry crosses second and leaves the bracket.", 'heist'),
    L('{A} switches the finish flag to the correct lane. {B} celebrates at the wrong line and misses the real finish. Out.', 'heist'),
    L('Lights out. Lights on. {B} has followed a decoy {model} through the exit. {A} is still at the starting line, whistling.', 'heist'),
    L("{A} loads {B}'s shelf onto a delivery trolley. {B} follows it through the exit and misses the deciding heat.", 'heist'),
    L("{A} picked the lock on {B}'s display case in four seconds. {B} fainted at three.", 'heist'),
    L('{A} rolls a decoy {model} toward the exit. {B} chases it out, and the elimination gate closes behind them.', 'heist'),
    L('{A} enters the lane with a {model}. {B} enters a paper cutout. The cutout folds at the launcher. {B} is out.', 'heist'),
    # collector
    L("{A} pointed out a tiny scratch on {B}'s mint card. {B} has not slept since. {B} is out.", 'col'),
    L('{A} told {B} the {model} they paid big for is a peg warmer. {B} turned to dust.', 'col'),
    L('{A} showed {B} a cleaner card of the same {model}. {B} retired from collecting.', 'col'),
    L("{A}'s loose {model} clears the lane. {B}'s unopened blister jams at the launcher. This heat needs wheels on track. {B} is out.", 'col'),
    L('{A} and {B} hunted the last {grail} at the same store. The cashier picked {A}. {B} is out.', 'col'),
    L("{A} found a dent in {B}'s blister with a ruler. {B} left the hobby that night.", 'col'),
    L('{A} offered {B} market price for a {model}. {B} checked the market and fainted.', 'col'),
    L('{A} trades {B} down to one common and a hot dog. {B} heads home before their deciding heat. Out.', 'col'),
    # degen
    L("{A} front-ran {B}'s rip and pulled the {grail} first. {B} is out.", 'degen', 'onchain'),
    L("{A} paid a higher priority fee. {B}'s transaction never landed.", 'degen', 'onchain', 'modern'),
    L('{A} sold the top to {B}. {B} is still holding the bag.', 'degen', 'onchain'),
    L('{A} airdropped {B} a fake pack. {B} signed it. {B} is gone.', 'degen', 'onchain'),
    L('{A} told {B} the floor only goes up. {B} believed it. {B} is out.', 'degen', 'onchain'),
    # surreal
    L("{A} whispers the {grail}'s true name to {B}. {B} shrinks to 1:64 scale and fails to reach the starting gate before it closes.", 'surreal'),
    L('{A} opened a portal behind the dump bin. {B} walked through it looking for restocks.', 'surreal'),
    L('{A} challenged {B} to a duel at high noon. {B} brought a {model}. {A} brought a monster truck.', 'surreal'),
    L('{A} folded {B} like a card back and slid {B} into a blister.', 'surreal'),
    # cinematic
    L('Slow motion. {A} turns. {B} reaches for the {grail}. Too slow. {B} is out.', 'cine'),
    L('{A} flips the track switch. {B} lands in the return bin instead of the finish tray. End of the heat for {B}.', 'cine'),
    L("{A} looked {B} in the eye, said 'nothing personal' and launched {B} into orbit.", 'cine'),
]

WIPE = [
    # slapstick
    L('{A} swallowed a {model} to keep it safe. Choked to death. The {model} is fine.', 'slap'),
    L('{A} climbed into the gacha garage to fix the claw. Got trapped. In there forever now. RIP {A}.', 'slap', 'rc'),
    L('{A} pulled a {grail} on the first rip, screamed and died of happiness.', 'slap'),
    L('{A} opened a {pack} sure it held a {grail}. The {pack} was fake. {A} burst into flames from grief.', 'slap'),
    L('{A} tried to smell a {model} through the blister and inhaled the blister.', 'slap'),
    L('{A} kissed the gacha garage for luck. Their lips are still stuck to it.', 'slap', 'rc'),
    L('{A} built a track loop from the roof to the pool. Rode it. Missed the pool.', 'slap'),
    L('{A} camped outside the store at 5 AM for a {model} restock. Froze solid at 5:20.', 'col'),
    L('{A} tried to rip a {pack} open with their teeth. The {pack} ripped {A} instead.', 'slap'),
    L('{A} looked up the price of a {grail} and fainted. Never woke up.', 'col'),
    L('{A} told the whole server their {model} was worth millions. Got a price check. Evaporated.', 'col', 'modern'),
    L('{A} fell asleep inside the gacha garage. The claw thought {A} was a prize and shipped {A} to a winner in Ohio.', 'slap', 'rc'),
    L('{A} got shrink-wrapped at the packing station. Mint forever. Unable to move.', 'slap'),
    L('{A} found a waffle and ate it. It was a free pull. {A} ate a free pull. Out of pulls, out of the rumble.', 'slap', 'rc'),
    L('{A} spends the deciding heat counting spare change. The starting gate closes without their entry. Out.', 'slap'),
    L('{A} stared at a {grail} too long and turned to stone. Shiny stone, at least.', 'surreal'),
    L('{A} raced a {model} against a city bus. The bus won. {A} was standing on the finish line.', 'slap'),
    L('{A} cleaned the claw with a wet towel. Got zapped. Hair stands straight up forever.', 'slap', 'rc'),
    L('{A} pulled the same common 40 times in a row and retired to a farm.', 'slap'),
    L('{A} sold a {grail} to buyback by mistake and screamed so hard they left orbit.', 'slap', 'rc'),
    L('{A} filmed a slow-motion unboxing. It took three days. The rumble moved on without them.', 'slap', 'modern'),
    L('{A} broke the house rule and called a Hot Wheels by the wrong name in front of The Ripper. Nobody has seen {A} since.', 'meta'),
    L('{A} put a {model} in the microwave to see what happens. Now everyone knows. {A} is out.', 'slap', 'modern'),
    L('{A} unboxed live on stream. Chat roasted {A} until there was nothing left.', 'meta', 'modern'),
    L('{A} stepped on a loose {model} barefoot at 3 AM. Screamed so loud they left the rumble.', 'slap'),
    L('{A} lost the seed phrase. The garage forgot {A} ever existed.', 'degen', 'onchain', 'modern'),
    L("{A} clicked a 'free {grail}' link. Rugged in four seconds.", 'degen', 'onchain'),
    L('{A} hugged the gacha garage too hard. The garage hugged back.', 'slap', 'rc'),
    L('{A} trades their collection for a {grail} sticker. They spend the deciding heat at the refund desk. Out.', 'col'),
    L('{A} opened a {pack} so carefully it took a week. Starved halfway through.', 'slap'),
    L('{A} chased a {model} under the fridge. Got stuck under the fridge. Lives there now.', 'slap'),
    L('{A} pressed their face on a protector case to see a {grail} up close. Head stuck. Mint, sealed, out.', 'slap'),
    L('{A} won the auction for a {grail}, then saw the shipping cost. Collapsed.', 'col'),
    L('{A} tried to outrun the claw. The claw does not get tired.', 'slap', 'rc'),
    L('{A} reorganized the shelf one last time. The shelf fell on {A}. Buried in blisters.', 'col'),
    L('{A} yelled LFRIP so loud the roof came down.', 'meta'),
    L('{A} checked a {model} with a magnifying glass in the sun. Set the {model} on fire. Then the table. Then {A}.', 'slap'),
    L('{A} squeezed into a display case to feel what a {grail} feels. Fit perfectly. Stuck forever.', 'surreal'),
    L('{A} pulled a {grail} and texted mom. Mom sold it. {A} is out.', 'slap', 'modern'),
    L('{A} opened a {pack} and found a smaller {pack} inside. Then a smaller one. {A} is still opening.', 'surreal'),
    L('{A} listed a common at {grail} prices. The server laughed {A} out of the rumble.', 'col', 'modern'),
    # warm: happy exits
    L("{A} finally pulled their grail, said 'I'm good' and walked off into the sunset. Retired happy.", 'warm'),
    L('{A} gave their last pack to a new ripper and left with a smile. Legend move.', 'warm'),
    L('{A} stopped to help someone pick up a dropped collection and missed the rest of the race. Worth it.', 'warm'),
    L('{A} pulled a common, loved it anyway and went home happy. Out, but at peace.', 'warm'),
    L("{A} got so busy hyping everyone else's pulls that they forgot to play. Out, but beloved.", 'warm'),
    L('{A} retired to open a tiny shop for loose commons. Business is slow. Life is good.', 'warm'),
    # collector
    L('{A} spent the whole lap sorting by casting year. Got sorted out of the rumble.', 'col'),
    L('{A} found a card variation nobody has heard of and left to write a 40-page post about it.', 'col'),
    L('{A} bought a second shelf. Then a third. The floor gave in. {A} lives in the basement now.', 'col'),
    L("{A} opened their own carded {grail} at 3 AM 'to see it once'. Value gone. Soul gone.", 'col'),
    L('{A} refreshed the restock page until the browser gave up. Then {A} gave up too.', 'col', 'modern'),
    L('{A} argued about the right shade of red for six hours. Was wrong. Left in silence.', 'col'),
    # race
    L('{A} went full send into the hairpin and forgot brakes exist.', 'race'),
    L('{A} pitted for fuel. The crew filled it with orange soda.', 'race'),
    L('{A} bounced off the rev limiter for a full lap. The engine quit and took {A} with it.', 'race'),
    L('{A} ran slicks in the rain. {A} is a boat now.', 'race'),
    L('{A} ran out of fuel ten meters from the line. Pushed. Did not make it.', 'race'),
    L('{A} does a victory burnout before the deciding heat. Tyres gone, entry withdrawn.', 'race'),
    # surreal
    L('{A} squeezes inside a display blister. The lid clicks shut. The next heat starts without them.', 'surreal'),
    L('{A} rode the orange track so many times they became the orange track.', 'surreal'),
    L("{A} looked straight into a {grail}'s headlights and saw the future. The future did not include {A}.", 'surreal'),
    L('{A} got abducted by aliens looking for a {model}. They were disappointed. {A} stayed up there anyway.', 'surreal'),
    L('{A} shrank to 1:64 scale and got lost in the carpet.', 'surreal'),
    # degen
    L('{A} bridged their pulls to the wrong chain. Gone forever.', 'degen', 'onchain'),
    L('{A} aped into a pack at 3 AM, woke up, read the receipt and fainted.', 'degen', 'modern'),
    L("{A} went all in on a 'guaranteed' {grail}. Nothing is guaranteed. {A} is out.", 'degen'),
    # cinematic
    L('Thunder. Rain. {A} holds an empty {pack} outside the locked starting gate. Their heat ends inside. Fade to black.', 'cine'),
    L("{A} whispered 'one more rip'. Those were their last words.", 'cine'),
    L('The music stops. The lights dim. {A} is gone, and only the {model} remains.', 'cine'),
]

MULTI = [
    L('{A} kicked the gacha garage. The claw went wild and grabbed {B} and {C}.', 'slap', 'rc'),
    L('{A} spilled a box of loose Hot Wheels on the stairs. {B} and {C} took the fast way down.', 'slap'),
    L("{A} yelled 'free {grail}' at the back of the room. {B} and {C} crashed into each other at full speed.", 'slap'),
    L('{A} pulled a {grail} in front of {B} and {C}. Both fainted at the same time.', 'slap'),
    L('{A} sealed {B} and {C} in a two-pack. Sold as a set.', 'slap'),
    L('{A} hit the track launcher too hard. {B} and {C} got fired into the next server.', 'slap', 'modern'),
    L('{A} started a {grail} restock rumor. {B} and {C} camped outside the store until they turned into furniture.', 'slap'),
    L('{A} bowled a {model} down the hallway. Strike. {B} and {C} are down.', 'slap'),
    L('{A} slammed the shutter down. {B} and {C} were leaning on it.', 'slap', 'rc'),
    L('{A} put {B} and {C} in one protector case to save space. Neither is getting out.', 'slap'),
    L('{A} knocked the shelf over. {B} and {C} got buried under 300 blisters.', 'slap'),
    L('{A} called a fake restock in two group chats. {B} and {C} drove into each other in the parking lot.', 'col', 'modern'),
    L("Commentary: '{A} goes three wide, and {B} and {C} are both in the barrier!'", 'race'),
    L('{A} tied {B} and {C} together by their shoelaces at the start. Green flag. Down they went.', 'race'),
    L('{A} outbid {B} and {C} at the same auction with one click. Both left the internet.', 'col', 'modern'),
    L('{A} sells {B} and {C} the same {grail}. Both abandon their starting lanes to argue at the returns desk. Their heat ends without them.', 'heist'),
    L('{A} hit the jackpot on the gacha garage. The confetti cannon took out {B} and {C}.', 'slap', 'rc'),
]

DOUBLE = [
    L('{A} and {B} grabbed the same pack and bonked heads. Both out.', 'slap'),
    L('{A} and {B} argued about loose versus carded until both turned to dust.', 'col'),
    L('{A} and {B} raced to the last {model}. Hit the shelf at the same time. The shelf won.', 'slap'),
    L('{A} and {B} tried to share one gacha garage. The claw took them both.', 'slap', 'rc'),
    L('{A} and {B} high-fived over a {grail} pull and dislocated everything. Both out.', 'slap'),
    L('{A} and {B} started a tandem drift and drifted straight out of the server together.', 'race', 'modern'),
    L('{A} and {B} traded the same {model} back and forth for six hours. Both got bored to death.', 'col'),
    L('{A} and {B} both lied about owning a {grail}. Both got caught. Both out.', 'col'),
    L('{A} and {B} fell asleep in the same dump bin. Shipped back to the warehouse together.', 'slap'),
    L('{A} and {B} held a staring contest over a {model}. Neither blinked. Both dried out.', 'surreal'),
]

# Finds: nobody goes out. {A} now holds the item ("grail" or "model").
FIND = [
    L('{A} found a {grail} under the couch cushions. Nobody saw. Keep it that way.', 'slap', holds='grail'),
    L('{A} pulled a {grail} and hid it in their sock. Walking funny, walking rich.', 'slap', holds='grail'),
    L('{A} traded half a sandwich for a {model}. Worst trade of the year for the other guy.', 'slap', holds='model'),
    L('{A} found a {model} at the bottom of a cereal box. Ate the cereal. Kept the {model}.', 'slap', holds='model'),
    L('{A} bought a {grail} at a yard sale for one dollar. The seller is crying somewhere.', 'col', holds='grail'),
    L('{A} fished a {model} out of the gacha garage with a coat hanger. Security looked away.', 'heist', 'rc', holds='model'),
    L("{A} found a {grail} in grandma's attic. Grandma wants it back. Grandma is not getting it back.", 'slap', holds='grail'),
    L("The claw dropped a {grail} straight into {A}'s lap. The claw has favorites.", 'slap', 'rc', holds='grail'),
    L('{A} found a {model} rolling around pit lane. Finders keepers.', 'race', holds='model'),
    L('{A} pulled a {grail} and posted it in general. Every ripper in the room turned around at once.', 'meta', 'modern', holds='grail'),
    L('{A} bought a {model} from a stranger in a parking lot. No questions asked. Several should have been.', 'heist', holds='model'),
    L('{A} found a sealed {grail} in a dumpster behind a collector show. Smells weird. Still mint.', 'col', holds='grail'),
    L('{A} swapped a common for a {grail} while the owner sneezed.', 'heist', holds='grail'),
    L('{A} won a {grail} in a raffle they never entered.', 'surreal', holds='grail'),
    L('{A} found a {model} in the pocket of a used jacket. Good day.', 'warm', holds='model'),
    L("{A} found a {model} taped under a park bench with a note: 'you deserve this'.", 'warm', 'modern', holds='model'),
    L('{A} pulled a {grail} and told nobody. Smiling a little too much.', 'col', holds='grail'),
    L('{A} traded a stack of commons for a {model} with someone who did not check the card.', 'col', holds='model'),
    L('{A} won a {model} in a bet about tyre pressure.', 'race', holds='model'),
    L('{A} found a {grail} on a dusty gas station shelf. The clerk had no idea.', 'col', holds='grail'),
    L('{A} bought a mystery box at a garage sale. Inside: a {grail} and a lot of dust.', 'col', holds='grail'),
    L('The Ripper tossed {A} a {model} from the roadster and drove off without a word.', 'cine', 'rc', holds='model'),
    L('{A} pulled a {grail} on their birthday. The universe owed them one.', 'warm', holds='grail'),
]

# Callbacks: only while a holder from an earlier lap is still in.
# out: "B" ({H} takes {B} out), "H" (the holder goes out, no kill), "B+C" ({H} takes both out)
CALL = [
    L("{B} waits behind the pit wall to steal {H}'s {item}. {H} throws it between {B}'s eyes, then picks it up. {B} is out.", 'slap', out='B'),
    L("{B} snatched {H}'s {item} and ran. {H} chased {B} across three servers, got it back and left {B} in the third one.", 'slap', 'modern', out='B'),
    L("{H} polished the {item} so hard it flashed the sun into {B}'s eyes. {B} drove into a lake.", 'slap', out='B'),
    L("{H} slept with the {item} under the pillow. It rolled into {H}'s mouth overnight. Choked. RIP {H}.", 'slap', out='H'),
    L("{H} waved the {item} in {B}'s face one time too many. {B} died of jealousy.", 'col', out='B'),
    L('{B} offered {H} three commons for the {item}. {H} laughed for an hour straight. {B} left in shame.', 'col', out='B'),
    L('{H} refused to let go of the {item} during a pit stop. The crew changed {H} instead of the tyres.', 'race', out='H'),
    L('{H} uses the {item} as a doorstop. {B} trips over it and falls out of the rumble. {H} picks it up again.', 'slap', out='B'),
    L("{B} and {C} rush the lane to grab {H}'s {item}. {H} keeps it behind the barrier. Both intruders miss their own starts and go out.", 'heist', out='B+C'),
    L('{H} married the {item}. {B} objected at the wedding and got thrown out of the rumble.', 'surreal', out='B'),
    L("{B} grabbed {H}'s {item}, then dropped it. Both dove for it. Only {H} came back up.", 'slap', out='B'),
    L('{H} flexed the {item} in front of the claw. The claw took {H} and left the {item}.', 'slap', 'rc', out='H'),
    L("{B} licked {H}'s {item} to call dibs. {H} called the mods. {B} is banned for life.", 'meta', 'modern', out='B'),
    L("{B} broke into {H}'s protector case for the {item}. Got stuck inside. Part of the display now.", 'heist', out='B'),
    L('{H} hid the {item} so well that {H} forgot where. Searched until the rumble moved on without them.', 'slap', out='H'),
    L("{H} tosses the {item} up to flex. It lands on {B}'s head, ending their run. {H} catches it on the rebound.", 'slap', out='B'),
    L('{B} challenges {H} to a race for the {item}. {H} brings a real Supra, wins the deciding run, and keeps the Hot Wheels. {B} is out.', 'race', 'modern', out='B'),
    L("{B} challenges {H} for the {item}. {H} keeps it safely on the display. {B}'s entry rolls off the deciding lane. {B} is out.", 'col', out='B'),
    L("{B} sent {H} a fake 'claim your {item} reward' link. {H} sent it back. {B} clicked it and got rugged.", 'degen', 'onchain', out='B'),
    L("{H} still won't stop talking about the {item}. {B} left the server to get some peace.", 'meta', 'modern', out='B'),
    L("{B} tried to swap {H}'s {item} for a fake. {H} spotted the wrong wheels and sent {B} home.", 'col', out='B'),
    L('{H} let {B} hold the {item} for one second. {B} sneezed on it. {H} sent {B} to the shadow dimension.', 'col', out='B'),
    L("{B} runs toward {H}'s {item} instead of the start line. {H} keeps the Hot Wheels. {B} misses the heat and goes out.", 'warm', out='B'),
    L("{H} carried the {item} as a lucky charm all lap. It worked. Then it rolled under {H}'s foot.", 'slap', out='H'),
    L("{B} filmed a video roasting {H}'s {item}. The comments sided with {H}. {B} is gone.", 'meta', 'modern', out='B'),
    L("{B} and {C} reach across the deciding lanes for {H}'s {item}. Their entries collide. Both out, while {H} keeps the Hot Wheels.", 'col', out='B+C'),
]

# Transfers: nobody goes out. The item moves from {H} to {A}.
TRANSFER = [
    L('{H} traded the {item} to {A} for a sandwich. {H} regrets it already.', 'slap'),
    L('{A} won the {item} off {H} in a coin flip. Best of three. Then best of five.', 'slap'),
    L('{H} dropped the {item} in pit lane. {A} picked it up and kept walking.', 'race'),
    L('{A} sweet-talked {H} out of the {item}. Nobody knows how.', 'heist'),
    L('{H} gifted the {item} to {A}. A rare act of kindness. The server is shook.', 'warm', 'modern'),
    L("{A} found the {item} in {H}'s jacket. {H} was still wearing the jacket.", 'heist'),
    L("The claw grabbed the {item} from {H} and dropped it in {A}'s lap. The claw has a sense of humor.", 'slap', 'rc'),
    L('{H} put the {item} up as a bet. {A} won the bet.', 'col'),
    L("{A} swapped a lookalike for {H}'s {item}. {H} has not noticed yet.", 'heist'),
    L('{H} left the {item} on the counter for one second. {A} was faster.', 'slap'),
]

SURVIVE = [
    L('{A} spent the whole lap staring at a {model} through the blister. Still alive. Barely.', 'col'),
    L('{A} hid in a dump bin all lap. Survived. Smells like cardboard now.', 'slap'),
    L('{A} stood still and pretended to be a display stand. Nobody noticed.', 'slap'),
    L('{A} found a {model} on the floor, sniffed it and put it back. Weird, but alive.', 'slap'),
    L('{A} took a nap in the gacha garage. The claw tucked {A} in.', 'warm', 'rc'),
    L('{A} tried to open a {pack}, got tired and gave up. Saved by laziness.', 'slap'),
    L('{A} dodged the claw three times in a row. The claw is starting to take it personally.', 'slap', 'rc'),
    L('{A} talked about a {model} for so long that everyone walked away. Survived by being boring.', 'col'),
    L('{A} wrapped themselves in bubble wrap. Ugly, but unbreakable.', 'slap'),
    L("{A} sold a common for profit. Nobody knows how. {A} doesn't know how either.", 'col'),
    L('{A} hid behind the {grail} display case. Armored glass. Lucky {A}.', 'slap'),
    L('{A} said gm to the claw. The claw said gm back. Spared.', 'meta', 'rc', 'modern'),
    L('{A} sat out the lap eating a hot dog by the track. No notes.', 'warm'),
    L('{A} took a wrong turn and missed all the chaos. Lucky.', 'slap'),
    L('{A} starts explaining two shades of blue. The crowd moves the whole table away before the second sentence.', 'col'),
    L('{A} fell asleep on the shelf and got mistaken for decor. Untouched.', 'slap'),
    L('{A} meditated in pit lane. The chaos went around them.', 'warm'),
    L('{A} found a quiet corner and reorganized their pockets. Safe for now.', 'slap'),
    L('{A} took a selfie with the gacha garage. The claw photobombed. Nobody got hurt.', 'meta', 'rc'),
    L('{A} watched the whole lap from behind a stack of boxes with popcorn.', 'warm'),
    L('{A} dodged a flying {model} with their eyes closed. Instinct.', 'cine'),
    L('{A} spent the lap admiring the paint on a {model}. Worth it. Still alive.', 'col'),
]

# Moments: two rippers, nobody goes out.
MOMENT = [
    L('{A} and {B} called a truce to admire a {model} together. Beautiful moment. Truce ends next lap.', 'warm'),
    L('{A} helped {B} up after a spin. Respect. Back to war in a minute.', 'race'),
    L('{A} and {B} split a hot dog in the paddock. The rumble will wait.', 'warm'),
    L('{A} and {B} formed an alliance. It lasted 11 seconds.', 'slap'),
    L('{A} gave {B} a tip about a restock. It was real. Nobody saw that coming.', 'warm'),
    L('{A} and {B} argued about the best casting ever. Nobody won. Everyone lived.', 'col'),
    L('{A} showed {B} their pull. {B} said W. Pure respect.', 'meta', 'modern'),
    L('{A} and {B} built a track loop together. It worked on the first try. Suspicious.', 'slap'),
    L('{A} lent {B} a protector case. Friendship is rare in this game.', 'warm'),
    L('{A} and {B} fist-bumped at full speed. Somehow both kept it on the road.', 'race'),
    L('{A} and {B} hid behind the same dump bin and pretended not to see each other.', 'slap'),
    L('{A} and {B} crashed into the same hay bale and laughed it off.', 'race'),
    L('{A} caught {B} looking at their {model}. Both nodded. Collector to collector.', 'col'),
    L('{A} and {B} said gm at the same time. The server felt that.', 'meta', 'modern'),
]

REVIVE = [
    L('{A} came back from the dead to check one more pack.', 'slap'),
    L('The claw lowers {A} onto the return lane, then opens its grip. Back on the grid.', 'slap', 'rc'),
    L('{A} found a waffle in an old jacket and respawned.', 'slap', 'rc'),
    L("{A} passes the return desk's second inspection. One sticker on the badge, one place back on the grid.", 'slap'),
    L('A fresh bubble mailer arrives at the return desk. The marshal opens it and {A} steps out. Back in.', 'slap'),
    L('{A} heard a {grail} restock rumor and rose from the grave.', 'col'),
    L('{A} got re-carded on a fresh blister. Mint again, back again.', 'col'),
    L('{A} found the seed phrase in an old notebook and walked back in.', 'degen', 'onchain', 'modern'),
    L('{A} was faking it the whole time. Best actor in the server is back.', 'cine', 'modern'),
    L('{A} arrives at the return lane carrying a cracked protector case. The marshal waves them back onto the grid.', 'slap'),
    L('The Ripper owed {A} a favor. {A} is back on track.', 'cine', 'rc'),
    L("{A} came back for the {grail}. Still doesn't have it. Still here.", 'slap'),
    L('{A} kicked the gacha garage on the way out. It spat out a second chance.', 'slap', 'rc'),
    L('{A} filed a protest with the race stewards. Protest accepted. Back on track.', 'race'),
    L('{A} rolled a natural 20 and climbed back in.', 'surreal', 'modern'),
    L('{A} played a Get Out of Jail Free card nobody knew they had.', 'surreal'),
    L("{A}'s damaged entry is replaced at the reserve desk. Fresh wheels, same ripper. Back in.", 'col'),
    L('{A} reloaded the last save and walked back in.', 'meta', 'modern'),
]

# Final two: {A} wins the duel, {B} goes out. The winner post follows.
DUEL = [
    L('Final two. {A} and {B} line up. Green flag. {A} gets the launch. {B} gets the dust.', 'race'),
    L("{A} and {B} reach for the last {grail} at the same time. {A}'s fingers are faster.", 'col'),
    L('Last launch. {A} clears the loop. {B} lands upside down in the catch tray. The final belongs to {A}.', 'cine'),
    L('{B} offers a handshake. {A} offers a {model} to the forehead. Respectfully.', 'slap'),
    L('Last two in the garage: {A} and {B}. The claw comes down. It picks {B}.', 'slap', 'rc'),
    L('Photo finish. The stewards check the tape. {A} by a bumper. {B} by a heartbreak.', 'race'),
    L('{A} and {B} stare each other down over a {pack}. {A} rips first. {B} rips nothing.', 'cine'),
    L("{B} tries the outside on the final bend. {A} crosses the finish first. {B}'s race ends in second place.", 'race'),
    L('{A} and {B} play rock paper scissors for the title. {A} throws a {model}. Not a valid move. Still wins.', 'slap'),
    L("{A}'s {model} crosses the final line first. {B} arrives a wheel later. The trophy title goes to {A}.", 'col'),
    L('The crowd counts down. {A} lands in the finish tray. {B} lands in the packing box. The final is over.', 'cine'),
    L('{A} and {B} flip a coin for the win. It lands on its edge. {A} pushes it over.', 'surreal'),
]

WIN = [
    L('{A} is the last ripper standing. Scuffed edges, winning finish.', 'slap'),
    L('{A} survived the claw, the fakes and every ripper in here. RIP to the rest. LFRIP 🏎️', 'slap', 'rc'),
    L('{A} wins the rumble and the bragging rights. The Hot Wheels in this story stay fictional.', 'slap'),
    L('Only {A} is left. The claw bows.', 'slap', 'rc'),
    L('{A} wins the rumble. Screenshot it. Frame it. Never stop talking about it.', 'meta'),
    L('{A} is the last one rolling. One of one.', 'col'),
    L('{A} wins. The gacha garage opens its shutter for one ripper only.', 'cine', 'rc'),
    L('{A} outlived everyone, the claw included.', 'slap', 'rc'),
    L('{A} drives out of the garage alone. The shutter rolls down behind them. Champion.', 'cine', 'rc'),
    L('{A} takes the rumble. Somewhere, a {grail} feels proud.', 'warm'),
    L('{A} won. Mods, give this ripper a crown.', 'meta', 'modern'),
    L("Every engine went quiet except {A}'s. That's the win.", 'race'),
]

# Generic hazards (mass events). {names} = the rippers who go out.
HAZARD = [
    L('The big shelf collapses. {names} are buried under blisters.', 'slap'),
    L('A restock rumor spreads. {names} sprint out the door and never come back.', 'col'),
    L('A sudden rainstorm hits the track. {names} spin out.', 'race'),
    L('The claw goes berserk and drags {names} into the machine.', 'slap', 'rc'),
    L('A flash flood rolls through the parking lot. {names} float away on their cardboard.', 'slap'),
    L('The power goes out. When the lights come back, {names} are gone.', 'cine'),
    L('A runaway shopping cart plows through the crowd. {names} go down like bowling pins.', 'slap'),
    L("Somebody shouts 'free packs outside'. {names} sprint out and the door locks behind them.", 'heist'),
    L('The floor opens like a trapdoor. {names} drop into the basement storage.', 'surreal'),
    L('A tornado of loose Hot Wheels spins through the room. {names} get swept up.', 'surreal'),
    L('A strange fog rolls in. When it clears, {names} are nowhere to be found.', 'cine'),
    L('The mods start a surprise cleanup. {names} get swept out with the trash.', 'meta', 'modern'),
]

# Ambient: no rippers, pure atmosphere. Used to give thin rounds (small lobbies) some air.
AMBIENT = [
    L('A lone {model} rolls across the floor. Nobody claims it.', 'slap'),
    L('Somewhere, a blister pops. Everyone flinches.', 'slap'),
    L('The crowd goes quiet. Even the claw is watching.', 'cine', 'rc'),
    L('A rumor of a {grail} restock ripples through the server.', 'col', 'modern'),
    L('Engines idle. Hands hover over packs. Nobody blinks.', 'cine'),
    L('A tumbleweed of bubble wrap drifts across the track.', 'surreal'),
    L('The Ripper checks the clock and says nothing.', 'cine', 'rc'),
    L('A loose wheel rolls across the desk. Three collectors reach for it. Nobody admits needing a spare.', 'meta'),
]

BANK = {
    "kill": KILL, "wipe": WIPE, "multi": MULTI, "double": DOUBLE, "find": FIND, "call": CALL,
    "transfer": TRANSFER, "survive": SURVIVE, "moment": MOMENT, "revive": REVIVE, "duel": DUEL,
    "win": WIN, "hazard": HAZARD, "ambient": AMBIENT,
}
