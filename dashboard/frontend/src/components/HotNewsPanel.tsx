import { useEffect, useState } from 'react'
import { Flame, RefreshCw, Sparkles } from 'lucide-react'
import './HotNewsPanel.css'

interface HotNewsItem {
    id: string
    source: string
    rank: number
    title: string
    url: string
    publish_time?: string
}

interface HotNewsSourceGroup {
    source: string
    source_name: string
    items: HotNewsItem[]
}

interface HotNewsResponse {
    updated_at: string
    sources: HotNewsSourceGroup[]
}

interface Props {
    onPickQuery: (query: string) => void
}

const SOURCE_OPTIONS = [
    { id: 'all', name: '全部' },
    { id: 'cls', name: '财联社' },
    { id: 'wallstreetcn', name: '华尔街见闻' },
    { id: 'xueqiu', name: '雪球' },
    { id: 'eastmoney', name: '东方财富' },
    { id: 'yicai', name: '第一财经' }
]

const API_BASE = import.meta.env.DEV ? 'http://localhost:8765' : ''

export function HotNewsPanel({ onPickQuery }: Props) {
    const [activeSource, setActiveSource] = useState('all')
    const [loading, setLoading] = useState(false)
    const [data, setData] = useState<HotNewsResponse | null>(null)
    const [error, setError] = useState<string | null>(null)

    const fetchHotNews = async (sourceId: string = activeSource) => {
        try {
            setLoading(true)
            setError(null)
            const sourcesParam = sourceId === 'all'
                ? SOURCE_OPTIONS.filter(s => s.id !== 'all').map(s => s.id).join(',')
                : sourceId
            const res = await fetch(`${API_BASE}/api/hot-news?sources=${encodeURIComponent(sourcesParam)}&count=8`)
            if (!res.ok) {
                throw new Error('热点获取失败')
            }
            const json = await res.json()
            setData(json)
        } catch (e) {
            setError((e as Error).message || '热点获取失败')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchHotNews('all')
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const handleSourceClick = (sourceId: string) => {
        setActiveSource(sourceId)
        fetchHotNews(sourceId)
    }

    return (
        <div className="hot-news-panel">
            <div className="hot-news-header">
                <div className="hot-news-title">
                    <Flame size={14} /> 热点新闻
                </div>
                <button
                    className="hot-news-refresh"
                    onClick={() => fetchHotNews(activeSource)}
                    disabled={loading}
                    title="刷新"
                >
                    <RefreshCw size={14} className={loading ? 'spin' : ''} />
                </button>
            </div>

            <div className="hot-news-sources">
                {SOURCE_OPTIONS.map((s) => (
                    <button
                        key={s.id}
                        className={`source-chip ${activeSource === s.id ? 'active' : ''}`}
                        onClick={() => handleSourceClick(s.id)}
                    >
                        {s.name}
                    </button>
                ))}
            </div>

            <div className="hot-news-body">
                {loading ? (
                    <div className="hot-news-empty">加载中...</div>
                ) : error ? (
                    <div className="hot-news-empty">{error}</div>
                ) : !data || data.sources.length === 0 ? (
                    <div className="hot-news-empty">暂无热点</div>
                ) : (
                    data.sources.map((group) => (
                        <div key={group.source} className="hot-news-group">
                            <div className="group-title">{group.source_name}</div>
                            <div className="hot-news-list">
                                {group.items.map((item) => (
                                    <div key={item.id} className="hot-news-item">
                                        <a
                                            href={item.url}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="item-title"
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            {item.rank}. {item.title}
                                        </a>
                                        <button
                                            className="item-pick"
                                            onClick={() => onPickQuery(item.title)}
                                            title="生成查询"
                                        >
                                            <Sparkles size={12} /> 生成
                                        </button>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    )
}
