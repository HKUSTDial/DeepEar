import os
import time
import json
import requests
import threading
from typing import List, Dict, Optional
from loguru import logger


class YoucomSearchEngine:
    """You.com Search API 封装 - 使用 ydc-index.io/v1/search"""

    YOUCOM_SEARCH_URL = "https://ydc-index.io/v1/search"

    _rate_limit_no_key = 10
    _rate_window = 60.0
    _min_interval = 2.0
    _request_times = []
    _last_request_time = 0.0
    _lock = threading.Lock()

    def __init__(self):
        self.api_key = os.getenv("YOUCOM_API_KEY", "").strip()
        self.has_api_key = bool(self.api_key)
        if self.has_api_key:
            logger.info("✅ You.com Search API key configured")
        else:
            logger.warning("⚠️ You.com API key not set (YOUCOM_API_KEY env var empty)")

    @classmethod
    def _wait_for_rate_limit(cls) -> None:
        time.sleep(0.3)

        with cls._lock:
            current_time = time.time()
            cls._request_times = [t for t in cls._request_times if current_time - t < cls._rate_window]

            if len(cls._request_times) >= cls._rate_limit_no_key:
                oldest = cls._request_times[0]
                wait_time = cls._rate_window - (current_time - oldest) + 1.0
                if wait_time > 0:
                    logger.warning(f"⏳ You.com Search rate limit, waiting {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    current_time = time.time()
                    cls._request_times = [t for t in cls._request_times if current_time - t < cls._rate_window]

            time_since_last = current_time - cls._last_request_time
            if time_since_last < cls._min_interval:
                time.sleep(cls._min_interval - time_since_last)

            cls._request_times.append(time.time())
            cls._last_request_time = time.time()

    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        使用 You.com Search API 执行搜索。

        Args:
            query: 搜索关键词
            max_results: 返回结果数量，默认 10

        Returns:
            搜索结果列表，每个结果包含 title, url, content
        """
        if not query:
            return []

        logger.info(f"🔍 You.com Search: {query}")

        if not self.has_api_key:
            logger.error("YOUCOM_API_KEY not configured, cannot search")
            return []

        self._wait_for_rate_limit()

        headers = {
            "Accept": "application/json",
            "X-API-Key": self.api_key,
        }

        try:
            payload = {"query": query, "count": max_results}
            response = requests.post(
                self.YOUCOM_SEARCH_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code == 429:
                logger.warning("⚠️ You.com Search rate limited (429), waiting 30s...")
                time.sleep(30)
                return self.search(query, max_results)

            if response.status_code == 401:
                logger.error("You.com API key is invalid or expired")
                return []

            if response.status_code == 403:
                logger.error("You.com API key lacks required permissions")
                return []

            if response.status_code != 200:
                logger.warning(f"You.com Search failed (Status {response.status_code})")
                return []

            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.error("You.com Search returned non-JSON response")
                return []

            results = []
            web_results = data.get("results", {}).get("web", [])
            if not web_results:
                web_results = data.get("results", [])

            for i, item in enumerate(web_results[:max_results]):
                snippet = ""
                snippets = item.get("snippets", [])
                if snippets and isinstance(snippets, list):
                    snippet = snippets[0]
                if not snippet:
                    snippet = item.get("description", "")

                results.append({
                    "title": item.get("title", f"Result {i + 1}"),
                    "url": item.get("url", ""),
                    "href": item.get("url", ""),
                    "content": snippet,
                    "body": snippet,
                })

            logger.info(f"✅ You.com Search returned {len(results)} results")
            return results

        except requests.exceptions.Timeout:
            logger.error("You.com Search timeout")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"You.com Search request error: {e}")
            return []
        except Exception as e:
            logger.error(f"You.com Search unexpected error: {e}")
            return []


class YoucomResearchEngine:
    """You.com Research API 封装 - 使用 ydc-index.io/v1/research"""

    YOUCOM_RESEARCH_URL = "https://ydc-index.io/v1/research"

    _lock = threading.Lock()

    def __init__(self):
        self.api_key = os.getenv("YOUCOM_API_KEY", "").strip()
        self.has_api_key = bool(self.api_key)
        if self.has_api_key:
            logger.info("✅ You.com Research API key configured")
        else:
            logger.warning("⚠️ You.com API key not set (YOUCOM_API_KEY env var empty)")

    def research(self, query: str, research_effort: str = "standard") -> Dict:
        """
        使用 You.com Research API 执行深度研究。

        Args:
            query: 研究问题
            research_effort: 研究深度，可选 lite/standard/deep/exhaustive，默认 standard

        Returns:
            包含 content (markdown综述) 和 sources (引用列表) 的字典
        """
        if not query:
            return {"content": "", "sources": []}

        logger.info(f"🔬 You.com Research: {query} (effort={research_effort})")

        if not self.has_api_key:
            logger.error("YOUCOM_API_KEY not configured, cannot research")
            return {"content": "", "sources": []}

        allowed_efforts = {"lite", "standard", "deep", "exhaustive"}
        if research_effort not in allowed_efforts:
            logger.warning(f"Unsupported research_effort '{research_effort}', falling back to standard")
            research_effort = "standard"

        headers = {
            "Accept": "application/json",
            "X-API-Key": self.api_key,
        }

        try:
            payload = {"input": query, "research_effort": research_effort}
            response = requests.post(
                self.YOUCOM_RESEARCH_URL,
                headers=headers,
                json=payload,
                timeout=120,
            )

            if response.status_code == 429:
                logger.warning("⚠️ You.com Research rate limited (429)")
                return {"content": "", "sources": []}

            if response.status_code == 401:
                logger.error("You.com API key is invalid or expired")
                return {"content": "", "sources": []}

            if response.status_code == 403:
                logger.error("You.com API key lacks required permissions")
                return {"content": "", "sources": []}

            if response.status_code != 200:
                logger.warning(f"You.com Research failed (Status {response.status_code})")
                return {"content": "", "sources": []}

            data = response.json()
            content = data.get("content", "")
            sources = []

            for source in data.get("sources", []):
                snippets = source.get("snippets", [])
                if isinstance(snippets, list) and snippets:
                    snippet = snippets[0]
                else:
                    snippet = ""
                sources.append({
                    "url": source.get("url", ""),
                    "title": source.get("title", ""),
                    "snippet": snippet,
                })

            char_count = len(content) if content else 0
            logger.info(f"✅ You.com Research returned {char_count} chars, {len(sources)} sources")
            return {"content": content, "sources": sources}

        except requests.exceptions.Timeout:
            logger.error("You.com Research timeout")
            return {"content": "", "sources": []}
        except requests.exceptions.RequestException as e:
            logger.error(f"You.com Research request error: {e}")
            return {"content": "", "sources": []}
        except Exception as e:
            logger.error(f"You.com Research unexpected error: {e}")
            return {"content": "", "sources": []}
