# Stage45-MuSiQue 链路完整性与二跳补证诊断

## 实验目的

Stage38 不重新调用回答模型，而是对给定的 20-query contexts 做离线诊断：区分“答案字符串已经出现在上下文”与“多跳支撑链完整出现”。随后它用非 oracle 的二跳追加策略，从当前上下文标题和实体桥接词出发，在干净 GraphRAG candidate pool 中补充可能缺失的第二跳证据。

## 边界说明

- 诊断指标会使用数据集的 support doc_id，因为这是离线评估链路完整性的标注。
- 二跳追加排序不使用 support doc_id、gold answer 或污染标签，只使用 query、当前 sources 的标题/文本实体和 clean candidate 文本。
- 本阶段产出的 targeted contexts 是后续真实 LLM answer run 的输入；当前结论是 source/chain-level proxy，不等同于最终回答提升已经发生。

## 实验设置

- 数据集：`musique`
- 输入 contexts：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_query_bm25_append_top12_contexts.jsonl`
- 回答审计输入：未提供；本阶段不报告 utility 或 attack success。
- clean candidate pool：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag/musique/stage40_debug50_clean_query_ready/output`
- max sources：`14`；每源字符预算：`450`
- 诊断 rows：`20`；targeted context rows：`20`

## 汇总结果

| 方法 | query数 | answer surface | support surface | support hit | full support | chain complete | answer表面但缺链 | partial support | no support | targeted full support | targeted chain complete | full-support gain | avg tokens -> targeted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `stage35_query_bm25_append_top12` | 20 | 0.4000 | 0.4000 | 1.0000 | 0.6000 | 0.6000 | 0.1000 | 0.3000 | 0.0000 | 0.8000 | 0.8000 | 0.2000 | 1594.0 -> 1861.3 |

## 诊断分布

| chain diagnosis | count | rate |
| --- | ---: | ---: |
| `complete_but_unanswered` | 6 | 0.3000 |
| `complete_support_without_answer_surface` | 6 | 0.3000 |
| `answer_surface_without_full_chain` | 2 | 0.1000 |
| `partial_support_missing_second_hop` | 6 | 0.3000 |

## 主要结论

基线 `full_support_hit_rate` 为 `0.6000`，`chain_complete_rate` 为 `0.6000`；这说明多跳上下文不能只用 answer surface 判断，还需要检查完整支撑链。

二跳追加后 `targeted_full_support_hit_rate` 为 `0.8000`，`targeted_chain_complete_rate` 为 `0.8000`，其中 full-support gain 为 `0.2000`。

若 targeted chain complete 仍低，后续重点应转向更强的实体链接、关系词解析和跨文档路径约束；若 source-level 已补齐但回答仍错，则需要进入真实 LLM answer run 与 prompt/裁判层面的误差分析。

## 代表示例

### 示例 1: `2hop__21104_16334`

- 问题：The 2010 study found that what modern population is most closely related to the group that represents at least 70% of Jews worldwide?
- 标准答案：`modern-day Italians`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`partial_support_missing_second_hop` -> `complete_support_without_answer_surface`
- 原始 support hit：`10172`；缺失：`11305`
- 二跳追加：`11305;10329`；其中 support：`11305`
- 桥接词：`Jews; The One That Got Away (Katy Perry song); The Hebrew Bible; The Age of Enlightenment; Islamic Spain and Portugal; North Africa and the Middle East; United States and Israel; In Another Life`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `10172` | Jews | 0 | Document ID: 10172 Title: Jews The Hebrew Bible, a religious interpretation of the traditions and early national history of the Jews, established the first of the Abrahamic religions, which are now practiced by 54% of the world. Judaism guides its adherents in ... |
| 2 | `8260` | The One That Got Away (Katy Perry song) | 0 | Document ID: 8260 Title: The One That Got Away (Katy Perry song) Originally titled ``In Another Life '', the song was produced by Dr. Luke and Max Martin, both of whom co-wrote it with Perry. It is a midtempo pop song positioned on the piece of E major and has ... |
| 3 | `1840` | Allies of World War II | 0 | Document ID: 1840 Title: Allies of World War II At the start of the war on 1 September 1939, the Allies consisted of France, Poland and the United Kingdom, as well as their dependent states, such as British India. Within days they were joined by the independen ... |
| 4 | `9782` | Pope John XXIII | 0 | Document ID: 9782 Title: Pope John XXIII Pope John XXIII did not live to see the Vatican Council to completion. He died of stomach cancer on 3 June 1963, four and a half years after his election and two months after the completion of his final and famed encycl ... |
| 5 | `990` | Aaron Spelling | 0 | Document ID: 990 Title: Aaron Spelling Aaron Spelling (April 22, 1923 – June 23, 2006) was an American film and television producer. Some of his works include the TV programs Charlie's Angels (1976–81), The Love Boat (1977–86), Hart to Hart (1979–84), Dynasty ... |

### 示例 2: `3hop1__324448_831637_91775`

- 问题：What does SEAL stand for in the military branch that operates USS Prevail?
- 标准答案：`Sea, Air, and Land`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`answer_surface_without_full_chain` -> `complete_but_unanswered`
- 原始 support hit：`9736;399`；缺失：`387`
- 二跳追加：`387;235`；其中 support：`387`
- 桥接词：`USS Prevail (AM-107); USS Edsall (DE-129); USS Zigzag (SP-106); The One That Got Away (Katy Perry song); United States Navy; United States Navy.; Seaman Norman Edsall; In Another Life`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `9736` | USS Prevail (AM-107) | 0 | Document ID: 9736 Title: USS Prevail (AM-107) USS "Prevail" (AM-107) was an acquired by the United States Navy for the dangerous task of removing mines from minefields laid in the water to prevent ships from passing. |
| 2 | `396` | USS Edsall (DE-129) | 0 | Document ID: 396 Title: USS Edsall (DE-129) USS "Edsall" (DE-129) was the lead ship of her class of destroyer escort in the United States Navy. She was the second Navy ship named in honor of Seaman Norman Edsall (1873–1899). |
| 3 | `4766` | USS Zigzag (SP-106) | 0 | Document ID: 4766 Title: USS Zigzag (SP-106) USS "Zigzag" (SP-106) was an armed motorboat that served in the United States Navy as a patrol vessel from 1917 to 1919. |
| 4 | `8260` | The One That Got Away (Katy Perry song) | 0 | Document ID: 8260 Title: The One That Got Away (Katy Perry song) Originally titled ``In Another Life '', the song was produced by Dr. Luke and Max Martin, both of whom co-wrote it with Perry. It is a midtempo pop song positioned on the piece of E major and has ... |
| 5 | `6681` | Ommatidae | 0 | Document ID: 6681 Title: Ommatidae The Ommatidae are a family of beetles in the suborder Archostemata. The Ommatidae are considered the extant beetle family that has most ancestral characteristics. Extant species of this group only occur in Australia and South ... |

### 示例 3: `3hop1__694534_160088_73916`

- 问题：What is the average yearly income for a person of the same nationality as the creator of MacGruder and Loud?
- 标准答案：`$72,641`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`partial_support_missing_second_hop` -> `complete_support_without_answer_surface`
- 原始 support hit：`5175;5183`；缺失：`990`
- 二跳追加：`990;2678`；其中 support：`990`
- 桥接词：`MacGruder and Loud; Household income in the United States; Aaron Spelling's; Super Bowl; United States; US Census Bureau; Annual Social and Economic Supplement; Huguenots`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `5183` | MacGruder and Loud | 0 | Document ID: 5183 Title: MacGruder and Loud This was one of the few failures from Aaron Spelling's production company in its history, since it was picked by ABC to debut right after the Super Bowl in 1985 and was heavily promoted during the game. The promotion ... |
| 2 | `5175` | Household income in the United States | 0 | Document ID: 5175 Title: Household income in the United States Another common measurement of personal income is the mean household income. Unlike the median household income, which divides all households in two halves, the mean income is the average income ear ... |
| 3 | `9170` | Huguenots | 0 | Document ID: 9170 Title: Huguenots A term used originally in derision, Huguenot has unclear origins. Various hypotheses have been promoted. The nickname may have been a combined reference to the Swiss politician Besançon Hugues (died 1532) and the religiously ... |
| 4 | `991` | The Wild Women of Chastity Gulch | 0 | Document ID: 991 Title: The Wild Women of Chastity Gulch The Wild Women of Chastity Gulch is a 1982 American made-for-television western romantic comedy film directed by Philip Leacock and starring Priscilla Barnes, Lee Horsley, Joan Collins, Donny Osmond, Mor ... |
| 5 | `1036` | Arizona | 0 | Document ID: 1036 Title: Arizona Arizona ( (listen); Navajo: Hoozdo Hahoodzo Navajo pronunciation: [xòːztò xɑ̀xòːtsò]; O'odham: Alĭ ṣonak Uto-Aztecan pronunciation: [ˡaɺi ˡʂonak]) is a state in the southwestern region of the United States. It is also part of t ... |

### 示例 4: `4hop1__802394_153080_159767_81096`

- 问题：An Indy car race was held in the capital of the state where the performer of Mingus Plays Piano was born. Who won the race?
- 标准答案：`Mario Andretti`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`answer_surface_without_full_chain` -> `complete_but_unanswered`
- 原始 support hit：`1042;962;959`；缺失：`1036`
- 二跳追加：`1036;9333`；其中 support：`1036`
- 桥接词：`Mingus Plays Piano; Capital punishment in New Zealand; Charles Mingus; Household income in the United States; Charles Mingus.; Mingus's de; New Zealand; Arizona. His`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `648` | Capital punishment in New Zealand | 0 | Document ID: 648 Title: Capital punishment in New Zealand Capital punishment in New Zealand first appeared in a codified form when it became a British territory in 1840, and was first employed in 1842. It was last used in 1957, abolished for murder in 1961, an ... |
| 2 | `5175` | Household income in the United States | 0 | Document ID: 5175 Title: Household income in the United States Another common measurement of personal income is the mean household income. Unlike the median household income, which divides all households in two halves, the mean income is the average income ear ... |
| 3 | `1840` | Allies of World War II | 0 | Document ID: 1840 Title: Allies of World War II At the start of the war on 1 September 1939, the Allies consisted of France, Poland and the United Kingdom, as well as their dependent states, such as British India. Within days they were joined by the independen ... |
| 4 | `1531` | 1952 Winter Olympics | 0 | Document ID: 1531 Title: 1952 Winter Olympics Thirty nations sent competitors, which was the highest number of participants at a Winter Games. New Zealand and Portugal took part in the Winter Olympic Games for the first time. Australia, Germany, and Japan retu ... |
| 5 | `10089` | Francis Watson (cricketer) | 0 | Document ID: 10089 Title: Francis Watson (cricketer) The son of a clergyman, Watson was born on a ship in the bay at Saint Helena. He grew up in India before his family moved to Tasmania. He moved to New Zealand, where he worked as a schoolteacher, becoming he ... |

### 示例 5: `2hop__130508_32379`

- 问题：What is the oldest college in the state that contains Borough House Plantation?
- 标准答案：`College of Charles Towne`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`partial_support_missing_second_hop` -> `partial_support_missing_second_hop`
- 原始 support hit：`6100`；缺失：`10101`
- 二跳追加：`913;2678`；其中 support：``
- 桥接词：`Borough House Plantation; Household income in the United States; 2010 United States House of Representatives elections; Sports in the New York metropolitan area; The One That Got Away (Katy Perry song); Borough House; Hillcrest Plantation and Anderson Place; South Carolina Highway`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `6100` | Borough House Plantation | 0 | Document ID: 6100 Title: Borough House Plantation Borough House Plantation, also known as Borough House, Hillcrest Plantation and Anderson Place, is an historic plantation on South Carolina Highway 261, north of its intersection with U.S. Route 76/US Route 378 ... |
| 2 | `5175` | Household income in the United States | 0 | Document ID: 5175 Title: Household income in the United States Another common measurement of personal income is the mean household income. Unlike the median household income, which divides all households in two halves, the mean income is the average income ear ... |
| 3 | `813` | 2010 United States House of Representatives elections | 0 | Document ID: 813 Title: 2010 United States House of Representatives elections Republicans regained control of the chamber they had lost in the 2006 midterm elections, picking up a net total of 63 seats and erasing the gains Democrats made in 2006 and 2008. Alt ... |
| 4 | `5444` | Sports in the New York metropolitan area | 0 | Document ID: 5444 Title: Sports in the New York metropolitan area At Madison Square Garden, New Yorkers can watch the New York Knicks play NBA basketball, while the New York Liberty play in the WNBA. The Barclays Center in Brooklyn is home to the Brooklyn Nets ... |
| 5 | `8260` | The One That Got Away (Katy Perry song) | 0 | Document ID: 8260 Title: The One That Got Away (Katy Perry song) Originally titled ``In Another Life '', the song was produced by Dr. Luke and Max Martin, both of whom co-wrote it with Perry. It is a midtempo pop song positioned on the piece of E major and has ... |

### 示例 6: `2hop__460091_405771`

- 问题：What taxa is Ommatidae part of?
- 标准答案：`Coleoptera`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`partial_support_missing_second_hop` -> `partial_support_missing_second_hop`
- 原始 support hit：`6681`；缺失：`6688`
- 二跳追加：`235;112`；其中 support：``
- 桥接词：`Ommatidae; The Godfather Part II; The Ommatidae; Archostemata. The Ommatidae; Australia and South America; Pangea. So; Francis Ford Coppola; Mario Puzo`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `6681` | Ommatidae | 0 | Document ID: 6681 Title: Ommatidae The Ommatidae are a family of beetles in the suborder Archostemata. The Ommatidae are considered the extant beetle family that has most ancestral characteristics. Extant species of this group only occur in Australia and South ... |
| 2 | `599` | The Godfather Part II | 0 | Document ID: 599 Title: The Godfather Part II The Godfather Part II is a 1974 American crime film produced and directed by Francis Ford Coppola from a screenplay co-written with Mario Puzo, starring Al Pacino and Robert De Niro. Partially based on Puzo's 1969 ... |
| 3 | `1840` | Allies of World War II | 0 | Document ID: 1840 Title: Allies of World War II At the start of the war on 1 September 1939, the Allies consisted of France, Poland and the United Kingdom, as well as their dependent states, such as British India. Within days they were joined by the independen ... |
| 4 | `1531` | 1952 Winter Olympics | 0 | Document ID: 1531 Title: 1952 Winter Olympics Thirty nations sent competitors, which was the highest number of participants at a Winter Games. New Zealand and Portugal took part in the Winter Olympic Games for the first time. Australia, Germany, and Japan retu ... |
| 5 | `1534` | The Messenger (Zusak novel) | 0 | Document ID: 1534 Title: The Messenger (Zusak novel) The Messenger is a 2002 Novel by Markus Zusak, and winner of the 2003 Children's Book Council of Australia Book of the Year Award. |

### 示例 7: `3hop1__9285_5188_63702`

- 问题：When did the country where the top-ranking Warsaw Pact operatives originated, despite its being headquartered in the nation known as the nobilities commonwealth, become allies with the US?
- 标准答案：`June 1941`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`partial_support_missing_second_hop` -> `partial_support_missing_second_hop`
- 原始 support hit：`11191;1840`；缺失：`9750`
- 二跳追加：`387;399`；其中 support：``
- 桥接词：`Warsaw Pact; Allies of World War II; Household income in the United States; In July; Mongolian People's Republic; Europe. Due; Poland and the United Kingdom; British India. Within da`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `11191` | Warsaw Pact | 0 | Document ID: 11191 Title: Warsaw Pact In July 1963 the Mongolian People's Republic asked to join the Warsaw Pact under Article 9 of the treaty. For this purpose a special protocol should have been taken since the text of the treaty applied only to Europe. Due ... |
| 2 | `1840` | Allies of World War II | 0 | Document ID: 1840 Title: Allies of World War II At the start of the war on 1 September 1939, the Allies consisted of France, Poland and the United Kingdom, as well as their dependent states, such as British India. Within days they were joined by the independen ... |
| 3 | `235` | Geography of Myanmar | 0 | Document ID: 235 Title: Geography of Myanmar Myanmar (also known as Burma) is the northwestern-most country of mainland Southeast Asia, bordering China, India, Bangladesh, Thailand and Laos. It lies along the Indian and Eurasian Plates, to the southeast of the ... |
| 4 | `553` | Reserve Officers' Training Corps (Philippines) | 0 | Document ID: 553 Title: Reserve Officers' Training Corps (Philippines) ROTC in the Philippines began in 1912 when the Philippine Constabulary commenced with military instruction at the University of the Philippines. The university's Board of Regents then made ... |
| 5 | `570` | Larry Alcala | 0 | Document ID: 570 Title: Larry Alcala He was born on August 18, 1926 to Ernesto Alcala and Elpidia Zarate in Daraga, Albay. Through a scholarship from Manila Times granted by the publisher Ramón Roces, he obtained a degree of Bachelor of Fine Arts in Painting a ... |

### 示例 8: `3hop1__9285_5188_86687`

- 问题：When did the country the top-ranking Warsaw Pact operatives came from, despite it being headquartered in the country known as the nobilities commonwealth, agree to a unified Germany inside NATO?
- 标准答案：`May 1990`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`partial_support_missing_second_hop` -> `partial_support_missing_second_hop`
- 原始 support hit：`11191;8387`；缺失：`9750`
- 二跳追加：`11305;112`；其中 support：``
- 桥接词：`Warsaw Pact; The Biggest Loser Brunei: Lose It All; In July; Mongolian People's Republic; Europe. Due; The Biggest Loser Brunei; Lose It All; The Biggest Loser. This`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `11191` | Warsaw Pact | 0 | Document ID: 11191 Title: Warsaw Pact In July 1963 the Mongolian People's Republic asked to join the Warsaw Pact under Article 9 of the treaty. For this purpose a special protocol should have been taken since the text of the treaty applied only to Europe. Due ... |
| 2 | `1175` | The Biggest Loser Brunei: Lose It All | 0 | Document ID: 1175 Title: The Biggest Loser Brunei: Lose It All The Biggest Loser Brunei (season 3): Lose It All is the third season of The Biggest Loser Brunei, which is the Bruneian version of the NBC reality television series The Biggest Loser. This season c ... |
| 3 | `1840` | Allies of World War II | 0 | Document ID: 1840 Title: Allies of World War II At the start of the war on 1 September 1939, the Allies consisted of France, Poland and the United Kingdom, as well as their dependent states, such as British India. Within days they were joined by the independen ... |
| 4 | `235` | Geography of Myanmar | 0 | Document ID: 235 Title: Geography of Myanmar Myanmar (also known as Burma) is the northwestern-most country of mainland Southeast Asia, bordering China, India, Bangladesh, Thailand and Laos. It lies along the Indian and Eurasian Plates, to the southeast of the ... |
| 5 | `553` | Reserve Officers' Training Corps (Philippines) | 0 | Document ID: 553 Title: Reserve Officers' Training Corps (Philippines) ROTC in the Philippines began in 1912 when the Philippine Constabulary commenced with military instruction at the University of the Philippines. The university's Board of Regents then made ... |

### 示例 9: `2hop__126306_396277`

- 问题：What is another notable work by the illustrator of Sylvester and the Magic Pebble?
- 标准答案：`Doctor De Soto`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_but_unanswered` -> `complete_but_unanswered`
- 原始 support hit：`7328;7340`；缺失：``
- 二跳追加：`10329;5444`；其中 support：``
- 桥接词：`Sylvester and the Magic Pebble; List of awards and nominations received by Matt Damon; William Steig; Damon and Ben Affleck; Good Will Hunting; Academy Awards; Damon and Affleck Oscars and Golden Globes; Best Screenplay. Damon`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `7328` | Sylvester and the Magic Pebble | 0 | Document ID: 7328 Title: Sylvester and the Magic Pebble Sylvester and the Magic Pebble is an award-winning children's picture book written and illustrated by William Steig, and published in 1969. |
| 2 | `6605` | List of awards and nominations received by Matt Damon | 0 | Document ID: 6605 Title: List of awards and nominations received by Matt Damon Damon and Ben Affleck wrote "Good Will Hunting" (1997), a screenplay about a young math genius, which received nine Academy Awards nominations, earning Damon and Affleck Oscars and ... |
| 3 | `7340` | Doctor De Soto | 0 | Document ID: 7340 Title: Doctor De Soto Doctor De Soto is a picture book for children written and illustrated by William Steig and first published in 1982. It features a mouse-dentist who must help a fox with a toothache without being eaten. |
| 4 | `4495` | Dazed and Confused (film) | 0 | Document ID: 4495 Title: Dazed and Confused (film) Freshman Mitch Kramer (Wiley Wiggins) escapes the initial hazing with his best friend Carl Burnett (Esteban Powell), but is later cornered after a baseball game and violently paddled. Fred O'Bannion (Ben Affle ... |
| 5 | `813` | 2010 United States House of Representatives elections | 0 | Document ID: 813 Title: 2010 United States House of Representatives elections Republicans regained control of the chamber they had lost in the 2006 midterm elections, picking up a net total of 63 seats and erasing the gains Democrats made in 2006 and 2008. Alt ... |

### 示例 10: `2hop__131275_72870`

- 问题：Who did the state where Christian Science Pleasant View Home was located vote for in 2016?
- 标准答案：`Hillary Clinton`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_but_unanswered` -> `complete_but_unanswered`
- 原始 support hit：`9333;9335`；缺失：``
- 二跳追加：`913;911`；其中 support：``
- 桥接词：`Christian Science Pleasant View Home; 2016 United States presidential election in New Hampshire; Household income in the United States; The Christian Science Pleasant View Home; Pleasant Street; New Hampshire; United States; Christian Science Board of Directors`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `9335` | Christian Science Pleasant View Home | 0 | Document ID: 9335 Title: Christian Science Pleasant View Home The Christian Science Pleasant View Home is a historic senior citizen residential facility located at 227 Pleasant Street in Concord, New Hampshire, in the United States, It was built in 1927 by the ... |
| 2 | `9333` | 2016 United States presidential election in New Hampshire | 0 | Document ID: 9333 Title: 2016 United States presidential election in New Hampshire The 2016 United States presidential election in New Hampshire was won by Hillary Clinton by a 0.3 percentage point margin, on November 8, 2016, as part of the 2016 General Elect ... |
| 3 | `5175` | Household income in the United States | 0 | Document ID: 5175 Title: Household income in the United States Another common measurement of personal income is the mean household income. Unlike the median household income, which divides all households in two halves, the mean income is the average income ear ... |
| 4 | `584` | Springfield, Illinois | 0 | Document ID: 584 Title: Springfield, Illinois Springfield's original name was Calhoun, after Senator John C. Calhoun of South Carolina. The land that Springfield now occupies was originally settled by trappers and traders who came to the Sangamon River in 1818 ... |
| 5 | `6240` | Hughesville, Maryland | 0 | Document ID: 6240 Title: Hughesville, Maryland Hughesville is a census-designated place (CDP) in Charles County, Maryland, United States. The population was 2,197 at the 2010 census. Truman's Place was listed on the National Register of Historic Places in 1988 ... |

## 产物路径

- chain rows JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_chain_completeness_rows.jsonl`
- summary CSV：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_chain_completeness_summary.csv`
- targeted contexts JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_second_hop_append_top14_contexts.jsonl`
- examples JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_chain_completeness_examples.jsonl`
