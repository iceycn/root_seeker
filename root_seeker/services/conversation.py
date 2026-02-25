"""
对话历史管理：用于多轮对话模式
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConversationHistory:
    """管理多轮对话的历史记录"""

    messages: list[dict[str, str]] = field(default_factory=list)

    def add_user_message(self, content: str) -> None:
        """添加用户消息"""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        """添加助手消息"""
        self.messages.append({"role": "assistant", "content": content})

    def to_api_format(self, system: str) -> list[dict[str, str]]:
        """转换为 API 格式（包含 system message）"""
        return [{"role": "system", "content": system}] + self.messages

    def get_last_assistant_message(self) -> str | None:
        """获取最后一条助手消息"""
        for msg in reversed(self.messages):
            if msg.get("role") == "assistant":
                return msg.get("content")
        return None

    def get_last_user_message(self) -> str | None:
        """获取最后一条用户消息"""
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                return msg.get("content")
        return None

    def clear(self) -> None:
        """清空对话历史"""
        self.messages.clear()

    def __len__(self) -> int:
        return len(self.messages)
