"""Curated self-contained adapters from Content Expansion v2. Source IDs remain traceable."""

ADDITIONS = {'garage': {'survive': [{'text': '{A} finds a magnifying glass beneath the workbench. The tiny wheel '
                                 'markings finally stop looking identical.',
                         'vibe': 'col',
                         'tags': [],
                         'source_id': 'G01'},
                        {'text': '{A} photographs a full-size Bone Shaker display, then returns to the table '
                                 'with the tiny racer that fits their lane.',
                         'vibe': 'col',
                         'tags': [],
                         'source_id': 'G11'},
                        {'text': "{A}'s capsule visits the 1968 package artwork, then the 2008 Custom Otto "
                                 'display. They return with a catalogue note, leaving the models behind.',
                         'vibe': 'surreal',
                         'tags': ['capsule', 'modern'],
                         'source_id': 'adapted-G-C'}],
            'wipe': [{'text': '{A} tightens the new wheel until it rubs against the body. Their Hot Wheels '
                              "stops halfway down the elimination track. They're out.",
                      'vibe': 'col',
                      'tags': [],
                      'source_id': 'G03'},
                     {'text': "{A}'s registered racer rolls off the tilted workbench. A snapped front axle "
                              'ends their run before the next heat.',
                      'vibe': 'col',
                      'tags': [],
                      'source_id': 'G07'}],
            'kill': [{'text': "{A}'s chipped mainline rolls past {B}'s display Hot Wheels in the deciding "
                              'heat. {B} leaves with the nicer paint and no place in the race.',
                      'vibe': 'col',
                      'tags': [],
                      'source_id': 'G04'}],
            'duel': [{'text': "{A}'s Hot Wheels clears the workbench straight first. {B} reaches the finish "
                              'a wheel behind and leaves the elimination bracket.',
                      'vibe': 'col',
                      'tags': [],
                      'source_id': 'G18'}],
            'moment': [{'text': '{A} announces a rare factory error. {B} removes a crumb from the wheel. The '
                                'mystery is over.',
                        'vibe': 'col',
                        'tags': [],
                        'source_id': 'G06'},
                       {'text': '{A} tests the empty lane while {B} checks the table. A folded catalogue '
                                'under one leg levels the track.',
                        'vibe': 'col',
                        'tags': [],
                        'source_id': 'G14'}],
            'find': [{'text': 'The Ripper slides a {model} across the workbench to {A}. A red ribbon marks '
                              'this Hot Wheels for the next heat.',
                      'vibe': 'col',
                      'tags': ['rc'],
                      'holds': 'model',
                      'source_id': 'adapted-G-E'}],
            'call': [{'text': "{H} sends the earlier {item} down the deciding lane. {B}'s entry stalls at "
                              'the loop. {B} is out, and {H} retrieves the Hot Wheels.',
                      'vibe': 'race',
                      'tags': ['rc'],
                      'out': 'B',
                      'source_id': 'adapted-G-B'}],
            'transfer': [{'text': '{H} gifts the {item} to {A}. The same Hot Wheels leaves one '
                                  'display and joins the other.',
                          'vibe': 'warm',
                          'tags': ['rc'],
                          'source_id': 'adapted-G-E'}]},
 'hunt': {'survive': [{'text': '{A} checks the copyright date, then the release reference. The Hot Wheels is '
                               'newer than the number underneath it suggests.',
                       'vibe': 'col',
                       'tags': [],
                       'source_id': 'T01'},
                      {'text': '{A} finds a blue AMX and asks where the Ed Shaver decal sheet went. The '
                               'model name is only half the question.',
                       'vibe': 'col',
                       'tags': [],
                       'source_id': 'T09'},
                      {'text': '{A} finds a Hot Wheels without its usual graphics and checks for repainting '
                               'before describing it as a factory error.',
                       'vibe': 'col',
                       'tags': [],
                       'source_id': 'T15'}],
          'wipe': [{'text': "At the deciding identification desk, {A} uses the wrong year's checklist. Their "
                            'submitted entry fails, ending the hunt.',
                    'vibe': 'col',
                    'tags': [],
                    'source_id': 'T17'}],
          'kill': [{'text': '{B} picks the brighter paint. {A} checks the release details and selects the '
                            'correct Hot Wheels. {B} loses the deciding round.',
                    'vibe': 'col',
                    'tags': [],
                    'source_id': 'T04'}],
          'duel': [{'text': '{B} matches the casting but misses the decoration. {A} submits the requested '
                            'release and takes the final place.',
                    'vibe': 'col',
                    'tags': [],
                    'source_id': 'T18'}]},
 'convention': {'survive': [{'text': '{A} wins the auction lot and opens the box. One display sign, no Hot '
                                     'Wheels. They read the lot description this time.',
                             'vibe': 'col',
                             'tags': [],
                             'source_id': 'C06'},
                            {'text': '{A} finds their convention badge inside the display-case pocket and '
                                     "gets through the door without borrowing anyone else's name.",
                             'vibe': 'col',
                             'tags': [],
                             'source_id': 'C14'},
                            {'text': "{A} examines the Candy Striper's numbered package, then returns it to "
                                     "the owner's display case.",
                             'vibe': 'col',
                             'tags': [],
                             'source_id': 'C16'}],
                'wipe': [{'text': '{A} negotiates over one final colour variation until the race desk '
                                  "closes. Their empty lane costs them the heat. They're out.",
                          'vibe': 'col',
                          'tags': [],
                          'source_id': 'C04'},
                         {'text': "A display trolley jolts into {A}'s loose race Hot Wheels. One bent axle "
                                  'later, {A} has no entry for the deciding heat.',
                          'vibe': 'col',
                          'tags': [],
                          'source_id': 'C07'}],
                'kill': [{'text': "{A}'s stock racer wins by its front wheels. {B} finishes the run, but "
                                  'their convention tournament ends there.',
                          'vibe': 'col',
                          'tags': [],
                          'source_id': 'C17'}],
                'duel': [{'text': '{A} and {B} receive fresh stock Hot Wheels at the race desk. {A} wins the '
                                  'deciding run. {B} leaves the bracket.',
                          'vibe': 'col',
                          'tags': [],
                          'source_id': 'C13'}],
                'moment': [{'text': '{A} takes the stairs while {B} waits with three collectors and six '
                                    'display cases for the elevator.',
                            'vibe': 'col',
                            'tags': [],
                            'source_id': 'C02'},
                           {'text': '{A} and {B} move the disputed colour variation under the neutral '
                                    'inspection lamp. The hotel lighting stops deciding the argument.',
                            'vibe': 'col',
                            'tags': [],
                            'source_id': 'C12'}]},
 'redline': {'survive': [{'text': '{A} moves the Hot Wheels away from the yellow lamp before naming its '
                                  'colour. The argument gets quieter under daylight.',
                          'vibe': 'col',
                          'tags': [],
                          'source_id': 'R02'},
                         {'text': '{A} turns the early Python over. The Cheetah name underneath earns the '
                                  'Hot Wheels a second, longer inspection.',
                          'vibe': 'col',
                          'tags': [],
                          'source_id': 'R06'},
                         {'text': '{A} studies the resin body under the desk lamp. It belongs to the design '
                                  'table, away from the elimination slope.',
                          'vibe': 'col',
                          'tags': [],
                          'source_id': 'R12'}],
             'wipe': [{'text': '{A} sends their registered Hot Wheels down the test slope with a bent axle. '
                               'It scrapes to a halt and fails the elimination run.',
                       'vibe': 'col',
                       'tags': [],
                       'source_id': 'R03'},
                      {'text': "{A}'s racer hits the booster off-centre, clears the table, and lands on its "
                               'front axle. Their race ends there.',
                       'vibe': 'col',
                       'tags': [],
                       'source_id': 'R07'}],
             'kill': [{'text': "{A}'s Twin Mill crosses first in the deciding downhill run. {B} picks up "
                               'their Hot Wheels and leaves the bracket.',
                       'vibe': 'col',
                       'tags': [],
                       'source_id': 'R04'}],
             'duel': [{'text': "{A}'s period racer stays straight through the last bend. {B}'s Hot Wheels "
                               'leaves the lane, and their elimination run ends.',
                       'vibe': 'col',
                       'tags': [],
                       'source_id': 'R20'}]},
 'gulf': {'survive': [{'text': '{A} stops at the wrong blue-and-orange pit board. The crew points one garage '
                               'down before anyone touches the race car.',
                       'vibe': 'race',
                       'tags': ['real_vehicle'],
                       'source_id': 'F06'},
                      {'text': '{A} notices a new vibration and brings the race car into the pits before '
                               'attempting another full-speed lap.',
                       'vibe': 'race',
                       'tags': ['real_vehicle'],
                       'source_id': 'F14'},
                      {'text': '{A} spots the service-road sign before turning off the circuit and stays on '
                               'the marked race route.',
                       'vibe': 'race',
                       'tags': [],
                       'source_id': 'F18'}],
          'wipe': [{'text': "{A}'s oil pressure falls on the straight. They stop behind the barrier, and the "
                            'crew retires the race car.',
                    'vibe': 'race',
                    'tags': ['real_vehicle'],
                    'source_id': 'F03'},
                   {'text': "Loose bodywork folds into {A}'s front tyre on the straight. They stop safely, "
                            'but the damaged wheel ends their race.',
                    'vibe': 'race',
                    'tags': [],
                    'source_id': 'F15'}],
          'kill': [{'text': '{A} holds the inside line through the final corner. {B} finishes behind them '
                            'and loses the elimination duel.',
                    'vibe': 'race',
                    'tags': [],
                    'source_id': 'F04'}],
          'duel': [{'text': '{A} exits the final bend ahead. {B} finishes safely behind them and loses the '
                            'deciding duel.',
                    'vibe': 'race',
                    'tags': [],
                    'source_id': 'F17'}]},
 'nft': {'survive': [{'text': '{A} checks the edition before copying a rarity label from another release of '
                              'the same famous casting.',
                      'vibe': 'col',
                      'tags': [],
                      'source_id': 'N11'},
                     {'text': '{A} moves from the WAX archive shelf to the later Flow exhibit and keeps the '
                              'two collection histories separately labelled.',
                      'vibe': 'col',
                      'tags': [],
                      'source_id': 'N12'},
                     {'text': '{A} enlarges the Hot Wheels preview across the whole wall. The display grows, '
                              'while the labelled die-cast scale stays the same.',
                      'vibe': 'col',
                      'tags': [],
                      'source_id': 'N17'}],
         'wipe': [{'text': '{A} submits a screenshot to the ownership desk. The matching entry belongs to '
                           'another avatar. {A} is out.',
                   'vibe': 'col',
                   'tags': [],
                   'source_id': 'N03'}],
         'kill': [{'text': '{B} selects the right model name but the wrong edition. {A} matches the full '
                           'record and wins the deciding comparison.',
                   'vibe': 'col',
                   'tags': [],
                   'source_id': 'N04'}],
         'duel': [{'text': "{A}'s rendered racer clears the final bend. {B}'s Hot Wheels slides into the "
                           'display barrier, ending their virtual-track run.',
                   'vibe': 'col',
                   'tags': [],
                   'source_id': 'N18'}],
         'moment': [{'text': '{A} and {B} compare matching Hot Wheels images, then notice the different '
                             'edition numbers in their exhibit records.',
                     'vibe': 'col',
                     'tags': [],
                     'source_id': 'N09'}]}}
