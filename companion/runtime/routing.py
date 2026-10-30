"""Small host routing rules. No execution authority or Agent runtime lives here."""
import re

COMPLEX=("修改","删除","执行","运行命令","部署","重构","编写代码","写代码","安装","发邮件","操作电脑","操作gui","agent","shell","delete","deploy","edit file","refactor","风险评估","预算优化","复杂跨文档")


def execution_status_question(question):
    return bool(re.search(r'^(你|您).*(已经|刚才|是否|有没有|已).*?(部署|执行|删除|修改|完成).*?(吗|么|？|\?)',question))


def work_fact_requires_source(question):
    """Narrow direct questions whose answer requires evidence of user work.

    This is a host evidence gate, not model quality or general intent detection.
    Inline context and general knowledge questions stay on the normal path.
    """
    q = question.strip().rstrip("？?。.!！ ")
    fields = r"(?:项目(?:名称|代号|预算|负责人|截止日期)?|当前(?:项目|文件|应用)|正在使用的(?:应用|文件)|文件(?:名称|路径))"
    return bool(re.fullmatch(r"(?:我(?:的)?|当前的|这个|这份)"+fields+r"(?:是|有|为)?(?:什么|多少|谁|哪(?:个|份|天)|什么时候)",q)
                or re.fullmatch(r"what is my (?:project (?:name|code|budget|owner|deadline)|current (?:project|file|app))",q,re.I))


def refers_to_conversation(question):
    return bool(re.search(r"刚才|上轮|前面(?:我|你|我们)?说|之前(?:我|你|我们)说|我们(?:聊过|说过)|"
                          r"what (?:did|have) (?:I|we|you) (?:say|tell)|previous (?:message|conversation)",question,re.I))


def needs_agent(question):
    q=question.lower()
    if execution_status_question(q):return False
    # Casual discussion of a difficult subject is not a request to execute it.
    casual = bool(re.search(r'随便问问|只是好奇|泛泛聊聊|概念|一般来说', q))
    concrete = bool(re.search(r'帮我|替我|请你|请修改|请删除|这些文件|这几份|当前项目', q))
    if casual and not concrete:return False
    if re.search(r'解释|什么意思|含义|定义',q) and not re.search(r'帮我|请你|替我|请修改|请删除|请执行',q):return False
    return any(w in q for w in COMPLEX) or bool(re.search(r'综合.*(财务|合同|法规)|复杂.*(编程|代码|跨文档|分析)|跨文件.*(分析|核对|评估)|(?:对照|核对).*(?:这些|多份|多个).*文件|打开.*(浏览器|电脑)|computer use|控制.*(鼠标|键盘)',q))


def semantic_route_needed(question):
    return bool(re.search(r'比较|对照|综合|分析|核对|方案|compare|analy', question, re.I)) and not bool(re.search(r'随便问问|只是好奇|概念|什么意思|定义', question))


def route_messages(question):
    return [{'role':'system','content':
        '你判断请求路由，不能执行任务。local=简单聊天、短文总结、概念解释、随便问问；'
        'agent=要求修改文件、操作电脑、复杂跨文件核对或规划。只输出JSON，route(local/agent)与confidence(0到1)。'},
        {'role':'user','content':question}]
