"""
Dashboard Router - Statistics and monitoring endpoints

Provides centralized dashboard APIs for monitoring system-wide statistics.
"""

import traceback
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from server.routers.auth_router import get_admin_user
from server.utils.auth_middleware import get_db
from src.storage.conversation import ConversationManager
from src.storage.db.models import User
from src.utils.logging_config import logger


dashboard = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# =============================================================================
# Response Models
# =============================================================================


class UserActivityStats(BaseModel):
    """用户活跃度统计"""

    total_users: int
    active_users_24h: int
    active_users_30d: int
    daily_active_users: list[dict]  # 最近7天每日活跃用户


class ToolCallStats(BaseModel):
    """工具调用统计"""

    total_calls: int
    successful_calls: int
    failed_calls: int
    success_rate: float
    most_used_tools: list[dict]
    tool_error_distribution: dict
    daily_tool_calls: list[dict]  # 最近7天每日工具调用数


class KnowledgeStats(BaseModel):
    """知识库统计"""

    total_databases: int
    total_files: int
    total_nodes: int
    total_storage_size: int  # 字节
    databases_by_type: dict
    file_type_distribution: dict


class AgentAnalytics(BaseModel):
    """AI智能体分析"""

    total_agents: int
    agent_conversation_counts: list[dict]
    agent_satisfaction_rates: list[dict]
    agent_tool_usage: list[dict]
    top_performing_agents: list[dict]


class ConversationListItem(BaseModel):
    """Conversation list item"""

    thread_id: str
    user_id: str
    agent_id: str
    title: str
    status: str
    message_count: int
    created_at: str
    updated_at: str


class ConversationDetailResponse(BaseModel):
    """Conversation detail"""

    thread_id: str
    user_id: str
    agent_id: str
    title: str
    status: str
    message_count: int
    created_at: str
    updated_at: str
    total_tokens: int
    messages: list[dict]


# =============================================================================
# Conversation Management
# =============================================================================


@dashboard.get("/conversations", response_model=list[ConversationListItem])
async def get_all_conversations(
    user_id: str | None = None,
    agent_id: str | None = None,
    status: str = "active",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Get all conversations (Admin only)"""
    from src.storage.db.models import Conversation, ConversationStats

    try:
        # Build query
        query = db.query(Conversation, ConversationStats).outerjoin(
            ConversationStats, Conversation.id == ConversationStats.conversation_id
        )

        # Apply filters
        if user_id:
            query = query.filter(Conversation.user_id == user_id)
        if agent_id:
            query = query.filter(Conversation.agent_id == agent_id)
        if status != "all":
            query = query.filter(Conversation.status == status)

        # Order and paginate
        query = query.order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)

        results = query.all()

        return [
            {
                "thread_id": conv.thread_id,
                "user_id": conv.user_id,
                "agent_id": conv.agent_id,
                "title": conv.title,
                "status": conv.status,
                "message_count": stats.message_count if stats else 0,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
            }
            for conv, stats in results
        ]
    except Exception as e:
        logger.error(f"Error getting conversations: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get conversations: {str(e)}")


@dashboard.get("/conversations/{thread_id}", response_model=ConversationDetailResponse)
async def get_conversation_detail(
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Get conversation detail (Admin only)"""
    try:
        conv_manager = ConversationManager(db)
        conversation = conv_manager.get_conversation_by_thread_id(thread_id)

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get messages and stats
        messages = conv_manager.get_messages(conversation.id)
        stats = conv_manager.get_stats(conversation.id)

        # Format messages
        message_list = []
        for msg in messages:
            msg_dict = {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "message_type": msg.message_type,
                "created_at": msg.created_at.isoformat(),
            }

            # Include tool calls if present
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "tool_name": tc.tool_name,
                        "tool_input": tc.tool_input,
                        "tool_output": tc.tool_output,
                        "status": tc.status,
                    }
                    for tc in msg.tool_calls
                ]

            message_list.append(msg_dict)

        return {
            "thread_id": conversation.thread_id,
            "user_id": conversation.user_id,
            "agent_id": conversation.agent_id,
            "title": conversation.title,
            "status": conversation.status,
            "message_count": stats.message_count if stats else len(message_list),
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "total_tokens": stats.total_tokens if stats else 0,
            "messages": message_list,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation detail: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get conversation detail: {str(e)}")


# =============================================================================
# User Activity Statistics
# =============================================================================


@dashboard.get("/stats/users", response_model=UserActivityStats)
async def get_user_activity_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Get user activity statistics (Admin only)"""
    try:
        from src.storage.db.models import User, Conversation

        now = datetime.utcnow()

        # 基础用户统计
        total_users = db.query(func.count(User.id)).scalar() or 0

        # 不同时间段的活跃用户数（基于对话活动）
        active_users_24h = (
            db.query(func.count(distinct(Conversation.user_id)))
            .filter(Conversation.updated_at >= now - timedelta(days=1))
            .scalar()
            or 0
        )

        active_users_30d = (
            db.query(func.count(distinct(Conversation.user_id)))
            .filter(Conversation.updated_at >= now - timedelta(days=30))
            .scalar()
            or 0
        )
        # 最近7天每日活跃用户
        daily_active_users = []
        for i in range(7):
            day_start = now - timedelta(days=i + 1)
            day_end = now - timedelta(days=i)

            active_count = (
                db.query(func.count(distinct(Conversation.user_id)))
                .filter(Conversation.updated_at >= day_start, Conversation.updated_at < day_end)
                .scalar()
                or 0
            )

            daily_active_users.append({"date": day_start.strftime("%Y-%m-%d"), "active_users": active_count})

        return UserActivityStats(
            total_users=total_users,
            active_users_24h=active_users_24h,
            active_users_30d=active_users_30d,
            daily_active_users=list(reversed(daily_active_users)),  # 按时间正序
        )

    except Exception as e:
        logger.error(f"Error getting user activity stats: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get user activity stats: {str(e)}")


# =============================================================================
# Tool Call Statistics
# =============================================================================


@dashboard.get("/stats/tools", response_model=ToolCallStats)
async def get_tool_call_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Get tool call statistics (Admin only)"""
    try:
        from src.storage.db.models import ToolCall

        now = datetime.utcnow()

        # 基础工具调用统计
        total_calls = db.query(func.count(ToolCall.id)).scalar() or 0
        successful_calls = db.query(func.count(ToolCall.id)).filter(ToolCall.status == "success").scalar() or 0
        failed_calls = total_calls - successful_calls
        success_rate = round((successful_calls / total_calls * 100), 2) if total_calls > 0 else 0

        # 最常用工具
        most_used_tools = (
            db.query(ToolCall.tool_name, func.count(ToolCall.id).label("count"))
            .group_by(ToolCall.tool_name)
            .order_by(func.count(ToolCall.id).desc())
            .limit(10)
            .all()
        )
        most_used_tools = [{"tool_name": name, "count": count} for name, count in most_used_tools]

        # 工具错误分布
        tool_errors = (
            db.query(ToolCall.tool_name, func.count(ToolCall.id).label("error_count"))
            .filter(ToolCall.status == "error")
            .group_by(ToolCall.tool_name)
            .all()
        )
        tool_error_distribution = {name: count for name, count in tool_errors}

        # 最近7天每日工具调用数
        daily_tool_calls = []
        for i in range(7):
            day_start = now - timedelta(days=i + 1)
            day_end = now - timedelta(days=i)

            daily_count = (
                db.query(func.count(ToolCall.id))
                .filter(ToolCall.created_at >= day_start, ToolCall.created_at < day_end)
                .scalar()
                or 0
            )

            daily_tool_calls.append({"date": day_start.strftime("%Y-%m-%d"), "call_count": daily_count})

        return ToolCallStats(
            total_calls=total_calls,
            successful_calls=successful_calls,
            failed_calls=failed_calls,
            success_rate=success_rate,
            most_used_tools=most_used_tools,
            tool_error_distribution=tool_error_distribution,
            daily_tool_calls=list(reversed(daily_tool_calls)),
        )

    except Exception as e:
        logger.error(f"Error getting tool call stats: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get tool call stats: {str(e)}")


# =============================================================================
# Knowledge Base Statistics
# =============================================================================


@dashboard.get("/stats/knowledge", response_model=KnowledgeStats)
async def get_knowledge_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Get knowledge base statistics (Admin only)"""
    try:
        from src.knowledge.manager import KnowledgeBaseManager
        import json
        import os

        # 从知识库管理系统获取数据
        kb_manager = KnowledgeBaseManager(work_dir="/app/saves/knowledge_base_data")

        # 读取全局元数据文件
        metadata_file = "/app/saves/knowledge_base_data/global_metadata.json"
        if os.path.exists(metadata_file):
            with open(metadata_file, encoding="utf-8") as f:
                global_metadata = json.load(f)

            databases = global_metadata.get("databases", {})
            total_databases = len(databases)

            # 统计不同类型的知识库
            databases_by_type = {}
            files_by_type = {}
            total_files = 0
            total_nodes = 0
            total_storage_size = 0

            # 文件类型映射到中文友好名称
            file_type_mapping = {
                "txt": "文本文件",
                "pdf": "PDF文档",
                "docx": "Word文档",
                "doc": "Word文档",
                "md": "Markdown",
                "html": "HTML网页",
                "htm": "HTML网页",
                "json": "JSON数据",
                "csv": "CSV表格",
                "xlsx": "Excel表格",
                "xls": "Excel表格",
                "pptx": "PowerPoint",
                "ppt": "PowerPoint",
                "png": "PNG图片",
                "jpg": "JPEG图片",
                "jpeg": "JPEG图片",
                "gif": "GIF图片",
                "svg": "SVG图片",
                "mp4": "MP4视频",
                "mp3": "MP3音频",
                "zip": "ZIP压缩包",
                "rar": "RAR压缩包",
                "7z": "7Z压缩包",
            }

            # 统计文件：改为基于各知识库实现中的 files_meta，更加准确
            # 注意：部分记录可能来源于 URL，此时无法统计物理大小
            for kb_instance in kb_manager.kb_instances.values():
                files_meta = getattr(kb_instance, "files_meta", {}) or {}
                total_files += len(files_meta)

                for _fid, finfo in files_meta.items():
                    file_ext = (finfo.get("file_type") or "").lower()
                    # 统一映射显示名
                    display_name = file_type_mapping.get(file_ext, file_ext.upper() + "文件" if file_ext else "其他")
                    files_by_type[display_name] = files_by_type.get(display_name, 0) + 1

                    # 估算大小（如果路径存在且是本地文件）
                    path = finfo.get("path") or ""
                    try:
                        if path and os.path.exists(path) and os.path.isfile(path):
                            total_storage_size += os.path.getsize(path)
                    except Exception:
                        # 忽略无法访问的路径
                        pass

            # 统计知识库类型分布
            for kb_id, kb_info in databases.items():
                kb_type = kb_info.get("kb_type", "unknown")
                display_type = {
                    "lightrag": "LightRAG",
                    "chroma": "Chroma",
                    "faiss": "FAISS",
                    "milvus": "Milvus",
                    "qdrant": "Qdrant",
                    "elasticsearch": "Elasticsearch",
                    "unknown": "未知类型",
                }.get(kb_type.lower(), kb_type)
                databases_by_type[display_type] = databases_by_type.get(display_type, 0) + 1

                # 尝试从各个知识库系统获取更详细的统计
                try:
                    kb_instance = kb_manager.get_kb(kb_id)
                    if kb_instance and hasattr(kb_instance, "get_stats"):
                        stats = kb_instance.get_stats()
                        total_nodes += stats.get("node_count", 0)
                except Exception as e:
                    logger.warning(f"Failed to get stats for KB {kb_id}: {e}")
                    continue

        else:
            # 如果没有元数据文件，返回空数据
            total_databases = 0
            total_files = 0
            total_nodes = 0
            total_storage_size = 0
            databases_by_type = {}
            files_by_type = {}

        return KnowledgeStats(
            total_databases=total_databases,
            total_files=total_files,
            total_nodes=total_nodes,
            total_storage_size=total_storage_size,
            databases_by_type=databases_by_type,
            file_type_distribution=files_by_type,  # 保持API兼容，但使用新的数据
        )

    except Exception as e:
        logger.error(f"Error getting knowledge stats: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get knowledge stats: {str(e)}")


# =============================================================================
# Agent Analytics
# =============================================================================


@dashboard.get("/stats/agents", response_model=AgentAnalytics)
async def get_agent_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Get AI agent analytics (Admin only)"""
    try:
        from src.storage.db.models import Conversation, MessageFeedback, Message, ToolCall

        # 获取所有智能体
        agents = (
            db.query(Conversation.agent_id, func.count(Conversation.id).label("conversation_count"))
            .group_by(Conversation.agent_id)
            .all()
        )

        total_agents = len(agents)
        agent_conversation_counts = [{"agent_id": agent_id, "conversation_count": count} for agent_id, count in agents]

        # 智能体满意度统计
        agent_satisfaction = []
        for agent_id, _ in agents:
            total_feedbacks = (
                db.query(func.count(MessageFeedback.id))
                .join(Message, MessageFeedback.message_id == Message.id)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .filter(Conversation.agent_id == agent_id)
                .scalar()
                or 0
            )

            positive_feedbacks = (
                db.query(func.count(MessageFeedback.id))
                .join(Message, MessageFeedback.message_id == Message.id)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .filter(Conversation.agent_id == agent_id, MessageFeedback.rating == "like")
                .scalar()
                or 0
            )

            satisfaction_rate = round((positive_feedbacks / total_feedbacks * 100), 2) if total_feedbacks > 0 else 0

            agent_satisfaction.append(
                {"agent_id": agent_id, "satisfaction_rate": satisfaction_rate, "total_feedbacks": total_feedbacks}
            )

        # 智能体工具使用统计
        agent_tool_usage = []
        for agent_id, _ in agents:
            tool_usage_count = (
                db.query(func.count(ToolCall.id))
                .join(Message, ToolCall.message_id == Message.id)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .filter(Conversation.agent_id == agent_id)
                .scalar()
                or 0
            )

            agent_tool_usage.append({"agent_id": agent_id, "tool_usage_count": tool_usage_count})

        # 表现最佳的智能体（综合评分）
        top_performing_agents = []
        for i, (agent_id, conv_count) in enumerate(agents):
            # 综合评分 = 对话数权重 + 满意度权重
            satisfaction_data = next(
                (s for s in agent_satisfaction if s["agent_id"] == agent_id), {"satisfaction_rate": 0}
            )

            score = conv_count * 0.3 + satisfaction_data["satisfaction_rate"] * 0.7

            top_performing_agents.append(
                {
                    "agent_id": agent_id,
                    "score": round(score, 2),
                    "conversation_count": conv_count,
                    "satisfaction_rate": satisfaction_data["satisfaction_rate"],
                }
            )

        # 按评分排序，取前5名
        top_performing_agents.sort(key=lambda x: x["score"], reverse=True)
        top_performing_agents = top_performing_agents[:5]

        return AgentAnalytics(
            total_agents=total_agents,
            agent_conversation_counts=agent_conversation_counts,
            agent_satisfaction_rates=agent_satisfaction,
            agent_tool_usage=agent_tool_usage,
            top_performing_agents=top_performing_agents,
        )

    except Exception as e:
        logger.error(f"Error getting agent analytics: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get agent analytics: {str(e)}")


# =============================================================================
# Basic Statistics (保留原有接口)
# =============================================================================


@dashboard.get("/stats")
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Get dashboard statistics (Admin only)"""
    from src.storage.db.models import Conversation, Message, MessageFeedback

    try:
        # Basic counts
        total_conversations = db.query(func.count(Conversation.id)).scalar() or 0
        active_conversations = (
            db.query(func.count(Conversation.id)).filter(Conversation.status == "active").scalar() or 0
        )
        total_messages = db.query(func.count(Message.id)).scalar() or 0
        total_users = db.query(func.count(User.id)).scalar() or 0

        # Feedback statistics
        total_feedbacks = db.query(func.count(MessageFeedback.id)).scalar() or 0
        like_count = db.query(func.count(MessageFeedback.id)).filter(MessageFeedback.rating == "like").scalar() or 0

        # Calculate satisfaction rate
        satisfaction_rate = round((like_count / total_feedbacks * 100), 2) if total_feedbacks > 0 else 0

        return {
            "total_conversations": total_conversations,
            "active_conversations": active_conversations,
            "total_messages": total_messages,
            "total_users": total_users,
            "feedback_stats": {
                "total_feedbacks": total_feedbacks,
                "satisfaction_rate": satisfaction_rate,
            },
        }
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard stats: {str(e)}")


# =============================================================================
# Feedback Management
# =============================================================================


class FeedbackListItem(BaseModel):
    """Feedback list item"""

    id: int
    user_id: str
    username: str | None
    avatar: str | None
    rating: str
    reason: str | None
    created_at: str
    message_content: str
    conversation_title: str | None
    agent_id: str


@dashboard.get("/feedbacks", response_model=list[FeedbackListItem])
async def get_all_feedbacks(
    rating: str | None = None,
    agent_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Get all feedback records (Admin only)"""
    from src.storage.db.models import MessageFeedback, Message, Conversation, User

    try:
        # Build query with joins including User table
        # Try both User.id and User.user_id as MessageFeedback.user_id might be stored as either
        query = (
            db.query(MessageFeedback, Message, Conversation, User)
            .join(Message, MessageFeedback.message_id == Message.id)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .outerjoin(User, (MessageFeedback.user_id == User.id) | (MessageFeedback.user_id == User.user_id))
        )

        # Apply filters
        if rating and rating in ["like", "dislike"]:
            query = query.filter(MessageFeedback.rating == rating)
        if agent_id:
            query = query.filter(Conversation.agent_id == agent_id)

        # Order by creation time (most recent first)
        query = query.order_by(MessageFeedback.created_at.desc())

        results = query.all()

        # Debug logging (privacy-safe)
        logger.info(f"Found {len(results)} feedback records")
        # Removed sensitive user data from logs for privacy compliance

        return [
            {
                "id": feedback.id,
                "message_id": feedback.message_id,
                "user_id": feedback.user_id,
                "username": user.username if user else None,
                "avatar": user.avatar if user else None,
                "rating": feedback.rating,
                "reason": feedback.reason,
                "created_at": feedback.created_at.isoformat(),
                "message_content": message.content[:100] + ("..." if len(message.content) > 100 else ""),
                "conversation_title": conversation.title,
                "agent_id": conversation.agent_id,
            }
            for feedback, message, conversation, user in results
        ]
    except Exception as e:
        logger.error(f"Error getting feedbacks: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get feedbacks: {str(e)}")


# =============================================================================
# Time Series Statistics for Call Analytics
# =============================================================================


class TimeSeriesStats(BaseModel):
    """时间序列统计数据"""

    data: list[dict]  # [{"date": "2024-01-01", "data": {"item1": 50, "item2": 30}, "total": 80}, ...]
    categories: list[str]  # 所有类别名称
    total_count: int
    average_count: float
    peak_count: int
    peak_date: str


@dashboard.get("/stats/calls/timeseries", response_model=TimeSeriesStats)
async def get_call_timeseries_stats(
    type: str = "models",  # models/agents/tokens/tools
    time_range: str = "7days",  # 7hours/7days/7weeks
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Get time series statistics for call analytics (Admin only)"""
    try:
        from src.storage.db.models import Conversation, Message, ToolCall

        # 计算时间范围（使用北京时间 UTC+8）
        now = datetime.utcnow()

        if time_range == "7hours":
            intervals = 7
            # 包含当前小时：从6小时前开始
            start_time = now - timedelta(hours=intervals - 1)
            # SQLite compatible approach: 使用datetime函数转换UTC时间为北京时间
            group_format = func.strftime("%Y-%m-%d %H:00", func.datetime(Message.created_at, "+8 hours"))
        elif time_range == "7weeks":
            intervals = 7
            # 包含当前周：从6周前开始
            start_time = now - timedelta(weeks=intervals - 1)
            # SQLite compatible approach: 使用datetime函数转换UTC时间为北京时间
            group_format = func.strftime("%Y-%W", func.datetime(Message.created_at, "+8 hours"))
        else:  # 7days (default)
            intervals = 7
            # 包含当前天：从6天前开始
            start_time = now - timedelta(days=intervals - 1)
            # SQLite compatible approach: 使用datetime函数转换UTC时间为北京时间
            group_format = func.strftime("%Y-%m-%d", func.datetime(Message.created_at, "+8 hours"))

        # 根据类型查询数据
        if type == "models":
            # 模型调用统计（基于消息数量，按模型分组）
            # 从message的extra_metadata中提取模型信息
            query = (
                db.query(
                    group_format.label("date"),
                    func.count(Message.id).label("count"),
                    func.json_extract(Message.extra_metadata, "$.response_metadata.model_name").label("category"),
                )
                .filter(Message.role == "assistant", Message.created_at >= start_time)
                .filter(Message.extra_metadata.isnot(None))
                .group_by(group_format, func.json_extract(Message.extra_metadata, "$.response_metadata.model_name"))
                .order_by(group_format)
            )
        elif type == "agents":
            # 智能体调用统计（基于对话数量，按智能体分组）
            # 为对话创建独立的时间格式化器
            if time_range == "7hours":
                conv_group_format = func.strftime("%Y-%m-%d %H:00", func.datetime(Conversation.created_at, "+8 hours"))
            elif time_range == "7weeks":
                conv_group_format = func.strftime("%Y-%W", func.datetime(Conversation.created_at, "+8 hours"))
            else:  # 7days
                conv_group_format = func.strftime("%Y-%m-%d", func.datetime(Conversation.created_at, "+8 hours"))

            query = (
                db.query(
                    conv_group_format.label("date"),
                    func.count(Conversation.id).label("count"),
                    Conversation.agent_id.label("category"),
                )
                .filter(Conversation.created_at >= start_time)
                .group_by(conv_group_format, Conversation.agent_id)
                .order_by(conv_group_format)
            )
        elif type == "tokens":
            # Token消耗统计（区分input/output tokens）
            # 先查询input tokens
            from sqlalchemy import literal

            input_query = (
                db.query(
                    group_format.label("date"),
                    func.sum(
                        func.coalesce(func.json_extract(Message.extra_metadata, "$.usage_metadata.input_tokens"), 0)
                    ).label("count"),
                    literal("input_tokens").label("category"),
                )
                .filter(
                    Message.created_at >= start_time,
                    Message.extra_metadata.isnot(None),
                    func.json_extract(Message.extra_metadata, "$.usage_metadata").isnot(None),
                )
                .group_by(group_format)
                .order_by(group_format)
            )

            # 查询output tokens
            output_query = (
                db.query(
                    group_format.label("date"),
                    func.sum(
                        func.coalesce(func.json_extract(Message.extra_metadata, "$.usage_metadata.output_tokens"), 0)
                    ).label("count"),
                    literal("output_tokens").label("category"),
                )
                .filter(
                    Message.created_at >= start_time,
                    Message.extra_metadata.isnot(None),
                    func.json_extract(Message.extra_metadata, "$.usage_metadata").isnot(None),
                )
                .group_by(group_format)
                .order_by(group_format)
            )

            # 合并两个查询结果
            input_results = input_query.all()
            output_results = output_query.all()
            results = input_results + output_results
        elif type == "tools":
            # 工具调用统计（按工具名称分组）
            # 为工具调用创建独立的时间格式化器
            if time_range == "7hours":
                tool_group_format = func.strftime("%Y-%m-%d %H:00", func.datetime(ToolCall.created_at, "+8 hours"))
            elif time_range == "7weeks":
                tool_group_format = func.strftime("%Y-%W", func.datetime(ToolCall.created_at, "+8 hours"))
            else:  # 7days
                tool_group_format = func.strftime("%Y-%m-%d", func.datetime(ToolCall.created_at, "+8 hours"))

            query = (
                db.query(
                    tool_group_format.label("date"),
                    func.count(ToolCall.id).label("count"),
                    ToolCall.tool_name.label("category"),
                )
                .filter(ToolCall.created_at >= start_time)
                .group_by(tool_group_format, ToolCall.tool_name)
                .order_by(tool_group_format)
            )
        else:
            raise HTTPException(status_code=422, detail=f"Invalid type: {type}")

        if type != "tokens":
            results = query.all()

        # 处理堆叠数据格式
        # 首先收集所有类别
        categories = set()
        for result in results:
            if hasattr(result, "category") and result.category:
                categories.add(result.category)

        # 如果没有类别数据，提供默认类别
        if not categories:
            if type == "models":
                categories.add("unknown_model")
            elif type == "agents":
                categories.add("unknown_agent")
            elif type == "tokens":
                categories.update(["input_tokens", "output_tokens"])
            elif type == "tools":
                categories.add("unknown_tool")

        categories = sorted(list(categories))

        # 重新组织数据：按时间点分组每个类别的数据
        time_data = {}
        for result in results:
            date_key = result.date
            category = getattr(result, "category", "unknown")
            count = result.count

            if date_key not in time_data:
                time_data[date_key] = {}

            time_data[date_key][category] = count

        # 填充缺失的时间点（使用北京时间）
        data = []
        # 从start_time开始，转换为北京时间
        current_time = start_time + timedelta(hours=8)

        if time_range == "7hours":
            delta = timedelta(hours=1)
        elif time_range == "7weeks":
            delta = timedelta(weeks=1)
        else:
            delta = timedelta(days=1)

        for i in range(intervals):
            if time_range == "7hours":
                date_key = current_time.strftime("%Y-%m-%d %H:00")
            elif time_range == "7weeks":
                # 计算ISO周数
                week_num = current_time.isocalendar()[1]
                date_key = f"{current_time.year}-{week_num:02d}"
            else:
                date_key = current_time.strftime("%Y-%m-%d")

            # 获取该时间点的数据
            day_data = time_data.get(date_key, {})
            day_total = sum(day_data.values())

            # 确保所有类别都有值（缺失的补0）
            for category in categories:
                if category not in day_data:
                    day_data[category] = 0

            data.append({"date": date_key, "data": day_data, "total": day_total})
            current_time += delta

        # 计算统计指标
        if type == "tools":
            # 对于工具调用，显示所有时间的总数（与ToolStatsComponent保持一致）
            from src.storage.db.models import ToolCall

            total_count = db.query(func.count(ToolCall.id)).scalar() or 0
        else:
            # 其他类型使用时间序列数据的总和
            total_count = sum(item["total"] for item in data)

        average_count = round(total_count / intervals, 2) if intervals > 0 else 0
        peak_data = max(data, key=lambda x: x["total"]) if data else {"total": 0, "date": ""}

        return TimeSeriesStats(
            data=data,
            categories=categories,
            total_count=total_count,
            average_count=average_count,
            peak_count=peak_data["total"],
            peak_date=peak_data["date"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting call timeseries stats: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get call timeseries stats: {str(e)}")
