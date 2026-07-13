# Stage45-HotpotQA 链路完整性与二跳补证诊断

## 实验目的

Stage38 不重新调用回答模型，而是对给定的 20-query contexts 做离线诊断：区分“答案字符串已经出现在上下文”与“多跳支撑链完整出现”。随后它用非 oracle 的二跳追加策略，从当前上下文标题和实体桥接词出发，在干净 GraphRAG candidate pool 中补充可能缺失的第二跳证据。

## 边界说明

- 诊断指标会使用数据集的 support doc_id，因为这是离线评估链路完整性的标注。
- 二跳追加排序不使用 support doc_id、gold answer 或污染标签，只使用 query、当前 sources 的标题/文本实体和 clean candidate 文本。
- 本阶段产出的 targeted contexts 是后续真实 LLM answer run 的输入；当前结论是 source/chain-level proxy，不等同于最终回答提升已经发生。

## 实验设置

- 数据集：`hotpotqa`
- 输入 contexts：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_bm25_append_top12_contexts.jsonl`
- 回答审计输入：未提供；本阶段不报告 utility 或 attack success。
- clean candidate pool：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag/hotpotqa/stage40_debug50_clean_query_ready/output`
- max sources：`14`；每源字符预算：`450`
- 诊断 rows：`20`；targeted context rows：`20`

## 汇总结果

| 方法 | query数 | answer surface | support surface | support hit | full support | chain complete | answer表面但缺链 | partial support | no support | targeted full support | targeted chain complete | full-support gain | avg tokens -> targeted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `stage35_query_bm25_append_top12` | 20 | 0.8500 | 0.8000 | 1.0000 | 0.9500 | 0.9500 | 0.0000 | 0.0500 | 0.0000 | 0.9500 | 0.9500 | 0.0000 | 1517.0 -> 1761.8 |

## 诊断分布

| chain diagnosis | count | rate |
| --- | ---: | ---: |
| `complete_but_unanswered` | 17 | 0.8500 |
| `complete_support_without_answer_surface` | 2 | 0.1000 |
| `partial_support_missing_second_hop` | 1 | 0.0500 |

## 主要结论

基线 `full_support_hit_rate` 为 `0.9500`，`chain_complete_rate` 为 `0.9500`；这说明多跳上下文不能只用 answer surface 判断，还需要检查完整支撑链。

二跳追加后 `targeted_full_support_hit_rate` 为 `0.9500`，`targeted_chain_complete_rate` 为 `0.9500`，其中 full-support gain 为 `0.0000`。

若 targeted chain complete 仍低，后续重点应转向更强的实体链接、关系词解析和跨文档路径约束；若 source-level 已补齐但回答仍错，则需要进入真实 LLM answer run 与 prompt/裁判层面的误差分析。

## 代表示例

### 示例 1: `5a729cc25542991f9a20c532`

- 问题：Which author wrote about a woman captured by the Symbionese Liberation Army?
- 标准答案：`Paul Avery`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`partial_support_missing_second_hop` -> `partial_support_missing_second_hop`
- 原始 support hit：`5655`；缺失：`5654`
- 二跳追加：`7369;4883`；其中 support：``
- 桥接词：`Lantern Waste; Mr. Tumnus; True (Avicii album); Hey Brother; Cesar Millan; Daddy (dog); Cinderella (1950 film); Bambi`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `4600` | Lantern Waste | 0 | Document ID: 4600 Title: Lantern Waste Lantern Waste is a fictional place in "The Chronicles of Narnia" series by C. S. Lewis. It is a wood and is notable as the place where Lucy Pevensie and Mr. Tumnus meet, which is the first scene of Narnia described in the ... |
| 2 | `4602` | Mr. Tumnus | 0 | Document ID: 4602 Title: Mr. Tumnus Tumnus is a fictional character in C. S. Lewis' series "The Chronicles of Narnia". He is featured prominently in "The Lion, the Witch and the Wardrobe" and also appears in "The Horse and His Boy" and "The Last Battle". He is ... |
| 3 | `4446` | True (Avicii album) | 0 | Document ID: 4446 Title: True (Avicii album) True is the debut studio album by Swedish DJ Avicii. It was released on 13 September 2013 on compact disc and audio cassette through PRMD Music, Lava Records and Sony Music Entertainment's Columbia Records. Avicii s ... |
| 4 | `4447` | Hey Brother | 0 | Document ID: 4447 Title: Hey Brother "Hey Brother" is a dance song by Swedish DJ and producer Avicii from his debut studio album, "True" (2013). American bluegrass singer Dan Tyminski provides vocals for the track. It was written by Avicii, Ash Pournouri, Sale ... |
| 5 | `5609` | Cesar Millan | 0 | Document ID: 5609 Title: Cesar Millan Cesar Millan ( ; born César Felipe Millán Favela, ] ; August 27, 1969) is a Mexican-American dog behaviorist with over 25 years of canine experience. He is widely known for his Emmy-nominated television series "Dog Whisper ... |

### 示例 2: `5a72a6d855429901807daf27`

- 问题：Of four Harry S. Truman Supreme Court candidates, who was the 53rd United States Secretary of the Treasury and the 13th Chief Justice of the United States?
- 标准答案：`Fred M. Vinson`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_but_unanswered` -> `complete_but_unanswered`
- 原始 support hit：`917;922`；缺失：``
- 二跳追加：`7376;3942`；其中 support：``
- 桥接词：`Harry S. Truman Supreme Court candidates; The United States Poker Championship; The Emperor's New Groove; The Late Late Show (U.S. TV series); President Harry S. Truman; Supreme Court of the United States; Chief Justice Fred M. Vinson; Associate Justice Harold Burton`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `917` | Harry S. Truman Supreme Court candidates | 0 | Document ID: 917 Title: Harry S. Truman Supreme Court candidates During his two terms in office, President Harry S. Truman appointed four members of the Supreme Court of the United States: Chief Justice Fred M. Vinson, Associate Justice Harold Burton, Associat ... |
| 2 | `1807` | The United States Poker Championship | 0 | Document ID: 1807 Title: The United States Poker Championship The United States Poker Championship (USPC) was a major annual stop on the poker tournament tour. This event was held at the Trump Taj Mahal in Atlantic City, New Jersey. This series of poker tourna ... |
| 3 | `5194` | The Emperor's New Groove | 0 | Document ID: 5194 Title: The Emperor's New Groove The Emperor's New Groove is a 2000 American animated buddy comedy film created by Walt Disney Feature Animation and released by Walt Disney Pictures. It is the 40th Disney animated feature film. It was directed ... |
| 4 | `7369` | The Late Late Show (U.S. TV series) | 0 | Document ID: 7369 Title: The Late Late Show (U.S. TV series) The Late Late Show is an American late-night television talk and variety show on CBS. It first aired in January 1995, with host Tom Snyder, followed by Craig Kilborn and Craig Ferguson. It is current ... |
| 5 | `8003` | Funnybot | 0 | Document ID: 8003 Title: Funnybot "Funnybot" is the second episode of the fifteenth season of the American animated television series "South Park", and the 211th episode of the series overall. "Funnybot" premiered in the United States on Comedy Central on May ... |

### 示例 3: `5a72a9ac5542991f9a20c55f`

- 问题：Which show co-hosted by Hoda Kotb was produced by Brian Balthazar?
- 标准答案：`the fourth hour of the TODAY Show`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_support_without_answer_surface` -> `complete_support_without_answer_surface`
- 原始 support hit：`7061;7066`；缺失：``
- 二跳追加：`1433;5194`；其中 support：``
- 桥接词：`Brian Balthazar; Hoda Kotb; The Late Late Show (U.S. TV series); The Wendy Williams Show; The Today Show; TV Guide Network and Showbiz Tonight; HLN. He; ABC's The View. As`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `7061` | Brian Balthazar | 0 | Document ID: 7061 Title: Brian Balthazar Brian Balthazar is a TV personality and the executive producer and developer of several programs on broadcast and cable television. He has frequently appeared on television as the editor of the website POPgoesTheWeek.co ... |
| 2 | `7066` | Hoda Kotb | 0 | Document ID: 7066 Title: Hoda Kotb Hoda Kotb ( ; Arabic: هدى قطب‎ ‎ "Hudā Quṭb" ] , born August 9, 1964) is an American television news anchor and TV host known as the co-host of NBC's "Today Show"' s fourth hour with Kathie Lee Gifford. An Egyptian American, ... |
| 3 | `7369` | The Late Late Show (U.S. TV series) | 0 | Document ID: 7369 Title: The Late Late Show (U.S. TV series) The Late Late Show is an American late-night television talk and variety show on CBS. It first aired in January 1995, with host Tom Snyder, followed by Craig Kilborn and Craig Ferguson. It is current ... |
| 4 | `8446` | Maine Legislature | 0 | Document ID: 8446 Title: Maine Legislature The Maine Legislature is the state legislature of the U.S. state of Maine. It is a bicameral body composed of the lower house Maine House of Representatives and the upper house Maine Senate. The Legislature convenes a ... |
| 5 | `8445` | John C. Talbot | 0 | Document ID: 8445 Title: John C. Talbot John Coffin Talbot (1784–1860) was an American businessperson and politician from Maine. Talbot, a Democrat, served 6 one-year terms in the Maine Legislature, including two in the Maine House of Representatives (1825; 18 ... |

### 示例 4: `5a77322055429972597f1494`

- 问题：Which software application was originally made for the company that acquired RadioShack in 1963?
- 标准答案：`DeskMate`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_but_unanswered` -> `complete_but_unanswered`
- 原始 support hit：`400;395`；缺失：``
- 二跳追加：`7369;5191`；其中 support：``
- 桥接词：`For Adults Only; Bill Cosby.; Westgate Las Vegas Resort; International Hotel.; Pearl Bailey LP; Roulette R-25016; Bambi; Westgate Las Vegas Resort &amp; Casino`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `2080` | For Adults Only | 0 | Document ID: 2080 Title: For Adults Only For Adults Only (1971) is the 13th comedy album by Bill Cosby. It was recorded at the Westgate Las Vegas Resort & Casino, then known as the International Hotel. The title "For Adults Only" was also used for a 1959 Pearl ... |
| 2 | `1432` | Bambi | 0 | Document ID: 1432 Title: Bambi Bambi is a 1942 American animated film directed by David Hand (supervising a team of sequence directors), produced by Walt Disney and based on the book "Bambi, a Life in the Woods" by Austrian author Felix Salten. The film was re ... |
| 3 | `2079` | Westgate Las Vegas Resort &amp; Casino | 0 | Document ID: 2079 Title: Westgate Las Vegas Resort &amp; Casino The Westgate Las Vegas Resort & Casino is a hotel and casino in Winchester, Nevada. It is owned by Westgate Resorts and operated by Navegante Group. It has 2,956 hotel rooms including 305 suites. ... |
| 4 | `7376` | Craig Kilborn | 0 | Document ID: 7376 Title: Craig Kilborn Craig Kilborn (born August 24, 1962) is an American comedian, sports and political commentator, and television host. He was the original host of "The Daily Show", a former anchor on ESPN's "SportsCenter", and Tom Snyder's ... |
| 5 | `1807` | The United States Poker Championship | 0 | Document ID: 1807 Title: The United States Poker Championship The United States Poker Championship (USPC) was a major annual stop on the poker tournament tour. This event was held at the Trump Taj Mahal in Atlantic City, New Jersey. This series of poker tourna ... |

### 示例 5: `5a774e9c55429972597f14f3`

- 问题：David Huntsinger has worked with this gospel singer born in the month of July?
- 标准答案：`Larnelle Harris`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_but_unanswered` -> `complete_but_unanswered`
- 原始 support hit：`4466;4470`；缺失：``
- 二跳追加：`4447;3126`；其中 support：``
- 桥接词：`David Huntsinger; Rambos. He; Holy Spirit; Thou Art Welcome; Dottie Rambo; Down By The Creek Bank; A Child; Gift of Lullabyes`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `3500` | The Legend of the Condor Heroes (2017 TV series) | 0 | Document ID: 3500 Title: The Legend of the Condor Heroes (2017 TV series) The Legend of the Condor Heroes is a 2017 Chinese television series adapted from Louis Cha's novel of the same title and a remake of the 1983 Hong Kong television series based on the sam ... |
| 2 | `3507` | Li Yitong (actress) | 0 | Document ID: 3507 Title: Li Yitong (actress) Li Yitong (Chinese: 李一桐, born 6 September 1990) is a Chinese actress. She made her acting debut in 2016 with a leading role in the web series "Demon Girl" by Yu Zheng. In 2017, she played Huang Rong in the televisio ... |
| 3 | `4037` | From Birth to Burial | 0 | Document ID: 4037 Title: From Birth to Burial From Birth to Burial is the seventh studio album by American rock band 10 Years. The album was released on April 21, 2015, through their own independent label called Palehorse Records, which is a part of Warner Mus ... |
| 4 | `4039` | 10 Years (band) | 0 | Document ID: 4039 Title: 10 Years (band) 10 Years is an American alternative metal band, formed in Knoxville, Tennessee in 1999. The band consists of Jesse Hasek (lead vocals), Brian Vodinh (drums, guitar, backing vocals), Chad Huff (bass guitar) and Matt Want ... |
| 5 | `4446` | True (Avicii album) | 0 | Document ID: 4446 Title: True (Avicii album) True is the debut studio album by Swedish DJ Avicii. It was released on 13 September 2013 on compact disc and audio cassette through PRMD Music, Lava Records and Sony Music Entertainment's Columbia Records. Avicii s ... |

### 示例 6: `5a77c74155429967ab105291`

- 问题：Which band formed in England, Of Montreal or Vib Gyor?
- 标准答案：`Vib Gyor was a band that was formed in Leeds, England.`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_but_unanswered` -> `complete_but_unanswered`
- 原始 support hit：`9422;9418`；缺失：``
- 二跳追加：`4037;7376`；其中 support：``
- 桥接词：`Vib Gyor; Of Montreal; 10 Years (band); Kevin Barnes; Jesse Hasek; Brian Vodinh; Chad Huff; Matt Wantland`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `9418` | Vib Gyor | 0 | Document ID: 9418 Title: Vib Gyor Vib Gyor was a band that was formed in Leeds, England. The name was derived from the first letters of all the colours in the rainbow, in order from the shortest to longest wavelengths. |
| 2 | `9422` | Of Montreal | 0 | Document ID: 9422 Title: Of Montreal of Montreal is an American experimental pop band from Athens, Georgia. It was founded by frontman Kevin Barnes in 1996, named after a failed romance between Barnes and a woman "of Montreal." The band is identified as part o ... |
| 3 | `4039` | 10 Years (band) | 0 | Document ID: 4039 Title: 10 Years (band) 10 Years is an American alternative metal band, formed in Knoxville, Tennessee in 1999. The band consists of Jesse Hasek (lead vocals), Brian Vodinh (drums, guitar, backing vocals), Chad Huff (bass guitar) and Matt Want ... |
| 4 | `7369` | The Late Late Show (U.S. TV series) | 0 | Document ID: 7369 Title: The Late Late Show (U.S. TV series) The Late Late Show is an American late-night television talk and variety show on CBS. It first aired in January 1995, with host Tom Snyder, followed by Craig Kilborn and Craig Ferguson. It is current ... |
| 5 | `5609` | Cesar Millan | 0 | Document ID: 5609 Title: Cesar Millan Cesar Millan ( ; born César Felipe Millán Favela, ] ; August 27, 1969) is a Mexican-American dog behaviorist with over 25 years of canine experience. He is widely known for his Emmy-nominated television series "Dog Whisper ... |

### 示例 7: `5a78ed6855429970f5fffdd9`

- 问题：What is the population of the town that gets it's water supply from Canobie Lake?
- 标准答案：`28,776 at the 2010 census`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_but_unanswered` -> `complete_but_unanswered`
- 原始 support hit：`3788;3790`；缺失：``
- 二跳追加：`1807;7369`；其中 support：``
- 桥接词：`Canobie Lake; What I Saw: Reports from Berlin, 1920-1933; Rockingham County; New Hampshire; United States; Salem and Windham.; Canobie Lake Park; The la`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `3788` | Canobie Lake | 0 | Document ID: 3788 Title: Canobie Lake Canobie Lake is a 375 acre body of water located in Rockingham County in southern New Hampshire, United States, in the towns of Salem and Windham. It is approximately 1.5 mi long, and on average 0.4 mi wide, though two arm ... |
| 2 | `8065` | What I Saw: Reports from Berlin, 1920-1933 | 0 | Document ID: 8065 Title: What I Saw: Reports from Berlin, 1920-1933 What I Saw: Reports from Berlin, 1920-1933 is a book of reportage by the Austrian writer Joseph Roth from the era of the Weimar Republic. The selection of pieces from Roth's large journalistic ... |
| 3 | `3790` | Salem, New Hampshire | 0 | Document ID: 3790 Title: Salem, New Hampshire Salem is a town in Rockingham County, New Hampshire, United States. The population was 28,776 at the 2010 census. Salem is a marketing and distributing center north of Boston, with a major amusement attraction, Can ... |
| 4 | `1510` | Birstall Shopping Park | 0 | Document ID: 1510 Title: Birstall Shopping Park Birstall Shopping Park is a shopping park located in Birstall, Batley, West Yorkshire, England. It contains a wide variety of retailers and includes the region's only IKEA store. Adjacent is another retail park, ... |
| 5 | `9289` | Steel Venom (Valleyfair) | 0 | Document ID: 9289 Title: Steel Venom (Valleyfair) Steel Venom is a steel Inverted Impulse roller coaster located at Valleyfair in Minnesota. It reaches a maximum height of 185 feet (56 m) and a top speed of 68 mph (109 km/h). It is similar to the "Wicked Twist ... |

### 示例 8: `5a7a9b9a5542990198eaf160`

- 问题：When was the Chinese American electronic musician and singer who collaborated on the album I Remember born?
- 标准答案：`1989`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_but_unanswered` -> `complete_but_unanswered`
- 原始 support hit：`7314;7312`；缺失：``
- 二跳追加：`9664;3183`；其中 support：``
- 桥接词：`I Remember (AlunaGeorge album); Zhu (musician); True (Avicii album); I Remember; Island Records.; Flume and Pell.; UK Singles Chart; Steven Zhu`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `7314` | I Remember (AlunaGeorge album) | 0 | Document ID: 7314 Title: I Remember (AlunaGeorge album) I Remember is the second studio album by English electronic music duo AlunaGeorge. It was released on 16 September 2016 by Island Records. The album includes collaborations with Popcaan, Zhu, Leikeli47, D ... |
| 2 | `7312` | Zhu (musician) | 0 | Document ID: 7312 Title: Zhu (musician) Steven Zhu (born 1989), known professionally as Zhu ( or ), is a Chinese American electronic musician and singer who has been active since the beginning of 2014, signed to Mind of a Genius Records and Columbia Records. U ... |
| 3 | `4446` | True (Avicii album) | 0 | Document ID: 4446 Title: True (Avicii album) True is the debut studio album by Swedish DJ Avicii. It was released on 13 September 2013 on compact disc and audio cassette through PRMD Music, Lava Records and Sony Music Entertainment's Columbia Records. Avicii s ... |
| 4 | `4037` | From Birth to Burial | 0 | Document ID: 4037 Title: From Birth to Burial From Birth to Burial is the seventh studio album by American rock band 10 Years. The album was released on April 21, 2015, through their own independent label called Palehorse Records, which is a part of Warner Mus ... |
| 5 | `4039` | 10 Years (band) | 0 | Document ID: 4039 Title: 10 Years (band) 10 Years is an American alternative metal band, formed in Knoxville, Tennessee in 1999. The band consists of Jesse Hasek (lead vocals), Brian Vodinh (drums, guitar, backing vocals), Chad Huff (bass guitar) and Matt Want ... |

### 示例 9: `5a80ad205542992bc0c4a79d`

- 问题：Who preceded the man who had the Nassak Diamond cut and placed into the handle of his sword?
- 标准答案：`1st Earl Grosvenor`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_but_unanswered` -> `complete_but_unanswered`
- 原始 support hit：`4015;4013`；缺失：``
- 二跳追加：`3483;922`；其中 support：``
- 桥接词：`Nassak Diamond; The Nassak Diamond; India. Found; Trimbakeshwar Shiva Temple; The British East India Company; Third Anglo-Maratha War; Rundell and Bridge; Marquess of Westminster's`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `4015` | Nassak Diamond | 0 | Document ID: 4015 Title: Nassak Diamond The Nassak Diamond (also known as the Nassac Diamond and the Eye of the Idol) is a large, 43.38 carat diamond that originated as a larger 89 carat diamond in the 15th century in India. Found in the Amaragiri mine located ... |
| 2 | `4013` | Robert Grosvenor, 1st Marquess of Westminster | 0 | Document ID: 4013 Title: Robert Grosvenor, 1st Marquess of Westminster Robert Grosvenor, 1st Marquess of Westminster, {'1': ", '2': ", '3': ", '4': "} (22 March 1767 – 17 February 1845) was the son of the 1st Earl Grosvenor, whom he succeeded in 1802 as 2nd Ea ... |
| 3 | `3480` | William Howard (engineer) | 0 | Document ID: 3480 Title: William Howard (engineer) William Howard (1793–1834) was an American mechanical engineer who was one of the first to work for the Baltimore and Ohio Railroad. When the railroad built its first cars using friction bearings first develop ... |
| 4 | `917` | Harry S. Truman Supreme Court candidates | 0 | Document ID: 917 Title: Harry S. Truman Supreme Court candidates During his two terms in office, President Harry S. Truman appointed four members of the Supreme Court of the United States: Chief Justice Fred M. Vinson, Associate Justice Harold Burton, Associat ... |
| 5 | `9664` | Follow the Yellow Brick Road Tour | 0 | Document ID: 9664 Title: Follow the Yellow Brick Road Tour Follow the Yellow Brick Road Tour is a concert tour by British musician Elton John taking place in North America and Europe in promotion of the 40th anniversary re-release of 1973's Goodbye Yellow Bric ... |

### 示例 10: `5a82edae55429966c78a6a9f`

- 问题：Swiss music duo Double released their best known single "The Captain of Her Heart" in what year?
- 标准答案：`1986`
- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。
- Stage38 诊断：`complete_but_unanswered` -> `complete_but_unanswered`
- 原始 support hit：`3183;3182`；缺失：``
- 二跳追加：`9662;8065`；其中 support：``
- 桥接词：`Double (band); Blue (Double album); The Captain of Her Heart; Woman of the World; Rangoon Moon; Your Prayer Takes Me Off; Pseudaelurus; Follow the Yellow Brick Road Tour`

| rank | doc_id | title | stage38追加 | snippet |
| ---: | --- | --- | ---: | --- |
| 1 | `3182` | Double (band) | 0 | Document ID: 3182 Title: Double (band) Double (pronounced "doo-blay") was a Swiss music duo best known for their hit single "The Captain of Her Heart". |
| 2 | `3183` | Blue (Double album) | 0 | Document ID: 3183 Title: Blue (Double album) Blue is the first full-length album from Swiss band Double. In addition to containing updated versions of two of the band's earlier singles ("Woman of the World" and "Rangoon Moon"), the album included the internati ... |
| 3 | `8076` | Pseudaelurus | 0 | Document ID: 8076 Title: Pseudaelurus Pseudaelurus is a prehistoric cat that lived in Europe, Asia and North America in the Miocene between approximately 20 to 8 million years ago. It is an ancestor of today's felines and pantherines as well as the extinct mac ... |
| 4 | `9664` | Follow the Yellow Brick Road Tour | 0 | Document ID: 9664 Title: Follow the Yellow Brick Road Tour Follow the Yellow Brick Road Tour is a concert tour by British musician Elton John taking place in North America and Europe in promotion of the 40th anniversary re-release of 1973's Goodbye Yellow Bric ... |
| 5 | `4335` | Luzhniki Stadium | 0 | Document ID: 4335 Title: Luzhniki Stadium Luzhniki Stadium (Russian: Стадион «Лужники» ; ] ), is a sports stadium in Moscow, Russia. Its total seating capacity is 81,000 seats, all covered (upgraded). The stadium is a part of the Luzhniki Olympic Complex, and ... |

## 产物路径

- chain rows JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_chain_completeness_rows.jsonl`
- summary CSV：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_chain_completeness_summary.csv`
- targeted contexts JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_second_hop_append_top14_contexts.jsonl`
- examples JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_chain_completeness_examples.jsonl`
