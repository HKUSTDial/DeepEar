"""
AlphaEar 工具包层 - Agno Toolkit 适配器
复用 utils 中的底层工具实现，提供 Agno Agent 兼容的 Toolkit 接口
"""
from datetime import datetime
from typing import Optional
from agno.tools import Toolkit
from loguru import logger

from utils.database_manager import DatabaseManager
from utils.news_tools import NewsNowTools, PolymarketTools
from utils.stock_tools import StockTools
from utils.search_tools import SearchTools
from utils.sentiment_tools import SentimentTools
from utils.youcom_search import YoucomResearchEngine


class NewsToolkit(Toolkit):
    """
    新闻工具包 - 包装 NewsNowTools 为 Agno Toolkit
    
    提供热点新闻获取、内容提取等功能
    """
    
    def __init__(self, db: DatabaseManager, **kwargs):
        self._news_tools = NewsNowTools(db)
        self._sources = self._news_tools.SOURCES
        
        tools = [
            self.fetch_hot_news,
            self.fetch_news_content,
            self.get_unified_trends,
            self.enrich_news_content,
        ]
        super().__init__(name="news_toolkit", tools=tools, **kwargs)


    def fetch_hot_news(self, source_id: str, count: int = 10) -> str:
        """
        从指定新闻源获取热点新闻列表。
        
        Args:
            source_id: 新闻源标识符。可选值按类别:
                **金融类**: "cls" (财联社), "wallstreetcn" (华尔街见闻), "xueqiu" (雪球)
                **综合类**: "weibo" (微博热搜), "zhihu" (知乎热榜), "baidu" (百度热搜),
                           "toutiao" (今日头条), "douyin" (抖音), "thepaper" (澎湃新闻)
                **科技类**: "36kr" (36氪), "ithome" (IT之家), "v2ex", "juejin" (掘金),
                           "hackernews" (Hacker News)
                推荐金融分析使用 "cls", "wallstreetcn", "xueqiu"。
            count: 获取的新闻数量，默认 10 条。
        
        Returns:
            热点新闻列表的文本描述，包含排名、标题和链接。如果源不可用则返回错误信息。
        """
        logger.info(f"🔧 [TOOL CALLED] fetch_hot_news(source_id={source_id}, count={count})")
        
        items = self._news_tools.fetch_hot_news(source_id, count=count, fetch_content=False)
        
        if not items:
            return f"获取 {source_id} 热点失败"
        
        source_name = self._sources.get(source_id, source_id)
        result = f"## {source_name} 热点 (获取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
        
        for item in items:
            result += f"{item['rank']}. {item['title']}\n   链接: {item['url']}\n\n"
        
        logger.info(f"✅ [TOOL SUCCESS] Got {len(items)} news items from {source_id}")
        return result

    def fetch_news_content(self, url: str) -> str:
        """
        使用 Jina Reader 抓取指定 URL 的网页正文内容。
        
        Args:
            url: 需要抓取内容的完整网页 URL，必须以 http:// 或 https:// 开头。
        
        Returns:
            提取的网页正文内容，如果失败则返回错误信息。
        """
        content = self._news_tools.fetch_news_content(url)
        if content:
            return content[:5000]  # 限制长度
        return "内容抓取失败"

    def get_unified_trends(self, sources: str = "wallstreetcn,cls") -> str:
        """
        获取多平台综合热点报告。
        
        Args:
            sources: 要扫描的新闻源，用逗号分隔。
                     可选值: weibo, zhihu, baidu, toutiao, wallstreetcn, cls
                     默认: "wallstreetcn,cls" (金融资讯)
        
        Returns:
            格式化的热点汇总报告。
        """
        source_list = [s.strip() for s in sources.split(",")]
        report = self._news_tools.get_unified_trends(source_list)
        return report

    def enrich_news_content(self, source: str = None, limit: int = 5) -> str:
        """
        为数据库中缺少正文内容的新闻补充内容。
        
        Args:
            source: 筛选特定新闻源（如 "cls"），为空则处理所有。
            limit: 最多处理的新闻数量，默认 5 条。
        
        Returns:
            处理结果的描述。
        """
        logger.info(f"🔧 [TOOL CALLED] enrich_news_content(source={source}, limit={limit})")
        
        # 获取需要补充内容的新闻
        news_items = self._news_tools.db.get_daily_news(source=source, limit=limit)
        items_without_content = [n for n in news_items if not n.get('content')]
        
        if not items_without_content:
            return "没有需要补充内容的新闻"
        
        updated_count = 0
        cursor = self._news_tools.db.conn.cursor()
        
        for item in items_without_content[:limit]:
            url = item.get('url')
            if url:
                content = self._news_tools.fetch_news_content(url)
                if content:
                    cursor.execute(
                        "UPDATE daily_news SET content = ? WHERE id = ?",
                        (content[:10000], item['id'])
                    )
                    updated_count += 1
        
        self._news_tools.db.conn.commit()
        logger.info(f"✅ [TOOL SUCCESS] Enriched {updated_count} news items with content")
        
        return f"✅ 已为 {updated_count} 条新闻补充正文内容"


class PolymarketToolkit(Toolkit):
    """
    Polymarket 预测市场工具包 - 获取热门预测市场数据
    
    预测市场数据可反映公众情绪、预期和关注度
    """
    
    def __init__(self, db: DatabaseManager, **kwargs):
        self._poly_tools = PolymarketTools(db)
        
        tools = [
            self.get_prediction_markets,
            self.get_market_summary,
        ]
        super().__init__(name="polymarket_toolkit", tools=tools, **kwargs)
    
    def get_prediction_markets(self, limit: int = 20) -> str:
        """
        获取 Polymarket 活跃预测市场的关键数据。
        
        预测市场反映公众对重大事件的概率预期，可用于:
        - 分析市场情绪和风险偏好
        - 了解热门话题的关注度
        - 获取重大事件的概率预期
        
        Args:
            limit: 获取的市场数量，默认 20 个。
        
        Returns:
            预测市场数据列表，包含问题、结果概率和交易量。
            如果获取失败返回错误信息。
        """
        logger.info(f"🔧 [TOOL CALLED] get_prediction_markets(limit={limit})")
        
        markets = self._poly_tools.get_active_markets(limit)
        if not markets:
            return "❌ 无法获取 Polymarket 数据（可能是网络问题）"
        
        result = f"## 🔮 Polymarket 热门预测 (共 {len(markets)} 个)\n\n"
        for i, m in enumerate(markets[:limit], 1):
            question = m.get("question", "Unknown")
            prices = m.get("outcomePrices", [])
            volume = m.get("volume", 0)
            
            result += f"{i}. **{question}**\n"
            if prices:
                result += f"   概率: {prices}\n"
            if volume:
                try:
                    result += f"   交易量: ${float(volume):,.0f}\n"
                except:
                    result += f"   交易量: {volume}\n"
            result += "\n"
        
        logger.info(f"✅ [TOOL SUCCESS] Got {len(markets)} prediction markets")
        return result
    
    def get_market_summary(self, limit: int = 10) -> str:
        """
        获取预测市场摘要报告，了解当前热门话题和公众预期。
        
        Args:
            limit: 获取的市场数量，默认 10 个。
            
        Returns:
            格式化的预测市场报告。
        """
        return self._poly_tools.get_market_summary(limit)


class StockToolkit(Toolkit):

    """
    股票工具包 - 包装 StockTools 为 Agno Toolkit
    
    提供股票搜索、价格查询等功能
    """
    
    def __init__(self, db: DatabaseManager, **kwargs):
        self._stock_tools = StockTools(db)
        
        tools = [
            self.search_ticker,
            self.get_stock_price,
        ]
        super().__init__(name="stock_toolkit", tools=tools, **kwargs)

    def search_ticker(self, query: str) -> str:
        """
        模糊搜索 A 股股票代码或名称。
        
        Args:
            query: 搜索关键词，可以是股票代码（如 "600519"）或名称关键词（如 "茅台"、"宁德"、"比亚迪"）。
        
        Returns:
            匹配的股票列表，包含代码和名称。
        """
        q = (query or "").strip()
        # Guardrails: prevent overly generic queries that tend to return arbitrary "...股份" matches.
        generic_terms = {
            "股份",
            "有限公司",
            "概念股",
            "受益股",
            "龙头",
            "标的",
            "相关股票",
            "合作概念股",
        }
        if not q:
            return "查询为空，无法搜索股票"
        if q in generic_terms:
            return f"查询过于泛化（{q}），为避免误匹配已拒绝。请提供更具体的公司名或6位代码。"
        # If it's not a numeric code, require at least 2 non-space chars.
        if not any(ch.isdigit() for ch in q) and len(q.replace(" ", "")) < 2:
            return "查询过短，无法搜索股票。请提供更具体的公司名或6位代码。"

        results = self._stock_tools.search_ticker(query)
        
        if not results:
            return f"未找到匹配 '{query}' 的股票"
        
        output = f"## 股票搜索结果 (关键词: {query})\n\n"
        for r in results:
            output += f"- {r['code']} - {r['name']}\n"
        return output

    def get_stock_price(self, ticker: str, days: int = 30) -> str:
        """
        获取指定股票的近期价格走势。
        
        Args:
            ticker: 股票代码，如 "600519"（贵州茅台）或 "000001"（平安银行）。
            days: 查询天数，默认 30 天。
        
        Returns:
            价格走势的文本摘要。
        """
        from datetime import timedelta
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        df = self._stock_tools.get_stock_price(ticker, start_date, end_date)
        
        if df.empty:
            return f"未能获取 {ticker} 的股价数据"
        

        latest = df.iloc[-1]
        change = ((latest['close'] - df.iloc[0]['close']) / df.iloc[0]['close']) * 100
        
        # 格式化历史数据供 LLM 分析 (取最近 15 天)
        history_df = df.tail(15).copy()
        history_df['date'] = history_df['date'].astype(str)
        # 简化列名以节省 token
        history_cols = ['date', 'open', 'close', 'high', 'low', 'volume']
        
        # 尝试使用 markdown 格式，如果失败退回到 string
        try:
             history_str = history_df[history_cols].to_markdown(index=False, numalign="left", stralign="left")
        except ImportError:
             history_str = history_df[history_cols].to_string(index=False)
        except Exception:
             history_str = history_df[history_cols].to_string(index=False)

        return f"""## {ticker} 价格走势 ({days}天)
- 当前价: ¥{latest['close']:.2f}
- 期间涨跌: {change:+.2f}%
- 最高/最低: ¥{df['high'].max():.2f} / ¥{df['low'].min():.2f}
- 数据范围: {df.iloc[0]['date']} -> {latest['date']}

### 最近 15 个交易日详细数据 (OHLCV):
{history_str}
"""



class SentimentToolkit(Toolkit):
    """
    情绪分析工具包 - 包装 SentimentTools 为 Agno Toolkit
    
    提供文本情绪分析功能（支持 BERT 和 LLM 模式）
    """
    
    def __init__(self, db: DatabaseManager, mode: str = "auto", **kwargs):
        self._sentiment_tools = SentimentTools(db, mode=mode)
        self._db = db
        
        tools = [
            self.analyze_sentiment,
            self.batch_update_sentiment,
        ]
        super().__init__(name="sentiment_toolkit", tools=tools, **kwargs)

    def analyze_sentiment(self, text: str) -> str:
        """
        分析文本的情绪极性。
        
        Args:
            text: 需要分析的文本内容，如新闻标题或摘要。
        
        Returns:
            情绪分析结果，包含分值(-1.0到1.0)和标签(positive/negative/neutral)。
        """
        result = self._sentiment_tools.analyze_sentiment(text)
        
        score = result.get('score', 0.0)
        label = result.get('label', 'neutral')
        reason = result.get('reason', '')
        
        return f"""情绪分析结果:
- 文本: {text[:100]}{'...' if len(text) > 100 else ''}
- 分值: {score:.2f}
- 标签: {label}
- 分析: {reason}"""

    def batch_update_sentiment(self, source: str = None, limit: int = 20) -> str:
        """
        批量更新数据库中新闻的情绪分数。
        
        Args:
            source: 筛选特定新闻源（如 "cls", "wallstreetcn"），为空则处理所有。
            limit: 最多处理的新闻数量，默认 20 条。
        
        Returns:
            更新结果的描述。
        """
        logger.info(f"🔧 [TOOL CALLED] batch_update_sentiment(source={source}, limit={limit})")
        
        count = self._sentiment_tools.batch_update_news_sentiment(source=source, limit=limit)
        
        return f"✅ 已更新 {count} 条新闻的情绪分数"



class SearchToolkit(Toolkit):
    """
    搜索工具包 - 包装 SearchTools 为 Agno Toolkit
    
    提供网络搜索功能（支持 Jina、DuckDuckGo 和百度）
    
    当环境变量 JINA_API_KEY 设置时，默认使用 Jina Search，
    提供 LLM 友好的搜索结果。
    """
    
    def __init__(self, db: DatabaseManager, **kwargs):
        self._search_tools = SearchTools(db)
        
        tools = [
            self.web_search,
            self.aggregate_search,
        ]
        super().__init__(name="search_toolkit", tools=tools, **kwargs)

    def web_search(self, query: str, engine: str = None, max_results: int = 5) -> str:
        """
        使用指定搜索引擎执行网络搜索。

        Args:
            query: 搜索关键词，如 "英伟达财报" 或 "光伏行业政策"。
            engine: 搜索引擎选择。可选值:
                    "youcom" (You.com Search，需配置 YOUCOM_API_KEY),
                    "jina" (Jina Search，需配置 JINA_API_KEY，LLM友好输出),
                    "ddg" (DuckDuckGo，推荐英文/国际搜索),
                    "baidu" (百度，推荐中文/国内搜索)。
                    默认: 若配置了 JINA_API_KEY 则使用 "jina"，否则 "ddg"。
            max_results: 返回结果数量。默认 5。

        Returns:
            搜索结果的文本描述。
        """
        return self._search_tools.search(query, engine=engine, max_results=max_results)

    def aggregate_search(self, query: str, max_results: int = 5) -> str:
        """
        同时使用多个搜索引擎搜索并聚合结果。
        
        Args:
            query: 搜索关键词。
            max_results: 每个引擎返回的最大结果数。默认 5。
        
        Returns:
            聚合后的搜索结果。
        """
        return self._search_tools.aggregate_search(query, max_results=max_results)


class YoucomResearchToolkit(Toolkit):
    """
    You.com 深度研究工具包 - 包装 YoucomResearchEngine 为 Agno Toolkit

    提供深度研究功能，返回带引用的高质量综述答案。
    适用于复杂金融问题需要综合多方信息的深度分析场景。
    """

    def __init__(self, **kwargs):
        self._research_engine = YoucomResearchEngine()

        tools = [
            self.deep_research,
        ]
        super().__init__(name="youcom_research_toolkit", tools=tools, **kwargs)

    def deep_research(self, query: str, research_effort: str = "standard") -> str:
        """
        使用 You.com Research API 进行深度研究，返回带引用的高质量综述答案。

        适用于复杂金融问题需要综合多方信息来源的场景，
        如行业趋势分析、政策影响评估、竞争格局研究等。
        对于简单的事实查询，建议使用 web_search 工具。

        Args:
            query: 研究问题，如 "光伏行业2024年供需格局变化及投资机会" 或 " GLP-1 药物对胰岛素替代市场的长期影响"。
            research_effort: 研究深度，可选值:
                    "lite" (快速概览),
                    "standard" (标准深度，默认),
                    "deep" (深度分析),
                    "exhaustive" (穷尽式研究)。
                    默认: "standard"。

        Returns:
            深度研究报告，包含综述内容和引用来源列表。
        """
        logger.info(f"🔧 [TOOL CALLED] deep_research(query={query[:50]}..., effort={research_effort})")

        result = self._research_engine.research(query, research_effort=research_effort)

        content = result.get("content", "")
        sources = result.get("sources", [])

        if not content:
            return "⚠️ You.com Research 返回了空结果，可能是 API Key 未配置或查询失败。"

        output = f"## You.com 深度研究报告\n\n"
        output += f"**研究问题:** {query}\n"
        output += f"**研究深度:** {research_effort}\n\n"
        output += f"### 综述答案\n\n{content}\n\n"
        output += f"### 引用来源 (共 {len(sources)} 条)\n\n"
        for i, source in enumerate(sources, 1):
            title = source.get("title", "未命名来源")
            url = source.get("url", "")
            snippet = source.get("snippet", "")
            output += f"{i}. **{title}**"
            if url:
                output += f" — {url}"
            output += f"\n"
            if snippet:
                output += f"   > {snippet[:200]}{'...' if len(snippet) > 200 else ''}\n"
            output += "\n"

        logger.info(f"✅ [TOOL SUCCESS] You.com Research returned {len(sources)} sources")
        return output


class ContextSearchToolkit(Toolkit):
    """
    上下文搜索工具包 - 用于 RAG 场景的文档片段检索
    
    支持在内存中存储文档片段，并通过关键词搜索相关内容。
    适用于 ReportAgent 的分段编辑场景。
    """
    
    def __init__(self, **kwargs):
        self._store = {}  # {doc_id: {"title": str, "content": str, "summary": str}}
        
        tools = [
            self.search_context,
            self.get_toc,
        ]
        super().__init__(name="context_search_toolkit", tools=tools, **kwargs)
    
    def add_document(self, doc_id: str, title: str, content: str, summary: str = ""):
        """添加文档到存储（供外部调用，非 LLM 工具）"""
        self._store[doc_id] = {
            "title": title,
            "content": content,
            "summary": summary or content[:200] + "..."
        }
        logger.info(f"📄 Added document to context store: {doc_id} - {title[:30]}...")
    
    def clear(self):
        """清空文档存储"""
        self._store.clear()
        logger.info("🗑️ Context store cleared")
    
    def search_context(self, query: str, max_results: int = 3) -> str:
        """
        在已存储的文档中搜索与查询相关的内容片段。
        
        Args:
            query: 搜索关键词，如 "消费板块" 或 "茅台 预测"。
            max_results: 返回的最大结果数，默认 3。
        
        Returns:
            匹配的文档片段，按相关性排序。
        """
        logger.info(f"🔍 [TOOL CALLED] search_context(query={query}, max_results={max_results})")
        
        if not self._store:
            return "⚠️ 上下文存储为空，无可搜索内容。"
        
        # 简单的关键词匹配 + 计分
        query_terms = query.lower().split()
        results = []
        
        for doc_id, doc in self._store.items():
            score = 0
            content_lower = doc["content"].lower()
            title_lower = doc["title"].lower()
            
            for term in query_terms:
                # 标题匹配权重更高
                if term in title_lower:
                    score += 3
                if term in content_lower:
                    score += content_lower.count(term)
            
            if score > 0:
                results.append((score, doc_id, doc))
        
        # 按分数排序
        results.sort(key=lambda x: x[0], reverse=True)
        results = results[:max_results]
        
        if not results:
            return f"未找到与 '{query}' 相关的内容。"
        
        output = f"## 搜索结果 (查询: {query})\n\n"
        for score, doc_id, doc in results:
            output += f"### [{doc_id}] {doc['title']}\n"
            # 返回摘要而非全文，节省 token
            output += f"{doc['summary']}\n\n"
        
        logger.info(f"✅ [TOOL SUCCESS] Found {len(results)} matching documents")
        return output
    
    def get_toc(self) -> str:
        """
        获取当前存储的所有文档的目录（TOC）。
        
        Returns:
            文档目录列表，包含 ID 和标题。
        """
        logger.info("🔍 [TOOL CALLED] get_toc()")
        
        if not self._store:
            return "⚠️ 上下文存储为空。"
        
        output = "## 文档目录 (TOC)\n\n"
        for doc_id, doc in self._store.items():
            output += f"- **[{doc_id}]** {doc['title']}\n"
        
        return output

