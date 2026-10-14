"""Compile the manually reviewed public-source prospect list; no model calls."""
from pathlib import Path
import csv, hashlib, html, json, shutil

OUT = Path(__file__).resolve().parent
RAW = Path('/tmp/wechat-prospects')
rows = []

def add(name, search, kind, area, activity, evidence, signal, opportunity, caveat, *urls):
    rows.append(dict(name=name, wechat_search=search, customer_type=kind, area=area,
                     activity=activity, interview_evidence=evidence, demand_signal=signal,
                     proposed_use=opportunity, caveat=caveat, urls=list(urls),
                     video_account_id='未取得：需视频号主页核验'))

add('大树AI创业圈', '大树AI创业圈', '个人/小团队', 'AI创业', '2026系列线索',
    '2026-02-12第50期视频号访谈，嘉宾渊虹（森创启睿CEO）；公开采访提到采访100位用AI赚钱的人。',
    '有第10期MCN老板火火访谈观点短片等生产行为；未发现采购表态。', '创业案例、商业模式和收入方法分成独立短片。',
    '访谈第50期有转载实录；先核对视频号同名主页、最近三场及切片负责人。',
    'https://xueqiu.com/8806655095/376624702',
    'https://finance.sina.com.cn/wm/2026-06-14/doc-inicipvz0908648.shtml',
    'https://www.douyin.com/video/7506903846183111962?source=360Spider-sdc',
    'https://podcasts.apple.com/cn/podcast/72-%E5%A4%A7%E6%A0%91-%E9%87%87%E8%AE%BF100%E4%BD%8D%E7%94%A8ai%E8%B5%9A%E9%92%B1%E7%9A%84%E4%BA%BA-%E7%94%A8ai%E8%B5%9A%E7%AC%83%E5%AE%9A%E7%9A%84%E9%92%B1/id1760676812?i=1000747579803')
add('李一诺', '李一诺Y.L', '个人/小团队', '教育/成长', '2025系列；2026频率待核验',
    '本人节目介绍明确视频号@李一诺Y.L，不定期与专家、学者、作者直播对谈；2025有孙瑞雪及严飞、刘擎等对谈。',
    '直播内容再次加工成播客；短视频需求推断。', '育儿问题、人生选择和金句切片。',
    '是不定期栏目，不能描述成周更；嘉宾孙瑞雪不另算一个已验证客户。',
    'https://www.xiaoyuzhoufm.com/episode/68c24b9b2c82c9dccacd77f9',
    'https://www.cnwomen.com.cn/2025/03/07/99719112.html',
    'https://www.xiaoyuzhoufm.com/episode/680f19757a449ae858239c1d')
add('凉子访谈录', '凉子访谈录', '创作者团队', '人物/人生故事', '2026直播预告与持续视频发布',
    '公开账号有2026-08入殓师韩云直播预告；好看视频账号的预告说明视频号/B站同步对谈，长期人物访谈。',
    '已有大量人物访谈视频和短片发布。', '人物经历中的转折、冲突和完整观点切片。',
    '“北京青年x凉子访谈录”按同一团队合并；短片可能含录播采访，需核对直播素材占比。',
    'https://www.163.com/dy/media/T1639645838770.html',
    'https://haokan.baidu.com/haokan/wiseauthor?app_id=1685020005331327',
    'https://www.bilibili.com/video/BV1WG411N7DX/')
add('京城教育圈', '京城教育圈', '垂直媒体团队', '升学/教育', '2026系列明确',
    '2026-05-25预告列出5月26、28、29、30日学校访谈；自2022年连续做视频号中招直播，2026近百所学校报名。',
    '多平台与家长社群联动；切片需求推断。', '把每场校长访谈拆成招生政策、特色班和择校问答。',
    '季节性集中开播；不能把学校嘉宾当独立主播客户。',
    'https://www.163.com/dy/article/KTQEEI5T0536JW7T.html',
    'https://news.sohu.com/a/901194453_113042')
add('EduKnow / EduTalk', 'EduKnow', '垂直媒体团队', '国际教育/留学', '2026多场明确',
    '2026-03美高系列在EduKnow视频号对谈；4月还有艺术留学、Brian程楚铭等不同场直播。',
    '官方媒体矩阵、多场教育直播；切片需求推断。', '申请策略、学校差异、家长问答系列短片。',
    'EduTalk是节目名称，与EduKnow合并，不重复计数。',
    'https://news.qq.com/rain/a/20260318A01USA00',
    'https://news.qq.com/rain/a/20260422A01IYH00',
    'https://news.qq.com/rain/a/20260417A01YQ700',
    'http://eduknow.cn/index.html')
add('见实 / 徐志斌', '见实', '垂直媒体团队', '私域/增长', '2026系列明确',
    '2026-01-28至02-13全域增长系列：每场1位嘉宾约90分钟、视频号连麦或腾讯会议推流；2024系列已完成39期。',
    '明确把优质直播转成深度文章/白皮书；短片需求推断。', '品牌实操案例、增长方法、反常识观点切片。',
    '有主持对话也有PPT单讲，产品要筛选访谈场次。',
    'https://www.163.com/dy/article/KKCLMUGA053144S4.html',
    'https://m.163.com/dy/article/JKB9ECM1053144S4.html')
add('清华大学出版社 / 陈国妍', '清华大学出版社；栏目“妍知有理”', '机构内小团队', '作者/知识对谈', '历史系列；有2026联合直播',
    '2024主播陈国妍说明“妍知有理”视频号对谈流程，提到每周1场计划；2026-09与中国教师报联合对谈。',
    '明确人员不足：找嘉宾、沟通、宣传、效果汇总等由一人承担；没有明确采购表态。',
    '自动提取作者金句、生成主题切片与字幕，减少一人运营负担。',
    '采访同时说当年只自播2次、准备需两周，不能将计划频率当实际周更；账号是出版社，非“妍知有理”独立号。',
    'http://www.chinawriter.com.cn/n1/2024/0517/c403994-40237919.html',
    'https://www.163.com/dy/article/L6D4IH8T0516DRAR.html?spss=dy_author')
add('韩叙 / 韩叙的朋友们', '韩叙HanXu', '个人/小团队', '运营/个人商业', '历史直播系列；内容持续更新',
    '2022本人复盘6月5场、7月排期4场视频号连麦；“韩叙的朋友们”节目持续更新。',
    '本人经营短视频、直播、播客多种内容形态。', '个人创业、运营增长和AI应用的观点切片。',
    '近期播客活跃不等于近期访谈直播活跃；先核实2026直播频率。',
    'https://www.woshipm.com/operate/5523651.html',
    'https://www.xiaoyuzhoufm.com/podcast/61e1b91af452bd1d3cdf4758',
    'https://m.huxiu.com/club/2073.html')
add('Miki粥', 'Miki粥', '个人/小团队', '国际教育/育儿', '历史周更访谈；当前多平台经营',
    '2022“教育，我有一个问题”在Miki粥视频号，每周邀请校长、老师或专家连麦；公开官网仍经营视频号和直播。',
    '官网明确视频号爆款和多平台观点视频制作。', '一次教育访谈拆成多个家长关心的独立问题。',
    '官网无更新时间；需要核实当下访谈频率。公开mikizhou520是公众号ID，不是视频号ID。',
    'https://new.qq.com/rain/a/20220419A02EHN', 'https://www.mikizhou.cn/',
    'https://www.163.com/dy/article/HALFQR7S05386T63.html')
add('赵健', '赵健的读书日记', '创作者团队', '读书/作家访谈', '2025—2026多场明确',
    '2025-12-28《人民文学》主编与作家做客视频号；2026-05有马家辉对谈预告，另有山峰、刘勃等历年对谈。',
    '中国作家网明确报道直播精彩片段、金句以视频切片传播。', '作者观点、阅读建议和故事高潮切片。',
    '已有团队和切片能力，适合测节省工时；需求是生产行为证据，非采购意愿。',
    'http://www.chinawriter.com.cn/n1/2026/0105/c403994-40639274.html',
    'https://weibo.com/1817124807/R1CjJ7SsF',
    'https://www.163.com/dy/article/JA97PH35051283QA.html')
add('申怡', '领读人申怡；另核对“申怡读书”', '创作者团队', '阅读/家庭教育', '历年多场；2026嘉宾线索',
    '2022视频号与Miki粥、纪连海分别对谈；2026-09作家周桦公开说明做客其直播间两小时。',
    '多平台直播与教育内容经营；切片需求推断。', '学习方法、亲子阅读、文史金句短片。',
    '近期作家帖未明确直播平台；历史视频号名为领读人申怡，当前名称需主页核验。',
    'https://news.sina.cn/sx/2022-09-15/detail-imqqsmrn9197205.d.html',
    'https://www.sohu.com/a/621776734_120476712',
    'https://weibo.com/1349932500/RhlTT36Gv?mod=weibotime')
add('张萌（作家萌姐）', '张萌；核对青创/萌姐身份', '创作者团队', '商业/成长', '历史大型系列；近期访谈频率待核验',
    '2022“张萌会客厅”已邀百位大咖，在微信视频号直播对谈。',
    '明确长期视频号作品发布、知识内容传播。', '商业方法、成长经验与嘉宾金句批量切片。',
    '同名演员很多；以青创品牌、作家萌姐身份核验，不能仅按姓名加好友。',
    'https://roll.sohu.com/a/615552256_100251370',
    'https://m.sohu.com/a/625290190_100251370/')
add('吴婷 / 嘉宾商学', '吴婷；核对嘉宾商学身份', '创作者团队', '企业家/商业', '历史周更；2025访谈短片仍发布',
    '2022公开说明每周四20:00视频号商业对谈；嘉宾包括管清友、任泽平，2025继续有不同企业家访谈。',
    '2025李泉访谈明确发布“访谈精彩片段”。', 'CEO战略、行业反差、创业经历短片。',
    '“我有嘉宾”“嘉宾商学”“吴婷”合并；2025短片不自动证明每周直播仍持续。',
    'http://news.sohu.com/a/574208677_461469',
    'https://cj.sina.com.cn/articles/view/6804861660/19599f2dc00101088d',
    'https://www.douyin.com/video/7532073332838092072')
add('此念文化 / 毛思翩', '此念毛思翩；此念文化', '创作者团队', '教育/心理/成长', '历史系列；2026对谈预告线索',
    '2022武志红、2023教育Jeff等直播对谈；2026出版社预告齐锐与毛思翩视频号对话。',
    '既有长对谈，也有数十秒/数分钟观点短片。', '亲子关系、生命成长、心理观点切片。',
    '有来源把“毛思翩”误写“毛诗篇”；名称与当前主页待确认，非新增两个客户。',
    'https://www.bilibili.com/video/BV1jV4y1f79U/',
    'https://www.douyin.com/video/7126838265189092642',
    'https://weibo.com/2119887771/R7qDUB1sF',
    'https://v.qq.com/x/page/g0880d263q5.html')
add('WeLegal法盟', 'WeLegal法盟；栏目“法盟有约”', '垂直媒体团队', '法律职业/法务', '历史高频系列；近期活跃待核验',
    '2022-04复盘：自2月17日有约20小时视频号连麦，每周二、四、六；官网保留法盟有约栏目。',
    '既有嘉宾访谈衍生短视频；切片提效需求推断。', '法务实务、职业选择、法律方法论问答。',
    '先核对2026频率；法律观点必须保留适用前提。官网栏目名不是视频号唯一ID。',
    'https://www.sohu.com/a/534548889_328962', 'https://www.welegal.net/col.jsp?id=144',
    'https://www.douyin.com/video/7181418023574670650')
add('郝波', '郝老板内参', '个人/小团队', '宠物行业/经营', '历史高频系列；近期活跃待核验',
    '有赞官方案例：100天连线200位嘉宾，视频号为郝老板内参；另有18位嘉宾精选音频合集。',
    '访谈内容再加工成精选合集。', '宠物店经营、品牌策略、行业判断短片。',
    '案例主要2021—2022，必须核实栏目是否仍在更新。',
    'https://www.youzan.com/cms/article/7746.html',
    'https://finance.sina.com.cn/tech/2021-08-18/doc-ikqciyzm2174270.shtml',
    'https://www.ximalaya.com/album/60660296')
add('任泽平 / 泽平宏观', '泽平宏观', '创作者团队', '经济/产业/科技', '历史多场；近期频率待核验',
    '2023大咖会客厅公开列出于丹、尹烨、施展、吴晓波、冯仑等多场视频号对谈；2024韩壁丞脑机接口对谈。',
    '成熟视频内容与长对谈经营；切片提效需求推断。', '产业趋势、创业实践、技术商业化观点短片。',
    '不是单纯讲市场行情的直播；先确认最近的双人对谈排期和现有剪辑流程。',
    'https://business.sohu.com/a/704408113_467568',
    'https://www.163.com/dy/article/J39CLBB10519NINF.html')
add('秋叶大叔', '秋叶；核对秋叶大叔/秋叶PPT身份', '创作者团队', '个人品牌/写作', '历史多场；近期活跃待核验',
    '2021四小时图书作者连麦、本人元宵三嘉宾视频号复盘；2022本人提及百场连麦。',
    '本人短视频、直播、写书私房课内容矩阵。', '写作方法、个人IP和职业故事切片。',
    '新文章/课程经营不能替代当下访谈直播频率证据；同名账号多。',
    'https://www.sohu.com/a/463234846_642641',
    'https://www.zhihu.com/pin/1348948722592714752',
    'https://weibo.com/1280110097/L9G0K1brX')
add('潘乱 / 乱翻书', '潘乱；栏目“乱翻书”', '个人/小团队', '科技/商业', '历史系列；2026视频号对话线索',
    '2020与极客公园张鹏视频号直播；公开主页说每周三与从业者连麦，2026春节AI红包对话来自潘乱视频号直播间。',
    '直播对话沉淀为播客、视频，已有跨平台发布。', '互联网产品判断、AI趋势、商业争议片段。',
    '每周三频率来自2023主页；2026场次需在本人主页核对，不能用同名“大潘”娱乐直播。',
    'https://www.sohu.com/a/438159332_114819',
    'https://www.ixigua.com/home/1668114531/',
    'https://bbs.hupu.com/637377418.html',
    'https://m.sohu.com/a/557710340_120091539/')
add('张德芬空间', '张德芬空间', '创作者团队', '女性/心理成长', '2026多场明确',
    '2026-02张德芬×武志红，4月29日张德芬×陈芳谊三小时视频号对谈。',
    '团队有视频内容传播和深度直播。', '关系、情绪、女性成长主题切片。',
    '张德芬个人与空间合并；先了解现有剪辑团队是否需要节省时间。',
    'https://www.xhby.net/content/s69ef09bce4b0aa176c2a87ce.html',
    'https://news.tom.com/202602/4241424928.html',
    'https://k.sina.com.cn/article_5734996980_155d51bf4019011f8n.html')
add('李筱懿', '李筱懿', '创作者团队', '女性成长/知识', '2026系列经营明确',
    '2026报道视频号持续深耕直播，列举凯文·凯利、梁鸿、阿明·福尔克等不同对谈；历史为隔周知识对谈。',
    '已有成熟短视频和直播内容矩阵。', '成长建议、认知反差、家庭教育切片。',
    '“灵魂有香气的女子”与李筱懿合并；大型团队可能已有成熟流程。',
    'https://m.tech.china.com/hea/articles/20260522/202605221875524.html',
    'https://www.sohu.com/a/706649210_121438824',
    'http://sqtv.net/news/bencandy.php?fid=32&id=215609')
add('刘润 / 刘润·进化者', '刘润', '创作者团队', '商业/知识访谈', '2025访谈视频生产；近期直播频率待核验',
    '2022视频号对话小马宋；历年吴军、凯文·凯利直播回放；2025本人复盘访谈视频制作。',
    '明确讲访谈高光片段、开头楔子、视频团队和剪法迭代。', '在现有团队流程中测试选段、字幕和批量导出是否提效。',
    '《进化者》既有录播也有直播，不能把全部访谈都写成视频号直播。',
    'https://cj.sina.com.cn/articles/view/1401122990/538370ae02701eqjq',
    'https://maimai.cn/article/detail?efid=3eYkhn2OZ6PUnDPicwldLw&fid=1733430185',
    'https://www.bilibili.com/video/BV1jV4y1277i/')
add('吴晓波频道', '吴晓波频道', '创作者团队', '企业/制造业', '2026多场明确',
    '2026-03-20卡拉羊张新华、3月31日双鹿电池朱祥奎，均吴晓波频道视频号实地对谈直播。',
    '成熟财经内容传播；切片提效需求推断。', '制造业转型、品牌经营、企业家金句。',
    '实地走访镜头多，除双人分屏模板外可能需多机位模板。',
    'https://finance.sina.com.cn/wm/2026-03-19/doc-inhrnqzz8758014.shtml',
    'https://finance.sina.com.cn/cj/2026-03-31/doc-inhsvshh5890737.shtml')
add('正和岛', '正和岛', '商业内容机构', '企业家/经营', '历史系列；近期访谈直播待核验',
    '2022企业家“十日谈”系列，视频号等平台直播；历年持续企业家内容与视频。',
    '已有企业家视频发布、活动内容复用。', '经营观点、企业家故事与圆桌论点切片。',
    '2025大型课程活动不等于访谈系列仍在播；优先联系内容团队而非企业家嘉宾。',
    'http://news.sohu.com/a/579513357_157640',
    'https://news.qq.com/rain/a/20220610A04BBC00',
    'https://k.sina.com.cn/article_2268916473_m873ceaf903301aabc.html')
add('樊登 / 帆书', '樊登；帆书原樊登读书', '创作者团队', '读书/作者', '2025多场明确',
    '2025-03阿来在帆书视频号对谈，2025-12刘震云在樊登视频号；长期读书访谈矩阵。',
    '负责人公开讨论视频号内容生产与传播。', '作者金句、阅读解释、人物观点短片。',
    '两个账号按同一运营集团计1个；主页名称需确认，现有团队可能已有工具。',
    'https://cul.sohu.com/a/961807273_121948389',
    'https://book.douban.com/subject/36841338/discussion/637778976/',
    'https://m.ebrun.com/500244.html')
add('InfoQ', 'InfoQ', '科技媒体团队', 'AI/开发者', '2026多场明确',
    '2026-05小红书与快手AI Coding对话，7月WAIC三天连麦技术大佬、创业者，在InfoQ视频号播出。',
    '多平台视频发布和技术对话素材。', '技术决策、AI实战案例和观点分段。',
    'AI前线、霍太稳等按极客邦运营体系合并，不凭联合播出另凑客户。',
    'http://m.163.com/dy/article/KTF2CKCI0511D3QS.html',
    'https://weibo.com/1746173800/R7KtjAfgA?mod=weibotime',
    'https://www.163.com/dy/article/JOP3VDL005566ZHB.html?spss=dy_author')
add('量子位', '量子位', '科技媒体团队', 'AI/科技', '2026直播；历史访谈系列',
    '2026-09预告9月29日两位嘉宾AI行业视频号直播；有长期创始人对话与视频访谈档案。',
    '已有访谈视频分发。', 'AI产品判断、创业路线、商业化观点短片。',
    '历史对话可能录播，需确认当下访谈直播频率和素材格式。',
    'https://finance.sina.com.cn/wm/2026-09-22/doc-inistexc1928998.shtml',
    'https://www.bilibili.com/video/av220097341/',
    'https://www.bilibili.com/video/BV1hB4y1e75s/')
add('中国教师报', '中国教师报', '教育媒体团队', '教师成长/家庭教育', '2026多场明确',
    '2026-08-25王志彬阅读与研学对话、9月教师节彭凯平×刘国正、9月22日两位班主任成长对谈，均明确中国教师报视频号。',
    '已有密集视频号知识直播和教育内容传播；切片需求推断。', '教学方法、教师成长、亲子教育问题短片。',
    '含单讲和对谈，试用选择有主持问答的场次；清华大学出版社联合场次不重复当独立主持证明。',
    'https://news.qq.com/rain/a/20260824A07NY200',
    'https://www.163.com/dy/article/L6D4IH8T0516DRAR.html',
    'https://news.qq.com/rain/a/20260922A062R900')
add('极客公园 / Founder Park', '极客公园；Founder Park；创业真人秀', '科技媒体团队', '科技创业', '历史高频系列；近期频率待核验',
    '2021春节7场视频号直播，2022春节6场；子品牌创业真人秀历史每周双更、21位创业者访谈。',
    '明确希望创业者观点被更多人看到，已有媒体视频矩阵。', '技术创业故事、产品认知、创业问答切片。',
    '2026转载“今天想和你聊聊天”正文注明首发2022-06-09，不能当2026开播证据；同一集团计1个。',
    'https://xueqiu.com/7748174714/172245002',
    'https://www.163.com/dy/article/GV260TRU05119FMA.html',
    'https://www.163.com/dy/article/L800DCD705119FMA.html')
add('高山科学经典', '高山科学经典', '科普组织团队', '科学/跨界知识', '历史编号系列；2026周更线索',
    '2023第67、70期不同科学家导读对谈，官方文章指向视频号回放；2026-01本人微博仍说明每周六20:00直播。',
    '明确沉淀专业导读视频；已有科学知识短视频。', '科学误区、跨学科金句和生活应用短片。',
    '部分场为单讲导读而非访谈；2026微博可能复用历史口播，仍需核对近三场，博雅小学堂联播不另计客户。',
    'https://tech.ifeng.com/c/8JFx5QeCAJb',
    'https://new.qq.com/rain/a/20230724A08Q1C00',
    'https://new.qq.com/rain/a/20230815A07U6Y00',
    'https://weibo.com/7745670089/Qn6RzbSem',
    'https://www.douyin.com/user/MS4wLjABAAAArkEioUx7ZEvYyl0zSbTVdXwWr0QApP9UQwMkVKmj-z4')
add('南都观察家', '南都观察家', '公益/社会议题团队', '社会/教育', '历史多场；近期活跃待核验',
    '2023强AI法律社会伦理对谈通过南都观察家视频号直播；2022职教、老龄化等多场年度对话。',
    '对谈内容文字回顾及多平台传播；切片需求推断。', '社会议题中的独立论点和问答。',
    '不是南方都市报所有账号的统称；先核实当前栏目和内容审核需求。',
    'https://laiw.scu.edu.cn/web/news/8a8383bc87327cbe0187b31a697c0017',
    'https://www.163.com/dy/article/HCLO7PL60516IJIT.html?spss=dy_author',
    'https://m.sohu.com/a/612793838_354821/')
add('新京报书评周刊', '新京报书评周刊', '文化媒体团队', '读书/文化', '2024—2025多场明确',
    '2024罗新、淡豹视频号对谈；2025刘亮程、王德威新书直播；长期书评作者活动。',
    '公开资料明确有视频号短视频发布。', '作者观点、读书推荐、文化问题切片。',
    '联合出版社场次不自动意味着各联合方都是独立高频主播；需核实2026更新。',
    'https://www.bjnews.com.cn/detail/1732170597168983.html',
    'https://www.bjnews.com.cn/detail/1757231999168810.html',
    'https://k.sina.com.cn/article_6315462594_1786e4fc2019015du6.html')
add('理想国', '理想国imaginist', '出版内容团队', '文学/思想', '2024系列；当前更新待核验',
    '2024年底多日视频号编辑对谈；有线上沙龙第034期及多期文化对谈档案。',
    '已有视频栏目和长对谈分发。', '作者/译者观点、书中问题、思想金句。',
    '沙龙档案不全是视频号直播；需看当下直播排期。',
    'https://www.sohu.com/a/842046302_100152450',
    'https://www.163.com/dy/article/JK8NK6TP0521C1P6.html',
    'https://www.bilibili.com/video/BV1ss421M7Y6/')
add('上海译文出版社', '上海译文；译文CLUB', '出版内容团队', '文学/翻译', '2023—2026多场线索',
    '2023女性写作对谈、2024魔戒译文CLUB对谈、2026-07李梓新与陈楸帆直播在上海译文等视频号播出。',
    '官方有短视频账号与作品发布。', '翻译/阅读方法、作家经历、文化金句。',
    '译文CLUB按同一出版社合并；最新场是联合直播，需核对独立主持频率。',
    'https://www.sohu.com/a/682915756_99895237',
    'https://www.weibo.com/1644944655/NDPSZplBT',
    'https://www.163.com/dy/article/L1PT14950521KJO0.html',
    'https://www.douyin.com/user/MS4wLjABAAAAtAoSSRZdNWUNNaQUL6IIvrXXEFWbd0jyTT19egiOXFWAMbUaDdvlugaIA8RPXCBY')
add('人民文学出版社', '人民文学出版社', '出版内容团队', '文学/作者', '历史多场；近期频率待核验',
    '2023世界读书日27场线上活动与作者对谈，2022鲁豫、文铮文学咖啡，2024上海成都作家联合活动。',
    '作者对谈和多平台读书内容传播。', '文学观点、人物经历、书单短片。',
    '“八点一刻”是视频号官方活动/入口，不是出版社自有子账号；近期主持频率需确认。',
    'https://cul.sohu.com/a/671678503_161795',
    'https://www.sohu.com/a/560908912_222493',
    'https://www.thepaper.cn/newsDetail_forward_28307070')
add('中国人民大学出版社', '中国人民大学出版社；CRUP大家谈', '出版内容团队', '人文/知识', '历史编号系列；近期频率待核验',
    '2022-08 CRUP大家谈视频号首两期；公开视频档案已有第36期。',
    '有系列长对谈和编辑/作者视频内容。', '知识问答、作者方法论、书中核心论点。',
    'CRUP大家谈是栏目；先核对官方主页名称与2026直播排期。',
    'https://m.sohu.com/a/573680819_121118940/',
    'https://www.sohu.com/a/573931144_121118940',
    'https://www.bilibili.com/video/BV1oP4y1m7Ai/')
add('北京大学出版社', '北京大学出版社', '出版内容团队', '人文/教育', '2024—2025多场；2026对话视频线索',
    '2024-08解亘、李昊债法总论深度对谈在北大社视频号；2025读书节多项活动，2026-09徐泓、许知远对话视频。',
    '出版社经营视频与直播内容。', '人文思想、阅读建议、教育观点切片。',
    '2026对话微博视频不等于视频号直播；年度读书节内并非全部场次都是访谈。',
    'https://www.163.com/dy/article/JAMU0QHG052182I6.html',
    'http://www.163.com/dy/article/JTLIPE6O052182I6.html',
    'https://www.weibo.com/1844297217/Ri23hrk8Q')
add('商务印书馆', '商务印书馆；商务印书馆学术中心', '出版内容团队', '学术/阅读', '2024—2025多场',
    '2025-01孙立天《康熙的红票》对谈回放在商务印书馆视频号；2024日新文库专家对谈在学术中心视频号直播。',
    '有直播档案和学术内容传播。', '专家论点、读书方法和历史知识切片。',
    '部分活动为讲座而非访谈；需逐场选择双人对谈。',
    'https://news.qq.com/rain/a/20250214A06O1M00',
    'https://www.cp.com.cn/Content/2024/09-02/1441457014.html',
    'https://www.sohu.com/a/870318246_228930',
    'https://www.sohu.com/a/758457531_228930')
add('广西师范大学出版社', '广西师大出版社；广西师范大学出版社', '出版内容团队', '文学/人文', '2026多场明确',
    '2026-03“请听她说”年度对谈，7月14日“今晚编辑有空”直播间+编辑对谈，7月22日该系列第14期；视频号播出。',
    '官方已有作者短视频、预告与视频内容。', '作家故事、书中问题、编辑荐书短片。',
    '集团有多个出版品牌；本表按出版社团队计1个，当前认证名称待核验。',
    'https://weibo.com/1345667185/Quyrzhs5Q',
    'https://weibo.com/1345667185/R7B6eBkkL',
    'https://weibo.com/1345667185/R9SvGwazC',
    'https://www.thepaper.cn/newsDetail_forward_29737780',
    'https://k.sina.com.cn/article_1345667185_m5035407103301k7nc.html')
add('十月杂志', '十月杂志', '文学期刊团队', '文学/作家', '2025编号系列；2026联合直播',
    '2025第五、第七期直播；2026-07李梓新、陈楸帆活动在十月杂志等视频号同步。',
    '作家访谈节目与直播内容传播。', '作家经历、创作方法与文学金句。',
    '“十月杂志”与北京十月文艺出版社不是同一主体，不能混用；近期独立访谈频率待主页核验。',
    'https://www.sohu.com/a/966863667_121124729',
    'https://cul.sohu.com/a/955360198_121124729',
    'https://www.163.com/dy/article/L1PT14950521KJO0.html')
add('湛庐文化', '湛庐文化', '出版内容团队', '商业/科技/心理', '2026多场明确',
    '2026-03-05周健工与安烨90分钟视频号对谈，4月另有总编余杰丰等作者活动。',
    '已有知识短视频与作者内容经营。', 'AI知识、商业方法、专家观点切片。',
    '科学育儿谈等旗下栏目合并；2026-03场主持为安烨，不是韩焱。',
    'https://www.163.com/dy/article/KN1UQBSN0541TTA7.html',
    'https://news.qq.com/rain/a/20260415A085LM00',
    'https://www.douyin.com/video/7341340541579250963')
add('经典947', '经典947', '广播/融媒体团队', '音乐/艺术家', '历史周更；2026嘉宾对话',
    '“七分音符”每周三20:00视频号直播；2026-01“静候嘉音”艺术家对话，历史空中音乐节多位嘉宾连线。',
    '广播节目视频化、嘉宾对话内容传播。', '音乐家故事、知识解释和艺术观点短片。',
    '演奏部分有音乐授权与多机位要求；优先访谈讲话部分，不能只套访谈模板处理音乐会。',
    'https://www.thepaper.cn/newsDetail_forward_25383175',
    'https://www.thepaper.cn/newsDetail_forward_19043350',
    'https://www.sina.cn/news/detail/5257995006771250.html')
add('959电台', '959电台', '广播/融媒体团队', '城市/民生访谈', '2025系列；2026改版线索',
    '2025两会声音系列在959电台视频号；12月15日两场主持嘉宾访谈，2026改版仍有959会客厅嘉宾节目。',
    '视频号直播和民生传播矩阵。', '居民关心的政策问答、人物故事和服务解释。',
    '需找到节目制片/新媒体运营者；官媒团队采购流程可能较长。',
    'https://www.163.com/dy/article/JLQABT9H0514BN8F.html',
    'https://www.163.com/dy/article/KGOFPV0N0514BN8F.html',
    'https://blog.sina.com.cn/s/blog_4aa618c601033k3p.html')
add('上海图书馆', '上海图书馆', '公共文化团队', '人文/文化对谈', '2026多场明确',
    '2026-01-18波德里亚对谈全文说明完整版回放在上海图书馆视频号；7月李梓新、陈楸帆等对谈，历年每周活动。',
    '已有完整回放及文字精华复用。', '文化观点、专家问答、阅读启发短片。',
    '线下活动同步直播，多人舞台画面需要模板适配；机构客户非个人主播。',
    'https://www.thepaper.cn/newsDetail_forward_32498388',
    'https://www.163.com/dy/article/L1PT14950521KJO0.html',
    'https://www.sohu.com/a/744402548_121124801')
add('腾讯自选股财经 / 投资会客厅', '腾讯自选股财经', '财经内容团队', '产业/投资', '2025多场明确',
    '投资会客厅2025-03金山云、6月物流装备、12月优必选，视频号等多平台直播。',
    '成熟财经直播与多平台传播；切片需求推断。', '产业解释、专家问答、技术商业化观点短片。',
    '联合泡财经等出品，先识别剪辑责任团队；所有观点保留时间与前提，非投资建议包装。',
    'https://www.163.com/dy/article/KFP1CSQ80552KYAK.html',
    'https://xueqiu.com/3124808626/337943676',
    'https://xueqiu.com/3124808626/329604959')
add('全景网 / 全景财经', '全景财经；全景网', '财经媒体团队', '投资/企业', '历史多场；持续视频栏目',
    '2023北交所系列第二场、人工智能圆桌在全景财经视频号；官网持续制作董事长、创客与科技领袖财经视频。',
    '明确制作和传播财经视频；有数分钟人物观点短片。', '企业人物、产业观点、圆桌问答切片。',
    '与腾讯自选股联播不作为独立主持依据；这里用全景自己组织的历史场次，当前频率待核验。',
    'https://finance.sina.com.cn/money/fund/jjzl/2023-04-26/doc-imyrtprr4744462.shtml',
    'https://finance.sina.com.cn/money/fund/jjzl/2023-07-05/doc-imyzrzqk9526601.shtml',
    'https://www.p5w.net/v/', 'https://www.iqiyi.com/v_19rx3yw10w.html')
add('婚姻与家庭杂志 / 勇赫大叔', '婚姻与家庭杂志', '杂志/知识团队', '家庭教育/儿童安全', '历史连续7周；近期频率待核验',
    '2022-07-13至08-24每周三14:00—16:00，勇赫大叔主持，视频号每周连麦一位专家，连续7周。',
    '家庭知识传播和专家连麦系列；切片需求推断。', '把食品、居家、网络等儿童安全问题分别剪成短问答。',
    '公众号持续更新不证明目前仍高频直播；需核实新的系列排期。',
    'https://www.163.com/dy/article/HCS812NJ05459162.html',
    'https://www.sohu.com/a/545317598_121106994')
add('中信书院 / 中信出版', '中信书院；中信出版集团', '出版内容团队', '商业/知识/人文', '历史多场；2025访谈内容经营',
    '2022诗歌对谈视频号同步，2023王石、管清友等直播；旗下知本论持续嘉宾访谈并引导关注中信书院视频号。',
    '明确访谈短片：知本论火箭专题、大师聊新知系列。', '商业知识、作者洞见、嘉宾观点切片。',
    '知本论播客未必直播；同一出版集团计1个，不将书院和出版另凑客户。',
    'https://m.sohu.com/a/562897677_99936888/',
    'https://xueqiu.com/6440197329/256627011',
    'https://podcasts.apple.com/cn/podcast/%E7%9F%A5%E6%9C%AC%E8%AE%BA/id1662186888',
    'https://www.xiaoyuzhoufm.com/episode/68cbc8b0a56ca3e0c41211cd',
    'https://www.douyin.com/video/7359509544982138146')
add('单向空间', '单向历；单向空间', '文化内容团队', '文学/作家', '历史系列；近期频率待核验',
    '2023南方聚会多场作家对谈，单向历视频号预约直播，余秀华、易小荷及许知远、陈侗、曹雨等不同场次。',
    '系列文化活动与视频内容分发；切片需求推断。', '文学金句、作家观点和人物故事短片。',
    '账号名以当时单向历为据，当前主页待核验；不把许知远个人节目另算。',
    'https://www.sohu.com/a/670469489_611314',
    'https://www.sohu.com/a/668088284_611314',
    'https://www.sohu.com/a/668745714_611314')
add('三联生活周刊 / 中读', '三联生活周刊；中读', '文化媒体团队', '人文/城市/知识', '历史多场；当前视频内容经营',
    '2022三联和朋友们图书活动视频号直播，2024花园城市嘉宾讨论视频号观看4.3万；中读也有知识对谈直播。',
    '多平台视频栏目和长活动内容传播。', '人文观点、城市议题、知识问答切片。',
    '集团内容账号合并计1个；需区分记者访谈录播、论坛同步直播与常态访谈直播。',
    'https://item.btime.com/41ajendv4038caqaui08b7jskkr',
    'https://3g.163.com/dy/article/HF9OP6SQ0550WCN1.html',
    'https://finance.sina.com.cn/wm/2022-01-19/doc-ikyakumy1398565.shtml')

# Attach evidence exactly as retrieved; snippets are not promoted to full-page verification.
searches = [json.loads(p.read_text()) for p in RAW.glob('*.json')]
pages = [json.loads(p.read_text()) for p in (RAW/'pages').glob('*.json')]
by_url = {p['url']: p for p in pages}
indexed = {}
for s in searches:
    for r in s.get('results', []):
        if 'ai.so.com' not in r['url']:
            indexed.setdefault(r['url'], []).append(dict(query=s['query'], **r))
for i, r in enumerate(rows, 1):
    r['number'] = i
    r['priority'] = ('先核验/试用' if i <= 19 else '团队合作候选')
    public_ids = {
        'Miki粥': '公众号ID：mikizhou520；官网商务微信：mikizhou000（均非视频号ID）',
        '韩叙 / 韩叙的朋友们': '公众号/视频号：韩叙HanXu；本人节目介绍说明公众号回复9可进入听友群（非唯一ID）',
        '高山科学经典': '官方公开小助手微信：GASA2017；内容合作邮箱：info@gasauniversity.org（2023原文，需确认仍有效；非视频号ID）',
        '中信书院 / 中信出版': '知本论公开商务合作/嘉宾推荐邮箱：sunbingjie@citicpub.com（Apple播客搜索摘要，需确认仍有效；非视频号ID）',
    }
    r['public_identifier'] = public_ids.get(r['name'], '使用上列公开名称搜索；唯一ID未取得')
    r['sources'] = []
    for u in r.pop('urls'):
        p = by_url.get(u)
        matched = indexed.get(u, [])
        if not matched:
            # URL tracking parameters or host variants may differ; retain original URLs in evidence.
            stem = u.split('?')[0].rstrip('/')
            for k, vals in indexed.items():
                if k.split('?')[0].rstrip('/') == stem:
                    matched += vals
        readable = bool(p and p.get('status') == 200 and '视频号' in p.get('text','')
                        and not ('xueqiu.com' in u))
        r['sources'].append(dict(url=u, page_snapshot_available=bool(p),
                                 evidence_access='正文含视频号证据' if readable else '公开搜索摘要/辅助档案',
                                 search_evidence=matched))

assert len(rows) == 50 and len({r['name'] for r in rows}) == 50
OUT.mkdir(exist_ok=True)
(OUT/'prospects.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
(OUT/'evidence').mkdir(exist_ok=True)
selected_urls = {s['url'] for r in rows for s in r['sources']}
for p in pages:
    if p['url'] in selected_urls:
        key = hashlib.sha256(p['url'].encode()).hexdigest()[:12]
        (OUT/'evidence'/f'{key}.json').write_text(json.dumps(p, ensure_ascii=False, indent=2))
(OUT/'evidence'/'search-index.json').write_text(json.dumps([
    s for s in searches if any(r['url'].split('?')[0].rstrip('/') in
    {u.split('?')[0].rstrip('/') for u in selected_urls} for r in s.get('results', []))
], ensure_ascii=False, indent=2))

intro = '''# 微信访谈直播产品：50个客户线索

检索日期：2026-10-12。对象按一个创作者/运营团队计数；机构的实际使用者通常是主持人、新媒体运营或剪辑负责人。

**这是50个有公开证据的潜在客户线索，不是50个已确认有购买意愿的客户。** 名单覆盖多场访谈/系列直播与视频号内容经营；部分是历史栏目，2026持续高频与切片需求需要进一步核验。每条明确写出证据、实际活动时间、需求线索与待确认事项。

微信视频号入口先出现“为了你的账号安全，请重新登录”，再次打开也未取得可用主页。因此本次通过公开预告、本人复盘、媒体报道和视频档案检索，未取得主页唯一视频号ID或微信原生直播卡片。**微信搜索名称不是唯一ID。** 所附是公开活动/回放证据链接，不把报道链接称为微信直播直链。无姓名推测微信号，无私下联系或购买意愿推测。

需求标签的含义：①已有短视频/切片生产，说明业务需要这种内容，但不证明要买新工具；②人员或制作压力，来自本人公开说明；③切片需求推断，依据长访谈和多平台经营，必须在访谈中确认。

先看个人和垂直小团队：大树AI创业圈、李一诺、Miki粥、韩叙、WeLegal法盟；以及有明确一人运营压力的清华大学出版社“妍知有理”。已有切片证据的赵健、吴婷、刘润更适合做现有流程与工具的工时对比。历史账号先问近期是否仍做访谈直播，再判断试用价值。

公开联系线索：Miki粥官网的商务微信 **mikizhou000**；高山科学经典官方文章的小助手微信 **GASA2017**、内容合作邮箱 **info@gasauniversity.org**；中信书院知本论的商务邮箱 **sunbingjie@citicpub.com**（后者仅搜索摘要）。均有对应来源，历史联系人需确认有效；不把这些标识称为视频号ID。

筛选步骤：在微信搜表中的名称 → 核对认证主体/主持人 → 查看最近3场访谈与最近10条视频 → 记录真实直播频率、现有剪辑工时和每周产出 → 再确认愿不愿用一场素材试剪。不要直接把嘉宾当主持人客户。

## 名单索引

| # | 创作者 / 运营团队 | 微信搜索名称（不是唯一ID） | 领域 | 活跃证据范围 |
|---|---|---|---|---|
'''
lines = [intro]
for r in rows:
    lines.append(f"| {r['number']:02d} | {r['name']} | {r['wechat_search']} | {r['area']} | {r['activity']} |")
lines += ['\n## 逐条证据与需求线索\n']
for r in rows:
    lines += [f"### {r['number']:02d} · {r['name']}\n",
              f"- 微信搜索：**{r['wechat_search']}**；{r['public_identifier']}。",
              f"- 用户类型：{r['customer_type']}；领域：{r['area']}。",
              f"- 活动时间/频率：{r['activity']}。",
              f"- 访谈直播证据：{r['interview_evidence']}",
              f"- 发布/切片需求线索：{r['demand_signal']}",
              f"- 可测试用途（产品判断）：{r['proposed_use']}",
              f"- 待确认：{r['caveat']}", '- 公开来源：']
    for j, s in enumerate(r['sources'], 1):
        title = s['search_evidence'][0]['title'] if s['search_evidence'] else f'公开资料 {j}'
        lines.append(f"  - [{title}]({s['url']}) — {s['evidence_access']}。")
    lines.append('')
lines += ['## 使用边界\n',
          '公开预告证明排期，不自动证明活动如期发生；回放/本人复盘更强。检索页日期可能是转载或抓取时间，名单以正文活动时间为准。无法读取的来源保留搜索摘要，不能视为全文验证。',
          '\n大型团队同样可能使用本产品，但不是个人主播早期验证的首选。建议优先验证小团队的“每场直播剪辑时间、每周切片量、人工审片是否可接受”，再决定是否推向机构。',
          '\n已合并同一团队别名；未纳入只当嘉宾、只有音频播客、无法建立视频号访谈关联的对象。没有向目标用户发消息。']
(OUT/'客户线索-50个.md').write_text('\n'.join(lines))
fields = [('number','序号'),('name','创作者/团队'),('wechat_search','微信搜索名称'),
          ('video_account_id','视频号唯一ID'),('public_identifier','公开标识'),
          ('customer_type','用户类型'),('area','领域'),('activity','活跃证据范围'),
          ('interview_evidence','访谈直播证据'),('demand_signal','需求线索'),
          ('proposed_use','可测试用途'),('caveat','待确认事项'),('priority','跟进分类')]
with (OUT/'客户线索-50个.csv').open('w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f); w.writerow([label for key,label in fields]+['公开来源链接','来源读取范围'])
    for r in rows:
        w.writerow([r[key] for key,label in fields]+[
            '\n'.join(s['url'] for s in r['sources']),
            '\n'.join(s['evidence_access'] for s in r['sources'])])

esc = html.escape
cards = []
for r in rows:
    links = ''.join(f'<li><a href="{esc(s["url"], quote=True)}" target="_blank" rel="noopener">来源 {j}</a> · {esc(s["evidence_access"])}</li>' for j,s in enumerate(r['sources'],1))
    cards.append(f'''<article><h2>{r['number']:02d} · {esc(r['name'])}</h2>
    <p class="meta">{esc(r['customer_type'])} · {esc(r['area'])} · {esc(r['activity'])}</p>
    <p><b>微信搜索：</b>{esc(r['wechat_search'])}<br><small>{esc(r['public_identifier'])}</small></p>
    <p><b>访谈证据：</b>{esc(r['interview_evidence'])}</p>
    <p><b>需求线索：</b>{esc(r['demand_signal'])}</p>
    <p><b>可测试用途：</b>{esc(r['proposed_use'])}</p>
    <p class="note"><b>待确认：</b>{esc(r['caveat'])}</p><ul>{links}</ul></article>''')
doc = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>微信访谈直播 · 50个客户线索</title><style>
body{margin:0;background:#f6f7f9;color:#222;font:16px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1000px;margin:auto;padding:36px 20px}h1{line-height:1.3}h2{font-size:21px;margin:0}p{margin:12px 0}.intro,article{background:white;border:1px solid #e1e5eb;padding:24px;border-radius:12px;margin:18px 0}.meta,small{color:#68737e}.note{background:#fff7e6;padding:12px;border-radius:8px}a{color:#126a50}input{box-sizing:border-box;width:100%;padding:14px;border:1px solid #c6cfd7;border-radius:8px;font:inherit}#count{color:#68737e}article[hidden]{display:none}ul{padding-left:22px}@media print{input,#count{display:none}article{break-inside:avoid}body{background:white}}
</style><main><h1>微信访谈直播<br>50个客户线索</h1><p>公开资料检索 · 2026-10-12 · 按运营团队去重</p>
<div class="intro"><b>50个潜在客户线索，购买意愿尚未确认。</b><p>包含近期与历史系列，活跃范围逐条标注。切片需求有些来自已有生产行为，有些是产品判断。微信视频号主页目前未能访问，所以账号唯一ID尚未取得；搜索名称不是ID。来源为公开预告、回放档案或报道，不是微信原生直播卡片。</p>
<p>优先看大树AI创业圈、李一诺、Miki粥、韩叙、WeLegal法盟和清华大学出版社“妍知有理”。赵健、吴婷、刘润已有切片/访谈视频生产证据，可比较现有剪辑工时。历史栏目先确认近期仍开播。</p>
<p>已找到公开商务联系线索：Miki粥 <b>mikizhou000</b>；高山科学经典 <b>GASA2017</b> / <b>info@gasauniversity.org</b>；中信书院知本论 <b>sunbingjie@citicpub.com</b>。非视频号ID，出处及有效性限制见对应条目。</p>
<p><a href="客户线索-50个.csv">下载CSV表格</a> · <a href="客户线索-50个.md">阅读完整文档</a></p></div>
<input id="query" aria-label="搜索客户线索" placeholder="搜索姓名、领域、2026、个人、切片…"><p id="count">显示 50 / 50</p>
''' + ''.join(cards) + '''<p>未联系目标用户。公开的发布行为不等于采购意愿；活动预告不自动证明如期举行。部分来源只取得搜索摘要，页面读取范围逐条标注。</p></main>
<script>const q=document.getElementById('query'),cards=[...document.querySelectorAll('article')];q.addEventListener('input',()=>{const term=q.value.trim().toLowerCase();let n=0;cards.forEach(c=>{c.hidden=!c.textContent.toLowerCase().includes(term);if(!c.hidden)n++});document.getElementById('count').textContent=`显示 ${n} / 50`})</script></html>'''
(OUT/'客户线索-50个.html').write_text(doc)
print(json.dumps(dict(records=len(rows), selected_sources=len(selected_urls),
                     saved_pages=len(list((OUT/'evidence').glob('*.json'))),
                     indexed_sources=sum(bool(s['search_evidence']) for r in rows for s in r['sources'])), ensure_ascii=False))
