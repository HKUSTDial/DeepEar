"""
AlphaEar Dashboard - 简化版服务端
只保留真实 Agent 模式，支持历史记录和 Query 跟踪
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from loguru import logger

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from dotenv import load_dotenv
load_dotenv()

from .models import RunRequest, RunResponse, DashboardRun, DashboardStep, HistoryItem, QueryGroup
from .db import get_db
from utils.database_manager import DatabaseManager
from utils.news_tools import NewsNowTools



# ============ 全局状态管理 ============
class RunState:
    """当前运行状态"""
    def __init__(self):
        self.current_run_id: Optional[str] = None
        self.status: str = "idle"
        self.phase: str = ""
        self.progress: int = 0
        self.output: Optional[str] = None  # 报告文件路径
        self.report_structured: Optional[dict] = None
        self.connections: List[WebSocket] = []
        
        # 缓存数据（用于 WebSocket 推送）
        self.signals: List[Dict] = []
        self.charts: Dict[str, Dict] = {}
        self.transmission_graph: Dict = {}
    
    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        dead_connections = []
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except:
                dead_connections.append(ws)
        
        # 清理断开的连接
        for ws in dead_connections:
            if ws in self.connections:
                self.connections.remove(ws)
    
    def reset(self, run_id: str):
        self.current_run_id = run_id
        self.status = "running"
        self.phase = "初始化"
        self.progress = 0
        self.output = None
        self.report_structured = None
        self.signals = []
        self.charts = {}
        self.transmission_graph = {}

run_state = RunState()

_news_db: Optional[DatabaseManager] = None
_news_tools: Optional[NewsNowTools] = None


def get_news_tools() -> NewsNowTools:
    global _news_db, _news_tools
    if _news_tools is None:
        _news_db = DatabaseManager()
        _news_tools = NewsNowTools(_news_db)
    return _news_tools

# ... (FastAPI setup omitted in replace context if not changing) ...


# ============ FastAPI App ============
async def lifespan(app: FastAPI):
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║   AlphaEar Dashboard - Real Agent Mode                    ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  🌐 Dashboard: http://localhost:8765                      ║
    ║  📡 WebSocket: ws://localhost:8765/ws                     ║
    ║  📚 API Docs:  http://localhost:8765/docs                 ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    yield
    print("👋 Dashboard shutting down")


app = FastAPI(title="AlphaEar Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ WebSocket ============
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    run_state.connections.append(websocket)
    db = get_db()
    
    # 发送初始状态
    running_task = db.get_running_task()
    if running_task:
        steps = db.get_steps(running_task.run_id, limit=100)
        # Filter out charts without valid prices to prevent frontend crashes
        valid_charts = {
            k: v for k, v in run_state.charts.items()
            if v and isinstance(v.get("prices"), list) and len(v.get("prices", [])) > 0
        }
        await websocket.send_json({
            "type": "init",
            "data": {
                "run_id": running_task.run_id,
                "status": running_task.status,
                "query": running_task.query,
                "steps": [s.model_dump() for s in steps],
                "signals": run_state.signals,
                "charts": valid_charts,
                "graph": run_state.transmission_graph
            }
        })
    else:
        await websocket.send_json({
            "type": "init",
            "data": {
                "run_id": None,
                "status": "idle",
                "query": None,
                "steps": [],
                "signals": [],
                "charts": {},
                "graph": {}
            }
        })
    
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            # 处理客户端命令
            if msg.get("command") == "get_history":
                history = db.get_history(limit=50)
                await websocket.send_json({
                    "type": "history",
                    "data": [h.model_dump() for h in history]
                })
            
            elif msg.get("command") == "get_query_groups":
                groups = db.get_query_groups(limit=20)
                await websocket.send_json({
                    "type": "query_groups",
                    "data": [g.model_dump() for g in groups]
                })
            
            elif msg.get("command") == "get_run_details":
                run_id = msg.get("run_id")
                if run_id:
                    run = db.get_run(run_id)
                    steps = db.get_steps(run_id)
                    await websocket.send_json({
                        "type": "run_details",
                        "data": {
                            "run": run.model_dump() if run else None,
                            "steps": [s.model_dump() for s in steps]
                        }
                    })
            
            elif msg.get("command") == "get_status":
                # 返回当前运行状态，用于页面刷新后同步
                from .integration import workflow_runner
                
                # 步骤需要从数据库获取
                steps_data = []
                if run_state.current_run_id:
                    steps = db.get_steps(run_state.current_run_id)
                    steps_data = [s.model_dump() for s in steps]
                
                # Filter out charts without valid prices
                valid_charts = {
                    k: v for k, v in run_state.charts.items()
                    if v and isinstance(v.get("prices"), list) and len(v.get("prices", [])) > 0
                }
                
                await websocket.send_json({
                    "type": "init",
                    "data": {
                        "run_id": run_state.current_run_id,
                        "status": run_state.status,
                        "phase": run_state.phase,
                        "progress": run_state.progress,
                        "steps": steps_data,
                        "signals": run_state.signals,
                        "charts": valid_charts,
                        "graph": run_state.transmission_graph,
                        "is_running": workflow_runner.is_running()
                    }
                })
    
    except WebSocketDisconnect:
        if websocket in run_state.connections:
            run_state.connections.remove(websocket)


# ============ REST API ============
@app.post("/api/run", response_model=RunResponse)
async def start_run(request: RunRequest):
    """启动新的分析任务"""
    db = get_db()
    
    # 检查是否有正在运行的任务 (双重检查: 内存状态 + 数据库)
    if run_state.status == "running":
        raise HTTPException(400, f"已有任务正在运行: {run_state.run_id}")
    
    # 清理数据库中的僵尸运行记录 (服务器重启后遗留的 running 状态)
    stale_running = db.get_running_task()
    if stale_running:
        logger.warning(f"⚠️ Found stale running task {stale_running.run_id}, marking as failed")
        db.update_run(stale_running.run_id, status="failed")
    
    # 创建新运行记录
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    sources_value = request.sources
    if isinstance(sources_value, list):
        sources_list = sources_value
        sources_text = ",".join(sources_value)
    else:
        sources_text = sources_value or "financial"
        sources_list = [s.strip() for s in sources_text.split(",") if s.strip()]

    run = DashboardRun(
        run_id=run_id,
        query=request.query,
        sources=sources_text,
        status="running",
        started_at=datetime.now().isoformat()
    )
    if request.query:
        latest = db.get_latest_run_by_query(request.query)
        if latest and latest.run_id != run_id:
            run.parent_run_id = latest.run_id
    db.create_run(run)
    
    # 重置状态
    run_state.reset(run_id)
    
    # 启动工作流
    asyncio.create_task(execute_workflow(run_id, request))
    
    return RunResponse(run_id=run_id, status="started", query=request.query)


@app.get("/api/status")
async def get_status():
    """获取当前状态"""
    from .integration import workflow_runner
    return {
        "run_id": run_state.current_run_id,
        "status": run_state.status,
        "phase": run_state.phase,
        "progress": run_state.progress,
        "signal_count": len(run_state.signals),
        "chart_count": len(run_state.charts),
        "is_running": workflow_runner.is_running(),
        "is_cancelled": workflow_runner.is_cancelled()
    }


@app.post("/api/run/cancel")
async def cancel_run():
    """取消当前运行的工作流"""
    from .integration import workflow_runner
    
    # 检查实际工作流状态
    if workflow_runner.is_running():
        if workflow_runner.cancel():
            run_state.status = "cancelling"
            await run_state.broadcast({
                "type": "status",
                "data": {"status": "cancelling", "message": "正在取消..."}
            })
            return {"success": True, "message": "已发送取消请求"}
        return {"success": False, "message": "取消失败"}
    
    # 工作流未运行，但前端状态可能过期 - 重置状态
    if run_state.status == "running":
        logger.warning("⚠️ Frontend state was stale (running), resetting to idle")
        run_state.status = "idle"
        await run_state.broadcast({
            "type": "status", 
            "data": {"status": "idle", "message": "状态已重置"}
        })
        return {"success": True, "message": "状态已重置（无运行中任务）"}
    
    return {"success": False, "message": "没有正在运行的任务"}


@app.get("/api/history", response_model=List[HistoryItem])
async def get_history(limit: int = 50):
    """获取历史运行列表"""
    db = get_db()
    return db.get_history(limit=limit)


@app.get("/api/query-groups", response_model=List[QueryGroup])
async def get_query_groups(limit: int = 20):
    """按 Query 分组获取历史"""
    db = get_db()
    return db.get_query_groups(limit=limit)


@app.get("/api/hot-news")
async def get_hot_news(sources: str = "cls,wallstreetcn,xueqiu", count: int = 8):
    """获取热点新闻（结构化）"""
    tools = get_news_tools()
    source_list = [s.strip() for s in sources.split(",") if s.strip()]
    data = []
    for src in source_list:
        items = tools.fetch_hot_news(src, count=count, fetch_content=False)
        data.append({
            "source": src,
            "source_name": tools.SOURCES.get(src, src),
            "items": items
        })
    return {
        "updated_at": datetime.now().isoformat(),
        "sources": data
    }


@app.get("/api/run/{run_id}")
async def get_run(run_id: str):
    """获取运行详情"""
    db = get_db()
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    
    steps = db.get_steps(run_id)
    return {
        "run": run.model_dump(),
        "steps": [s.model_dump() for s in steps]
    }


@app.get("/api/run/{run_id}/data")
async def get_run_data(run_id: str):
    """获取运行的结构化数据 (signals, charts, graph)"""
    db = get_db()
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    
    data = db.get_run_data(run_id)
    result = data or {
        "signals": [],
        "charts": {},
        "graph": {}
    }

    # Load structured report from checkpoint if not in DB
    if "report_structured" not in result:
        try:
            from utils.checkpointing import CheckpointManager
            ckpt = CheckpointManager("reports/checkpoints", run_id)
            if ckpt.exists("report_structured.json"):
                result["report_structured"] = ckpt.load_json("report_structured.json")
        except Exception as e:
            logger.warning(f"Failed to load report_structured for {run_id}: {e}")
    
    # Filter out charts without valid prices to prevent frontend crashes
    if "charts" in result and isinstance(result["charts"], dict):
        valid_charts = {
            k: v for k, v in result["charts"].items()
            if v and isinstance(v.get("prices"), list) and len(v.get("prices", [])) > 0
        }
        result["charts"] = valid_charts
    
    # Read report content if available
    report_content = None
    report_path = run.report_path
    if report_path:
        report_file = Path(report_path)
        if not report_file.is_absolute():
            report_file = Path(__file__).parent.parent / report_file
        if report_file.exists():
            try:
                with open(report_file, "r", encoding="utf-8") as f:
                    report_content = f.read()
            except Exception as e:
                logger.error(f"Failed to read report file {report_file}: {e}")
            
    result["report_content"] = report_content
    result["report_path"] = report_path
    
    return {
        "run_id": run_id,
        **result
    }

@app.delete("/api/run/{run_id}")
async def delete_run(run_id: str, confirm: bool = False):
    """删除运行记录"""
    if not confirm:
        raise HTTPException(400, "请确认删除操作 (confirm=true)")
    
    db = get_db()
    if db.delete_run(run_id):
        return {"message": f"已删除运行记录: {run_id}"}
    raise HTTPException(404, "运行记录不存在")


@app.post("/api/run/{run_id}/rerun")
async def rerun(run_id: str):
    """重新运行相同的查询"""
    db = get_db()
    old_run = db.get_run(run_id)
    if not old_run:
        raise HTTPException(404, "运行记录不存在")
    
    # 使用相同参数创建新任务
    request = RunRequest(
        query=old_run.query,
        sources=old_run.sources
    )
    return await start_run(request)


@app.post("/api/run/{run_id}/update")
async def update_run_endpoint(run_id: str, request: RunRequest):
    """
    更新运行记录：基于旧 Run + 新行情生成新报告
    request.query 可用于传递附加指令
    """
    db = get_db()
    
    # Check current running state
    if run_state.status == "running":
        raise HTTPException(400, "已有任务正在运行，请稍候")

    old_run = db.get_run(run_id)
    if not old_run:
        raise HTTPException(404, "运行记录不存在")
    
    # Create placeholder run entry (actual ID created by workflow, but let's pre-announce)
    # Actually workflow.update_run creates the new ID.
    # To conform to UI expectations, we might want to return the 'future' ID or just start it.
    # But integration logic makes it tricky to know ID upfront.
    # Simplified approach: We let the workflow create it, and UI listens to WebSocket for 'init' or 'connected'.
    # HOWEVER, run_state needs an ID to broadcast correctly.
    
    # Generate the REAL ID here to ensure alignment
    new_run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_state.reset(new_run_id)

    # Create run record upfront so UI/DB can track status
    new_run = DashboardRun(
        run_id=new_run_id,
        query=old_run.query,
        sources=old_run.sources,
        status="running",
        started_at=datetime.now().isoformat(),
        parent_run_id=run_id
    )
    db.create_run(new_run)
    
    asyncio.create_task(execute_update_workflow(run_id, request.query, new_run_id))
    return {"message": "Update started", "base_run_id": run_id, "run_id": new_run_id}

async def execute_update_workflow(base_run_id: str, user_query: Optional[str], new_run_id: str):
    """Execute update logic"""
    from .integration import dashboard_callback, workflow_runner
    db = get_db()
    loop = asyncio.get_event_loop()
    
    async def async_broadcast(message: dict):
        msg_type = message.get("type")
        data = message.get("data", {})

        if msg_type == "progress":
            run_state.phase = data.get("phase", "")
            run_state.progress = data.get("progress", 0)
        elif msg_type == "step":
            # Save steps to DB for update runs
            step = DashboardStep(
                run_id=new_run_id,
                step_type=data.get("type", ""),
                agent=data.get("agent", ""),
                content=data.get("content", ""),
                timestamp=data.get("timestamp", datetime.now().isoformat())
            )
            db.add_step(step)

        await run_state.broadcast(message)

    dashboard_callback.enable(async_broadcast, loop)
    
    try:
        run_state.status = "running"
        workflow_runner.update_run_async(
            base_run_id, 
            run_state=run_state, 
            user_query=user_query, 
            new_run_id=new_run_id
        )
        
        while workflow_runner.is_running():
            await asyncio.sleep(0.5)
            
        # Post-processing: Sync the newly created run to SQLite
        try:
            from utils.checkpointing import CheckpointManager
            ckpt = CheckpointManager("reports/checkpoints", new_run_id)
            state = ckpt.load_json("state.json") if ckpt.exists("state.json") else {}

            # Load updated signals from checkpoint
            analyzed_signals = ckpt.load_json("analyzed_signals.json") if ckpt.exists("analyzed_signals.json") else []

            # Fallback to base run data if needed
            base_data = db.get_run_data(base_run_id) or {}
            signals = analyzed_signals or base_data.get("signals", [])

            # Rebuild charts with latest prices when possible
            charts: Dict[str, Dict] = dict(base_data.get("charts", {}) or {})
            try:
                workflow = workflow_runner._ensure_workflow()
                stock_tools = workflow.trend_agent.stock_toolkit._stock_tools
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
                updated_tickers = set()
                for signal in signals:
                    for item in signal.get("impact_tickers", []) or []:
                        if isinstance(item, dict):
                            ticker_code = item.get("ticker")
                            ticker_name = item.get("name")
                        else:
                            ticker_code = str(item)
                            ticker_name = str(item)
                        if not ticker_code or ticker_code in updated_tickers:
                            continue
                        try:
                            df = stock_tools.get_stock_price(ticker_code, start_date, end_date)
                            if df is not None and not df.empty:
                                chart_data = workflow_runner._format_chart_from_df(
                                    ticker_code,
                                    ticker_name or ticker_code,
                                    df,
                                    news_text=signal.get("summary") or signal.get("title", ""),
                                    prediction_logic=signal.get("summary")
                                )
                                charts[ticker_code] = chart_data
                                updated_tickers.add(ticker_code)
                        except Exception as e:
                            logger.warning(f"Chart refresh failed for {ticker_code}: {e}")
            except Exception as e:
                logger.warning(f"Chart rebuild skipped: {e}")

            structured = None
            if ckpt.exists("report_structured.json"):
                structured = ckpt.load_json("report_structured.json")

            run_data = {
                "signals": signals,
                "charts": charts,
                "graph": base_data.get("graph", {}),
                "report_structured": structured
            }
            db.save_run_data(new_run_id, run_data)

            db.update_run(
                new_run_id,
                status=state.get("status", "completed"),
                finished_at=state.get("finished_at"),
                report_path=state.get("output"),
                signal_count=len(signals)
            )

            run_state.output = state.get("output")
            run_state.status = "completed"
            await run_state.broadcast({
                "type": "completed",
                "data": {"run_id": new_run_id, "parent_run_id": base_run_id}
            })
            logger.info(f"✅ Synced updated run {new_run_id} to DB")
        except Exception as e:
            logger.error(f"Failed to sync update to DB: {e}")
        
    except Exception as e:
        run_state.status = "failed"
        await run_state.broadcast({"type": "error", "data": {"message": str(e)}})
    finally:
        dashboard_callback.disable()
        if run_state.status == "running":
            run_state.status = "idle"


# ============ 工作流执行 ============
async def execute_workflow(run_id: str, request: RunRequest):
    """执行真实的 AlphaEar 工作流"""
    from .integration import dashboard_callback, workflow_runner
    
    db = get_db()
    loop = asyncio.get_event_loop()
    
    async def async_broadcast(message: dict):
        """处理回调消息并广播"""
        msg_type = message.get("type")
        data = message.get("data", {})
        
        if msg_type == "progress":
            run_state.phase = data.get("phase", "")
            run_state.progress = data.get("progress", 0)
        
        elif msg_type == "step":
            # 保存到数据库
            step = DashboardStep(
                run_id=run_id,
                step_type=data.get("type", ""),
                agent=data.get("agent", ""),
                content=data.get("content", ""),
                timestamp=data.get("timestamp", datetime.now().isoformat())
            )
            db.add_step(step)
        
        elif msg_type == "signal":
            run_state.signals.append(data)
        
        elif msg_type == "chart":
            ticker = data.get("ticker")
            if ticker:
                run_state.charts[ticker] = data
        
        elif msg_type == "graph":
            run_state.transmission_graph = data
        
        # 广播到所有客户端
        await run_state.broadcast(message)
    
    # 启用回调
    dashboard_callback.enable(async_broadcast, loop)
    
    try:
        run_state.status = "running"
        
        # 在后台线程启动工作流
        sources_value = request.sources
        if isinstance(sources_value, list):
            sources_list = sources_value
        else:
            sources_text = sources_value or "financial"
            sources_list = [s.strip() for s in sources_text.split(",") if s.strip()]
        
        workflow_runner.run_async(
            query=request.query,
            sources=sources_list,
            wide=request.wide,
            depth=request.depth,
            run_state=run_state
        )
        
        # 等待工作流完成
        while workflow_runner.is_running():
            await asyncio.sleep(0.5)
        
        # 更新数据库
        db.update_run(
            run_id,
            status="completed",
            finished_at=datetime.now().isoformat(),
            signal_count=len(run_state.signals),
            report_path=run_state.output
        )
        
        # 保存结构化数据 (用于交互式渲染和对比)
        logger.info(f"📊 Saving run data: {len(run_state.signals)} signals, {len(run_state.charts)} charts")
        run_data = {
            "signals": run_state.signals,
            "charts": run_state.charts,
            "graph": run_state.transmission_graph,
            "report_structured": run_state.report_structured
        }
        db.save_run_data(run_id, run_data)
        
        run_state.status = "completed"
        
        # 广播完成
        await run_state.broadcast({
            "type": "completed",
            "data": {
                "run_id": run_id,
                "signal_count": len(run_state.signals)
            }
        })
        
    except Exception as e:
        db.update_run(
            run_id,
            status="failed",
            finished_at=datetime.now().isoformat(),
            error_message=str(e)
        )
        run_state.status = "failed"
        
        await run_state.broadcast({
            "type": "error",
            "data": {"message": str(e)}
        })
    
    finally:
        dashboard_callback.disable()


# ============ 静态文件服务 ============
# React 构建产物
frontend_dist = Path(__file__).parent / "frontend" / "dist"
reports_dir = Path("reports")
if reports_dir.exists():
    app.mount("/reports", StaticFiles(directory=reports_dir), name="reports")

if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")
    
    @app.get("/")
    async def serve_frontend():
        return FileResponse(frontend_dist / "index.html")
    
    @app.get("/{path:path}")
    async def serve_frontend_routes(path: str):
        # 处理 React Router 路由
        file_path = frontend_dist / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")
else:
    @app.get("/")
    async def no_frontend():
        return {
            "message": "前端未构建",
            "hint": "请运行: cd dashboard/frontend && npm run build"
        }


# ============ 入口 ============
if __name__ == "__main__":
    uvicorn.run(
        "dashboard.server:app",
        host="0.0.0.0",
        port=8765,
        reload=True
    )
