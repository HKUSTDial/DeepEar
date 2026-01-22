import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { Signal, ChartData } from '../store'
import { KLineChart } from './KLineChart'
import { GitCompare, TrendingUp, Plus, X, RefreshCw, ArrowRight } from 'lucide-react'
import './ComparisonView.css'

interface RunData {
    run_id: string
    signals: Signal[]
    charts: Record<string, ChartData>
    graph: { nodes: any[]; edges: any[] }
}

interface Props {
    oldRun: RunData
    newRun: RunData
}

interface SignalDelta {
    signal: Signal
    oldSignal?: Signal
    sentiment_delta?: number
    confidence_delta?: number
    intensity_delta?: number
    status: 'new' | 'removed' | 'changed' | 'unchanged'
}

export function ComparisonView({ oldRun, newRun }: Props) {
    const graphRef = useRef<HTMLDivElement>(null)
    const graphInstance = useRef<echarts.ECharts | null>(null)

    // 计算信号变化
    const signalDeltas: SignalDelta[] = []

    // Match signals by title or signal_id
    const oldSignalMap = new Map(oldRun.signals.map(s => [s.title, s]))
    const newSignalMap = new Map(newRun.signals.map(s => [s.title, s]))

    // New or changed signals
    newRun.signals.forEach(newSig => {
        const oldSig = oldSignalMap.get(newSig.title)
        if (!oldSig) {
            signalDeltas.push({ signal: newSig, status: 'new' })
        } else {
            const sentimentDelta = newSig.sentiment_score - oldSig.sentiment_score
            const confidenceDelta = newSig.confidence - oldSig.confidence
            const intensityDelta = newSig.intensity - oldSig.intensity
            const hasChange = Math.abs(sentimentDelta) > 0.01 ||
                Math.abs(confidenceDelta) > 0.01 ||
                Math.abs(intensityDelta) > 0
            signalDeltas.push({
                signal: newSig,
                oldSignal: oldSig,
                sentiment_delta: sentimentDelta,
                confidence_delta: confidenceDelta,
                intensity_delta: intensityDelta,
                status: hasChange ? 'changed' : 'unchanged'
            })
        }
    })

    // Removed signals
    oldRun.signals.forEach(oldSig => {
        if (!newSignalMap.has(oldSig.title)) {
            signalDeltas.push({ signal: oldSig, status: 'removed' })
        }
    })

    // 找出共同的 ticker
    const allTickers = new Set([
        ...Object.keys(oldRun.charts),
        ...Object.keys(newRun.charts)
    ])

    // 渲染传导图对比
    useEffect(() => {
        if (!graphRef.current) return

        if (!graphInstance.current) {
            graphInstance.current = echarts.init(graphRef.current, 'dark')
        }

        const chart = graphInstance.current

        // 合并新旧图节点，标记变化
        const oldNodeIds = new Set(oldRun.graph?.nodes?.map(n => n.id) || [])
        const newNodeIds = new Set(newRun.graph?.nodes?.map(n => n.id) || [])

        const combinedNodes = (newRun.graph?.nodes || []).map(n => ({
            ...n,
            name: n.label,
            symbolSize: 50,
            itemStyle: {
                color: oldNodeIds.has(n.id) ? '#4fc3f7' : '#81c784' // 蓝=已有, 绿=新增
            }
        }))

        // 标记已删除节点
        oldRun.graph?.nodes?.forEach(n => {
            if (!newNodeIds.has(n.id)) {
                combinedNodes.push({
                    ...n,
                    name: n.label + ' (已移除)',
                    symbolSize: 40,
                    itemStyle: { color: '#ef5350' }
                })
            }
        })

        const option: echarts.EChartsOption = {
            backgroundColor: 'transparent',
            title: {
                text: '传导图变化',
                left: 'center',
                textStyle: { color: '#e1e4e8' }
            },
            tooltip: {},
            legend: {
                data: ['保持', '新增', '移除'],
                bottom: 10,
                textStyle: { color: '#8b949e' }
            },
            series: [{
                type: 'graph',
                layout: 'force',
                data: combinedNodes,
                links: (newRun.graph?.edges || []).map(e => ({
                    source: e.from,
                    target: e.to,
                    label: { show: true, formatter: e.label }
                })),
                roam: true,
                label: { show: true, position: 'bottom' },
                force: { repulsion: 200 }
            }]
        }

        chart.setOption(option)

        return () => {
            chart.dispose()
            graphInstance.current = null
        }
    }, [oldRun, newRun])

    return (
        <div className="comparison-view">
            <div className="comparison-header">
                <h2><GitCompare size={18} style={{ marginRight: 8 }} />对比分析</h2>
                <div className="run-labels">
                    <span className="old-run">基准: {oldRun.run_id}</span>
                    <ArrowRight size={14} className="arrow" />
                    <span className="new-run">更新: {newRun.run_id}</span>
                </div>
            </div>

            <div className="signal-comparison-list">
                {signalDeltas.map((delta, i) => {
                    const isNew = delta.status === 'new'
                    const isRemoved = delta.status === 'removed'
                    const isUnchanged = delta.status === 'unchanged'
                    const oldReasoning = delta.oldSignal?.reasoning || '无基准逻辑'
                    const newReasoning = delta.signal.reasoning

                    // Filter relevant tickers for this signal
                    const signalTickers = new Set(delta.signal.impact_tickers.map(t => String(t.ticker)))
                    const relevantTickers = Array.from(allTickers).filter(t => signalTickers.has(String(t)))

                    return (
                        <div key={i} className={`signal-comparison-card ${delta.status}`}>
                            {/* 1. 信号标题栏 */}
                            <div className="card-header">
                                <div className="card-title-row">
                                    <div className="title-text">{delta.signal.title}</div>
                                    <div className={`status-badge ${delta.status}`}>
                                        {isNew && <><Plus size={12} /> 新增</>}
                                        {isRemoved && <><X size={12} /> 移除</>}
                                        {delta.status === 'changed' && <><RefreshCw size={12} /> 演变</>}
                                        {isUnchanged && '逻辑维持'}
                                    </div>
                                </div>
                                <div className="card-metrics-row">
                                    {/* 简单显示情绪变化 */}
                                    <span className={`metric-tag ${delta.sentiment_delta! > 0 ? 'up' : delta.sentiment_delta! < 0 ? 'down' : ''}`}>
                                        情绪: {delta.signal.sentiment_score.toFixed(2)}
                                        {!isNew && !isRemoved && Math.abs(delta.sentiment_delta!) > 0.01 && (
                                            <span className="delta-val"> ({delta.sentiment_delta! > 0 ? '+' : ''}{delta.sentiment_delta!.toFixed(2)})</span>
                                        )}
                                    </span>
                                    <span className="metric-tag">
                                        置信度: {(delta.signal.confidence * 100).toFixed(0)}%
                                    </span>
                                </div>
                            </div>

                            {/* 2. 逻辑演变对比 */}
                            <div className="logic-evolution-block">
                                <div className="logic-column old">
                                    <div className="col-header">
                                        <div className="col-title">基准逻辑</div>
                                    </div>
                                    <div className="text-content">
                                        {delta.oldSignal ? oldReasoning : <span className="placeholder">--</span>}
                                    </div>
                                </div>
                                <div className="logic-divider">
                                    <ArrowRight size={16} />
                                </div>
                                <div className="logic-column new">
                                    <div className="col-header">
                                        <div className="col-title">{isRemoved ? '失效状态' : '最新追踪'}</div>
                                    </div>
                                    <div className="text-content">
                                        {isRemoved ? <span className="placeholder">逻辑已失效/移除</span> : newReasoning}
                                    </div>
                                </div>
                            </div>

                            {/* 3. 引用新闻源 (News Sources) */}
                            {delta.signal.sources && delta.signal.sources.length > 0 && (
                                <div className="signal-sources">
                                    <div className="sources-label">相关资讯追踪:</div>
                                    <div className="sources-list">
                                        {delta.signal.sources.map((s, idx) => (
                                            <a key={idx} href={s.url} target="_blank" rel="noopener noreferrer" className="source-link">
                                                {s.source_name}: {s.title}
                                            </a>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* 4. 相关 K线图 (Embedded) */}
                            {relevantTickers.length > 0 && (
                                <div className="signal-charts-section">
                                    <div className="section-title">
                                        <TrendingUp size={14} /> 市场验证 ({relevantTickers.length})
                                    </div>
                                    <div className="signal-charts-grid">
                                        {relevantTickers.map(ticker => {
                                            const oldChart = oldRun.charts[ticker]
                                            const newChart = newRun.charts[ticker]

                                            // Y-Axis Sync Logic
                                            const getMinMax = (chart?: ChartData) => {
                                                if (!chart?.prices?.length) return null
                                                let min = Infinity, max = -Infinity
                                                const updateMinMax = (p: { low: number, high: number }) => {
                                                    if (p.low < min) min = p.low
                                                    if (p.high > max) max = p.high
                                                }
                                                chart.prices.forEach(updateMinMax)
                                                chart.forecast?.forEach(updateMinMax)
                                                chart.forecast_base?.forEach(updateMinMax)
                                                return [min, max]
                                            }
                                            const oldRange = getMinMax(oldChart)
                                            const newRange = getMinMax(newChart)
                                            let yMin: number | undefined, yMax: number | undefined

                                            if (oldRange || newRange) {
                                                const minVal = Math.min(oldRange ? oldRange[0] : Infinity, newRange ? newRange[0] : Infinity)
                                                const maxVal = Math.max(oldRange ? oldRange[1] : -Infinity, newRange ? newRange[1] : -Infinity)
                                                const padding = (maxVal - minVal) * 0.1
                                                yMin = Math.floor(minVal - padding)
                                                yMax = Math.ceil(maxVal + padding)
                                            }

                                            return (
                                                <div key={ticker} className="embedded-chart-pair">
                                                    <div className="chart-wrapper old">
                                                        <div className="chart-tag">基准</div>
                                                        {oldChart?.prices?.length ? (
                                                            <KLineChart data={oldChart} yMin={yMin} yMax={yMax} group={`g-${ticker}-${i}`} />
                                                        ) : <div className="no-data">无数据</div>}
                                                    </div>
                                                    <div className="chart-wrapper new">
                                                        <div className="chart-tag">追踪</div>
                                                        {newChart?.prices?.length ? (
                                                            <KLineChart data={newChart} yMin={yMin} yMax={yMax} group={`g-${ticker}-${i}`} />
                                                        ) : <div className="no-data">无数据</div>}
                                                    </div>
                                                </div>
                                            )
                                        })}
                                    </div>
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
